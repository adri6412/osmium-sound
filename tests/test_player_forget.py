"""Tests for the players of this device that come and go — audio zones and
Bluetooth speakers: when one stops (its DAC unplugged, the speaker switched
off or removed) Lyrion is told to forget it, instead of keeping a dead player
in its list (hifi_squeezelite.py record_player / forget_unit / run_zone).

Hermetic: the run directory is temporary, Lyrion and squeezelite are fakes.

Run with:  python3 tests/test_player_forget.py
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import hifi_squeezelite as sq  # noqa: E402


class LmsHostTest(unittest.TestCase):
    def test_hosts(self):
        self.assertEqual(sq._lms_host('127.0.0.1'), '127.0.0.1')
        self.assertEqual(sq._lms_host('nas.local:3483'), 'nas.local')
        self.assertEqual(sq._lms_host('[::1]:3483'), '[::1]')
        self.assertEqual(sq._lms_host('fe80::1'), '[fe80::1]')
        self.assertEqual(sq._lms_host(''), '127.0.0.1')


class ForgetTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.run = self.dir.name

    def tearDown(self):
        self.dir.cleanup()

    def test_forget_sends_client_forget(self):
        sent = {}

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{}'

        def opener(req, timeout):
            sent['url'] = req.full_url
            sent['body'] = json.loads(req.data)
            return Resp()
        self.assertTrue(sq.forget_player('nas.local:3483', '02:11:22:33:44:55', opener=opener))
        self.assertEqual(sent['url'], 'http://nas.local:9000/jsonrpc.js')
        self.assertEqual(sent['body']['params'], ['02:11:22:33:44:55', ['client', 'forget']])

    def test_forget_never_raises(self):
        def opener(req, timeout):
            raise OSError('connection refused')
        with mock.patch('sys.stderr'):
            self.assertFalse(sq.forget_player('127.0.0.1', '02:11:22:33:44:55', opener=opener))
        self.assertFalse(sq.forget_player('127.0.0.1', ''))

    def test_record_then_forget_unit(self):
        unit = 'hifi-bt-player@f4-2b-7d-63-98-d7.service'
        sq.record_player(unit, '02:aa:bb:cc:dd:ee', '127.0.0.1', run_dir=self.run)
        calls = []
        ok = sq.forget_unit(unit, run_dir=self.run, forget=lambda s, m: calls.append((s, m)) or True)
        self.assertTrue(ok)
        self.assertEqual(calls, [('127.0.0.1', '02:aa:bb:cc:dd:ee')])
        # once: the record is gone, a second stop has nothing to forget
        self.assertFalse(sq.forget_unit(unit, run_dir=self.run, forget=lambda s, m: calls.append(m) or True))
        self.assertEqual(len(calls), 1)


class RunZoneTest(unittest.TestCase):
    """The zone's runner stops squeezelite when the DAC goes, has Lyrion
    forget the player, and waits for the DAC to come back."""

    def test_unplug_stops_and_forgets(self):
        zone = sq.normalize_zone({'output': 'hw:CARD=D50s,DEV=0', 'mac': '02:11:22:33:44:55', 'name': 'Kitchen'})
        present = iter([True, True, False, True])        # wait, check once, gone, back again

        def card_present(output):
            try:
                return next(present)
            except StopIteration:
                raise KeyboardInterrupt                    # end of the script: leave the loop
        forgotten = []
        with tempfile.TemporaryDirectory() as run, \
                mock.patch.object(sq, 'load_zones', lambda path=None: [zone]), \
                mock.patch.object(sq, 'load', lambda path=None: (sq.normalize({}), False)), \
                mock.patch.object(sq, 'card_present', card_present), \
                mock.patch.object(sq, 'zone_argv', lambda z, server: [sys.executable, '-c', 'import time; time.sleep(30)']), \
                mock.patch.object(sq, 'PLAYERS_RUN_DIR', run), \
                mock.patch.object(sq, 'forget_player', lambda s, m: forgotten.append(m) or True), \
                mock.patch('signal.signal'):
            with self.assertRaises(KeyboardInterrupt):
                sq.run_zone('D50s-0', poll=0.05)
        self.assertEqual(forgotten, ['02:11:22:33:44:55'])

    def test_squeezelite_ending_ends_the_runner(self):
        zone = sq.normalize_zone({'output': 'hw:CARD=D50s,DEV=0', 'mac': '02:11:22:33:44:55'})
        with tempfile.TemporaryDirectory() as run, \
                mock.patch.object(sq, 'load_zones', lambda path=None: [zone]), \
                mock.patch.object(sq, 'load', lambda path=None: (sq.normalize({}), False)), \
                mock.patch.object(sq, 'card_present', lambda o: True), \
                mock.patch.object(sq, 'zone_argv', lambda z, server: [sys.executable, '-c', 'raise SystemExit(3)']), \
                mock.patch.object(sq, 'PLAYERS_RUN_DIR', run), \
                mock.patch('signal.signal'):
            self.assertEqual(sq.run_zone('D50s-0', poll=0.05), 3)
            # the record stays for the unit's ExecStopPost
            self.assertTrue(os.path.exists(sq._unit_record('hifi-zone@D50s-0.service', run)))


class UnitsTest(unittest.TestCase):
    def test_units_forget_on_stop(self):
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'distro', 'config',
                            'includes.chroot', 'etc', 'systemd', 'system')
        for unit in ('hifi-zone@.service', 'hifi-bt-player@.service'):
            with open(os.path.join(base, unit)) as f:
                self.assertIn('ExecStopPost=-/usr/bin/python3 /usr/local/bin/hifi_squeezelite.py forget-unit %n',
                              f.read(), unit)


if __name__ == '__main__':
    unittest.main()
