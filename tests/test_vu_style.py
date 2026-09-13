"""Tests for the VU meter skin choice in api_server.py: which skins are offered
(read from the folders the on-screen interface ships, never kept by hand),
which one is in use, and what may be stored.

Run with:  python tests/test_vu_style.py
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import api_server  # noqa: E402

REPO_SKINS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'native-ui-qt', 'assets', 'vu')


class VuStyleTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='hifi-vu-style-test-')
        self._saved = {}
        self._patch('VU_SKINS_DIR', os.path.join(self.tmp, 'vu'))
        self._patch('VU_STYLE_FILE', os.path.join(self.tmp, 'etc', 'vu-style'))
        os.makedirs(api_server.VU_SKINS_DIR)

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(api_server, name, value)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _patch(self, name, value):
        self._saved[name] = getattr(api_server, name)
        setattr(api_server, name, value)

    def _skin(self, sid, en, it=None, order=None, raw=None):
        d = os.path.join(api_server.VU_SKINS_DIR, sid)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'skin.json'), 'w', encoding='utf-8') as f:
            if raw is not None:
                f.write(raw)
            else:
                meta = {'name': {'en': en, 'it': it or en}}
                if order is not None:
                    meta['order'] = order
                json.dump(meta, f)

    def _ids(self):
        return [st['id'] for st in api_server.list_vu_styles()]

    # ── the list ──────────────────────────────────────────────────────

    def test_skins_come_from_the_folders_in_declared_order(self):
        self._skin('modulometer', 'Modulometer', 'Modulometro', order=20)
        self._skin('classic', 'Classic', 'Classico', order=10)
        self._skin('another', 'Another', order=15)
        self.assertEqual(self._ids(), ['classic', 'another', 'modulometer'])
        names = {st['id']: st['name'] for st in api_server.list_vu_styles()}
        self.assertEqual(names['modulometer'], {'en': 'Modulometer', 'it': 'Modulometro'})

    def test_classic_is_always_offered(self):
        # the interface draws it even without its folder, so a device whose
        # payload predates the skins still has a valid choice
        self._skin('modulometer', 'Modulometer', order=20)
        self.assertEqual(self._ids(), ['classic', 'modulometer'])

    def test_no_skins_folder_at_all(self):
        shutil.rmtree(api_server.VU_SKINS_DIR)
        self.assertEqual(self._ids(), ['classic'])

    def test_a_broken_skin_is_not_offered(self):
        self._skin('classic', 'Classic', order=10)
        self._skin('broken', 'x', raw='{ not json')
        os.makedirs(os.path.join(api_server.VU_SKINS_DIR, 'empty'))      # no skin.json
        os.makedirs(os.path.join(api_server.VU_SKINS_DIR, 'Bad Name'))
        self.assertEqual(self._ids(), ['classic'])

    def test_missing_italian_name_falls_back_to_english(self):
        self._skin('classic', 'Classic', order=10)
        self._skin('plain', 'Plain', raw=json.dumps({'name': {'en': 'Plain'}}))
        plain = [st for st in api_server.list_vu_styles() if st['id'] == 'plain'][0]
        self.assertEqual(plain['name'], {'en': 'Plain', 'it': 'Plain'})

    # ── get / set ─────────────────────────────────────────────────────

    def test_default_is_classic(self):
        self._skin('modulometer', 'Modulometer', order=20)
        self.assertEqual(api_server.get_vu_style()['style'], 'classic')

    def test_set_an_installed_skin(self):
        self._skin('modulometer', 'Modulometer', order=20)
        r = api_server.set_vu_style('modulometer')
        self.assertTrue(r['success'])
        self.assertEqual(api_server.get_vu_style()['style'], 'modulometer')
        with open(api_server.VU_STYLE_FILE) as f:
            self.assertEqual(f.read().strip(), 'modulometer')

    def test_unknown_or_unsafe_ids_are_refused(self):
        self._skin('modulometer', 'Modulometer', order=20)
        for bad in ('nagra', '../../etc', '', None, 'Modulometer', 'a' * 60):
            r = api_server.set_vu_style(bad)
            self.assertFalse(r['success'], bad)
            self.assertEqual(r['code'], 'prefs.vuStyleUnknown')
        self.assertFalse(os.path.exists(api_server.VU_STYLE_FILE))

    def test_a_stored_skin_that_is_gone_reads_as_classic(self):
        # chosen once, then removed by an update: the device must not keep
        # asking the interface for a folder that is no longer there
        self._skin('modulometer', 'Modulometer', order=20)
        api_server.set_vu_style('modulometer')
        shutil.rmtree(os.path.join(api_server.VU_SKINS_DIR, 'modulometer'))
        self.assertEqual(api_server.get_vu_style()['style'], 'classic')

    # ── the skins shipped in the repository ──────────────────────────

    def test_shipped_skins_are_complete(self):
        """Every skin folder in native-ui-qt/assets/vu has the files its
        skin.json names and the geometry VuPanel.qml needs."""
        self._patch('VU_SKINS_DIR', REPO_SKINS)
        ids = self._ids()
        self.assertIn('classic', ids)
        self.assertIn('modulometer', ids)
        for sid in ids:
            d = os.path.join(REPO_SKINS, sid)
            with open(os.path.join(d, 'skin.json'), encoding='utf-8') as f:
                skin = json.load(f)
            self.assertEqual(len(skin['size']), 2, sid)
            self.assertEqual(len(skin['meters']), 2, sid)
            self.assertEqual(len(skin['angles']), 2, sid)
            self.assertLess(skin['angles'][0], skin['angles'][1], sid)
            self.assertTrue(skin['name'].get('en') and skin['name'].get('it'), sid)
            for key in ('under', 'over'):
                self.assertTrue(os.path.isfile(os.path.join(d, skin[key])), f'{sid}: {skin[key]}')
            needle = skin['needle']
            if needle.get('image'):
                self.assertTrue(os.path.isfile(os.path.join(d, needle['image'])), sid)
                for key in ('width', 'height', 'pivotX', 'pivotY'):
                    self.assertGreater(needle[key], 0, f'{sid}: needle.{key}')
            else:
                self.assertGreater(needle['height'], 0, sid)


if __name__ == '__main__':
    unittest.main()
