"""Tests for the now-playing animation store in api_server.py: the signed
catalogue, the download and unpacking of .animpak packages (a QML scene and
its images), what gets refused, and how store animations join the choices.

A throwaway Ed25519 key signs a catalogue served by a local HTTP server, so
the real openssl verification and the real urllib download paths run.

Run with:  python tests/test_anim_store.py
"""
import functools
import hashlib
import http.server
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import api_server  # noqa: E402

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
JPG = b'\xff\xd8\xff\xe0' + b'\x00' * 32
SCENE = b'import QtQuick\nItem { property url assetsBase }\n'


def anim_json(aid, version, fmt=1, **extra):
    a = {'id': aid, 'version': version, 'format': fmt, 'name': {'en': aid.title(), 'it': aid.title()},
         'scene': 'Scene.qml', 'order': 60}
    a.update(extra)
    return a


def make_pack(meta, files=None, raw_entries=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        if raw_entries is not None:
            for name, data in raw_entries:
                zf.writestr(name, data)
        else:
            zf.writestr('anim.json', json.dumps(meta))
            for name, data in (files or {'Scene.qml': SCENE, 'deck.png': PNG}).items():
                zf.writestr(name, data)
    return buf.getvalue()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class AnimStoreTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.keydir = tempfile.mkdtemp(prefix='hifi-anim-key-')
        cls.key = os.path.join(cls.keydir, 'key.pem')
        cls.pub = os.path.join(cls.keydir, 'pub.pem')
        subprocess.run(['openssl', 'genpkey', '-algorithm', 'ed25519', '-out', cls.key], check=True, capture_output=True)
        subprocess.run(['openssl', 'pkey', '-in', cls.key, '-pubout', '-out', cls.pub], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.keydir, ignore_errors=True)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='hifi-anim-store-test-')
        self.www = os.path.join(self.tmp, 'www')
        os.makedirs(os.path.join(self.www, 'anim'))
        handler = functools.partial(_QuietHandler, directory=self.www)
        self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self._saved = {}
        self._patch('ANIM_STORE_URL', 'http://127.0.0.1:%d/anim/' % self.httpd.server_address[1])
        self._patch('ANIM_STORE_DIR', os.path.join(self.tmp, 'scenes'))
        self._patch('ANIM_STORE_STATE_DIR', os.path.join(self.tmp, 'state'))
        self._patch('ANIM_STORE_PUBKEY', self.pub)
        self._patch('ANIM_STORE_SIG_RETRY', 0)
        self._patch('NOWPLAYING_ANIMATION_FILE', os.path.join(self.tmp, 'etc', 'nowplaying-animation'))
        api_server._anim_store.update({'catalog': None, 'checked': 0, 'error': None, 'checking': False,
                                       'loaded': False, 'jobs': {}})

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        for name, value in self._saved.items():
            setattr(api_server, name, value)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _patch(self, name, value):
        self._saved[name] = getattr(api_server, name)
        setattr(api_server, name, value)

    # ── publishing helpers ───────────────────────────────────────────

    def publish(self, packs, sign_with=None, tamper_index=False):
        """packs: [(anim.json, pack_bytes)]; writes the .animpak files,
        previews, index.json and its signature into the served folder."""
        d = os.path.join(self.www, 'anim')
        entries = []
        for meta, data in packs:
            fname = '%s-%d.animpak' % (meta['id'], meta['version'])
            with open(os.path.join(d, fname), 'wb') as f:
                f.write(data)
            pname = '%s-%d.jpg' % (meta['id'], meta['version'])
            with open(os.path.join(d, pname), 'wb') as f:
                f.write(JPG)
            entries.append({'id': meta['id'], 'version': meta['version'], 'format': meta.get('format', 1),
                            'name': meta['name'], 'author': 'Osmium Sound', 'license': 'AGPL-3.0-only',
                            'file': fname, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                            'preview': pname, 'previewSize': len(JPG), 'previewSha256': hashlib.sha256(JPG).hexdigest()})
        index = json.dumps({'format': 1, 'animations': entries}).encode('utf-8')
        path = os.path.join(d, 'index.json')
        with open(path, 'wb') as f:
            f.write(index)
        subprocess.run(['openssl', 'pkeyutl', '-sign', '-inkey', sign_with or self.key, '-rawin',
                        '-in', path, '-out', path + '.sig'], check=True, capture_output=True)
        if tamper_index:
            with open(path, 'wb') as f:
                f.write(index.replace(b'Osmium Sound', b'Someone Else'))

    def refresh(self):
        api_server._anim_store_refresh()

    def install(self, aid):
        r = api_server.anim_store_install(aid)
        for _ in range(100):
            job = api_server._anim_store['jobs'].get(aid)
            if not job or job['state'] == 'error':
                break
            time.sleep(0.05)
        return r

    def store_items(self):
        return {i['id']: i for i in api_server.get_anim_store()['animations']}

    # ── catalogue ────────────────────────────────────────────────────

    def test_signed_catalogue_is_listed_with_preview(self):
        meta = anim_json('reel', 1)
        self.publish([(meta, make_pack(meta))])
        self.refresh()
        items = self.store_items()
        self.assertTrue(items['reel']['new'])
        self.assertFalse(items['reel']['installed'])
        self.assertTrue(items['reel']['preview'].startswith('data:image/jpeg;base64,'))
        self.assertIsNone(api_server.get_anim_store()['error'])
        self.assertEqual(api_server.get_anim_store(summary=True), {'new': 1, 'updates': 0})

    def test_catalogue_signed_by_another_key_is_ignored(self):
        other = os.path.join(self.tmp, 'other.pem')
        subprocess.run(['openssl', 'genpkey', '-algorithm', 'ed25519', '-out', other], check=True, capture_output=True)
        meta = anim_json('reel', 1)
        self.publish([(meta, make_pack(meta))], sign_with=other)
        self.refresh()
        store = api_server.get_anim_store()
        self.assertEqual(store['animations'], [])
        self.assertEqual(store['error']['code'], 'animStore.signatureInvalid')

    def test_altered_catalogue_is_ignored(self):
        meta = anim_json('reel', 1)
        self.publish([(meta, make_pack(meta))], tamper_index=True)
        self.refresh()
        self.assertEqual(api_server.get_anim_store()['error']['code'], 'animStore.signatureInvalid')

    def test_offline_keeps_the_last_verified_catalogue(self):
        meta = anim_json('reel', 1)
        self.publish([(meta, make_pack(meta))])
        self.refresh()
        shutil.rmtree(os.path.join(self.www, 'anim'))
        api_server._anim_store.update({'catalog': None, 'loaded': False, 'checked': 0})
        api_server._anim_store_load_cached()
        self.assertEqual([e['id'] for e in api_server._anim_store['catalog']], ['reel'])
        self.refresh()
        store = api_server.get_anim_store()
        self.assertIn('reel', [i['id'] for i in store['animations']])
        self.assertEqual(store['error']['code'], 'animStore.catalogUnavailable')

    def test_builtin_ids_are_not_offered(self):
        meta = anim_json('vinyl', 3)
        self.publish([(meta, make_pack(meta))])
        self.refresh()
        self.assertNotIn('vinyl', self.store_items())
        self.assertEqual(api_server.anim_store_install('vinyl')['code'], 'animStore.builtin')

    def test_newer_scene_format_is_listed_but_not_installed(self):
        meta = anim_json('future', 1, fmt=api_server.ANIM_SCENE_FORMAT + 1)
        self.publish([(meta, make_pack(meta))])
        self.refresh()
        self.assertFalse(self.store_items()['future']['supported'])
        self.assertEqual(api_server.anim_store_install('future')['code'], 'animStore.unsupported')

    def test_seen_clears_the_new_badge(self):
        meta = anim_json('reel', 1)
        self.publish([(meta, make_pack(meta))])
        self.refresh()
        self.assertTrue(api_server.anim_store_mark_seen()['success'])
        self.assertFalse(self.store_items()['reel']['new'])

    # ── install / remove / choice ────────────────────────────────────

    def test_install_unpacks_and_joins_the_choices(self):
        meta = anim_json('reel', 1)
        pack = make_pack(meta, {'Scene.qml': SCENE, 'Reel.qml': SCENE, 'deck.png': PNG, 'tape.jpg': JPG})
        self.publish([(meta, pack)])
        self.refresh()
        self.assertTrue(self.install('reel')['success'])
        d = os.path.join(api_server.ANIM_STORE_DIR, 'reel')
        self.assertEqual(sorted(os.listdir(d)), ['Reel.qml', 'Scene.qml', 'anim.json', 'deck.png', 'tape.jpg'])
        got = api_server.get_nowplaying_animation()
        self.assertIn('reel', got['choices'])
        self.assertEqual(got['store'], [{'id': 'reel', 'name': {'en': 'Reel', 'it': 'Reel'}, 'scene': 'Scene.qml'}])
        self.assertTrue(api_server.set_nowplaying_animation('reel')['success'])
        self.assertEqual(api_server.get_nowplaying_animation()['animation'], 'reel')
        self.assertTrue(self.store_items()['reel']['installed'])

    def test_not_installed_store_id_cannot_be_chosen(self):
        self.assertEqual(api_server.set_nowplaying_animation('reel')['code'], 'prefs.animationUnknown')

    def test_remove_deletes_and_resets_the_choice(self):
        meta = anim_json('reel', 1)
        self.publish([(meta, make_pack(meta))])
        self.refresh()
        self.install('reel')
        api_server.set_nowplaying_animation('reel')
        self.assertTrue(api_server.anim_store_remove('reel')['success'])
        self.assertFalse(os.path.exists(os.path.join(api_server.ANIM_STORE_DIR, 'reel')))
        self.assertEqual(api_server.get_nowplaying_animation()['animation'], 'none')
        self.assertEqual(api_server.anim_store_remove('reel')['code'], 'animStore.notInstalled')

    def test_refresh_updates_installed_animations_only(self):
        a1, b1 = anim_json('reel', 1), anim_json('jukebox', 1)
        self.publish([(a1, make_pack(a1)), (b1, make_pack(b1))])
        self.refresh()
        self.install('reel')
        a2, b2 = anim_json('reel', 2), anim_json('jukebox', 2)
        self.publish([(a2, make_pack(a2)), (b2, make_pack(b2))])
        self.refresh()
        self.assertEqual(api_server._anim_installed_store(), {'reel': 2})

    def test_damaged_download_is_discarded(self):
        meta = anim_json('reel', 1)
        self.publish([(meta, make_pack(meta))])
        self.refresh()
        with open(os.path.join(self.www, 'anim', 'reel-1.animpak'), 'r+b') as f:
            f.seek(10)
            f.write(b'X')
        self.install('reel')
        item = self.store_items()['reel']
        self.assertEqual(item['jobError']['code'], 'animStore.verifyFailed')
        self.assertFalse(os.path.exists(os.path.join(api_server.ANIM_STORE_DIR, 'reel')))

    def _assert_refused(self, meta, pack):
        self.publish([(meta, pack)])
        self.refresh()
        self.install(meta['id'])
        self.assertEqual(api_server._anim_store['jobs'][meta['id']]['code'], 'animStore.invalidPackage')
        self.assertFalse(os.path.exists(os.path.join(api_server.ANIM_STORE_DIR, meta['id'])))

    def test_path_in_package_is_refused(self):
        meta = anim_json('reel', 1)
        self._assert_refused(meta, make_pack(meta, raw_entries=[
            ('anim.json', json.dumps(meta)), ('Scene.qml', SCENE), ('../../etc/evil.qml', SCENE)]))

    def test_unexpected_file_type_is_refused(self):
        meta = anim_json('reel', 1)
        self._assert_refused(meta, make_pack(meta, {'Scene.qml': SCENE, 'helper.js': b'var x = 1'}))

    def test_missing_scene_is_refused(self):
        meta = anim_json('reel', 1, scene='Missing.qml')
        self._assert_refused(meta, make_pack(meta))

    def test_anim_json_for_another_id_is_refused(self):
        meta = anim_json('reel', 1)
        self._assert_refused(meta, make_pack(dict(meta, id='jukebox')))

    def test_binary_qml_is_refused(self):
        meta = anim_json('reel', 1)
        self._assert_refused(meta, make_pack(meta, {'Scene.qml': b'import QtQuick\x00\xff\xfe'}))

    def test_fake_png_is_refused(self):
        meta = anim_json('reel', 1)
        self._assert_refused(meta, make_pack(meta, {'Scene.qml': SCENE, 'deck.png': b'GIF89a'}))

    def test_unknown_id_is_refused(self):
        self.assertEqual(api_server.anim_store_install('nothing')['code'], 'animStore.unknown')
        self.assertEqual(api_server.anim_store_install('../x')['code'], 'animStore.unknown')


if __name__ == '__main__':
    unittest.main()
