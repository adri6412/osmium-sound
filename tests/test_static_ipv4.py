"""Static (fixed) IPv4 configuration — admin-webui only.

Covers the validation that keeps a headless box reachable (a gateway outside
the configured subnet, a network/broadcast address, a bad prefix) and the
exact nmcli arguments the accepted cases produce, since those are what decide
whether the address survives a reboot.
"""
import ast
import os
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import api_server  # noqa: E402  (needs the path above)


def _route_table(name):
    """Read a route dict out of webui_server.py without importing it.

    Importing webui_server under a unittest runner sends the runner into an
    endless re-run loop in this tree (it breaks test_networkmanager_recovery.py
    the same way, with or without this feature) — and both dicts are plain
    literals, so parsing them is exact rather than a stand-in."""
    with open(os.path.join(REPO, 'webui_server.py'), encoding='utf-8') as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') == name:
            return ast.literal_eval(node.value)
    raise AssertionError(f'{name} not found in webui_server.py')


def _ok(cmd, stdout=''):
    return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr='')


class Ipv4HelperTests(unittest.TestCase):
    def test_prefix_bounds(self):
        for good in (8, 16, 24, '24', 30):
            self.assertTrue(api_server._valid_prefix(good), good)
        # /31 and /32 leave no room for a host+gateway pair.
        for bad in (0, 31, 32, 33, -1, None, '', 'abc'):
            self.assertFalse(api_server._valid_prefix(bad), bad)

    def test_same_subnet(self):
        self.assertTrue(api_server._same_subnet('192.168.1.50', '192.168.1.1', 24))
        self.assertFalse(api_server._same_subnet('192.168.1.50', '192.168.2.1', 24))
        # A /16 makes the same pair legitimate again.
        self.assertTrue(api_server._same_subnet('192.168.1.50', '192.168.2.1', 16))

    def test_assignable_host(self):
        self.assertTrue(api_server._assignable_host('192.168.1.50', 24))
        self.assertFalse(api_server._assignable_host('192.168.1.0', 24))    # network
        self.assertFalse(api_server._assignable_host('192.168.1.255', 24))  # broadcast
        self.assertFalse(api_server._assignable_host('127.0.0.1', 24))      # loopback
        self.assertFalse(api_server._assignable_host('224.0.0.5', 24))      # multicast
        self.assertFalse(api_server._assignable_host('0.10.0.1', 24))

    def test_parse_dns_accepts_string_and_list(self):
        self.assertEqual(api_server._parse_dns('1.1.1.1, 8.8.8.8'), ['1.1.1.1', '8.8.8.8'])
        self.assertEqual(api_server._parse_dns('1.1.1.1 8.8.8.8'), ['1.1.1.1', '8.8.8.8'])
        self.assertEqual(api_server._parse_dns(['1.1.1.1']), ['1.1.1.1'])
        self.assertEqual(api_server._parse_dns(''), [])
        self.assertEqual(api_server._parse_dns(None), [])


class SetIpv4ConfigTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def _fake_run(self, cmd, timeout=20):
        self.calls.append(cmd)
        return _ok(cmd)

    def _apply(self, cfg, device='eth0', dtype='ethernet', conn='Wired connection 1'):
        """Run set_ipv4_config with the network stack stubbed out.

        The background re-activation is stubbed at `_bg_apply_ipv4` rather
        than at threading.Thread: `api_server.threading` *is* the stdlib
        module, so patching Thread there would swap it out process-wide."""
        self.applied = None
        done = threading.Event()

        def fake_bg(*args):
            self.applied = args
            done.set()

        with patch.object(api_server, '_run', side_effect=self._fake_run), \
             patch.object(api_server, '_active_device', return_value=(device, dtype)), \
             patch.object(api_server, '_active_connection_name', return_value=conn), \
             patch.object(api_server, '_bg_apply_ipv4', side_effect=fake_bg):
            result = api_server.set_ipv4_config(cfg)
            self.scheduled = done.wait(5) if result.get('success') else False
        return result

    def test_manual_builds_nmcli_modify(self):
        r = self._apply({'mode': 'manual', 'address': '192.168.1.50', 'prefix': 24,
                         'gateway': '192.168.1.1', 'dns': '1.1.1.1, 8.8.8.8'})
        self.assertTrue(r['success'], r)
        self.assertEqual(r['address'], '192.168.1.50')
        modify = self.calls[0]
        self.assertEqual(modify[:4], ['nmcli', 'connection', 'modify', 'Wired connection 1'])
        # The address has to land in the *profile* (survives reboot), not on
        # the live interface only.
        self.assertIn('ipv4.addresses', modify)
        self.assertEqual(modify[modify.index('ipv4.addresses') + 1], '192.168.1.50/24')
        self.assertEqual(modify[modify.index('ipv4.gateway') + 1], '192.168.1.1')
        self.assertEqual(modify[modify.index('ipv4.dns') + 1], '1.1.1.1 8.8.8.8')
        self.assertEqual(modify[modify.index('ipv4.method') + 1], 'manual')
        # Without autoconnect the box comes back on a different address.
        self.assertIn(['nmcli', 'connection', 'modify', 'Wired connection 1',
                       'connection.autoconnect', 'yes'], self.calls)
        # The re-activation runs in the background so the reply reaches the
        # browser before the address moves out from under it.
        self.assertTrue(self.scheduled)
        self.assertEqual(self.applied, ('Wired connection 1', 'eth0', '192.168.1.50'))

    def test_manual_without_dns_falls_back_to_gateway(self):
        r = self._apply({'mode': 'manual', 'address': '192.168.1.50', 'prefix': 24,
                         'gateway': '192.168.1.1', 'dns': ''})
        self.assertTrue(r['success'], r)
        modify = self.calls[0]
        self.assertEqual(modify[modify.index('ipv4.dns') + 1], '192.168.1.1')

    def test_manual_caps_dns_at_three(self):
        r = self._apply({'mode': 'manual', 'address': '192.168.1.50', 'prefix': 24,
                         'gateway': '192.168.1.1',
                         'dns': '1.1.1.1, 8.8.8.8, 9.9.9.9, 8.8.4.4'})
        self.assertTrue(r['success'], r)
        modify = self.calls[0]
        self.assertEqual(modify[modify.index('ipv4.dns') + 1], '1.1.1.1 8.8.8.8 9.9.9.9')

    def test_auto_clears_the_static_fields(self):
        r = self._apply({'mode': 'auto'})
        self.assertTrue(r['success'], r)
        # No expected address on DHCP: any lease counts as success.
        self.assertEqual(self.applied, ('Wired connection 1', 'eth0', None))
        modify = self.calls[0]
        self.assertEqual(modify[modify.index('ipv4.method') + 1], 'auto')
        # Leftover addresses/gateway/dns would otherwise stay in the profile.
        self.assertEqual(modify[modify.index('ipv4.addresses') + 1], '')
        self.assertEqual(modify[modify.index('ipv4.gateway') + 1], '')
        self.assertEqual(modify[modify.index('ipv4.dns') + 1], '')

    def test_legacy_mode_names_accepted(self):
        self.assertTrue(self._apply({'mode': 'dhcp'})['success'])
        self.setUp()
        self.assertTrue(self._apply({'mode': 'static', 'address': '192.168.1.50',
                                     'prefix': 24, 'gateway': '192.168.1.1'})['success'])

    def _assert_rejected(self, cfg, code):
        r = self._apply(cfg)
        self.assertFalse(r['success'], r)
        self.assertEqual(r['code'], code)
        # Nothing may reach nmcli once validation fails.
        self.assertEqual(self.calls, [])
        self.assertTrue(r['message'])

    def test_rejects_gateway_outside_subnet(self):
        self._assert_rejected(
            {'mode': 'manual', 'address': '192.168.1.50', 'prefix': 24, 'gateway': '10.0.0.1'},
            'network.gatewayOutsideSubnet')

    def test_rejects_bad_values(self):
        base = {'mode': 'manual', 'address': '192.168.1.50', 'prefix': 24, 'gateway': '192.168.1.1'}
        self._assert_rejected({**base, 'address': '192.168.1.999'}, 'network.invalidAddress')
        self.setUp()
        self._assert_rejected({**base, 'address': ''}, 'network.invalidAddress')
        self.setUp()
        self._assert_rejected({**base, 'prefix': 33}, 'network.invalidPrefix')
        self.setUp()
        self._assert_rejected({**base, 'address': '192.168.1.0'}, 'network.unusableAddress')
        self.setUp()
        self._assert_rejected({**base, 'gateway': 'nope'}, 'network.invalidGateway')
        self.setUp()
        # Network address: passes the same-subnet check but never answers ARP.
        self._assert_rejected({**base, 'gateway': '192.168.1.0'}, 'network.invalidGateway')
        self.setUp()
        self._assert_rejected({**base, 'gateway': '192.168.1.255'}, 'network.invalidGateway')
        self.setUp()
        # Its own address as the gateway is a silent no-route-out.
        self._assert_rejected({**base, 'gateway': '192.168.1.50'}, 'network.invalidGateway')
        self.setUp()
        self._assert_rejected({**base, 'dns': '1.1.1.1, bogus'}, 'network.invalidDns')
        self.setUp()
        self._assert_rejected({**base, 'mode': 'sideways'}, 'network.invalidMode')

    def test_no_active_uplink(self):
        with patch.object(api_server, '_run', side_effect=self._fake_run), \
             patch.object(api_server, '_active_device', return_value=(None, None)):
            r = api_server.set_ipv4_config({'mode': 'auto'})
        self.assertFalse(r['success'])
        self.assertEqual(r['code'], 'network.noActiveConnection')


class BgApplyIpv4Tests(unittest.TestCase):
    """The background re-activation is the last line of defence: a box that
    keeps a static address it can't actually bring up is off the network with
    no way back in short of a keyboard and a monitor."""

    def _run_bg(self, conn, device, expect_ip, ips):
        """`ips` is the sequence _device_ip returns on successive polls."""
        calls = []
        seq = list(ips)

        def fake_run(cmd, timeout=20):
            calls.append(cmd)
            return _ok(cmd)

        def fake_device_ip(dev):
            return seq.pop(0) if seq else None

        with patch.object(api_server, '_run', side_effect=fake_run), \
             patch.object(api_server, '_device_ip', side_effect=fake_device_ip), \
             patch.object(api_server.time, 'sleep'), \
             patch.object(api_server.time, 'monotonic', side_effect=_clock()):
            api_server._bg_apply_ipv4(conn, device, expect_ip)
        return calls

    def test_reverts_to_dhcp_when_the_address_never_comes_up(self):
        calls = self._run_bg('Wired connection 1', 'eth0', '192.168.1.50', ips=[])
        modifies = [c for c in calls if c[:3] == ['nmcli', 'connection', 'modify']]
        self.assertTrue(modifies, calls)
        rollback = modifies[-1]
        self.assertEqual(rollback[rollback.index('ipv4.method') + 1], 'auto')
        self.assertEqual(rollback[rollback.index('ipv4.addresses') + 1], '')
        # And the DHCP profile is actually brought back up.
        self.assertEqual(calls[-1][:3], ['nmcli', 'connection', 'up'])

    def test_keeps_the_static_address_once_it_is_up(self):
        calls = self._run_bg('Wired connection 1', 'eth0', '192.168.1.50',
                             ips=[None, '192.168.1.50'])
        self.assertEqual([c for c in calls if c[:3] == ['nmcli', 'connection', 'modify']], [])
        self.assertEqual(calls, [['nmcli', 'connection', 'up', 'Wired connection 1']])

    def test_a_different_address_is_treated_as_failure(self):
        """NM falling back to a DHCP lease means the manual profile did not
        take — reverting keeps the profile honest about what it will do."""
        calls = self._run_bg('Wired connection 1', 'eth0', '192.168.1.50',
                             ips=['192.168.1.77'] * 40)
        self.assertTrue([c for c in calls if c[:3] == ['nmcli', 'connection', 'modify']])

    def test_dhcp_accepts_any_lease(self):
        calls = self._run_bg('Wired connection 1', 'eth0', None, ips=['192.168.1.77'])
        self.assertEqual([c for c in calls if c[:3] == ['nmcli', 'connection', 'modify']], [])


def _clock():
    """monotonic() ticking a second per call, so the poll loop reaches its
    deadline without the test actually waiting."""
    t = [0.0]
    while True:
        t[0] += 1.0
        yield t[0]


class GetIpv4ConfigTests(unittest.TestCase):
    def test_dhcp_box_reports_the_live_lease(self):
        """On DHCP the form must pre-fill from the working lease, so "keep this
        address, make it permanent" needs no typing."""
        with patch.object(api_server, '_active_device', return_value=('eth0', 'ethernet')), \
             patch.object(api_server, '_active_connection_name', return_value='Wired connection 1'), \
             patch.object(api_server, '_nm_connection_ipv4', return_value={
                 'method': 'auto', 'address': None, 'prefix': None, 'gateway': None, 'dns': []}), \
             patch.object(api_server, '_device_ipv4_runtime', return_value={
                 'address': '192.168.0.133', 'prefix': 24,
                 'gateway': '192.168.0.1', 'dns': ['192.168.0.1']}):
            r = api_server.get_ipv4_config()
        self.assertEqual(r['mode'], 'auto')
        self.assertEqual(r['address'], '192.168.0.133')
        self.assertEqual(r['prefix'], 24)
        self.assertEqual(r['gateway'], '192.168.0.1')
        self.assertEqual(r['dns'], ['192.168.0.1'])
        self.assertEqual(r['type'], 'wired')

    def test_manual_box_reports_the_profile(self):
        with patch.object(api_server, '_active_device', return_value=('wlan0', 'wifi')), \
             patch.object(api_server, '_active_connection_name', return_value='Home'), \
             patch.object(api_server, '_nm_connection_ipv4', return_value={
                 'method': 'manual', 'address': '192.168.0.60', 'prefix': 24,
                 'gateway': '192.168.0.1', 'dns': ['1.1.1.1']}), \
             patch.object(api_server, '_device_ipv4_runtime', return_value={
                 'address': '192.168.0.60', 'prefix': 24,
                 'gateway': '192.168.0.1', 'dns': ['1.1.1.1']}):
            r = api_server.get_ipv4_config()
        self.assertEqual(r['mode'], 'manual')
        self.assertEqual(r['address'], '192.168.0.60')
        self.assertEqual(r['type'], 'wireless')

    def test_parses_nmcli_terse_output(self):
        out = ('ipv4.method:manual\n'
               'ipv4.addresses:192.168.0.60/24\n'
               'ipv4.gateway:192.168.0.1\n'
               'ipv4.dns:1.1.1.1,8.8.8.8\n')
        with patch.object(api_server, '_run', return_value=_ok([], stdout=out)):
            cfg = api_server._nm_connection_ipv4('Home')
        self.assertEqual(cfg, {'method': 'manual', 'address': '192.168.0.60', 'prefix': 24,
                               'gateway': '192.168.0.1', 'dns': ['1.1.1.1', '8.8.8.8']})

    def test_parses_device_runtime_output(self):
        out = ('IP4.ADDRESS[1]:192.168.0.133/24\n'
               'IP4.GATEWAY:192.168.0.1\n'
               'IP4.DNS[1]:192.168.0.1\n'
               'IP4.DNS[2]:1.1.1.1\n')
        with patch.object(api_server, '_run', return_value=_ok([], stdout=out)):
            cfg = api_server._device_ipv4_runtime('eth0')
        self.assertEqual(cfg, {'address': '192.168.0.133', 'prefix': 24,
                               'gateway': '192.168.0.1', 'dns': ['192.168.0.1', '1.1.1.1']})


class Ipv4RouteExposureTests(unittest.TestCase):
    def test_webui_proxies_both_methods(self):
        """Settings.vue reaches api_server only through webui_server's
        session-gated whitelist — an unlisted route is a 404 for the admin."""
        auth = _route_table('_AUTH_ROUTES')
        self.assertEqual(auth[('/api/system/ipv4_config', 'GET')], '/ipv4_config')
        self.assertEqual(auth[('/api/system/ipv4_config', 'POST')], '/ipv4_config')

    def test_not_reachable_before_login(self):
        """Re-addressing the box is an admin action: it must not be in the
        unauthenticated provisioning whitelist."""
        for key in _route_table('_PROVISION_ROUTES'):
            self.assertNotIn('ipv4_config', str(key))

    def test_api_server_exposes_both_methods(self):
        self.assertEqual(
            {m for rule in api_server.app.url_map.iter_rules() if str(rule) == '/ipv4_config'
             for m in rule.methods} & {'GET', 'POST'},
            {'GET', 'POST'})


if __name__ == '__main__':
    unittest.main()
