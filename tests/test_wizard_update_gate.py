"""Tests for the setup wizard's mandatory update gate in api_server.py
(wizard_update_check / wizard_update_apply): prod channel only -- a dev-only
release must never block setup on a stable install --, the live-session skip
(a boot=live session runs from the read-only squashfs and can't install
anything), and the "couldn't check" vs "checked, nothing to update"
distinction the wizard's retry loop keys off.

Run with:  python tests/test_wizard_update_gate.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import api_server  # noqa: E402


class WizardUpdateGateTestCase(unittest.TestCase):
    """Redirects every path/collaborator the gate touches, like the other
    suites here: channel files into a temp dir, the release check and the
    update runner into recording fakes, /proc/cmdline into a temp file."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='hifi-wizard-gate-test-')
        self._saved = {}
        self._patch('OTA_CHANNEL_FILE', os.path.join(self.tmp, 'ota-channel'))
        self._patch('OTA_ALPHA_MARKER_FILE', os.path.join(self.tmp, 'ota-alpha-unlocked'))
        self._patch('PROC_CMDLINE', os.path.join(self.tmp, 'cmdline'))
        self._patch('_lang', lambda: 'en')  # no Flask request context here
        self.checked = []   # channels the release check was asked about
        self.applied = 0    # how many times the real update runner would have started
        self._patch('apply_all_updates', self._fake_apply)
        self._cmdline('BOOT_IMAGE=/vmlinuz root=UUID=abc ro quiet splash')
        os.environ.pop('HIFI_OTA_CHANNEL', None)

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(api_server, name, value)
        os.environ.pop('HIFI_OTA_CHANNEL', None)

    def _patch(self, name, value):
        self._saved[name] = getattr(api_server, name)
        setattr(api_server, name, value)

    def _cmdline(self, text):
        with open(api_server.PROC_CMDLINE, 'w') as f:
            f.write(text + '\n')

    def _fake_apply(self):
        self.applied += 1
        return {'started': True, 'version': 'x'}

    def _releases(self, table):
        """table: {channel: True (update available) | False (up to date)
        | 'error' (check failed outright)}. Channels not listed count as
        up to date. Records every channel asked about in self.checked."""
        def fake(current, prefix, channel=None):
            self.checked.append(channel)
            entry = table.get(channel, False)
            if entry == 'error':
                return {'current': current, 'error': 'boom'}
            return {'current': current, 'latest': 'x', 'channel': channel,
                    'update_available': bool(entry)}
        self._patch('_check_release_update', fake)

    # ── _is_live_boot ────────────────────────────────────────────────

    def test_live_boot_detected_from_kernel_cmdline_token(self):
        self._cmdline('boot=live components quiet splash hostname=hifiplayer')
        self.assertTrue(api_server._is_live_boot())

    def test_installed_system_is_not_live(self):
        self.assertFalse(api_server._is_live_boot())

    def test_live_token_must_match_whole_word(self):
        self._cmdline('reboot=liveish quiet')
        self.assertFalse(api_server._is_live_boot())

    def test_unreadable_cmdline_means_not_live(self):
        os.remove(api_server.PROC_CMDLINE)
        self.assertFalse(api_server._is_live_boot())

    # ── wizard_update_check ──────────────────────────────────────────

    def test_prod_update_is_mandatory_and_automatic(self):
        self._releases({'prod': True})
        self.assertEqual(api_server.wizard_update_check(),
                         {'available': True, 'channel': 'prod', 'auto': True})

    def test_up_to_date_lets_setup_continue(self):
        self._releases({'prod': False})
        self.assertEqual(api_server.wizard_update_check(), {'available': False})

    def test_dev_only_release_does_not_block_setup(self):
        # The stable ISO is on the current prod release while a newer -dev.N
        # exists: that must not be "required to continue setup".
        self._releases({'prod': False, 'dev': True, 'alpha': True})
        self.assertEqual(api_server.wizard_update_check(), {'available': False})
        self.assertNotIn('dev', self.checked)
        self.assertNotIn('alpha', self.checked)

    def test_failed_check_is_reported_distinctly(self):
        self._releases({'prod': 'error'})
        self.assertEqual(api_server.wizard_update_check(),
                         {'available': False, 'checkFailed': True})

    def test_live_session_skips_the_gate_without_touching_the_network(self):
        self._cmdline('boot=live components quiet splash')
        self._releases({'prod': True})
        self.assertEqual(api_server.wizard_update_check(),
                         {'available': False, 'live': True})
        self.assertEqual(self.checked, [])

    # ── wizard_update_apply ──────────────────────────────────────────

    def test_apply_prod_starts_the_update_on_the_prod_channel(self):
        result = api_server.wizard_update_apply('prod')
        self.assertTrue(result['started'])
        self.assertEqual(self.applied, 1)
        self.assertEqual(api_server.get_ota_channel(), 'prod')

    def test_apply_refuses_any_other_channel(self):
        for channel in ('dev', 'alpha', None, 'bogus'):
            result = api_server.wizard_update_apply(channel)
            self.assertFalse(result['started'], channel)
        self.assertEqual(self.applied, 0)
        self.assertEqual(api_server.get_ota_channel(), 'prod')

    def test_apply_refused_on_a_live_session(self):
        self._cmdline('boot=live components quiet splash')
        result = api_server.wizard_update_apply('prod')
        self.assertFalse(result['started'])
        self.assertEqual(result['code'], 'update.liveSession')
        self.assertTrue(result['message'])
        self.assertEqual(self.applied, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
