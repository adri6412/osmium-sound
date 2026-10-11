"""Backup/restore: the archive being restored, size limits, disk not RAM, the
weekly timer.

- A restore's safety snapshot must never rotate away the backup being
  restored (it used to, whenever the owner had exactly "keep" backups and
  restored the oldest), nor cost the owner one of theirs.
- A backup never holds a member a restore would refuse; a restore measures
  every gzip layer before walking it and streams members to disk.
- Downloads are streamed from disk, uploads go straight to disk.
- The weekly timer ships in the image, and turning the schedule on reports
  a failure instead of answering "saved".
- Every backup is encrypted with the one password the device keeps: none is
  made, scheduled or downloaded without it, a restore falls back to it, and
  it is kept sealed, never in the clear and never inside a backup.

Run with:  python3 -m unittest tests.test_backup_restore_safety
"""
import gzip
import io
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import hifi_backup as hb  # noqa: E402
import sources_server as ss  # noqa: E402

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')


def _write(root, logical, content=b"x"):
    path = os.path.join(root, logical.lstrip("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    return path


class _Patched(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hifi-backup-safety-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "root")
        self.store = os.path.join(self.tmp, "store")
        os.makedirs(self.root)
        os.makedirs(self.store)
        self._saved = []
        self._patch(hb, "STORE_DIR", self.store)
        self._patch(hb, "RESTORE_PIN_FILE", os.path.join(self.tmp, "pin"))
        self._patch(hb, "SETTINGS_FILE", os.path.join(self.tmp, "backup.json"))
        self._patch(hb, "PASSPHRASE_FILE", os.path.join(self.tmp, "backup-passphrase"))
        # Everything that would read the live system reads the fake root.
        build, peak = hb.build_archive, hb.estimate_peak
        self._patch(hb, "build_archive",
                    lambda dest, cats, root="/", **kw: build(dest, cats, self.root, **kw))
        self._patch(hb, "estimate_peak",
                    lambda cats, root="/", encrypted=False: peak(cats, self.root, encrypted))
        self._patch(hb, "device_versions", lambda root="/": {})
        _write(self.root, "/etc/hifi-player/dsp.json", b'{"enabled": false}')

    def tearDown(self):
        for obj, name, value in reversed(self._saved):
            setattr(obj, name, value)

    def _patch(self, obj, name, value):
        self._saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def _with_passphrase(self, passphrase="correct horse"):
        """The device keeps a backup password (sealing is SealedPassphraseTests')."""
        self._patch(hb, "load_passphrase", lambda path=None: passphrase)
        self._patch(hb, "passphrase_set", lambda path=None: True)

    def _make_gen(self, gen_id, trigger="manual"):
        gdir = os.path.join(self.store, gen_id)
        os.makedirs(gdir)
        manifest = hb.build_archive(os.path.join(gdir, hb.ARCHIVE_NAME), ["core"],
                                    extra={"created": gen_id, "trigger": trigger})
        with open(os.path.join(gdir, hb.MANIFEST_NAME), "w") as f:
            json.dump(manifest, f)
        return gdir

    def _ids(self, trigger=None):
        return [g["id"] for g in hb.list_generations(self.store)
                if trigger is None or g["trigger"] == trigger]


class RotationTests(_Patched):
    def test_safety_snapshots_do_not_count_against_keep(self):
        for day in range(1, 6):
            self._make_gen(f"2026010{day}-000000")
        self._make_gen("20260106-000000", hb.PRE_RESTORE_TRIGGER)
        self._make_gen("20260107-000000", hb.PRE_RESTORE_TRIGGER)
        dropped = hb.rotate(self.store, keep=5)
        # all five of the owner's stay; only the newest safety snapshot does
        self.assertEqual(dropped, ["20260106-000000"])
        self.assertEqual(len(self._ids("manual")), 5)
        self.assertEqual(self._ids(hb.PRE_RESTORE_TRIGGER), ["20260107-000000"])

    def test_protected_and_pinned_generations_survive(self):
        for day in range(1, 8):
            self._make_gen(f"2026010{day}-000000")
        hb.pin_generation("20260101-000000")
        dropped = hb.rotate(self.store, keep=3, protect=("20260102-000000",))
        self.assertNotIn("20260101-000000", dropped)
        self.assertNotIn("20260102-000000", dropped)
        self.assertEqual(sorted(dropped), ["20260103-000000", "20260104-000000"])
        hb.unpin_generation()
        self.assertEqual(hb.pinned_generations(), set())

    def test_stale_workdirs_go_live_ones_stay(self):
        live = hb.make_workdir("download")
        stale = hb.make_workdir("restore")
        old = 1_000_000
        os.utime(stale, (old, old))
        hb.prune_incomplete(self.store)
        self.assertTrue(os.path.isdir(live))
        self.assertFalse(os.path.exists(stale))
        # never listed as a generation
        self.assertEqual(self._ids(), [])


class RestoreOldestTests(_Patched):
    """The reported bug: 5 backups, keep 5, restore the oldest."""

    def setUp(self):
        super().setUp()
        for day in range(1, 6):
            self._make_gen(f"2026010{day}-000000")
        self.oldest = "20260101-000000"
        with open(hb.SETTINGS_FILE, "w") as f:
            json.dump({"scheduled": False, "keep": 5}, f)

    def test_snapshot_keeps_the_backup_being_restored(self):
        gen = ss._snapshot_before_restore(protect=(self.oldest,))
        self.assertIsNotNone(gen)
        self.assertIn(self.oldest, self._ids())
        self.assertEqual(len(self._ids("manual")), 5)   # nothing of the owner's lost
        tar, manifest = hb.open_backup(hb.archive_path(self.store, self.oldest),
                                       self.tmp, max_payload=hb.MAX_RESTORE_PAYLOAD)
        with tar:
            self.assertIn("etc/hifi-player/dsp.json", tar.getnames())

    def test_restore_route_reads_the_oldest_backup_intact(self):
        seen = {}

        def fake_restore(path, passphrase, categories, report=None):
            # what the real one does first: open the archive in place
            work = hb.make_workdir("restore")
            try:
                tar, _m = hb.open_backup(path, work, passphrase,
                                         max_payload=hb.MAX_RESTORE_PAYLOAD)
                tar.close()
                seen["pinned"] = hb.pinned_generations()
                return {"success": True, "message": "ok", "restored": 1}, 200
            except hb.BackupError as e:
                return {"success": False, "message": str(e)}, 400
            finally:
                shutil.rmtree(work, ignore_errors=True)

        statuses = []
        self._patch(ss, "_restore_from_path", fake_restore)
        self._patch(ss, "_write_restore_status",
                    lambda state, progress, message, **kw: statuses.append((state, message)))
        resp = ss.app.test_client().post(f"/api/backup/{self.oldest}/restore", json={})
        self.assertEqual(resp.status_code, 202)
        ss._RESTORE_LOCK.acquire(timeout=30)   # the worker releases it when done
        ss._RESTORE_LOCK.release()
        self.assertEqual(statuses[-1][0], "done", statuses)
        self.assertEqual(seen["pinned"], {self.oldest})
        self.assertEqual(hb.pinned_generations(), set())      # unpinned afterwards
        self.assertIn(self.oldest, self._ids())
        self.assertEqual(len(self._ids("manual")), 5)
        self.assertEqual(len(self._ids(hb.PRE_RESTORE_TRIGGER)), 1)

    def test_snapshot_is_skipped_rather_than_filling_the_disk(self):
        self._patch(hb, "free_space_ok", lambda path, need: False)
        self.assertIsNone(ss._snapshot_before_restore(protect=(self.oldest,)))
        self.assertEqual(len(self._ids()), 5)


class SizeLimitTests(_Patched):
    def test_backup_leaves_out_what_a_restore_would_refuse(self):
        self._patch(hb, "MAX_MEMBER_SIZE", 1000)
        _write(self.root, "/etc/camilladsp/filters/huge.wav", b"\0" * 2000)
        _write(self.root, "/etc/camilladsp/filters/small.wav", b"\0" * 10)
        manifest = hb.build_archive(os.path.join(self.tmp, "a.tar.gz"), ["core"])
        self.assertNotIn("etc/camilladsp/filters/huge.wav", manifest["members"])
        self.assertIn("etc/camilladsp/filters/small.wav", manifest["members"])
        self.assertIn("too-large:/etc/camilladsp/filters/huge.wav", manifest["notes"])

    def test_the_metadata_archive_has_its_own_larger_limit(self):
        self.assertGreater(hb.member_size_limit(hb.METADATA_DB), 32 * 1024 * 1024)
        self.assertEqual(hb.member_size_limit("/etc/hifi-player/dsp.json"), hb.MAX_MEMBER_SIZE)
        self.assertGreaterEqual(ss.MAX_RESTORE_ARCHIVE_SIZE, hb.MAX_METADATA_DB_SIZE)
        db = os.path.join(self.root, hb.METADATA_DB.lstrip("/"))
        os.makedirs(os.path.dirname(db))
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE t (v BLOB)")
        con.execute("INSERT INTO t VALUES (?)", (b"\0" * 200000,))
        con.commit()
        con.close()
        self._patch(hb, "MAX_MEMBER_SIZE", 1000)        # the small limit does not apply
        manifest = hb.build_archive(os.path.join(self.tmp, "a.tar.gz"), ["core"])
        self.assertIn(hb.METADATA_DB.lstrip("/"), manifest["members"])

    def test_estimate_peak_counts_the_snapshot_and_the_ciphertext(self):
        db = os.path.join(self.root, hb.METADATA_DB.lstrip("/"))
        os.makedirs(os.path.dirname(db))
        with open(db, "wb") as f:
            f.write(b"\0" * 100000)
        raw = hb.estimate_size(["core"], self.root)
        plain = hb.estimate_peak(["core"])
        enc = hb.estimate_peak(["core"], encrypted=True)
        self.assertGreaterEqual(plain, raw + 100000)   # archive + snapshot beside it
        self.assertGreaterEqual(enc, 2 * raw)

    def test_a_decompression_bomb_is_refused_before_tarfile_walks_it(self):
        bomb = os.path.join(self.tmp, "bomb.tar.gz")
        with tarfile.open(bomb, "w:gz") as tar:
            info = tarfile.TarInfo("etc/hifi-player/dsp.json")
            info.size = 5 * 1024 * 1024
            tar.addfile(info, io.BytesIO(b"\0" * info.size))
        self.assertLess(os.path.getsize(bomb), 64 * 1024)
        with self.assertRaises(hb.BackupError) as cm:
            hb.open_backup(bomb, self.tmp, max_payload=1024 * 1024)
        self.assertEqual(cm.exception.code, "restore.archiveTooLarge")
        self.assertIn("1 MB", ss._backup_error_message(cm.exception))

    def test_garbage_gzip_is_invalid(self):
        junk = os.path.join(self.tmp, "junk.tar.gz")
        with open(junk, "wb") as f:
            f.write(gzip.compress(b"x")[:5])
        with self.assertRaises(hb.BackupError):
            hb.payload_size(junk, 1024)


class RestoreMembersTests(_Patched):
    """Members are streamed to disk, checked, and only then put in place."""

    def setUp(self):
        super().setUp()
        dest_root = os.path.join(self.tmp, "dest")
        orig = hb.restore_dest_for_member
        self._patch(hb, "restore_dest_for_member",
                    lambda name, cats, root="/": orig(name, cats, dest_root))
        self.dest_root = dest_root

    def _archive(self, files, digests=None):
        path = os.path.join(self.tmp, "r.tar.gz")
        with tarfile.open(path, "w:gz") as tar:
            for name, data in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return tarfile.open(path, "r:gz"), {"members": digests or {}}

    def test_streamed_member_lands_and_bad_checksum_leaves_nothing(self):
        import hashlib
        good = os.urandom(3 * 1024 * 1024)
        tar, manifest = self._archive(
            {"etc/hifi-player/dsp.json": good, "etc/hifi-player/cdrip.json": b"tampered"},
            {"etc/hifi-player/dsp.json": hashlib.sha256(good).hexdigest(),
             "etc/hifi-player/cdrip.json": hashlib.sha256(b"original").hexdigest()})
        with tar:
            restored, errors = ss._restore_members(tar, manifest, ["core"])
        dsp = os.path.join(self.dest_root, "etc/hifi-player/dsp.json")
        self.assertEqual(restored, [dsp])
        with open(dsp, "rb") as f:
            self.assertEqual(f.read(), good)
        self.assertEqual(len(errors), 1)
        left = os.listdir(os.path.join(self.dest_root, "etc/hifi-player"))
        self.assertEqual(left, ["dsp.json"])               # no cdrip.json, no .restore.tmp

    def test_too_large_member_is_skipped(self):
        self._patch(hb, "MAX_MEMBER_SIZE", 10)
        tar, manifest = self._archive({"etc/hifi-player/dsp.json": b"0123456789ABC"})
        with tar:
            restored, errors = ss._restore_members(tar, manifest, ["core"])
        self.assertEqual(restored, [])
        self.assertEqual(len(errors), 1)


class StreamingTests(_Patched):
    def setUp(self):
        super().setUp()
        self.client = ss.app.test_client()

    def test_stored_backup_is_streamed_from_disk(self):
        gen = "20260101-000000"
        self._make_gen(gen)
        resp = self.client.get(f"/api/backup/{gen}")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.direct_passthrough or resp.is_streamed)
        with open(hb.archive_path(self.store, gen), "rb") as f:
            self.assertEqual(resp.data, f.read())
        self.assertEqual(resp.headers["Content-Length"], str(len(resp.data)))
        self.assertIn(f'filename="osmium-backup-{gen}.tar.gz"', resp.headers["Content-Disposition"])
        resp.close()

    def test_download_now_builds_on_disk_and_cleans_up(self):
        self._with_passphrase("pw-download")
        resp = self.client.get("/api/backup")
        self.assertEqual(resp.status_code, 200)
        got = os.path.join(self.tmp, "got.tar.gz")
        with open(got, "wb") as f:
            f.write(resp.data)
        resp.close()
        with tarfile.open(got, "r:gz") as outer:
            self.assertIn(hb.ENC_NAME, outer.getnames())      # encrypted, not flat
        work = tempfile.mkdtemp(dir=self.tmp)
        tar, manifest = hb.open_backup(got, work, "pw-download")
        with tar:
            self.assertIn("etc/hifi-player/dsp.json", tar.getnames())
        self.assertEqual(manifest["trigger"], "download")
        self.assertEqual([n for n in os.listdir(self.store) if n.startswith(hb.WORKDIR_PREFIX)], [])

    def test_download_now_needs_the_backup_password(self):
        resp = self.client.get("/api/backup")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()["code"], "backup.passphraseMissing")

    def test_download_now_reports_no_space(self):
        self._with_passphrase()
        self._patch(hb, "free_space_ok", lambda path, need: False)
        resp = self.client.get("/api/backup")
        self.assertEqual(resp.status_code, 507)
        self.assertEqual(resp.get_json()["code"], "backup.noSpace")

    def test_upload_goes_to_disk_beyond_the_old_80mb_cap(self):
        got = {}

        def fake_start(path, passphrase, categories, workdir_to_clean=None, gen_id=None):
            with open(path, "rb") as f:
                got["data"] = f.read()
            got.update(path=path, passphrase=passphrase, categories=categories)
            shutil.rmtree(workdir_to_clean, ignore_errors=True)
            return None

        self._patch(ss, "_start_restore", fake_start)
        payload = os.urandom(200000)
        resp = self.client.post("/api/restore", data={
            "file": (io.BytesIO(payload), "b.tar.gz"),
            "passphrase": "pw", "categories": "core,sources"},
            content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 202, resp.get_json())
        self.assertEqual(got["data"], payload)
        self.assertTrue(got["path"].startswith(self.store + os.sep))
        self.assertEqual(got["passphrase"], "pw")
        self.assertEqual(got["categories"], ["core", "sources"])

    def test_upload_over_the_limit_is_refused(self):
        self._patch(ss, "MAX_RESTORE_ARCHIVE_SIZE", 1000)
        self._patch(ss, "_start_restore", lambda *a, **k: self.fail("must not start"))
        resp = self.client.post("/api/restore", data={
            "file": (io.BytesIO(b"\0" * (2 * 1024 * 1024)), "b.tar.gz")},
            content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual([n for n in os.listdir(self.store) if n.startswith(hb.WORKDIR_PREFIX)], [])

    def test_upload_without_a_file(self):
        resp = self.client.post("/api/restore", data={"passphrase": ""},
                                content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 400)


class ScheduleTests(_Patched):
    def setUp(self):
        super().setUp()
        self.client = ss.app.test_client()
        self.calls = []

    def _systemctl(self, rc, err=""):
        def run(cmd, timeout=30):
            self.calls.append(cmd)
            return SimpleNamespace(returncode=rc, stdout="", stderr=err)
        self._patch(ss, "_run", run)

    def test_enable_failure_is_reported_and_not_saved(self):
        self._with_passphrase()
        self._systemctl(1, "Unit file hifi-backup.timer does not exist.")
        resp = self.client.post("/api/backup/settings", json={"scheduled": True})
        self.assertEqual(resp.status_code, 500)
        body = resp.get_json()
        self.assertFalse(body["success"])
        self.assertIn("does not exist", body["message"])
        self.assertFalse(hb.read_settings()["scheduled"])
        self.assertEqual(self.calls, [["systemctl", "enable", "--now", "hifi-backup.timer"]])

    def test_enable_success_and_keep_is_preserved(self):
        with open(hb.SETTINGS_FILE, "w") as f:
            json.dump({"scheduled": False, "keep": 9}, f)
        self._with_passphrase()
        self._systemctl(0)
        resp = self.client.post("/api/backup/settings", json={"scheduled": True})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(hb.read_settings(), {"scheduled": True, "keep": 9})

    def test_no_weekly_backup_without_the_backup_password(self):
        self._systemctl(0)
        resp = self.client.post("/api/backup/settings", json={"scheduled": True})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()["code"], "backup.passphraseMissing")
        self.assertFalse(hb.read_settings()["scheduled"])
        self.assertEqual(self.calls, [])

    def test_disable_failure_still_turns_it_off(self):
        # the worker exits on "scheduled": false, so off is off regardless
        self._systemctl(1, "boom")
        resp = self.client.post("/api/backup/settings", json={"scheduled": False})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(hb.read_settings()["scheduled"])


class PassphraseTests(_Patched):
    """One password, chosen once, encrypts every backup."""

    def setUp(self):
        super().setUp()
        self.client = ss.app.test_client()
        self.saved = []
        self._patch(hb, "save_passphrase", lambda p, path=None: self.saved.append(p))

    def _job(self):
        self._patch(ss, "BACKUP_SCRIPT", __file__)
        self._patch(ss, "BACKUP_JOB", os.path.join(self.tmp, "job.json"))
        self._patch(hb, "STATUS_FILE", os.path.join(self.tmp, "status.json"))
        self._patch(ss, "_run", lambda cmd, timeout=30: SimpleNamespace(returncode=0, stdout="", stderr=""))

    def test_choosing_it(self):
        resp = self.client.post("/api/backup/passphrase", json={"passphrase": "short"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["code"], "backup.passphraseTooShort")
        self.assertEqual(self.saved, [])
        resp = self.client.post("/api/backup/passphrase", json={"passphrase": "long enough"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.saved, ["long enough"])

    def test_it_is_shown_only_when_asked(self):
        self.assertEqual(self.client.get("/api/backup/passphrase").get_json(), {"set": False})
        self.assertEqual(self.client.get("/api/backup/passphrase?reveal=1").status_code, 409)
        self._with_passphrase("open sesame")
        self.assertEqual(self.client.get("/api/backup/passphrase").get_json(), {"set": True})
        body = self.client.get("/api/backup/passphrase?reveal=1").get_json()
        self.assertEqual(body["passphrase"], "open sesame")
        self.assertTrue(self.client.get("/api/backup/list").get_json()["passphrase_set"])

    def test_no_backup_without_it(self):
        self._job()
        resp = self.client.post("/api/backup/create", json={})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()["code"], "backup.passphraseMissing")
        self.assertFalse(os.path.exists(ss.BACKUP_JOB))

    def test_a_backup_uses_the_stored_one_and_carries_everything(self):
        self._job()
        self._with_passphrase("stored pw")
        resp = self.client.post("/api/backup/create", json={})
        self.assertEqual(resp.status_code, 202)
        with open(ss.BACKUP_JOB) as f:
            job = json.load(f)
        self.assertEqual(job["passphrase"], "stored pw")
        self.assertEqual(job["categories"], list(hb.ALL_CATEGORIES))

    def test_the_first_one_typed_in_the_app_is_kept(self):
        # The companion app still sends a passphrase with each backup.
        self._job()
        resp = self.client.post("/api/backup/create", json={"passphrase": "from the app"})
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(self.saved, ["from the app"])
        with open(ss.BACKUP_JOB) as f:
            self.assertEqual(json.load(f)["passphrase"], "from the app")

    def test_the_safety_snapshot_is_encrypted_and_complete(self):
        self._with_passphrase("snap pw")
        gen = ss._snapshot_before_restore()
        manifest = hb.read_manifest(self.store, gen)
        self.assertTrue(manifest.get("enc"))
        self.assertEqual(manifest["categories"], list(hb.ALL_CATEGORIES))
        self.assertFalse(os.path.exists(os.path.join(self.store, gen, hb.ARCHIVE_NAME)))
        wrapper = os.path.join(self.tmp, "w.tar.gz")
        hb.wrap_encrypted(wrapper, manifest, hb.archive_path(self.store, gen, manifest))
        tar, _m = hb.open_backup(wrapper, tempfile.mkdtemp(dir=self.tmp), "snap pw")
        with tar:
            self.assertIn("etc/hifi-player/dsp.json", tar.getnames())

    def test_never_inside_a_backup(self):
        self.assertIn("/etc/hifi-player/backup-passphrase", hb.DENY_FILES)
        self.assertEqual(hb.PASSPHRASE_FILE, os.path.join(self.tmp, "backup-passphrase"))
        self.assertIsNone(hb.restore_dest_for_member("etc/hifi-player/backup-passphrase",
                                                     list(hb.ALL_CATEGORIES)))


class RestorePassphraseTests(_Patched):
    def setUp(self):
        super().setUp()
        self.statuses = []
        self.saved = []
        self.passed = []
        self._patch(ss, "_write_restore_status",
                    lambda state, progress, message, **kw: self.statuses.append((state, message)))
        self._patch(ss, "_snapshot_before_restore", lambda protect=(): "snap")
        self._patch(ss, "PROVISIONING_MARKER", os.path.join(self.tmp, "provisioning-pending"))
        self._patch(hb, "save_passphrase", lambda p, path=None: self.saved.append(p))
        self.addCleanup(lambda: ss._job_lang.__dict__.pop("lang", None))

    def _run(self, typed, result):
        def fake_restore(path, passphrase, categories, report=None):
            self.passed.append(passphrase)
            return result
        self._patch(ss, "_restore_from_path", fake_restore)
        self.assertTrue(ss._RESTORE_LOCK.acquire(timeout=30))
        ss._run_restore_async("x", typed, None, lang="en")
        return self.statuses[-1]

    def test_nothing_typed_uses_the_stored_one(self):
        self._with_passphrase("stored pw")
        self._run("", ({"success": True, "message": "ok", "restored": 1}, 200))
        self.assertEqual(self.passed, ["stored pw"])
        self.assertEqual(self.saved, [])

    def test_a_backup_made_with_another_password_says_so(self):
        self._with_passphrase("stored pw")
        state, message = self._run("", ({"success": False, "code": "restore.wrongPassphrase",
                                         "message": "x"}, 400))
        self.assertEqual(state, "error")
        self.assertEqual(message, ss._ht("restore.otherPassphrase", "en"))

    def test_a_new_device_keeps_the_password_it_was_restored_with(self):
        self._run("old box pw", ({"success": True, "message": "ok", "restored": 1}, 200))
        self.assertEqual(self.passed, ["old box pw"])
        self.assertEqual(self.saved, ["old box pw"])

    def test_a_device_with_its_own_keeps_it(self):
        self._with_passphrase("mine")
        self._run("older one", ({"success": True, "message": "ok", "restored": 1}, 200))
        self.assertEqual(self.saved, [])


class RestoredLyrionDatabaseTests(_Patched):
    def test_a_restored_persist_db_does_not_meet_the_old_log(self):
        db = _write(self.root, "/var/lib/squeezeboxserver/prefs/persist.db", b"snapshot")
        _write(self.root, "/var/lib/squeezeboxserver/prefs/persist.db-wal", b"old log")
        _write(self.root, "/var/lib/squeezeboxserver/prefs/persist.db-shm", b"old index")
        ss._drop_stale_sqlite_logs([db])
        self.assertEqual(sorted(os.listdir(os.path.dirname(db))), ["persist.db"])

    def test_an_old_backup_cannot_bring_a_log_back(self):
        for side in ("-wal", "-shm"):
            self.assertIsNone(hb.restore_dest_for_member(
                "var/lib/squeezeboxserver/prefs/persist.db" + side, ["lyrion"]))
        self.assertTrue(hb.restore_dest_for_member(
            "var/lib/squeezeboxserver/prefs/persist.db", ["lyrion"]))


@unittest.skipUnless(shutil.which("systemd-creds"), "systemd-creds not installed")
class SealedPassphraseTests(_Patched):
    def setUp(self):
        super().setUp()
        self._patch(hb, "LOGIN_KEY_FILE", os.path.join(self.tmp, "credential.secret"))

    def test_round_trip_sealed_on_disk(self):
        self.assertFalse(hb.passphrase_set())
        self.assertEqual(hb.load_passphrase(), "")
        hb.save_passphrase("hunter2 hunter2")
        self.assertTrue(hb.passphrase_set())
        with open(hb.PASSPHRASE_FILE, "rb") as f:
            self.assertNotIn(b"hunter2", f.read())
        self.assertEqual(os.stat(hb.PASSPHRASE_FILE).st_mode & 0o777, 0o600)
        self.assertEqual(hb.load_passphrase(), "hunter2 hunter2")

    def test_a_lost_key_makes_it_unreadable(self):
        hb.save_passphrase("hunter2 hunter2")
        os.unlink(hb.LOGIN_KEY_FILE)
        hb.seal_login("x", "y")            # a fresh key takes its place
        with self.assertRaises(hb.LoginUnreadable):
            hb.load_passphrase()

    def test_a_share_login_does_not_open_as_the_passphrase(self):
        with open(hb.PASSPHRASE_FILE, "w") as f:
            f.write(hb.seal_login("g22", "hunter2"))    # same key, other name
        with self.assertRaises(hb.LoginUnreadable):
            hb.load_passphrase()


class ShippedUnitsTests(unittest.TestCase):
    UNITS = os.path.join(REPO, "distro/config/includes.chroot/etc/systemd/system")

    def _heredoc(self, unit):
        with open(os.path.join(REPO, "distro/os-update/apply.d/0033-backup-scheduler.sh")) as f:
            text = f.read()
        start = text.index(f"/etc/systemd/system/{unit} 644 root:root <<'EOF'\n")
        body = text[text.index("\n", start) + 1:]
        return body[:body.index("\nEOF\n") + 1]

    def test_units_ship_in_the_image_identical_to_0033(self):
        # Byte-identical: on a legacy install the system bundle copies these
        # and 0033's ensure_file_content must then find nothing to change.
        for unit in ("hifi-backup.service", "hifi-backup.timer"):
            with open(os.path.join(self.UNITS, unit)) as f:
                self.assertEqual(f.read(), self._heredoc(unit), unit)

    def test_the_service_runs_a_script_the_image_has(self):
        with open(os.path.join(self.UNITS, "hifi-backup.service")) as f:
            exec_start = [l for l in f if l.startswith("ExecStart=")][0]
        script = exec_start.split("=", 1)[1].split()[0]
        self.assertEqual(script, "/usr/local/sbin/hifi-backup-run.py")
        shipped = os.path.join(REPO, "distro/config/includes.chroot", script.lstrip("/"))
        self.assertTrue(os.access(shipped, os.X_OK) or os.path.isfile(shipped))

    def test_the_timer_is_enabled_in_the_image(self):
        with open(os.path.join(REPO, "distro/config/hooks/normal/0400-enable-services.hook.chroot")) as f:
            self.assertIn("systemctl enable hifi-backup.timer", f.read())

    def test_the_worker_exits_when_the_schedule_is_off(self):
        with open(os.path.join(REPO, "distro/config/includes.chroot/usr/local/sbin/hifi-backup-run.py")) as f:
            src = f.read()
        self.assertIn('if not settings["scheduled"]', src)

    def test_factory_reset_forgets_the_backup_password(self):
        with open(os.path.join(REPO, "distro/config/includes.chroot/usr/local/sbin/hifi-factory-reset.sh")) as f:
            self.assertIn("rm -f /etc/hifi-player/backup-passphrase", f.read())


if __name__ == "__main__":
    unittest.main()
