"""Tests for what the monitors show in api_server.py (Settings -> Display).

With more than one monitor the kiosk shows the same interface on all of them
("mirror", the default) or on one only ("only:<output>"); never "extend". The
kiosk reads /etc/hifi-player/ui-screens at its start (kmsmode.cpp), matching
outputs by Qt's names, so these pin down the names, the order (the first
monitor is the source when mirroring) and that a change restarts the kiosk.

Hermetic: the DRM connectors are fake sysfs entries, the file goes to a temp
dir, the kiosk restart is recorded instead of run.

Run with:  python tests/test_ui_screens.py
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import api_server as a  # noqa: E402


def edid_named(name):
    """A minimal EDID whose first descriptor is a monitor name (0xFC)."""
    e = bytearray(128)
    e[:8] = b'\x00\xff\xff\xff\xff\xff\xff\x00'
    d = b'\x00\x00\x00\xfc\x00' + (name.encode('ascii') + b'\n').ljust(13, b' ')
    e[54:72] = d
    return bytes(e)


class ScreensTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='hifi-screens-test-')
        self.drm = os.path.join(self.tmp, 'drm')
        os.makedirs(os.path.join(self.drm, 'card0'))          # the card itself, not a connector
        self.restarts = 0
        saved = {k: getattr(a, k) for k in ('UI_SCREENS_FILE', 'DRM_SYSFS_DIR', 'restart_kiosk_ui',
                                            '_update_in_progress', '_lang')}
        self.addCleanup(lambda: [setattr(a, k, v) for k, v in saved.items()])
        self.addCleanup(shutil.rmtree, self.tmp, True)
        a.UI_SCREENS_FILE = os.path.join(self.tmp, 'ui-screens')
        a.DRM_SYSFS_DIR = self.drm
        a.restart_kiosk_ui = self._restart
        a._update_in_progress = lambda: False
        a._lang = lambda: 'en'

    def _restart(self, delay=1.5):
        self.restarts += 1

    def connector(self, name, status='connected', cid=None, edid=b''):
        d = os.path.join(self.drm, name)
        os.makedirs(d)
        with open(os.path.join(d, 'status'), 'w') as f:
            f.write(status + '\n')
        if cid is not None:
            with open(os.path.join(d, 'connector_id'), 'w') as f:
                f.write(f'{cid}\n')
        with open(os.path.join(d, 'edid'), 'wb') as f:
            f.write(edid)

    def saved(self):
        with open(a.UI_SCREENS_FILE) as f:
            return f.read().strip()


class ListTest(ScreensTestCase):
    def test_names_are_qt_names_in_connector_order(self):
        self.connector('card0-HDMI-A-1', cid=95, edid=edid_named('LG TV'))
        self.connector('card0-eDP-1', cid=77)
        self.connector('card0-DVI-D-2', cid=100, edid=edid_named('DELL U2419H'))
        self.connector('card0-DP-1', status='disconnected', cid=90)
        self.connector('card1-HDMI-A-1', cid=1)                 # another card: not the kiosk's
        s = a.get_ui_screens()
        self.assertEqual([x['name'] for x in s['screens']], ['eDP1', 'HDMI1', 'DVI2'])
        self.assertEqual([x['label'] for x in s['screens']], ['eDP-1', 'LG TV', 'DELL U2419H'])
        self.assertEqual(s['screens'][1]['connector'], 'HDMI-A-1')

    def test_default_is_mirror(self):
        self.assertEqual((a.get_ui_screens()['mode'], a.get_ui_screens()['output']), ('mirror', None))

    def test_a_malformed_file_reads_as_mirror(self):
        with open(a.UI_SCREENS_FILE, 'w') as f:
            f.write('only:../../etc\n')
        self.assertEqual(a.get_ui_screens()['mode'], 'mirror')

    def test_no_drm_at_all(self):
        a.DRM_SYSFS_DIR = os.path.join(self.tmp, 'nothing-here')
        self.assertEqual(a.get_ui_screens()['screens'], [])

    def test_a_broken_edid_falls_back_to_the_connector(self):
        self.connector('card0-HDMI-A-2', cid=1, edid=b'\x00' * 128)
        self.assertEqual(a.get_ui_screens()['screens'][0]['label'], 'HDMI-A-2')


class SetTest(ScreensTestCase):
    def setUp(self):
        super().setUp()
        self.connector('card0-HDMI-A-1', cid=1)
        self.connector('card0-DP-1', cid=2)

    def test_only_on_a_connected_monitor(self):
        r = a.set_ui_screens('only', 'DP1')
        self.assertTrue(r['success'])
        self.assertEqual(self.saved(), 'only:DP1')
        self.assertEqual(self.restarts, 1)
        self.assertEqual((a.get_ui_screens()['mode'], a.get_ui_screens()['output']), ('only', 'DP1'))

    def test_back_to_mirror(self):
        a.set_ui_screens('only', 'DP1')
        r = a.set_ui_screens('mirror', 'DP1')
        self.assertTrue(r['success'])
        self.assertIsNone(r['output'])
        self.assertEqual(self.saved(), 'mirror')
        self.assertEqual(self.restarts, 2)

    def test_a_monitor_that_is_not_connected_is_refused(self):
        r = a.set_ui_screens('only', 'HDMI2')
        self.assertFalse(r['success'])
        self.assertEqual(r['code'], 'uiScreens.notConnected')
        self.assertFalse(os.path.exists(a.UI_SCREENS_FILE))
        self.assertEqual(self.restarts, 0)

    def test_extend_is_not_a_choice(self):
        r = a.set_ui_screens('extend')
        self.assertFalse(r['success'])
        self.assertEqual(r['code'], 'uiScreens.invalid')

    def test_refused_while_an_update_applies(self):
        a._update_in_progress = lambda: True
        r = a.set_ui_screens('mirror')
        self.assertFalse(r['success'])
        self.assertEqual(r['code'], 'update.inProgressRetry')
        self.assertEqual(self.restarts, 0)


class RouteTest(ScreensTestCase):
    def test_routes(self):
        self.connector('card0-HDMI-A-1', cid=1)
        c = a.app.test_client()
        self.assertEqual(c.get('/ui_screens').get_json()['screens'][0]['name'], 'HDMI1')
        r = c.post('/ui_screens', json={'mode': 'only', 'output': 'HDMI1'}).get_json()
        self.assertTrue(r['success'])
        self.assertEqual(self.saved(), 'only:HDMI1')

    def test_messages_exist_in_both_languages(self):
        import hifi_i18n
        for k in ('uiScreens.invalid', 'uiScreens.notConnected', 'uiScreens.changeFailed', 'uiScreens.updated'):
            for lang in ('en', 'it'):
                self.assertNotEqual(a._t(k, lang), k, f'{k} missing in {lang}')
        self.assertTrue(hifi_i18n)


if __name__ == '__main__':
    unittest.main()
