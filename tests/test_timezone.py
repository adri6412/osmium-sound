"""Tests for the timezone plumbing in api_server.py.

The bug these pin down: the box would report (and keep showing) UTC after the
user had picked a zone. Two independent causes, both covered here.

  1. The name was read back from /etc/timezone. That file is a Debian-ism
     systemd's timedated does not maintain, so on trixie `timedatectl
     set-timezone` moved /etc/localtime while the name file stayed on the
     build-time "Etc/UTC" that every Settings page then displayed.
  2. If `timedatectl` itself failed (no systemd-timedated on the bus), the
     call gave up and nothing was applied at all.

Hermetic: every path the timezone code touches is redirected into a temp dir
and `timedatectl` is stubbed, so this needs neither root nor an appliance.

Run with:  python tests/test_timezone.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import api_server  # noqa: E402


class TimezoneTestCase(unittest.TestCase):
    """Redirects /etc/localtime, /etc/timezone and the zoneinfo tree."""

    ZONES = ('Europe/Rome', 'America/New_York', 'Etc/UTC', 'UTC', 'posix/Europe/Rome')

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='hifi-tz-test-')
        self.zoneinfo = os.path.join(self.tmp, 'usr', 'share', 'zoneinfo')
        for zone in self.ZONES:
            path = os.path.join(self.zoneinfo, *zone.split('/'))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w') as f:
                f.write('TZif')  # only its existence is ever checked
        os.makedirs(os.path.join(self.tmp, 'etc'))
        self._saved = {}
        self._patch('ZONEINFO_DIR', self.zoneinfo)
        self._patch('LOCALTIME_LINK', os.path.join(self.tmp, 'etc', 'localtime'))
        self._patch('TIMEZONE_FILE', os.path.join(self.tmp, 'etc', 'timezone'))
        # No systemd on the bus here, and no kiosk to restart. `timedatectl`
        # is stubbed per-test via self.timedatectl; the default is the
        # failing one, i.e. the harder of the two paths.
        self.timedatectl = lambda tz: 1
        self.calls = []
        self._saved['subprocess'] = api_server.subprocess
        api_server.subprocess = _StubSubprocess(self)
        self._saved['restart_kiosk_ui'] = api_server.restart_kiosk_ui
        api_server.restart_kiosk_ui = lambda *a, **kw: self.calls.append('restart')
        # A fresh image: UTC by way of the build hook.
        self.link('Etc/UTC')
        self.write_name('Etc/UTC')

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(api_server, name, value)

    def _patch(self, name, value):
        self._saved[name] = getattr(api_server, name)
        setattr(api_server, name, value)

    # ── helpers ──────────────────────────────────────────────────
    def link(self, zone):
        """Point the fake /etc/localtime at `zone`, timedated-style."""
        if os.path.lexists(api_server.LOCALTIME_LINK):
            os.unlink(api_server.LOCALTIME_LINK)
        os.symlink(os.path.join('..', 'usr', 'share', 'zoneinfo', zone),
                   api_server.LOCALTIME_LINK)

    def write_name(self, value):
        with open(api_server.TIMEZONE_FILE, 'w') as f:
            f.write(value + '\n')

    def read_name(self):
        with open(api_server.TIMEZONE_FILE) as f:
            return f.read().strip()

    def linked_zone(self):
        target = os.readlink(api_server.LOCALTIME_LINK)
        return target.split('zoneinfo' + os.sep, 1)[1].replace(os.sep, '/')

    # ── reading it back ──────────────────────────────────────────
    def test_the_symlink_wins_over_a_stale_name_file(self):
        # The reported bug: the zone was applied, but /etc/timezone still said
        # UTC because timedated never touched it, so Settings showed UTC.
        self.link('Europe/Rome')
        self.write_name('Etc/UTC')
        self.assertEqual(api_server.get_timezone(), {'timezone': 'Europe/Rome'})

    def test_the_name_file_is_the_fallback_when_there_is_no_symlink(self):
        # An image that copied the zone file in place instead of linking it.
        os.unlink(api_server.LOCALTIME_LINK)
        self.write_name('Europe/Rome')
        self.assertEqual(api_server.get_timezone(), {'timezone': 'Europe/Rome'})

    def test_utc_when_nothing_says_otherwise(self):
        os.unlink(api_server.LOCALTIME_LINK)
        os.unlink(api_server.TIMEZONE_FILE)
        self.assertEqual(api_server.get_timezone(), {'timezone': 'UTC'})

    def test_the_posix_copy_of_the_tree_reports_the_plain_name(self):
        # /usr/share/zoneinfo/posix/<zone> is the same data under a second
        # name; reporting it verbatim would not match any option Settings has.
        self.link('posix/Europe/Rome')
        self.assertEqual(api_server.get_timezone(), {'timezone': 'Europe/Rome'})

    # ── the list Settings offers ─────────────────────────────────
    def test_the_list_skips_the_posix_and_leap_second_mirrors(self):
        # right/<zone> is TAI-based: a box set from one runs ~37s off, and
        # posix/<zone> is a duplicate of a name already in the list.
        path = os.path.join(self.zoneinfo, 'right', 'Europe')
        os.makedirs(path)
        with open(os.path.join(path, 'Rome'), 'w') as f:
            f.write('TZif')
        listed = api_server.list_timezones()
        self.assertIn('Europe/Rome', listed)
        self.assertNotIn('posix/Europe/Rome', listed)
        self.assertNotIn('right/Europe/Rome', listed)

    # ── setting it ───────────────────────────────────────────────
    def test_setting_a_zone_moves_the_symlink_and_the_name_file(self):
        self.timedatectl = self._timedatectl_like_trixie
        result = api_server.set_timezone('Europe/Rome')
        self.assertTrue(result['success'], result)
        self.assertEqual(result['timezone'], 'Europe/Rome')
        self.assertEqual(self.linked_zone(), 'Europe/Rome')
        # timedated only moved the symlink; set_timezone owes us the name file
        # too, because that is what the backup profile captures.
        self.assertEqual(self.read_name(), 'Europe/Rome')
        self.assertEqual(api_server.get_timezone(), {'timezone': 'Europe/Rome'})

    def test_it_still_applies_when_timedatectl_cannot(self):
        # `Failed to connect to bus` — the box must end up in the right zone
        # anyway rather than silently sitting in UTC.
        self.timedatectl = lambda tz: 1
        result = api_server.set_timezone('America/New_York')
        self.assertTrue(result['success'], result)
        self.assertEqual(self.linked_zone(), 'America/New_York')
        self.assertEqual(self.read_name(), 'America/New_York')

    def test_a_posix_mirror_name_applies_as_the_plain_zone(self):
        # /timezones used to offer these; a client that kept one must not get
        # a "change failed" for a change that actually went through.
        self.timedatectl = self._timedatectl_like_trixie
        result = api_server.set_timezone('posix/Europe/Rome')
        self.assertTrue(result['success'], result)
        self.assertEqual(result['timezone'], 'Europe/Rome')
        self.assertEqual(api_server.get_timezone(), {'timezone': 'Europe/Rome'})

    def test_the_kiosk_is_restarted_so_chromium_re_reads_its_zone(self):
        api_server.set_timezone('Europe/Rome')
        self.assertIn('restart', self.calls)

    @unittest.skipIf(os.geteuid() == 0,
                     'root ignores the directory mode this test relies on')
    def test_a_failed_apply_is_reported_as_such(self):
        # timedatectl down AND the symlink unwritable: nothing applied, and
        # the caller must hear about it instead of getting a false success.
        self.timedatectl = lambda tz: 1
        os.chmod(os.path.join(self.tmp, 'etc'), 0o500)
        try:
            result = api_server.set_timezone('Europe/Rome')
        finally:
            os.chmod(os.path.join(self.tmp, 'etc'), 0o700)
        self.assertFalse(result['success'])
        self.assertEqual(result['code'], 'timezone.changeFailed')
        self.assertNotIn('restart', self.calls)

    def test_unknown_and_traversing_names_are_refused(self):
        for bad in ('', '   ', 'Mars/Olympus', '../../etc/passwd',
                    '/etc/passwd', 'Europe/Rome/../../../etc/passwd'):
            result = api_server.set_timezone(bad)
            self.assertFalse(result['success'], bad)
            self.assertEqual(result['code'], 'timezone.invalid', bad)
        # and none of them moved anything
        self.assertEqual(self.linked_zone(), 'Etc/UTC')
        self.assertEqual(self.read_name(), 'Etc/UTC')

    # ── stubs ────────────────────────────────────────────────────
    def _timedatectl_like_trixie(self, tz):
        """Succeeds, and moves /etc/localtime only — as timedated really does."""
        self.link(tz)
        return 0


class _StubSubprocess(object):
    """Stands in for the subprocess module: only `timedatectl` reaches it."""

    def __init__(self, case):
        self.case = case

    def run(self, argv, **kwargs):
        self.case.calls.append(' '.join(argv))
        assert argv[0] == 'timedatectl', argv
        code = self.case.timedatectl(argv[-1])
        return type('CompletedProcess', (), {
            'returncode': code, 'stdout': '',
            'stderr': '' if code == 0 else 'Failed to connect to bus: No such file or directory',
        })()


if __name__ == '__main__':
    unittest.main(verbosity=2)
