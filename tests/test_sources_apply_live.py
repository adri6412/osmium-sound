"""Tests for the live apply the first-run wizard ends its sources step with.

The restart-based /api/apply held the wizard's "Done, continue" button for up
to two minutes (stop Lyrion, start it, wait for a rescan). {"live": true} must
answer from JSON-RPC alone, touch Lyrion only when its folder list is wrong,
and fall back to the restart in the background when Lyrion does not answer.

Run with:  python tests/test_sources_apply_live.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import sources_server as ss  # noqa: E402


class FakeLyrion:
    def __init__(self, mediadirs, reachable=True):
        self.mediadirs = list(mediadirs)
        self.reachable = reachable
        self.calls = []

    def request(self, params, timeout=10):
        if not self.reachable:
            raise OSError('connection refused')
        self.calls.append(list(params))
        if params[:3] == ['pref', 'mediadirs', '?']:
            return {'_p2': list(self.mediadirs)}
        if params[:2] == ['pref', 'mediadirs']:
            self.mediadirs = list(params[2])
        return {}


class ApplyLiveTests(unittest.TestCase):
    def setUp(self):
        self._saved = {}
        self.state = {'sources': [{'id': 'a', 'type': 'smb', 'subpath_pending': True}]}
        self.paths = ['/mnt/hifi-smb/nas/Music']
        self._patch('load_state', lambda: self.state)
        self._patch('save_state', lambda st: None)
        self._patch('current_paths', lambda st: list(self.paths))
        self._patch('_sync_from_lyrion', lambda st: False)
        self.restarts = []
        self._patch('apply_to_lyrion', lambda st: (self.restarts.append(1), (True, 'ok'))[1])
        self.client = ss.app.test_client()

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(ss, name, value)

    def _patch(self, name, value):
        self._saved[name] = getattr(ss, name)
        setattr(ss, name, value)

    def _lyrion(self, **kw):
        fake = FakeLyrion(**kw)
        self._patch('_lyrion_request', fake.request)
        return fake

    def _apply(self):
        return self.client.post('/api/apply', json={'live': True})

    def test_nothing_to_do_when_lyrion_already_has_the_folders(self):
        fake = self._lyrion(mediadirs=self.paths)
        r = self._apply()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()['success'])
        self.assertEqual([c for c in fake.calls if c != ['pref', 'mediadirs', '?']], [])
        self.assertEqual(self.restarts, [])

    def test_missing_folder_is_set_live_and_rescanned(self):
        fake = self._lyrion(mediadirs=[])
        r = self._apply()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(fake.mediadirs, self.paths)
        self.assertIn(['rescan'], fake.calls)
        self.assertEqual(self.restarts, [])

    def test_pending_flags_are_cleared(self):
        self._lyrion(mediadirs=self.paths)
        self._apply()
        self.assertNotIn('subpath_pending', self.state['sources'][0])

    def test_unreachable_lyrion_falls_back_to_a_background_restart(self):
        self._lyrion(mediadirs=[], reachable=False)
        started = []

        class NoThread:
            def __init__(self, target, daemon):
                self.target = target

            def start(self):
                started.append(self.target)

        self._patch('threading', type('T', (), {'Thread': NoThread, 'Lock': ss.threading.Lock}))
        r = self._apply()
        self.assertEqual(r.status_code, 202)
        self.assertTrue(r.get_json()['background'])
        self.assertEqual(started, [ss._apply_to_lyrion_background])

    def test_plain_apply_still_restarts(self):
        self._lyrion(mediadirs=self.paths)
        r = self.client.post('/api/apply', json={})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.restarts, [1])


if __name__ == '__main__':
    unittest.main(verbosity=2)
