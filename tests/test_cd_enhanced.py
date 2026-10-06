"""Enhanced CD (audio tracks + a data track in a second session) and
mixed-mode discs: the data track is neither ripped nor counted in the
MusicBrainz disc id, and a "non audio" read never throws away the tracks
already ripped.

Hermetic: the TOC, cd-discid and cdparanoia are fakes.

Run with:  python3 -m unittest tests.test_cd_enhanced
"""
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)

import hifi_cdrip as hcd  # noqa: E402
import hifi_metadata as hmeta  # noqa: E402

# An Enhanced CD as cd-discid prints it: 10 audio tracks, then the data
# track of the second session; the lead-out is the end of the data session.
AUDIO_OFFSETS = [150, 15363, 32314, 46592, 63414, 80489, 95413, 112305, 128000, 143111]
DATA_OFFSET = 171600            # 143111 + the last track's audio + 11400 frames of gap
DISC_LEADOUT = 230000
ALL_OFFSETS = AUDIO_OFFSETS + [DATA_OFFSET]


class AudioTocTests(unittest.TestCase):
    def test_trailing_data_track_is_left_out_like_musicbrainz_does(self):
        toc = hcd.audio_toc(ALL_OFFSETS, DISC_LEADOUT, [11])
        self.assertEqual(toc['tracks'], list(range(1, 11)))
        self.assertEqual(toc['offsets'], AUDIO_OFFSETS)
        self.assertEqual(toc['leadout'], DATA_OFFSET - 11400)
        # the disc id is the one of the audio session alone
        self.assertEqual(hmeta.mb_disc_id(toc['offsets'], toc['leadout']),
                         hmeta.mb_disc_id(AUDIO_OFFSETS, DATA_OFFSET - 11400))
        self.assertNotEqual(hmeta.mb_disc_id(toc['offsets'], toc['leadout']),
                            hmeta.mb_disc_id(ALL_OFFSETS, DISC_LEADOUT))

    def test_an_audio_cd_is_unchanged(self):
        toc = hcd.audio_toc(AUDIO_OFFSETS, 160000, [])
        self.assertEqual((toc['offsets'], toc['leadout'], toc['tracks']),
                         (AUDIO_OFFSETS, 160000, list(range(1, 11))))
        self.assertEqual(hcd.audio_toc(AUDIO_OFFSETS, 160000, None)['tracks'], list(range(1, 11)))

    def test_mixed_mode_keeps_the_data_track_in_the_toc_but_not_in_the_rip(self):
        toc = hcd.audio_toc(ALL_OFFSETS, DISC_LEADOUT, [1])
        self.assertEqual(toc['offsets'], ALL_OFFSETS)
        self.assertEqual(toc['leadout'], DISC_LEADOUT)
        self.assertEqual(toc['tracks'], list(range(2, 12)))

    def test_a_data_track_with_no_gap_before_it(self):
        toc = hcd.audio_toc([150, 5000], 9000, [2])
        self.assertEqual(toc['leadout'], 5000)
        self.assertEqual(toc['tracks'], [1])

    def test_a_data_only_disc_has_nothing_to_rip(self):
        self.assertEqual(hcd.audio_toc([150], 9000, [1])['tracks'], [])

    def test_tocentry_control_bits(self):
        # cdte_track 11, adr 1 / ctrl 4 (data), LBA format, lba 171450
        buf = hcd._TOCENTRY.pack(11, (0x4 << 4) | 0x1, hcd.CDROM_LBA, 171450, 0)
        self.assertEqual(len(buf), 12)
        self.assertEqual(hcd.parse_tocentry(buf), (11, 4, 171450))
        audio = hcd._TOCENTRY.pack(3, (0x0 << 4) | 0x1, hcd.CDROM_LBA, 32164, 0)
        self.assertEqual(hcd.parse_tocentry(audio)[1] & hcd.CDROM_DATA_TRACK, 0)

    def test_no_drive_means_no_answer(self):
        self.assertIsNone(hcd.read_data_tracks('/nonexistent/cdrom'))

    def test_non_audio_error(self):
        self.assertTrue(hcd.is_non_audio_error(
            'Selected span contains non audio track at track 11.  Aborting.'))
        self.assertTrue(hcd.is_non_audio_error('non-audio track'))
        self.assertFalse(hcd.is_non_audio_error('Unable to read from the disc: Input/output error'))
        self.assertFalse(hcd.is_non_audio_error(None))


class ServerTocTests(unittest.TestCase):
    """_cd_toc() and the rip plan of sources_server.py on an Enhanced CD."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ.setdefault('HIFI_META_CACHE_DIR', os.path.join(cls.tmp, 'cache'))
        os.environ.setdefault('HIFI_META_ETC_DIR', cls.tmp)
        with mock.patch('hifi_logging.tee_stdio_to_file'):
            import sources_server
        cls.ss = sources_server

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        ss = self.ss
        ss._cd_leadouts.clear()
        ss._cd_data_tracks.clear()
        ss._cd_info_cache.clear()
        plain = f"9e0aa30b 11 {' '.join(map(str, ALL_OFFSETS))} {DISC_LEADOUT // 75}\n"
        mbfmt = f"11 {' '.join(map(str, ALL_OFFSETS))} {DISC_LEADOUT}\n"

        def fake_run(cmd, timeout=30):
            return mock.Mock(returncode=0, stdout=mbfmt if '--musicbrainz' in cmd else plain, stderr='')
        for p in (mock.patch.object(ss, '_run', side_effect=fake_run),
                  mock.patch.object(ss.hcd, 'read_data_tracks', return_value=[11]),
                  mock.patch.object(ss, '_cd_lookup', return_value=None)):
            p.start()
            self.addCleanup(p.stop)

    def test_toc_is_the_audio_session(self):
        toc = self.ss._cd_toc()
        self.assertEqual(toc['ntracks'], 10)
        self.assertEqual(toc['offsets'], AUDIO_OFFSETS)
        self.assertEqual(toc['leadout'], DATA_OFFSET - 11400)
        self.assertEqual(len(toc['lengths']), 10)
        self.assertEqual(toc['audio_tracks'], list(range(1, 11)))
        self.assertEqual(toc['discid'], '9e0aa30b')      # freedb id as cd-discid gives it

    def test_data_tracks_read_once_per_disc(self):
        self.ss._cd_toc()
        self.ss._cd_toc()
        self.assertEqual(self.ss.hcd.read_data_tracks.call_count, 1)

    def test_metadata_offers_only_audio_tracks(self):
        meta = self.ss._cd_metadata(self.ss._cd_toc())
        self.assertEqual([t['num'] for t in meta['tracks']], list(range(1, 11)))

    def test_mixed_mode_metadata_skips_the_leading_data_track(self):
        self.ss.hcd.read_data_tracks.return_value = [1]
        meta = self.ss._cd_metadata(self.ss._cd_toc())
        self.assertEqual([t['num'] for t in meta['tracks']], list(range(2, 12)))

    def test_tags_follow_the_place_on_the_disc(self):
        meta = {'choice': {'rel': {'artist-credit': []}, 'mbid': 'm', 'medium': 1},
                'lookup': {}, 'tracks': [{'num': 2}, {'num': 3}]}
        with mock.patch.object(self.ss, '_cd_fetch_full', return_value=None), \
                mock.patch.object(self.ss.hmeta, 'cd_tags',
                                  return_value=([], [[('T', 'data')], [('T', 'two')], [('T', 'three')]],
                                                ['', 'B', 'C'])), \
                mock.patch.object(self.ss.hmeta, 'artist_credit_text', return_value='A'):
            _album, tags, artists = self.ss._cd_tag_plan(meta, 'A')
        self.assertEqual(tags, [[('T', 'two')], [('T', 'three')]])
        self.assertEqual(artists, ['B', 'C'])


class WorkerTests(unittest.TestCase):
    """hifi-rip-cd.py, imported as a module."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            'hifi_rip_cd_enh', os.path.join(ROOT, 'distro', 'config', 'includes.chroot', 'usr',
                                            'local', 'sbin', 'hifi-rip-cd.py'))
        cls.rip = importlib.util.module_from_spec(spec)
        with mock.patch('hifi_logging.tee_stdio_to_file'):
            spec.loader.exec_module(cls.rip)

    def test_tracks_past_cdparanoias_audio_list_are_left_out(self):
        toc = {n: {'length': 1000, 'begin': 0, 'copy': False, 'pre': False, 'channels': 2}
               for n in range(1, 11)}
        tracks = [{'num': n, 'title': f'T{n}'} for n in range(1, 12)]
        kept, skipped = self.rip.audio_only(tracks, toc)
        self.assertEqual([t['num'] for t in kept], list(range(1, 11)))
        self.assertEqual(skipped, [11])
        # without a TOC nothing is guessed
        kept, skipped = self.rip.audio_only(tracks, {})
        self.assertEqual((len(kept), skipped), (11, []))

    def test_a_non_audio_last_track_keeps_the_album(self):
        """End to end through main(): cdparanoia -Q fails (no TOC to go by),
        the last track is refused as "non audio" — the album of the first
        two is still placed, with TRACKTOTAL fixed."""
        rip = self.rip
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        root = os.path.join(tmp, 'usb')
        os.makedirs(root)
        plan = {'device': '/dev/null', 'root': root, 'artist': 'A', 'album': 'B',
                'tracks': [{'num': 1, 'title': 'One'}, {'num': 2, 'title': 'Two'},
                           {'num': 3, 'title': 'Data'}],
                'options': {'format': 'wav', 'retries': 0, 'log_file': False, 'eject': False,
                            'replaygain': False}}
        plan_path = os.path.join(tmp, 'plan.json')
        with open(plan_path, 'w') as f:
            import json
            json.dump(plan, f)
        status = os.path.join(tmp, 'status.json')

        def fake_rip_track(device, num, wav, opt, expected=0, on_progress=None):
            if num == 3:
                return {'ok': False, 'error': 'Selected span contains non audio track at track 03.  Aborting.'}
            with open(wav, 'wb') as f:
                f.write(b'RIFF' + b'\0' * 100)
            return {'ok': True, 'crc': 1, 'reads': 1, 'accurate': None, 'crcs': [1]}
        with mock.patch.object(rip, 'STATUS', status), \
                mock.patch.object(rip, 'read_toc', return_value={}), \
                mock.patch.object(rip, 'rip_track', side_effect=fake_rip_track), \
                mock.patch.object(rip.hifi_cdrip, 'drive_info', return_value={}), \
                mock.patch.object(rip, 'rip_owner', return_value=None), \
                mock.patch.object(rip.hifi_cdrip, 'hand_over_tree'), \
                mock.patch.object(rip.hifi_cdrip, 'hand_over'), \
                mock.patch.object(sys, 'argv', ['hifi-rip-cd.py', plan_path]):
            rip.main()
        with open(status) as f:
            import json
            st = json.load(f)
        self.assertEqual(st['state'], 'done', st)
        self.assertEqual(st['total'], 2)
        self.assertEqual(sorted(os.listdir(st['dest'])), ['01 - One.wav', '02 - Two.wav'])


if __name__ == '__main__':
    unittest.main()
