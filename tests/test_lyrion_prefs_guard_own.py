"""own_tree() must re-own only the entries that belong to the wrong user, skip
the playlist folder, and never let a chown error stop Lyrion from starting.

Lyrion runs as squeezeboxserver (uid 900). When its cache/state tree is owned by
root — the /var graft at an image's first boot, or a backup restore — the first
NEW plugin install dies on `mkdir ...: Permission denied` and the service loops
down (field report, 2026-10-23: Spotty). hifi-lyrion-prefs-guard.py repairs the
ownership on every start; this checks it does so surgically.

No real chown: lstat/chown are injected, so it runs as any user in CI.

Run with:  python tests/test_lyrion_prefs_guard_own.py
"""
import importlib.util
import os
import sys
import tempfile
import unittest

_GUARD = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'distro', 'config',
    'includes.chroot', 'usr', 'local', 'sbin', 'hifi-lyrion-prefs-guard.py')
_spec = importlib.util.spec_from_file_location('hifi_lyrion_prefs_guard', _GUARD)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


class FakeStat:
    def __init__(self, uid, gid):
        self.st_uid = uid
        self.st_gid = gid


class OwnTree(unittest.TestCase):
    OWNER = (900, 65534)        # squeezeboxserver:nogroup
    OTHER = (0, 0)              # root:root

    def setUp(self):
        # A small tree: a root dir, a file owned by root, a file already right,
        # a nested dir owned by root, and a playlists/ subtree to be left alone.
        self.tmp = tempfile.mkdtemp()
        self.wrong = {              # paths that start out owned by root
            self.tmp,
            os.path.join(self.tmp, 'server.prefs'),
            os.path.join(self.tmp, 'cache'),
            os.path.join(self.tmp, 'cache', 'InstalledPlugins'),
            os.path.join(self.tmp, 'playlists'),
            os.path.join(self.tmp, 'playlists', 'kept.m3u'),
        }
        self.right = {              # already squeezeboxserver — must not be touched
            os.path.join(self.tmp, 'server.ok'),
        }
        for rel in ('cache', 'cache/InstalledPlugins', 'playlists'):
            os.makedirs(os.path.join(self.tmp, rel), exist_ok=True)
        for rel in ('server.prefs', 'server.ok', 'playlists/kept.m3u'):
            open(os.path.join(self.tmp, rel), 'w').close()

        self.chowned = []

        def fake_lstat(path):
            uid, gid = self.OTHER if path in self.wrong else self.OWNER
            return FakeStat(uid, gid)

        def fake_chown(path, uid, gid):
            self.chowned.append((path, uid, gid))

        self.fake_lstat = fake_lstat
        self.fake_chown = fake_chown

    def _run(self, skip=()):
        return guard.own_tree(
            (self.tmp,), self.OWNER, skip=skip,
            lstat=self.fake_lstat, chown=self.fake_chown)

    def test_only_wrong_owner_entries_are_fixed(self):
        fixed = self._run()
        touched = {p for p, _, _ in self.chowned}
        # every chown targets a wrong-owner entry, each at most once
        self.assertTrue(touched <= self.wrong)
        self.assertEqual(len(self.chowned), len(touched))
        # the already-correct file is never chowned
        self.assertTrue(self.right.isdisjoint(touched))
        # all chowns set squeezeboxserver:nogroup
        self.assertTrue(all((u, g) == self.OWNER for _, u, g in self.chowned))
        self.assertEqual(fixed, len(touched))

    def test_playlists_subtree_is_skipped(self):
        self._run(skip=(os.path.join(self.tmp, 'playlists'),))
        touched = {p for p, _, _ in self.chowned}
        self.assertNotIn(os.path.join(self.tmp, 'playlists'), touched)
        self.assertNotIn(os.path.join(self.tmp, 'playlists', 'kept.m3u'), touched)
        # the other wrong entries are still fixed
        self.assertIn(os.path.join(self.tmp, 'cache'), touched)
        self.assertIn(os.path.join(self.tmp, 'server.prefs'), touched)

    def test_chown_error_does_not_propagate(self):
        def boom(path, uid, gid):
            raise OSError('read-only file system')
        fixed = guard.own_tree(
            (self.tmp,), self.OWNER, lstat=self.fake_lstat, chown=boom)
        self.assertEqual(fixed, 0)     # nothing counted as fixed, no exception

    def test_no_owner_is_a_noop(self):
        self.assertEqual(
            guard.own_tree((self.tmp,), None,
                           lstat=self.fake_lstat, chown=self.fake_chown), 0)
        self.assertEqual(self.chowned, [])

    def test_missing_tree_is_skipped(self):
        fixed = guard.own_tree(
            ('/no/such/tree',), self.OWNER,
            lstat=self.fake_lstat, chown=self.fake_chown)
        self.assertEqual(fixed, 0)
        self.assertEqual(self.chowned, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
