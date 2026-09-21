"""Bluetooth speakers (A2DP source) in api_server.py.

The appliance plays OUT to a Bluetooth speaker, and every speaker set up here
becomes a squeezelite player of its own in Lyrion — the piCorePlayer
arrangement. What these tests pin is the part that has to be right for that to
survive a reboot, an update and a restore:

  * the choice, and the speaker list, live in ONE state file
    (/etc/hifi-player/bluetooth.json) and nowhere else — api_server never
    enables a unit, it writes the file and signals hifi-bt-out.service. A file
    written by the older, sink-era build (just {"enabled": ...}) still reads.
  * each speaker's Lyrion player id is stable across restarts and derived from
    this device as well as the speaker, so two Osmiums paired to the same
    speaker do not claim to be the same player.
  * the address from a network request never reaches a subprocess unchecked.

Run with:  python tests/test_bt_speakers.py
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import api_server  # noqa: E402  (needs the path above)

MAC = 'F4:2B:7D:63:98:D7'
MAC2 = 'F4:4E:FD:08:52:3F'


def _cp(cmd, rc=0, stdout='', stderr=''):
    return subprocess.CompletedProcess(cmd, rc, stdout=stdout, stderr=stderr)


class BtTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='hifi-bt-test-')
        self._saved = {}
        self._patch('BT_STATE_FILE', os.path.join(self.tmp, 'etc', 'bluetooth.json'))
        self._patch('BT_STATUS_FILE', os.path.join(self.tmp, 'run', 'output.json'))
        os.makedirs(os.path.join(self.tmp, 'etc'))
        os.makedirs(os.path.join(self.tmp, 'run'))

        # BlueZ's view of the world, as the fake bluetoothctl reports it.
        self.known = {}          # mac -> {name, paired, trusted, connected, audio}
        self.calls = []          # every argv, in order
        self.pair_succeeds = True
        self.connect_succeeds = True
        self.snapshot = {'enabled': True, 'adapter': True, 'speakers': []}

        self.addCleanup(patch.object(api_server, '_bt_available', lambda: True).stop)
        patch.object(api_server, '_bt_available', lambda: True).start()
        for target in ('subprocess.run',):
            p = patch.object(api_server.subprocess, 'run', self._fake_run)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(api_server.time, 'sleep', lambda *_: None)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(api_server, name, value)
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _patch(self, name, value):
        self._saved[name] = getattr(api_server, name)
        setattr(api_server, name, value)

    # ── stubs ────────────────────────────────────────────────────────
    def _fake_run(self, cmd, capture_output=False, text=False, timeout=None, **kw):
        self.calls.append(list(cmd))
        if cmd[0] == 'bluetoothctl':
            return self._bluetoothctl(cmd)
        if cmd[0] == 'systemctl':
            if cmd[1] == 'is-active':
                return _cp(cmd, stdout='inactive\n')
            return _cp(cmd)
        return _cp(cmd)

    def _bluetoothctl(self, cmd):
        verb = cmd[1]
        if verb == 'devices':
            rows = ''.join(f'Device {m} {d["name"]}\n' for m, d in self.known.items())
            return _cp(cmd, stdout=rows)
        if verb == 'info':
            d = self.known.get(cmd[2])
            if not d:
                return _cp(cmd, rc=1, stdout='Device not available\n')
            uuids = '\tUUID: Audio Sink (0000110b-0000-1000-8000-00805f9b34fb)\n' if d['audio'] else ''
            return _cp(cmd, stdout=(
                f'Device {cmd[2]}\n\tName: {d["name"]}\n\tAlias: {d["name"]}\n'
                f'\tPaired: {"yes" if d["paired"] else "no"}\n'
                f'\tTrusted: {"yes" if d["trusted"] else "no"}\n'
                f'\tConnected: {"yes" if d["connected"] else "no"}\n' + uuids))
        if verb == 'pair':
            if self.pair_succeeds:
                self.known[cmd[2]]['paired'] = True
                return _cp(cmd, stdout='Pairing successful\n')
            return _cp(cmd, rc=1, stdout='Failed to pair: org.bluez.Error.AuthenticationCanceled\n')
        if verb == 'trust':
            self.known[cmd[2]]['trusted'] = True
            return _cp(cmd, stdout='Changing F4 trust succeeded\n')
        if verb == 'connect':
            if self.connect_succeeds:
                self.known[cmd[2]]['connected'] = True
                return _cp(cmd, stdout='Connection successful\n')
            return _cp(cmd, rc=1, stdout='Failed to connect: br-connection-page-timeout\n')
        if verb == 'disconnect':
            self.known[cmd[2]]['connected'] = False
            return _cp(cmd, stdout='Successful disconnected\n')
        if verb == 'remove':
            return _cp(cmd) if self.known.pop(cmd[2], None) else _cp(cmd, rc=1)
        return _cp(cmd)

    # ── helpers ──────────────────────────────────────────────────────
    def _see(self, mac, name, audio=True, paired=False, connected=False):
        self.known[mac] = {'name': name, 'paired': paired, 'trusted': False,
                           'connected': connected, 'audio': audio}

    def _write_state(self, doc):
        with open(api_server.BT_STATE_FILE, 'w') as f:
            json.dump(doc, f)

    def _write_snapshot(self, snap):
        with open(api_server.BT_STATUS_FILE, 'w') as f:
            json.dump(snap, f)

    def _state(self):
        with open(api_server.BT_STATE_FILE) as f:
            return json.load(f)

    def _argv(self, *prefix):
        return [c for c in self.calls if c[:len(prefix)] == list(prefix)]


class StateFileTests(BtTestCase):

    def test_missing_file_means_off(self):
        self.assertFalse(api_server._read_bt_state())
        self.assertEqual(api_server._bt_read_doc(), {'enabled': False, 'speakers': []})

    def test_a_sink_era_state_file_still_reads(self):
        """Devices that used the old "appliance as a Bluetooth speaker" build
        have a file with nothing but the switch in it."""
        self._write_state({'enabled': True})
        self.assertTrue(api_server._read_bt_state())
        self.assertEqual(api_server._bt_read_doc()['speakers'], [])

    def test_rubbish_in_the_file_is_off_rather_than_an_exception(self):
        with open(api_server.BT_STATE_FILE, 'w') as f:
            f.write('{ not json at all')
        self.assertFalse(api_server._read_bt_state())

    def test_enabling_writes_the_file_and_signals_the_supervisor(self):
        self._write_snapshot({'adapter': True, 'speakers': []})
        out = api_server.set_bt_enabled(True)
        self.assertTrue(out['success'])
        self.assertTrue(self._state()['enabled'])
        self.assertEqual(
            self._argv('systemctl', 'kill', '-s', 'HUP', 'hifi-bt-out.service'),
            [['systemctl', 'kill', '-s', 'HUP', 'hifi-bt-out.service']])

    def test_enabling_never_enables_a_unit_itself(self):
        """🚨 The whole point of the supervisor: an enable symlink does not
        survive an A/B image swap, so the choice must be the state file and
        nothing else."""
        self._write_snapshot({'adapter': True, 'speakers': []})
        api_server.set_bt_enabled(True)
        self.assertEqual(self._argv('systemctl', 'enable'), [])

    def test_turning_it_off_keeps_the_speakers(self):
        self._write_state({'enabled': True, 'speakers': [{'mac': MAC, 'name': 'Kitchen'}]})
        api_server.set_bt_enabled(False)
        doc = self._state()
        self.assertFalse(doc['enabled'])
        self.assertEqual([s['mac'] for s in doc['speakers']], [MAC])


class PlayerIdTests(BtTestCase):

    def test_player_id_is_stable_and_locally_administered(self):
        first = api_server._bt_player_mac(MAC)
        self.assertEqual(first, api_server._bt_player_mac(MAC))
        self.assertNotEqual(first, api_server._bt_player_mac(MAC2))
        head = int(first.split(':')[0], 16)
        self.assertEqual(head & 0x02, 0x02, 'locally administered bit not set')
        self.assertEqual(head & 0x01, 0x00, 'must not be a multicast address')

    def test_player_id_depends_on_this_device_too(self):
        """Two Osmiums paired to the same speaker must not tell Lyrion they
        are the same player."""
        with patch('builtins.open', side_effect=FileNotFoundError):
            with patch.object(api_server.socket, 'gethostname', return_value='box-a'):
                a = api_server._bt_player_mac(MAC)
            with patch.object(api_server.socket, 'gethostname', return_value='box-b'):
                b = api_server._bt_player_mac(MAC)
        self.assertNotEqual(a, b)

    def test_instance_name_has_no_colons(self):
        self.assertEqual(api_server._bt_instance(MAC), 'f4-2b-7d-63-98-d7')


class AddSpeakerTests(BtTestCase):

    def setUp(self):
        super().setUp()
        self._write_state({'enabled': True, 'speakers': []})
        self._write_snapshot({'enabled': True, 'adapter': True, 'speakers': []})

    def test_pairs_trusts_and_stores(self):
        self._see(MAC, 'Anker Soundcore')
        out = api_server.bt_add_speaker(MAC)
        self.assertTrue(out['success'], out)
        self.assertTrue(self._argv('bluetoothctl', 'pair', MAC))
        # trusted as well as paired, or the speaker cannot reconnect by itself
        self.assertTrue(self._argv('bluetoothctl', 'trust', MAC))
        saved = self._state()['speakers']
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]['name'], 'Anker Soundcore')
        self.assertEqual(saved[0]['player'], 'Anker Soundcore')
        self.assertTrue(saved[0]['autoconnect'])
        self.assertTrue(saved[0]['player_mac'])

    def test_discovery_is_stopped_before_pairing(self):
        """BlueZ will not pair while the adapter is still hopping channels."""
        self._see(MAC, 'Anker Soundcore')
        api_server.bt_add_speaker(MAC)
        order = [c for c in self.calls if c[:2] in (['bluetoothctl', 'scan'], ['bluetoothctl', 'pair'])]
        self.assertEqual(order[0][:3], ['bluetoothctl', 'scan', 'off'])
        self.assertEqual(order[1][:2], ['bluetoothctl', 'pair'])

    def test_an_already_paired_speaker_is_not_paired_again(self):
        self._see(MAC, 'Anker Soundcore', paired=True)
        self.assertTrue(api_server.bt_add_speaker(MAC)['success'])
        self.assertEqual(self._argv('bluetoothctl', 'pair', MAC), [])

    def test_a_failed_pairing_stores_nothing(self):
        self._see(MAC, 'Anker Soundcore')
        self.pair_succeeds = False
        out = api_server.bt_add_speaker(MAC)
        self.assertFalse(out['success'])
        self.assertEqual(out['code'], 'bluetooth.pairFailed')
        self.assertEqual(self._state()['speakers'], [])

    def test_the_same_speaker_twice_is_refused(self):
        self._see(MAC, 'Anker Soundcore')
        api_server.bt_add_speaker(MAC)
        out = api_server.bt_add_speaker(MAC)
        self.assertFalse(out['success'])
        self.assertEqual(out['code'], 'bluetooth.alreadyAdded')
        self.assertEqual(len(self._state()['speakers']), 1)

    def test_a_bogus_address_never_reaches_bluetoothctl(self):
        for bad in ('', 'not-a-mac', '; rm -rf /', 'F4:2B:7D:63:98', MAC + ':00'):
            self.calls.clear()
            out = api_server.bt_add_speaker(bad)
            self.assertFalse(out['success'], bad)
            self.assertEqual(out['code'], 'bluetooth.invalidAddress')
            self.assertEqual(self._argv('bluetoothctl'), [], bad)

    def test_adding_while_bluetooth_is_off_is_refused(self):
        self._write_state({'enabled': False, 'speakers': []})
        self._see(MAC, 'Anker Soundcore')
        out = api_server.bt_add_speaker(MAC)
        self.assertEqual(out['code'], 'bluetooth.turnOnFirst')
        self.assertEqual(self._argv('bluetoothctl', 'pair', MAC), [])


class SpeakerEditingTests(BtTestCase):

    def setUp(self):
        super().setUp()
        self._see(MAC, 'Anker Soundcore', paired=True, connected=True)
        self._write_state({'enabled': True, 'speakers': []})
        self._write_snapshot({'enabled': True, 'adapter': True, 'speakers': []})
        api_server.bt_add_speaker(MAC)
        self.calls.clear()

    def test_renaming_the_player(self):
        out = api_server.bt_update_speaker(MAC, {'player': 'Kitchen'})
        self.assertTrue(out['success'])
        self.assertEqual(self._state()['speakers'][0]['player'], 'Kitchen')
        # the speaker's own Bluetooth name is not what was renamed
        self.assertEqual(self._state()['speakers'][0]['name'], 'Anker Soundcore')

    def test_a_name_with_control_characters_is_cleaned_not_refused(self):
        api_server.bt_update_speaker(MAC, {'player': 'Kit\x00chen\n'})
        self.assertEqual(self._state()['speakers'][0]['player'], 'Kitchen')

    def test_an_empty_name_falls_back_to_the_speakers_own(self):
        api_server.bt_update_speaker(MAC, {'player': '   '})
        self.assertEqual(self._state()['speakers'][0]['player'], 'Anker Soundcore')

    def test_disconnecting_by_hand_parks_the_automatic_retry(self):
        """Or the supervisor reconnects it fifteen seconds later."""
        out = api_server.bt_connect(MAC, connect=False)
        self.assertTrue(out['success'])
        self.assertFalse(self._state()['speakers'][0]['autoconnect'])

    def test_connecting_by_hand_turns_the_retry_back_on(self):
        api_server.bt_connect(MAC, connect=False)
        api_server.bt_connect(MAC, connect=True)
        self.assertTrue(self._state()['speakers'][0]['autoconnect'])

    def test_a_connect_that_fails_says_so(self):
        self.known[MAC]['connected'] = False
        self.connect_succeeds = False
        out = api_server.bt_connect(MAC, connect=True)
        self.assertFalse(out['success'])
        self.assertEqual(out['code'], 'bluetooth.connectFailed')

    def test_forgetting_stops_the_player_before_unpairing(self):
        """Removing the device out from under a squeezelite that still has the
        PCM open leaves a hung ALSA handle instead of a clean exit."""
        out = api_server.bt_remove_speaker(MAC)
        self.assertTrue(out['success'])
        self.assertEqual(self._state()['speakers'], [])
        stop = self._argv('systemctl', 'stop', 'hifi-bt-player@f4-2b-7d-63-98-d7.service')
        remove = self._argv('bluetoothctl', 'remove', MAC)
        self.assertTrue(stop)
        self.assertTrue(remove)
        self.assertLess(self.calls.index(stop[0]), self.calls.index(remove[0]))

    def test_forgetting_something_that_was_never_added(self):
        out = api_server.bt_remove_speaker(MAC2)
        self.assertFalse(out['success'])
        self.assertEqual(out['code'], 'bluetooth.deviceNotFound')


class StatusTests(BtTestCase):

    def test_live_state_comes_from_the_supervisors_snapshot(self):
        self._write_state({'enabled': True, 'speakers': [
            {'mac': MAC, 'name': 'Anker', 'player': 'Kitchen', 'autoconnect': True}]})
        self._write_snapshot({'enabled': True, 'adapter': True, 'speakers': [
            {'mac': MAC, 'connected': True, 'playing': True}]})
        out = api_server.get_bt_speakers()
        self.assertTrue(out['adapter'])
        self.assertEqual(out['speakers'][0]['player'], 'Kitchen')
        self.assertTrue(out['speakers'][0]['connected'])
        self.assertTrue(out['speakers'][0]['playing'])

    def test_a_speaker_already_set_up_is_not_offered_again(self):
        self._see(MAC, 'Anker Soundcore', paired=True)
        self._see(MAC2, 'Other speaker')
        self._write_state({'enabled': True, 'speakers': [{'mac': MAC, 'name': 'Anker'}]})
        self._write_snapshot({'enabled': True, 'adapter': True, 'speakers': []})
        out = api_server.get_bt_speakers()
        self.assertEqual([d['mac'] for d in out['found']], [MAC2])

    def test_with_bluetooth_off_bluez_is_not_asked_anything(self):
        self._write_state({'enabled': False, 'speakers': []})
        out = api_server.get_bt_speakers()
        self.assertEqual(out['found'], [])
        self.assertEqual(self._argv('bluetoothctl'), [])

    def test_a_non_audio_device_is_listed_but_flagged(self):
        """A keyboard can be paired and will never play; the UI needs to be
        able to say so rather than silently offering it."""
        self._see(MAC2, 'Some keyboard', audio=False)
        self._write_state({'enabled': True, 'speakers': []})
        self._write_snapshot({'enabled': True, 'adapter': True, 'speakers': []})
        out = api_server.get_bt_speakers()
        self.assertEqual(len(out['found']), 1)
        self.assertFalse(out['found'][0]['audio'])

    def test_scanning_while_bluetooth_is_off_is_refused(self):
        self._write_state({'enabled': False, 'speakers': []})
        out = api_server.bt_scan(10)
        self.assertEqual(out['code'], 'bluetooth.turnOnFirst')
        self.assertEqual(self._argv('bluetoothctl'), [])

    def test_scan_window_is_bounded(self):
        self._write_state({'enabled': True, 'speakers': []})
        self._write_snapshot({'enabled': True, 'adapter': True, 'speakers': []})
        api_server.bt_scan(9999)
        scan = self._argv('bluetoothctl', '--timeout')[0]
        self.assertEqual(scan[2], '30')
        # and discovery is asked to stop by itself, not left running
        self.assertIn('--timeout', scan)


class PlayerCommandTests(unittest.TestCase):
    """hifi-bt-player-run.py: the squeezelite command line for one speaker."""

    @classmethod
    def setUpClass(cls):
        path = os.path.join(REPO, 'distro', 'config', 'includes.chroot',
                            'usr', 'local', 'sbin', 'hifi-bt-player-run.py')
        spec = importlib.util.spec_from_file_location('hifi_bt_player_run', path)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='hifi-bt-player-test-')
        self.mod.STATE_FILE = os.path.join(self.tmp, 'bluetooth.json')
        self.mod.SQ_DEFAULT = os.path.join(self.tmp, 'squeezelite')
        with open(self.mod.SQ_DEFAULT, 'w') as f:
            f.write("ARGS='-o hw:CARD=D50s,DEV=0 -D -v -C 5 -s 192.168.0.42 -n OsmiumSound -M Osmium'\n")
        with open(self.mod.STATE_FILE, 'w') as f:
            json.dump({'enabled': True, 'speakers': [
                {'mac': MAC, 'name': 'Anker', 'player': 'Kitchen speaker',
                 'player_mac': '02:11:22:33:44:55', 'enabled': True}]}, f)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _argv(self, instance='f4-2b-7d-63-98-d7'):
        """The argv main() would have handed to execv, for one instance."""
        seen = {}
        with patch.object(self.mod.sys, 'argv', ['hifi-bt-player-run.py', instance]):
            with patch.object(self.mod.os, 'execv', lambda p, a: seen.update(path=p, argv=a)):
                self.mod.main()
        return seen.get('argv', [])

    def test_instance_name_is_turned_back_into_an_address(self):
        self.assertEqual(self.mod.mac_from_instance('f4-2b-7d-63-98-d7'), MAC)
        self.assertIsNone(self.mod.mac_from_instance('not-an-address'))

    def test_output_is_the_bluealsa_pcm_for_this_speaker(self):
        argv = self._argv()
        self.assertIn('-o', argv)
        self.assertEqual(argv[argv.index('-o') + 1],
                         f'bluealsa:DEV={MAC},PROFILE=a2dp,SRV=org.bluealsa')

    def test_the_name_travels_as_one_argument(self):
        """squeezelite splits ARGS on whitespace; execv does not, which is why
        a two-word player name works here and would not through /etc/default."""
        argv = self._argv()
        self.assertEqual(argv[argv.index('-n') + 1], 'Kitchen speaker')

    def test_it_joins_the_same_lyrion_as_the_built_in_player(self):
        """So a Bluetooth speaker follows Settings -> Multiroom too."""
        argv = self._argv()
        self.assertEqual(argv[argv.index('-s') + 1], '192.168.0.42')

    def test_no_server_configured_falls_back_to_the_local_one(self):
        with open(self.mod.SQ_DEFAULT, 'w') as f:
            f.write("# nothing useful here\n")
        self.assertEqual(self.mod.main_server(), '127.0.0.1')

    def test_rates_are_capped_at_what_a2dp_can_carry(self):
        argv = self._argv()
        self.assertEqual(argv[argv.index('-r') + 1], '44100,48000')
        self.assertIn('-R', argv)

    def test_mmap_is_off_in_the_alsa_parameters(self):
        """The BlueALSA PCM plugin does not implement mmap."""
        argv = self._argv()
        self.assertTrue(argv[argv.index('-a') + 1].endswith(':0'))

    def test_the_player_id_is_passed_through(self):
        argv = self._argv()
        self.assertEqual(argv[argv.index('-m') + 1], '02:11:22:33:44:55')

    def test_a_pinned_codec_reaches_the_pcm(self):
        self._edit(lambda sp: sp.update(codec='aptX'))
        argv = self._argv()
        self.assertTrue(argv[argv.index('-o') + 1].endswith(',CODEC=aptX'))

    def test_no_codec_pinned_leaves_the_negotiated_one_alone(self):
        argv = self._argv()
        self.assertNotIn('CODEC=', argv[argv.index('-o') + 1])

    def test_a_speaker_switched_off_in_settings_does_not_start(self):
        self._edit(lambda sp: sp.update(enabled=False))
        self.assertEqual(self._argv(), [])

    def test_an_unknown_speaker_does_not_start(self):
        self.assertEqual(self._argv('aa-bb-cc-dd-ee-ff'), [])

    def test_a_bogus_instance_name_does_not_start(self):
        self.assertEqual(self._argv('; rm -rf /'), [])

    def _edit(self, fn):
        with open(self.mod.STATE_FILE) as f:
            doc = json.load(f)
        fn(doc['speakers'][0])
        with open(self.mod.STATE_FILE, 'w') as f:
            json.dump(doc, f)


class SupervisorHarness(unittest.TestCase):
    """hifi-bt-out.py with a fake bluetoothctl and a fake systemd under it.
    Split from the tests themselves so the classes below can share it without
    re-running each other's cases."""

    @classmethod
    def setUpClass(cls):
        import signal
        path = os.path.join(REPO, 'distro', 'config', 'includes.chroot',
                            'usr', 'local', 'sbin', 'hifi-bt-out.py')
        saved = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
        spec = importlib.util.spec_from_file_location('hifi_bt_out', path)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)
        for sig, handler in saved.items():   # importing it installs its own
            signal.signal(sig, handler)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='hifi-bt-out-test-')
        self.mod.STATE_FILE = os.path.join(self.tmp, 'bluetooth.json')
        self.mod.RUNDIR = self.tmp
        self.mod.STATUS_FILE = os.path.join(self.tmp, 'output.json')
        self.calls = []
        self.connected = set()
        self.active = set()
        self.connect_succeeds = True
        # Addresses bluetoothctl will not answer about: the question times out
        # the way it really does while the adapter is busy paging a speaker
        # that has just walked out of range.
        self.silent = set()
        p = patch.object(self.mod.subprocess, 'run', self._fake_run)
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(self.mod.time, 'sleep', lambda *_: None)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _fake_run(self, cmd, capture_output=False, text=False, timeout=None, **kw):
        self.calls.append(list(cmd))
        if cmd[0] == 'bluetoothctl':
            if cmd[1] == 'list':
                return _cp(cmd, stdout='Controller 00:11:22:33:44:55 osmium [default]\n')
            if cmd[1] == 'show':
                return _cp(cmd, stdout='Controller 00:11:22:33:44:55\n\tPowered: yes\n')
            if cmd[1] == 'info':
                if cmd[2] in self.silent:
                    raise subprocess.TimeoutExpired(cmd, timeout or 10)
                yes = 'yes' if cmd[2] in self.connected else 'no'
                return _cp(cmd, stdout=f'Device {cmd[2]}\n\tConnected: {yes}\n')
            if cmd[1] == 'connect':
                if self.connect_succeeds:
                    self.connected.add(cmd[2])
                return _cp(cmd)
            return _cp(cmd)
        if cmd[0] == 'systemctl':
            if cmd[1] == 'is-active':
                return _cp(cmd, stdout=('active\n' if cmd[2] in self.active else 'inactive\n'))
            if cmd[1] == 'show':
                return _cp(cmd, stdout='loaded\n')
            if cmd[1] == 'list-units':
                return _cp(cmd, stdout=''.join(f'{u} loaded active running x\n' for u in sorted(self.active)
                                               if u.startswith('hifi-bt-player@')))
            if cmd[1] == 'start':
                self.active.add(cmd[2])
                return _cp(cmd)
            if cmd[1] == 'stop':
                self.active.discard(cmd[2])
                return _cp(cmd)
        return _cp(cmd)

    def _write(self, doc):
        with open(self.mod.STATE_FILE, 'w') as f:
            json.dump(doc, f)

    def _status(self):
        with open(self.mod.STATUS_FILE) as f:
            return json.load(f)

    def _argv(self, *prefix):
        return [c for c in self.calls if c[:len(prefix)] == list(prefix)]


class SupervisorTests(SupervisorHarness):
    """The daemon that turns the state file into running services. It is the
    only thing that starts or stops anything, so what matters is that it does
    nothing at all when the owner said no, and that a player is started only
    once its speaker is really connected."""

    def test_off_starts_nothing_and_powers_the_adapter_down(self):
        self._write({'enabled': False, 'speakers': [{'mac': MAC, 'name': 'Anker'}]})
        self.active.add('bluetooth.service')
        self.mod.Supervisor().tick()
        self.assertEqual(self._argv('systemctl', 'start'), [])
        self.assertIn(['bluetoothctl', 'power', 'off'], self.calls)
        self.assertFalse(self._status()['enabled'])

    def test_off_also_stops_the_old_sink_units(self):
        """The appliance is a source now; bluealsa-aplay holding the DAC open
        for a role nobody uses would be a silent theft of the output."""
        self._write({'enabled': False, 'speakers': []})
        self.active.update({'hifi-bt-aplay.service', 'hifi-bt-watcher.service'})
        self.mod.Supervisor().tick()
        self.assertIn(['systemctl', 'stop', 'hifi-bt-aplay.service'], self.calls)
        self.assertIn(['systemctl', 'stop', 'hifi-bt-watcher.service'], self.calls)

    def test_on_brings_up_bluealsa_and_the_pairing_agent(self):
        self._write({'enabled': True, 'speakers': []})
        self.mod.Supervisor().tick()
        self.assertIn(['systemctl', 'start', 'hifi-bluealsa.service'], self.calls)
        self.assertIn(['systemctl', 'start', 'hifi-bt-agent.service'], self.calls)
        self.assertTrue(self._status()['adapter'])

    def test_a_connected_speaker_gets_its_player(self):
        self._write({'enabled': True, 'speakers': [{'mac': MAC, 'name': 'Anker'}]})
        self.mod.Supervisor().tick()
        self.assertIn(['systemctl', 'start', 'hifi-bt-player@f4-2b-7d-63-98-d7.service'], self.calls)
        self.assertTrue(self._status()['speakers'][0]['connected'])

    def test_a_speaker_that_will_not_connect_gets_no_player(self):
        self.connect_succeeds = False
        self._write({'enabled': True, 'speakers': [{'mac': MAC, 'name': 'Anker'}]})
        self.mod.Supervisor().tick()
        self.assertEqual(self._argv('systemctl', 'start', 'hifi-bt-player@f4-2b-7d-63-98-d7.service'), [])
        self.assertFalse(self._status()['speakers'][0]['connected'])

    def test_the_retry_backs_off_instead_of_hammering_a_speaker_that_is_off(self):
        """A box next to a speaker switched off for the night must not spend
        the night in a connect loop."""
        self.connect_succeeds = False
        self._write({'enabled': True, 'speakers': [{'mac': MAC, 'name': 'Anker'}]})
        sup = self.mod.Supervisor()
        sup.tick()
        first = len(self._argv('bluetoothctl', 'connect', MAC))
        sup.tick()          # straight away: still inside the backoff window
        self.assertEqual(len(self._argv('bluetoothctl', 'connect', MAC)), first)
        self.assertGreaterEqual(sup.retry[MAC]['delay'], self.mod.RETRY_MIN * 2)

    def test_autoconnect_off_means_no_connect_attempt(self):
        self._write({'enabled': True, 'speakers': [
            {'mac': MAC, 'name': 'Anker', 'autoconnect': False}]})
        self.mod.Supervisor().tick()
        self.assertEqual(self._argv('bluetoothctl', 'connect', MAC), [])

    def test_a_speaker_switched_off_in_settings_has_its_player_stopped(self):
        self.connected.add(MAC)
        self.active.add('hifi-bt-player@f4-2b-7d-63-98-d7.service')
        self._write({'enabled': True, 'speakers': [
            {'mac': MAC, 'name': 'Anker', 'enabled': False}]})
        self.mod.Supervisor().tick()
        self.assertIn(['systemctl', 'stop', 'hifi-bt-player@f4-2b-7d-63-98-d7.service'], self.calls)

    def test_a_forgotten_speaker_leaves_no_player_behind(self):
        self.active.add('hifi-bt-player@f4-4e-fd-08-52-3f.service')
        self._write({'enabled': True, 'speakers': [{'mac': MAC, 'name': 'Anker'}]})
        self.mod.Supervisor().tick()
        self.assertIn(['systemctl', 'stop', 'hifi-bt-player@f4-4e-fd-08-52-3f.service'], self.calls)

    def test_a_bogus_address_in_the_file_is_ignored(self):
        self._write({'enabled': True, 'speakers': [
            {'mac': 'nonsense', 'name': 'x'}, {'mac': MAC, 'name': 'Anker'}]})
        self.mod.Supervisor().tick()
        self.assertEqual([s['mac'] for s in self._status()['speakers']], [MAC])


class TwoSpeakersTests(SupervisorHarness):
    """🚨 The reason this file has a whole class for it: with headphones and
    a speaker both connected, switching one off used to drop the other too.

    Nothing dramatic was happening — bluetoothctl simply did not answer in
    time about the speaker that was still playing, because the adapter was
    busy paging the one that had gone, and an unanswered question counted as
    "not connected". That stopped the good speaker's player and sent the
    adapter after it as well."""

    PLAYER = 'hifi-bt-player@f4-2b-7d-63-98-d7.service'
    PLAYER2 = 'hifi-bt-player@f4-4e-fd-08-52-3f.service'

    def _both(self, **extra):
        self._write({'enabled': True, 'speakers': [
            dict({'mac': MAC, 'name': 'Cuffie'}, **extra),
            dict({'mac': MAC2, 'name': 'Casse'}, **extra)]})

    def test_a_speaker_bluez_will_not_talk_about_keeps_playing(self):
        """The single line this whole class exists for."""
        self._both()
        self.connected.update({MAC, MAC2})
        self.active.update({self.PLAYER, self.PLAYER2})
        sup = self.mod.Supervisor()
        sup.tick()                        # both answer: both known connected
        self.silent.add(MAC2)             # and now one question goes unanswered
        self.calls.clear()
        sup.tick()
        self.assertEqual(self._argv('systemctl', 'stop', self.PLAYER2), [])
        self.assertEqual(self._argv('bluetoothctl', 'connect', MAC2), [])

    def test_a_speaker_that_goes_quiet_is_still_reported_as_it_last_was(self):
        """The screen must not show a speaker dropping out because we could
        not ask about it — the owner is listening to it."""
        self._both()
        self.connected.update({MAC, MAC2})
        sup = self.mod.Supervisor()
        sup.tick()
        self.silent.add(MAC2)
        sup.tick()
        row = [s for s in self._status()['speakers'] if s['mac'] == MAC2][0]
        self.assertTrue(row['connected'])
        self.assertTrue(row['stale'])

    def test_one_speaker_walking_off_does_not_take_the_other_with_it(self):
        """The whole scenario: the headphones are switched off, and while the
        adapter chases them bluetoothctl stops answering about the speaker."""
        self._both()
        self.connected.update({MAC, MAC2})
        self.active.update({self.PLAYER, self.PLAYER2})
        sup = self.mod.Supervisor()
        sup.tick()
        self.connect_succeeds = False
        self.connected.discard(MAC)       # the headphones are switched off
        self.silent.add(MAC2)             # BlueZ gets slow about the speaker
        self.calls.clear()
        sup.tick()
        self.assertIn(['systemctl', 'stop', self.PLAYER], self.calls)
        self.assertEqual(self._argv('systemctl', 'stop', self.PLAYER2), [])
        self.assertIn(self.PLAYER2, self.active)

    def test_only_one_speaker_is_paged_per_pass(self):
        """The adapter can only page one device at a time, and every second
        spent paging is a second stolen from whatever is still playing."""
        self.connect_succeeds = False
        self._both()
        self.mod.Supervisor().tick()
        attempts = [c for c in self.calls if c[:2] == ['bluetoothctl', 'connect']]
        self.assertEqual(len(attempts), 1)

    def test_every_state_is_read_before_anything_is_paged(self):
        """Ordering is the fix: a page attempt blocks for up to twenty
        seconds and is what makes the next question time out. It goes last."""
        self.connect_succeeds = False
        self._both()
        self.connected.add(MAC2)
        self.mod.Supervisor().tick()
        first_connect = next(i for i, c in enumerate(self.calls)
                             if c[:2] == ['bluetoothctl', 'connect'])
        asked = [i for i, c in enumerate(self.calls)
                 if c[:2] == ['bluetoothctl', 'info'] and c[2] == MAC2]
        self.assertTrue(asked)
        self.assertLess(min(asked), first_connect)

    def test_a_confirmed_disconnection_is_still_acted_on_at_once(self):
        """Holding the last state is for silence, not for a "no": a speaker
        BlueZ says is gone must lose its player on the spot, or squeezelite
        sits there restarting against a PCM that is not there."""
        self._both()
        self.connected.update({MAC, MAC2})
        self.active.update({self.PLAYER, self.PLAYER2})
        sup = self.mod.Supervisor()
        sup.tick()
        self.connect_succeeds = False
        self.connected.discard(MAC2)
        self.calls.clear()
        sup.tick()
        self.assertIn(['systemctl', 'stop', self.PLAYER2], self.calls)


class StateFileReadTests(SupervisorHarness):
    """Reading the owner's choice. Getting this wrong is expensive: "off"
    means powering the adapter down, which disconnects every speaker at
    once."""

    def test_a_file_that_cannot_be_read_does_not_mean_off(self):
        self._write({'enabled': True, 'speakers': [{'mac': MAC, 'name': 'Casse'}]})
        sup = self.mod.Supervisor()
        sup.tick()
        with open(self.mod.STATE_FILE, 'w') as f:
            f.write('{ this is not json')
        self.calls.clear()
        sup.tick()
        self.assertEqual(self._argv('bluetoothctl', 'power', 'off'), [])
        self.assertEqual(self._argv('systemctl', 'stop', 'bluetooth.service'), [])
        self.assertTrue(self._status()['enabled'])

    def test_no_file_at_all_does_mean_off(self):
        """A device where the feature was never switched on."""
        self.active.add('bluetooth.service')
        self.mod.Supervisor().tick()
        self.assertIn(['bluetoothctl', 'power', 'off'], self.calls)
        self.assertFalse(self._status()['enabled'])


class UnitFileTests(unittest.TestCase):
    """The systemd units the image ships. Two rules here are load-bearing and
    both look like tidy-up bait to anyone reading them later, so they are
    pinned: the agent's stop signal, and which unit may carry [Install]."""

    UNITS = os.path.join(REPO, 'distro', 'config', 'includes.chroot',
                         'etc', 'systemd', 'system')

    SBIN = os.path.join(REPO, 'distro', 'config', 'includes.chroot',
                        'usr', 'local', 'sbin')

    def _unit(self, name):
        with open(os.path.join(self.UNITS, name)) as f:
            return f.read()

    def _sbin(self, name):
        with open(os.path.join(self.SBIN, name)) as f:
            return f.read()

    def test_bluealsa_is_never_given_an_option_it_may_not_know(self):
        """🚨 BlueALSA exits on an unrecognised option, and its unit restarts
        it for ever: what the owner gets is not a missing refinement but every
        speaker dropping out every three seconds. --keep-alive only exists
        from 4.0, and a device upgraded through the OTA path can be on 3.x, so
        it is asked for the same way the optional codecs are."""
        text = self._sbin('hifi-bluealsa-run.sh')
        exec_line = [l for l in text.splitlines() if l.startswith('exec ')][0]
        self.assertNotIn('--keep-alive', exec_line)
        self.assertIn('$KEEPALIVE', exec_line)
        self.assertIn('*keep-alive*)', text)

    def test_the_pairing_agent_is_stopped_with_SIGINT(self):
        """🚨 bluez-tools wires bt-agent's handlers up crossed: SIGTERM lands
        in the SIGUSR1 handler and returns G_SOURCE_CONTINUE, so bt-agent
        deliberately keeps running. systemd then waits out its 90-second
        default and the appliance appears not to switch off. SIGINT is the one
        that quits the main loop."""
        unit = self._unit('hifi-bt-agent.service')
        self.assertIn('KillSignal=SIGINT', unit)
        stop = [l for l in unit.splitlines() if l.startswith('TimeoutStopSec=')]
        self.assertTrue(stop, 'no TimeoutStopSec: a future bluez-tools could hold a shutdown again')
        self.assertLessEqual(int(stop[0].split('=')[1]), 10)

    def test_only_the_supervisor_may_be_enabled(self):
        """Everything else is started by hifi-bt-out.service. An [Install]
        section on any of them invites a `systemctl enable` that then vanishes
        at the next A/B image swap, leaving Bluetooth mysteriously off."""
        for name in ('hifi-bluealsa.service', 'hifi-bt-agent.service',
                     'hifi-bt-player@.service'):
            self.assertNotIn('[Install]', self._unit(name), name)
        self.assertIn('WantedBy=multi-user.target', self._unit('hifi-bt-out.service'))

    def test_the_image_enables_the_supervisor_and_nothing_else_bluetooth(self):
        hook = os.path.join(REPO, 'distro', 'config', 'hooks', 'normal',
                            '0400-enable-services.hook.chroot')
        with open(hook) as f:
            text = f.read()
        enabled = [l.split()[2] for l in text.splitlines()
                   if l.startswith('systemctl enable ') and ('bt' in l or 'blue' in l)]
        self.assertEqual(enabled, ['hifi-bt-out.service'])
        self.assertIn('systemctl disable bluetooth.service', text)

    def test_the_players_die_with_bluealsa(self):
        """The PCM goes away with the daemon; a squeezelite left pointing at
        it is a restart loop, not a player."""
        self.assertIn('BindsTo=hifi-bluealsa.service', self._unit('hifi-bt-player@.service'))


if __name__ == '__main__':
    unittest.main()
