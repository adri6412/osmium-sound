"""Unit tests for the web admin's file manager.

The service runs as root, so every one of these endpoints is one bad path
away from `rm -rf` on the system. The confinement and the protected-path list
are therefore tested first and hardest; the copy/move/delete work itself runs
against real files in a temp tree, because that is what has to be trusted not
to lose somebody's music.
"""
import os
import shutil
import tempfile
import unittest

import sources_server as ss


class FileOpsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hifi-files-")
        self.root = os.path.join(self.tmp, "music")
        os.makedirs(os.path.join(self.root, "Album", "CD1"))
        with open(os.path.join(self.root, "Album", "CD1", "01.flac"), "wb") as f:
            f.write(b"x" * 1024)
        with open(os.path.join(self.root, "Album", "cover.jpg"), "wb") as f:
            f.write(b"y" * 512)
        os.makedirs(os.path.join(self.root, "Dest"))

        self._saved = (ss.ALLOWED_LOCAL_ROOTS, ss._BROWSE_ROOTS,
                       ss._ensure_samba_uid_gid, ss._lyrion_rescan, ss.load_state)
        ss.ALLOWED_LOCAL_ROOTS = (self.root,)
        ss._BROWSE_ROOTS = (self.root,)
        ss._ensure_samba_uid_gid = lambda: (0, 0)   # no useradd from a test
        ss._lyrion_rescan = lambda: None
        ss.load_state = lambda: {"sources": []}

    def tearDown(self):
        (ss.ALLOWED_LOCAL_ROOTS, ss._BROWSE_ROOTS, ss._ensure_samba_uid_gid,
         ss._lyrion_rescan, ss.load_state) = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def targets(self, data, need_dest=False):
        # _file_op_targets() builds Flask error responses, so it needs an app
        # context even though nothing here goes over HTTP.
        with ss.app.app_context():
            return ss._file_op_targets(data, need_dest=need_dest)

    def run_job(self, op, paths, dest=None):
        jid = ss._file_job_new(op)
        ss._file_worker(jid, op, paths, dest)
        return ss._FILE_JOBS[jid]


class ConfinementTests(FileOpsBase):
    def test_paths_outside_the_roots_are_refused(self):
        for bad in ("/etc/passwd", "/", os.path.join(self.root, "..", "escape"),
                    self.tmp):
            self.assertIsNone(ss._local_path_allowed(bad), bad)

    def test_a_symlink_out_of_the_root_does_not_escape(self):
        # realpath() resolves before the prefix check, so a link planted from
        # a PC over the network share cannot widen what the API may touch.
        link = os.path.join(self.root, "escape")
        os.symlink("/etc", link)
        self.assertIsNone(ss._local_path_allowed(os.path.join(link, "passwd")))

    def test_op_targets_refuse_a_path_outside(self):
        _p, _d, err = self.targets({"paths": ["/etc/passwd"]}, need_dest=False)
        self.assertIsNotNone(err)

    def test_op_targets_refuse_a_missing_path(self):
        _p, _d, err = self.targets(
            {"paths": [os.path.join(self.root, "nope")]}, need_dest=False)
        self.assertIsNotNone(err)

    def test_too_many_items_at_once(self):
        many = [os.path.join(self.root, "Album")] * (ss._FILE_MAX_ITEMS + 1)
        _p, _d, err = self.targets({"paths": many}, need_dest=False)
        self.assertIsNotNone(err)


class ProtectedPathTests(FileOpsBase):
    def test_a_root_is_never_deletable(self):
        self.assertIn(os.path.realpath(self.root), ss._protected_paths())
        _p, _d, err = self.targets({"paths": [self.root]}, need_dest=False)
        self.assertIsNotNone(err)

    def test_a_source_mountpoint_is_never_deletable(self):
        # Deleting it does not remove the source, it only leaves a broken one
        # that looks exactly like a NAS that lost its music.
        mp = os.path.join(self.root, "Album")
        ss.load_state = lambda: {"sources": [{"id": "x", "mountpoint": mp}]}
        self.assertIn(os.path.realpath(mp), ss._protected_paths())
        _p, _d, err = self.targets({"paths": [mp]}, need_dest=False)
        self.assertIsNotNone(err)

    def test_an_ordinary_folder_is_fine(self):
        paths, _d, err = self.targets(
            {"paths": [os.path.join(self.root, "Album")]}, need_dest=False)
        self.assertIsNone(err)
        self.assertEqual(len(paths), 1)


class NameTests(unittest.TestCase):
    def test_rejects_separators_and_dot_entries(self):
        for bad in ("", "a/b", ".", "..", ".hidden", "x" * 256, None):
            self.assertIsNone(ss._safe_name(bad), bad)

    def test_accepts_a_normal_name(self):
        self.assertEqual(ss._safe_name("  Pink Floyd  "), "Pink Floyd")


class UniqueNameTests(FileOpsBase):
    def test_a_clash_never_overwrites(self):
        # There is no undo here: losing a folder of FLACs to a name clash is
        # not a recoverable mistake.
        existing = os.path.join(self.root, "Album")
        self.assertEqual(ss._unique_name(existing), existing + " (2)")

    def test_a_file_keeps_its_extension(self):
        f = os.path.join(self.root, "Album", "cover.jpg")
        self.assertTrue(ss._unique_name(f).endswith(" (2).jpg"))


class CopyMoveDeleteTests(FileOpsBase):
    def test_copy_keeps_the_original_and_the_tree(self):
        job = self.run_job("copy", [os.path.join(self.root, "Album")],
                           os.path.join(self.root, "Dest"))
        self.assertEqual(job["state"], "done", job.get("detail"))
        self.assertTrue(os.path.exists(
            os.path.join(self.root, "Dest", "Album", "CD1", "01.flac")))
        self.assertTrue(os.path.exists(os.path.join(self.root, "Album", "cover.jpg")))
        self.assertEqual(job["total"], 1536)

    def test_copy_into_the_same_folder_does_not_overwrite(self):
        job = self.run_job("copy", [os.path.join(self.root, "Album", "cover.jpg")],
                           os.path.join(self.root, "Album"))
        self.assertEqual(job["state"], "done")
        self.assertTrue(os.path.exists(os.path.join(self.root, "Album", "cover (2).jpg")))
        self.assertTrue(os.path.exists(os.path.join(self.root, "Album", "cover.jpg")))

    def test_move_removes_the_original(self):
        job = self.run_job("move", [os.path.join(self.root, "Album")],
                           os.path.join(self.root, "Dest"))
        self.assertEqual(job["state"], "done", job.get("detail"))
        self.assertFalse(os.path.exists(os.path.join(self.root, "Album")))
        self.assertTrue(os.path.exists(
            os.path.join(self.root, "Dest", "Album", "CD1", "01.flac")))

    def test_delete_removes_a_whole_tree(self):
        job = self.run_job("delete", [os.path.join(self.root, "Album")])
        self.assertEqual(job["state"], "done", job.get("detail"))
        self.assertFalse(os.path.exists(os.path.join(self.root, "Album")))

    def test_a_failure_is_reported_as_a_failed_job(self):
        job = self.run_job("delete", [os.path.join(self.root, "gone")])
        self.assertEqual(job["state"], "error")
        self.assertEqual(job["code"], "msg.fileOpFailed")

    def test_copying_a_folder_into_itself_is_refused(self):
        album = os.path.join(self.root, "Album")
        _p, _d, err = self.targets({"paths": [album], "dest": album + "/CD1"},
                                          need_dest=True)
        self.assertIsNotNone(err)


class MessageCatalogTests(unittest.TestCase):
    def test_every_file_message_exists_in_both_languages(self):
        for code in ("msg.fileProtected", "msg.fileReadOnly", "msg.fileIntoItself",
                     "msg.fileExists", "msg.badName", "msg.fileOpFailed",
                     "msg.jobNotFound"):
            for lang in ("en", "it"):
                self.assertIn(code, ss.SOURCES_I18N[lang], f"{code} missing in {lang}")


if __name__ == "__main__":
    unittest.main()
