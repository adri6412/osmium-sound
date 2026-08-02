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


if __name__ == '__main__':
    unittest.main()
