"""Joining a Wi-Fi network from the post-setup UIs (api_server.wifi_connect).

The case that matters is re-joining a network the box has already used: the
`nmcli device wifi connect` shorthand pushes the password into the existing
profile as a bare `psk`, NetworkManager refuses the update with
"802-11-wireless-security.key-mgmt: property is missing" (issue #98), and
Wi-Fi becomes unreachable from every UI until the profile is removed by hand.
These tests pin the profile-building path that replaces it, the key management
it picks per security type, and the "don't touch a saved profile the user
typed no password for" rule.
"""
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import api_server  # noqa: E402  (needs the path above)


def _cp(cmd, rc=0, stdout='', stderr=''):
    return subprocess.CompletedProcess(cmd, rc, stdout=stdout, stderr=stderr)


class WifiConnectTests(unittest.TestCase):
    #: SSID -> SECURITY, as `nmcli -t -f SSID,SECURITY device wifi list` prints it
    SCAN = {'HomeNet': 'WPA2', 'Legacy': 'WEP', 'Cafe': '',
            'NewNet': 'WPA2 WPA3', 'FutureNet': 'WPA3'}

    def setUp(self):
        self.calls = []          # every nmcli argv, in order
        self.profiles = set()    # Wi-Fi profile names NetworkManager holds
        self.up_results = [0]    # return codes for successive `connection up`
        self.add_rc = 0
        #: profile name -> `nmcli -t -f ipv4.* connection show` output
        self.profile_ipv4 = {}

    # ── stubs ────────────────────────────────────────────────────────
    def _fake_run(self, cmd, timeout=20):
        self.calls.append(cmd)
        if cmd[:5] == ['nmcli', '-t', '-f', 'NAME,TYPE', 'connection']:
            rows = ''.join(f'{n}:802-11-wireless\n' for n in sorted(self.profiles))
            return _cp(cmd, stdout=rows)
        if cmd[:5] == ['nmcli', '-t', '-f', 'SSID,SECURITY', 'device']:
            rows = ''.join(f'{s}:{sec}\n' for s, sec in self.SCAN.items())
            return _cp(cmd, stdout=rows)
        if cmd[3].startswith('ipv4.method') and cmd[4:6] == ['connection', 'show']:
            return _cp(cmd, stdout=self.profile_ipv4.get(cmd[-1], ''))
        if cmd[1:3] == ['connection', 'delete']:
            self.profiles.discard(cmd[-1])
            return _cp(cmd)
        if cmd[1:3] == ['connection', 'add']:
            if self.add_rc == 0:
                self.profiles.add(cmd[cmd.index('con-name') + 1])
            return _cp(cmd, rc=self.add_rc, stderr='add refused' if self.add_rc else '')
        if cmd[1:3] == ['connection', 'up']:
            rc = self.up_results.pop(0) if self.up_results else 4
            return _cp(cmd, rc=rc, stderr='activation failed' if rc else '')
        if cmd[1:4] == ['device', 'wifi', 'connect']:
            return _cp(cmd)
        return _cp(cmd)

    def _connect(self, ssid, password, wifi_dev='wlan0', ip='192.168.1.40'):
        self.enabled = []
        with patch.object(api_server, '_run', self._fake_run), \
             patch.object(api_server, '_first_device_of_type',
                          lambda t: wifi_dev if t == 'wifi' else 'eth0'), \
             patch.object(api_server, '_ensure_networkmanager_state', lambda *a: None), \
             patch.object(api_server, '_ensure_dhcp_ip', lambda dev, **kw: ip), \
             patch.object(api_server, '_set_interface_enabled',
                          lambda t, on: self.enabled.append((t, on))), \
             patch.object(api_server.time, 'sleep', lambda *a: None):
            # time.sleep is the retry backoff inside _wifi_join; api_server.time
            # is the stdlib module, so this is restored on exit rather than left
            # patched for the process.
            return api_server.wifi_connect(ssid, password)

    def _argv(self, *prefix):
        """The first recorded nmcli call starting with these arguments."""
        for cmd in self.calls:
            if cmd[:len(prefix)] == list(prefix):
                return cmd
        return None

    # ── the reported bug ─────────────────────────────────────────────
    def test_rejoining_a_known_network_rebuilds_the_profile(self):
        """Issue #98: with a profile already on disk the shorthand is unusable."""
        self.profiles.add('HomeNet')
        res = self._connect('HomeNet', 'hunter2hunter2')
        self.assertTrue(res['success'], res)
        # The stale profile goes first — that's what made NetworkManager reject
        # the update with the missing key-mgmt.
        self.assertEqual(self._argv('nmcli', 'connection', 'delete'),
                         ['nmcli', 'connection', 'delete', 'id', 'HomeNet'])
        add = self._argv('nmcli', 'connection', 'add')
        self.assertIn('802-11-wireless-security.key-mgmt', add)
        self.assertEqual(add[add.index('802-11-wireless-security.key-mgmt') + 1], 'wpa-psk')
        self.assertEqual(add[add.index('802-11-wireless-security.psk') + 1], 'hunter2hunter2')
        self.assertEqual(add[add.index('ifname') + 1], 'wlan0')
        self.assertIsNotNone(self._argv('nmcli', 'connection', 'up', 'id', 'HomeNet'))
        # …and the shorthand is not used at all any more.
        self.assertIsNone(self._argv('nmcli', 'device', 'wifi', 'connect'))

    def test_first_time_join_takes_the_same_path(self):
        """A never-seen network is joined the same way, not via a second path."""
        res = self._connect('HomeNet', 'hunter2hunter2')
        self.assertTrue(res['success'], res)
        self.assertIsNotNone(self._argv('nmcli', 'connection', 'add'))
        self.assertIsNone(self._argv('nmcli', 'device', 'wifi', 'connect'))

    # ── key management per security type ─────────────────────────────
    def _keymgmt(self, ssid, password='hunter2hunter2'):
        self._connect(ssid, password)
        add = self._argv('nmcli', 'connection', 'add')
        if '802-11-wireless-security.key-mgmt' not in add:
            return None
        return add[add.index('802-11-wireless-security.key-mgmt') + 1]

    def test_wpa2_uses_psk(self):
        self.assertEqual(self._keymgmt('HomeNet'), 'wpa-psk')

    def test_wpa3_only_uses_sae(self):
        self.assertEqual(self._keymgmt('FutureNet'), 'sae')

    def test_wpa2_wpa3_transition_ap_still_uses_psk(self):
        # Both are advertised; wpa-psk is what associates with such an AP.
        self.assertEqual(self._keymgmt('NewNet'), 'wpa-psk')

    def test_unknown_ssid_falls_back_to_psk(self):
        # Not in the scan list (the card's passive cache can miss a live
        # network) — assume the home-network case rather than give up.
        self.assertEqual(self._keymgmt('Hidden'), 'wpa-psk')

    def test_open_network_gets_no_security_setting(self):
        # Scanned and reported open: a typed password would make the profile
        # unusable, so it is dropped rather than written.
        self.assertIsNone(self._keymgmt('Cafe'))

    def test_wep_passphrase_and_key_are_told_apart(self):
        self._connect('Legacy', 'a-longer-wep-passphrase')
        add = self._argv('nmcli', 'connection', 'add')
        self.assertEqual(add[add.index('802-11-wireless-security.key-mgmt') + 1], 'none')
        self.assertEqual(add[add.index('802-11-wireless-security.wep-key0') + 1],
                         'a-longer-wep-passphrase')
        self.assertEqual(add[add.index('802-11-wireless-security.wep-key-type') + 1], '2')
        self.setUp()
        self._connect('Legacy', 'ABCDE')          # 5 characters: a raw key
        add = self._argv('nmcli', 'connection', 'add')
        self.assertEqual(add[add.index('802-11-wireless-security.wep-key-type') + 1], '1')

    # ── no password typed ────────────────────────────────────────────
    def test_saved_profile_is_activated_not_rewritten(self):
        """No password means no new secret: the saved one must survive."""
        self.profiles.add('HomeNet')
        res = self._connect('HomeNet', '')
        self.assertTrue(res['success'], res)
        self.assertIsNone(self._argv('nmcli', 'connection', 'delete'))
        self.assertIsNone(self._argv('nmcli', 'connection', 'add'))
        self.assertIsNotNone(self._argv('nmcli', 'connection', 'up', 'id', 'HomeNet'))

    def test_open_network_without_a_profile_uses_the_shorthand(self):
        res = self._connect('Cafe', '')
        self.assertTrue(res['success'], res)
        self.assertEqual(self._argv('nmcli', 'device', 'wifi', 'connect'),
                         ['nmcli', 'device', 'wifi', 'connect', 'Cafe'])

    # ── failure handling ─────────────────────────────────────────────
    def test_activation_is_retried_once(self):
        self.up_results = [4, 0]
        res = self._connect('HomeNet', 'hunter2hunter2')
        self.assertTrue(res['success'], res)
        self.assertEqual(sum(1 for c in self.calls if c[1:3] == ['connection', 'up']), 2)

    def test_a_profile_that_never_associates_is_removed(self):
        self.up_results = [4, 4]
        res = self._connect('HomeNet', 'wrong-password')
        self.assertFalse(res['success'])
        self.assertEqual(res['code'], 'network.connectFailed')
        self.assertEqual(res['message'], 'activation failed')
        # Nothing left behind for the next attempt to trip over.
        self.assertNotIn('HomeNet', self.profiles)
        self.assertEqual(self.enabled, [])   # and the cable is left alone

    def test_add_failure_is_reported_verbatim(self):
        self.add_rc = 2
        res = self._connect('HomeNet', 'hunter2hunter2')
        self.assertFalse(res['success'])
        self.assertEqual(res['message'], 'add refused')
        self.assertIsNone(self._argv('nmcli', 'connection', 'up'))

    # ── a fixed address on a Wi-Fi profile ───────────────────────────
    def test_a_fixed_address_survives_the_rebuild(self):
        """The admin web UI can put a fixed address on Wi-Fi, and it lives on
        the very profile the join rebuilds — losing it would move a headless
        box to some other address the owner never chose."""
        self.profiles.add('HomeNet')
        self.profile_ipv4['HomeNet'] = ('ipv4.method:manual\n'
                                        'ipv4.addresses:192.168.1.90/24\n'
                                        'ipv4.gateway:192.168.1.1\n'
                                        'ipv4.dns:192.168.1.1,1.1.1.1\n')
        res = self._connect('HomeNet', 'hunter2hunter2', ip='192.168.1.90')
        self.assertTrue(res['success'], res)
        add = self._argv('nmcli', 'connection', 'add')
        self.assertEqual(add[add.index('ipv4.method') + 1], 'manual')
        self.assertEqual(add[add.index('ipv4.addresses') + 1], '192.168.1.90/24')
        self.assertEqual(add[add.index('ipv4.gateway') + 1], '192.168.1.1')
        self.assertEqual(add[add.index('ipv4.dns') + 1], '192.168.1.1 1.1.1.1')
        self.assertEqual(add[add.index('ipv4.ignore-auto-dns') + 1], 'yes')

    def test_a_dhcp_profile_is_left_on_dhcp(self):
        self.profiles.add('HomeNet')
        self.profile_ipv4['HomeNet'] = 'ipv4.method:auto\n'
        self._connect('HomeNet', 'hunter2hunter2')
        self.assertNotIn('ipv4.method', self._argv('nmcli', 'connection', 'add'))

    def test_a_new_network_is_not_given_an_address(self):
        # Nothing to carry over: no profile existed, so nothing is read either.
        self._connect('HomeNet', 'hunter2hunter2')
        self.assertNotIn('ipv4.method', self._argv('nmcli', 'connection', 'add'))
        self.assertIsNone(self._argv('nmcli', '-t', '-f', 'ipv4.method,ipv4.addresses,'
                                     'ipv4.gateway,ipv4.dns'))

    # ── the exclusivity flip ─────────────────────────────────────────
    def test_ip_is_read_from_the_wifi_interface(self):
        """Not from _active_device(), which prefers Ethernet: on a box that is
        still cabled that returned the wired address, so Wi-Fi looked up and
        the cable got turned off on the strength of the cable's own IP."""
        seen = []
        with patch.object(api_server, '_run', self._fake_run), \
             patch.object(api_server, '_first_device_of_type',
                          lambda t: 'wlan0' if t == 'wifi' else 'eth0'), \
             patch.object(api_server, '_ensure_networkmanager_state', lambda *a: None), \
             patch.object(api_server, '_ensure_dhcp_ip',
                          lambda dev, **kw: seen.append(dev) or '192.168.1.40'), \
             patch.object(api_server, '_set_interface_enabled', lambda t, on: None), \
             patch.object(api_server, '_active_device',
                          lambda: self.fail('_active_device() prefers Ethernet')):
            res = api_server.wifi_connect('HomeNet', 'hunter2hunter2')
        self.assertTrue(res['success'], res)
        self.assertEqual(seen, ['wlan0'])
        self.assertEqual(res['ip'], '192.168.1.40')

    def test_exclusivity_only_flips_once_wifi_has_an_ip(self):
        res = self._connect('HomeNet', 'hunter2hunter2', ip=None)
        self.assertTrue(res['success'], res)
        self.assertIsNone(res['ip'])
        self.assertEqual(self.enabled, [])
        self.setUp()
        self._connect('HomeNet', 'hunter2hunter2', ip='192.168.1.40')
        self.assertEqual(self.enabled, [('wifi', True), ('ethernet', False)])

    # ── argv safety (unchanged behaviour, kept pinned) ───────────────
    def test_missing_and_unsafe_values_are_refused(self):
        self.assertEqual(self._connect('', 'pw')['code'], 'network.ssidMissing')
        self.assertEqual(self._connect('-oProxyCommand', 'pw')['code'], 'network.invalidField')
        self.assertEqual(self._connect('HomeNet', 'pw\nmore')['code'], 'network.invalidField')
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
