#!/usr/bin/env python3
"""Osmium Sound — music and playlists sitting on the legacy root, moved onto
/data before the device switches to the A/B image.

WHY
A source can be a folder of the appliance's own root filesystem: Music Sources
accepts /srv, /mnt, /media and /home, and "publish it over the network" turns
one of them into a Samba share people copy their library into. On the A/B
layout the system is a read-only image, and none of those paths holds anything
of the owner's any more: / is the squashfs of the running slot, /mnt and
/media are tmpfs (empty at every boot), and the only thing that survives is
/data plus what is bind-mounted from it (/etc's overlay, /var, /home).
Converting without moving those folders first leaves the music on the disk —
inside the old root, now slot A — but invisible, and gone for good at the
first image update that writes over that slot.

WHAT
    scan [--mib]   what would be relocated: JSON, or just the MiB it needs on
                   /data (hifi-ab-precheck.sh refuses a conversion that would
                   not fit)
    move           relocate it, then repoint Lyrion and Samba at the new place

Two destinations, because the two cases are not the same:

  * under /home the path stays as it is. The image bind-mounts /home from
    /data/home, so such a folder only has to BE there: it is copied, not
    moved (the legacy root stays bootable as slot A until the first image
    update overwrites it, so it has to keep working), and nothing needs
    repointing. hifi-ab-seed.sh already does this for the homes of the
    wizard's users; this covers /home/hifi/Music and the folders under /home
    that belong to no user at all.

  * everything else moves to /data/music/<name>, and every pointer follows it:
    /etc/hifi-sources.json, the Samba shares file, Lyrion's mediadirs and its
    playlistdir. /data is mounted at that same path on the legacy root too, so
    the new path is valid on BOTH sides of the switch — including a rollback
    to slot A, where a symlink left where the folder used to be also rescues
    anything else that still pointed at the old place.

Runs BEFORE hifi-ab-seed.sh (hifi-image-update.sh and hifi-ab-convert.sh
install both call it there): the seed copies hifi-sources.json, the Samba
shares and Lyrion's prefs onto /data, so the pointers have to be the new ones
by the time it runs.

Idempotent. An interrupted run leaves the copy in place and the original
folder still there, and the next one finishes the job — the destination it had
picked is recorded in /data/music/.osmium-moved.json, so a second attempt does
not end up with a "-2" folder next to the first.
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

# Only the tests set these; on the appliance the defaults are the real thing.
SYSROOT = os.environ.get("HIFI_SYSROOT", "")
SYSTEMCTL = os.environ.get("HIFI_SYSTEMCTL", "systemctl")
LYRION_RPC = os.environ.get("HIFI_LYRION_RPC", "http://127.0.0.1:9000/jsonrpc.js")

DATA_MNT = "/data"
MUSIC_ROOT = "/data/music"
DATA_HOME = "/data/home"
MANIFEST = MUSIC_ROOT + "/.osmium-moved.json"
STATE_FILE = "/etc/hifi-sources.json"
SAMBA_SHARES = "/etc/samba/hifi-shares.conf"
SUMMARY = "/run/hifi-ab-media.json"
IMAGE_MARKER = "/usr/lib/osmium/IMAGE_VERSION"
LYRION_SERVICE = "lyrionmusicserver.service"
PREFS_FILES = ("/var/lib/squeezeboxserver/prefs/server.prefs",
               "/var/lib/lyrionmusicserver/prefs/server.prefs")
PREFS_GLOB = "/var/lib/lyrion*/prefs/server.prefs"

HOME = "/home"
# Where a folder of the root filesystem may be moved from. These are the roots
# Music Sources itself allows, minus /home (its own case above): what is here
# was put here by the owner, so it can be moved without thinking about what
# else might need it.
MOVABLE_ROOTS = ("/srv", "/mnt", "/media")
# ...but never the roots themselves: /mnt and /media are where the appliance
# mounts disks and shares (on the image they are tmpfs), so they must keep
# being ordinary directories.
NEVER_TOUCH = ("/", "/mnt", "/media")
# Folders hifi-ab-seed.sh already copies onto /data under the very same path.
# Whatever is inside them is on the image as well, so it must NOT be moved —
# the appliance's own playlist folder (/var/lib/squeezeboxserver/playlists) is
# the one that matters here.
SEEDED = ("/var/lib/hifi-player", "/var/lib/squeezeboxserver",
          "/var/lib/lyrionmusicserver", "/var/lib/bluetooth", "/var/lib/samba",
          "/var/lib/NetworkManager", "/var/log/hifi")
# The appliance's own mount roots. A folder that turns up under one of these
# while nothing is mounted there is not a library on the root filesystem: it
# is the empty mountpoint of a disk that is unplugged, or files someone wrote
# into it while it was — moving that would resurrect shadowed junk as a
# library, and the disk itself is not affected by the conversion anyway.
MOUNT_ROOTS = ("/mnt/hifi-sources", "/mnt/hifi-internal", "/mnt/hifi-usb",
               "/media/hifi-usb")
# Left free on /data after everything has been copied.
MARGIN_MIB = 128


def log(msg):
    print("I: [hifi-ab-media] %s" % msg, file=sys.stderr)


def warn(msg):
    print("W: [hifi-ab-media] %s" % msg, file=sys.stderr)


# ───────────────────────────── paths ────────────────────────────────────
def real(path):
    """On-disk path for an appliance one (identical outside the tests)."""
    return SYSROOT + path if SYSROOT else path


def appliance(path):
    if SYSROOT and path.startswith(SYSROOT):
        return path[len(SYSROOT):] or "/"
    return path


def resolve(path):
    """Realpath, followed on disk, answered in appliance terms."""
    return appliance(os.path.realpath(real(path)))


def under(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def load_json(path, default):
    try:
        with open(real(path)) as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, data, mode=0o644):
    tmp = real(path) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.chmod(tmp, mode)
    os.replace(tmp, real(path))


# ───────────────────────────── Lyrion ───────────────────────────────────
def rpc(params, timeout=10):
    payload = {"id": 1, "method": "slim.request", "params": ["", params]}
    req = urllib.request.Request(
        LYRION_RPC, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8")).get("result") or {}


def prefs_file():
    for c in PREFS_FILES:
        if os.path.isfile(real(c)):
            return c
    for c in sorted(glob.glob(real(PREFS_GLOB))):
        if os.path.isfile(c):
            return appliance(c)
    return None


def prefs_read():
    p = prefs_file()
    if not p:
        return {}
    try:
        import yaml
        with open(real(p)) as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        warn("server.prefs unreadable (%s)" % e)
        return {}


def lyrion_get(key, default=None):
    """Live value first: Lyrion keeps its prefs in memory and only flushes
    them to disk now and then, so a running server is the authority. The file
    is the answer when it is not running."""
    try:
        v = rpc(["pref", key, "?"]).get("_p2")
        if v is not None:
            return v
    except Exception:
        pass
    v = prefs_read().get(key)
    return default if v is None else v


def lyrion_set(values):
    """Write prefs. Live over JSON-RPC while Lyrion answers (it persists them
    itself, and nothing has to be restarted mid-update); otherwise stop it,
    rewrite server.prefs and start it again — edited underneath a running
    server, the file would simply be overwritten."""
    live = True
    for key, value in values.items():
        try:
            rpc(["pref", key, value])
        except Exception:
            live = False
            break
    if live:
        return True

    p = prefs_file()
    if not p:
        # No prefs file at all: Lyrion has never run here, so it points at
        # nothing and there is nothing to repoint.
        log("server.prefs not found: nothing to repoint in Lyrion")
        return True
    try:
        import yaml
    except Exception:
        warn("python3-yaml missing: server.prefs cannot be rewritten")
        return False
    subprocess.run([SYSTEMCTL, "stop", LYRION_SERVICE],
                   capture_output=True, check=False)
    try:
        data = prefs_read()
        data.update(values)
        tmp = real(p) + ".tmp"
        with open(tmp, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
        try:
            st = os.stat(real(p))
            os.chown(tmp, st.st_uid, st.st_gid)
            os.chmod(tmp, st.st_mode & 0o7777)
        except OSError:
            pass
        os.replace(tmp, real(p))
    except Exception as e:
        warn("server.prefs rewrite failed: %s" % e)
        return False
    finally:
        subprocess.run([SYSTEMCTL, "start", LYRION_SERVICE],
                       capture_output=True, check=False)
    return True


def lyrion_rescan():
    """Mediadirs that changed mean the library has to be walked again: the
    tracks Lyrion knows are at paths that no longer exist. Best effort, and
    patient — after the file fallback above the server has just been started
    and its JSON-RPC takes a few seconds to answer."""
    for _ in range(15):
        try:
            rpc(["rescan"])
            log("Lyrion library rescan requested")
            return
        except Exception:
            time.sleep(2)
    warn("Lyrion did not answer: the library rescan has to be asked for by hand")


# ─────────────────────────── what to relocate ───────────────────────────
def candidates():
    """Every folder this appliance points at for music or playlists, what
    points at it, and the exact strings it is written as. Lyrion's own list
    counts too, not only ours: a folder can have been added in Lyrion's web
    interface, and it would be just as gone after the switch.

    The raw strings are kept because they are what has to be rewritten later,
    and by then the folder has moved: resolving them a second time would
    follow the symlink left behind and answer "already right"."""
    found = {}

    def add(path, origin):
        if not path or not isinstance(path, str):
            return
        raw = path.strip()
        p = resolve(raw)
        if p:
            e = found.setdefault(p, {"origins": set(), "raw": set()})
            e["origins"].add(origin)
            e["raw"].add(raw)

    state = load_json(STATE_FILE, {}) or {}
    for src in state.get("sources", []) if isinstance(state, dict) else []:
        if isinstance(src, dict) and src.get("type") == "local":
            add(src.get("path"), "sources")
    media = lyrion_get("mediadirs") or []
    if isinstance(media, str):
        media = [media]
    for d in media if isinstance(media, list) else []:
        add(d, "mediadirs")
    add(lyrion_get("playlistdir") or "", "playlistdir")
    return found


def classify(path):
    """"move", "copy", "unsupported" — or None when there is nothing to do."""
    if not os.path.isdir(real(path)) or os.path.islink(real(path)):
        return None
    if under(path, DATA_MNT):
        return None                       # already where it has to be
    for r in MOUNT_ROOTS:
        if under(path, r):
            return None                   # a disk or a share, not the root fs
    for r in SEEDED:
        if under(path, r):
            return None                   # hifi-ab-seed.sh already carries it
    try:
        if os.stat(real(path)).st_dev != os.stat(real("/")).st_dev:
            return None                   # its own filesystem: it survives
    except OSError:
        return None
    if under(path, HOME):
        return "copy"
    if path in NEVER_TOUCH:
        return "unsupported"
    for r in MOVABLE_ROOTS:
        if under(path, r):
            return "move"
    return "unsupported"


def tree_size(path):
    """What the folder takes on the disk, the way du counts it — that is what
    has to fit on /data. Symlinks are not followed and a hard-linked file is
    counted once."""
    total = 0
    seen = set()
    for root, dirs, files in os.walk(real(path), followlinks=False):
        for name in dirs + files:
            try:
                st = os.lstat(os.path.join(root, name))
            except OSError:
                continue
            if st.st_nlink > 1:
                if st.st_ino in seen:
                    continue
                seen.add(st.st_ino)
            total += st.st_blocks * 512
    return total


def is_image():
    """An A/B image slot, where there is nothing to relocate: /home already IS
    /data/home (bind-mounted by the initramfs), and copying it onto itself is
    the only thing this would find to do."""
    return os.path.exists(real(IMAGE_MARKER))


def scan(found=None):
    """The folders to deal with, outermost first and with the ones nested
    inside another dropped: a mediadir pointing at a subfolder of a source
    moves with the source, and counting it twice would ask /data for space
    that is not needed."""
    if is_image():
        return []
    if found is None:
        found = candidates()
    keep = {p: a for p, a in ((p, classify(p)) for p in found) if a}
    entries = []
    for path in sorted(keep):
        if any(under(path, other) and path != other for other in keep):
            continue
        entries.append({"path": path, "action": keep[path],
                        "origins": sorted(found[path]["origins"]),
                        "bytes": tree_size(path) if keep[path] != "unsupported" else 0})
    return entries


# ─────────────────────────────── moving ─────────────────────────────────
def dest_for(path, action, manifest, taken):
    if action == "copy":
        return DATA_HOME + path[len(HOME):]
    known = manifest.get(path)
    if known:
        return known                      # a run that was interrupted: resume
    base = os.path.basename(path.rstrip("/")) or "music"
    dest = MUSIC_ROOT + "/" + base
    n = 2
    while dest in taken or os.path.exists(real(dest)):
        dest = "%s/%s-%d" % (MUSIC_ROOT, base, n)
        n += 1
    return dest


def copy_tree(src, dest, update=True):
    """cp -a, plus -u so a second attempt only copies what is missing. The
    top folder's own owner and mode are set as well: on a published folder
    they are what lets Samba and Lyrion both write inside it (hifimusic,
    the shared group, setgid).

    Without `update` every file is copied again: that is the way out of the
    one state -u cannot fix by itself, a file left half-written by a copy that
    was cut short, which is newer than the original and would be skipped for
    ever."""
    os.makedirs(real(dest), exist_ok=True)
    cmd = ["cp", "-a"] + (["-u"] if update else []) + ["--", real(src) + "/.", real(dest) + "/"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        warn("cp %s: %s" % (src, (r.stderr or "").strip()[:200]))
        return False
    try:
        st = os.lstat(real(src))
        os.chown(real(dest), st.st_uid, st.st_gid)
        os.chmod(real(dest), st.st_mode & 0o7777)
    except OSError:
        pass
    return True


def verify(src, dest):
    """How many files did not arrive, or arrived a different size. Stat only,
    so it costs nothing on a big library, and it catches the one failure that
    matters before the original is deleted: a copy that ran out of room."""
    bad = 0
    base = real(src)
    for root, dirs, files in os.walk(base, followlinks=False):
        rel = os.path.relpath(root, base)
        for name in files:
            s = os.path.join(root, name)
            d = os.path.join(real(dest), name) if rel == "." \
                else os.path.join(real(dest), rel, name)
            try:
                ss = os.lstat(s)
            except OSError:
                continue                  # vanished while we walked: not ours
            try:
                ds = os.lstat(d)
            except OSError:
                bad += 1
                continue
            if not os.path.islink(s) and ss.st_size != ds.st_size:
                bad += 1
    return bad


def ensure_music_root():
    """/data/music belongs to the shared group, setgid: everything created
    inside it — by Samba as hifimusic, by Lyrion saving a playlist — stays
    writable by the other one (see SHARE_GROUP in sources_server.py)."""
    os.makedirs(real(MUSIC_ROOT), exist_ok=True)
    try:
        import grp
        gid = grp.getgrnam("hifishare").gr_gid
        os.chown(real(MUSIC_ROOT), 0, gid)
    except Exception:
        pass
    try:
        os.chmod(real(MUSIC_ROOT), 0o2775)
    except OSError:
        pass


def remap(path, moves):
    for old, new in moves.items():
        if path == old:
            return new
        if path.startswith(old.rstrip("/") + "/"):
            return new + path[len(old):]
    return path


def target(stored, moves, resolved):
    """The new value for a pointer, or None when it does not name a moved
    folder.

    The string itself is tried first, and only then what it resolved to
    BEFORE anything moved (`resolved`, for a pointer that named a symlink or
    a subfolder). Asking the filesystem now would follow the symlink left
    where the folder used to be and answer "already right" — which is exactly
    how a share ends up serving a path that exists on the legacy slot only,
    and that is also the state a run interrupted between the move and this
    has to be able to repair."""
    if not stored:
        return None
    for was in (os.path.normpath(stored), resolved.get(stored)):
        if not was:
            continue
        new = remap(was, moves)
        if new != stored:
            return new
    return None


def repoint(moves, resolved):
    """Everything that names a moved folder now names the new one. Errors are
    collected, not raised: the files are already safe on /data, and the caller
    decides what a pointer left behind is worth."""
    errors = []

    state = load_json(STATE_FILE, None)
    if isinstance(state, dict) and isinstance(state.get("sources"), list):
        changed = False
        for src in state["sources"]:
            if not isinstance(src, dict) or src.get("type") != "local":
                continue
            was = src.get("path") or ""
            new = target(was, moves, resolved)
            if not new:
                continue
            # The name of a local source IS its path (api_add_local), so it
            # follows; a name the owner gave it does not.
            if src.get("name") == was:
                src["name"] = new
            src["path"] = new
            changed = True
        if changed:
            try:
                write_json(STATE_FILE, state, 0o600)
                log("Music Sources repointed at the new folders")
            except OSError as e:
                errors.append("hifi-sources.json: %s" % e)

    try:
        with open(real(SAMBA_SHARES)) as f:
            lines = f.read().splitlines()
    except OSError:
        lines = None
    if lines is not None:
        out, changed = [], False
        for line in lines:
            key, sep, value = line.partition("=")
            if sep and key.strip() == "path":
                new = target(value.strip(), moves, resolved)
                if new:
                    line = "   path = " + new
                    changed = True
            out.append(line)
        if changed:
            try:
                tmp = real(SAMBA_SHARES) + ".tmp"
                with open(tmp, "w") as f:
                    f.write("\n".join(out) + "\n")
                os.chmod(tmp, 0o644)
                os.replace(tmp, real(SAMBA_SHARES))
                subprocess.run([SYSTEMCTL, "try-reload-or-restart", "smbd"],
                               capture_output=True, check=False)
                log("network shares repointed at the new folders")
            except OSError as e:
                errors.append("%s: %s" % (SAMBA_SHARES, e))

    values = {}
    media = lyrion_get("mediadirs") or []
    if isinstance(media, str):
        media = [media]
    if isinstance(media, list) and media:
        new_media = []
        for d in media:
            # A folder and a subfolder of it travel together and can come out
            # as the same path: Lyrion must not be handed it twice.
            d = target(d, moves, resolved) or d
            if d not in new_media:
                new_media.append(d)
        if new_media != media:
            values["mediadirs"] = new_media
    playlists = lyrion_get("playlistdir") or ""
    if playlists:
        new_playlists = target(playlists, moves, resolved)
        if new_playlists:
            values["playlistdir"] = new_playlists
    if values:
        if lyrion_set(values):
            log("Lyrion repointed (%s)" % ", ".join(sorted(values)))
            lyrion_rescan()
        else:
            errors.append("Lyrion could not be repointed at the new folders")
    return errors


def summary(entries, moves, errors):
    data = {"entries": entries, "moved": moves, "errors": errors,
            "needed_mib": sum(e["bytes"] for e in entries) // (1024 * 1024)}
    try:
        os.makedirs(os.path.dirname(real(SUMMARY)), exist_ok=True)
        write_json(SUMMARY, data)
    except OSError:
        pass
    return data


# ─────────────────────────────── commands ───────────────────────────────
def cmd_scan(argv):
    entries = scan()
    if "--mib" in argv:
        print(sum(e["bytes"] for e in entries) // (1024 * 1024))
    else:
        json.dump({"entries": entries,
                   "needed_mib": sum(e["bytes"] for e in entries) // (1024 * 1024)},
                  sys.stdout, indent=2)
        print()
    return 0


def cmd_move():
    if not SYSROOT and not os.path.ismount(real(DATA_MNT)):
        subprocess.run(["mount", DATA_MNT], capture_output=True, check=False)
        if not os.path.ismount(real(DATA_MNT)):
            warn("/data is not mounted: nothing can be moved onto it")
            return 1

    found = candidates()
    # What every pointer meant before anything moved (see target()).
    resolved = {raw: path for path, e in found.items() for raw in e["raw"]}
    entries = scan(found)
    todo = [e for e in entries if e["action"] in ("move", "copy")]
    for e in entries:
        if e["action"] == "unsupported":
            warn("%s (%s) is on the system disk but outside the folders the "
                 "appliance manages: it will not be on the new system — copy "
                 "it to a USB or internal disk yourself"
                 % (e["path"], ", ".join(e["origins"])))
    manifest = load_json(MANIFEST, {}) or {}
    # A run that died between moving a folder and repointing at it: the
    # folder is gone from the root filesystem, so nothing above sees it any
    # more, and the pointers would stay on the old path for good.
    moves = {old: new for old, new in manifest.items()
             if os.path.isdir(real(new))
             and not (os.path.isdir(real(old)) and not os.path.islink(real(old)))}
    if not todo and not moves:
        log("no music or playlist folder of the root filesystem to relocate")
        summary(entries, {}, [])
        return 0

    need = sum(e["bytes"] for e in todo)
    free = shutil.disk_usage(real(DATA_MNT)).free
    if free < need + MARGIN_MIB * 1024 * 1024:
        warn("the data partition has %d MiB free and the music on the system "
             "disk needs %d MiB: not moving anything"
             % (free // (1024 * 1024), need // (1024 * 1024)))
        summary(entries, {}, ["not enough room on /data"])
        return 1

    ensure_music_root()
    errors = []
    for e in todo:
        src = e["path"]
        dest = dest_for(src, e["action"], manifest, set(moves.values()))
        e["dest"] = dest
        log("%s %s -> %s (%d MiB)"
            % ("copying" if e["action"] == "copy" else "moving",
               src, dest, e["bytes"] // (1024 * 1024)))
        if e["action"] == "move" and manifest.get(src) != dest:
            # The destination is written down BEFORE the copy starts, so a run
            # that is cut short half-way carries on into the same folder
            # instead of leaving a half-copy behind and starting a "-2" one.
            manifest[src] = dest
            try:
                write_json(MANIFEST, manifest)
            except OSError as ex:
                warn("the list of moved folders could not be written: %s" % ex)
        if not copy_tree(src, dest):
            # cp is allowed to have complained (a socket it cannot recreate,
            # an owner it cannot preserve): what decides is whether the files
            # are there, which is what verify() answers.
            log("cp reported errors on %s: checking what actually arrived" % src)
        missing = verify(src, dest)
        if missing:
            log("%s: %d file(s) to copy again" % (src, missing))
            copy_tree(src, dest, update=False)
            missing = verify(src, dest)
        if missing:
            errors.append("%s: %d file(s) did not arrive in %s"
                          % (src, missing, dest))
            continue
        if e["action"] == "copy":
            # /home is bind-mounted from /data/home on the image, so the path
            # is already right: the original stays where it is, for the legacy
            # slot to keep using until an image update overwrites it.
            continue
        try:
            shutil.rmtree(real(src))
        except OSError as ex:
            errors.append("%s could not be removed: %s" % (src, ex))
            continue
        moves[src] = dest
        try:
            # Safety net for the legacy slot only (the image has no writable
            # /srv): anything still naming the old path — a pointer we could
            # not rewrite, a bookmark of the owner's — keeps working.
            os.symlink(dest, real(src))
        except OSError:
            pass

    if moves:
        errors += repoint(moves, resolved)

    summary(entries, moves, errors)
    if errors:
        for e in errors:
            warn(e)
        return 1
    log("music and playlists are on the data partition (%d folder(s))" % len(todo))
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "scan"
    if cmd == "scan":
        return cmd_scan(argv[2:])
    if cmd == "move":
        return cmd_move()
    print("usage: %s scan [--mib] | move" % os.path.basename(argv[0]),
          file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv))
