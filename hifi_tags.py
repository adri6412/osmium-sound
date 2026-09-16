#!/usr/bin/env python3
"""Osmium Sound — the tags inside the music files, for the Library editor.

sources_server.py mounts the /api/library/* routes from here (init_app,
behind its pairing check); the web admin reaches them with its session as the
gate through webui_server's /api/system/library/*. What they do:

  * browse the library (Lyrion's albums and artists, covers passed through on
    the same origin — the admin page may be HTTPS, Lyrion is plain HTTP),
  * read the tags of an album's files,
  * write corrections as ONE background job at a time. Before a file is
    written, the values it had for the keys being changed are journaled in
    /var/lib/hifi-player/metadata-edits/tag-jobs/<job_id>.json (the last 50
    jobs are kept), with the file's size and mtime after the write, so a job
    can be undone exactly and an undo can tell when a file changed again.

🚨 Files are touched only when this device uses its OWN Lyrion (only then are
the paths in its database paths on this machine), only below the music roots
sources_server confines every other file operation to (ALLOWED_LOCAL_ROOTS,
passed in by init_app), symlinks resolved, never on a read-only mount, and
never for a track cut out of a bigger file by a cue sheet (tags are per file:
changing one would change them all). Embedded pictures and every tag that is
not being changed are preserved. Lyrion's incremental rescan, which picks the
changes up, keys on the file's mtime, so the mtime is left to change.

Writers: python3-mutagen when it is importable (FLAC, MP3/ID3v2.4, MP4/ALAC,
Ogg Vorbis/Opus, WavPack/APE/Musepack, DSF/DSDIFF/WAV/AIFF with ID3), else
`metaflac` for FLAC. A format with no writer is still shown, read-only, from
the file when it can be parsed here (FLAC always is) or from Lyrion's own
reading of the tags (`tags 0 200 track_id:N`). Nothing is vendored: mutagen
comes from the Debian package.

Tag vocabulary: Vorbis-comment style upper-case keys (EDITABLE_KEYS), every
value a list of strings. The per-format mapping (ID3 frames and TXXX, MP4
atoms and iTunes freeform atoms, APEv2 item names) follows what MusicBrainz
Picard writes, so the files stay readable by Lyrion and by Picard.
"""
import concurrent.futures
import copy
import hashlib
import importlib
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import hifi_metadata as hm
from hifi_i18n import t as _t

# ── configuration ────────────────────────────────────────────────────
EDITS_DIR = '/var/lib/hifi-player/metadata-edits'
JOBS_SUBDIR = 'tag-jobs'
JOBS_KEEP = 50
# Where local music may live when init_app is not told (sources_server passes
# its own ALLOWED_LOCAL_ROOTS, which is the list that counts).
DEFAULT_ROOTS = ('/data/music', '/mnt', '/media', '/srv', '/home')

EDITABLE_KEYS = (
    'TITLE', 'ARTIST', 'ALBUMARTIST', 'ALBUM', 'TRACKNUMBER', 'TRACKTOTAL', 'DISCNUMBER', 'DISCTOTAL', 'DATE',
    'ORIGINALDATE', 'GENRE', 'COMPOSER', 'CONDUCTOR', 'LYRICIST', 'ARRANGER', 'BAND', 'PERFORMER', 'PRODUCER',
    'ENGINEER', 'MIXER', 'REMIXER', 'LABEL', 'CATALOGNUMBER', 'COMMENT', 'COMPILATION', 'RELEASETYPE', 'ISRC',
    'MUSICBRAINZ_ALBUMID', 'MUSICBRAINZ_ALBUMARTISTID', 'MUSICBRAINZ_ARTISTID', 'MUSICBRAINZ_TRACKID',
    'MUSICBRAINZ_RELEASEGROUPID', 'MUSICBRAINZ_RELEASETRACKID',
)
EDITABLE = frozenset(EDITABLE_KEYS)
PAIRS = (('TRACKNUMBER', 'TRACKTOTAL'), ('DISCNUMBER', 'DISCTOTAL'))
NUMBER_KEYS = frozenset(p[0] for p in PAIRS)
TOTAL_KEYS = frozenset(p[1] for p in PAIRS)
MBID_KEYS = frozenset(k for k in EDITABLE_KEYS if k.startswith('MUSICBRAINZ_'))
SINGLE_KEYS = NUMBER_KEYS | TOTAL_KEYS | {'COMPILATION', 'MUSICBRAINZ_ALBUMID', 'MUSICBRAINZ_TRACKID',
                                         'MUSICBRAINZ_RELEASEGROUPID', 'MUSICBRAINZ_RELEASETRACKID'}
DATE_KEYS = frozenset(('DATE', 'ORIGINALDATE'))
# Tags that decide which Lyrion album a file belongs to: changing one gives
# the album a new id after the rescan (and a new metadata fingerprint), so the
# job follows the files to their album afterwards.
ALBUM_KEYS = frozenset(('ALBUM', 'ALBUMARTIST', 'ARTIST', 'COMPILATION', 'MUSICBRAINZ_ALBUMID',
                        'MUSICBRAINZ_ALBUMARTISTID'))
FOLLOW_TIMEOUT = 900        # s: how long to wait for Lyrion's rescan before giving up

MAX_VALUE_LEN = 1000
MAX_COMMENT_LEN = 5000
MAX_VALUES = 50
MAX_TRACKS = 2000
OTHER_VALUE_LEN = 1000      # read-only tags are shown cut to this
OTHER_KEYS_MAX = 100
MAX_COVER_BYTES = 12 * 1024 * 1024
LYRION_TAGS_TIMEOUT = 5.0   # Lyrion 9.2 can hang on `tags` for a WAV file

_NUMBER_RE = re.compile(r'^[0-9]{1,4}(/[0-9]{1,4})?$')
_TOTAL_RE = re.compile(r'^[0-9]{1,4}$')
# What an ID3v2.4 timestamp frame can hold; anything else mutagen drops.
_DATE_RE = re.compile(r'^[0-9]{4}(-[0-9]{2}(-[0-9]{2}([T ][0-9]{2}(:[0-9]{2}(:[0-9]{2})?)?)?)?)?$')
_JOB_ID_RE = re.compile(r'^[0-9A-Za-z-]{6,64}$')
_COVER_ID_RE = re.compile(r'^[0-9A-Za-z_-]{1,64}$')

EXTENSIONS = {
    '.flac': 'flac', '.fla': 'flac', '.mp3': 'mp3', '.m4a': 'm4a', '.m4b': 'm4a', '.mp4': 'm4a', '.alac': 'm4a',
    '.ogg': 'ogg', '.oga': 'ogg', '.opus': 'opus', '.wv': 'wv', '.ape': 'ape', '.mpc': 'mpc', '.dsf': 'dsf',
    '.dff': 'dff', '.wav': 'wav', '.aif': 'aiff', '.aiff': 'aiff', '.aifc': 'aiff',
}
FORMATS = ('flac', 'mp3', 'm4a', 'ogg', 'opus', 'wv', 'ape', 'mpc', 'dsf', 'dff', 'wav', 'aiff')
_MUTAGEN_MODULES = {'flac': 'flac', 'mp3': 'mp3', 'm4a': 'mp4', 'ogg': 'oggvorbis', 'opus': 'oggopus',
                    'wv': 'wavpack', 'ape': 'monkeysaudio', 'mpc': 'musepack', 'dsf': 'dsf', 'dff': 'dsdiff',
                    'wav': 'wave', 'aiff': 'aiff'}
ID3_FORMATS = frozenset(('mp3', 'dsf', 'dff', 'wav', 'aiff'))


def _log(msg):
    print(f'[tags] {msg}', flush=True)


class TagError(Exception):
    """A request that cannot be done: `code` is a hifi_i18n key, `status` the
    HTTP status, `fields` go into the message and the JSON answer."""

    def __init__(self, code, status=400, **fields):
        super().__init__(code)
        self.code = code
        self.status = status
        self.fields = fields


class FileTagError(Exception):
    """Reading or writing one file failed."""


# ── writers available on this device ────────────────────────────────
_disable_mutagen = False        # tests: behave as if python3-mutagen were not installed


def mutagen_module():
    if _disable_mutagen:
        return None
    try:
        return importlib.import_module('mutagen')
    except ImportError:
        return None


def metaflac_path():
    return shutil.which('metaflac')


def writers():
    """Formats this device can write right now."""
    if mutagen_module() is not None:
        out = {}
        for fmt in FORMATS:
            try:
                importlib.import_module('mutagen.' + _MUTAGEN_MODULES[fmt])
                out[fmt] = True
            except ImportError:
                out[fmt] = False
        return out
    have_metaflac = bool(metaflac_path())
    return {fmt: (fmt == 'flac' and have_metaflac) for fmt in FORMATS}


def format_of(path):
    return EXTENSIONS.get(os.path.splitext(str(path or ''))[1].lower())


# ── validation ───────────────────────────────────────────────────────
def clean_values(key, values):
    """A value list as it may be written: strings only, control characters
    removed (line breaks kept in COMMENT), empty values dropped, lengths and
    numbers checked. An empty result means "remove the tag"."""
    if isinstance(values, (str, int)) and not isinstance(values, bool):
        values = [values]
    if not isinstance(values, list):
        raise TagError('library.badRequest')
    if len(values) > MAX_VALUES * 2:
        raise TagError('library.tooManyValues', key=key, max=MAX_VALUES)
    limit = MAX_COMMENT_LEN if key == 'COMMENT' else MAX_VALUE_LEN
    out = []
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (str, int)):
            raise TagError('library.badRequest')
        s = hm.clean_text(str(v), keep_newlines=(key == 'COMMENT'))
        if not s:
            continue
        if len(s) > limit:
            raise TagError('library.valueTooLong', key=key, max=limit)
        if s not in out:
            out.append(s)
    most = 1 if key in SINGLE_KEYS else MAX_VALUES
    if len(out) > most:
        raise TagError('library.tooManyValues', key=key, max=most)
    for s in out:
        if key in NUMBER_KEYS and not _NUMBER_RE.match(s):
            raise TagError('library.badNumber', key=key)
        if key in TOTAL_KEYS and not _TOTAL_RE.match(s):
            raise TagError('library.badTotal', key=key)
        if key in MBID_KEYS and not hm.UUID_RE.fullmatch(s):
            raise TagError('library.badMbid', key=key)
        if key == 'COMPILATION' and s not in ('0', '1'):
            raise TagError('library.badCompilation', key=key)
    if key in MBID_KEYS:
        out = [s.lower() for s in out]
    return out


def _editable_key(raw):
    key = str(raw if raw is not None else '').strip().upper()
    if key not in EDITABLE:
        raise TagError('library.badKey', key=hm.clean_text(str(raw))[:60])
    return key


def clean_changes(body):
    """(album_id, [{track_id, set, remove}]) from a POST album/tags body."""
    if not isinstance(body, dict):
        raise TagError('library.badRequest')
    album_id = body.get('album_id')
    if isinstance(album_id, bool) or not isinstance(album_id, (int, str)) or not str(album_id).isdigit():
        raise TagError('library.albumRequired')
    changes = body.get('changes')
    if not isinstance(changes, list) or not changes:
        raise TagError('library.nothingToChange')
    if len(changes) > MAX_TRACKS:
        raise TagError('library.tooManyTracks', max=MAX_TRACKS)
    out, seen = [], set()
    for ch in changes:
        if not isinstance(ch, dict):
            raise TagError('library.badRequest')
        tid = ch.get('track_id')
        if isinstance(tid, bool) or not isinstance(tid, (int, str)) or not str(tid).isdigit():
            raise TagError('library.badRequest')
        tid = int(tid)
        if tid in seen:
            raise TagError('library.badRequest')
        seen.add(tid)
        raw_set = ch.get('set') or {}
        raw_remove = ch.get('remove') or []
        if not isinstance(raw_set, dict) or not isinstance(raw_remove, list):
            raise TagError('library.badRequest')
        new_set, remove = {}, []
        for k, v in raw_set.items():
            key = _editable_key(k)
            values = clean_values(key, v)
            if values:
                new_set[key] = values
            elif key not in remove:
                remove.append(key)
        for k in raw_remove:
            key = _editable_key(k)
            if key in new_set:
                raise TagError('library.setAndRemove', key=key)
            if key not in remove:
                remove.append(key)
        if new_set or remove:
            out.append({'track_id': tid, 'set': new_set, 'remove': remove})
    if not out:
        raise TagError('library.nothingToChange')
    return int(album_id), out


def touched_keys(set_, remove):
    """The keys whose previous values are journaled: the ones changed, plus
    the other half of a track or disc number pair (in ID3, MP4 and APE both
    halves live in one field, so writing one can change the other)."""
    keys = set(set_) | set(remove)
    for a, b in PAIRS:
        if a in keys or b in keys:
            keys |= {a, b}
    return sorted(keys)


# ── reading: shared shape ────────────────────────────────────────────
def _show(values):
    """Read-only values for display: text, cut; binary as its size."""
    if not isinstance(values, (list, tuple)):
        values = [values]
    out = []
    for v in values[:MAX_VALUES]:
        if isinstance(v, (bytes, bytearray)):
            s = f'({len(v)} bytes)'
        else:
            s = str(v)
        if len(s) > OTHER_VALUE_LEN:
            s = s[:OTHER_VALUE_LEN] + '…'
        out.append(s)
    return out


class _Model:
    def __init__(self):
        self.tags = {}
        self.other = {}
        self.picture = False

    def add(self, key, values):
        vals = [v for v in (str(x) for x in values) if v != '']
        if vals:
            have = self.tags.setdefault(key, [])
            have.extend(v for v in vals if v not in have)

    def add_other(self, key, values):
        if len(self.other) < OTHER_KEYS_MAX or key in self.other:
            self.other.setdefault(key, []).extend(_show(values))

    def pair(self, number_key, total_key, text):
        n, _, total = str(text or '').partition('/')
        n, total = n.strip(), total.strip()
        if n and n != '0':
            self.add(number_key, [n])
        if total and total != '0':
            self.add(total_key, [total])

    def result(self):
        return {'tags': self.tags, 'other_tags': self.other, 'has_picture': self.picture}


_VORBIS_PICTURE_KEYS = ('METADATA_BLOCK_PICTURE', 'COVERART', 'COVERARTMIME')


def _vorbis_model(pairs, picture=False):
    m = _Model()
    m.picture = picture
    for key, value in pairs:
        k = str(key).upper()
        if k in _VORBIS_PICTURE_KEYS:
            m.picture = m.picture or k != 'COVERARTMIME'
            continue
        if k in EDITABLE:
            m.add(k, [value])
        else:
            m.add_other(k, [value])
    return m.result()


# ── FLAC without mutagen ─────────────────────────────────────────────
def read_flac(path):
    """The Vorbis comments and whether there is a picture, read straight from
    a FLAC file's metadata blocks — exact even for values with line breaks,
    which `metaflac --export-tags-to=-` cannot delimit."""
    try:
        with open(path, 'rb') as f:
            head = f.read(10)
            offset = 0
            if head[:3] == b'ID3' and len(head) == 10:
                size = (head[6] << 21) | (head[7] << 14) | (head[8] << 7) | head[9]
                offset = 10 + size + (10 if head[5] & 0x10 else 0)
            f.seek(offset)
            if f.read(4) != b'fLaC':
                raise FileTagError('not a FLAC file')
            pairs, picture = [], False
            for _ in range(1024):
                hdr = f.read(4)
                if len(hdr) < 4:
                    break
                last, btype = hdr[0] & 0x80, hdr[0] & 0x7F
                length = int.from_bytes(hdr[1:4], 'big')
                if btype == 4:
                    data = f.read(length)
                    if len(data) < length:
                        raise FileTagError('truncated comment block')
                    pairs.extend(_parse_vorbis_block(data))
                elif btype == 6:
                    picture = True
                    f.seek(length, 1)
                elif btype == 127:
                    raise FileTagError('invalid metadata block')
                else:
                    f.seek(length, 1)
                if last:
                    break
    except OSError as e:
        raise FileTagError(str(e))
    return _vorbis_model(pairs, picture)


def _parse_vorbis_block(data):
    def u32(pos):
        if pos + 4 > len(data):
            raise FileTagError('truncated comment block')
        return int.from_bytes(data[pos:pos + 4], 'little')
    pos = 4 + u32(0)
    count = u32(pos)
    pos += 4
    out = []
    for _ in range(min(count, 100000)):
        n = u32(pos)
        pos += 4
        raw = data[pos:pos + n]
        pos += n
        text = raw.decode('utf-8', 'replace')
        if '=' in text:
            key, value = text.split('=', 1)
            out.append((key, value))
    return out


def write_flac_metaflac(path, set_, remove):
    """One metaflac call per file: every touched key removed, then the new
    values set. metaflac rewrites the comment block in place when the padding
    allows, and leaves pictures and every other block alone."""
    exe = metaflac_path()
    if not exe:
        raise FileTagError('metaflac is not installed')
    args = [exe, '--no-utf8-convert']
    for key in sorted(set(set_) | set(remove)):
        args.append(f'--remove-tag={key}')
    for key in sorted(set_):
        for value in set_[key]:
            args.append(f'--set-tag={key}={value}')
    args.append(path)
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise FileTagError(f'metaflac: {e}')
    if r.returncode != 0:
        raise FileTagError(('metaflac: ' + (r.stderr or r.stdout or f'exit {r.returncode}').strip())[:400])


# ── mutagen ──────────────────────────────────────────────────────────
ID3_TEXT = {'TITLE': 'TIT2', 'ARTIST': 'TPE1', 'ALBUMARTIST': 'TPE2', 'ALBUM': 'TALB', 'DATE': 'TDRC',
            'ORIGINALDATE': 'TDOR', 'GENRE': 'TCON', 'COMPOSER': 'TCOM', 'CONDUCTOR': 'TPE3', 'LYRICIST': 'TEXT',
            'REMIXER': 'TPE4', 'LABEL': 'TPUB', 'ISRC': 'TSRC', 'COMPILATION': 'TCMP'}
ID3_TXXX = {'MUSICBRAINZ_ALBUMID': 'MusicBrainz Album Id', 'MUSICBRAINZ_ALBUMARTISTID': 'MusicBrainz Album Artist Id',
            'MUSICBRAINZ_ARTISTID': 'MusicBrainz Artist Id', 'MUSICBRAINZ_RELEASEGROUPID': 'MusicBrainz Release Group Id',
            'MUSICBRAINZ_RELEASETRACKID': 'MusicBrainz Release Track Id', 'RELEASETYPE': 'MusicBrainz Album Type',
            'CATALOGNUMBER': 'CATALOGNUMBER', 'ARRANGER': 'ARRANGER', 'BAND': 'BAND', 'PERFORMER': 'PERFORMER',
            'PRODUCER': 'PRODUCER', 'ENGINEER': 'ENGINEER', 'MIXER': 'MIXER'}
ID3_TRACKID_TXXX = 'MusicBrainz Track Id'
MB_UFID_OWNER = 'http://musicbrainz.org'
ID3_PAIRS = {'TRCK': PAIRS[0], 'TPOS': PAIRS[1]}
_ID3_TEXT_REV = {v: k for k, v in ID3_TEXT.items()}
_ID3_TXXX_REV = {v.lower(): k for k, v in ID3_TXXX.items()}

MP4_TEXT = {'TITLE': '\xa9nam', 'ARTIST': '\xa9ART', 'ALBUMARTIST': 'aART', 'ALBUM': '\xa9alb', 'DATE': '\xa9day',
            'GENRE': '\xa9gen', 'COMPOSER': '\xa9wrt', 'COMMENT': '\xa9cmt'}
MP4_FREEFORM_PREFIX = '----:com.apple.iTunes:'
MP4_FREEFORM = {'MUSICBRAINZ_ALBUMID': 'MusicBrainz Album Id', 'MUSICBRAINZ_ALBUMARTISTID': 'MusicBrainz Album Artist Id',
                'MUSICBRAINZ_ARTISTID': 'MusicBrainz Artist Id', 'MUSICBRAINZ_TRACKID': 'MusicBrainz Track Id',
                'MUSICBRAINZ_RELEASEGROUPID': 'MusicBrainz Release Group Id',
                'MUSICBRAINZ_RELEASETRACKID': 'MusicBrainz Release Track Id', 'RELEASETYPE': 'MusicBrainz Album Type',
                'ORIGINALDATE': 'ORIGINALDATE', 'CONDUCTOR': 'CONDUCTOR', 'LYRICIST': 'LYRICIST',
                'ARRANGER': 'ARRANGER', 'BAND': 'BAND', 'PERFORMER': 'PERFORMER', 'PRODUCER': 'PRODUCER',
                'ENGINEER': 'ENGINEER', 'MIXER': 'MIXER', 'REMIXER': 'REMIXER', 'LABEL': 'LABEL',
                'CATALOGNUMBER': 'CATALOGNUMBER', 'ISRC': 'ISRC'}
MP4_PAIRS = {'trkn': PAIRS[0], 'disk': PAIRS[1]}
_MP4_TEXT_REV = {v: k for k, v in MP4_TEXT.items()}
_MP4_FREEFORM_REV = {v.lower(): k for k, v in MP4_FREEFORM.items()}

APE_NAMES = {'ALBUMARTIST': 'Album Artist', 'REMIXER': 'MixArtist', 'CATALOGNUMBER': 'CatalogNumber',
             'RELEASETYPE': 'MUSICBRAINZ_ALBUMTYPE', 'DATE': 'Year', 'ISRC': 'ISRC'}
APE_PAIRS = {'track': PAIRS[0], 'disc': PAIRS[1]}
_APE_REV = {v.lower(): k for k, v in APE_NAMES.items()}


def _ape_name(key):
    if key in APE_NAMES:
        return APE_NAMES[key]
    return key if key in MBID_KEYS else key.title()


def _family(audio):
    names = {c.__name__ for c in type(audio).__mro__}
    if 'MP4' in names:
        return 'mp4'
    if names & {'FLAC', 'OggFileType'}:
        return 'vorbis'
    if 'APEv2File' in names:
        return 'ape'
    if names & {'ID3FileType', 'DSF', 'DSDIFF', 'WAVE', 'AIFF'}:
        return 'id3'
    return None


def _mutagen_open(path):
    mutagen = mutagen_module()
    if mutagen is None:
        raise FileTagError('python3-mutagen is not installed')
    try:
        audio = mutagen.File(path)
    except Exception as e:  # noqa: BLE001 — mutagen raises many kinds for a damaged file
        raise FileTagError(f'{type(e).__name__}: {e}')
    if audio is None:
        raise FileTagError('unrecognised file')
    family = _family(audio)
    if family is None:
        raise FileTagError(f'unsupported file type {type(audio).__name__}')
    return audio, family


def read_mutagen(path):
    audio, family = _mutagen_open(path)
    tags = audio.tags
    if family == 'vorbis':
        pictures = bool(getattr(audio, 'pictures', None))
        return _vorbis_model(list(tags) if tags is not None else [], pictures)
    m = _Model()
    if tags is None:
        return m.result()
    if family == 'id3':
        _read_id3(tags, m)
    elif family == 'mp4':
        _read_mp4(tags, m)
    else:
        _read_ape(tags, m)
    return m.result()


def _read_id3(tags, m):
    ufid_track = None
    txxx_track = []
    for frame in tags.values():
        fid = frame.FrameID
        if fid == 'APIC':
            m.picture = True
        elif fid in ID3_PAIRS:
            m.pair(*ID3_PAIRS[fid], text=str(frame.text[0]) if frame.text else '')
        elif fid == 'TCON':
            m.add('GENRE', frame.genres)
        elif fid in _ID3_TEXT_REV:
            m.add(_ID3_TEXT_REV[fid], [str(x) for x in frame.text])
        elif fid == 'COMM' and frame.desc == '':
            m.add('COMMENT', [str(x) for x in frame.text])
        elif fid == 'TXXX' and frame.desc.lower() in _ID3_TXXX_REV:
            m.add(_ID3_TXXX_REV[frame.desc.lower()], [str(x) for x in frame.text])
        elif fid == 'TXXX' and frame.desc.lower() == ID3_TRACKID_TXXX.lower():
            txxx_track = [str(x) for x in frame.text]
        elif fid == 'UFID' and frame.owner == MB_UFID_OWNER:
            ufid_track = frame.data.decode('ascii', 'replace')
        elif hasattr(frame, 'people'):       # TIPL/TMCL: shown, not edited
            m.add_other(frame.HashKey, [': '.join(str(x) for x in pair) for pair in frame.people])
        elif hasattr(frame, 'text'):
            m.add_other(frame.HashKey, [str(x) for x in frame.text] if isinstance(frame.text, list) else [frame.text])
        elif hasattr(frame, 'url'):
            m.add_other(frame.HashKey, [frame.url])
        elif isinstance(getattr(frame, 'data', None), bytes):
            m.add_other(frame.HashKey, [frame.data])
        else:
            m.add_other(frame.HashKey, [frame.pprint().split('=', 1)[-1]])
    if ufid_track:
        m.add('MUSICBRAINZ_TRACKID', [ufid_track])
    elif txxx_track:
        m.add('MUSICBRAINZ_TRACKID', txxx_track)


def _read_mp4(tags, m):
    for atom, value in tags.items():
        values = value if isinstance(value, list) else [value]
        if atom == 'covr':
            m.picture = True
        elif atom in MP4_PAIRS:
            if values and isinstance(values[0], tuple):
                n, total = (list(values[0]) + [0, 0])[:2]
                m.pair(*MP4_PAIRS[atom], text=f'{n or 0}/{total or 0}')
        elif atom == 'cpil':
            m.add('COMPILATION', ['1' if value else '0'])
        elif atom in _MP4_TEXT_REV:
            m.add(_MP4_TEXT_REV[atom], [str(v) for v in values])
        elif atom.startswith(MP4_FREEFORM_PREFIX) and atom[len(MP4_FREEFORM_PREFIX):].lower() in _MP4_FREEFORM_REV:
            m.add(_MP4_FREEFORM_REV[atom[len(MP4_FREEFORM_PREFIX):].lower()],
                  [bytes(v).decode('utf-8', 'replace') for v in values])
        elif atom.startswith('----:'):
            m.add_other(atom, [bytes(v).decode('utf-8', 'replace') for v in values])
        else:
            m.add_other(atom, [v if isinstance(v, (bytes, bytearray)) else str(v) for v in values])


def _read_ape(tags, m):
    for name, value in tags.items():
        low = name.lower()
        binary = getattr(value, 'kind', 0) != 0
        if low.startswith('cover art'):
            m.picture = True
        elif binary:
            m.add_other(name, [bytes(value.value) if hasattr(value, 'value') else b''])
        elif low in APE_PAIRS:
            m.pair(*APE_PAIRS[low], text=list(value)[0] if list(value) else '')
        elif low in _APE_REV:
            m.add(_APE_REV[low], list(value))
        elif name.upper() in EDITABLE:
            m.add(name.upper(), list(value))
        else:
            m.add_other(name, list(value))


def _pair_after(current, set_, remove, number_key, total_key):
    """(number, total) a combined field ends up with."""
    n = (current.get(number_key) or [None])[0]
    total = (current.get(total_key) or [None])[0]
    if number_key in remove:
        n = None
    if total_key in remove:
        total = None
    if number_key in set_:
        a, _, b = set_[number_key][0].partition('/')
        n = a or None
        if b and total_key not in set_:
            total = b
    if total_key in set_:
        total = set_[total_key][0]
    return n, total


def write_mutagen(path, set_, remove):
    audio, family = _mutagen_open(path)
    touched = set(set_) | set(remove)
    if family == 'vorbis':
        if audio.tags is None:
            audio.add_tags()
        for key in touched:
            try:
                del audio.tags[key]
            except KeyError:
                pass
        for key, values in set_.items():
            audio.tags[key] = list(values)
    else:
        current = read_mutagen(path)['tags']
        if audio.tags is None:
            audio.add_tags()        # a bare MP3/WAV/DSF gets ID3v2.4, an MP4 its ilst, WavPack APEv2
        if family == 'id3':
            _write_id3(audio.tags, set_, remove, current)
        elif family == 'mp4':
            _write_mp4(audio.tags, set_, remove, current)
        else:
            _write_ape(audio.tags, set_, remove, current)
    try:
        audio.save()
    except Exception as e:  # noqa: BLE001
        raise FileTagError(f'{type(e).__name__}: {e}')


def _write_id3(tags, set_, remove, current):
    from mutagen import id3
    for frame_id, (nkey, tkey) in ID3_PAIRS.items():
        if nkey in set_ or tkey in set_ or nkey in remove or tkey in remove:
            n, total = _pair_after(current, set_, remove, nkey, tkey)
            tags.delall(frame_id)
            if n:
                text = f'{n}/{total}' if total else n
                tags.add(getattr(id3, frame_id)(encoding=3, text=[text]))
    for key in (set(set_) | set(remove)) - NUMBER_KEYS - TOTAL_KEYS:
        values = set_.get(key)
        if key in ID3_TEXT:
            tags.delall(ID3_TEXT[key])
            if values:
                tags.add(getattr(id3, ID3_TEXT[key])(encoding=3, text=list(values)))
        elif key == 'COMMENT':
            for frame in list(tags.getall('COMM')):
                if frame.desc == '':
                    del tags[frame.HashKey]
            if values:
                tags.add(id3.COMM(encoding=3, lang='eng', desc='', text=list(values)))
        elif key == 'MUSICBRAINZ_TRACKID':
            tags.delall('UFID:' + MB_UFID_OWNER)
            _drop_txxx(tags, ID3_TRACKID_TXXX)
            if values:
                tags.add(id3.UFID(owner=MB_UFID_OWNER, data=values[0].encode('ascii')))
        elif key in ID3_TXXX:
            _drop_txxx(tags, ID3_TXXX[key])
            if values:
                tags.add(id3.TXXX(encoding=3, desc=ID3_TXXX[key], text=list(values)))


def _drop_txxx(tags, desc):
    for frame in list(tags.getall('TXXX')):
        if frame.desc.lower() == desc.lower():
            del tags[frame.HashKey]


def _write_mp4(tags, set_, remove, current):
    from mutagen.mp4 import MP4FreeForm
    for atom, (nkey, tkey) in MP4_PAIRS.items():
        if nkey in set_ or tkey in set_ or nkey in remove or tkey in remove:
            n, total = _pair_after(current, set_, remove, nkey, tkey)
            tags.pop(atom, None)
            if n or total:
                tags[atom] = [(int(n or 0), int(total or 0))]
    for key in (set(set_) | set(remove)) - NUMBER_KEYS - TOTAL_KEYS:
        values = set_.get(key)
        if key == 'COMPILATION':
            tags.pop('cpil', None)
            if values:
                tags['cpil'] = values[0] == '1'
        elif key in MP4_TEXT:
            tags.pop(MP4_TEXT[key], None)
            if values:
                tags[MP4_TEXT[key]] = list(values)
        elif key in MP4_FREEFORM:
            wanted = MP4_FREEFORM[key].lower()
            for atom in [a for a in tags.keys() if a.startswith(MP4_FREEFORM_PREFIX)
                         and a[len(MP4_FREEFORM_PREFIX):].lower() == wanted]:
                del tags[atom]
            if values:
                tags[MP4_FREEFORM_PREFIX + MP4_FREEFORM[key]] = [MP4FreeForm(v.encode('utf-8')) for v in values]


def _write_ape(tags, set_, remove, current):
    for name, (nkey, tkey) in (('Track', PAIRS[0]), ('Disc', PAIRS[1])):
        if nkey in set_ or tkey in set_ or nkey in remove or tkey in remove:
            n, total = _pair_after(current, set_, remove, nkey, tkey)
            if name in tags:
                del tags[name]
            if n:
                tags[name] = f'{n}/{total}' if total else n
    for key in (set(set_) | set(remove)) - NUMBER_KEYS - TOTAL_KEYS:
        name = _ape_name(key)
        if name in tags:
            del tags[name]
        values = set_.get(key)
        if values:
            tags[name] = list(values)


# ── one file ─────────────────────────────────────────────────────────
def read_file(path, fmt):
    if mutagen_module() is not None:
        return read_mutagen(path)
    if fmt == 'flac':
        return read_flac(path)
    raise FileTagError('no reader for this format')


def write_file(path, fmt, set_, remove):
    if mutagen_module() is not None:
        return write_mutagen(path, set_, remove)
    if fmt == 'flac':
        return write_flac_metaflac(path, set_, remove)
    raise FileTagError('no writer for this format')


# ── Lyrion's reading of the tags (read-only fallback) ────────────────
def _fold(key):
    return re.sub(r'[^A-Z0-9]', '', str(key).upper())


_LYRION_KEYS = {_fold(k): k for k in EDITABLE_KEYS}
_LYRION_KEYS.update({
    'TOTALTRACKS': 'TRACKTOTAL', 'TOTALDISCS': 'DISCTOTAL', 'YEAR': 'DATE', 'MIXARTIST': 'REMIXER',
    'MUSICBRAINZALBUMTYPE': 'RELEASETYPE', 'ALBUMARTISTS': None,
    'TIT2': 'TITLE', 'TPE1': 'ARTIST', 'TPE2': 'ALBUMARTIST', 'TALB': 'ALBUM', 'TDRC': 'DATE', 'TYER': 'DATE',
    'TDOR': 'ORIGINALDATE', 'TORY': 'ORIGINALDATE', 'TCON': 'GENRE', 'TCOM': 'COMPOSER', 'TPE3': 'CONDUCTOR',
    'TEXT': 'LYRICIST', 'TPE4': 'REMIXER', 'TPUB': 'LABEL', 'TSRC': 'ISRC', 'TCMP': 'COMPILATION', 'COMM': 'COMMENT',
    'NAM': 'TITLE', 'ART': 'ARTIST', 'AART': 'ALBUMARTIST', 'ALB': 'ALBUM', 'DAY': 'DATE', 'GEN': 'GENRE',
    'WRT': 'COMPOSER', 'CMT': 'COMMENT', 'CPIL': 'COMPILATION',
})
_LYRION_PAIRS = {'TRCK': PAIRS[0], 'TRKN': PAIRS[0], 'TRACK': PAIRS[0],
                 'TPOS': PAIRS[1], 'DISK': PAIRS[1], 'DISC': PAIRS[1]}
_LYRION_PICTURES = {'ALLPICTURES', 'APIC', 'COVR', 'COVERART', 'COVERARTFRONT', 'METADATABLOCKPICTURE', 'PICTURE'}


def lyrion_tags_model(raw):
    """Lyrion's `tags track_id:` answer in the editor's vocabulary."""
    m = _Model()
    for key, value in (raw or {}).items():
        key = str(key)
        if key.endswith(('_offset', '_length')):
            continue
        folded = _fold(key.rsplit(':', 1)[-1])
        text = str(value if value is not None else '')
        if text.startswith('[ ') and text.endswith(' ]'):
            values = [x.strip() for x in text[2:-2].split(', ')]
        else:
            values = [text]
        values = [v for v in values if v]
        if folded in _LYRION_PICTURES:
            m.picture = True
        elif folded in _LYRION_PAIRS:
            if values:
                m.pair(*_LYRION_PAIRS[folded], text=values[0])
        elif _LYRION_KEYS.get(folded):
            m.add(_LYRION_KEYS[folded], values)
        elif values:
            m.add_other(key, values)
    return m.result()


# ── paths ────────────────────────────────────────────────────────────
def path_from_url(url):
    """(local path, cue) from a Lyrion track URL; (None, False) for anything
    that is not a file. `cue` marks a track cut out of a bigger file."""
    try:
        parts = urllib.parse.urlsplit(str(url or ''))
    except ValueError:
        return None, False
    if parts.scheme != 'file' or parts.netloc not in ('', 'localhost'):
        return None, False
    path = os.fsdecode(urllib.parse.unquote_to_bytes(parts.path))
    return (path or None), bool(parts.fragment)


def confine(path, roots):
    """The resolved path when it is a music root or below one, else None —
    the same rule as sources_server's _under_roots(): what comes out is never
    the caller's string."""
    if not path:
        return None
    real = os.path.realpath(path)
    for root in roots:
        root = os.path.realpath(root)
        if real == root or real.startswith(root + os.sep):
            return real
    return None


def fs_readonly(path):
    """True on a read-only mount (a NAS added read-only, the image's
    squashfs): root passes os.access() there and fails at the write."""
    try:
        return bool(os.statvfs(path).f_flag & os.ST_RDONLY)
    except OSError:
        return False


def display_path(path, mediadirs):
    best = None
    for d in mediadirs or []:
        d = str(d).rstrip('/')
        if d and (path == d or path.startswith(d + '/')) and (best is None or len(d) > len(best)):
            best = d
    if best:
        return path[len(best):].lstrip('/')
    return os.path.basename(path or '')


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _host_is_this_device(host):
    host = (host or '').strip('[]').lower()
    if host in ('localhost', 'localhost.localdomain'):
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        name = socket.gethostname().lower()
        return host in (name, name + '.local')
    if addr.is_loopback:
        return True
    # An address this machine owns is one it can bind to.
    try:
        with socket.socket(socket.AF_INET6 if addr.version == 6 else socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.bind((str(addr), 0))
        return True
    except OSError:
        return False


def _write_json(path, doc):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, separators=(',', ':'))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# ── the service ──────────────────────────────────────────────────────
class TagService:
    def __init__(self, roots=DEFAULT_ROOTS, lyrion=None, edits_dir=None, clock=None, local=None, urlopen=None,
                 metadata=None, sleep=None, monotonic=None):
        self.roots = tuple(roots)
        self._metadata = metadata           # the MetadataService (hm.get_service() when None)
        self._sleep = sleep or time.sleep
        self._monotonic = monotonic or time.monotonic
        self.lyrion = lyrion or hm.Lyrion()
        self.edits_dir = edits_dir or os.environ.get('HIFI_META_EDITS_DIR') or EDITS_DIR
        self.jobs_dir = os.path.join(self.edits_dir, JOBS_SUBDIR)
        self._clock = clock or time.time
        self._local = local
        self._urlopen = urlopen or urllib.request.urlopen
        self._lock = threading.Lock()       # the running job, the journal files
        self._job = None
        self._thread = None
        self._seq = 0
        self._recovered = False
        self._summaries = {}
        self._cache_lock = threading.Lock()
        self._local_cache = None
        self._stamp_cache = None
        self._counts = {'tracks': {}, 'albums': {}}
        self._count_stamp = {}
        self._mediadirs_cache = None
        self._placeholders = {}

    # ── where the library is ──
    def is_local(self):
        if self._local is not None:
            return bool(self._local() if callable(self._local) else self._local)
        url = self.lyrion.base_url()
        now = time.monotonic()
        cached = self._local_cache
        if cached and cached[0] == url and now - cached[1] < 60:
            return cached[2]
        local = _host_is_this_device(urllib.parse.urlsplit(url).hostname)
        self._local_cache = (url, now, local)
        return local

    def status(self):
        local = self.is_local()
        available, reason = True, ''
        try:
            self.lyrion.request(['serverstatus', 0, 0], timeout=5)
        except hm.LyrionError:
            available, reason = False, 'lyrion_unreachable'
        if available and not local:
            reason = 'remote_server'
        return {'available': available, 'local': local, 'writers': writers(),
                'mutagen': mutagen_module() is not None, 'reason': reason}

    def _scan_stamp(self):
        url = self.lyrion.base_url()
        now = time.monotonic()
        cached = self._stamp_cache
        if cached and cached[0] == url and now - cached[1] < 30:
            return cached[2]
        try:
            st = self.lyrion.request(['serverstatus', 0, 0], timeout=5)
            stamp = (url, st.get('lastscan'), st.get('info total albums'), st.get('info total songs'))
        except hm.LyrionError:
            stamp = (url, None)
        self._stamp_cache = (url, now, stamp)
        return stamp

    def _counted(self, kind, ids):
        """Track counts per album ('tracks') or album counts per artist
        ('albums'), one small query each (pooled), kept until the library is
        scanned again."""
        stamp = self._scan_stamp()
        with self._cache_lock:
            if self._count_stamp.get(kind) != stamp:
                self._counts[kind] = {}
                self._count_stamp[kind] = stamp
            cache = self._counts[kind]
            missing = [i for i in dict.fromkeys(ids) if i is not None and i not in cache]

        def count(item):
            cmd = ['titles', 0, 0, f'album_id:{item}'] if kind == 'tracks' else ['albums', 0, 0, f'artist_id:{item}']
            try:
                return item, int(self.lyrion.request(cmd, timeout=10).get('count') or 0)
            except (hm.LyrionError, TypeError, ValueError):
                return item, None
        if missing:
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                found = list(pool.map(count, missing))
            with self._cache_lock:
                for item, n in found:
                    if n is not None:
                        cache[item] = n
        return {i: cache.get(i) for i in ids}

    def _mediadirs(self):
        url = self.lyrion.base_url()
        now = time.monotonic()
        cached = self._mediadirs_cache
        if cached and cached[0] == url and now - cached[1] < 30:
            return cached[2]
        try:
            dirs = self.lyrion.request(['pref', 'mediadirs', '?'], timeout=5).get('_p2')
        except hm.LyrionError:
            dirs = None
        if not isinstance(dirs, list):
            dirs = [dirs] if isinstance(dirs, str) and dirs else []
        self._mediadirs_cache = (url, now, dirs)
        return dirs

    # ── browsing ──
    @staticmethod
    def _album_entry(a):
        art = a.get('artwork_track_id')
        return {'album_id': int(a['id']), 'title': a.get('album') or '', 'artist': a.get('artist') or '',
                'artist_id': _int_or_none(a.get('artist_id')), 'year': _int_or_none(a.get('year')) or None,
                'artwork_track_id': str(art) if art not in (None, '') else None,
                'compilation': str(a.get('compilation') or '0') == '1'}

    def albums(self, q='', offset=0, limit=60, artist_id=None):
        """Albums by title, or one artist's albums by year then title."""
        params = ['albums', int(offset), int(limit), 'tags:alyjwqS',
                  'sort:album' if artist_id is None else 'sort:yearalbum']
        if q:
            params.append(f'search:{q}')
        if artist_id is not None:
            params.append(f'artist_id:{int(artist_id)}')
        r = self.lyrion.request(params, timeout=20)
        loop = [a for a in r.get('albums_loop') or [] if _int_or_none(a.get('id')) is not None]
        counts = self._counted('tracks', [int(a['id']) for a in loop])
        albums = []
        for a in loop:
            entry = self._album_entry(a)
            entry['track_count'] = counts.get(entry['album_id'])
            albums.append(entry)
        return {'total': int(r.get('count') or 0), 'albums': albums}

    def artists(self, q='', offset=0, limit=100):
        params = ['artists', int(offset), int(limit)]
        if q:
            params.append(f'search:{q}')
        r = self.lyrion.request(params, timeout=20)
        loop = [a for a in r.get('artists_loop') or [] if _int_or_none(a.get('id')) is not None]
        counts = self._counted('albums', [int(a['id']) for a in loop])
        return {'total': int(r.get('count') or 0),
                'artists': [{'artist_id': int(a['id']), 'name': a.get('artist') or '',
                             'album_count': counts.get(int(a['id']))} for a in loop]}

    def cover(self, cover_id, size=300):
        """(bytes, content type) of an album or track cover from Lyrion,
        resized there; None when there is no art. Lyrion answers a missing
        cover with its generic placeholder (200, `Cache-Control: no-cache`,
        where real art is cacheable for a year), so such an answer is compared
        with the placeholder before it is passed on."""
        if not _COVER_ID_RE.match(str(cover_id)):
            return None
        size = max(32, min(1200, int(size)))
        got = self._fetch_cover(cover_id, size)
        if got is None:
            return None
        data, ctype, cache_control = got
        if 'no-cache' in cache_control.lower():
            placeholder = self._placeholder_digest(size)
            if placeholder is None or hashlib.sha1(data).hexdigest() == placeholder:
                return None
        return data, ctype

    def _fetch_cover(self, cover_id, size):
        url = f'{self.lyrion.base_url()}/music/{cover_id}/cover_{size}x{size}_o'
        try:
            with self._urlopen(urllib.request.Request(url), timeout=10) as resp:
                data = resp.read(MAX_COVER_BYTES + 1)
                headers = resp.headers
                ctype = (headers.get('Content-Type') or '') if headers is not None else ''
                cache_control = (headers.get('Cache-Control') or '') if headers is not None else ''
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise hm.LyrionError(f'HTTP {e.code}')
        except (urllib.error.URLError, OSError) as e:
            raise hm.LyrionError(str(e))
        if len(data) > MAX_COVER_BYTES or not ctype.lower().startswith('image/'):
            return None
        return data, ctype, cache_control

    def _placeholder_digest(self, size):
        key = (self.lyrion.base_url(), size)
        if key not in self._placeholders:
            try:
                got = self._fetch_cover('0', size)
            except hm.LyrionError:
                return None
            self._placeholders[key] = hashlib.sha1(got[0]).hexdigest() if got else None
        return self._placeholders[key]

    def _lyrion_album(self, album_id):
        r = self.lyrion.request(['albums', 0, 1, f'album_id:{int(album_id)}', 'tags:alyjwqS'])
        loop = r.get('albums_loop') or []
        return loop[0] if loop and _int_or_none(loop[0].get('id')) is not None else None

    def _album_tracks(self, album_id):
        r = self.lyrion.request(['titles', 0, 5000, f'album_id:{int(album_id)}', 'tags:dtiuoalyg',
                                 'sort:tracknum'], timeout=30)
        return [t for t in r.get('titles_loop') or [] if _int_or_none(t.get('id')) is not None]

    # ── one album's files ──
    def access(self, path, fmt, cue=False, writer_map=None):
        """(confined real path or None, reason). The path is only handed back
        when the file may be read here; `reason` is "" when it may be written."""
        if not path:
            return None, 'unsupported_format'
        real = confine(path, self.roots)
        if real is None:
            return None, 'outside_sources'
        if not os.path.isfile(real):
            return None, 'missing'
        if cue or not (writer_map if writer_map is not None else writers()).get(fmt):
            return real, 'unsupported_format'
        if fs_readonly(real) or not os.access(real, os.W_OK):
            return real, 'readonly'
        return real, ''

    def album(self, album_id):
        a = self._lyrion_album(album_id)
        if a is None:
            raise TagError('library.unknownAlbum', 404)
        tracks = self._album_tracks(album_id)
        local = self.is_local()
        mediadirs = self._mediadirs()
        writer_map = writers()
        dump_state = {}         # format -> Lyrion failed on `tags` for it

        def row(t):
            return self._track_row(t, local, mediadirs, writer_map, dump_state)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(row, tracks))
        rows.sort(key=lambda r: (r.pop('_disc'), r.pop('_n'), r['track_id']))
        reasons = {r['reason'] for r in rows}
        writable = [r for r in rows if r['writable']]
        if not rows:
            editable, reason = False, ('remote_server' if not local else '')
        elif not local:
            editable, reason = False, 'remote_server'
        elif len(writable) == len(rows):
            editable, reason = True, ''
        elif writable:
            editable, reason = True, 'mixed'
        else:
            editable, reason = False, (reasons.pop() if len(reasons) == 1 else 'mixed')
        entry = self._album_entry(a)
        entry['disc_count'] = _int_or_none(a.get('disccount')) or 1
        entry.pop('track_count', None)
        return {'album': entry, 'editable': editable, 'reason': reason, 'tracks': rows}

    def _track_row(self, t, local, mediadirs, writer_map, dump_state):
        tid = int(t['id'])
        path, cue = path_from_url(t.get('url'))
        fmt = format_of(path) or str(t.get('type') or '')
        row = {'track_id': tid, 'file': display_path(path, mediadirs) if path else '', 'format': fmt,
               'writable': False, 'reason': '', 'tags': {}, 'other_tags': {}, 'has_picture': False,
               'duration': float(t['duration']) if t.get('duration') not in (None, '') else None,
               '_disc': _int_or_none(t.get('disc')) or 1,
               '_n': _int_or_none(str(t.get('tracknum') or '0').split('/')[0]) or 0}
        real = None
        if local:
            real, reason = self.access(path, fmt, cue, writer_map)
            row['reason'] = reason
            row['writable'] = reason == ''
        else:
            row['reason'] = 'remote_server'
        model = None
        if real is not None:
            try:
                model = read_file(real, fmt)
            except FileTagError as e:
                if row['writable'] or row['reason'] == 'readonly':
                    _log(f'track {tid}: unreadable ({e}): shown read-only')
                    row['writable'], row['reason'] = False, 'unsupported_format'
        if model is None:
            model = self._lyrion_model(t, fmt, dump_state)
        row.update(tags=model['tags'], other_tags=model['other_tags'], has_picture=model['has_picture'])
        return row

    # What Lyrion shows for a missing tag; not something the file says.
    _LYRION_PLACEHOLDERS = frozenset(('No Artist', 'No Album', 'No Genre'))

    def _lyrion_model(self, t, fmt, dump_state):
        if not dump_state.get(fmt):
            try:
                raw = self.lyrion.request(['tags', 0, 200, f"track_id:{int(t['id'])}"], timeout=LYRION_TAGS_TIMEOUT)
                raw = {k: v for k, v in raw.items() if not isinstance(v, (dict, list))}
                return lyrion_tags_model(raw)
            except hm.LyrionError as e:
                # Lyrion 9.2 fails or stalls on `tags` for some files (WAV):
                # after one failure the album's other files of that kind are
                # shown from the track list.
                _log(f"tags of track {t.get('id')} not read from Lyrion: {e}")
                dump_state[fmt] = True
        m = _Model()
        m.add('TITLE', [t.get('title') or ''])
        for key, field in (('ARTIST', 'artist'), ('ALBUM', 'album'), ('GENRE', 'genre')):
            if t.get(field) and t[field] not in self._LYRION_PLACEHOLDERS:
                m.add(key, [t[field]])
        if str(t.get('year') or '0') != '0':
            m.add('DATE', [str(t.get('year'))])
        m.pair('TRACKNUMBER', 'TRACKTOTAL', str(t.get('tracknum') or ''))
        if str(t.get('disc') or ''):
            m.pair('DISCNUMBER', 'DISCTOTAL', str(t.get('disc')))
        return m.result()

    # ── writing ──
    def start_tags(self, body):
        album_id, changes = clean_changes(body)
        if not self.is_local():
            raise TagError('library.remoteServer', 409)
        a = self._lyrion_album(album_id)
        if a is None:
            raise TagError('library.unknownAlbum', 404)
        by_id = {int(t['id']): t for t in self._album_tracks(album_id)}
        writer_map = writers()
        files = []
        for ch in changes:
            t = by_id.get(ch['track_id'])
            if t is None:
                raise TagError('library.trackNotInAlbum', track_id=ch['track_id'])
            path, cue = path_from_url(t.get('url'))
            fmt = format_of(path)
            real, reason = self.access(path, fmt, cue, writer_map)
            if reason:
                raise TagError('library.trackNotWritable', 409, track_id=ch['track_id'], reason=reason)
            if fmt in ID3_FORMATS:
                for key in DATE_KEYS & set(ch['set']):
                    if not all(_DATE_RE.match(v) for v in ch['set'][key]):
                        raise TagError('library.badDate', key=key, track_id=ch['track_id'])
            files.append({'track_id': ch['track_id'], 'path': real, 'format': fmt, 'url': t.get('url') or '',
                          'set': ch['set'], 'remove': ch['remove']})
        before = {'album_id': album_id, 'title': a.get('album') or '', 'artist': a.get('artist') or '',
                  'track_count': len(by_id)}
        return self._start_job(album_id, a.get('album') or '', files, before=before)

    def _new_job_id(self):
        stamp = time.strftime('%Y%m%d-%H%M%S', time.gmtime(self._clock()))
        return f'{stamp}-{secrets.token_hex(3)}'

    def _start_job(self, album_id, album_title, files, undo_of=None, before=None):
        with self._lock:
            self._recover()
            if self._job is not None:
                raise TagError('library.busy', 409)
            os.makedirs(self.jobs_dir, mode=0o755, exist_ok=True)
            job_id = self._new_job_id()
            # `seq` orders jobs started within the same second
            self._seq = max(self._seq + 1, int(self._clock() * 1_000_000))
            doc = {'version': 1, 'job_id': job_id, 'when': int(self._clock()), 'seq': self._seq, 'album_id': album_id,
                   'album': album_title, 'tracks': len(files), 'state': 'running', 'done': 0,
                   'total': len(files), 'errors': [], 'rescan': None, 'undone': False, 'undone_by': None,
                   'undo_of': undo_of, 'interrupted': False, 'files': files,
                   # the album as it was, and where its files are once Lyrion has rescanned
                   'before_album': before, 'follow': None, 'new_album_id': None}
            _write_json(os.path.join(self.jobs_dir, job_id + '.json'), doc)
            self._job = doc
        self._thread = threading.Thread(target=self._run, args=(doc,), daemon=True, name=f'tags-{job_id}')
        self._thread.start()
        return {'job_id': job_id}

    def wait(self, timeout=60):
        """Tests: until the running job (if any) has finished."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        return self._job is None

    def _run(self, doc):
        """The job thread. `doc` is shared with job()/history(), which copy
        it under the lock, so every change to it is made under the lock too;
        the slow parts (reading, writing, Lyrion) run outside it."""
        lock = self._lock

        def error(track_id, code, detail):
            with lock:
                doc['errors'].append({'track_id': track_id, 'code': code, 'detail': str(detail)[:400]})
        try:
            for f in doc['files']:
                try:
                    current = read_file(f['path'], f['format'])['tags']
                except FileTagError as e:
                    error(f['track_id'], 'library.readFailed', e)
                    continue
                with lock:
                    f['before'] = {k: (list(current[k]) if k in current else None)
                                   for k in touched_keys(f['set'], f['remove'])}
            # Everything a write may lose is on disk before the first write.
            self._save(doc)
            last = time.monotonic()
            for f in doc['files']:
                if 'before' in f:
                    try:
                        if confine(f['path'], self.roots) != f['path']:
                            raise FileTagError('the file is no longer inside the music folders')
                        write_file(f['path'], f['format'], f['set'], f['remove'])
                        st = os.stat(f['path'])
                        with lock:
                            f.update(written=True, size=st.st_size, mtime_ns=st.st_mtime_ns)
                    except (FileTagError, OSError) as e:
                        error(f['track_id'], 'library.writeFailed', e)
                with lock:
                    doc['done'] += 1
                if time.monotonic() - last > 2:
                    self._save(doc)
                    last = time.monotonic()
            written = any(f.get('written') for f in doc['files'])
            rescan = 'skipped'
            if written and self.is_local():
                try:
                    self.lyrion.request(['rescan'], timeout=10)
                    rescan = 'started'
                except hm.LyrionError as e:
                    _log(f"job {doc['job_id']}: rescan not started: {e}")
                    rescan = 'failed'
            renamed = rescan == 'started' and bool(doc.get('before_album')) and any(
                (set(f['set']) | set(f['remove'])) & ALBUM_KEYS for f in doc['files'] if f.get('written'))
            with lock:
                doc['rescan'] = rescan
                doc['state'] = 'done' if written or not doc['errors'] else 'error'
                doc['follow'] = 'waiting' if renamed else None
                clean = not doc['errors']
            if doc.get('undo_of') and written and clean:
                self._mark_undone(doc['undo_of'], doc['job_id'])
        except Exception as e:  # noqa: BLE001 — the journal must still be closed
            _log(f"job {doc['job_id']} failed: {type(e).__name__}: {e}")
            error(None, 'library.writeFailed', f'{type(e).__name__}: {e}')
            with lock:
                doc['state'] = 'error'
        finally:
            with lock:
                try:
                    _write_json(os.path.join(self.jobs_dir, doc['job_id'] + '.json'), doc)
                except OSError as e:
                    _log(f"job {doc['job_id']}: journal not saved: {e}")
                self._job = None
                self._prune()
            if doc.get('follow') == 'waiting':
                threading.Thread(target=self._follow_album, args=(doc['job_id'],), daemon=True,
                                 name=f"tags-follow-{doc['job_id']}").start()
            _log(f"job {doc['job_id']}: {doc['state']}, {sum(1 for f in doc['files'] if f.get('written'))}"
                 f"/{doc['total']} file(s) written, {len(doc['errors'])} error(s), rescan {doc['rescan']}")

    def _save(self, doc):
        with self._lock:
            _write_json(os.path.join(self.jobs_dir, doc['job_id'] + '.json'), copy.deepcopy(doc))

    # ── after a job that moved files to another album ──
    def _wait_for_scan(self):
        """Until Lyrion's rescan (started by the job) is over. A scan that
        never shows up within 20 s is taken as already finished."""
        start = self._monotonic()
        seen = False
        while self._monotonic() - start < FOLLOW_TIMEOUT:
            try:
                st = self.lyrion.request(['serverstatus', 0, 0], timeout=10)
                scanning = str(st.get('rescan') or '0') not in ('0', '')
            except hm.LyrionError:
                scanning = True             # restarting: wait for it
            if scanning:
                seen = True
            elif seen or self._monotonic() - start > 20:
                return True
            self._sleep(2)
        return False

    def album_of_url(self, url):
        """The Lyrion album a file belongs to now (its track looked up by URL)."""
        if not url:
            return None
        quoted = str(url).replace("'", "''")
        r = self.lyrion.request(['titles', 0, 1, 'tags:e', f"search:sql=tracks.url='{quoted}'"], timeout=15)
        loop = r.get('titles_loop') or []
        return _int_or_none(loop[0].get('album_id')) if loop else None

    def _follow_album(self, job_id):
        """The job changed album, album artist or artist: once Lyrion has
        rescanned, find the album the files are in now (a new id), tell the
        web app through the job (`new_album_id`) and let the metadata service
        move the album's edition choice and credit corrections to it."""
        doc = self._load(job_id)
        if doc is None:
            return
        url = next((f.get('url') for f in doc.get('files') or [] if f.get('written') and f.get('url')), '')
        new_id = None
        try:
            if self._wait_for_scan():
                new_id = self.album_of_url(url)
                if new_id is not None:
                    service = self._metadata or hm.get_service()
                    service.album_renamed(doc.get('before_album') or {}, new_id)
        except Exception as e:  # noqa: BLE001 — the job must still be closed
            _log(f'job {job_id}: following the album failed: {type(e).__name__}: {e}')
        with self._lock:
            current = self._load(job_id) or doc
            current['follow'] = 'done'
            current['new_album_id'] = new_id
            try:
                _write_json(os.path.join(self.jobs_dir, job_id + '.json'), current)
            except OSError as e:
                _log(f'job {job_id}: journal not saved: {e}')
        _log(f'job {job_id}: files now in album {new_id}')

    def _load(self, job_id):
        if not _JOB_ID_RE.match(str(job_id or '')):
            return None
        try:
            with open(os.path.join(self.jobs_dir, job_id + '.json'), encoding='utf-8') as f:
                doc = json.load(f)
        except (OSError, ValueError):
            return None
        return doc if isinstance(doc, dict) and doc.get('job_id') == job_id else None

    def _mark_undone(self, job_id, by):
        with self._lock:
            doc = self._load(job_id)
            if doc is not None:
                doc.update(undone=True, undone_by=by)
                _write_json(os.path.join(self.jobs_dir, job_id + '.json'), doc)

    def _recover(self):
        """Once per process (lock held): a journal still "running" belongs to
        a job the service was stopped in the middle of."""
        if self._recovered:
            return
        self._recovered = True
        try:
            names = [n for n in os.listdir(self.jobs_dir) if n.endswith('.json')]
        except OSError:
            return
        for name in names:
            doc = self._load(name[:-5])
            if doc and doc.get('state') == 'running':
                doc.update(state='error', interrupted=True)
                doc.setdefault('errors', []).append({'track_id': None, 'code': 'library.interrupted', 'detail': ''})
                try:
                    _write_json(os.path.join(self.jobs_dir, name), doc)
                except OSError:
                    pass

    def _prune(self):
        try:
            names = [n[:-5] for n in os.listdir(self.jobs_dir) if n.endswith('.json')]
        except OSError:
            return
        entries = []
        for job_id in names:
            s = self._summary(job_id)
            if s:
                entries.append((s['when'], s['seq'], job_id))
        entries.sort(reverse=True)
        for _when, _seq, job_id in entries[JOBS_KEEP:]:
            if self._job is not None and self._job['job_id'] == job_id:
                continue
            try:
                os.remove(os.path.join(self.jobs_dir, job_id + '.json'))
            except OSError:
                pass
            self._summaries.pop(job_id, None)

    def _summary(self, job_id):
        path = os.path.join(self.jobs_dir, job_id + '.json')
        try:
            st = os.stat(path)
        except OSError:
            return None
        stamp = (st.st_mtime_ns, st.st_size)
        cached = self._summaries.get(job_id)
        if cached and cached[0] == stamp:
            return cached[1]
        doc = self._load(job_id)
        if doc is None:
            return None
        summary = {'job_id': job_id, 'when': int(doc.get('when') or 0), 'seq': int(doc.get('seq') or 0),
                   'album_id': doc.get('album_id'),
                   'album': doc.get('album') or '', 'tracks': int(doc.get('tracks') or len(doc.get('files') or [])),
                   'state': doc.get('state') or 'error', 'undone': bool(doc.get('undone')),
                   'undo_of': doc.get('undo_of')}
        self._summaries[job_id] = (stamp, summary)
        return summary

    def _undoable(self, doc):
        if doc.get('state') not in ('done', 'error') or doc.get('undone'):
            return False
        if self._job is not None and self._job.get('job_id') == doc.get('job_id'):
            return False
        return any(f.get('written') or (doc.get('interrupted') and 'before' in f) for f in doc.get('files') or [])

    def job(self, job_id, lang='en'):
        doc = None
        with self._lock:
            self._recover()
            if self._job is not None and self._job['job_id'] == job_id:
                doc = copy.deepcopy(self._job)
        if doc is None:
            doc = self._load(job_id)
        if doc is None:
            raise TagError('library.jobNotFound', 404)
        errors = []
        for e in doc.get('errors') or []:
            code = e.get('code') or 'library.writeFailed'
            errors.append({'track_id': e.get('track_id'), 'code': code,
                           'message': _t(code, lang, detail=e.get('detail') or '')})
        return {'job_id': doc['job_id'], 'state': doc.get('state'), 'done': doc.get('done', 0),
                'total': doc.get('total', 0), 'errors': errors, 'rescan': doc.get('rescan'),
                'undoable': self._undoable(doc), 'album_id': doc.get('album_id'), 'album': doc.get('album') or '',
                'undo_of': doc.get('undo_of'), 'undone': bool(doc.get('undone')),
                'follow': doc.get('follow'), 'new_album_id': doc.get('new_album_id')}

    def history(self):
        with self._lock:
            self._recover()
            running = copy.deepcopy(self._job) if self._job is not None else None
        try:
            names = [n[:-5] for n in os.listdir(self.jobs_dir) if n.endswith('.json')]
        except OSError:
            names = []
        jobs = []
        for job_id in names:
            if running and running['job_id'] == job_id:
                continue
            s = self._summary(job_id)
            if s:
                jobs.append(dict(s))
        if running:
            jobs.append({'job_id': running['job_id'], 'when': running['when'], 'seq': running['seq'],
                         'album_id': running['album_id'], 'album': running['album'], 'tracks': running['tracks'],
                         'state': 'running', 'undone': False, 'undo_of': running.get('undo_of')})
        jobs.sort(key=lambda j: (j['when'], j['seq'], j['job_id']), reverse=True)
        return {'jobs': [{k: j[k] for k in ('job_id', 'when', 'album_id', 'album', 'tracks', 'state', 'undone',
                                            'undo_of')} for j in jobs[:JOBS_KEEP]]}

    def undo(self, body):
        """Write back what a job journaled, as a new job. A file whose size
        or mtime is not what the job left (changed again since) stops the
        undo unless `force`."""
        body = body if isinstance(body, dict) else {}
        job_id = body.get('job_id')
        force = body.get('force') is True
        if not isinstance(job_id, str) or not _JOB_ID_RE.match(job_id):
            raise TagError('library.jobNotFound', 404)
        if not self.is_local():
            raise TagError('library.remoteServer', 409)
        with self._lock:
            self._recover()
            running = self._job is not None
        doc = self._load(job_id)
        if doc is None:
            raise TagError('library.jobNotFound', 404)
        if running:
            raise TagError('library.busy', 409)
        if not self._undoable(doc):
            raise TagError('library.notUndoable', 409)
        writer_map = writers()
        files, changed = [], []
        for f in doc.get('files') or []:
            before = f.get('before')
            if not isinstance(before, dict):
                continue
            if not f.get('written') and not doc.get('interrupted'):
                continue        # its write failed: nothing to put back
            real = confine(f.get('path'), self.roots)
            if real is None or real != f.get('path'):
                raise TagError('library.trackNotWritable', 409, track_id=f.get('track_id'), reason='outside_sources')
            if not os.path.isfile(real):
                changed.append(f.get('track_id'))
                continue        # gone: nothing can be written back, even with force
            if f.get('written'):
                st = os.stat(real)
                if st.st_size != f.get('size') or st.st_mtime_ns != f.get('mtime_ns'):
                    changed.append(f.get('track_id'))
            else:
                # Interrupted before this file's result was saved: what the
                # file holds tells whether it was written.
                try:
                    now = read_file(real, f['format'])['tags']
                except FileTagError:
                    changed.append(f.get('track_id'))
                    continue
                current = {k: (now.get(k) or None) for k in before}
                if current == before:
                    continue
                intended = {k: (f['set'].get(k) or (None if k in f['remove'] else before.get(k))) for k in before}
                if current != intended:
                    changed.append(f.get('track_id'))
            _real, reason = self.access(real, f.get('format'), False, writer_map)
            if reason:
                raise TagError('library.trackNotWritable', 409, track_id=f.get('track_id'), reason=reason)
            files.append({'track_id': f.get('track_id'), 'path': real, 'format': f.get('format'),
                          'url': f.get('url') or '',
                          'set': {k: v for k, v in before.items() if v},
                          'remove': sorted(k for k, v in before.items() if not v)})
        if changed and not force:
            raise TagError('library.changed_since', 409, count=len(changed), changed=changed)
        if not files:
            raise TagError('library.notUndoable', 409)
        # the album the files are in now (a rename moved them), for following them back
        current_id = doc.get('new_album_id') or doc.get('album_id')
        before = None
        try:
            a = self._lyrion_album(current_id) if current_id is not None else None
            if a is not None:
                before = {'album_id': current_id, 'title': a.get('album') or '', 'artist': a.get('artist') or '',
                          'track_count': len(self._album_tracks(current_id))}
        except hm.LyrionError:
            before = None
        return self._start_job(current_id, doc.get('album') or '', files, undo_of=job_id, before=before)


# ── Flask wiring ─────────────────────────────────────────────────────
_service = None
_service_lock = threading.Lock()


def get_service(roots=None):
    global _service
    with _service_lock:
        if _service is None:
            _service = TagService(roots=roots or DEFAULT_ROOTS)
        return _service


def init_app(app, require_auth, roots=None, service_getter=None):
    """Mount /api/library/* on a Flask app. `require_auth()` returns None or
    the response to send back (sources_server's _require_pair_token); `roots`
    are the folders music may be written in (its ALLOWED_LOCAL_ROOTS)."""
    from flask import Response, jsonify, request

    svc = service_getter or (lambda: get_service(roots))

    def lang():
        return hm.request_lang(request)

    def fail(code, status=400, **fields):
        variables = dict(fields)
        if 'reason' in fields:
            variables['reason'] = _t('library.reason.' + str(fields['reason']), lang())
        body = {'success': False, 'code': code, 'message': _t(code, lang(), **variables)}
        body.update(fields)
        return jsonify(body), status

    def guard(fn):
        def wrapper(*a, **kw):
            denied = require_auth()
            if denied:
                return denied
            try:
                return fn(*a, **kw)
            except TagError as e:
                return fail(e.code, e.status, **e.fields)
            except hm.LyrionError as e:
                _log(f'{request.path}: lyrion: {e}')
                return fail('library.lyrionUnreachable', 502)
            except Exception as e:  # noqa: BLE001
                _log(f'{request.path} failed: {type(e).__name__}: {e}')
                return fail('library.writeFailed', 500, detail=f'{type(e).__name__}')
        wrapper.__name__ = 'library_' + fn.__name__
        return wrapper

    def int_arg(name, default, lo, hi):
        try:
            value = int(request.args.get(name, default))
        except (TypeError, ValueError):
            raise TagError('library.badRequest')
        return max(lo, min(hi, value))

    def query():
        return hm.clean_text(request.args.get('q') or '')[:100]

    @app.route('/api/library/status', methods=['GET'])
    @guard
    def status():
        return jsonify(svc().status())

    @app.route('/api/library/albums', methods=['GET'])
    @guard
    def albums():
        artist_id = request.args.get('artist_id')
        if artist_id not in (None, '') and not str(artist_id).isdigit():
            raise TagError('library.badRequest')
        return jsonify(svc().albums(query(), int_arg('offset', 0, 0, 10 ** 7), int_arg('limit', 60, 1, 500),
                                    int(artist_id) if artist_id not in (None, '') else None))

    @app.route('/api/library/artists', methods=['GET'])
    @guard
    def artists():
        return jsonify(svc().artists(query(), int_arg('offset', 0, 0, 10 ** 7), int_arg('limit', 100, 1, 500)))

    @app.route('/api/library/cover/<cover_id>', methods=['GET'])
    @guard
    def cover(cover_id):
        got = svc().cover(cover_id, int_arg('size', 300, 32, 1200))
        if got is None:
            return fail('library.noCover', 404)
        data, ctype = got
        resp = Response(data, mimetype=ctype.split(';')[0].strip() or 'application/octet-stream')
        resp.headers['Cache-Control'] = 'private, max-age=3600'
        return resp

    @app.route('/api/library/album', methods=['GET'])
    @guard
    def album():
        raw = request.args.get('album_id') or ''
        if not raw.isdigit():
            raise TagError('library.albumRequired')
        return jsonify(svc().album(int(raw)))

    @app.route('/api/library/album/tags', methods=['POST'])
    @guard
    def album_tags():
        return jsonify(svc().start_tags(request.get_json(silent=True)))

    @app.route('/api/library/job', methods=['GET'])
    @guard
    def job():
        job_id = request.args.get('id') or ''
        if not _JOB_ID_RE.match(job_id):
            raise TagError('library.jobNotFound', 404)
        return jsonify(svc().job(job_id, lang()))

    @app.route('/api/library/history', methods=['GET'])
    @guard
    def history():
        return jsonify(svc().history())

    @app.route('/api/library/undo', methods=['POST'])
    @guard
    def undo():
        return jsonify(svc().undo(request.get_json(silent=True)))
