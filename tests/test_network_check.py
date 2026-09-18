"""Tests for the network check in api_server.py (Settings → Network check).

The probes themselves talk to the network and to NetworkManager; these tests
replace them and cover what the UIs rely on: the order of the steps, which
step the verdict points at, when a failed hop is let off because a later one
worked, how the clock is judged, and how errors are named.

Run with:  python tests/test_network_check.py
"""
import os
import socket
import ssl
import sys
import time
import unittest
import urllib.error
from email.utils import formatdate

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import api_server  # noqa: E402


class NetworkCheckTest(unittest.TestCase):
    def setUp(self):
        self._saved = {}
        self.probes = {
            'link': {'status': 'ok', 'detail': 'eth0 · 192.168.1.5'},
            'router': {'status': 'ok', 'gateway': '192.168.1.1'},
            'internet': {'status': 'ok'},
            'dns': {'status': 'ok'},
            'ntp': True,
            'ota': ({'status': 'ok', 'sources': []}, {'tag_name': 'v1', 'assets': []},
                    [formatdate(time.time(), usegmt=True)]),
            'download': {'status': 'ok'},
        }
        p = self.probes
        self._patch('get_ota_channel', lambda: 'prod')
        self._patch('_netcheck_link', lambda: dict(p['link']))
        self._patch('_netcheck_router', lambda: dict(p['router']))
        self._patch('_netcheck_internet', lambda: dict(p['internet']))
        self._patch('_netcheck_dns', lambda: dict(p['dns']))
        self._patch('_netcheck_ntp', lambda: p['ntp'])
        self._patch('_netcheck_ota', lambda ch: (dict(p['ota'][0]),) + p['ota'][1:])
        self._patch('_netcheck_download', lambda m: dict(p['download']))

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(api_server, k, v)

    def _patch(self, name, value):
        self._saved.setdefault(name, getattr(api_server, name))
        setattr(api_server, name, value)

    def steps(self, res):
        return {s['id']: s for s in res['steps']}

    def test_all_good(self):
        res = api_server.network_check()
        self.assertEqual([s['id'] for s in res['steps']], list(api_server.NETCHECK_STEPS))
        self.assertEqual(res['verdict'], 'ok')
        self.assertIsNone(res['warn'])

    def test_no_link_skips_the_rest(self):
        self.probes['link'] = {'status': 'fail', 'error': 'noLink'}
        res = api_server.network_check()
        self.assertEqual(res['verdict'], 'link')
        self.assertTrue(all(s['status'] == 'skip' for s in res['steps'][1:]))

    def test_verdict_is_first_failing_hop(self):
        self.probes['dns'] = {'status': 'fail', 'error': 'dns'}
        self.probes['ota'] = ({'status': 'fail', 'error': 'otaDown'}, None, [])
        self.probes['download'] = {'status': 'skip'}
        self.assertEqual(api_server.network_check()['verdict'], 'dns')

    def test_router_ignoring_ping_is_not_the_fault(self):
        self.probes['router'] = {'status': 'fail', 'error': 'noAnswer', 'gateway': '192.168.1.1'}
        res = api_server.network_check()
        self.assertEqual(self.steps(res)['router']['status'], 'ok')
        self.assertEqual(self.steps(res)['router']['error'], 'noPing')
        self.assertEqual(res['verdict'], 'ok')

    def test_no_gateway_stays_a_failure(self):
        self.probes['router'] = {'status': 'fail', 'error': 'noGateway'}
        self.assertEqual(api_server.network_check()['verdict'], 'router')

    def test_blocked_raw_ips_with_working_update_server_is_a_warning(self):
        self.probes['internet'] = {'status': 'fail', 'error': 'timeout'}
        res = api_server.network_check()
        self.assertEqual(self.steps(res)['internet']['status'], 'warn')
        self.assertEqual(self.steps(res)['internet']['error'], 'blockedIps')
        self.assertEqual((res['verdict'], res['warn']), ('ok', 'internet'))

    def test_internet_down_is_the_verdict(self):
        self.probes['internet'] = {'status': 'fail', 'error': 'timeout'}
        self.probes['dns'] = {'status': 'fail', 'error': 'dns'}
        self.probes['ota'] = ({'status': 'fail', 'error': 'otaDown'}, None, [])
        self.assertEqual(api_server.network_check()['verdict'], 'internet')

    def test_clock_judged_by_measured_offset_not_ntp_flag(self):
        # no NTP client on the image, but the clock agrees with the servers
        self.probes['ntp'] = False
        res = api_server.network_check()
        self.assertEqual(self.steps(res)['clock']['status'], 'ok')
        self.assertEqual(res['verdict'], 'ok')

    def test_clock_offsets(self):
        now = time.time()
        warn = api_server._netcheck_clock(True, [formatdate(now + 600, usegmt=True)])
        self.assertEqual((warn['status'], warn['error']), ('warn', 'clockOff'))
        self.assertLess(warn['skew'], -500)
        fail = api_server._netcheck_clock(True, [formatdate(now - 2 * 86400, usegmt=True)])
        self.assertEqual(fail['status'], 'fail')
        ok = api_server._netcheck_clock(None, [formatdate(now, usegmt=True)])
        self.assertEqual(ok['status'], 'ok')

    def test_error_names(self):
        E = api_server._netcheck_error
        self.assertEqual(E(urllib.error.URLError(socket.gaierror(-2, 'x'))), ('dns', None))
        self.assertEqual(E(urllib.error.URLError(TimeoutError('timed out'))), ('timeout', None))
        self.assertEqual(E(urllib.error.URLError(ConnectionRefusedError())), ('refused', None))
        self.assertEqual(E(urllib.error.URLError(ssl.SSLCertVerificationError('bad'))), ('tlsCert', None))
        self.assertEqual(E(urllib.error.HTTPError('u', 403, 'Forbidden', {}, None)), ('http', 403))
        self.assertEqual(E(OSError(101, 'Network is unreachable')), ('unreachable', None))

    def test_parallel_reports_a_stuck_probe_as_timed_out(self):
        res = api_server._netcheck_parallel({'fast': lambda: 1, 'stuck': lambda: time.sleep(5)}, 0.3)
        self.assertEqual(res['fast'], 1)
        self.assertIsInstance(res['stuck'], TimeoutError)


if __name__ == '__main__':
    unittest.main()
