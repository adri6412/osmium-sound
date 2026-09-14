"""Tests for the VU meter store in api_server.py: the signed catalogue, the
download and unpacking of .vupak packages, what gets refused, and how
store skins join the list of looks.

A throwaway Ed25519 key signs a catalogue served by a local HTTP server, so
the real openssl verification and the real urllib download paths run.

Run with:  python tests/test_vu_store.py
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


def skin_json(sid, version, fmt=2, **extra):
    s = {'id': sid, 'version': version, 'format': fmt, 'name': {'en': sid.title(), 'it': sid.title()},
         'size': [2048, 1080], 'under': 'under.png', 'over': 'over.png',
         'needle': {'image': 'needle.png', 'width': 10, 'height': 400, 'pivotX': 5, 'pivotY': 395},
         'meters': [[500, 700], [1500, 700]], 'angles': [-40, 40]}
    s.update(extra)
    return s


def make_pack(skin, files=None, raw_entries=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        if raw_entries is not None:
            for name, data in raw_entries:
                zf.writestr(name, data)
        else:
            zf.writestr('skin.json', json.dumps(skin))
            for name, data in (files or {'under.png': PNG, 'over.png': PNG, 'needle.png': PNG}).items():
                zf.writestr(name, data)
    return buf.getvalue()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class VuStoreTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.keydir = tempfile.mkdtemp(prefix='hifi-vu-key-')
        cls.key = os.path.join(cls.keydir, 'key.pem')
        cls.pub = os.path.join(cls.keydir, 'pub.pem')
        subprocess.run(['openssl', 'genpkey', '-algorithm', 'ed25519', '-out', cls.key], check=True, capture_output=True)
        subprocess.run(['openssl', 'pkey', '-in', cls.key, '-pubout', '-out', cls.pub], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.keydir, ignore_errors=True)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='hifi-vu-store-test-')
        self.www = os.path.join(self.tmp, 'www')
        os.makedirs(self.www)
        handler = functools.partial(_QuietHandler, directory=self.www)
        self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self._saved = {}
        self._patch('VU_STORE_URL', 'http://127.0.0.1:%d/vu/' % self.httpd.server_address[1])
        self._patch('VU_SKINS_DIR', os.path.join(self.tmp, 'builtin'))
        self._patch('VU_STORE_DIR', os.path.join(self.tmp, 'store'))
        self._patch('VU_STORE_STATE_DIR', os.path.join(self.tmp, 'state'))
        self._patch('VU_STORE_PUBKEY', self.pub)
        self._patch('VU_STORE_SIG_RETRY', 0)
        self._patch('VU_STYLE_FILE', os.path.join(self.tmp, 'etc', 'vu-style'))
        os.makedirs(os.path.join(self.www, 'vu'))
        os.makedirs(os.path.join(api_server.VU_SKINS_DIR, 'classic'))
        with open(os.path.join(api_server.VU_SKINS_DIR, 'classic', 'skin.json'), 'w') as f:
            json.dump({'name': {'en': 'Classic', 'it': 'Classico'}, 'order': 10}, f)
        api_server._vu_store.update({'catalog': None, 'checked': 0, 'error': None, 'checking': False,
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
        """packs: [(skin, pack_bytes)]; writes the .vupak files, previews,
        index.json and its signature into the served folder."""
        vu = os.path.join(self.www, 'vu')
        entries = []
        for skin, data in packs:
            fname = '%s-%d.vupak' % (skin['id'], skin['version'])
            with open(os.path.join(vu, fname), 'wb') as f:
                f.write(data)
            pname = '%s-%d.jpg' % (skin['id'], skin['version'])
            with open(os.path.join(vu, pname), 'wb') as f:
                f.write(JPG)
            entries.append({'id': skin['id'], 'version': skin['version'], 'format': skin.get('format', 1),
                            'name': skin['name'], 'author': 'Osmium Sound', 'license': 'CC-BY-4.0',
                            'file': fname, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                            'preview': pname, 'previewSize': len(JPG), 'previewSha256': hashlib.sha256(JPG).hexdigest()})
        index = json.dumps({'format': 1, 'skins': entries}).encode('utf-8')
        path = os.path.join(vu, 'index.json')
        with open(path, 'wb') as f:
            f.write(index)
        subprocess.run(['openssl', 'pkeyutl', '-sign', '-inkey', sign_with or self.key, '-rawin',
                        '-in', path, '-out', path + '.sig'], check=True, capture_output=True)
        if tamper_index:
            with open(path, 'wb') as f:
                f.write(index.replace(b'Osmium Sound', b'Someone Else'))

    def refresh(self):
        api_server._vu_store_refresh()

    def install(self, sid):
        r = api_server.vu_store_install(sid)
        for _ in range(100):
            job = api_server._vu_store['jobs'].get(sid)
            if not job or job['state'] == 'error':
                break
            time.sleep(0.05)
        return r

    def store_items(self):
        return {i['id']: i for i in api_server.get_vu_store()['skins']}

    # ── catalogue ────────────────────────────────────────────────────

    def test_signed_catalogue_is_listed_with_preview(self):
        skin = skin_json('amber', 1)
        self.publish([(skin, make_pack(skin))])
        self.refresh()
        items = self.store_items()
        self.assertIn('amber', items)
        self.assertTrue(items['amber']['new'])
        self.assertFalse(items['amber']['installed'])
        self.assertTrue(items['amber']['preview'].startswith('data:image/jpeg;base64,'))
        self.assertIsNone(api_server.get_vu_store()['error'])
        self.assertEqual(api_server.get_vu_store(summary=True), {'new': 1, 'updates': 0})

    def test_catalogue_signed_by_another_key_is_ignored(self):
        other = os.path.join(self.tmp, 'other.pem')
        subprocess.run(['openssl', 'genpkey', '-algorithm', 'ed25519', '-out', other], check=True, capture_output=True)
        skin = skin_json('amber', 1)
        self.publish([(skin, make_pack(skin))], sign_with=other)
        self.refresh()
        store = api_server.get_vu_store()
        self.assertEqual(store['skins'], [])
        self.assertEqual(store['error']['code'], 'vuStore.signatureInvalid')

    def test_altered_catalogue_is_ignored(self):
        skin = skin_json('amber', 1)
        self.publish([(skin, make_pack(skin))], tamper_index=True)
        self.refresh()
        self.assertEqual(api_server.get_vu_store()['error']['code'], 'vuStore.signatureInvalid')

    def test_missing_public_key_refuses_the_catalogue(self):
        self._patch('VU_STORE_PUBKEY', os.path.join(self.tmp, 'nope.pem'))
        skin = skin_json('amber', 1)
        self.publish([(skin, make_pack(skin))])
        self.refresh()
        self.assertEqual(api_server.get_vu_store()['skins'], [])

    def test_offline_keeps_the_last_verified_catalogue(self):
        skin = skin_json('amber', 1)
        self.publish([(skin, make_pack(skin))])
        self.refresh()
        shutil.rmtree(os.path.join(self.www, 'vu'))
        api_server._vu_store.update({'catalog': None, 'loaded': False, 'checked': 0})
        api_server._vu_store_load_cached()
        self.assertEqual([e['id'] for e in api_server._vu_store['catalog']], ['amber'])
        self.refresh()
        store = api_server.get_vu_store()
        self.assertIn('amber', [i['id'] for i in store['skins']])
        self.assertEqual(store['error']['code'], 'vuStore.catalogUnavailable')

    def test_builtin_ids_are_not_offered(self):
        skin = skin_json('classic', 3)
        self.publish([(skin, make_pack(skin))])
        self.refresh()
        self.assertNotIn('classic', self.store_items())
        self.assertEqual(api_server.vu_store_install('classic')['code'], 'vuStore.builtin')

    def test_newer_format_is_listed_but_not_installed(self):
        skin = skin_json('future', 1, fmt=api_server.VU_SKIN_FORMAT + 1)
        self.publish([(skin, make_pack(skin))])
        self.refresh()
        self.assertFalse(self.store_items()['future']['supported'])
        self.assertEqual(api_server.vu_store_install('future')['code'], 'vuStore.unsupported')

    def test_seen_clears_the_new_badge(self):
        skin = skin_json('amber', 1)
        self.publish([(skin, make_pack(skin))])
        self.refresh()
        self.assertTrue(api_server.vu_store_mark_seen()['success'])
        self.assertFalse(self.store_items()['amber']['new'])

    # ── install / remove ─────────────────────────────────────────────

    def test_install_unpacks_and_joins_the_styles(self):
        skin = skin_json('amber', 1, effects={'peakLamp': {'image': 'lamp.png', 'threshold': 90}})
        pack = make_pack(skin, {'under.png': PNG, 'over.png': PNG, 'needle.png': PNG, 'lamp.png': PNG})
        self.publish([(skin, pack)])
        self.refresh()
        self.assertTrue(self.install('amber')['success'])
        d = os.path.join(api_server.VU_STORE_DIR, 'amber')
        self.assertEqual(sorted(os.listdir(d)), ['lamp.png', 'needle.png', 'over.png', 'skin.json', 'under.png'])
        styles = {s['id']: s for s in api_server.list_vu_styles()}
        self.assertEqual(styles['amber']['source'], 'store')
        self.assertEqual(styles['classic']['source'], 'builtin')
        self.assertTrue(api_server.set_vu_style('amber')['success'])
        self.assertTrue(self.store_items()['amber']['installed'])

    def test_remove_deletes_and_resets_the_style_in_use(self):
        skin = skin_json('amber', 1)
        self.publish([(skin, make_pack(skin))])
        self.refresh()
        self.install('amber')
        api_server.set_vu_style('amber')
        self.assertTrue(api_server.vu_store_remove('amber')['success'])
        self.assertFalse(os.path.exists(os.path.join(api_server.VU_STORE_DIR, 'amber')))
        self.assertEqual(api_server.get_vu_style()['style'], 'classic')
        self.assertEqual(api_server.vu_store_remove('amber')['code'], 'vuStore.notInstalled')

    def test_refresh_updates_installed_skins_only(self):
        a1, b1 = skin_json('amber', 1), skin_json('blue', 1)
        self.publish([(a1, make_pack(a1)), (b1, make_pack(b1))])
        self.refresh()
        self.install('amber')
        a2, b2 = skin_json('amber', 2), skin_json('blue', 2)
        self.publish([(a2, make_pack(a2)), (b2, make_pack(b2))])
        self.refresh()
        self.assertEqual(api_server._vu_installed_store(), {'amber': 2})

    def test_damaged_download_is_discarded(self):
        skin = skin_json('amber', 1)
        self.publish([(skin, make_pack(skin))])
        self.refresh()
        with open(os.path.join(self.www, 'vu', 'amber-1.vupak'), 'r+b') as f:
            f.seek(10)
            f.write(b'X')
        self.install('amber')
        item = self.store_items()['amber']
        self.assertEqual(item['job'], 'error')
        self.assertEqual(item['jobError']['code'], 'vuStore.verifyFailed')
        self.assertFalse(os.path.exists(os.path.join(api_server.VU_STORE_DIR, 'amber')))

    def _assert_refused(self, skin, pack):
        self.publish([(skin, pack)])
        self.refresh()
        self.install(skin['id'])
        self.assertEqual(api_server._vu_store['jobs'][skin['id']]['code'], 'vuStore.invalidPackage')
        self.assertFalse(os.path.exists(os.path.join(api_server.VU_STORE_DIR, skin['id'])))

    def test_path_in_package_is_refused(self):
        skin = skin_json('amber', 1)
        self._assert_refused(skin, make_pack(skin, raw_entries=[
            ('skin.json', json.dumps(skin)), ('under.png', PNG), ('over.png', PNG), ('needle.png', PNG),
            ('../../etc/evil.png', PNG)]))

    def test_unexpected_file_type_is_refused(self):
        skin = skin_json('amber', 1)
        self._assert_refused(skin, make_pack(skin, {'under.png': PNG, 'over.png': PNG, 'needle.png': PNG,
                                                    'Main.qml': b'import QtQuick'}))

    def test_skin_json_for_another_id_is_refused(self):
        skin = skin_json('amber', 1)
        other = dict(skin, id='blue')
        self._assert_refused(skin, make_pack(other))

    def test_missing_image_is_refused(self):
        skin = skin_json('amber', 1)
        self._assert_refused(skin, make_pack(skin, {'under.png': PNG, 'over.png': PNG}))

    def test_fake_png_is_refused(self):
        skin = skin_json('amber', 1)
        self._assert_refused(skin, make_pack(skin, {'under.png': b'GIF89a', 'over.png': PNG, 'needle.png': PNG}))

    def test_effect_image_outside_package_is_refused(self):
        skin = skin_json('amber', 1, effects={'backlight': {'image': '../lit.png'}})
        self._assert_refused(skin, make_pack(skin))

    def test_bad_geometry_is_refused(self):
        skin = skin_json('amber', 1, meters=[[1, 2]])
        self._assert_refused(skin, make_pack(skin))

    def test_unknown_id_is_refused(self):
        self.assertEqual(api_server.vu_store_install('nothing')['code'], 'vuStore.unknown')
        self.assertEqual(api_server.vu_store_install('../x')['code'], 'vuStore.unknown')


if __name__ == '__main__':
    unittest.main()
