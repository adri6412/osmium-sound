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
                mock.patch.object(sq, 'zone_argv', lambda z, server, p2d_subdev=None: [sys.executable, '-c', 'import time; time.sleep(30)']), \
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
                mock.patch.object(sq, 'zone_argv', lambda z, server, p2d_subdev=None: [sys.executable, '-c', 'raise SystemExit(3)']), \
                mock.patch.object(sq, 'PLAYERS_RUN_DIR', run), \
                mock.patch('signal.signal'):
            self.assertEqual(sq.run_zone('D50s-0', poll=0.05), 3)
            # the record stays for the unit's ExecStopPost
            self.assertTrue(os.path.exists(sq._unit_record('hifi-zone@D50s-0.service', run)))


class FollowDacStateTest(unittest.TestCase):
    """When the built-in player's USB DAC is unplugged, render falls back to the
    silent `null` device and follow_dac_state() pauses the player on Lyrion;
    when the DAC is back it resumes the player it paused (hifi_squeezelite.py
    follow_dac_state, the squeezelite.service ExecStartPost `dac-check`)."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.run = self.dir.name
        self.mac = '02:11:22:33:44:55'
        self.model = {'output': 'hw:CARD=Lite,DEV=0', 'mac': self.mac, 'server': '127.0.0.1'}

    def tearDown(self):
        self.dir.cleanup()

    @staticmethod
    def _opener(mode, log):
        # `mode` is the reply to every `mode ?`, or a list of replies consumed
        # one per query (the last value repeats) to model Lyrion's state
        # changing across the settle window.
        modes = list(mode) if isinstance(mode, (list, tuple)) else None

        class Resp:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return self.payload

        def next_mode():
            if modes is None:
                return mode
            return modes.pop(0) if len(modes) > 1 else modes[0]

        def opener(req, timeout):
            cmd = json.loads(req.data)['params'][1]
            log.append(cmd)
            if cmd == ['mode', '?']:
                return Resp(json.dumps({'result': {'_mode': next_mode()}}).encode())
            return Resp(b'{"result":{}}')
        return opener

    def _run(self, present, mode, log, marker_mac=None):
        if marker_mac is not None:
            os.makedirs(self.run, exist_ok=True)
            with open(sq._dac_pause_marker(self.run), 'w') as f:
                f.write(marker_mac + '\n')
        with mock.patch.object(sq, 'card_present', lambda o, p=None: present):
            sq.follow_dac_state(self.model, run_dir=self.run, opener=self._opener(mode, log),
                                connect_timeout=0.2, poll=0.01, settle_wait=0.0)

    def _marker(self):
        try:
            with open(sq._dac_pause_marker(self.run)) as f:
                return f.read().strip()
        except OSError:
            return None

    def test_gone_while_playing_pauses_and_marks(self):
        log = []
        self._run(present=False, mode='play', log=log)
        self.assertIn(['pause', '1'], log)
        self.assertEqual(self._marker(), self.mac)

    def test_gone_pause_is_retried_until_it_sticks(self):
        # Lyrion resumes the player when squeezelite reconnects after the
        # service restart, so the first `pause 1` is played over (mode is still
        # `play` right after it). follow_dac_state must pause again until it
        # holds, otherwise the player runs on into `null` with the VU moving.
        log = []
        self._run(present=False, mode=['play', 'play', 'pause'], log=log)
        self.assertEqual(log.count(['pause', '1']), 2)
        self.assertEqual(self._marker(), self.mac)

    def test_gone_while_stopped_does_not_pause(self):
        log = []
        self._run(present=False, mode='stop', log=log)
        self.assertNotIn(['pause', '1'], log)
        self.assertIsNone(self._marker())

    def test_back_resumes_the_player_it_paused(self):
        log = []
        self._run(present=True, mode='pause', log=log, marker_mac=self.mac)
        self.assertIn(['pause', '0'], log)
        self.assertIsNone(self._marker())              # marker cleared

    def test_back_without_marker_does_nothing(self):
        log = []
        self._run(present=True, mode='play', log=log)
        self.assertEqual(log, [])

    def test_non_hw_output_is_a_noop(self):
        log = []
        self.model['output'] = 'default'
        self._run(present=False, mode='play', log=log)
        self.assertEqual(log, [])


class UnitsTest(unittest.TestCase):
    def test_units_forget_on_stop(self):
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'distro', 'config',
                            'includes.chroot', 'etc', 'systemd', 'system')
        for unit in ('hifi-zone@.service', 'hifi-bt-player@.service'):
            with open(os.path.join(base, unit)) as f:
                self.assertIn('ExecStopPost=-/usr/bin/python3 /usr/local/bin/hifi_squeezelite.py forget-unit %n',
                              f.read(), unit)

    def test_squeezelite_runs_dac_check_after_start(self):
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'distro', 'config',
                            'includes.chroot', 'etc', 'systemd', 'system')
        with open(os.path.join(base, 'squeezelite.service')) as f:
            self.assertIn('ExecStartPost=-/usr/bin/python3 /usr/local/bin/hifi_squeezelite.py dac-check',
                          f.read())


if __name__ == '__main__':
    unittest.main()
