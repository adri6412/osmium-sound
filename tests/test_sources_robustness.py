"""sources_server.py against the failures seen on real devices (2026-10-06):

  * a folder name with a line break injected sections into smb.conf;
  * two folders (or two shares) whose names make the same slug shared one id;
  * a wrong SMB password was tried ~180 times at every boot;
  * a NAS switched off while mounted froze every route behind _lock;
  * the same USB disk was mounted twice, stacked, at boot.

Hermetic: the mount table is a temporary file standing in for
/proc/self/mountinfo, mount(8) and Lyrion are fakes.

Run with:  python3 -m unittest tests.test_sources_robustness
"""
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

import sources_server as ss


def _done(rc=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


class FakeMounts:
    """A mountinfo file the test edits: mount(8) adds a line, umount drops one."""

    def __init__(self, path):
        self.path = path
        self.entries = []          # (mountpoint, fstype)
        self.write()

    def write(self):
        with open(self.path, "w") as f:
            for i, (mp, fstype) in enumerate(self.entries):
                esc = mp.replace("\\", "\\134").replace(" ", "\\040")
                f.write(f"{100 + i} 1 0:{i} / {esc} rw,relatime shared:1 - {fstype} src rw\n")

    def add(self, mp, fstype="ext4"):
        self.entries.append((mp, fstype))
        self.write()

    def drop(self, mp):
        for i in range(len(self.entries) - 1, -1, -1):
            if self.entries[i][0] == mp:
                del self.entries[i]
                break
        self.write()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="hifi-robust-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.mounts = FakeMounts(os.path.join(self.tmp, "mountinfo"))
        self.root = os.path.join(self.tmp, "music")
        os.makedirs(self.root)
        self.pushed = []
        self.patch("MOUNTINFO", self.mounts.path)
        self.patch("STATE_FILE", os.path.join(self.tmp, "sources.json"))
        self.patch("SAMBA_SHARES_FILE", os.path.join(self.tmp, "smb", "shares.conf"))
        self.patch("MOUNT_ROOT", os.path.join(self.tmp, "smb-mnt"))
        self.patch("USB_ADOPTED_ROOT", os.path.join(self.tmp, "usb-mnt"))
        self.patch("ALLOWED_LOCAL_ROOTS", (self.root, os.path.join(self.tmp, "smb-mnt")))
        self.patch("_ensure_samba_uid_gid", lambda: (os.getuid(), os.getgid()))
        self.patch("_share_group_name", lambda: "hifishare")
        self.patch("_publish_smb_discovery", lambda enabled: None)
        self.patch("_run", lambda *a, **k: _done(rc=1))
        self.patch("_lyrion_push_live", lambda **k: self.pushed.append(k) or True)
        self.patch("_lyrion_mediadirs", lambda: None)
        self.patch("_lyrion_remove_mediadir_live", lambda roots: False)
        ss._smb_auth_failed.clear()
        self.client = ss.app.test_client()

    def patch(self, name, value):
        saved = getattr(ss, name)
        setattr(ss, name, value)
        self.addCleanup(setattr, ss, name, saved)

    def sources(self):
        with open(ss.STATE_FILE) as f:
            return json.load(f)["sources"]


# ── A: smb.conf injection ────────────────────────────────────────────
class SmbConfInjectionTests(Base):
    EVIL = "x\n[iniettata]\n  comment = owned\n  root preexec = /bin/touch /tmp/owned"

    def test_rename_and_new_folder_refuse_control_characters(self):
        self.assertIsNone(ss._safe_name(self.EVIL))
        self.assertIsNone(ss._safe_name("tab\there"))
        self.assertIsNone(ss._safe_name("del\x7f"))
        self.assertEqual(ss._safe_name("Jazz è 100%"), "Jazz è 100%")
        name = "x\n[iniettata]\n  comment = owned"
        r = self.client.post("/api/local/mkdir", json={"path": self.root, "name": name})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["code"], "msg.badName")
        self.assertEqual(os.listdir(self.root), [])

    def test_the_writer_never_emits_an_unsafe_stanza(self):
        for share, path in (("Musica", "/data/music/" + self.EVIL),
                            ("Musica", "/data/music/a\\"),
                            ("Musica", "/data/music/%H"),
                            ("Musica", "/data/music/trailing "),
                            ("Musica", "relative/path"),
                            ("x]\n[evil", "/data/music/ok"),
                            ("global", "/data/music/ok"),
                            ("HOMES", "/data/music/ok")):
            self.assertEqual(ss._samba_share_block(share, path, "hifishare"), [], (share, path))
        self.assertTrue(ss._samba_share_block("Musica-2", "/data/music/100% Jazz", None))

    def test_a_folder_already_on_disk_cannot_inject(self):
        # Made over SSH or from a PC, then present in the state (a restore,
        # or an add from before this fix): skipped, with the others kept.
        evil = os.path.join(self.root, self.EVIL)
        os.makedirs(evil)
        good = os.path.join(self.root, "Good")
        os.makedirs(good)
        state = {"sources": [
            {"id": "local-x", "type": "local", "path": evil, "samba": True, "share": "x"},
            {"id": "local-Good", "type": "local", "path": good, "samba": True, "share": "Good"},
            {"id": "local-dup", "type": "local", "path": good, "samba": True, "share": "good"},
        ]}
        self.patch("load_state", lambda: state)
        ss.regen_samba_shares()
        with open(ss.SAMBA_SHARES_FILE) as f:
            conf = f.read()
        self.assertNotIn("iniettata", conf)
        self.assertNotIn("preexec", conf)
        self.assertEqual(conf.count("[Good]"), 1)
        self.assertNotIn("[good]", conf)

    def test_publishing_such_a_folder_is_refused_with_a_reason(self):
        evil = os.path.join(self.root, self.EVIL)
        os.makedirs(evil)
        r = self.client.post("/api/sources/local", json={"path": evil, "samba": True})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["code"], "msg.unsafeFolderName")
        self.assertFalse(os.path.exists(ss.STATE_FILE))

    def test_a_share_name_is_never_a_reserved_section(self):
        self.patch("_adopted_disk_sources", lambda: [{"share": "Musica"}])
        self.assertEqual(ss._share_name("GLOBAL"), "GLOBAL-2")
        self.assertEqual(ss._share_name("musica"), "musica-2")

    def test_messages_exist_in_both_languages(self):
        for code in ("msg.unsafeFolderName", "msg.badName", "msg.smbBadCredentials"):
            for lang in ("en", "it"):
                self.assertIn(code, ss.SOURCES_I18N[lang], f"{code} missing in {lang}")


# ── B: unique source ids ─────────────────────────────────────────────
class SourceIdTests(Base):
    def add(self, path):
        r = self.client.post("/api/sources/local", json={"path": path})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

    def test_two_folders_with_one_name_get_two_ids(self):
        a = os.path.join(self.root, "_a", "Jazz")
        b = os.path.join(self.root, "_b", "Jazz")
        os.makedirs(a)
        os.makedirs(b)
        self.add(a)
        self.add(b)
        ids = {s["path"]: s["id"] for s in self.sources()}
        self.assertEqual(len(ids), 2)
        self.assertEqual(ids[a], "local-Jazz")              # the first keeps the old format
        self.assertTrue(ids[b].startswith("local-Jazz-"))
        # removing either one removes only that one
        r = self.client.delete(f"/api/sources/{ids[a]}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([s["path"] for s in self.sources()], [b])

    def test_the_same_folder_again_replaces_its_own_entry(self):
        a = os.path.join(self.root, "_a", "Jazz")
        b = os.path.join(self.root, "_b", "Jazz")
        os.makedirs(a)
        os.makedirs(b)
        self.add(a)
        self.add(b)
        before = {s["path"]: s["id"] for s in self.sources()}
        self.add(b)
        self.add(a)
        after = {s["path"]: s["id"] for s in self.sources()}
        self.assertEqual(before, after)
        self.assertEqual(len(self.sources()), 2)

    def test_an_existing_id_is_never_renamed(self):
        a = os.path.join(self.root, "Jazz")
        os.makedirs(a)
        ss.save_state({"sources": [{"id": "local-Jazz", "type": "local", "name": a, "path": a}]})
        self.add(a)
        self.assertEqual([s["id"] for s in self.sources()], ["local-Jazz"])

    def test_smb_shares_with_one_slug_get_their_own_id_and_mountpoint(self):
        first = {"id": "smb-nas-Musica", "type": "smb", "server": "nas", "share": "Musica",
                 "mountpoint": os.path.join(ss.MOUNT_ROOT, "nas-Musica")}
        sid, mp = ss._smb_slot([first], "nas", "Musica è")
        self.assertNotEqual(sid, first["id"])
        self.assertTrue(sid.startswith("smb-nas-Musica-"))
        self.assertNotEqual(ss._mp_key(mp), ss._mp_key(first["mountpoint"]))
        # stable: the same share always gets the same slot
        self.assertEqual(ss._smb_slot([first], "nas", "Musica è"), (sid, mp))
        # the share already there keeps its own, whatever the case
        self.assertEqual(ss._smb_slot([first], "NAS", "musica"), (first["id"], first["mountpoint"]))
        # a first share keeps the old format
        self.assertEqual(ss._smb_slot([], "nas", "Rock Pop"),
                         ("smb-nas-Rock_Pop", os.path.join(ss.MOUNT_ROOT, "nas-Rock_Pop")))
        rp = {"id": "smb-nas-Rock_Pop", "type": "smb", "server": "nas", "share": "Rock Pop",
              "mountpoint": os.path.join(ss.MOUNT_ROOT, "nas-Rock_Pop")}
        sid2, mp2 = ss._smb_slot([rp], "nas", "Rock_Pop")
        self.assertNotEqual(sid2, rp["id"])
        self.assertNotEqual(mp2, rp["mountpoint"])

    def test_a_mountpoint_taken_by_another_source_is_never_reused(self):
        other = {"id": "smb-x", "type": "smb", "server": "x", "share": "y",
                 "mountpoint": os.path.join(ss.MOUNT_ROOT, "nas-Musica")}
        _sid, mp = ss._smb_slot([other], "nas", "Musica")
        self.assertNotEqual(ss._mp_key(mp), ss._mp_key(other["mountpoint"]))

    def test_lyrion_folder_with_a_taken_name_is_imported_under_its_own_id(self):
        a = os.path.join(self.root, "_a", "Jazz")
        b = os.path.join(self.root, "_b", "Jazz")
        os.makedirs(a)
        os.makedirs(b)
        state = {"sources": [{"id": "local-Jazz", "type": "local", "name": b, "path": b}]}
        self.assertTrue(ss._sync_from_lyrion(state, [a, b]))
        ids = {s["path"]: s["id"] for s in state["sources"]}
        self.assertEqual(ids[b], "local-Jazz")
        self.assertTrue(ids[a].startswith("local-Jazz-"))
        self.assertFalse(ss._sync_from_lyrion(state, [a, b]))   # nothing new the second time


# ── C: refused SMB login at boot ─────────────────────────────────────
class SmbAuthRetryTests(Base):
    def setUp(self):
        super().setUp()
        self.src = {"id": "smb-nas-Musica", "type": "smb", "name": "nas/Musica",
                    "server": "nas", "share": "Musica",
                    "mountpoint": os.path.join(ss.MOUNT_ROOT, "nas-Musica")}
        self.state = {"sources": [self.src]}
        self.patch("load_state", lambda: self.state)
        self.patch("regen_samba_shares", lambda: None)
        self.patch("_smb_reachable", lambda server, timeout=5: True)
        self.mount_calls = []
        self.answer = _done(rc=32, stderr="mount error(13): Permission denied")

        def run(cmd, timeout=30):
            if cmd[:1] == ["mount"]:
                self.mount_calls.append(cmd)
                return self.answer
            return _done(rc=1)
        self.patch("_run", run)
        self.sleeps = []
        p = mock.patch.object(ss.time, "sleep", side_effect=self.sleeps.append)
        p.start()
        self.addCleanup(p.stop)

    def test_one_refused_login_and_no_more(self):
        ss.remount_all_retry(attempts=60, delay=5)
        self.assertEqual(len(self.mount_calls), 1)      # one version, one pass, one attempt
        self.assertEqual(self.sleeps, [])               # the loop is over: nothing to retry
        ss.remount_all()
        self.assertEqual(len(self.mount_calls), 1)

    def test_a_new_login_is_tried_again(self):
        ss.remount_all()
        self.src["password"] = "the-right-one"       # a clear login, as before sealing
        self.answer = _done()
        ss.remount_all()
        self.assertEqual(len(self.mount_calls), 2)
        self.assertIsNone(ss._smb_auth_blocked(self.src))

    def test_the_list_says_why_the_share_is_missing(self):
        ss.remount_all()
        self.patch("load_state", lambda: json.loads(json.dumps(self.state)))
        r = self.client.get("/api/sources")
        [item] = r.get_json()["sources"]
        self.assertFalse(item["mounted"])
        self.assertEqual(item["mount_error"]["code"], "msg.smbBadCredentials")
        self.assertTrue(item["mount_error"]["message"])

    def test_an_unreachable_server_is_retried_with_a_backoff(self):
        self.patch("_smb_reachable", lambda server, timeout=5: False)
        ss.remount_all_retry(attempts=16, delay=5, max_delay=60)
        self.assertEqual(self.mount_calls, [])
        self.assertEqual(self.sleeps, [5] * 12 + [10, 20, 40, 60])


# ── E: a NAS switched off while mounted ──────────────────────────────
class DeadNasTests(Base):
    def test_mount_table_parsing(self):
        mp = os.path.join(self.tmp, "with space")
        self.mounts.add(mp, "cifs")
        self.mounts.add(mp, "cifs")
        self.mounts.add(self.root, "ext4")
        table = ss._mount_table()
        self.assertEqual(len(table[mp]), 2)
        self.assertEqual(ss._mount_depth(mp), 2)
        self.assertEqual(ss._mount_depth(self.root), 1)
        self.assertEqual(ss._mount_depth(os.path.join(self.tmp, "nope")), 0)
        self.assertTrue(ss._on_network_fs(os.path.join(mp, "Album", "01.flac")))
        self.assertFalse(ss._on_network_fs(os.path.join(self.root, "Album")))

    def test_a_probe_that_hangs_is_bounded_and_not_stacked(self):
        gate = threading.Event()
        started = []

        def stuck(path):
            started.append(path)
            gate.wait(10)
            return "late"
        t0 = time.monotonic()
        self.assertEqual(ss._bounded_probe(stuck, "/x", "default", timeout=0.2), "default")
        self.assertLess(time.monotonic() - t0, 1)
        self.assertEqual(ss._bounded_probe(stuck, "/x", "default", timeout=0.2), "default")
        self.assertEqual(len(started), 1)           # the second call did not start another
        gate.set()
        time.sleep(0.1)
        self.assertEqual(ss._bounded_probe(lambda p: "ok", "/x", "default"), "ok")

    def test_the_list_does_not_hold_the_lock_on_a_dead_share(self):
        mp = os.path.join(ss.MOUNT_ROOT, "nas-Musica")
        os.makedirs(mp)
        self.mounts.add(mp, "cifs")
        state = {"sources": [{"id": "smb-nas-Musica", "type": "smb", "server": "nas",
                              "share": "Musica", "mountpoint": mp}]}
        self.patch("load_state", lambda: json.loads(json.dumps(state)))
        gate = threading.Event()
        self.addCleanup(gate.set)

        def dead_statvfs(path):
            gate.wait(20)
            return None
        self.patch("_fs_usage", dead_statvfs)
        result = {}

        def call():
            result["r"] = self.client.get("/api/sources")
        t = threading.Thread(target=call)
        t0 = time.monotonic()
        t.start()
        time.sleep(0.3)
        self.assertTrue(ss._lock.acquire(timeout=0.5), "_lock held while probing a dead share")
        ss._lock.release()
        t.join(10)
        self.assertLess(time.monotonic() - t0, ss._PROBE_TIMEOUT + 3)
        [item] = result["r"].get_json()["sources"]
        self.assertTrue(item["mounted"])
        self.assertIsNone(item["usage"])
        # the next poll does not wait again while the first probe is stuck
        t1 = time.monotonic()
        self.client.get("/api/sources")
        self.assertLess(time.monotonic() - t1, 1)

    def test_removing_a_disk_flushes_only_that_disk(self):
        mp = os.path.join(ss.USB_ADOPTED_ROOT, "STICK-1234")
        os.makedirs(mp)
        self.mounts.add(mp)
        calls = []

        def run(cmd, timeout=30):
            calls.append(list(cmd))
            if cmd[0] == "umount":
                self.mounts.drop(cmd[-1])
            return _done()
        self.patch("_run", run)
        ok, lazy = ss.umount_clean(mp)
        self.assertTrue(ok)
        self.assertFalse(lazy)
        self.assertNotIn(["sync"], calls)
        self.assertIn(["sync", "-f", mp], calls)

    def test_a_share_is_unmounted_without_touching_it(self):
        mp = os.path.join(ss.MOUNT_ROOT, "nas-Musica")
        self.mounts.add(mp, "cifs")
        calls = []
        self.patch("_run", lambda cmd, timeout=30: calls.append(list(cmd)) or self.mounts.drop(cmd[-1]) or _done())
        with mock.patch("os.path.ismount", side_effect=AssertionError("stat of a dead share")):
            ss.umount(mp)
        self.assertEqual(calls, [["umount", "-l", "-c", ss._mp_key(mp)]])


# ── F: the same USB disk mounted twice ───────────────────────────────
class StackedMountTests(Base):
    def setUp(self):
        super().setUp()
        self.mp = os.path.join(ss.USB_ADOPTED_ROOT, "STICK-1234")
        self.src = {"id": "usb-STICK", "type": "usb", "partuuid": "1234-01",
                    "fstype": "ext4", "mountpoint": self.mp}
        self.mount_calls = []

        def run(cmd, timeout=30):
            if cmd[0] == "mount":
                self.mount_calls.append(cmd)
                time.sleep(0.3)                     # long enough for the other thread to look
                self.mounts.add(cmd[-1])
                return _done()
            if cmd[0] == "umount":
                self.mounts.drop(cmd[-1])
                return _done()
            return _done()
        self.patch("_run", run)

    def test_two_mounts_at_once_mount_once(self):
        threads = [threading.Thread(target=ss.mount_usb_adopted, args=(dict(self.src),))
                   for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual(len(self.mount_calls), 1)
        self.assertEqual(ss._mount_depth(self.mp), 1)

    def test_a_stack_left_by_an_older_version_is_fully_removed(self):
        os.makedirs(self.mp)
        self.mounts.add(self.mp)
        self.mounts.add(self.mp)
        ok, _lazy = ss.umount_clean(self.mp)
        self.assertTrue(ok)
        self.assertEqual(ss._mount_depth(self.mp), 0)


if __name__ == "__main__":
    unittest.main()
