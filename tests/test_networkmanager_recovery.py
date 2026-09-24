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
