"""Tests for the connectivity state in api_server.py (the kiosk's top-bar
icon: internet / local network only / offline).

The probes talk to NetworkManager and to the network; these tests replace
them and cover the state machine and the cache the UI relies on.

Run with:  python tests/test_connectivity.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import api_server  # noqa: E402


class ConnectivityTest(unittest.TestCase):
    def setUp(self):
        self._saved = {}
        self.link = {'device': 'eth0', 'type': 'ethernet', 'ip': '192.168.1.5', 'ssid': None}
        self.gateway = '192.168.1.1'
        self.router_ok = True
        self.internet_ok = True
        self.router_calls = []
        self._patch('_active_device', lambda: (self.link['device'], self.link['type']))
        self._patch('_device_ip', lambda dev: self.link['ip'] if dev else None)
        self._patch('_active_ssid', lambda: self.link['ssid'])
        self._patch('_default_gateway', lambda: self.gateway)
        self._patch('_conn_router_ok', self._router)
        self._patch('_conn_internet_ok', lambda: self.internet_ok)
        api_server._connectivity_cache['result'] = None
        api_server._connectivity_cache['at'] = 0.0

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(api_server, k, v)
        api_server._connectivity_cache['result'] = None

    def _patch(self, name, value):
        self._saved.setdefault(name, getattr(api_server, name))
        setattr(api_server, name, value)

    def _router(self, gw):
        self.router_calls.append(gw)
        return self.router_ok

    def test_internet(self):
        res = api_server.get_connectivity()
        self.assertEqual(res['state'], 'internet')
        self.assertEqual(res['type'], 'wired')
        self.assertEqual(res['ip'], '192.168.1.5')
        self.assertEqual(res['gateway'], '192.168.1.1')
        self.assertTrue(res['router'])
        self.assertIn('at', res)

    def test_lan_only(self):
        self.internet_ok = False
        res = api_server.get_connectivity()
        self.assertEqual(res['state'], 'lan')
        self.assertTrue(res['router'])

    def test_internet_proves_router(self):
        # a router that ignores ping and is not in ARP, but the outside answers
        self.router_ok = False
        res = api_server.get_connectivity()
        self.assertEqual(res['state'], 'internet')
        self.assertTrue(res['router'])

    def test_address_but_dead_router(self):
        self.router_ok = False
        self.internet_ok = False
        res = api_server.get_connectivity()
        self.assertEqual(res['state'], 'offline')
        self.assertEqual(res['ip'], '192.168.1.5')
        self.assertFalse(res['router'])

    def test_no_gateway(self):
        self.gateway = None
        self.internet_ok = False
        res = api_server.get_connectivity()
        self.assertEqual(res['state'], 'offline')
        self.assertEqual(self.router_calls, [])

    def test_no_link(self):
        self.link = {'device': None, 'type': None, 'ip': None, 'ssid': None}
        res = api_server.get_connectivity()
        self.assertEqual(res['state'], 'offline')
        self.assertEqual(res['type'], 'none')
        self.assertIsNone(res['ip'])
        self.assertEqual(self.router_calls, [])

    def test_wireless_reports_ssid(self):
        self.link = {'device': 'wlan0', 'type': 'wifi', 'ip': '192.168.1.9', 'ssid': 'CasaWiFi'}
        res = api_server.get_connectivity()
        self.assertEqual(res['type'], 'wireless')
        self.assertEqual(res['ssid'], 'CasaWiFi')

    def test_cached_within_ttl(self):
        api_server.get_connectivity()
        self.internet_ok = False
        self.assertEqual(api_server.get_connectivity()['state'], 'internet')
        self.assertEqual(api_server.get_connectivity(force=True)['state'], 'lan')

    def test_cache_expires(self):
        api_server.get_connectivity()
        api_server._connectivity_cache['at'] -= api_server.CONNECTIVITY_TTL + 1
        self.internet_ok = False
        self.assertEqual(api_server.get_connectivity()['state'], 'lan')

    def test_probe_failure_is_offline(self):
        def boom():
            raise RuntimeError('nmcli missing')
        self._patch('_active_device', boom)
        res = api_server.get_connectivity()
        self.assertEqual(res['state'], 'offline')
        self.assertEqual(res['type'], 'none')

    def test_result_is_a_copy(self):
        res = api_server.get_connectivity()
        res['state'] = 'tampered'
        self.assertEqual(api_server.get_connectivity()['state'], 'internet')


if __name__ == '__main__':
    unittest.main()
