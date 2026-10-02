"""Tests for CD ripping: hifi_cdrip.py (settings, drive, AccurateRip offsets,
TOC, file names, WAV CRC), the worker's log and the /api/cd/settings,
/api/cd/cancel and /api/cd/offset_lookup endpoints of sources_server.py.

Hermetic: settings and sources live in temporary folders; the offsets page,
cd-discid and systemctl are fakes.

Run with:  python3 tests/test_cdrip.py
"""
import importlib.util
import io
import json
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)

import hifi_cdrip as hcd  # noqa: E402

OFFSETS_HTML = """<html><body><table border="0" width="100%">
<tr><td bgcolor="#000000"><b>CD Drive</b></td><td><b>Correction Offset</b></td><td><b>Submitted By</b></td><td><b>Percentage Agree</b></td></tr>
<tr><td><font face="Arial" size="2">- 16X12 DVD DUAL</font></td><td align="center"><font>+91</font></td><td><font>10</font></td><td><font>100%</font></td></tr>
<tr><td><font>LG Electronics - DVDRW&nbsp; GX50N</font></td><td><font>+6</font></td><td><font>288</font></td><td><font>100%</font></td></tr>
<tr><td><font>Lite-ON - DVDRW GX50N</font></td><td><font>+48</font></td><td><font>3</font></td><td><font>100%</font></td></tr>
<tr><td><font>ASUS - BW-16D1HT</font></td><td><font>+6</font></td><td><font>3015</font></td><td><font>100%</font></td></tr>
<tr><td><font>Plextor - PX-230A</font></td><td><font>[Purged]</font></td><td><font>8</font></td><td><font>50%</font></td></tr>
</table></body></html>"""

TOC_TEXT = """cdparanoia III release 10.2 (September 11, 2008)

Table of contents (audio tracks only):
track        length               begin        copy pre ch
===========================================================
  1.    13702 [03:02.52]        0 [00:00.00]    no   no  2
  2.    24040 [05:20.40]    13702 [03:02.52]    no  yes  2
TOTAL   37742 [08:23.17]    (audio only)
"""


def write_wav(path, samples=b'\x01\x02\x03\x04' * 100):
    data = samples
    fmt = struct.pack('<HHIIHH', 1, 2, 44100, 44100 * 4, 4, 16)
    body = b'WAVE' + b'fmt ' + struct.pack('<I', len(fmt)) + fmt + b'data' + struct.pack('<I', len(data)) + data
    with open(path, 'wb') as f:
        f.write(b'RIFF' + struct.pack('<I', len(body)) + body)


class TestSettings(unittest.TestCase):
    def test_defaults_and_leniency(self):
        s = hcd.normalize({})
        self.assertEqual(s, hcd.DEFAULTS)
        s = hcd.normalize({'auto_start': 'weird', 'format': 'mp3', 'flac_compression': 42, 'retries': 3,
                           'pre_emphasis': 'x', 'speed': 7, 'offset': 99999, 'target': 'relative/path',
                           'dir_prefix': '/bad:name/', 'enabled': 0})
        self.assertEqual((s['auto_start'], s['format'], s['flac_compression'], s['retries']), ('off', 'flac', 5, 2))
        self.assertEqual((s['pre_emphasis'], s['speed'], s['offset'], s['target']), ('ignore', 0, 0, ''))
        self.assertEqual(s['dir_prefix'], '')
        self.assertFalse(s['enabled'])
        self.assertEqual(hcd.normalize({'dir_prefix': ' CD rips/ '})['dir_prefix'], 'CD rips')
        self.assertEqual(hcd.normalize({'dir_prefix': 'CD rips/2026/'})['dir_prefix'], 'CD rips/2026')
        self.assertEqual(hcd.normalize({'dir_prefix': '../escape'})['dir_prefix'], '')
        self.assertEqual(hcd.clean_prefix('a\\b'), 'a/b')
        self.assertIsNone(hcd.clean_prefix('a/../b'))

    def test_set_fields_strict(self):
        base = hcd.normalize({})
        s = hcd.set_fields(base, {'format': 'wav', 'retries': 5, 'offset': -12, 'speed': 24, 'dir_prefix': 'Rips', 'eject': False})
        self.assertEqual((s['format'], s['retries'], s['offset'], s['speed'], s['dir_prefix'], s['eject']), ('wav', 5, -12, 24, 'Rips', False))
        for bad in ({'format': 'mp3'}, {'retries': 3}, {'flac_compression': 9}, {'speed': 10}, {'offset': 'six'},
                    {'offset': 6000}, {'eject': 1}, {'target': 'no-slash'}, {'dir_prefix': 'a/../b'}, {'nope': 1}, {'pre_emphasis': 'x'}):
            with self.assertRaises(hcd.InvalidField, msg=str(bad)):
                hcd.set_fields(base, bad)
        self.assertEqual(base, hcd.normalize({}))

    def test_save_and_load(self):
        p = os.path.join(tempfile.mkdtemp(), 'cdrip.json')
        hcd.save({'retries': 1, 'target': '/mnt/x'}, p)
        s = hcd.load(p)
        self.assertEqual((s['retries'], s['target'], s['format']), (1, '/mnt/x', 'flac'))
        with open(p, 'w') as f:
            f.write('{ broken')
        self.assertEqual(hcd.load(p), hcd.DEFAULTS)
        self.assertEqual(hcd.load(p + '.missing'), hcd.DEFAULTS)


class TestDrive(unittest.TestCase):
    def test_drive_info(self):
        tmp = tempfile.mkdtemp()
        dev = os.path.join(tmp, 'sr0')
        open(dev, 'w').close()
        link = os.path.join(tmp, 'cdrom')
        os.symlink(dev, link)
        os.makedirs(os.path.join(tmp, 'block', 'sr0', 'device'))
        with open(os.path.join(tmp, 'block', 'sr0', 'device', 'vendor'), 'w') as f:
            f.write('HL-DT-ST\n')
        with open(os.path.join(tmp, 'block', 'sr0', 'device', 'model'), 'w') as f:
            f.write('DVDRW  GX50N   \n')
        d = hcd.drive_info(link, os.path.join(tmp, 'block'))
        self.assertEqual((d['node'], d['vendor'], d['model']), ('sr0', 'HL-DT-ST', 'DVDRW GX50N'))
        self.assertEqual(d['label'], 'HL-DT-ST - DVDRW GX50N (sr0)')
        self.assertTrue(d['present'])
        d = hcd.drive_info(os.path.join(tmp, 'nope'), os.path.join(tmp, 'block'))
        self.assertFalse(d['present'])


class TestOffsets(unittest.TestCase):
    def test_parse(self):
        rows = hcd.parse_offsets_html(OFFSETS_HTML)
        self.assertEqual(rows[0], ('- 16X12 DVD DUAL', 91, '10', '100%'))
        self.assertIn(('LG Electronics - DVDRW GX50N', 6, '288', '100%'), rows)
        self.assertIn(('Plextor - PX-230A', None, '8', '50%'), rows)
        self.assertEqual(len(rows), 5)       # the header is not a row

    def test_find(self):
        rows = hcd.parse_offsets_html(OFFSETS_HTML)
        # the drive says HL-DT-ST, the list says LG Electronics; the exact
        # vendor match wins over the Lite-ON line with the same model
        self.assertEqual(hcd.find_offset(rows, 'HL-DT-ST', 'DVDRW GX50N')[1], 6)
        self.assertEqual(hcd.find_offset(rows, 'HL-DT-ST', 'DVDRW  GX50N')[1], 6)
        self.assertEqual(hcd.find_offset(rows, 'Unknown Vendor', 'DVDRW GX50N')[0], 'LG Electronics - DVDRW GX50N')
        self.assertEqual(hcd.find_offset(rows, 'ASUS', 'BW-16D1HT')[1], 6)
        self.assertIsNone(hcd.find_offset(rows, 'ASUS', 'NOPE'))
        self.assertIsNone(hcd.find_offset(rows, 'ASUS', ''))

    def test_lookup(self):
        r = hcd.lookup_offset('HL-DT-ST', 'DVDRW GX50N', fetch=lambda: OFFSETS_HTML)
        self.assertEqual((r['found'], r['offset'], r['submitted']), (True, 6, '288'))
        r = hcd.lookup_offset('Plextor', 'PX-230A', fetch=lambda: OFFSETS_HTML)
        self.assertEqual((r['found'], r['purged']), (False, True))
        r = hcd.lookup_offset('X', 'Y', fetch=lambda: OFFSETS_HTML)
        self.assertFalse(r['found'])
        with self.assertRaises(OSError):
            hcd.lookup_offset('X', 'Y', fetch=mock.Mock(side_effect=OSError('offline')))


class TestTocAndNames(unittest.TestCase):
    def test_toc(self):
        toc = hcd.parse_cdparanoia_toc(TOC_TEXT)
        self.assertEqual(sorted(toc), [1, 2])
        self.assertEqual(toc[2], {'length': 24040, 'begin': 13702, 'copy': False, 'pre': True, 'channels': 2})
        self.assertEqual(hcd.parse_cdparanoia_toc(''), {})
        self.assertEqual(hcd.frames_to_msf(13702), '03:02.52')

    def test_safe_name(self):
        self.assertEqual(hcd.safe_name('Kind of Blue', 'x'), 'Kind of Blue')
        self.assertEqual(hcd.safe_name('AC/DC: Back "in" Black?', 'x'), 'AC_DC_ Back _in_ Black_')
        self.assertEqual(hcd.safe_name('Café Été – Noël', 'x', ascii_only=True), 'Cafe Ete Noel')   # the dash has no ASCII form and goes
        self.assertEqual(hcd.safe_name('   ', 'Unknown Album'), 'Unknown Album')
        self.assertEqual(len(hcd.safe_name('x' * 300, 'f')), 120)

    def test_wav_crc(self):
        tmp = tempfile.mkdtemp()
        p = os.path.join(tmp, 't.wav')
        write_wav(p)
        import zlib
        self.assertEqual(hcd.wav_crc32(p), zlib.crc32(b'\x01\x02\x03\x04' * 100) & 0xFFFFFFFF)
        with open(os.path.join(tmp, 'not.wav'), 'wb') as f:
            f.write(b'nope')
        self.assertIsNone(hcd.wav_crc32(os.path.join(tmp, 'not.wav')))
        self.assertIsNone(hcd.wav_crc32(os.path.join(tmp, 'missing.wav')))


class TestWorkerLog(unittest.TestCase):
    """hifi-rip-cd.py's log, with the worker imported as a module."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            'hifi_rip_cd', os.path.join(ROOT, 'distro', 'config', 'includes.chroot', 'usr', 'local', 'sbin', 'hifi-rip-cd.py'))
        cls.rip = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.rip)

    def test_build_log(self):
        plan = {'artist': 'Miles Davis', 'album': 'Kind of Blue', 'year': '1959', 'discid': '3b0a2c05', 'device': '/dev/sr0',
                'album_tags': [['MUSICBRAINZ_ALBUMID', 'abc-123'], ['LABEL', 'Columbia']]}
        opt = hcd.normalize({'offset': 6, 'retries': 2, 'pre_emphasis': 'tag'})
        drive = {'label': 'HL-DT-ST - DVDRW GX50N (sr0)'}
        toc = hcd.parse_cdparanoia_toc(TOC_TEXT)
        results = [{'num': 1, 'file': '01 - So What.flac', 'crc': 0xDEADBEEF, 'reads': 2, 'crcs': [0xDEADBEEF, 0xDEADBEEF], 'accurate': True},
                   {'num': 2, 'file': '02 - Freddie Freeloader.flac', 'crc': 1, 'reads': 3, 'crcs': [1, 2, 1], 'accurate': False, 'pre': 'flagged, tagged PRE_EMPHASIS'}]
        log = self.rip.build_log(plan, opt, drive, toc, results, 'Miles Davis/Kind of Blue')
        for needle in ('HL-DT-ST - DVDRW GX50N', 'Read offset : +6 samples', 'MUSICBRAINZ_ALBUMID: abc-123',
                       '03:02.52', 'Copy CRC DEADBEEF', 'Accurately ripped', 'Inaccurate: no two reads agreed',
                       'Pre-emphasis: flagged, tagged PRE_EMPHASIS', '1 track(s) could not be read the same way twice: 2',
                       'End of status report'):
            self.assertIn(needle, log)
        self.assertNotIn('LABEL', log)
        clean = self.rip.build_log(plan, hcd.normalize({}), drive, {}, [{'num': 1, 'file': 'a.flac', 'crc': 5, 'reads': 1, 'accurate': None}], 'x')
        self.assertIn('No errors occurred', clean)
        self.assertIn('Copy OK (read once)', clean)

    def test_read_track_reports_progress(self):
        """The bar moves inside a track: a fake cdparanoia writes the WAV in
        slices and read_track() reports the growing fraction."""
        tmp = tempfile.mkdtemp()
        fake = os.path.join(tmp, 'cdparanoia')
        with open(fake, 'w') as f:
            f.write('#!/usr/bin/env python3\nimport sys, time\nout = sys.argv[-1]\n'
                    'with open(out, "wb") as f:\n    for _ in range(8):\n        f.write(b"x" * 1000); f.flush(); time.sleep(0.12)\n')
        os.chmod(fake, 0o755)
        wav = os.path.join(tmp, 'track01.wav')
        seen = []
        env_path = os.environ['PATH']
        os.environ['PATH'] = tmp + os.pathsep + env_path
        try:
            ok, err = self.rip.read_track('/dev/null', 1, wav, hcd.normalize({}), expected_bytes=8000, on_progress=seen.append)
        finally:
            os.environ['PATH'] = env_path
        self.assertTrue(ok, err)
        self.assertEqual(os.path.getsize(wav), 8000)
        self.assertGreaterEqual(len(seen), 2, seen)
        self.assertEqual(seen, sorted(seen))
        self.assertTrue(all(0 <= v <= 1 for v in seen), seen)
        self.assertFalse(os.path.exists(wav + '.err'))

    def test_extra_tags(self):
        self.assertEqual(self.rip.extra_tags([['artist', ' Miles  Davis '], ['bad name', 'x'], ['LABEL', '']]), ['--tag=ARTIST=Miles Davis'])


class TestApi(unittest.TestCase):
    """/api/cd/settings, /api/cd/cancel and the offset lookup on sources_server."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ.setdefault('HIFI_META_CACHE_DIR', os.path.join(cls.tmp, 'cache'))
        os.environ.setdefault('HIFI_META_ETC_DIR', cls.tmp)
        with mock.patch('hifi_logging.tee_stdio_to_file'):
            import sources_server
        cls.ss = sources_server

    def setUp(self):
        ss = self.ss
        self.tmp = tempfile.mkdtemp()
        self.mount = os.path.join(self.tmp, 'usb')
        os.makedirs(os.path.join(self.mount, 'Rips'))
        self._saved = {}
        self._patch('CDRIP_CONF', os.path.join(self.tmp, 'cdrip.json'))
        self._patch('RIP_STATUS', os.path.join(self.tmp, 'rip-status.json'))
        self._patch('_rip_writable_sources', lambda: [{'id': 'usb1', 'name': 'USB disk', 'type': 'usb', 'mountpoint': self.mount}])
        self.calls = []
        self._patch('_run', self._fake_run)
        self.drive = {'device': '/dev/cdrom', 'node': 'sr0', 'vendor': 'HL-DT-ST', 'model': 'DVDRW GX50N', 'present': True, 'label': 'HL-DT-ST - DVDRW GX50N (sr0)'}
        self._hcd_saved = (hcd.drive_info, hcd.fetch_offsets)
        hcd.drive_info = lambda device=None, sys_block=None: self.drive
        hcd.fetch_offsets = lambda url=None, timeout=25: OFFSETS_HTML
        self.client = ss.app.test_client()

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(self.ss, k, v)
        hcd.drive_info, hcd.fetch_offsets = self._hcd_saved

    def _patch(self, name, value):
        self._saved[name] = getattr(self.ss, name)
        setattr(self.ss, name, value)

    def _fake_run(self, cmd, timeout=20):
        import subprocess
        self.calls.append(list(cmd))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout='', stderr='')

    def test_get_defaults(self):
        r = self.client.get('/api/cd/settings')
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertTrue(d['success'])
        self.assertEqual(d['settings'], hcd.DEFAULTS)
        self.assertEqual(d['drive']['label'], 'HL-DT-ST - DVDRW GX50N (sr0)')
        self.assertFalse(d['target_ok'])
        self.assertEqual(d['targets'][0]['source_id'], 'usb1')
        self.assertEqual(d['choices']['retries'], [0, 1, 2, 5])

    def test_post_and_target_rules(self):
        r = self.client.post('/api/cd/settings', json={'target': os.path.join(self.mount, 'Rips'), 'retries': 5, 'format': 'wav'})
        d = r.get_json()
        self.assertEqual(r.status_code, 200, d)
        self.assertTrue(d['target_ok'])
        self.assertEqual((d['settings']['retries'], d['settings']['format']), (5, 'wav'))
        self.assertEqual(hcd.load(self.ss.CDRIP_CONF)['target'], os.path.join(self.mount, 'Rips'))
        # outside every writable source: refused, nothing saved
        r = self.client.post('/api/cd/settings', json={'target': self.tmp})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()['code'], 'msg.cdTargetOutside')
        self.assertEqual(hcd.load(self.ss.CDRIP_CONF)['target'], os.path.join(self.mount, 'Rips'))
        # inside, but missing
        r = self.client.post('/api/cd/settings', json={'target': os.path.join(self.mount, 'nope')})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()['code'], 'msg.folderMissing')
        # bad value
        r = self.client.post('/api/cd/settings', json={'retries': 3})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()['code'], 'msg.cdInvalidValue')
        self.assertIn('retries', r.get_json()['message'])
        # clearing the target
        r = self.client.post('/api/cd/settings', json={'target': ''})
        self.assertEqual(r.get_json()['settings']['target'], '')

    def test_default_target_helpers(self):
        hcd.save({'target': os.path.join(self.mount, 'Rips')}, self.ss.CDRIP_CONF)
        self.assertEqual(self.ss._cd_default_target()['path'], os.path.join(self.mount, 'Rips'))
        self.assertEqual(self.ss._cd_default_target()['source_id'], 'usb1')
        hcd.save({'target': '/somewhere/else'}, self.ss.CDRIP_CONF)
        self.assertIsNone(self.ss._cd_default_target())

    def test_offset_lookup(self):
        r = self.client.post('/api/cd/settings/offset_lookup')
        d = r.get_json()
        self.assertEqual(r.status_code, 200, d)
        self.assertEqual((d['offset'], d['drive']), (6, 'LG Electronics - DVDRW GX50N'))
        self.assertEqual(hcd.load(self.ss.CDRIP_CONF)['offset'], 6)
        self.assertIn('+6', d['message'])
        self.drive['model'] = 'NOPE'
        r = self.client.post('/api/cd/settings/offset_lookup')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()['code'], 'msg.cdOffsetNotFound')
        hcd.fetch_offsets = mock.Mock(side_effect=OSError('offline'))
        r = self.client.post('/api/cd/settings/offset_lookup')
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.get_json()['code'], 'msg.cdOffsetLookupFailed')

    def test_cancel(self):
        r = self.client.post('/api/cd/cancel')
        self.assertEqual(r.status_code, 409)
        with open(self.ss.RIP_STATUS, 'w') as f:
            json.dump({'state': 'ripping', 'track': 2, 'total': 9, 'progress': 20, 'message': 'x'}, f)
        self.assertTrue(self.ss._rip_running())
        r = self.client.post('/api/cd/cancel')
        self.assertEqual(r.status_code, 200)
        self.assertIn(['systemctl', 'stop', 'hifi-rip-cd.service'], self.calls)
        # the worker did not get to write "cancelled" (fake stop): the server does
        self.assertEqual(self.ss._rip_state()['state'], 'cancelled')
        self.assertFalse(self.ss._rip_running())
        # and the disc can be ejected now
        r = self.client.post('/api/cd/eject')
        self.assertEqual(r.status_code, 200)
        self.assertIn(['eject', self.ss.CD_DEVICE], self.calls)

    def test_rip_target_folder(self):
        """POST /api/cd/rip with `target` (a folder picked in the browser),
        with the default folder, or with the only writable source."""
        ss = self.ss
        self._patch('RIP_PLAN', os.path.join(self.tmp, 'rip-plan.json'))
        self._patch('RIP_COVER', os.path.join(self.tmp, 'rip-cover.jpg'))
        self._patch('_cd_lookup', lambda toc: None)
        self._patch('_rip_watcher', lambda: None)
        toc = {'discid': 'abcd1234', 'ntracks': 2, 'offsets': [150, 20000], 'total_sec': 500, 'lengths': [264, 235], 'leadout': 37500}
        self._patch('_cd_toc', lambda: toc)
        picked = os.path.join(self.mount, 'Rips')
        r = self.client.post('/api/cd/rip', json={'target': picked})
        self.assertEqual(r.status_code, 202, r.get_json())
        with open(ss.RIP_PLAN) as f:
            plan = json.load(f)
        self.assertEqual(plan['root'], picked)
        self.assertEqual(plan['options']['retries'], 2)
        self.assertEqual(len(plan['tracks']), 2)
        self.assertIn(['systemd-run', '--no-block', '--collect', '--unit=hifi-rip-cd', ss.RIP_SCRIPT, ss.RIP_PLAN], self.calls)
        # a folder outside every writable source is refused
        with open(ss.RIP_STATUS, 'w') as f:
            json.dump({'state': 'idle'}, f)
        r = self.client.post('/api/cd/rip', json={'target': self.tmp})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()['code'], 'msg.cdTargetOutside')
        # nothing picked: the default folder from the settings, else the only source
        hcd.save({'target': picked, 'dir_prefix': 'CD rips/2026'}, ss.CDRIP_CONF)
        r = self.client.post('/api/cd/rip', json={})
        self.assertEqual(r.status_code, 202)
        with open(ss.RIP_PLAN) as f:
            plan = json.load(f)
        self.assertEqual(plan['root'], picked)
        self.assertEqual(plan['options']['dir_prefix'], 'CD rips/2026')
        hcd.save({}, ss.CDRIP_CONF)
        with open(ss.RIP_STATUS, 'w') as f:
            json.dump({'state': 'idle'}, f)
        r = self.client.post('/api/cd/rip', json={})
        self.assertEqual(r.status_code, 202)
        with open(ss.RIP_PLAN) as f:
            plan = json.load(f)
        self.assertEqual(plan['root'], self.mount)

    def test_terminal_states(self):
        for state in ('idle', 'done', 'error', 'cancelled'):
            with open(self.ss.RIP_STATUS, 'w') as f:
                json.dump({'state': state}, f)
            self.assertFalse(self.ss._rip_running(), state)
        with open(self.ss.RIP_STATUS, 'w') as f:
            json.dump({'state': 'starting'}, f)
        self.assertTrue(self.ss._rip_running())


if __name__ == '__main__':
    unittest.main()
