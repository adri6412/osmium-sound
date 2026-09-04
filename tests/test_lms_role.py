"""Tests for the Lyrion server role in api_server.py: which host squeezelite
is pointed at, and — the part owners actually notice — that the device's own
Lyrion is stopped and disabled while it follows an external server, so a later
boot cannot come up on the local one.

Run with:  python tests/test_lms_role.py
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import api_server  # noqa: E402


DEFAULT_ARGS = "ARGS='-o default -D -v -C 5 -s 127.0.0.1 -n OsmiumSound -M Osmium'\n"


class LmsRoleTestCase(unittest.TestCase):
    """Redirects /etc/default/squeezelite into a temp file and records every
    systemctl call instead of running it, like the other suites here."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='hifi-lms-role-test-')
        self.sq = os.path.join(self.tmp, 'squeezelite')
        with open(self.sq, 'w') as f:
            f.write(DEFAULT_ARGS)
        self._saved = {}
        self._patch('SQUEEZELITE_DEFAULT', self.sq)
        self.calls = []
        self._patch('_run', self._fake_run)
        # The player-enabled check reads a file of its own; keep the restart
        # path alive so the role change is exercised end to end.
        self._patch('PLAYER_ENABLED_FILE', os.path.join(self.tmp, 'player-enabled'))

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(api_server, name, value)

    def _patch(self, name, value):
        self._saved[name] = getattr(api_server, name)
        setattr(api_server, name, value)

    def _fake_run(self, cmd, timeout=20):
        self.calls.append(list(cmd))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout='', stderr='')

    def _args(self):
        with open(self.sq) as f:
            return f.read()

    def _systemctl(self, unit):
        return [c for c in self.calls
                if c and c[0] == 'systemctl' and c[-1] == unit]

    # ── follow: point at the other server, switch our own off ────────

    def test_follow_points_squeezelite_at_the_other_server(self):
        result = api_server.set_lms_role('follow', '192.168.1.50')
        self.assertTrue(result['success'])
        self.assertEqual(result['host'], '192.168.1.50')
        self.assertIn('-s 192.168.1.50', self._args())

    def test_follow_stops_and_disables_the_local_lyrion(self):
        api_server.set_lms_role('follow', '192.168.1.50')
        self.assertEqual(self._systemctl(api_server.LYRION_UNIT),
                         [['systemctl', 'disable', '--now', api_server.LYRION_UNIT]])

    def test_local_lyrion_is_stopped_before_squeezelite_restarts(self):
        # Otherwise the player can reconnect while the local server is still
        # answering on loopback.
        api_server.set_lms_role('follow', '192.168.1.50')
        names = [' '.join(c) for c in self.calls]
        self.assertLess(names.index('systemctl disable --now ' + api_server.LYRION_UNIT),
                        names.index('systemctl restart squeezelite'))

    # ── local: our own server comes back ─────────────────────────────

    def test_local_restores_loopback_and_starts_the_local_lyrion(self):
        api_server.set_lms_role('follow', '192.168.1.50')
        self.calls = []
        result = api_server.set_lms_role('local', None)
        self.assertTrue(result['success'])
        self.assertIsNone(result['host'])
        self.assertIn('-s 127.0.0.1', self._args())
        self.assertEqual(self._systemctl(api_server.LYRION_UNIT),
                         [['systemctl', 'enable', '--now', api_server.LYRION_UNIT]])

    def test_role_survives_a_reread(self):
        api_server.set_lms_role('follow', '192.168.1.50')
        self.assertEqual(api_server.get_lms_role(),
                         {'mode': 'follow', 'host': '192.168.1.50'})
        api_server.set_lms_role('local', None)
        self.assertEqual(api_server.get_lms_role(), {'mode': 'local', 'host': None})

    # ── refusals leave both the args and the service alone ───────────

    def test_invalid_host_touches_nothing(self):
        result = api_server.set_lms_role('follow', 'not-an-ip')
        self.assertFalse(result['success'])
        self.assertEqual(self.calls, [])
        self.assertEqual(self._args(), DEFAULT_ARGS)

    def test_follow_on_loopback_refused(self):
        result = api_server.set_lms_role('follow', '127.0.0.1')
        self.assertFalse(result['success'])
        self.assertEqual(self.calls, [])

    def test_invalid_mode_refused(self):
        result = api_server.set_lms_role('bogus', None)
        self.assertFalse(result['success'])
        self.assertEqual(self.calls, [])

    # ── a boot without the data partition cannot keep the choice ─────

    def test_volatile_boot_is_reported_in_the_message(self):
        self._patch('_data_partition_mounted', lambda: False)
        result = api_server.set_lms_role('follow', '192.168.1.50')
        self.assertTrue(result['success'])
        self.assertIn('192.168.1.50', result['message'])
        # the warning is appended to the normal outcome, not instead of it
        self.assertGreater(len(result['message'].split(' — ')), 1)

    def test_normal_boot_message_carries_no_warning(self):
        self._patch('_data_partition_mounted', lambda: True)
        result = api_server.set_lms_role('local', None)
        self.assertNotIn(' — ', result['message'])

    # ── a unit that cannot be acted on is not a failed role change ───

    def test_systemctl_failure_does_not_fail_the_role_change(self):
        def failing(cmd, timeout=20):
            self.calls.append(list(cmd))
            rc = 1 if cmd[-1] == api_server.LYRION_UNIT else 0
            return subprocess.CompletedProcess(args=cmd, returncode=rc,
                                               stdout='', stderr='Unit not found.')
        self._patch('_run', failing)
        result = api_server.set_lms_role('follow', '192.168.1.50')
        self.assertTrue(result['success'])
        self.assertIn('-s 192.168.1.50', self._args())


if __name__ == '__main__':
    unittest.main(verbosity=2)
