"""Unit tests for the playlist-folder half of the field reports:

  * Windows path separators in playlists copied onto the box from a PC.
  * The appliance's own playlist folder being refusable as a network share.

Both run against real files in a temp directory — the separator rewrite is
byte-for-byte work on real playlist files, which is exactly what has to be
trusted not to corrupt somebody's library.
"""
import json
import os
import shutil
import tempfile
import unittest

import sources_server as ss


class SeparatorRewriteTests(unittest.TestCase):
    def norm(self, raw, is_pls=False):
        return ss._normalize_playlist_bytes(raw, is_pls)

    def test_m3u_backslashes_become_slashes(self):
        out, changed = self.norm(b"Music\\Artist\\01 Track.flac\n")
        self.assertTrue(changed)
        self.assertEqual(out, b"Music/Artist/01 Track.flac\n")

    def test_mixed_separators_in_one_file(self):
        raw = (b"#EXTM3U\n"
               b"#EXTINF:214,Artist - A\n"
               b"/mnt/hifi-internal/disk/Artist\\A.flac\n"
               b"/mnt/hifi-internal/disk/Artist/B.flac\n")
        out, changed = self.norm(raw)
        self.assertTrue(changed)
        self.assertIn(b"/mnt/hifi-internal/disk/Artist/A.flac", out)
        self.assertIn(b"/mnt/hifi-internal/disk/Artist/B.flac", out)

    def test_directives_are_left_alone(self):
        # A backslash inside an #EXTINF title is part of the title, not a path.
        raw = b"#EXTINF:1,AC\\DC - Back In Black\nMusic\\ACDC\\track.flac\n"
        out, changed = self.norm(raw)
        self.assertTrue(changed)
        self.assertIn(b"#EXTINF:1,AC\\DC - Back In Black", out)
        self.assertIn(b"Music/ACDC/track.flac", out)

    def test_urls_are_left_alone(self):
        raw = b"http://stream.example/a\\b\n"
        out, changed = self.norm(raw)
        self.assertFalse(changed)
        self.assertEqual(out, raw)

    def test_crlf_and_trailing_newline_survive(self):
        raw = b"a\\b.flac\r\nc\\d.flac\r\n"
        out, changed = self.norm(raw)
        self.assertTrue(changed)
        self.assertEqual(out, b"a/b.flac\r\nc/d.flac\r\n")

    def test_non_utf8_bytes_survive(self):
        # cp1252 "Bj<f6>rk": a .m3u declares no encoding, so the rewrite must
        # not decode the file at all.
        raw = b"Music\\Bj\xf6rk\\track.flac\n"
        out, changed = self.norm(raw)
        self.assertTrue(changed)
        self.assertEqual(out, b"Music/Bj\xf6rk/track.flac\n")

    def test_pls_only_touches_file_entries(self):
        raw = (b"[playlist]\n"
               b"NumberOfEntries=1\n"
               b"File1=D:\\Music\\a.flac\n"
               b"Title1=A\\B\n")
        out, changed = self.norm(raw, is_pls=True)
        self.assertTrue(changed)
        self.assertIn(b"File1=D:/Music/a.flac", out)
        self.assertIn(b"Title1=A\\B", out)

    def test_already_unix_is_not_rewritten(self):
        raw = b"#EXTM3U\n/mnt/music/a.flac\n"
        out, changed = self.norm(raw)
        self.assertFalse(changed)
        self.assertEqual(out, raw)


class RewriteOnDiskTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="hifi-playlist-test-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def read(self, path):
        with open(path, "rb") as f:
            return f.read()

    def write(self, name, raw, age=3600):
        path = os.path.join(self.root, name)
        with open(path, "wb") as f:
            f.write(raw)
        old = os.stat(path).st_mtime - age
        os.utime(path, (old, old))
        return path

    def test_pass_rewrites_and_is_idempotent(self):
        path = self.write("mine.m3u", b"Music\\a.flac\n")
        ss._playlist_seen.clear()
        ss._normalize_playlists(self.root)
        self.assertEqual(self.read(path), b"Music/a.flac\n")
        before = os.stat(path).st_mtime_ns
        ss._normalize_playlists(self.root)
        self.assertEqual(os.stat(path).st_mtime_ns, before)

    def test_mode_is_preserved(self):
        path = self.write("mine.m3u", b"Music\\a.flac\n")
        os.chmod(path, 0o664)
        ss._playlist_seen.clear()
        ss._normalize_playlists(self.root)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o664)

    def test_a_file_still_being_copied_is_left_for_the_next_pass(self):
        # Freshly written (age 0): a copy over SMB may still be in flight.
        path = self.write("landing.m3u", b"Music\\a.flac\n", age=0)
        ss._playlist_seen.clear()
        ss._normalize_playlists(self.root)
        self.assertEqual(self.read(path), b"Music\\a.flac\n")

    def test_other_files_are_not_touched(self):
        path = self.write("track.flac", b"not\\a playlist\n")
        ss._playlist_seen.clear()
        ss._normalize_playlists(self.root)
        self.assertEqual(self.read(path), b"not\\a playlist\n")

    def test_oversized_file_is_skipped(self):
        raw = b"a\\b.flac\n" * 8
        path = self.write("big.m3u", raw)
        ss._playlist_seen.clear()
        orig = ss.NORMALIZE_MAX_BYTES
        ss.NORMALIZE_MAX_BYTES = 4
        try:
            ss._normalize_playlists(self.root)
        finally:
            ss.NORMALIZE_MAX_BYTES = orig
        self.assertEqual(self.read(path), raw)


class _Grp:
    def __init__(self, gid):
        self.gr_gid = gid


class ShareGroupTests(unittest.TestCase):
    """The group hifimusic and Lyrion have in common. It is consulted from the
    ownership path, which runs on every mount and every share regeneration, so
    "how often does it actually do work" is part of the contract."""

    def setUp(self):
        for name, value in (("_share_group_gid", None),
                            ("_share_group_done", False),
                            ("_share_group_next_try", 0.0)):
            self.addCleanup(setattr, ss, name, getattr(ss, name))
            setattr(ss, name, value)
        self.exists = True
        self.members = {"hifimusic": False, "squeezeboxserver": False}
        self.commands = []
        for name, value in (("_run", self.fake_run),
                            ("_in_group", self.fake_in_group),
                            ("_restart_lyrion_for_group", lambda: None)):
            self.addCleanup(setattr, ss, name, getattr(ss, name))
            setattr(ss, name, value)
        import grp
        self.addCleanup(setattr, grp, "getgrnam", grp.getgrnam)
        grp.getgrnam = self.fake_getgrnam

    def fake_getgrnam(self, name):
        if name == ss.SHARE_GROUP and self.exists:
            return _Grp(902)
        raise KeyError(name)

    def fake_in_group(self, user, gid):
        return self.members.get(user)      # None = no such user

    def fake_run(self, argv, **kw):
        self.commands.append(argv)
        if argv[0] == "groupadd":
            self.exists = True
        if argv[0] == "usermod":
            self.members[argv[-1]] = True
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    def test_it_creates_the_group_and_adds_both_writers(self):
        self.exists = False
        self.assertEqual(ss._ensure_share_group(), 902)
        self.assertIn(["groupadd", "-r", ss.SHARE_GROUP], self.commands)
        added = {c[-1] for c in self.commands if c[0] == "usermod"}
        self.assertEqual(added, {"hifimusic", "squeezeboxserver"})

    def test_a_settled_device_never_shells_out_again(self):
        self.members = {"hifimusic": True, "squeezeboxserver": True}
        self.assertEqual(ss._ensure_share_group(), 902)
        for _ in range(50):
            ss._ensure_share_group()
        self.assertEqual(self.commands, [])

    def test_lyrion_not_installed_yet_is_retried_later_not_every_call(self):
        # A device that follows another room's server has no squeezeboxserver
        # user at all; the work must not be redone on every mount either.
        self.members = {"hifimusic": True}
        self.assertEqual(ss._ensure_share_group(), 902)
        self.assertFalse(ss._share_group_done)
        before = len(self.commands)
        ss._ensure_share_group()
        self.assertEqual(len(self.commands), before)
        ss._share_group_next_try = 0.0          # a minute later
        self.members["squeezeboxserver"] = False
        self.assertEqual(ss._ensure_share_group(), 902)
        self.assertTrue(ss._share_group_done)

    def test_a_group_that_cannot_be_created_does_not_fork_every_call(self):
        self.exists = False

        def failing_run(argv, **kw):
            self.commands.append(argv)
            return type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()

        ss._run = failing_run
        self.assertIsNone(ss._ensure_share_group())
        self.assertIsNone(ss._ensure_share_group())
        self.assertEqual(len(self.commands), 1)


class ShareStanzaTests(unittest.TestCase):
    """What smb.conf gets for a published folder. The owner report this
    guards: files could be copied in and edited from a PC, but deleting them
    answered "you don't have permission", and `sudo rm` over SSH was the only
    way out."""

    def block(self, group="hifishare"):
        return ss._samba_share_block("Playlist", "/srv/playlists", group)

    def test_delete_of_another_account_s_file_is_not_vetoed(self):
        self.assertIn("   delete readonly = yes", self.block())

    def test_new_files_are_group_writable(self):
        # Not just the mask: a Windows client asking for 0644 must still end
        # up writable by the other account.
        self.assertIn("   force create mode = 0664", self.block())

    def test_new_subfolders_keep_the_shared_group(self):
        self.assertIn("   force directory mode = 2775", self.block())

    def test_the_shared_group_is_forced_when_there_is_one(self):
        self.assertIn("   force group = hifishare", self.block())

    def test_a_device_without_the_group_still_gets_a_valid_share(self):
        lines = self.block(group=None)
        self.assertFalse(any(l.startswith("   force group") for l in lines))
        self.assertIn("   force user = " + ss.SAMBA_USER, lines)


class PlaylistFolderAsShareTests(unittest.TestCase):
    """The picker offers the default playlist folder, so adding it must be
    allowed — and it must not become a music folder when it is."""

    def test_default_playlistdir_is_offered_by_the_browser(self):
        self.assertIn(ss.DEFAULT_PLAYLISTDIR, ss._BROWSE_ROOTS)

    def test_default_playlistdir_is_outside_the_media_roots(self):
        # If this ever changes, the special case in api_add_local() is dead
        # code rather than the fix for "the folder is not available".
        self.assertIsNone(ss._local_path_allowed(ss.DEFAULT_PLAYLISTDIR))

    def test_a_share_only_source_never_reaches_lyrion(self):
        state = {"sources": [
            {"id": "local-playlists", "type": "local", "media": False,
             "path": ss.DEFAULT_PLAYLISTDIR, "samba": True},
        ]}
        self.assertEqual(ss.current_paths(state), [])


class AddPlaylistFolderAsShareTests(unittest.TestCase):
    """The reported failure, end to end through the route: the folder picker
    offers the playlist folder and selecting it answered "folder not
    available"."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="hifi-share-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.playlists = os.path.join(self.root, "playlists")
        os.makedirs(self.playlists)
        self.pushed = []

        patches = {
            "DEFAULT_PLAYLISTDIR": self.playlists,
            "STATE_FILE": os.path.join(self.root, "sources.json"),
            "SAMBA_SHARES_FILE": os.path.join(self.root, "smb", "shares.conf"),
            # No root here: ownership and systemctl are not what is under test.
            "_ensure_samba_uid_gid": lambda: (os.getuid(), os.getgid()),
            "_share_group_name": lambda: "hifishare",
            "_run": lambda *a, **k: type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})(),
            "_publish_smb_discovery": lambda enabled: None,
            "_lyrion_push_live": lambda **k: self.pushed.append(k),
        }
        for name, value in patches.items():
            saved = getattr(ss, name)
            setattr(ss, name, value)
            self.addCleanup(setattr, ss, name, saved)
        self.client = ss.app.test_client()

    def sources(self):
        with open(os.path.join(self.root, "sources.json")) as f:
            return json.load(f)["sources"]

    def test_it_can_be_published(self):
        r = self.client.post("/api/sources/local",
                             json={"path": self.playlists, "samba": True})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertTrue(r.get_json()["success"])
        [src] = self.sources()
        self.assertTrue(src["samba"])
        self.assertIs(src["media"], False)

    def test_publishing_it_does_not_add_a_music_folder(self):
        self.client.post("/api/sources/local",
                         json={"path": self.playlists, "samba": True})
        self.assertEqual(self.pushed, [])
        self.assertEqual(ss.current_paths({"sources": self.sources()}), [])

    def test_the_share_lands_in_smb_conf(self):
        self.client.post("/api/sources/local",
                         json={"path": self.playlists, "samba": True})
        with open(os.path.join(self.root, "smb", "shares.conf")) as f:
            conf = f.read()
        self.assertIn(f"path = {self.playlists}", conf)
        self.assertIn("delete readonly = yes", conf)

    def test_picking_it_with_sharing_off_unshares_it(self):
        self.client.post("/api/sources/local",
                         json={"path": self.playlists, "samba": True})
        self.client.post("/api/sources/local",
                         json={"path": self.playlists, "samba": False})
        self.assertEqual(self.sources(), [])

    def test_a_path_outside_the_roots_is_still_refused(self):
        r = self.client.post("/api/sources/local",
                             json={"path": "/etc", "samba": True})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
