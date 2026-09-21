"""Bluetooth remote controls in api_server.py.

A remote is an input device, not an output: once paired and trusted the
kernel gives it a /dev/input node and the on-screen interface reads the keys
itself (native-ui-qt/src/remote.cpp). So api_server only has to pair one, and
forget one — but doing that on this appliance has two traps, and these tests
pin both:

  * the radio. Bluetooth is off on a box whose owner never asked for it, and
    the supervisor owns it. A remote has to be paired BEFORE there is a remote
    to keep the radio on for, so a scan writes a pairing window into the state
    file and waits for the adapter. It must never enable a unit itself.
  * the two halves of the feature travel apart (api_server in an app update,
    the supervisor in the image). On a device whose supervisor does not know
    about remotes, a pairing window would be ignored and BlueZ torn down
    mid-pairing, so pairing must refuse with "update first" instead.

Everything else is the speakers' pattern: one state file, and an address from
a network request that is checked before it reaches a subprocess.

Run with:  python tests/test_bt_remotes.py
"""
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

REMOTE = 'C8:3F:26:11:22:33'
SPEAKER = 'F4:2B:7D:63:98:D7'


def _cp(cmd, rc=0, stdout='', stderr=''):
    return subprocess.CompletedProcess(cmd, rc, stdout=stdout, stderr=stderr)


class RemoteTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='hifi-rm-test-')
        self._saved = {}
        self._patch('BT_STATE_FILE', os.path.join(self.tmp, 'etc', 'bluetooth.json'))
        self._patch('BT_STATUS_FILE', os.path.join(self.tmp, 'run', 'output.json'))
        os.makedirs(os.path.join(self.tmp, 'etc'))
        os.makedirs(os.path.join(self.tmp, 'run'))

        self.known = {}          # mac -> what BlueZ says about it
        self.calls = []          # every argv, in order
        self.pair_succeeds = True

        p = patch.object(api_server, '_bt_remotes_available', lambda: True)
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(api_server.subprocess, 'run', self._fake_run)
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(api_server.time, 'sleep', lambda *_: None)
        p.start()
        self.addCleanup(p.stop)
        # the supervisor answers "radio up, and I know about remotes"
        self._write_snapshot({'enabled': False, 'adapter': True, 'speakers': [], 'remotes': []})

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
        return _cp(cmd)

    def _bluetoothctl(self, cmd):
        verb = cmd[1] if len(cmd) > 1 else ''
        if verb == '--timeout':          # bluetoothctl --timeout N scan on
            return _cp(cmd)
        if verb == 'devices':
            return _cp(cmd, stdout=''.join(f'Device {m} {d["name"]}\n'
                                           for m, d in self.known.items()))
        if verb == 'info':
            d = self.known.get(cmd[2])
            if not d:
                return _cp(cmd, rc=1, stdout='Device not available\n')
            uuids = ''
            if d['audio']:
                uuids += '\tUUID: Audio Sink (0000110b-0000-1000-8000-00805f9b34fb)\n'
            if d['input']:
                uuids += '\tUUID: Human Interface Device (00001124-0000-1000-8000-00805f9b34fb)\n'
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
            return _cp(cmd)
        if verb == 'connect':
            self.known[cmd[2]]['connected'] = True
            return _cp(cmd)
        if verb == 'remove':
            return _cp(cmd) if self.known.pop(cmd[2], None) else _cp(cmd, rc=1)
        return _cp(cmd)

    # ── helpers ──────────────────────────────────────────────────────
    def _see(self, mac, name, input_=True, audio=False, paired=False, connected=False):
        self.known[mac] = {'name': name, 'paired': paired, 'trusted': False,
                           'connected': connected, 'audio': audio, 'input': input_}

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


class PairingWindowTests(RemoteTestCase):

    def test_a_scan_opens_the_window_and_signals_the_supervisor(self):
        out = api_server.bt_remotes_scan(5)
        self.assertTrue(out['success'], out)
        self.assertGreater(self._state()['remote_pairing_until'], 0)
        self.assertEqual(
            self._argv('systemctl', 'kill', '-s', 'HUP', 'hifi-bt-out.service'),
            [['systemctl', 'kill', '-s', 'HUP', 'hifi-bt-out.service']])

    def test_pairing_never_enables_or_starts_a_unit_itself(self):
        """🚨 The supervisor owns BlueZ. Starting bluetoothd from here would
        be torn down again on its next pass, halfway through a pairing."""
        self._see(REMOTE, 'Osmium Remote')
        api_server.bt_remotes_scan(5)
        api_server.bt_remote_add(REMOTE)
        self.assertEqual(self._argv('systemctl', 'enable'), [])
        self.assertEqual(self._argv('systemctl', 'start'), [])

    def test_an_old_supervisor_is_told_to_update_instead(self):
        """A snapshot with no `remotes` key is a system half that predates
        this feature: it would tear the radio down mid-pairing."""
        self._write_snapshot({'enabled': False, 'adapter': True, 'speakers': []})
        self._see(REMOTE, 'Osmium Remote')
        out = api_server.bt_remote_add(REMOTE)
        self.assertFalse(out['success'])
        self.assertEqual(out['code'], 'bluetooth.remoteNeedsUpdate')
        self.assertEqual(self._argv('bluetoothctl', 'pair'), [])

    def test_no_adapter_is_reported_rather_than_pairing_blind(self):
        self._write_snapshot({'enabled': False, 'adapter': False, 'speakers': [], 'remotes': []})
        self._see(REMOTE, 'Osmium Remote')
        out = api_server.bt_remote_add(REMOTE)
        self.assertFalse(out['success'])
        self.assertEqual(out['code'], 'bluetooth.noAdapter')


class AddAndForgetTests(RemoteTestCase):

    def test_adding_pairs_trusts_and_remembers(self):
        self._see(REMOTE, 'Osmium Remote')
        out = api_server.bt_remote_add(REMOTE)
        self.assertTrue(out['success'], out)
        self.assertEqual(self._argv('bluetoothctl', 'pair', REMOTE),
                         [['bluetoothctl', 'pair', REMOTE]])
        # trusting is what lets it come back on its own after a night in a drawer
        self.assertEqual(self._argv('bluetoothctl', 'trust', REMOTE),
                         [['bluetoothctl', 'trust', REMOTE]])
        self.assertEqual([r['mac'] for r in self._state()['remotes']], [REMOTE])
        self.assertEqual(self._state()['remotes'][0]['name'], 'Osmium Remote')

    def test_a_failed_pairing_is_not_remembered(self):
        self._see(REMOTE, 'Osmium Remote')
        self.pair_succeeds = False
        out = api_server.bt_remote_add(REMOTE)
        self.assertFalse(out['success'])
        self.assertEqual(out['code'], 'bluetooth.remotePairFailed')
        self.assertEqual(self._state()['remotes'], [])

    def test_a_remote_does_not_disturb_the_speakers(self):
        self._write_state({'enabled': True,
                           'speakers': [{'mac': SPEAKER, 'name': 'Cucina'}]})
        self._see(REMOTE, 'Osmium Remote')
        api_server.bt_remote_add(REMOTE)
        doc = self._state()
        self.assertTrue(doc['enabled'])
        self.assertEqual([s['mac'] for s in doc['speakers']], [SPEAKER])
        self.assertEqual([r['mac'] for r in doc['remotes']], [REMOTE])

    def test_the_same_remote_twice_is_refused(self):
        self._see(REMOTE, 'Osmium Remote')
        api_server.bt_remote_add(REMOTE)
        out = api_server.bt_remote_add(REMOTE)
        self.assertFalse(out['success'])
        self.assertEqual(out['code'], 'bluetooth.remoteAlreadyAdded')

    def test_forgetting_unpairs_and_drops_it_from_the_file(self):
        self._see(REMOTE, 'Osmium Remote')
        api_server.bt_remote_add(REMOTE)
        out = api_server.bt_remote_remove(REMOTE)
        self.assertTrue(out['success'], out)
        self.assertEqual(self._state()['remotes'], [])
        self.assertEqual(self._argv('bluetoothctl', 'remove', REMOTE),
                         [['bluetoothctl', 'remove', REMOTE]])

    def test_forgetting_something_that_is_not_there(self):
        out = api_server.bt_remote_remove(REMOTE)
        self.assertFalse(out['success'])
        self.assertEqual(out['code'], 'bluetooth.remoteNotFound')

    def test_an_address_from_the_network_never_reaches_a_subprocess(self):
        for bad in ('', 'not-a-mac', 'C8:3F:26:11:22:33; rm -rf /', '../../etc/passwd',
                    'C8:3F:26:11:22', 'C8-3F-26-11-22-33'):
            out = api_server.bt_remote_add(bad)
            self.assertFalse(out['success'], bad)
            self.assertEqual(out['code'], 'bluetooth.invalidAddress', bad)
            out = api_server.bt_remote_remove(bad)
            self.assertFalse(out['success'], bad)
        self.assertEqual(self._argv('bluetoothctl', 'pair'), [])
        self.assertEqual(self._argv('bluetoothctl', 'remove'), [])


class StatusTests(RemoteTestCase):

    def test_found_leaves_out_speakers_and_what_is_already_paired(self):
        self._see(REMOTE, 'Osmium Remote')
        self._see('AA:BB:CC:DD:EE:01', 'Cuffie', input_=False, audio=True)
        self._see('AA:BB:CC:DD:EE:02', 'Tastiera')
        api_server.bt_remote_add(REMOTE)
        found = api_server.get_bt_remotes()['found']
        macs = [d['mac'] for d in found]
        self.assertIn('AA:BB:CC:DD:EE:02', macs)
        self.assertNotIn('AA:BB:CC:DD:EE:01', macs, 'a speaker is not a remote')
        self.assertNotIn(REMOTE, macs, 'already paired')

    def test_a_remote_is_recognised_as_an_input_device(self):
        self._see(REMOTE, 'Osmium Remote')
        found = api_server.get_bt_remotes()['found']
        self.assertEqual(found[0]['mac'], REMOTE)
        self.assertTrue(found[0]['input'])

    def test_connected_comes_from_the_supervisor_snapshot(self):
        self._write_state({'enabled': False, 'speakers': [],
                           'remotes': [{'mac': REMOTE, 'name': 'Osmium Remote'}]})
        self._write_snapshot({'enabled': False, 'adapter': True, 'speakers': [],
                              'remotes': [{'mac': REMOTE, 'connected': True}]})
        rows = api_server.get_bt_remotes()['remotes']
        self.assertEqual(rows, [{'mac': REMOTE, 'name': 'Osmium Remote', 'connected': True}])

    def test_nothing_is_listed_while_the_radio_is_down(self):
        self._write_snapshot({'enabled': False, 'adapter': False, 'speakers': [], 'remotes': []})
        self._see(REMOTE, 'Osmium Remote')
        out = api_server.get_bt_remotes()
        self.assertEqual(out['found'], [])
        self.assertFalse(out['adapter'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
