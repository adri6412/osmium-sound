"""Unit tests for the support bundle.

The bundle is what a remote diagnosis has to work from, and it had two holes
that cost a real investigation: nothing about the disk, and nothing about the
A/B conversion — so "it updated but stayed on the old layout" could not be
answered from the zip at all. These tests pin down that the answers are in
there, and that collecting them never takes the bundle down with it: a device
that is poorly is exactly the one being asked for a bundle.
"""
import io
import json
import unittest
import zipfile

import api_server as a


class BundleContentsTests(unittest.TestCase):
    def bundle(self):
        return zipfile.ZipFile(io.BytesIO(a._support_bundle_build()))

    def test_the_disk_and_the_ab_state_are_in_it(self):
        names = self.bundle().namelist()
        for member in ('ab_status.json', 'disks.txt', 'services.txt', 'system_info.json'):
            self.assertIn(member, names)

    def test_ab_status_is_valid_json(self):
        d = json.loads(self.bundle().read('ab_status.json'))
        self.assertIsInstance(d, dict)
        for key in ('image_mode', 'rauc_configured'):
            self.assertIn(key, d)

    def test_the_disk_snapshot_names_what_it_ran(self):
        txt = self.bundle().read('disks.txt').decode()
        for label in ('== lsblk ==', '== df ==', '== partitions =='):
            self.assertIn(label, txt)

    def test_the_ab_units_are_reported(self):
        # A device that did not convert looks like one that did nothing unless
        # the units that carry the conversion are named.
        txt = self.bundle().read('services.txt').decode()
        for unit in ('hifi-rauc-config', 'hifi-ab-image', 'hifi-ab-finish'):
            self.assertIn(unit, txt)


class GracefulDegradationTests(unittest.TestCase):
    def test_a_missing_precheck_script_does_not_break_the_bundle(self):
        saved = a.AB_PRECHECK_SCRIPT
        a.AB_PRECHECK_SCRIPT = '/nonexistent/hifi-ab-precheck.sh'
        try:
            d = a._support_ab_snapshot()
        finally:
            a.AB_PRECHECK_SCRIPT = saved
        self.assertIn('precheck_run', d)
        self.assertIn('error', d['precheck_run'])

    def test_a_failing_ab_status_is_reported_not_raised(self):
        saved = a.ab_status
        a.ab_status = lambda: (_ for _ in ()).throw(RuntimeError('boom'))
        try:
            d = a._support_ab_snapshot()
        finally:
            a.ab_status = saved
        self.assertIn('error', d)
        self.assertIn('boom', d['error'])

    def test_the_precheck_is_not_run_on_an_image_device(self):
        # On a converted device the question is already answered, and running
        # a pre-check about converting would only be noise.
        saved = a.ab_status
        a.ab_status = lambda: {'image_mode': True, 'precheck': None}
        try:
            d = a._support_ab_snapshot()
        finally:
            a.ab_status = saved
        self.assertNotIn('precheck_run', d)


if __name__ == '__main__':
    unittest.main()
