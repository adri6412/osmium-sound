"""Tests for hifi_tags.py (the Library editor: the tags inside the music files)
and its wiring in sources_server.py and webui_server.py.

Hermetic: Lyrion is a fake, files live in a temporary folder. What needs a tool
skips cleanly without it:
  * the metaflac writer needs `metaflac`,
  * the mutagen reader/writer needs python3-mutagen (importable),
  * formats other than FLAC and DSF need `ffmpeg` to make a tiny file.
The job, journal and undo logic runs everywhere, on a fake file format.

Run with:  python3 tests/test_tags.py
"""
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)

import hifi_metadata as hm  # noqa: E402
import hifi_tags as ht  # noqa: E402

HAVE_MUTAGEN = importlib.util.find_spec('mutagen') is not None
HAVE_METAFLAC = shutil.which('metaflac') is not None
HAVE_FFMPEG = shutil.which('ffmpeg') is not None
MBID = 'e6479787-3839-4082-b133-de2e5a1bd574'
MBID2 = '15a30428-87c4-455b-b7e8-71013237fea0'


# ── tiny audio files ─────────────────────────────────────────────────
def _flac_block(btype, data, last=False):
    return bytes([(0x80 if last else 0) | btype]) + len(data).to_bytes(3, 'big') + data


def flac_bytes(comments, picture=True, padding=512, id3_prefix=False):
    """A FLAC file with metadata blocks only (no audio frames): enough for
    metaflac, mutagen and the built-in reader."""
    info = struct.pack('>HH', 4096, 4096) + b'\0' * 6 + ((44100 << 44) | (1 << 41) | (15 << 36)).to_bytes(8, 'big') \
        + b'\0' * 16
    vc = struct.pack('<I', 4) + b'test' + struct.pack('<I', len(comments))
    for key, value in comments:
        entry = f'{key}={value}'.encode('utf-8')
        vc += struct.pack('<I', len(entry)) + entry
    out = b'fLaC' + _flac_block(0, info) + _flac_block(4, vc)
    if picture:
        img = b'\x89PNG\r\n\x1a\n' + b'\0' * 20
        pic = struct.pack('>II', 3, 9) + b'image/png' + struct.pack('>IIIIII', 0, 1, 1, 24, 0, len(img)) + img
        out += _flac_block(6, pic)
    out += _flac_block(1, b'\0' * padding, last=True)
    if id3_prefix:
        body = b'TIT2' + (6).to_bytes(4, 'big') + b'\0\0' + b'\x03hello'
        out = b'ID3\x04\x00\x00' + bytes([0, 0, 0, len(body)]) + body + out
    return out


def dsf_bytes():
    data = b'\0' * 8192
    fmt = b'fmt ' + struct.pack('<QIIIIIIQII', 52, 1, 0, 2, 2, 2822400, 1, 8192 * 4, 4096, 0)
    body = fmt + b'data' + struct.pack('<Q', 12 + len(data)) + data
    return b'DSD ' + struct.pack('<QQQ', 28, 28 + len(body), 0) + body


FFMPEG_CODECS = {'mp3': ['-c:a', 'libmp3lame', '-id3v2_version', '0', '-write_xing', '0'],
                 'm4a': ['-c:a', 'aac'], 'ogg': ['-c:a', 'libvorbis'], 'opus': ['-c:a', 'libopus'],
                 'wv': ['-c:a', 'wavpack'], 'wav': ['-c:a', 'pcm_s16le'], 'aiff': ['-c:a', 'pcm_s16be']}


def ffmpeg_file(path, fmt):
    cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo', '-t', '0.2',
           '-map_metadata', '-1'] + FFMPEG_CODECS[fmt] + [path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return r.returncode == 0 and os.path.isfile(path)


# ── fakes ────────────────────────────────────────────────────────────
class FakeLyrion:
    def __init__(self, base='http://127.0.0.1:9000'):
        self.base = base
        self.albums = {}
        self.tracks = {}
        self.raw = {}
        self.artists = []
        self.mediadirs = []
        self.calls = []
        self.fail = False
        self.moved_to = None        # the album the files belong to after a rescan
        self.scanning = []          # serverstatus `rescan` answers, in order

    def base_url(self):
        return self.base

    def request(self, params, timeout=None):
        self.calls.append([str(p) for p in params])
        if self.fail:
            raise hm.LyrionError('down')
        cmd = params[0]
        args = dict(str(p).split(':', 1) for p in params[1:] if isinstance(p, str) and ':' in p)
        if cmd == 'serverstatus':
            return {'lastscan': '1', 'info total albums': len(self.albums),
                    'rescan': self.scanning.pop(0) if self.scanning else '0'}
        if cmd == 'rescan':
            return {}
        if cmd == 'pref':
            return {'_p2': list(self.mediadirs)}
        if cmd == 'tags':
            return dict(self.raw.get(int(args['track_id']), {}))
        start, count = int(params[1]), int(params[2])
        if cmd == 'albums':
            loop = list(self.albums.values())
            if 'album_id' in args:
                loop = [a for a in loop if int(a['id']) == int(args['album_id'])]
            if 'artist_id' in args:
                loop = [a for a in loop if int(a.get('artist_id') or 0) == int(args['artist_id'])]
            if 'search' in args:
                loop = [a for a in loop if args['search'].lower() in a['album'].lower()]
            return {'count': len(loop), 'albums_loop': loop[start:start + count]} if count else {'count': len(loop)}
        if cmd == 'titles' and str(args.get('search', '')).startswith("sql=tracks.url='"):
            url = args['search'][len("sql=tracks.url='"):-1].replace("''", "'")
            for aid, loop in self.tracks.items():
                for t in loop:
                    if t['url'] == url:
                        return {'count': 1, 'titles_loop': [{'id': t['id'], 'album_id': str(self.moved_to or aid)}]}
            return {'count': 0, 'titles_loop': []}
        if cmd == 'titles':
            loop = list(self.tracks.get(int(args.get('album_id', 0)), []))
            return {'count': len(loop), 'titles_loop': loop[start:start + count]} if count else {'count': len(loop)}
        if cmd == 'artists':
            loop = list(self.artists)
            return {'count': len(loop), 'artists_loop': loop[start:start + count]}
        raise AssertionError(f'unexpected {params}')


def file_url(path):
    import urllib.parse
    return 'file://' + urllib.parse.quote(path)


class JsonFormat:
    """A stand-in file format (tags as JSON) so the job, journal and undo run
    without any tag library."""

    @staticmethod
    def read_file(path, fmt):
        with open(path, encoding='utf-8') as f:
            return {'tags': json.load(f), 'other_tags': {}, 'has_picture': False}

    @staticmethod
    def write_file(path, fmt, set_, remove):
        with open(path, encoding='utf-8') as f:
            tags = json.load(f)
        for key in set(set_) | set(remove):
            tags.pop(key, None)
        tags.update({k: list(v) for k, v in set_.items()})
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(tags, f, sort_keys=True)

    @staticmethod
    def writers():
        return {fmt: True for fmt in ht.FORMATS}


# ── validation ───────────────────────────────────────────────────────
class ValidationTests(unittest.TestCase):

    def clean(self, set_=None, remove=None, track_id=1):
        return ht.clean_changes({'album_id': 7, 'changes': [{'track_id': track_id, 'set': set_ or {},
                                                             'remove': remove or []}]})

    def code(self, fn, *a, **kw):
        with self.assertRaises(ht.TagError) as ctx:
            fn(*a, **kw)
        return ctx.exception.code

    def test_whitelist_and_normalisation(self):
        album_id, changes = self.clean({'composer': ['  Roger\x00 Waters '], 'Comment': ['a\r\nb\x07']},
                                       ['isrc'])
        self.assertEqual(album_id, 7)
        self.assertEqual(changes[0]['set'], {'COMPOSER': ['Roger Waters'], 'COMMENT': ['a\nb']})
        self.assertEqual(changes[0]['remove'], ['ISRC'])
        # line breaks only survive in COMMENT
        self.assertEqual(self.clean({'TITLE': ['one\ntwo']})[1][0]['set'], {'TITLE': ['onetwo']})
        self.assertEqual(self.code(self.clean, {'REPLAYGAIN_TRACK_GAIN': ['1 dB']}), 'library.badKey')
        self.assertEqual(self.code(self.clean, None, ['LYRICS']), 'library.badKey')
        # an empty value list means "remove"
        self.assertEqual(self.clean({'GENRE': ['', ' ']})[1][0], {'track_id': 1, 'set': {}, 'remove': ['GENRE']})
        self.assertEqual(self.code(self.clean, {'GENRE': ['Rock']}, ['GENRE']), 'library.setAndRemove')

    def test_lengths_and_counts(self):
        self.assertEqual(self.code(self.clean, {'TITLE': ['x' * 1001]}), 'library.valueTooLong')
        self.clean({'COMMENT': ['x' * 4000]})
        self.assertEqual(self.code(self.clean, {'PERFORMER': [f'p{i}' for i in range(51)]}), 'library.tooManyValues')
        self.assertEqual(self.code(self.clean, {'TRACKNUMBER': ['1', '2']}), 'library.tooManyValues')
        self.assertEqual(self.code(self.clean, {'TITLE': [{'x': 1}]}), 'library.badRequest')

    def test_numbers_ids_and_flags(self):
        for ok in ('3', '3/12', '0003/0012'):
            self.clean({'TRACKNUMBER': [ok], 'DISCNUMBER': [ok]})
        for bad in ('three', '3/', '-1', '3/12/1', '12345'):
            self.assertEqual(self.code(self.clean, {'TRACKNUMBER': [bad]}), 'library.badNumber', bad)
        self.assertEqual(self.code(self.clean, {'TRACKTOTAL': ['3/12']}), 'library.badTotal')
        self.assertEqual(self.clean({'MUSICBRAINZ_ALBUMID': [MBID.upper()]})[1][0]['set'],
                         {'MUSICBRAINZ_ALBUMID': [MBID]})
        self.assertEqual(self.code(self.clean, {'MUSICBRAINZ_ARTISTID': ['nope']}), 'library.badMbid')
        self.assertEqual(self.code(self.clean, {'COMPILATION': ['yes']}), 'library.badCompilation')

    def test_request_shape(self):
        self.assertEqual(self.code(ht.clean_changes, {'changes': []}), 'library.albumRequired')
        self.assertEqual(self.code(ht.clean_changes, {'album_id': 1, 'changes': []}), 'library.nothingToChange')
        self.assertEqual(self.code(ht.clean_changes, {'album_id': 1, 'changes': [{'track_id': 1}]}),
                         'library.nothingToChange')
        dup = [{'track_id': 1, 'set': {'TITLE': ['a']}}, {'track_id': 1, 'set': {'TITLE': ['b']}}]
        self.assertEqual(self.code(ht.clean_changes, {'album_id': 1, 'changes': dup}), 'library.badRequest')
        many = [{'track_id': i, 'set': {'TITLE': ['a']}} for i in range(ht.MAX_TRACKS + 1)]
        self.assertEqual(self.code(ht.clean_changes, {'album_id': 1, 'changes': many}), 'library.tooManyTracks')
        self.assertEqual(ht.touched_keys({'TRACKNUMBER': ['1']}, ['COMMENT']), ['COMMENT', 'TRACKNUMBER', 'TRACKTOTAL'])


# ── paths ────────────────────────────────────────────────────────────
class PathTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.music = os.path.join(self.tmp, 'music')
        self.outside = os.path.join(self.tmp, 'etc')
        os.makedirs(os.path.join(self.music, 'Artist'))
        os.makedirs(self.outside)

    def tearDown(self):
        for dirpath, dirnames, filenames in os.walk(self.tmp):
            for name in filenames:
                try:
                    os.chmod(os.path.join(dirpath, name), 0o644)
                except OSError:
                    pass
        shutil.rmtree(self.tmp)

    def test_confine(self):
        roots = (self.music,)
        inside = os.path.join(self.music, 'Artist', 'a.flac')
        self.assertEqual(ht.confine(inside, roots), os.path.realpath(inside))
        self.assertEqual(ht.confine(self.music, roots), os.path.realpath(self.music))
        self.assertIsNone(ht.confine(os.path.join(self.music, '..', 'etc', 'passwd'), roots))
        self.assertIsNone(ht.confine(self.music + '-evil/a.flac', roots))
        # a symlink inside the music folder that leads outside it
        secret = os.path.join(self.outside, 'shadow.flac')
        open(secret, 'w').close()
        link = os.path.join(self.music, 'Artist', 'link.flac')
        os.symlink(secret, link)
        self.assertIsNone(ht.confine(link, roots))
        self.assertIsNone(ht.confine('', roots))

    def test_urls_and_display(self):
        path = os.path.join(self.music, 'Artist', 'Déjà vu #1.flac')
        self.assertEqual(ht.path_from_url(file_url(path)), (path, False))
        self.assertEqual(ht.path_from_url(file_url(path) + '#12.5-300.1'), (path, True))       # a cue-sheet track
        self.assertEqual(ht.path_from_url('http://radio/stream.mp3'), (None, False))
        self.assertEqual(ht.path_from_url('file://nas/share/a.flac'), (None, False))
        self.assertEqual(ht.display_path('/mnt/src/Musica/A/b.flac', ['/mnt/src', '/mnt/src/Musica']), 'A/b.flac')
        self.assertEqual(ht.display_path('/elsewhere/b.flac', ['/mnt/src']), 'b.flac')
        self.assertEqual(ht.format_of('/x/Y.FLAC'), 'flac')
        self.assertIsNone(ht.format_of('/x/y.txt'))

    def test_access_reasons(self):
        svc = ht.TagService(roots=(self.music,), lyrion=FakeLyrion(), edits_dir=self.tmp, local=True)
        writable = {fmt: True for fmt in ht.FORMATS}
        good = os.path.join(self.music, 'Artist', 'a.flac')
        open(good, 'w').close()
        self.assertEqual(svc.access(good, 'flac', writer_map=writable), (os.path.realpath(good), ''))
        self.assertEqual(svc.access(os.path.join(self.outside, 'x.flac'), 'flac', writer_map=writable),
                         (None, 'outside_sources'))
        self.assertEqual(svc.access(os.path.join(self.music, 'gone.flac'), 'flac', writer_map=writable),
                         (None, 'missing'))
        self.assertEqual(svc.access(good, 'flac', writer_map={'flac': False})[1], 'unsupported_format')
        self.assertEqual(svc.access(good, 'flac', cue=True, writer_map=writable)[1], 'unsupported_format')
        with mock.patch.object(ht, 'fs_readonly', return_value=True):
            self.assertEqual(svc.access(good, 'flac', writer_map=writable)[1], 'readonly')
        if os.geteuid() != 0:
            os.chmod(good, 0o444)
            self.assertEqual(svc.access(good, 'flac', writer_map=writable)[1], 'readonly')

    def test_this_device(self):
        self.assertTrue(ht._host_is_this_device('127.0.0.1'))
        self.assertTrue(ht._host_is_this_device('localhost'))
        self.assertTrue(ht._host_is_this_device('::1'))
        self.assertFalse(ht._host_is_this_device('192.0.2.77'))        # TEST-NET: never ours
        self.assertFalse(ht._host_is_this_device('nas.example'))


# ── reading ──────────────────────────────────────────────────────────
class ReadTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_builtin_flac_reader(self):
        path = os.path.join(self.tmp, 'a.flac')
        with open(path, 'wb') as f:
            f.write(flac_bytes([('TITLE', 'One'), ('artist', 'A'), ('ARTIST', 'B'), ('COMMENT', 'line1\nline2'),
                                ('REPLAYGAIN_TRACK_GAIN', '-6.1 dB'), ('MUSICBRAINZ_ALBUMID', MBID)]))
        model = ht.read_flac(path)
        self.assertEqual(model['tags'], {'TITLE': ['One'], 'ARTIST': ['A', 'B'], 'COMMENT': ['line1\nline2'],
                                         'MUSICBRAINZ_ALBUMID': [MBID]})
        self.assertEqual(model['other_tags'], {'REPLAYGAIN_TRACK_GAIN': ['-6.1 dB']})
        self.assertTrue(model['has_picture'])
        with open(path, 'wb') as f:
            f.write(flac_bytes([('TITLE', 'Two')], picture=False, id3_prefix=True))
        self.assertEqual(ht.read_flac(path), {'tags': {'TITLE': ['Two']}, 'other_tags': {}, 'has_picture': False})
        with open(path, 'wb') as f:
            f.write(b'not audio at all')
        with self.assertRaises(ht.FileTagError):
            ht.read_flac(path)

    def test_lyrion_dumps(self):
        # answers of a real Lyrion 9.2 (FLAC, DSF with ID3, MP4, MP3)
        flac = ht.lyrion_tags_model({'ARTIST': 'Lacuna Coil', 'VENDOR': 'Mutagen 1.45.1', 'COMPOSER': '',
                                     'ALLPICTURES': '[ HASH(0x55c2c7c30e40) ]', 'TRACKNUMBER': '3',
                                     'TRACKTOTAL': '27', 'DISCNUMBER': '1', 'DATE': '2018-11-09'})
        self.assertEqual(flac['tags'], {'ARTIST': ['Lacuna Coil'], 'TRACKNUMBER': ['3'], 'TRACKTOTAL': ['27'],
                                        'DISCNUMBER': ['1'], 'DATE': ['2018-11-09']})
        self.assertTrue(flac['has_picture'])
        self.assertEqual(flac['other_tags'], {'VENDOR': ['Mutagen 1.45.1']})
        dsf = ht.lyrion_tags_model({'TALB': 'Consign to Oblivion', 'TPOS': '1/1', 'TIT2': 'Hunab Ku', 'TSRC': '',
                                    'TPE1': 'EPICA', 'TCON': 'Other', 'TRCK': '1/12', 'TYER': '2005',
                                    'MUSICBRAINZ ALBUM ID': MBID})
        self.assertEqual(dsf['tags']['TRACKNUMBER'], ['1'])
        self.assertEqual(dsf['tags']['TRACKTOTAL'], ['12'])
        self.assertEqual(dsf['tags']['DISCTOTAL'], ['1'])
        self.assertEqual((dsf['tags']['ALBUM'], dsf['tags']['DATE'], dsf['tags']['MUSICBRAINZ_ALBUMID']),
                         (['Consign to Oblivion'], ['2005'], [MBID]))
        mp4 = ht.lyrion_tags_model({'DAY': '1976', 'ALB': 'Chocolate Kings', 'NAM': 'Acoustic Guitar Solo',
                                    'COVR': '122112', 'COVR_offset': '46813', 'AART': 'PFM', 'ART': 'P.F.M',
                                    'TRKN': '3/12', 'DISK': '2/2', 'TOO': 'Dolby'})
        self.assertEqual(mp4['tags'], {'DATE': ['1976'], 'ALBUM': ['Chocolate Kings'],
                                       'TITLE': ['Acoustic Guitar Solo'], 'ALBUMARTIST': ['PFM'],
                                       'ARTIST': ['P.F.M'], 'TRACKNUMBER': ['3'], 'TRACKTOTAL': ['12'],
                                       'DISCNUMBER': ['2'], 'DISCTOTAL': ['2']})
        self.assertTrue(mp4['has_picture'])
        self.assertEqual(mp4['other_tags'], {'TOO': ['Dolby']})


# ── writing with metaflac ────────────────────────────────────────────
@unittest.skipUnless(HAVE_METAFLAC, 'metaflac is not installed')
class MetaflacTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, 'a.flac')
        with open(self.path, 'wb') as f:
            f.write(flac_bytes([('TITLE', 'One'), ('COMMENT', 'old'), ('ENCODER', 'x'), ('ARTIST', 'A')]))
        self.patch = mock.patch.object(ht, '_disable_mutagen', True)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.tmp)

    def test_writers_without_mutagen(self):
        w = ht.writers()
        self.assertTrue(w['flac'])
        self.assertFalse(any(v for k, v in w.items() if k != 'flac'))

    def test_set_remove_preserve(self):
        ht.write_file(self.path, 'flac', {'COMPOSER': ['Roger Waters', 'David Gilmour'], 'ARTIST': ['Pink Floyd'],
                                          'COMMENT': ['two\nlines'], 'TITLE': ['Ünïcode']}, ['GENRE'])
        model = ht.read_file(self.path, 'flac')
        self.assertEqual(model['tags'], {'TITLE': ['Ünïcode'], 'ARTIST': ['Pink Floyd'],
                                         'COMPOSER': ['Roger Waters', 'David Gilmour'], 'COMMENT': ['two\nlines']})
        self.assertEqual(model['other_tags'], {'ENCODER': ['x']})       # not edited: kept
        self.assertTrue(model['has_picture'])
        ht.write_file(self.path, 'flac', {}, ['COMMENT', 'COMPOSER'])
        self.assertNotIn('COMMENT', ht.read_file(self.path, 'flac')['tags'])

    def test_failure_is_reported(self):
        with open(self.path, 'wb') as f:
            f.write(b'garbage')
        with self.assertRaises(ht.FileTagError):
            ht.write_file(self.path, 'flac', {'TITLE': ['x']}, [])


# ── writing with mutagen ─────────────────────────────────────────────
@unittest.skipUnless(HAVE_MUTAGEN, 'python3-mutagen is not importable')
class MutagenTests(unittest.TestCase):

    CHANGES = {'TITLE': ['Speak to Me'], 'ARTIST': ['Pink Floyd'], 'ALBUMARTIST': ['Pink Floyd'],
               'ALBUM': ['The Dark Side of the Moon'], 'TRACKNUMBER': ['1'], 'TRACKTOTAL': ['10'],
               'DISCNUMBER': ['1'], 'DISCTOTAL': ['2'], 'DATE': ['1973-03-01'], 'GENRE': ['Rock', 'Progressive'],
               'COMPOSER': ['Nick Mason'], 'CONDUCTOR': ['Nobody'], 'LYRICIST': ['Roger Waters'],
               'PERFORMER': ['David Gilmour (guitar)', 'Richard Wright (keyboard)'], 'PRODUCER': ['Pink Floyd'],
               'ENGINEER': ['Alan Parsons'], 'LABEL': ['Harvest'], 'CATALOGNUMBER': ['SHVL 804'],
               'COMMENT': ['first\nsecond'], 'COMPILATION': ['0'], 'RELEASETYPE': ['album'], 'ISRC': ['GBN9Y1100001'],
               'MUSICBRAINZ_ALBUMID': [MBID], 'MUSICBRAINZ_ARTISTID': [MBID2, MBID], 'MUSICBRAINZ_TRACKID': [MBID2],
               'MUSICBRAINZ_RELEASEGROUPID': [MBID], 'MUSICBRAINZ_RELEASETRACKID': [MBID2],
               'MUSICBRAINZ_ALBUMARTISTID': [MBID2]}

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def make(self, fmt):
        path = os.path.join(self.tmp, 'a.' + fmt)
        if fmt == 'flac':
            with open(path, 'wb') as f:
                f.write(flac_bytes([('TITLE', 'old'), ('ENCODER', 'x')]))
            return path
        if fmt == 'dsf':
            with open(path, 'wb') as f:
                f.write(dsf_bytes())
            return path
        if not HAVE_FFMPEG:
            self.skipTest('ffmpeg is not installed')
        if not ffmpeg_file(path, fmt):
            self.skipTest(f'this ffmpeg cannot make {fmt}')
        return path

    def roundtrip(self, fmt):
        path = self.make(fmt)
        before = ht.read_file(path, fmt)
        ht.write_file(path, fmt, self.CHANGES, [])
        after = ht.read_file(path, fmt)
        self.assertEqual(after['tags'], self.CHANGES, fmt)
        # what was there and not edited is still there
        for key, values in before['other_tags'].items():
            self.assertEqual(after['other_tags'].get(key), values, f'{fmt}: {key} lost')
        # a partial change leaves the rest alone; removing works
        ht.write_file(path, fmt, {'TRACKTOTAL': ['12'], 'COMPOSER': ['Roger Waters']}, ['COMMENT', 'CONDUCTOR'])
        again = ht.read_file(path, fmt)['tags']
        want = dict(self.CHANGES, TRACKTOTAL=['12'], COMPOSER=['Roger Waters'])
        del want['COMMENT'], want['CONDUCTOR']
        self.assertEqual(again, want, fmt)
        return path

    def test_flac(self):
        path = self.roundtrip('flac')
        self.assertTrue(ht.read_file(path, 'flac')['has_picture'])            # the picture block survives
        self.assertEqual(ht.read_file(path, 'flac')['other_tags'], {'ENCODER': ['x']})

    def test_mp3_gets_id3v24(self):
        path = self.make('mp3')
        import mutagen
        self.assertIsNone(mutagen.File(path).tags)                          # no ID3 header at all
        self.roundtrip('mp3')
        audio = mutagen.File(path)
        self.assertEqual(audio.tags.version[:2], (2, 4))
        self.assertEqual(str(audio.tags['TRCK'].text[0]), '1/12')
        self.assertEqual(audio.tags['UFID:http://musicbrainz.org'].data.decode(), MBID2)
        self.assertEqual(list(audio.tags['TXXX:MusicBrainz Album Id'].text), [MBID])

    def test_id3_date_check(self):
        svc = ht.TagService(roots=(self.tmp,), lyrion=FakeLyrion(), edits_dir=self.tmp, local=True)
        path = self.make('dsf')
        svc.lyrion.albums[1] = {'id': 1, 'album': 'A'}
        svc.lyrion.tracks[1] = [{'id': 5, 'url': file_url(path)}]
        with self.assertRaises(ht.TagError) as ctx:
            svc.start_tags({'album_id': 1, 'changes': [{'track_id': 5, 'set': {'DATE': ['March 1973']}}]})
        self.assertEqual(ctx.exception.code, 'library.badDate')

    def test_m4a(self):
        path = self.roundtrip('m4a')
        import mutagen
        tags = mutagen.File(path).tags
        self.assertEqual(tags['trkn'], [(1, 12)])
        self.assertIn('----:com.apple.iTunes:MusicBrainz Album Id', tags)

    def test_ogg(self):
        self.roundtrip('ogg')

    def test_opus(self):
        self.roundtrip('opus')

    def test_wavpack(self):
        self.roundtrip('wv')

    def test_wav(self):
        self.roundtrip('wav')

    def test_aiff(self):
        self.roundtrip('aiff')

    def test_dsf(self):
        self.roundtrip('dsf')

    def test_other_tags_and_pictures_are_kept(self):
        path = self.make('mp3')
        import mutagen
        from mutagen import id3
        audio = mutagen.File(path)
        audio.add_tags()
        audio.tags.add(id3.APIC(encoding=3, mime='image/png', type=3, desc='', data=b'\x89PNG....'))
        audio.tags.add(id3.TXXX(encoding=3, desc='REPLAYGAIN_TRACK_GAIN', text=['-6.1 dB']))
        audio.tags.add(id3.TIPL(encoding=3, people=[['mix', 'Chris Thomas']]))
        audio.tags.add(id3.COMM(encoding=3, lang='eng', desc='iTunNORM', text=['0000']))
        audio.save()
        ht.write_file(path, 'mp3', {'TITLE': ['t'], 'COMMENT': ['c']}, [])
        model = ht.read_file(path, 'mp3')
        self.assertTrue(model['has_picture'])
        self.assertEqual(model['tags'], {'TITLE': ['t'], 'COMMENT': ['c']})
        self.assertEqual(model['other_tags']['TXXX:REPLAYGAIN_TRACK_GAIN'], ['-6.1 dB'])
        self.assertEqual(model['other_tags']['TIPL'], ['mix: Chris Thomas'])
        self.assertEqual(model['other_tags']['COMM:iTunNORM:eng'], ['0000'])
        ht.write_file(path, 'mp3', {}, ['COMMENT'])
        self.assertEqual(ht.read_file(path, 'mp3')['other_tags']['COMM:iTunNORM:eng'], ['0000'])


# ── the service: listing, reading, jobs, journal, undo ───────────────
class ServiceTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.music = os.path.join(self.tmp, 'music')
        self.edits = os.path.join(self.tmp, 'metadata-edits')
        os.makedirs(os.path.join(self.music, 'Pink Floyd', 'DSOTM'))
        self.lyrion = FakeLyrion()
        self.lyrion.mediadirs = [self.music]
        self.local = {'yes': True}
        self.svc = ht.TagService(roots=(self.music,), lyrion=self.lyrion, edits_dir=self.edits,
                                 local=lambda: self.local['yes'])
        self.paths = []
        tracks = []
        for n in (1, 2, 3):
            path = os.path.join(self.music, 'Pink Floyd', 'DSOTM', f'0{n} Track.flac')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({'TITLE': [f'Track {n}'], 'TRACKNUMBER': [str(n)], 'COMMENT': ['old']}, f)
            self.paths.append(path)
            tracks.append({'id': 100 + n, 'title': f'Track {n}', 'url': file_url(path), 'tracknum': str(n),
                           'disc': '1', 'duration': 60.5, 'type': 'flc'})
        self.lyrion.albums[704] = {'id': 704, 'album': 'The Dark Side of the Moon', 'artist': 'Pink Floyd',
                                   'artist_id': 977, 'year': 1973, 'artwork_track_id': 'abc123', 'compilation': 0,
                                   'disccount': 1}
        self.lyrion.tracks[704] = tracks
        self.lyrion.artists = [{'id': 977, 'artist': 'Pink Floyd'}]
        self.fmt = mock.patch.multiple(ht, read_file=JsonFormat.read_file, write_file=JsonFormat.write_file,
                                       writers=JsonFormat.writers)
        self.fmt.start()

    def tearDown(self):
        self.fmt.stop()
        self.svc.wait()
        shutil.rmtree(self.tmp)

    def tags_of(self, i):
        with open(self.paths[i], encoding='utf-8') as f:
            return json.load(f)

    def run_job(self, body, undo=False):
        out = (self.svc.undo if undo else self.svc.start_tags)(body)
        self.assertTrue(self.svc.wait())
        return out['job_id']

    def test_status_and_listing(self):
        s = self.svc.status()
        self.assertEqual((s['available'], s['local'], s['reason']), (True, True, ''))
        self.assertEqual(set(s['writers']), set(ht.FORMATS))
        self.local['yes'] = False
        self.assertEqual(self.svc.status()['reason'], 'remote_server')
        self.lyrion.fail = True
        self.assertEqual(self.svc.status()['available'], False)
        self.lyrion.fail = False
        out = self.svc.albums('dark', 0, 60)
        self.assertEqual(out['total'], 1)
        self.assertEqual(out['albums'][0], {'album_id': 704, 'title': 'The Dark Side of the Moon',
                                            'artist': 'Pink Floyd', 'artist_id': 977, 'year': 1973,
                                            'artwork_track_id': 'abc123', 'track_count': 3, 'compilation': False})
        self.assertEqual(self.svc.albums('', 0, 60, artist_id=977)['total'], 1)
        # one artist's albums come by year, then title
        albums_calls = [c for c in self.lyrion.calls if c[0] == 'albums' and c[2] != '0']
        self.assertIn('sort:yearalbum', albums_calls[-1])
        self.assertIn('sort:album', albums_calls[-2])
        self.assertEqual(self.svc.artists('', 0, 100),
                         {'total': 1, 'artists': [{'artist_id': 977, 'name': 'Pink Floyd', 'album_count': 1}]})
        # counts are asked once per scan
        n = sum(1 for c in self.lyrion.calls if c[0] == 'titles')
        self.svc.albums('', 0, 60)
        self.assertEqual(sum(1 for c in self.lyrion.calls if c[0] == 'titles'), n)

    def test_album_reading_and_reasons(self):
        outside = os.path.join(self.tmp, 'elsewhere.flac')
        with open(outside, 'w') as f:
            f.write('{}')
        self.lyrion.tracks[704].append({'id': 200, 'url': file_url(outside), 'tracknum': '4', 'disc': '1'})
        self.lyrion.tracks[704].append({'id': 201, 'url': file_url(self.paths[0]) + '#10.0-20.0', 'tracknum': '5'})
        self.lyrion.tracks[704].append({'id': 202, 'url': file_url(os.path.join(self.music, 'gone.mp3')),
                                        'tracknum': '6'})
        self.lyrion.raw[200] = {'TITLE': 'From Lyrion', 'TRCK': '4/6'}
        out = self.svc.album(704)
        self.assertEqual(out['album'], {'album_id': 704, 'title': 'The Dark Side of the Moon', 'artist': 'Pink Floyd',
                                        'artist_id': 977, 'year': 1973, 'artwork_track_id': 'abc123',
                                        'compilation': False, 'disc_count': 1})
        self.assertEqual((out['editable'], out['reason']), (True, 'mixed'))
        rows = {r['track_id']: r for r in out['tracks']}
        first = rows[101]
        self.assertEqual((first['file'], first['format'], first['writable'], first['reason']),
                         ('Pink Floyd/DSOTM/01 Track.flac', 'flac', True, ''))
        self.assertEqual(first['tags'], {'TITLE': ['Track 1'], 'TRACKNUMBER': ['1'], 'COMMENT': ['old']})
        self.assertEqual(first['duration'], 60.5)
        self.assertEqual(set(first), {'track_id', 'file', 'format', 'writable', 'reason', 'tags', 'other_tags',
                                      'has_picture', 'duration'})
        self.assertEqual((rows[200]['reason'], rows[200]['tags']),
                         ('outside_sources', {'TITLE': ['From Lyrion'], 'TRACKNUMBER': ['4'], 'TRACKTOTAL': ['6']}))
        self.assertEqual(rows[201]['reason'], 'unsupported_format')        # cue track: never written
        self.assertEqual(rows[202]['reason'], 'missing')
        self.assertEqual([r['track_id'] for r in out['tracks']], [101, 102, 103, 200, 201, 202])
        # another server's library: nothing is written, tags come from Lyrion
        self.local['yes'] = False
        remote = self.svc.album(704)
        self.assertEqual((remote['editable'], remote['reason']), (False, 'remote_server'))
        self.assertTrue(all(r['reason'] == 'remote_server' and not r['writable'] for r in remote['tracks']))
        with self.assertRaises(ht.TagError) as ctx:
            self.svc.start_tags({'album_id': 704, 'changes': [{'track_id': 101, 'set': {'TITLE': ['x']}}]})
        self.assertEqual((ctx.exception.code, ctx.exception.status), ('library.remoteServer', 409))
        with self.assertRaises(ht.TagError) as ctx:
            self.svc.album(9999)
        self.assertEqual(ctx.exception.status, 404)

    def test_refusals(self):
        def refused(changes, album_id=704):
            with self.assertRaises(ht.TagError) as ctx:
                self.svc.start_tags({'album_id': album_id, 'changes': changes})
            return ctx.exception
        self.assertEqual(refused([{'track_id': 999, 'set': {'TITLE': ['x']}}]).code, 'library.trackNotInAlbum')
        self.assertEqual(refused([{'track_id': 101, 'set': {'TITLE': ['x']}}], album_id=1).code,
                         'library.unknownAlbum')
        link = os.path.join(self.music, 'link.flac')
        os.symlink(os.path.join(self.tmp, 'outside.flac'), link)
        open(os.path.join(self.tmp, 'outside.flac'), 'w').close()
        self.lyrion.tracks[704].append({'id': 300, 'url': file_url(link)})
        e = refused([{'track_id': 300, 'set': {'TITLE': ['x']}}])
        self.assertEqual((e.code, e.status, e.fields['reason']), ('library.trackNotWritable', 409, 'outside_sources'))
        with mock.patch.object(ht, 'fs_readonly', return_value=True):
            self.assertEqual(refused([{'track_id': 101, 'set': {'TITLE': ['x']}}]).fields['reason'], 'readonly')
        # one job at a time
        self.svc._job = {'job_id': 'x' * 10}
        try:
            self.assertEqual(refused([{'track_id': 101, 'set': {'TITLE': ['x']}}]).code, 'library.busy')
        finally:
            self.svc._job = None
        self.assertEqual(os.listdir(self.edits) if os.path.isdir(self.edits) else [], [])   # nothing started

    def test_job_journal_and_undo(self):
        job_id = self.run_job({'album_id': 704, 'changes': [
            {'track_id': 101, 'set': {'COMPOSER': ['Roger Waters'], 'TRACKNUMBER': ['1/10']}, 'remove': ['COMMENT']},
            {'track_id': 102, 'set': {'COMMENT': ['new']}}]})
        self.assertEqual(self.tags_of(0), {'TITLE': ['Track 1'], 'TRACKNUMBER': ['1/10'], 'COMPOSER': ['Roger Waters']})
        self.assertEqual(self.tags_of(1)['COMMENT'], ['new'])
        job = self.svc.job(job_id)
        self.assertEqual({k: job[k] for k in ('state', 'done', 'total', 'errors', 'rescan', 'undoable')},
                         {'state': 'done', 'done': 2, 'total': 2, 'errors': [], 'rescan': 'started', 'undoable': True})
        self.assertIn(['rescan'], self.lyrion.calls)
        # the journal: previous values of the touched keys (None = absent), the file's state after
        with open(os.path.join(self.edits, 'tag-jobs', job_id + '.json'), encoding='utf-8') as f:
            journal = json.load(f)
        entry = journal['files'][0]
        self.assertEqual(entry['before'], {'COMMENT': ['old'], 'COMPOSER': None, 'TRACKNUMBER': ['1'],
                                           'TRACKTOTAL': None})
        st = os.stat(self.paths[0])
        self.assertEqual((entry['size'], entry['mtime_ns'], entry['written']), (st.st_size, st.st_mtime_ns, True))
        hist = self.svc.history()['jobs']
        self.assertEqual(hist[0], {'job_id': job_id, 'when': journal['when'], 'album_id': 704,
                                   'album': 'The Dark Side of the Moon', 'tracks': 2, 'state': 'done',
                                   'undone': False, 'undo_of': None})
        # undo puts back exactly what was there
        undo_id = self.run_job({'job_id': job_id}, undo=True)
        self.assertEqual(self.tags_of(0), {'TITLE': ['Track 1'], 'TRACKNUMBER': ['1'], 'COMMENT': ['old']})
        self.assertEqual(self.tags_of(1)['COMMENT'], ['old'])
        self.assertTrue(self.svc.job(job_id)['undone'])
        self.assertFalse(self.svc.job(job_id)['undoable'])
        self.assertEqual(self.svc.job(undo_id)['undo_of'], job_id)
        with self.assertRaises(ht.TagError) as ctx:
            self.svc.undo({'job_id': job_id})
        self.assertEqual(ctx.exception.code, 'library.notUndoable')
        # and the undo itself can be undone
        self.run_job({'job_id': undo_id}, undo=True)
        self.assertEqual(self.tags_of(0)['COMPOSER'], ['Roger Waters'])
        self.assertEqual([j['job_id'] for j in self.svc.history()['jobs']][1:], [undo_id, job_id])

    def test_album_rename_is_followed_after_the_rescan(self):
        class Meta:
            calls = []

            def album_renamed(self, before, album_id):
                self.calls.append((before, album_id))
        clock = {'t': 0.0}
        self.svc._metadata = Meta()
        self.svc._monotonic = lambda: clock['t']
        self.svc._sleep = lambda s: clock.__setitem__('t', clock['t'] + s)
        self.lyrion.moved_to = 750
        self.lyrion.scanning = ['1', '1', '0']
        job_id = self.run_job({'album_id': 704, 'changes': [
            {'track_id': n, 'set': {'ALBUM': ["The Dark Side of the Moon (2011)"]}} for n in (101, 102, 103)]})
        for _ in range(500):
            if self.svc.job(job_id)['follow'] == 'done':
                break
            time.sleep(0.01)
        job = self.svc.job(job_id)
        self.assertEqual((job['follow'], job['new_album_id']), ('done', 750))
        self.assertEqual(Meta.calls, [({'album_id': 704, 'title': 'The Dark Side of the Moon', 'artist': 'Pink Floyd',
                                        'track_count': 3}, 750)])
        self.assertTrue(any(str(p).startswith("search:sql=tracks.url='") for call in self.lyrion.calls for p in call))
        # a job that touches no album tag has nothing to follow
        other = self.run_job({'album_id': 704, 'changes': [{'track_id': 101, 'set': {'COMMENT': ['x']}}]})
        self.assertIsNone(self.svc.job(other)['follow'])
        # quotes in a file URL are doubled for Lyrion's SQL
        self.lyrion.tracks[704][0]['url'] = "file:///music/it's.flac"
        self.assertEqual(self.svc.album_of_url("file:///music/it's.flac"), 750)
        self.assertIsNone(self.svc.album_of_url(''))

    def test_undo_refuses_changed_files_unless_forced(self):
        job_id = self.run_job({'album_id': 704, 'changes': [{'track_id': 101, 'set': {'GENRE': ['Rock']}},
                                                            {'track_id': 102, 'set': {'GENRE': ['Rock']}}]})
        JsonFormat.write_file(self.paths[1], 'flac', {'GENRE': ['Jazz']}, [])      # somebody else, later
        st = os.stat(self.paths[1])
        os.utime(self.paths[1], ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
        with self.assertRaises(ht.TagError) as ctx:
            self.svc.undo({'job_id': job_id})
        self.assertEqual((ctx.exception.code, ctx.exception.status, ctx.exception.fields['changed']),
                         ('library.changed_since', 409, [102]))
        self.assertEqual(self.tags_of(1)['GENRE'], ['Jazz'])                    # nothing touched
        self.run_job({'job_id': job_id, 'force': True}, undo=True)
        self.assertNotIn('GENRE', self.tags_of(0))
        self.assertNotIn('GENRE', self.tags_of(1))

    def test_write_errors_are_listed(self):
        def broken(path, fmt, set_, remove):
            if path == self.paths[1]:
                raise ht.FileTagError('disk on fire')
            JsonFormat.write_file(path, fmt, set_, remove)
        with mock.patch.object(ht, 'write_file', broken):
            job_id = self.run_job({'album_id': 704, 'changes': [{'track_id': 101, 'set': {'GENRE': ['Rock']}},
                                                                {'track_id': 102, 'set': {'GENRE': ['Rock']}}]})
        job = self.svc.job(job_id, 'it')
        self.assertEqual(job['state'], 'done')
        self.assertEqual(job['errors'], [{'track_id': 102, 'code': 'library.writeFailed',
                                          'message': 'Impossibile scrivere i tag: disk on fire'}])
        self.assertTrue(job['undoable'])
        with mock.patch.object(ht, 'write_file', side_effect=ht.FileTagError('no')):
            job_id = self.run_job({'album_id': 704, 'changes': [{'track_id': 101, 'set': {'GENRE': ['Pop']}}]})
        job = self.svc.job(job_id)
        self.assertEqual((job['state'], job['rescan'], job['undoable']), ('error', 'skipped', False))

    def test_interrupted_job_is_recovered_and_undone_by_content(self):
        job_id = self.run_job({'album_id': 704, 'changes': [{'track_id': 101, 'set': {'GENRE': ['Rock']}},
                                                            {'track_id': 102, 'set': {'GENRE': ['Rock']}}]})
        path = os.path.join(self.edits, 'tag-jobs', job_id + '.json')
        with open(path, encoding='utf-8') as f:
            doc = json.load(f)
        # as if the service stopped after writing the files but before saving that
        doc['state'] = 'running'
        for entry in doc['files']:
            for k in ('written', 'size', 'mtime_ns'):
                entry.pop(k, None)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(doc, f)
        svc = ht.TagService(roots=(self.music,), lyrion=self.lyrion, edits_dir=self.edits, local=True)
        job = svc.job(job_id)
        self.assertEqual(job['state'], 'error')
        self.assertEqual(job['errors'][-1]['code'], 'library.interrupted')
        self.assertTrue(job['undoable'])
        svc.undo({'job_id': job_id})
        svc.wait()
        self.assertNotIn('GENRE', self.tags_of(0))

    def test_history_keeps_the_last_50(self):
        jobs_dir = os.path.join(self.edits, 'tag-jobs')
        os.makedirs(jobs_dir)
        for i in range(60):
            with open(os.path.join(jobs_dir, f'old-{i:04d}.json'), 'w', encoding='utf-8') as f:
                json.dump({'job_id': f'old-{i:04d}', 'when': 1000 + i, 'state': 'done', 'files': []}, f)
        self.run_job({'album_id': 704, 'changes': [{'track_id': 101, 'set': {'GENRE': ['Rock']}}]})
        names = os.listdir(jobs_dir)
        self.assertEqual(len([n for n in names if n.endswith('.json')]), ht.JOBS_KEEP)
        self.assertNotIn('old-0000.json', names)
        self.assertEqual(len(self.svc.history()['jobs']), ht.JOBS_KEEP)

    def test_job_ids_are_checked(self):
        for bad in ('../../etc/passwd', '', 'a b', 'x' * 100):
            with self.assertRaises(ht.TagError):
                self.svc.job(bad)
            with self.assertRaises(ht.TagError):
                self.svc.undo({'job_id': bad})

    def test_cover_passthrough(self):
        class Resp:
            def __init__(self, body, ctype, cache):
                self.body, self.headers = body, {'Content-Type': ctype, 'Cache-Control': cache}

            def read(self, n=-1):
                return self.body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        placeholder = b'\x89PNG placeholder'
        seen = []

        def urlopen(req, timeout=None):
            seen.append(req.full_url)
            if '/music/abc123/' in req.full_url:
                return Resp(b'\xff\xd8JPEG', 'image/jpeg', 'max-age=31536000')
            return Resp(placeholder, 'image/png', 'no-cache')
        self.svc._urlopen = urlopen
        self.assertEqual(self.svc.cover('abc123', 300), (b'\xff\xd8JPEG', 'image/jpeg'))
        self.assertEqual(seen[0], 'http://127.0.0.1:9000/music/abc123/cover_300x300_o')
        self.assertIsNone(self.svc.cover('5972', 300))                         # Lyrion's "no art" image
        self.assertIsNone(self.svc.cover('../x', 300))


@unittest.skipUnless(HAVE_MUTAGEN or HAVE_METAFLAC, 'neither python3-mutagen nor metaflac is available')
class RealFlacJobTests(unittest.TestCase):
    """A whole job and its undo on a real FLAC file, with whichever writer
    this machine has (mutagen first, as on a device that has it)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, 'music', 'a.flac')
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, 'wb') as f:
            f.write(flac_bytes([('TITLE', 'One'), ('COMMENT', 'old'), ('REPLAYGAIN_TRACK_GAIN', '-6.1 dB')]))
        self.lyrion = FakeLyrion()
        self.lyrion.albums[1] = {'id': 1, 'album': 'A'}
        self.lyrion.tracks[1] = [{'id': 7, 'url': file_url(self.path), 'tracknum': '1'}]
        self.svc = ht.TagService(roots=(os.path.join(self.tmp, 'music'),), lyrion=self.lyrion,
                                 edits_dir=os.path.join(self.tmp, 'edits'), local=True)

    def tearDown(self):
        self.svc.wait()
        shutil.rmtree(self.tmp)

    def test_job_and_undo(self):
        before = ht.read_file(self.path, 'flac')
        row = self.svc.album(1)['tracks'][0]
        self.assertEqual((row['writable'], row['tags'], row['has_picture']), (True, before['tags'], True))
        job = self.svc.start_tags({'album_id': 1, 'changes': [{'track_id': 7, 'set': {'COMPOSER': ['X', 'Y']},
                                                               'remove': ['COMMENT']}]})
        self.svc.wait()
        self.assertEqual(self.svc.job(job['job_id'])['state'], 'done')
        after = ht.read_file(self.path, 'flac')
        self.assertEqual(after['tags'], {'TITLE': ['One'], 'COMPOSER': ['X', 'Y']})
        self.assertEqual((after['other_tags'], after['has_picture']), (before['other_tags'], True))
        self.svc.undo({'job_id': job['job_id']})
        self.svc.wait()
        self.assertEqual(ht.read_file(self.path, 'flac'), before)


# ── HTTP ─────────────────────────────────────────────────────────────
class RoutesTests(unittest.TestCase):

    def test_routes_errors_and_auth(self):
        from flask import Flask, jsonify
        app = Flask(__name__)
        allowed = {'yes': True}
        calls = []

        class Svc:
            def status(self):
                return {'available': True, 'local': True, 'writers': {}, 'mutagen': False, 'reason': ''}

            def albums(self, q, offset, limit, artist_id):
                calls.append(('albums', q, offset, limit, artist_id))
                return {'total': 0, 'albums': []}

            def cover(self, cover_id, size):
                return (b'\xff\xd8', 'image/jpeg') if cover_id == 'ok' else None

            def start_tags(self, body):
                if body.get('album_id') == 1:
                    raise ht.TagError('library.trackNotWritable', 409, track_id=5, reason='readonly')
                return {'job_id': 'job-123456'}

            def album(self, album_id):
                raise hm.LyrionError('down')

        svc = Svc()
        ht.init_app(app, lambda: None if allowed['yes'] else (jsonify({'success': False}), 401),
                    service_getter=lambda: svc)
        c = app.test_client()
        self.assertEqual(c.get('/api/library/status').get_json()['local'], True)
        c.get('/api/library/albums?q=dark&offset=5&limit=9999&artist_id=3')
        self.assertEqual(calls[-1], ('albums', 'dark', 5, 500, 3))
        r = c.get('/api/library/cover/ok?size=300')
        self.assertEqual((r.status_code, r.mimetype, r.data), (200, 'image/jpeg', b'\xff\xd8'))
        r = c.get('/api/library/cover/none', headers={'X-UI-Lang': 'it'})
        self.assertEqual((r.status_code, r.get_json()['code'], r.get_json()['message']),
                         (404, 'library.noCover', 'Nessuna copertina.'))
        self.assertEqual(c.post('/api/library/album/tags', json={'album_id': 2}).get_json(), {'job_id': 'job-123456'})
        r = c.post('/api/library/album/tags', json={'album_id': 1}, headers={'X-UI-Lang': 'it'})
        body = r.get_json()
        self.assertEqual((r.status_code, body['success'], body['code'], body['reason'], body['track_id']),
                         (409, False, 'library.trackNotWritable', 'readonly', 5))
        self.assertIn('sola lettura', body['message'])
        self.assertEqual(c.get('/api/library/album?album_id=x').status_code, 400)
        self.assertEqual(c.get('/api/library/album?album_id=3').status_code, 502)
        self.assertEqual(c.get('/api/library/job?id=../x').status_code, 404)
        allowed['yes'] = False
        self.assertEqual(c.get('/api/library/status').status_code, 401)

    def test_sources_server_mounts_the_routes(self):
        with mock.patch('hifi_logging.tee_stdio_to_file'):
            import sources_server
        rules = {r.rule for r in sources_server.app.url_map.iter_rules()}
        for path in ('/api/library/status', '/api/library/albums', '/api/library/artists',
                     '/api/library/cover/<cover_id>', '/api/library/album', '/api/library/album/tags',
                     '/api/library/job', '/api/library/history', '/api/library/undo'):
            self.assertIn(path, rules)
        svc = ht.get_service(sources_server.ALLOWED_LOCAL_ROOTS)
        self.assertEqual(svc.roots, tuple(sources_server.ALLOWED_LOCAL_ROOTS))

    def test_webui_proxy_and_page(self):
        dist = tempfile.mkdtemp()
        try:
            with open(os.path.join(dist, 'index.html'), 'w') as f:
                f.write('ADMIN')
            with open(os.path.join(dist, 'library.html'), 'w') as f:
                f.write('LIBRARY')
            with mock.patch('hifi_logging.tee_stdio_to_file'):
                import webui_server as ws
            c = ws.app.test_client()
            with mock.patch.object(ws, 'DIST_DIR', dist), mock.patch.object(ws, '_provisioning', return_value=False):
                with c.get('/library') as r:
                    self.assertEqual(r.data, b'LIBRARY')
                r = c.get('/library/?x=1')
                self.assertEqual((r.status_code, r.headers['Location']), (302, '/library?x=1'))
                with c.get('/') as r:
                    self.assertEqual(r.data, b'ADMIN')
                with mock.patch.object(ws, '_logged_in', return_value=False):
                    self.assertEqual(c.get('/api/system/library/status').status_code, 401)
                with mock.patch.object(ws, '_logged_in', return_value=True), \
                        mock.patch.object(ws, '_forward_to_sources', return_value=('ok', 200)) as fwd:
                    c.get('/api/system/library/cover/abc?size=300')
                    fwd.assert_called_with('/api/library/cover/abc')
            with mock.patch.object(ws, 'DIST_DIR', dist), mock.patch.object(ws, '_provisioning', return_value=True):
                r = c.get('/library')
                self.assertEqual((r.status_code, r.headers['Location']), (302, '/'))
        finally:
            shutil.rmtree(dist)


if __name__ == '__main__':
    unittest.main(verbosity=2)
