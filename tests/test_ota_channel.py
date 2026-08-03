"""Tests for the OTA release-channel logic in api_server.py: the prod/dev/alpha
selection, the alpha marker-file gate, and the dev/alpha filtering in
_fetch_github_api_release (the invariant that an alpha-tagged release must
never reach a device on the dev channel).

Run with:  python tests/test_ota_channel.py
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import api_server  # noqa: E402


class _FakeResponse:
    """Minimal stand-in for the object urllib.request.urlopen() returns,
    enough for `with urlopen(...) as resp: json.load(resp)`."""

    def __init__(self, payload):
        self._body = json.dumps(payload).encode('utf-8')

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def _release(tag, prerelease=False, draft=False):
    return {'tag_name': tag, 'name': tag, 'prerelease': prerelease, 'draft': draft,
            'assets': []}


class OtaChannelTestCase(unittest.TestCase):
    """Redirects the channel + marker files into a temp dir, like the other
    suites in this directory redirect every path the code under test touches."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='hifi-ota-channel-test-')
        self._saved = {}
        self._patch('OTA_CHANNEL_FILE', os.path.join(self.tmp, 'ota-channel'))
        self._patch('OTA_ALPHA_MARKER_FILE', os.path.join(self.tmp, 'ota-alpha-unlocked'))
        os.environ.pop('HIFI_OTA_CHANNEL', None)

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(api_server, name, value)
        os.environ.pop('HIFI_OTA_CHANNEL', None)

    def _patch(self, name, value):
        self._saved[name] = getattr(api_server, name)
        setattr(api_server, name, value)

    def _unlock_alpha(self):
        with open(api_server.OTA_ALPHA_MARKER_FILE, 'w'):
            pass

    # ── get/set channel ──────────────────────────────────────────────

    def test_default_channel_is_prod(self):
        self.assertEqual(api_server.get_ota_channel(), 'prod')

    def test_set_and_get_dev(self):
        self.assertTrue(api_server.set_ota_channel('dev')['success'])
        self.assertEqual(api_server.get_ota_channel(), 'dev')

    def test_set_alpha_refused_when_locked(self):
        result = api_server.set_ota_channel('alpha')
        self.assertFalse(result['success'])
        self.assertEqual(api_server.get_ota_channel(), 'prod')

    def test_set_alpha_succeeds_when_unlocked(self):
        self._unlock_alpha()
        self.assertTrue(api_server.set_ota_channel('alpha')['success'])
        self.assertEqual(api_server.get_ota_channel(), 'alpha')

    def test_get_falls_back_to_prod_if_marker_removed_after_selection(self):
        self._unlock_alpha()
        api_server.set_ota_channel('alpha')
        os.remove(api_server.OTA_ALPHA_MARKER_FILE)
        self.assertEqual(api_server.get_ota_channel(), 'prod')

    def test_invalid_channel_refused(self):
        result = api_server.set_ota_channel('bogus')
        self.assertFalse(result['success'])

    def test_env_var_alpha_ignored_when_locked(self):
        os.environ['HIFI_OTA_CHANNEL'] = 'alpha'
        self.assertEqual(api_server.get_ota_channel(), 'prod')

    def test_env_var_alpha_honoured_when_unlocked(self):
        self._unlock_alpha()
        os.environ['HIFI_OTA_CHANNEL'] = 'alpha'
        self.assertEqual(api_server.get_ota_channel(), 'alpha')

    # ── /ota_channel channel list ────────────────────────────────────

    def test_channels_list_excludes_alpha_when_locked(self):
        self.assertEqual(
            [c for c in api_server.OTA_CHANNELS if c != 'alpha' or api_server._alpha_unlocked()],
            ['prod', 'dev'])

    def test_channels_list_includes_alpha_when_unlocked(self):
        self._unlock_alpha()
        self.assertEqual(
            [c for c in api_server.OTA_CHANNELS if c != 'alpha' or api_server._alpha_unlocked()],
            ['prod', 'dev', 'alpha'])

    # ── _fetch_github_api_release: the "alpha never leaks into dev" invariant ──

    def _fake_releases(self, releases):
        api_server.urllib.request.urlopen = lambda *a, **k: _FakeResponse(releases)

    def test_dev_excludes_alpha_tagged_releases(self):
        saved = api_server.urllib.request.urlopen
        try:
            self._fake_releases([
                _release('v2.5.21-dev.50-alpha2', prerelease=True),
                _release('v2.5.21-dev.50-alpha1', prerelease=True),
                _release('v2.5.21-dev.50', prerelease=True),
                _release('v2.5.20', prerelease=False),
            ])
            result = api_server._fetch_github_api_release('dev')
            self.assertEqual(result['tag_name'], 'v2.5.21-dev.50')
        finally:
            api_server.urllib.request.urlopen = saved

    def test_alpha_returns_newest_of_any_kind(self):
        saved = api_server.urllib.request.urlopen
        try:
            self._fake_releases([
                _release('v2.5.21-dev.50-alpha2', prerelease=True),
                _release('v2.5.21-dev.50', prerelease=True),
                _release('v2.5.20', prerelease=False),
            ])
            result = api_server._fetch_github_api_release('alpha')
            self.assertEqual(result['tag_name'], 'v2.5.21-dev.50-alpha2')
        finally:
            api_server.urllib.request.urlopen = saved

    def test_prod_only_returns_stable(self):
        saved = api_server.urllib.request.urlopen
        try:
            self._fake_releases([
                _release('v2.5.21-dev.50-alpha1', prerelease=True),
                _release('v2.5.21-dev.50', prerelease=True),
                _release('v2.5.20', prerelease=False),
            ])
            result = api_server._fetch_github_api_release('prod')
            self.assertEqual(result['tag_name'], 'v2.5.20')
        finally:
            api_server.urllib.request.urlopen = saved

    def test_alpha_semver_key_ranks_between_its_base_dev_and_the_next_one(self):
        base = api_server._semver_key('2.5.21-dev.50')
        alpha1 = api_server._semver_key('2.5.21-dev.50-alpha1')
        alpha2 = api_server._semver_key('2.5.21-dev.50-alpha2')
        next_dev = api_server._semver_key('2.5.21-dev.51')
        self.assertLess(base, alpha1)
        self.assertLess(alpha1, alpha2)
        self.assertLess(alpha2, next_dev)


if __name__ == '__main__':
    unittest.main(verbosity=2)
