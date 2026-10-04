"""Tests for the screen rotation in api_server.py (Settings -> Display).

One setting, two readers: the Qt kiosk turns its canvas from
/etc/hifi-player/ui-rotation, and the boot splash turns from the kernel
command line (video=<connector>:panel_orientation=...). These pin down that
the file and the command line always agree, on an A/B image (a GRUB
environment file of its own on the ESP, read by the slot's grub.cfg) and on a
legacy root (/etc/default/grub + update-grub), and that the A/B boot state is
never touched.

Hermetic: paths go to a temp dir, the DRM connectors are fake sysfs entries,
grub-editenv and update-grub are stubbed.

Run with:  python tests/test_ui_rotation.py
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import api_server as a  # noqa: E402


class RotationTestCase(unittest.TestCase):
    CONNECTORS = ('card0-eDP-1', 'card0-HDMI-A-1', 'card0-DP-1', 'card0-Writeback-1')

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='hifi-rot-test-')
        self.drm = os.path.join(self.tmp, 'drm')
        for c in self.CONNECTORS:
            os.makedirs(os.path.join(self.drm, c))
        os.makedirs(os.path.join(self.drm, 'card0'))           # the card itself, not a connector
        self.esp = os.path.join(self.tmp, 'efi', 'EFI', 'debian')
        os.makedirs(self.esp)
        self.grub = os.path.join(self.tmp, 'grub')
        with open(self.grub, 'w') as f:
            f.write('GRUB_TIMEOUT=0\nGRUB_CMDLINE_LINUX_DEFAULT="quiet splash loglevel=0"\n')
        self.env = {}            # what grub-editenv holds, per file
        self.calls = []
        saved = {k: getattr(a, k) for k in (
            'UI_ROTATION_FILE', 'DRM_SYSFS_DIR', 'BOOT_CMDLINE_ENV', 'GRUB_DEFAULTS_FILE',
            '_run', '_image_mode', '_is_live_boot', '_update_in_progress')}
        self.addCleanup(lambda: [setattr(a, k, v) for k, v in saved.items()])
        a.UI_ROTATION_FILE = os.path.join(self.tmp, 'ui-rotation')
        a.DRM_SYSFS_DIR = self.drm
        a.BOOT_CMDLINE_ENV = os.path.join(self.esp, 'hifi-cmdline.env')
        a.GRUB_DEFAULTS_FILE = self.grub
        a._run = self.fake_run
        a._image_mode = lambda: True
        a._is_live_boot = lambda: False
        a._update_in_progress = lambda: False

    def fake_run(self, cmd, timeout=20):
        self.calls.append(cmd)
        out, rc = '', 0
        if cmd[0] == 'grub-editenv':
            path, op = cmd[1], cmd[2]
            if op == 'create':
                open(path, 'w').close()
                self.env.setdefault(path, {})
            elif op == 'set':
                k, v = cmd[3].split('=', 1)
                self.env.setdefault(path, {})[k] = v
            elif op == 'unset':
                self.env.get(path, {}).pop(cmd[3], None)
            elif op == 'list':
                out = ''.join(f'{k}={v}\n' for k, v in self.env.get(path, {}).items())
        return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr='')

    def saved(self):
        with open(a.UI_ROTATION_FILE) as f:
            return f.read()

    def boot_value(self):
        return self.env.get(a.BOOT_CMDLINE_ENV, {}).get('hifi_cmdline')


class ImageTests(RotationTestCase):
    def test_absent_means_normal(self):
        self.assertEqual(a.get_ui_rotation(), {'rotation': 0})
        with open(a.UI_ROTATION_FILE, 'w') as f:
            f.write('45\n')
        self.assertEqual(a.get_ui_rotation(), {'rotation': 0})

    def test_a_quarter_turn_reaches_the_kiosk_and_the_splash(self):
        r = a.set_ui_rotation(90)
        self.assertTrue(r['success'])
        self.assertTrue(r['splash'])
        self.assertEqual(self.saved(), '90\n')
        self.assertEqual(a.get_ui_rotation(), {'rotation': 90})
        # clockwise for the picture = the panel's right side is up (Plymouth)
        self.assertEqual(self.boot_value(),
                         'video=DP-1:panel_orientation=right_side_up '
                         'video=HDMI-A-1:panel_orientation=right_side_up '
                         'video=eDP-1:panel_orientation=right_side_up')
        self.assertNotIn('Writeback', self.boot_value())

    def test_the_other_turns(self):
        a.set_ui_rotation(180)
        self.assertIn('panel_orientation=upside_down', self.boot_value())
        a.set_ui_rotation(270)
        self.assertIn('panel_orientation=left_side_up', self.boot_value())

    def test_back_to_normal_takes_the_tokens_away(self):
        a.set_ui_rotation(90)
        r = a.set_ui_rotation(0)
        self.assertTrue(r['success'] and r['splash'])
        self.assertIsNone(self.boot_value())
        self.assertEqual(self.saved(), '0\n')

    def test_the_ab_state_is_never_written(self):
        a.set_ui_rotation(90)
        a.set_ui_rotation(0)
        touched = {c[1] for c in self.calls if c[0] == 'grub-editenv'}
        self.assertEqual(touched, {a.BOOT_CMDLINE_ENV})
        self.assertFalse(any(c[0] in ('update-grub', 'update-grub2', 'grub-install') for c in self.calls))

    def test_nothing_rewritten_when_already_there(self):
        a.set_ui_rotation(90)
        n = len([c for c in self.calls if c[:3] == ['grub-editenv', a.BOOT_CMDLINE_ENV, 'set']])
        a.set_ui_rotation(90)
        m = len([c for c in self.calls if c[:3] == ['grub-editenv', a.BOOT_CMDLINE_ENV, 'set']])
        self.assertEqual(n, m)

    def test_invalid_values_are_refused(self):
        for bad in (45, -90, 360, 'x', None):
            r = a.set_ui_rotation(bad)
            self.assertFalse(r['success'], bad)
            self.assertEqual(r['code'], 'uiRotation.invalid')
        self.assertFalse(os.path.exists(a.UI_ROTATION_FILE))

    def test_refused_during_an_update(self):
        a._update_in_progress = lambda: True
        r = a.set_ui_rotation(90)
        self.assertFalse(r['success'])
        self.assertEqual(r['code'], 'update.inProgressRetry')

    def test_no_display_saves_for_the_screen_only(self):
        for c in self.CONNECTORS:
            os.rmdir(os.path.join(self.drm, c))
        r = a.set_ui_rotation(90)
        self.assertTrue(r['success'])
        self.assertFalse(r['splash'])
        self.assertEqual(r['code'], 'uiRotation.savedScreenOnly')
        self.assertEqual(self.saved(), '90\n')

    def test_no_esp_saves_for_the_screen_only(self):
        a.BOOT_CMDLINE_ENV = os.path.join(self.tmp, 'not-mounted', 'EFI', 'debian', 'hifi-cmdline.env')
        r = a.set_ui_rotation(180)
        self.assertTrue(r['success'])
        self.assertFalse(r['splash'])

    def test_reconcile_after_moving_to_ab(self):
        with open(a.UI_ROTATION_FILE, 'w') as f:
            f.write('270\n')
        a._reconcile_rotation_boot()
        self.assertIn('panel_orientation=left_side_up', self.boot_value())


class LegacyTests(RotationTestCase):
    def setUp(self):
        super().setUp()
        a._image_mode = lambda: False

    def cmdline(self):
        return a._read_kv_file(self.grub, 'GRUB_CMDLINE_LINUX_DEFAULT').split()

    def test_tokens_go_to_etc_default_grub(self):
        r = a.set_ui_rotation(180)
        self.assertTrue(r['splash'])
        line = self.cmdline()
        self.assertEqual(line[:3], ['quiet', 'splash', 'loglevel=0'])
        self.assertIn('video=HDMI-A-1:panel_orientation=upside_down', line)
        self.assertIn(['update-grub'], self.calls)
        self.assertNotIn(a.BOOT_CMDLINE_ENV, {c[1] for c in self.calls if c[0] == 'grub-editenv'})

    def test_a_new_turn_replaces_the_old_one(self):
        a.set_ui_rotation(90)
        a.set_ui_rotation(270)
        line = self.cmdline()
        self.assertFalse(any('right_side_up' in t for t in line))
        self.assertEqual(len([t for t in line if 'panel_orientation' in t]), 3)
        a.set_ui_rotation(0)
        self.assertEqual(self.cmdline(), ['quiet', 'splash', 'loglevel=0'])

    def test_live_session_saves_for_the_screen_only(self):
        a._is_live_boot = lambda: True
        r = a.set_ui_rotation(90)
        self.assertTrue(r['success'])
        self.assertFalse(r['splash'])
        self.assertNotIn(['update-grub'], self.calls)


if __name__ == '__main__':
    unittest.main()
