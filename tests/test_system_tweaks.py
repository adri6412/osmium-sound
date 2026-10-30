"""Tests for the System tweaks (hifi_system_tweaks.py + api_server wiring).

Two sides:
  * the config model and the /sys apply (hermetic: SYSFS_ROOT and the config
    point at a temp tree);
  * the one command-line knob (mitigations=off) must share hifi_cmdline with
    the screen-rotation tokens without either clobbering the other.

Run with:  python3 tests/test_system_tweaks.py
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import hifi_system_tweaks as stw  # noqa: E402
import api_server as a  # noqa: E402


class ModelTestCase(unittest.TestCase):
    """A fake /sys with two CPUs offering schedutil/performance and a usable
    SMT control."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='hifi-tweaks-')
        sysroot = os.path.join(self.tmp, 'sys')
        cpu = os.path.join(sysroot, 'devices', 'system', 'cpu')
        for n in (0, 1):
            d = os.path.join(cpu, f'cpu{n}', 'cpufreq')
            os.makedirs(d)
            with open(os.path.join(d, 'scaling_governor'), 'w') as f:
                f.write('schedutil\n')
            with open(os.path.join(d, 'scaling_available_governors'), 'w') as f:
                f.write('schedutil performance powersave\n')
        os.makedirs(os.path.join(cpu, 'smt'))
        with open(os.path.join(cpu, 'smt', 'control'), 'w') as f:
            f.write('on\n')
        self.cmdline = os.path.join(self.tmp, 'cmdline')
        with open(self.cmdline, 'w') as f:
            f.write('BOOT_IMAGE=/boot/vmlinuz ro quiet splash\n')
        saved = {k: getattr(stw, k) for k in ('CONF', 'SYSFS_ROOT', 'PROC_CMDLINE')}
        self.addCleanup(lambda: [setattr(stw, k, v) for k, v in saved.items()])
        stw.CONF = os.path.join(self.tmp, 'system-tweaks.json')
        stw.SYSFS_ROOT = sysroot
        stw.PROC_CMDLINE = self.cmdline

    def gov(self, n):
        with open(os.path.join(stw.SYSFS_ROOT, 'devices/system/cpu', f'cpu{n}', 'cpufreq/scaling_governor')) as f:
            return f.read().strip()

    def smt(self):
        with open(os.path.join(stw.SYSFS_ROOT, 'devices/system/cpu/smt/control')) as f:
            return f.read().strip()


class ModelTests(ModelTestCase):
    def test_defaults_match_current_behaviour(self):
        self.assertEqual(stw.load(), {'cpu_governor': 'schedutil',
                                      'cpu_mitigations': 'on', 'hyperthreading': 'on'})

    def test_reads_the_hardware(self):
        self.assertEqual(stw.available_governors(), ['schedutil', 'performance', 'powersave'])
        self.assertEqual(stw.governor_live(), 'schedutil')
        self.assertTrue(stw.smt_available())

    def test_set_fields_accepts_real_values(self):
        m = stw.set_fields(stw.DEFAULTS, {'cpu_governor': 'performance',
                                          'cpu_mitigations': 'off', 'hyperthreading': 'off'})
        self.assertEqual(m, {'cpu_governor': 'performance',
                             'cpu_mitigations': 'off', 'hyperthreading': 'off'})

    def test_unknown_field_refused(self):
        with self.assertRaises(stw.InvalidField) as cm:
            stw.set_fields(stw.DEFAULTS, {'nope': 1})
        self.assertEqual(cm.exception.code, 'systemTweaks.unknownField')

    def test_governor_checked_against_hardware(self):
        with self.assertRaises(stw.InvalidField) as cm:
            stw.set_fields(stw.DEFAULTS, {'cpu_governor': 'ludicrous'})
        self.assertEqual(cm.exception.code, 'systemTweaks.invalidValue')

    def test_bad_enum_refused(self):
        for key, bad in (('cpu_mitigations', 'maybe'), ('hyperthreading', 'sometimes')):
            with self.assertRaises(stw.InvalidField):
                stw.set_fields(stw.DEFAULTS, {key: bad})

    def test_apply_writes_every_cpu_and_smt(self):
        m = stw.update(lambda x: stw.set_fields(x, {'cpu_governor': 'performance',
                                                    'hyperthreading': 'off'}))
        res = stw.apply_runtime(m)
        self.assertEqual(res['governor_cpus'], 2)
        self.assertTrue(res['smt'])
        self.assertEqual((self.gov(0), self.gov(1)), ('performance', 'performance'))
        self.assertEqual(self.smt(), 'off')

    def test_boot_tokens_and_needs_reboot(self):
        off = stw.normalize({'cpu_mitigations': 'off'})
        self.assertEqual(stw.boot_tokens(off), ['mitigations=off'])
        self.assertEqual(stw.boot_tokens(stw.DEFAULTS), [])
        # /proc/cmdline has no mitigations=off, so choosing off needs a reboot
        self.assertTrue(stw.needs_reboot(off))
        self.assertFalse(stw.needs_reboot(stw.DEFAULTS))

    def test_smt_not_supported_is_hidden(self):
        with open(os.path.join(stw.SYSFS_ROOT, 'devices/system/cpu/smt/control'), 'w') as f:
            f.write('notsupported\n')
        self.assertFalse(stw.smt_available())
        # apply is then a no-op on SMT, never raising
        self.assertFalse(stw.apply_smt(stw.normalize({'hyperthreading': 'off'})))


class BootMergeTestCase(ModelTestCase):
    """System tweaks' mitigations token and the rotation tokens share one
    hifi_cmdline value; neither write may drop the other's tokens."""

    CONNECTORS = ('card0-HDMI-A-1', 'card0-DP-1')

    def setUp(self):
        super().setUp()
        self.drm = os.path.join(self.tmp, 'drm')
        for c in self.CONNECTORS:
            os.makedirs(os.path.join(self.drm, c))
        self.esp = os.path.join(self.tmp, 'efi', 'EFI', 'debian')
        os.makedirs(self.esp)
        self.env = {}
        saved = {k: getattr(a, k) for k in (
            'UI_ROTATION_FILE', 'DRM_SYSFS_DIR', 'BOOT_CMDLINE_ENV',
            '_run', '_image_mode', '_is_live_boot', '_update_in_progress')}
        self.addCleanup(lambda: [setattr(a, k, v) for k, v in saved.items()])
        a.UI_ROTATION_FILE = os.path.join(self.tmp, 'ui-rotation')
        a.DRM_SYSFS_DIR = self.drm
        a.BOOT_CMDLINE_ENV = os.path.join(self.esp, 'hifi-cmdline.env')
        a._run = self.fake_run
        a._image_mode = lambda: True
        a._is_live_boot = lambda: False
        a._update_in_progress = lambda: False

    def fake_run(self, cmd, timeout=20):
        out = ''
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
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr='')

    def boot_value(self):
        return self.env.get(a.BOOT_CMDLINE_ENV, {}).get('hifi_cmdline')

    def test_mitigations_rides_beside_rotation(self):
        a.set_ui_rotation(90)
        self.assertIn('hifi.rotate=90', self.boot_value())
        self.assertNotIn('mitigations=off', self.boot_value())
        # turn mitigations off: rotation must survive
        r = a.set_system_tweaks({'cpu_mitigations': 'off'})
        self.assertTrue(r['success'])
        self.assertTrue(r['needs_reboot'])
        self.assertIn('hifi.rotate=90', self.boot_value())
        self.assertIn('mitigations=off', self.boot_value())

    def test_clearing_rotation_keeps_mitigations(self):
        a.set_system_tweaks({'cpu_mitigations': 'off'})
        a.set_ui_rotation(90)
        a.set_ui_rotation(0)                       # rotation back to normal
        self.assertEqual(self.boot_value(), 'mitigations=off')

    def test_mitigations_back_on_leaves_rotation_alone(self):
        a.set_ui_rotation(180)
        a.set_system_tweaks({'cpu_mitigations': 'off'})
        a.set_system_tweaks({'cpu_mitigations': 'on'})
        self.assertIn('hifi.rotate=180', self.boot_value())
        self.assertNotIn('mitigations=off', self.boot_value())

    def test_get_reports_capabilities(self):
        info = a.get_system_tweaks()
        self.assertIn('performance', info['governors_available'])
        self.assertTrue(info['smt_available'])
        self.assertEqual(info['conf']['cpu_governor'], 'schedutil')


if __name__ == '__main__':
    unittest.main()
