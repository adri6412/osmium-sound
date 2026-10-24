"""Which Lyrion player is this box's own squeezelite, and what the
shutdown quiesce does to the box's players.

Every Bluetooth speaker has a squeezelite of its own on the box
(hifi-bt-player@), connecting to Lyrion from 127.0.0.1 just like the main
player, and Lyrion's players_loop has no fixed order. The DSP pause must find
the main player by its MAC (hifi_squeezelite keeps it in squeezelite.json),
not by "the first one on loopback"; the shutdown quiesce instead pauses every
local player, speakers included (issue #124).

Run with:  python3 -m unittest tests.test_own_player
"""
import importlib.util
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import api_server  # noqa: E402

OWN = '02:aa:bb:cc:dd:ee'
BT = '02:11:22:33:44:55'
OTHER = '00:04:20:12:34:56'     # a real Squeezebox elsewhere on the LAN

CAPTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'distro', 'config',
                       'includes.chroot', 'usr', 'local', 'sbin', 'hifi-capture-playback-state.py')


def _players(*ids):
    ips = {OWN: '127.0.0.1:41000', BT: '127.0.0.1:41002', OTHER: '192.168.1.40:3483'}
    return [{'playerid': i, 'ip': ips[i]} for i in ids]


class FakeLms:
    """serverstatus + per-player status, recording every command."""

    def __init__(self, players, modes):
        self.players = players
        self.modes = modes
        self.calls = []

    def __call__(self, playerid, command, timeout=5):
        self.calls.append((playerid, list(command)))
        if command[0] == 'serverstatus':
            return {'players_loop': self.players}
        if command[0] == 'status':
            return {'mode': self.modes.get(playerid, 'stop'), 'time': 42.0,
                    'player_connected': 1}
        return {}

    def sent_to(self, playerid):
        return [c for p, c in self.calls if p == playerid and c[0] != 'status']


class OwnPlayerTestCase(unittest.TestCase):

    def setUp(self):
        self.mac = OWN
        p = mock.patch.object(api_server, '_own_player_mac', lambda: self.mac)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(api_server.time, 'sleep', lambda *_: None)
        p.start()
        self.addCleanup(p.stop)

    def test_the_mac_decides_whatever_the_order(self):
        self.assertEqual(api_server._own_player_ids(_players(BT, OTHER, OWN)), [OWN])
        self.assertEqual(api_server._own_player_ids(_players(BT, OTHER)), [])

    def test_mac_compared_case_insensitively(self):
        self.mac = OWN
        players = [{'playerid': OWN.upper(), 'ip': '127.0.0.1:1'}]
        self.assertEqual(api_server._own_player_ids(players), [OWN.upper()])

    def test_without_a_mac_loopback_minus_the_speakers(self):
        self.mac = ''
        with mock.patch.object(api_server, '_bt_read_doc',
                               lambda: {'speakers': [{'mac': 'F4:2B:7D:63:98:D7'}]}), \
                mock.patch.object(api_server, '_bt_player_mac', lambda m: BT.upper()):
            self.assertEqual(api_server._own_player_ids(_players(BT, OTHER, OWN)), [OWN])

    def test_dsp_pause_finds_the_main_player_not_the_speaker(self):
        lms = FakeLms(_players(BT, OWN), {BT: 'play', OWN: 'play'})
        with mock.patch.object(api_server, '_lms_request', lms):
            self.assertEqual(api_server._local_playing_player(), (OWN, 42.0))

    def test_dsp_pause_leaves_a_playing_speaker_alone(self):
        lms = FakeLms(_players(BT, OWN), {BT: 'play', OWN: 'stop'})
        with mock.patch.object(api_server, '_lms_request', lms):
            self.assertEqual(api_server._local_playing_player(), (None, 0.0))


class CaptureScriptTestCase(unittest.TestCase):

    def setUp(self):
        spec = importlib.util.spec_from_file_location('hifi_capture', CAPTURE)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.tmp = tempfile.mkdtemp(prefix='hifi-capture-test-')
        self.mod.STATE_FILE = os.path.join(self.tmp, 'playback-state.json')

    def test_pauses_every_local_player(self):
        lms = FakeLms(_players(BT, OTHER, OWN), {BT: 'play', OWN: 'pause'})
        self.mod.lms_request = lms
        self.mod.main()
        # Both players on loopback get paused and have power-on resume cleared.
        for local in (OWN, BT):
            self.assertIn(['pause', '1'], lms.sent_to(local))
            self.assertIn(['playerpref', 'playingAtPowerOff', '0'], lms.sent_to(local))
        # The Squeezebox elsewhere on the LAN is left alone.
        self.assertEqual(lms.sent_to(OTHER), [])

    def test_local_player_ids_are_the_loopback_ones(self):
        self.assertEqual(sorted(self.mod.local_player_ids(_players(BT, OTHER, OWN))),
                         sorted([BT, OWN]))

    def test_a_stale_state_file_is_removed(self):
        with open(self.mod.STATE_FILE, 'w') as f:
            f.write('{}')
        lms = FakeLms(_players(OWN), {OWN: 'play'})
        self.mod.lms_request = lms
        self.mod.main()
        self.assertFalse(os.path.exists(self.mod.STATE_FILE))

    def test_one_player_failing_does_not_skip_the_rest(self):
        calls = []

        def flaky(playerid, command, timeout=5):
            calls.append((playerid, list(command)))
            if command[0] == 'serverstatus':
                return {'players_loop': _players(BT, OWN)}
            if playerid == BT:
                raise RuntimeError('not answering')
            return {}
        self.mod.lms_request = flaky
        self.mod.main()
        self.assertIn((OWN, ['pause', '1']), calls)


if __name__ == '__main__':
    unittest.main()
