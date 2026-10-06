import subprocess
import unittest
from unittest.mock import patch

import api_server
import webui_server


class NetworkManagerRecoveryTests(unittest.TestCase):
    def test_api_server_reenables_nm_for_device(self):
        calls = []

        def fake_run(cmd, timeout=20):
            calls.append((cmd, timeout))
            return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')

        with patch.object(api_server, '_run', side_effect=fake_run):
            api_server._ensure_networkmanager_state('ens37')

        self.assertEqual(calls[0][0], ['nmcli', 'networking', 'on'])
        self.assertEqual(calls[1][0], ['nmcli', 'device', 'set', 'ens37', 'managed', 'yes'])

    def test_webui_reenables_nm_for_device(self):
        calls = []

        def fake_nmcli(args, timeout=60):
            calls.append((args, timeout))
            return 0, '', ''

        with patch.object(webui_server, '_nmcli', side_effect=fake_nmcli):
            webui_server._ensure_networkmanager_state('ens37')

        self.assertIn(['networking', 'on'], [c[0] for c in calls])
        self.assertIn(['device', 'set', 'ens37', 'managed', 'yes'], [c[0] for c in calls])


class RecoveryHotspotTests(unittest.TestCase):
    """The recovery hotspot takes a Wi-Fi-only unit off the home network, so
    it must go up only on a network that is certainly gone — not on a box so
    short of memory that nmcli could not answer (2026-09-24)."""

    def setUp(self):
        webui_server._net_down_ticks = 0
        webui_server._net_recovery['active'] = False
        self.raised = []
        patches = [
            patch.object(webui_server, 'FAKE', False),
            patch.object(webui_server, '_provisioning', return_value=False),
            patch.object(webui_server, '_wired_self_heal', return_value=None),
            patch.object(webui_server, '_monitor_start', -10_000),
            patch.object(webui_server, '_raise_net_recovery_ap',
                         side_effect=lambda: self.raised.append(1) or True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _tick_with(self, nmcli_answer):
        with patch.object(webui_server, '_nmcli', return_value=nmcli_answer):
            webui_server._network_monitor_tick()

    def test_nmcli_failing_never_raises_the_hotspot(self):
        for _ in range(10):
            self._tick_with((1, '', 'timed out'))
        self.assertEqual(self.raised, [])

    def test_one_down_reading_is_not_enough(self):
        down = (0, 'wlp0s12f0:wifi:disconnected:--\n', '')
        up = (0, 'wlp0s12f0:wifi:connected:Home\n', '')
        for answer in (down, down, up, down, down):
            self._tick_with(answer)
        self.assertEqual(self.raised, [])

    def test_three_down_readings_in_a_row_raise_it(self):
        down = (0, 'wlp0s12f0:wifi:disconnected:--\n', '')
        for _ in range(3):
            self._tick_with(down)
        self.assertEqual(self.raised, [1])

    def test_a_timeout_in_between_does_not_reset_nor_count(self):
        down = (0, 'wlp0s12f0:wifi:disconnected:--\n', '')
        for answer in (down, (1, '', 'timed out'), down):
            self._tick_with(answer)
        self.assertEqual(self.raised, [])
        self._tick_with(down)
        self.assertEqual(self.raised, [1])


class RecoveryHotspotRetryTests(unittest.TestCase):
    """On a Wi-Fi-only box the recovery AP occupies the one radio, so the home
    network coming back can never be seen while it is up: after a router
    reboot of more than a minute the box stayed off the network for good. The
    AP now steps aside every few minutes -- only while nobody is on it -- and
    stays down if a saved network comes back."""

    DOWN = (0, 'wlp0s12f0:wifi:connected:hifi-setup\n', '')

    def setUp(self):
        webui_server._net_down_ticks = 0
        webui_server._net_recovery.update({'active': True, 'ssid': 'Osmium-Setup-ABCD',
                                           'tried_at': 0, 'connecting': False})
        self.addCleanup(webui_server._net_recovery.update,
                        {'active': False, 'ssid': None, 'tried_at': None, 'connecting': False})
        self.raised, self.retries = [], []
        self.clients = 0
        self.back = False
        patches = [
            patch.object(webui_server, 'FAKE', False),
            patch.object(webui_server, '_provisioning', return_value=False),
            patch.object(webui_server, '_wired_self_heal', return_value=None),
            patch.object(webui_server, '_monitor_start', -10_000),
            patch.object(webui_server, '_wifi_device', return_value='wlp0s12f0'),
            patch.object(webui_server, '_nmcli', return_value=self.DOWN),
            patch.object(webui_server, '_ap_clients', side_effect=lambda dev: self.clients),
            patch.object(webui_server, '_retry_saved_wifi',
                         side_effect=lambda: self.retries.append(1) or self.back),
            patch.object(webui_server, '_raise_net_recovery_ap',
                         side_effect=lambda: self.raised.append(1) or True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_an_unused_hotspot_steps_aside_and_stays_down_when_home_is_back(self):
        self.back = True
        webui_server._network_monitor_tick()
        self.assertEqual(self.retries, [1])
        self.assertFalse(webui_server._net_recovery['active'])
        self.assertEqual(self.raised, [])

    def test_no_home_network_brings_the_hotspot_back(self):
        webui_server._network_monitor_tick()
        self.assertEqual(self.retries, [1])
        self.assertEqual(self.raised, [1])

    def test_never_with_somebody_on_the_hotspot(self):
        self.clients = 1
        webui_server._network_monitor_tick()
        self.assertEqual(self.retries, [])

    def test_never_while_their_join_is_in_flight(self):
        webui_server._net_recovery['connecting'] = True
        webui_server._network_monitor_tick()
        self.assertEqual(self.retries, [])

    def test_never_when_the_stations_cannot_be_counted(self):
        self.clients = None
        webui_server._network_monitor_tick()
        self.assertEqual(self.retries, [])

    def test_not_more_often_than_every_few_minutes(self):
        now = webui_server.time.monotonic()
        self.assertFalse(webui_server._recovery_retry_due(now, now - 30, 0, False))
        self.assertTrue(webui_server._recovery_retry_due(
            now, now - webui_server._NET_RETRY_EVERY, 0, False))



class ApClientsTests(unittest.TestCase):
    def _count(self, rc, out):
        with patch.object(webui_server, 'FAKE', False), \
                patch.object(webui_server.subprocess, 'run',
                             return_value=subprocess.CompletedProcess([], rc, stdout=out, stderr='')):
            return webui_server._ap_clients('wlp0s12f0')

    def test_counts_stations(self):
        dump = ('Station 11:22:33:44:55:66 (on wlp0s12f0)\n\tinactive time:\t10 ms\n'
                'Station aa:bb:cc:dd:ee:ff (on wlp0s12f0)\n\tinactive time:\t20 ms\n')
        self.assertEqual(self._count(0, dump), 2)
        self.assertEqual(self._count(0, ''), 0)

    def test_unknown_when_iw_fails(self):
        self.assertIsNone(self._count(1, ''))


class DnsmasqCheckTests(unittest.TestCase):
    def test_read_only_root_never_runs_apt(self):
        with patch.object(webui_server, 'FAKE', False), \
                patch.object(webui_server, '_dnsmasq_present', return_value=False), \
                patch.object(webui_server, '_root_is_writable', return_value=False), \
                patch.object(webui_server, '_dnsmasq_attempted', False), \
                patch.object(webui_server.subprocess, 'run') as run:
            self.assertFalse(webui_server._ensure_dnsmasq())
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
