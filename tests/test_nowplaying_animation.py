"""Tests for the now-playing animation choice in api_server.py: the CD, vinyl
record or cassette the kiosk can draw in place of the VU meters. Which ids are
accepted, what is read back from a missing or damaged file, and what the HTTP
routes answer.

Run with:  python tests/test_nowplaying_animation.py
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import api_server  # noqa: E402

CHOICES = ['none', 'cd', 'cdfront', 'vinyl', 'cassette']


class NowPlayingAnimationTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='hifi-np-animation-test-')
        self._saved = {}
        self._patch('NOWPLAYING_ANIMATION_FILE', os.path.join(self.tmp, 'etc', 'nowplaying-animation'))
        # the VU switch lives next to it: setting an animation must not touch it
        self._patch('VU_METER_FILE', os.path.join(self.tmp, 'etc', 'vu-meter-enabled'))
        self.client = api_server.app.test_client()

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(api_server, name, value)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _patch(self, name, value):
        self._saved[name] = getattr(api_server, name)
        setattr(api_server, name, value)

    def _write_raw(self, content):
        os.makedirs(os.path.dirname(api_server.NOWPLAYING_ANIMATION_FILE), exist_ok=True)
        with open(api_server.NOWPLAYING_ANIMATION_FILE, 'w') as f:
            f.write(content)

    def _stored(self):
        with open(api_server.NOWPLAYING_ANIMATION_FILE) as f:
            return f.read().strip()

    # ── get / set ─────────────────────────────────────────────────────

    def test_default_is_none(self):
        self.assertEqual(api_server.get_nowplaying_animation(),
                         {'animation': 'none', 'choices': CHOICES})

    def test_set_each_valid_id(self):
        for aid in ('cd', 'vinyl', 'cassette', 'none'):
            r = api_server.set_nowplaying_animation(aid)
            self.assertEqual(r, {'success': True, 'animation': aid}, aid)
            self.assertEqual(api_server.get_nowplaying_animation()['animation'], aid)
            self.assertEqual(self._stored(), aid)
        self.assertFalse(os.path.exists(api_server.NOWPLAYING_ANIMATION_FILE + '.tmp'))

    def test_surrounding_whitespace_is_tolerated(self):
        self.assertTrue(api_server.set_nowplaying_animation(' vinyl\n')['success'])
        self.assertEqual(self._stored(), 'vinyl')

    def test_invalid_ids_are_refused(self):
        api_server.set_nowplaying_animation('cassette')
        for bad in ('', 'CD', 'Vinyl', 'dvd', 'vu', '../../etc/passwd', 'cd/../vinyl',
                    '/etc/hifi-player/nowplaying-animation', 'cd\x00', 'cd;rm -rf /',
                    'a' * 500, None, 1, 0, True, ['cd'], {'animation': 'cd'}):
            r = api_server.set_nowplaying_animation(bad)
            self.assertFalse(r['success'], repr(bad))
            self.assertEqual(r['code'], 'prefs.animationUnknown', repr(bad))
            self.assertEqual(r['animation'], 'cassette', repr(bad))
            self.assertTrue(r['message'], repr(bad))
        self.assertEqual(self._stored(), 'cassette')

    def test_refusal_on_a_fresh_device_writes_nothing(self):
        r = api_server.set_nowplaying_animation('turntable')
        self.assertFalse(r['success'])
        self.assertEqual(r['animation'], 'none')
        self.assertFalse(os.path.exists(api_server.NOWPLAYING_ANIMATION_FILE))

    def test_garbage_file_content_reads_as_none(self):
        for raw in ('', '\n', 'garbage', 'CASSETTE', 'cd vinyl', '../cd', 'x' * 10000, '\x00\x01'):
            self._write_raw(raw)
            self.assertEqual(api_server.get_nowplaying_animation()['animation'], 'none', repr(raw))

    def test_stored_value_with_newline_reads_back(self):
        self._write_raw('vinyl\n')
        self.assertEqual(api_server.get_nowplaying_animation()['animation'], 'vinyl')

    def test_unreadable_file_reads_as_none(self):
        # a directory where the file should be: open() fails, default wins
        os.makedirs(api_server.NOWPLAYING_ANIMATION_FILE)
        self.assertEqual(api_server.get_nowplaying_animation()['animation'], 'none')

    def test_persist_failure_is_reported(self):
        os.makedirs(api_server.NOWPLAYING_ANIMATION_FILE)   # os.replace onto a directory fails
        with self.assertLogs(api_server.log, level='ERROR'):
            r = api_server.set_nowplaying_animation('cd')
        self.assertFalse(r['success'])
        self.assertEqual(r['code'], 'prefs.saveFailed')
        self.assertEqual(r['animation'], 'none')

    def test_error_message_is_bilingual(self):
        with api_server.app.test_request_context(headers={'X-UI-Lang': 'it'}):
            it = api_server.set_nowplaying_animation('dvd')['message']
        with api_server.app.test_request_context(headers={'X-UI-Lang': 'en'}):
            en = api_server.set_nowplaying_animation('dvd')['message']
        self.assertNotEqual(it, 'prefs.animationUnknown')
        self.assertNotEqual(en, 'prefs.animationUnknown')
        self.assertNotEqual(it, en)

    def test_vu_meter_switch_is_left_alone(self):
        api_server.set_vu_meter(True)
        api_server.set_nowplaying_animation('vinyl')
        self.assertTrue(api_server.get_vu_meter()['enabled'])
        api_server.set_vu_meter(False)
        api_server.set_nowplaying_animation('none')
        self.assertFalse(api_server.get_vu_meter()['enabled'])

    # ── HTTP routes ───────────────────────────────────────────────────

    def test_route_get(self):
        r = self.client.get('/nowplaying_animation')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {'animation': 'none', 'choices': CHOICES})

    def test_route_post_valid(self):
        for aid in CHOICES:
            r = self.client.post('/nowplaying_animation', json={'animation': aid})
            self.assertEqual(r.status_code, 200, aid)
            self.assertEqual(r.get_json(), {'success': True, 'animation': aid})
            self.assertEqual(self.client.get('/nowplaying_animation').get_json()['animation'], aid)

    def test_route_post_invalid_is_400(self):
        self.client.post('/nowplaying_animation', json={'animation': 'cd'})
        bodies = [
            {'json': {'animation': '../../etc/shadow'}},
            {'json': {'animation': 'DVD'}},
            {'json': {'animation': 7}},
            {'json': {'animation': None}},
            {'json': {'style': 'cd'}},                  # missing key
            {'json': {}},
            {'json': ['cd']},                           # not an object
            {'json': 'cd'},
            {'data': 'not json', 'content_type': 'application/json'},
            {},                                         # no body at all
        ]
        for kw in bodies:
            r = self.client.post('/nowplaying_animation', **kw)
            self.assertEqual(r.status_code, 400, kw)
            body = r.get_json()
            self.assertFalse(body['success'], kw)
            self.assertEqual(body['animation'], 'cd', kw)
            self.assertEqual(body['code'], 'prefs.animationUnknown', kw)
            self.assertTrue(body['message'], kw)
        self.assertEqual(self._stored(), 'cd')

    def test_route_post_italian_message(self):
        r = self.client.post('/nowplaying_animation', json={'animation': 'dvd'}, headers={'X-UI-Lang': 'it'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()['message'], 'Questa animazione non è disponibile')


if __name__ == '__main__':
    unittest.main()
