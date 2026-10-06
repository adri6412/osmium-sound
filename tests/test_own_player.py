"""Which Lyrion player is this box's own squeezelite.

Every Bluetooth speaker has a squeezelite of its own on the box
(hifi-bt-player@), connecting to Lyrion from 127.0.0.1 just like the main
player, and Lyrion's players_loop has no fixed order. The DSP pause, the
resume after a boot and the capture before shutdown must all find the main
player by its MAC (hifi_squeezelite keeps it in squeezelite.json), not by
"the first one on loopback".

Run with:  python3 -m unittest tests.test_own_player
"""
import importlib.util
import json
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
        self.tmp = tempfile.mkdtemp(prefix='hifi-own-player-test-')
        self.mac = OWN
        for name, value in (('_own_player_mac', lambda: self.mac),
                            ('PLAYBACK_STATE_FILE', os.path.join(self.tmp, 'playback-state.json'))):
            p = mock.patch.object(api_server, name, value)
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

    def _state(self, **state):
        with open(api_server.PLAYBACK_STATE_FILE, 'w') as f:
            json.dump(state, f)

    def test_resume_goes_to_the_saved_player(self):
        self._state(playerid=OWN, mode='play', time=12.0, playlist_cur_index=3)
        lms = FakeLms(_players(BT, OWN), {})
        with mock.patch.object(api_server, '_lms_request', lms):
            api_server._resume_playback_after_boot()
        self.assertIn(['playlist', 'index', 3], lms.sent_to(OWN))
        self.assertEqual(lms.sent_to(BT), [])

    def test_resume_without_a_saved_player_uses_the_mac(self):
        self._state(mode='pause', time=0, playlist_cur_index=1)
        lms = FakeLms(_players(BT, OWN), {})
        with mock.patch.object(api_server, '_lms_request', lms):
            api_server._resume_playback_after_boot()
        self.assertIn(['playlist', 'index', 1], lms.sent_to(OWN))
        self.assertIn(['pause', '1'], lms.sent_to(OWN))
        self.assertEqual(lms.sent_to(BT), [])


class CaptureScriptTestCase(unittest.TestCase):

    def setUp(self):
        spec = importlib.util.spec_from_file_location('hifi_capture', CAPTURE)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.tmp = tempfile.mkdtemp(prefix='hifi-capture-test-')
        self.mod.STATE_FILE = os.path.join(self.tmp, 'playback-state.json')

    def test_captures_the_main_player_by_its_mac(self):
        lms = FakeLms(_players(BT, OWN), {BT: 'play', OWN: 'pause'})
        self.mod.lms_request = lms
        self.mod.own_player_mac = lambda: OWN
        self.mod.main()
        with open(self.mod.STATE_FILE) as f:
            state = json.load(f)
        self.assertEqual(state['playerid'], OWN)
        self.assertEqual(state['mode'], 'pause')

    def test_fallback_skips_the_speakers_players(self):
        self.mod.own_player_mac = lambda: ''
        self.mod.bt_player_ids = lambda: {BT}
        self.assertEqual(self.mod.own_player_id(_players(BT, OTHER, OWN)), OWN)

    def test_bt_player_ids_match_the_api(self):
        machine_id = os.path.join(self.tmp, 'machine-id')
        with open(machine_id, 'w') as f:
            f.write('0123456789abcdef0123456789abcdef\n')
        bt_state = os.path.join(self.tmp, 'bluetooth.json')
        with open(bt_state, 'w') as f:
            json.dump({'speakers': [{'mac': 'F4:2B:7D:63:98:D7'}]}, f)
        self.mod.MACHINE_ID = machine_id
        self.mod.BT_STATE_FILE = bt_state
        real_open = open

        def fake_open(path, *a, **k):
            return real_open(machine_id if path == '/etc/machine-id' else path, *a, **k)
        with mock.patch('builtins.open', fake_open):
            expected = api_server._bt_player_mac('F4:2B:7D:63:98:D7').lower()
        self.assertEqual(self.mod.bt_player_ids(), {expected})

    def test_reads_the_mac_through_hifi_squeezelite(self):
        import hifi_squeezelite
        with mock.patch.object(hifi_squeezelite, 'load',
                               lambda *a, **k: ({'mac': OWN.upper()}, False)):
            self.assertEqual(self.mod.own_player_mac(), OWN)


if __name__ == '__main__':
    unittest.main()
