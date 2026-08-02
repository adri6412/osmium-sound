#!/usr/bin/env python3
"""HiFi Player — build one backup generation.

Two entry points, one code path:

    hifi-backup-run.py /run/hifi-backup-job.json   (from sources_server.py, via
                                                    systemd-run, user-triggered)
    hifi-backup-run.py --scheduled                 (from hifi-backup.timer)

Progress goes to /run/hifi-backup-status.json in the same shape as the disk
format and CD rip jobs, so the UI polls it with the machinery it already has.

Building a backup is deliberately NOT a job that stops services. Whole-system
backup tools have to quiesce the box because they copy live databases blind;
here each format that cannot be copied safely has a proper snapshot path in
hifi_backup.py (SQLite backup API, YAML re-parse), so music keeps playing while
this runs. Restore is the operation that stops things — and that one is
user-initiated and handled by sources_server.py.

The generation directory is only ever completed by writing manifest.json LAST.
If this process is killed, power is cut, or the disk fills mid-tar, what is left
behind has no manifest, is invisible to the listing, and is deleted on the next
run — an interrupted backup can never be mistaken for a usable one.

The job file lives on /run (tmpfs) because it may carry the passphrase. It is
deleted as soon as it has been read; the passphrase is never written to
persistent storage, and is never recorded in the manifest or the history.
"""
import json
import os
import sys

try:
    # hifi_backup.py and hifi_logging.py ship in /usr/local/bin alongside the
    # Python daemons; this script lives in /usr/local/sbin, so they are not
    # importable without this.
    sys.path.insert(0, '/usr/local/bin')
    from hifi_logging import tee_stdio_to_file
    tee_stdio_to_file('backup')
except Exception:
    pass

sys.path.insert(0, '/usr/local/bin')
import hifi_backup as hb                                     # noqa: E402

STATUS = hb.STATUS_FILE


def write_status(state, progress, message, **extra):
    payload = {"state": state, "progress": progress, "message": message}
    payload.update(extra)
    tmp = STATUS + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, STATUS)
    except OSError as e:
        print(f"W: [hifi-backup] impossibile scrivere lo stato: {e}",
              file=sys.stderr)


def fail(message, store=None):
    write_status("error", 0, message)
    if store:
        hb.record_history(store, f"backup\tfailed\t{message}")
    print(f"E: [hifi-backup] {message}", file=sys.stderr)
    sys.exit(1)


def read_job(path):
    """Read and immediately destroy the job file — it may hold the passphrase."""
    try:
        with open(path) as f:
            job = json.load(f)
    except Exception as e:
        fail(f"job di backup illeggibile: {e}")
    try:
        os.unlink(path)
    except OSError:
        pass
    return job


def main():
    if len(sys.argv) != 2:
        fail("uso: hifi-backup-run.py <job.json>|--scheduled")

    if sys.argv[1] == "--scheduled":
        settings = hb.read_settings()
        if not settings["scheduled"]:
            # The timer is enabled but the preference was turned off since;
            # exit quietly rather than producing an unwanted generation.
            print("I: [hifi-backup] backup pianificato disattivato, esco")
            return
        job = {"categories": list(hb.UNATTENDED_CATEGORIES),
               "trigger": "scheduled", "keep": settings["keep"]}
    else:
        job = read_job(sys.argv[1])

    store = job.get("store") or hb.STORE_DIR
    passphrase = job.get("passphrase") or ""
    trigger = job.get("trigger") or "manual"
    keep = job.get("keep") or hb.read_settings()["keep"]
    categories = hb.selected_categories(job.get("categories"), bool(passphrase))
    if not categories:
        fail("nessuna categoria da salvare", store)

    write_status("preparing", 5, "Preparazione…")
    try:
        os.makedirs(store, exist_ok=True)
        os.chmod(store, 0o700)
    except OSError as e:
        fail(f"impossibile creare {store}: {e}")

    # Clear out anything a previous interrupted run left behind before we
    # measure free space, so its bytes are not counted against us.
    hb.prune_incomplete(store)

    write_status("checking", 10, "Verifica spazio disponibile…")
    need = hb.estimate_size(categories, "/")
    if not hb.free_space_ok(store, need):
        fail(f"spazio insufficiente: servono ~{need // (1024 * 1024) + 64} MB", store)

    gen_id = hb.new_gen_id()
    gen_dir = os.path.join(store, gen_id)
    try:
        os.makedirs(gen_dir, exist_ok=True)
        os.chmod(gen_dir, 0o700)
    except OSError as e:
        fail(f"impossibile creare la generazione: {e}", store)

    hb.record_history(store, f"backup\tstarted\t{gen_id}\t{','.join(categories)}")

    plain = os.path.join(gen_dir, hb.ARCHIVE_NAME)
    write_status("archiving", 35, "Creazione archivio…", id=gen_id)
    extra = {
        "created": gen_id,
        "hostname": os.uname().nodename if hasattr(os, "uname") else "",
        "trigger": trigger,
        "versions": hb.device_versions("/"),
    }
    try:
        manifest = hb.build_archive(plain, categories, "/",
                                    encrypted=bool(passphrase), extra=extra)
    except Exception as e:
        _abandon(gen_dir)
        fail(f"creazione archivio fallita: {e}", store)

    members = manifest["members"]
    if not members:
        _abandon(gen_dir)
        fail("nessun file da salvare", store)

    enc_meta = None
    if passphrase:
        write_status("encrypting", 70, "Cifratura…", id=gen_id)
        enc = os.path.join(gen_dir, hb.ENC_NAME)
        try:
            enc_meta = hb.encrypt_archive(plain, enc, passphrase)
        except hb.BackupError as e:
            _abandon(gen_dir)
            fail(str(e), store)
        except Exception as e:
            _abandon(gen_dir)
            fail(f"cifratura fallita: {e}", store)
        finally:
            # The plaintext must not survive next to its own ciphertext, and it
            # must go even if encryption failed — it holds the credentials the
            # passphrase was meant to protect.
            try:
                os.unlink(plain)
            except OSError:
                pass

    # ── commit ───────────────────────────────────────────────────────
    # Everything above can be thrown away safely. Writing the manifest is what
    # makes this generation exist.
    write_status("finishing", 90, "Finalizzazione…", id=gen_id)
    if enc_meta:
        manifest["enc"] = enc_meta
    try:
        tmp = os.path.join(gen_dir, hb.MANIFEST_NAME + ".tmp")
        with open(tmp, "w") as f:
            json.dump(manifest, f, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, os.path.join(gen_dir, hb.MANIFEST_NAME))
    except OSError as e:
        _abandon(gen_dir)
        fail(f"scrittura manifest fallita: {e}", store)

    dropped = hb.rotate(store, keep)
    size = 0
    try:
        size = os.path.getsize(hb.archive_path(store, gen_id, manifest))
    except OSError:
        pass

    hb.record_history(store,
                      f"backup\tcompleted\t{gen_id}\t{len(members)} file\t"
                      f"{size} byte\t{'cifrato' if enc_meta else 'in chiaro'}")
    if dropped:
        hb.record_history(store, f"rotate\tremoved\t{','.join(dropped)}")

    write_status("done", 100,
                 f"Backup completato: {len(members)} file.", id=gen_id,
                 size=size, encrypted=bool(enc_meta), categories=categories)
    print(f"I: [hifi-backup] {gen_id}: {len(members)} file, {size} byte")


def _abandon(gen_dir):
    """Drop a generation that never reached its manifest. Best-effort: even if
    this fails, the missing manifest already makes it invisible and it will be
    pruned on the next run."""
    import shutil
    shutil.rmtree(gen_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
