"""Tests for hifi_diskguard.py — the system disk's reserve for Lyrion — and
for hifi-lyrion-prefs-guard.py, which repairs Lyrion's prefs after a full
disk.

Hermetic: statvfs and the "system disk" device are faked.

Run with:  python3 tests/test_diskguard.py
"""
import importlib.util
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

import hifi_diskguard as dg  # noqa: E402

GB = 1000 ** 3


def fake_vfs(total, free):
    return mock.patch.object(dg, '_vfs', lambda path: (total, free))


class ReserveTest(unittest.TestCase):
    def test_reserve_size(self):
        self.assertEqual(dg.reserve_for(5 * GB), dg.MIN_RESERVE)            # a 16 GB disk's data: 512 MiB
        self.assertEqual(dg.reserve_for(20 * GB), int(20 * GB * 0.05))      # in between: 5 %
        self.assertEqual(dg.reserve_for(1000 * GB), dg.MAX_RESERVE)         # large disk: 2 GiB

    def test_room_and_check(self):
        with mock.patch.object(dg, 'on_system_disk', lambda p: True), fake_vfs(20 * GB, 4 * GB):    # reserve 1 GB
            self.assertEqual(dg.room('/data/music'), 3 * GB)
            dg.check('/data/music', 2 * GB)
            with self.assertRaises(dg.NoRoom) as cm:
                dg.check('/data/music', 4 * GB)
            self.assertEqual((cm.exception.need, cm.exception.room, cm.exception.reserve), (4 * GB, 3 * GB, 1 * GB))
            self.assertEqual(cm.exception.errno, 28)

    def test_other_disks_are_free(self):
        with mock.patch.object(dg, 'on_system_disk', lambda p: False), fake_vfs(100 * GB, 1 * GB):
            self.assertIsNone(dg.room('/mnt/usb/x'))
            dg.check('/mnt/usb/x', 50 * GB)
            b = dg.Budget('/mnt/usb/x')
            b.add(10 * GB)

    def test_budget_stops_mid_copy(self):
        state = {'free': 6 * GB}
        with mock.patch.object(dg, 'on_system_disk', lambda p: True), \
                mock.patch.object(dg, '_vfs', lambda p: (100 * GB, state['free'])):
            b = dg.Budget('/data/music/a.flac')
            b.add(dg.RECHECK_BYTES)               # still above the reserve
            state['free'] = 1 * GB                 # below the 2 GiB of a 100 GB disk
            with self.assertRaises(dg.NoRoom):
                b.add(dg.RECHECK_BYTES)

    def test_on_system_disk_for_a_path_not_yet_there(self):
        with tempfile.TemporaryDirectory() as d:
            dev = os.stat(d).st_dev
            self.assertTrue(dg.on_system_disk(os.path.join(d, 'new', 'deeper', 'f.flac'), sys_dev=dev))
            self.assertFalse(dg.on_system_disk(d, sys_dev=dev + 1))

    def test_status_levels(self):
        with mock.patch.object(dg.os.path, 'exists', lambda p: True):
            with fake_vfs(100 * GB, 40 * GB):
                self.assertEqual(dg.status()['level'], 'ok')
            with fake_vfs(100 * GB, 9 * GB):
                self.assertEqual(dg.status()['level'], 'warn')
            with fake_vfs(100 * GB, 2 * GB):
                s = dg.status()
                self.assertEqual((s['level'], s['room']), ('full', 0))

    def test_message(self):
        e = dg.NoRoom('/x', 3 * GB, int(1.2 * GB), int(5.1 * GB))
        self.assertIn('3,0 GB', dg.message(e, 'it'))
        self.assertIn('5.1 GB', dg.message(e, 'en', stopped=True))


def load_prefs_guard():
    path = os.path.join(HERE, '..', 'distro', 'config', 'includes.chroot', 'usr', 'local', 'sbin',
                        'hifi-lyrion-prefs-guard.py')
    spec = importlib.util.spec_from_file_location('prefs_guard', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.log = lambda msg: None
    mod._owner = lambda: None
    return mod


class PrefsGuardTest(unittest.TestCase):
    def setUp(self):
        self.pg = load_prefs_guard()
        self.dir = tempfile.TemporaryDirectory()
        self.root = self.dir.name
        os.makedirs(os.path.join(self.root, 'plugin'))
        self.write('server.prefs', "---\nlanguage: IT\nmediadirs:\n  - /data/music\n")
        self.write('plugin/a.prefs', "---\nfoo: 1\n")

    def tearDown(self):
        self.dir.cleanup()

    def write(self, rel, text):
        with open(os.path.join(self.root, rel), 'w') as f:
            f.write(text)

    def read(self, rel):
        with open(os.path.join(self.root, rel)) as f:
            return f.read()

    def test_save_then_restore(self):
        self.assertEqual(self.pg.guard(self.root), (['plugin/a.prefs', 'server.prefs'], [], []))
        self.write('server.prefs', '')                       # the half-written file of a full disk
        self.write('plugin/a.prefs', "---\nfoo: [1,\n")      # cut in the middle
        saved, restored, moved = self.pg.guard(self.root)
        self.assertEqual(sorted(restored), ['plugin/a.prefs', 'server.prefs'])
        self.assertIn('mediadirs', self.read('server.prefs'))

    def test_no_good_copy_moves_aside(self):
        self.write('plugin/b.prefs', '')
        _, _, moved = self.pg.guard(self.root)
        self.assertEqual(moved, ['plugin/b.prefs'])
        self.assertTrue(os.path.exists(os.path.join(self.root, 'plugin', 'b.prefs.broken')))

    def test_perl_tags_are_fine(self):
        self.write('plugin/c.prefs', "---\nx: !!perl/hash:Foo\n  a: 1\n")
        self.assertTrue(self.pg.readable(os.path.join(self.root, 'plugin', 'c.prefs')))


if __name__ == '__main__':
    unittest.main()
