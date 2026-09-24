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


class BundleSecretsTests(unittest.TestCase):
    """An owner found their NAS password in config/etc/hifi-sources.json."""

    SOURCES = {'sources': [
        {'id': 'a', 'type': 'smb', 'server': 'nas', 'share': 'music',
         'username': 'g22', 'password': 'hunter2', 'rw': True},
        {'id': 'b', 'type': 'smb', 'server': 'nas', 'share': 'pub',
         'username': '', 'password': ''},
    ]}

    def build_with(self, text):
        import os
        import tempfile
        fd, path = tempfile.mkstemp(suffix='.json')
        with os.fdopen(fd, 'w') as f:
            f.write(text)
        saved = (a.SUPPORT_CONFIG_FILES, a._SUPPORT_REDACT_JSON)
        a.SUPPORT_CONFIG_FILES, a._SUPPORT_REDACT_JSON = [path], {path}
        try:
            return path, zipfile.ZipFile(io.BytesIO(a._support_bundle_build()))
        finally:
            a.SUPPORT_CONFIG_FILES, a._SUPPORT_REDACT_JSON = saved
            os.unlink(path)

    def test_the_login_of_a_share_is_masked(self):
        path, z = self.build_with(json.dumps(self.SOURCES))
        raw = z.read('config' + path).decode()
        self.assertNotIn('hunter2', raw)
        self.assertNotIn('g22', raw)
        d = json.loads(raw)['sources']
        self.assertEqual(d[0]['password'], '<redacted>')
        self.assertEqual(d[0]['server'], 'nas')
        # guest versus login must still be visible
        self.assertEqual(d[1]['password'], '')

    def test_a_file_that_does_not_parse_is_left_out(self):
        path, z = self.build_with('{"password": "hunter2",')
        self.assertNotIn('config' + path, z.namelist())
        for name in z.namelist():
            self.assertNotIn(b'hunter2', z.read(name))


class LyrionLogTests(unittest.TestCase):
    """Lyrion's own logs are on /data and survive the power cycle that a
    frozen box gets, so they go in — tail only, and without the tokens that
    streaming services put in the URLs Lyrion logs."""

    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp()
        self.saved = (a.SUPPORT_LYRION_LOG_DIR, a.SUPPORT_LYRION_LOG_TAIL)
        a.SUPPORT_LYRION_LOG_DIR = self.dir
        self.addCleanup(lambda: (setattr(a, 'SUPPORT_LYRION_LOG_DIR', self.saved[0]),
                                 setattr(a, 'SUPPORT_LYRION_LOG_TAIL', self.saved[1])))

    def write(self, name, data):
        import os
        with open(os.path.join(self.dir, name), 'wb') as f:
            f.write(data)

    def test_server_and_scanner_logs_are_in_the_bundle(self):
        self.write('server.log', b'[18:09] Slim::Web::HTTP warning\n')
        self.write('scanner.log', b'[18:00] scan done\n')
        self.write('unrelated.txt', b'nope\n')
        names = zipfile.ZipFile(io.BytesIO(a._support_bundle_build())).namelist()
        self.assertIn('lyrion/server.log', names)
        self.assertIn('lyrion/scanner.log', names)
        self.assertNotIn('lyrion/unrelated.txt', names)

    def test_url_credentials_are_masked(self):
        self.write('server.log', b'GET http://s/x?track=1&user_auth_token=abc123&sig=f00 ok\n')
        data = dict(a._support_lyrion_logs())['server.log']
        self.assertNotIn(b'abc123', data)
        self.assertNotIn(b'f00', data)
        self.assertIn(b'track=1', data)

    def test_only_the_tail_of_a_big_log(self):
        a.SUPPORT_LYRION_LOG_TAIL = 64
        self.write('server.log', b''.join(b'line %04d\n' % i for i in range(1000)))
        data = dict(a._support_lyrion_logs())['server.log']
        self.assertTrue(data.startswith(b'(... first '))
        self.assertTrue(data.endswith(b'line 0999\n'))
        self.assertLess(len(data), 200)


if __name__ == '__main__':
    unittest.main()
