"""Tests for the dashboard's system stats in api_server.py: which filesystem
the disk figure describes, and which sensor the temperatures come from.

Both used to be picked by luck rather than by name -- the root filesystem (the
read-only image slot, permanently 100% full) and the hottest thermal zone in
the box (as often the Wi-Fi card or the chipset as the CPU).

Run with:  python tests/test_system_stats.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import api_server  # noqa: E402


class SensorTestCase(unittest.TestCase):
    """Builds a fake /sys tree per test and points the module's globs at it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='hifi-stats-test-')
        self._saved = {}
        self._patch('THERMAL_ZONE_GLOB', os.path.join(self.tmp, 'thermal', 'thermal_zone*'))
        self._patch('HWMON_GLOB', os.path.join(self.tmp, 'hwmon', 'hwmon*'))
        self._patch('DRM_HWMON_TEMP_GLOB',
                    os.path.join(self.tmp, 'drm', 'card[0-9]', 'device', 'hwmon', 'hwmon*', 'temp*_input'))

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(api_server, name, value)
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _patch(self, name, value):
        self._saved[name] = getattr(api_server, name)
        setattr(api_server, name, value)

    def _zone(self, index, ztype, millideg):
        path = os.path.join(self.tmp, 'thermal', 'thermal_zone%d' % index)
        os.makedirs(path, exist_ok=True)
        self._write(os.path.join(path, 'type'), ztype)
        self._write(os.path.join(path, 'temp'), str(millideg))

    def _hwmon(self, index, name, sensors):
        """sensors: [(millidegrees, label or None), ...] as temp1_input, temp2_input, ..."""
        path = os.path.join(self.tmp, 'hwmon', 'hwmon%d' % index)
        os.makedirs(path, exist_ok=True)
        self._write(os.path.join(path, 'name'), name)
        for n, (millideg, label) in enumerate(sensors, start=1):
            self._write(os.path.join(path, 'temp%d_input' % n), str(millideg))
            if label is not None:
                self._write(os.path.join(path, 'temp%d_label' % n), label)

    def _drm_hwmon(self, name, sensors):
        path = os.path.join(self.tmp, 'drm', 'card0', 'device', 'hwmon', 'hwmon4')
        os.makedirs(path, exist_ok=True)
        self._write(os.path.join(path, 'name'), name)
        for n, (millideg, label) in enumerate(sensors, start=1):
            self._write(os.path.join(path, 'temp%d_input' % n), str(millideg))
            if label is not None:
                self._write(os.path.join(path, 'temp%d_label' % n), label)

    @staticmethod
    def _write(path, text):
        with open(path, 'w') as f:
            f.write(text + '\n')


class CpuTempTests(SensorTestCase):
    def test_picks_the_package_sensor_not_the_hottest_zone(self):
        # A typical Intel mini PC: the Wi-Fi card is the hottest thing listed,
        # and that is exactly what the old max() reported as "Temperature".
        self._zone(0, 'acpitz', 27800)
        self._zone(1, 'pch_cannonlake', 65000)
        self._zone(2, 'x86_pkg_temp', 52000)
        self._zone(3, 'iwlwifi_1', 70000)
        self.assertEqual(api_server._cpu_temp_c(), 52.0)

    def test_ignores_the_igpu_zone(self):
        self._zone(0, 'x86_pkg_temp', 48000)
        self._zone(1, 'gpu_thermal', 61000)
        self.assertEqual(api_server._cpu_temp_c(), 48.0)

    def test_ignores_an_out_of_range_reading(self):
        # 0xFFFF millidegrees from an ACPI zone with nothing behind it.
        self._zone(0, 'acpitz', 216800)
        self._zone(1, 'coretemp', 44000)
        self.assertEqual(api_server._cpu_temp_c(), 44.0)

    def test_hottest_of_several_packages(self):
        self._zone(0, 'x86_pkg_temp', 51000)
        self._zone(1, 'x86_pkg_temp', 57500)
        self.assertEqual(api_server._cpu_temp_c(), 57.5)

    def test_acpitz_only_as_a_last_resort(self):
        self._zone(0, 'acpitz', 40000)
        self._zone(1, 'k10temp', 62000)
        self.assertEqual(api_server._cpu_temp_c(), 62.0)

    def test_a_coretemp_hwmon_beats_the_acpitz_zone(self):
        # acpitz tracks the board on most machines; the hwmon is the die.
        self._zone(0, 'acpitz', 40000)
        self._hwmon(0, 'coretemp', [(58000, 'Package id 0')])
        self.assertEqual(api_server._cpu_temp_c(), 58.0)

    def test_acpitz_when_there_is_nothing_better(self):
        self._zone(0, 'acpitz', 40000)
        self._zone(1, 'nvme', 60000)
        self.assertEqual(api_server._cpu_temp_c(), 40.0)

    def test_falls_back_to_hwmon(self):
        self._zone(0, 'nvme', 58000)
        self._hwmon(0, 'coretemp', [(46000, 'Package id 0'), (44000, 'Core 0'), (49000, 'Core 1')])
        self.assertEqual(api_server._cpu_temp_c(), 46.0)

    def test_hwmon_without_a_package_label_uses_the_hottest_core(self):
        self._hwmon(0, 'coretemp', [(44000, 'Core 0'), (49000, 'Core 1')])
        self.assertEqual(api_server._cpu_temp_c(), 49.0)

    def test_unknown_zone_names_still_report_something(self):
        # Bare ACPI names: better the hottest zone that is at least not a
        # component we can name than no reading at all.
        self._zone(0, 'tz00', 45000)
        self._zone(1, 'nvme', 60000)
        self.assertEqual(api_server._cpu_temp_c(), 45.0)

    def test_no_sensor_at_all(self):
        self.assertIsNone(api_server._cpu_temp_c())

    def test_only_non_cpu_sensors(self):
        self._zone(0, 'nvme', 60000)
        self._zone(1, 'iwlwifi_1', 70000)
        self.assertIsNone(api_server._cpu_temp_c())


class GpuTempTests(SensorTestCase):
    def test_reads_the_drm_hwmon(self):
        self._drm_hwmon('amdgpu', [(43000, 'edge'), (58000, 'junction'), (40000, 'mem')])
        self.assertEqual(api_server._gpu_temp_c(), 43.0)

    def test_falls_back_to_a_gpu_thermal_zone(self):
        self._zone(0, 'x86_pkg_temp', 52000)
        self._zone(1, 'GPU_thermal', 61000)
        self.assertEqual(api_server._gpu_temp_c(), 61.0)

    def test_intel_igpu_has_no_sensor_of_its_own(self):
        self._zone(0, 'x86_pkg_temp', 52000)
        self.assertIsNone(api_server._gpu_temp_c())


class DiskPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='hifi-stats-disk-')
        self._data = api_server.DATA_MOUNT
        api_server.DATA_MOUNT = os.path.join(self.tmp, 'data')

    def tearDown(self):
        api_server.DATA_MOUNT = self._data
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reports_the_data_partition_when_it_is_mounted(self):
        os.makedirs(api_server.DATA_MOUNT)
        real_ismount = os.path.ismount
        os.path.ismount = lambda p: p == api_server.DATA_MOUNT or real_ismount(p)
        try:
            self.assertEqual(api_server._disk_path(), api_server.DATA_MOUNT)
        finally:
            os.path.ismount = real_ismount

    def test_legacy_install_keeps_reporting_root(self):
        # No data partition: / is the writable filesystem and the only answer.
        self.assertEqual(api_server._disk_path(), '/')


if __name__ == '__main__':
    unittest.main()
