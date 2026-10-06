#!/usr/bin/env python3
"""CD ripping settings and helpers, shared by sources_server.py (the API and
the auto-start monitor) and hifi-rip-cd.py (the worker).

The settings live in /etc/hifi-player/cdrip.json and mirror Daphile's CD
Ripping page, field by field:

  enabled          CD ripping on at all (the banner, the auto-start)
  target           default destination folder, absolute, inside a writable
                   source ("" = the single writable source, or ask)
  dir_prefix       a folder under the target the albums go into ("" = none)
  auto_start       off | if_tags | always — start by itself when a disc is
                   inserted (if_tags: only when MusicBrainz knows the disc)
  format           flac | wav; flac_compression 0..8
  retries          "inaccurate retries": a track is read again until two reads
                   agree (0 = read once and trust it; 1, 2 or 5 extra reads)
  pre_emphasis     ignore | tag | filter — what to do with a track the TOC
                   flags as pre-emphasised: nothing, a PRE_EMPHASIS tag, or
                   SoX's de-emphasis filter on the audio
  clean_names      file names stripped of special and non-ASCII characters
  replaygain       ReplayGain computed and tagged (FLAC only)
  log_file         a ripping log next to the album
  eject            eject after a successful rip
  speed            drive speed forced (0 = the drive's own maximum)
  offset           read offset in samples (AccurateRip's drive offset)
  paranoia         cdparanoia's error correction on (off = plain reads)
"""
import json
import os
import re
import stat
import struct
import time
import unicodedata
import urllib.request
import zlib

CONF = '/etc/hifi-player/cdrip.json'
CD_DEVICE = '/dev/cdrom'
OFFSETS_URL = 'http://www.accuraterip.com/driveoffsets.htm'

DEFAULTS = {
    'enabled': True,
    'target': '',
    'dir_prefix': '',
    'auto_start': 'off',
    'format': 'flac',
    'flac_compression': 5,
    'retries': 2,
    'pre_emphasis': 'ignore',
    'clean_names': True,
    'replaygain': True,
    'log_file': True,
    'eject': True,
    'speed': 0,
    'offset': 0,
    'paranoia': True,
}
AUTO_START = ('off', 'if_tags', 'always')
FORMATS = ('flac', 'wav')
RETRIES = (0, 1, 2, 5)
PRE_EMPHASIS = ('ignore', 'tag', 'filter')
SPEEDS = (0, 4, 8, 16, 24, 32, 48)

_SEGMENT_RE = re.compile(r'^[^\x00-\x1f<>:"/\\|?*]{1,60}$')


def clean_prefix(value):
    """The directory prefix as 'a' or 'a/b' (a folder, maybe nested, under the
    target): empty for none, None when a segment is not a plain folder name."""
    parts = [p.strip() for p in str(value or '').replace('\\', '/').split('/')]
    parts = [p for p in parts if p]
    if any(p in ('.', '..') or not _SEGMENT_RE.match(p) for p in parts):
        return None
    return '/'.join(parts)


class InvalidField(ValueError):
    def __init__(self, field, detail=''):
        super().__init__(f'{field} {detail}'.strip())
        self.field, self.detail = field, detail


def normalize(settings):
    """A complete, clean settings dict from whatever was read (lenient)."""
    src = settings if isinstance(settings, dict) else {}
    s = dict(DEFAULTS)
    s['enabled'] = bool(src.get('enabled', True))
    target = str(src.get('target') or '').strip()
    s['target'] = target if target.startswith('/') and '\x00' not in target else ''
    s['dir_prefix'] = clean_prefix(src.get('dir_prefix')) or ''
    s['auto_start'] = src.get('auto_start') if src.get('auto_start') in AUTO_START else 'off'
    s['format'] = src.get('format') if src.get('format') in FORMATS else 'flac'
    try:
        level = int(src.get('flac_compression', 5))
    except (TypeError, ValueError):
        level = 5
    s['flac_compression'] = level if 0 <= level <= 8 else 5
    try:
        retries = int(src.get('retries', 2))
    except (TypeError, ValueError):
        retries = 2
    s['retries'] = retries if retries in RETRIES else 2
    s['pre_emphasis'] = src.get('pre_emphasis') if src.get('pre_emphasis') in PRE_EMPHASIS else 'ignore'
    for key in ('clean_names', 'replaygain', 'log_file', 'eject', 'paranoia'):
        s[key] = bool(src.get(key, DEFAULTS[key]))
    try:
        speed = int(src.get('speed', 0))
    except (TypeError, ValueError):
        speed = 0
    s['speed'] = speed if speed in SPEEDS else 0
    try:
        offset = int(src.get('offset', 0))
    except (TypeError, ValueError):
        offset = 0
    s['offset'] = offset if -5000 <= offset <= 5000 else 0
    return s


def set_fields(settings, changes):
    """Strict partial update: raises InvalidField on a value the page should
    never have sent. `target` is only checked for shape here; whether it is
    inside a writable source is the server's business."""
    s = normalize(settings)
    for key, value in (changes or {}).items():
        if key not in DEFAULTS:
            raise InvalidField(key, 'unknown')
        if key in ('enabled', 'clean_names', 'replaygain', 'log_file', 'eject', 'paranoia'):
            if not isinstance(value, bool):
                raise InvalidField(key, str(value))
        elif key == 'target':
            value = str(value or '').strip()
            if value and (not value.startswith('/') or '\x00' in value):
                raise InvalidField(key, value)
        elif key == 'dir_prefix':
            cleaned = clean_prefix(value)
            if cleaned is None:
                raise InvalidField(key, str(value))
            value = cleaned
        elif key == 'auto_start':
            if value not in AUTO_START:
                raise InvalidField(key, str(value))
        elif key == 'format':
            if value not in FORMATS:
                raise InvalidField(key, str(value))
        elif key == 'flac_compression':
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 8:
                raise InvalidField(key, str(value))
        elif key == 'retries':
            if not isinstance(value, int) or isinstance(value, bool) or value not in RETRIES:
                raise InvalidField(key, str(value))
        elif key == 'pre_emphasis':
            if value not in PRE_EMPHASIS:
                raise InvalidField(key, str(value))
        elif key == 'speed':
            if not isinstance(value, int) or isinstance(value, bool) or value not in SPEEDS:
                raise InvalidField(key, str(value))
        elif key == 'offset':
            if not isinstance(value, int) or isinstance(value, bool) or not -5000 <= value <= 5000:
                raise InvalidField(key, str(value))
        s[key] = value
    return s


def load(path=CONF):
    try:
        with open(path, encoding='utf-8') as f:
            return normalize(json.load(f))
    except (OSError, ValueError):
        return normalize({})


def save(settings, path=CONF):
    s = normalize(settings)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(s, f, indent=2, sort_keys=True)
        f.write('\n')
    os.replace(tmp, path)
    return s


# ── Who owns what a rip writes ───────────────────────────────────────
# The worker runs as root, but music folders belong to the account the
# network shares write as, in the group Lyrion has in common with it (see
# SAMBA_USER / SHARE_GROUP in sources_server.py). Anything left root-owned
# plays fine but cannot be renamed or deleted from a PC on the network.
SHARE_USER = 'hifimusic'
SHARE_GROUP = 'hifishare'


def share_owner(user=SHARE_USER, group=SHARE_GROUP):
    """(uid, gid) rips are handed to, or None when the account is missing
    (a development machine): the shared group's gid, else the user's own."""
    import grp
    import pwd
    try:
        ent = pwd.getpwnam(user)
    except KeyError:
        return None
    try:
        gid = grp.getgrnam(group).gr_gid
    except KeyError:
        gid = ent.pw_gid
    return ent.pw_uid, gid


def parents_within(root, dest):
    """`dest` and its parent folders up to, not including, `root`: the
    prefix and artist folders a rip creates on the way to the album. Empty
    when dest is not inside root."""
    root = os.path.realpath(root)
    p = os.path.realpath(dest)
    out = []
    while p != root and p.startswith(root + os.sep):
        out.append(p)
        p = os.path.dirname(p)
    return out


def hand_over(path, owner, from_uids=(0,)):
    """Give `path` to the share account: an entry owned by one of `from_uids`
    (root, i.e. the rip worker) becomes owner's, every entry takes the shared
    group, folders get setgid + group write (2775) and files group write
    (0664) — the shape sources_server gives a published folder. Symlinks are
    left alone. Filesystems without POSIX ownership (FAT, exFAT, NTFS, SMB)
    refuse and are ignored: their mount options already fix uid and gid.
    Returns True when something changed."""
    if not owner:
        return False
    uid, gid = owner
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return False
    changed = False
    want_uid = uid if st.st_uid in from_uids else st.st_uid
    try:
        if want_uid != st.st_uid or st.st_gid != gid:
            os.chown(path, want_uid, gid)
            changed = True
        bits = st.st_mode & 0o7777
        want = bits | (0o2775 if stat.S_ISDIR(st.st_mode) else 0o664)
        if want != bits:
            os.chmod(path, want)
            changed = True
    except OSError:
        pass
    return changed


def hand_over_tree(root, dest, owner, from_uids=(0,), limit=None, skip_names=()):
    """hand_over() for `dest`, everything under it and the folders between
    `dest` and `root` — the whole path a rip made, not just the album. `root`
    itself (the destination the user chose) is never touched. `limit` bounds
    the walk; entries named in `skip_names` (lost+found) are left out, with
    whatever is under them. Returns how many entries changed."""
    if not owner:
        return 0
    n = 0
    for p in parents_within(root, dest):
        n += hand_over(p, owner, from_uids)
    if os.path.isdir(dest):
        seen = 0
        for dirpath, dirnames, filenames in os.walk(dest):
            if skip_names:
                dirnames[:] = [d for d in dirnames if d not in skip_names]
                filenames = [f for f in filenames if f not in skip_names]
            for name in dirnames + filenames:
                seen += 1
                if limit is not None and seen > limit:
                    return n
                n += hand_over(os.path.join(dirpath, name), owner, from_uids)
    return n


# ── The drive ───────────────────────────────────────────────────────
def drive_info(device=CD_DEVICE, sys_block='/sys/block'):
    """Vendor, model and node of the optical drive behind `device`, the way
    Daphile heads its per-drive box: "HL-DT-ST - DVDRW GX50N (sr0)"."""
    try:
        node = os.path.basename(os.path.realpath(device))
    except OSError:
        node = ''
    info = {'device': device, 'node': node, 'vendor': '', 'model': '', 'present': False}
    if not node:
        return info
    base = os.path.join(sys_block, node, 'device')
    for key in ('vendor', 'model'):
        try:
            with open(os.path.join(base, key), encoding='utf-8', errors='replace') as f:
                info[key] = ' '.join(f.read().split())
        except OSError:
            pass
    info['present'] = bool(info['vendor'] or info['model']) or os.path.exists(os.path.join(sys_block, node))
    parts = [p for p in (info['vendor'], info['model']) if p]
    info['label'] = (' - '.join(parts) if parts else node) + (f' ({node})' if parts else '')
    return info


# ── AccurateRip's drive offset list ─────────────────────────────────
# The page names some vendors differently from what the drive itself says.
VENDOR_ALIASES = {
    'HL-DT-ST': 'LG Electronics',
    'HL-DT-STDVD': 'LG Electronics',
    'JLMS': 'Lite-ON',
    'MATSHITA': 'Panasonic',
    'TSSTCORP': 'TSSTcorp',
}


def parse_offsets_html(html):
    """Rows of the offsets table: [(drive, offset_or_None, submitted, agree)].
    The page is an old FrontPage table: one <tr> per drive, four <td>."""
    rows = []
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', html or '', re.S | re.I):
        cells = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S | re.I)
        if len(cells) != 4:
            continue
        text = [' '.join(re.sub(r'<[^>]+>', '', c).replace('&nbsp;', ' ').replace('&amp;', '&').split()) for c in cells]
        drive, offset, submitted, agree = text
        if not drive or drive.startswith('CD Drive') or '\n' in cells[0] and 'Correction Offset' in tr:
            continue
        m = re.match(r'^([+-]?\d+)$', offset)
        rows.append((drive, int(m.group(1)) if m else None, submitted, agree))
    return rows


def _norm(s):
    return ' '.join(str(s or '').upper().split())


def find_offset(rows, vendor, model):
    """The row for a drive, matched as AccurateRip spells it. Returns
    (drive_name, offset, submitted, agree) or None. Prefers the exact
    "<vendor> - <model>" line (vendor aliased), then any line ending in the
    model, the one with most submissions first."""
    model_n = _norm(model)
    if not model_n:
        return None
    vendors = {_norm(vendor)}
    alias = VENDOR_ALIASES.get(str(vendor or '').strip().upper())
    if alias:
        vendors.add(_norm(alias))
    exact, loose = [], []
    for row in rows:
        name = _norm(row[0])
        if ' - ' in name:
            v, _, m = name.partition(' - ')
        else:
            v, m = '', name.lstrip('- ').strip()
        if m == model_n:
            (exact if v in vendors else loose).append(row)
    def submissions(row):
        try:
            return int(re.sub(r'\D', '', row[2]) or 0)
        except ValueError:
            return 0
    for group in (exact, loose):
        if group:
            return max(group, key=submissions)
    return None


def fetch_offsets(url=OFFSETS_URL, timeout=25):
    req = urllib.request.Request(url, headers={'User-Agent': 'Osmium Sound (CD ripping; +https://osmiumsound.it)'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(6 * 1024 * 1024).decode('cp1252', errors='replace')


def lookup_offset(vendor, model, fetch=None):
    """{'found': True, 'offset': 6, 'drive': 'LG Electronics - DVDRW GX50N',
    'submitted': '288', 'agree': '100%'} — or found False; raises on a network
    error so the caller can say "could not reach" apart from "not listed"."""
    rows = parse_offsets_html((fetch or fetch_offsets)())   # looked up at call time: tests swap it
    row = find_offset(rows, vendor, model)
    if not row or row[1] is None:
        return {'found': False, 'drive': row[0] if row else '', 'purged': bool(row)}
    return {'found': True, 'offset': row[1], 'drive': row[0], 'submitted': row[2], 'agree': row[3]}


# ── TOC with the pre-emphasis flag (cdparanoia -Q) ──────────────────
_TOC_RE = re.compile(r'^\s*(\d+)\.\s+(\d+)\s+\[[^\]]*\]\s+(\d+)\s+\[[^\]]*\]\s+(\S+)\s+(\S+)\s+(\d+)\s*$')


def parse_cdparanoia_toc(text):
    """`cdparanoia -Q` prints, per track: number, length and begin in frames
    (with mm:ss.ff), then the copy-permitted, pre-emphasis and channel
    columns. Returns {num: {'length': frames, 'begin': frames, 'copy': bool,
    'pre': bool, 'channels': int}}."""
    toc = {}
    for line in (text or '').splitlines():
        m = _TOC_RE.match(line)
        if not m:
            continue
        toc[int(m.group(1))] = {
            'length': int(m.group(2)), 'begin': int(m.group(3)),
            'copy': m.group(4).lower() == 'yes', 'pre': m.group(5).lower() == 'yes',
            'channels': int(m.group(6)),
        }
    return toc


# ── Data tracks (Enhanced CD, mixed mode) ───────────────────────────
# An "Enhanced" CD carries its audio tracks and then, in a second session, a
# data track (videos, a web page). Nothing used to tell the two apart: the
# rip plan included the data track, cdparanoia refused it ("non audio
# track"), and the failure threw away every audio track already read. The
# MusicBrainz disc id came out wrong as well, since MusicBrainz leaves the
# trailing data track out and ends the disc 11400 frames (the gap between
# the two sessions) before it starts.
CDROMREADTOCHDR = 0x5305
CDROMREADTOCENTRY = 0x5306
CDROM_LBA = 0x01
CDROM_DATA_TRACK = 0x04
SESSION_GAP_FRAMES = 11400
_TOCENTRY = struct.Struct('=BBBxiB3x')     # struct cdrom_tocentry, 12 bytes


def parse_tocentry(buf):
    """(track, control bits, LBA) of one CDROMREADTOCENTRY answer. The
    control nibble is the upper half of the second byte (cdte_ctrl:4 after
    cdte_adr:4, filled from the low bits up)."""
    track, adr_ctrl, _fmt, lba, _mode = _TOCENTRY.unpack(bytes(buf[:_TOCENTRY.size]))
    return track, (adr_ctrl >> 4) & 0x0f, lba


def read_data_tracks(device=CD_DEVICE):
    """Numbers of the tracks that carry data rather than audio, read from the
    TOC's control bits with the same ioctls cd-discid uses — no tool to run,
    nothing to spin up. None when the TOC cannot be read."""
    import fcntl
    try:
        fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        hdr = bytearray(2)
        fcntl.ioctl(fd, CDROMREADTOCHDR, hdr)
        first, last = hdr[0], hdr[1]
        if not 1 <= first <= last <= 99:
            return None
        data = []
        for n in range(first, last + 1):
            buf = bytearray(_TOCENTRY.pack(n, 0, CDROM_LBA, 0, 0))
            fcntl.ioctl(fd, CDROMREADTOCENTRY, buf)
            _track, ctrl, _lba = parse_tocentry(buf)
            if ctrl & CDROM_DATA_TRACK:
                data.append(n)
        return data
    except OSError:
        return None
    finally:
        os.close(fd)


def audio_toc(offsets, leadout, data_tracks):
    """The disc as MusicBrainz sees it, and which tracks can be ripped.

    `offsets` (frames, lead-in included) and `leadout` describe every track
    from 1, as cd-discid prints them; `data_tracks` are the numbers of the
    data tracks. Trailing data tracks are dropped from the TOC and the disc
    ends SESSION_GAP_FRAMES before the first of them (libdiscid's rule); a
    data track anywhere else stays in the TOC, as it does on MusicBrainz, but
    is not ripped. Returns {'offsets', 'leadout', 'tracks'} with `tracks` the
    audio track numbers."""
    n = len(offsets)
    data = {int(t) for t in data_tracks or () if 1 <= int(t) <= n}
    keep = n
    while keep > 1 and keep in data:
        keep -= 1
    offsets = list(offsets)
    if keep < n:
        end = offsets[keep] - SESSION_GAP_FRAMES
        # a single-session disc has no gap to take off
        leadout = end if end > offsets[keep - 1] else offsets[keep]
        offsets = offsets[:keep]
    tracks = [t for t in range(1, keep + 1) if t not in data]
    return {'offsets': offsets, 'leadout': leadout, 'tracks': tracks}


_NON_AUDIO_RE = re.compile(r'non[- ]?audio|data track', re.IGNORECASE)


def is_non_audio_error(text):
    """True for cdparanoia's refusal of a data track ("Selected span
    contains non audio track")."""
    return bool(_NON_AUDIO_RE.search(text or ''))


def frames_to_msf(frames):
    frames = max(0, int(frames))
    return f'{frames // (75 * 60):02d}:{(frames // 75) % 60:02d}.{frames % 75:02d}'


# ── File names ──────────────────────────────────────────────────────
def safe_name(value, fallback, ascii_only=False):
    """A file or folder name that is fine on ext4, exFAT and SMB. With
    `ascii_only` (the "clean up all special & non ASCII characters" switch)
    accents are folded to their base letter and anything but letters, digits,
    space, dot, dash, underscore, parentheses and the ampersand goes."""
    v = str(value or '')
    if ascii_only:
        folded = unicodedata.normalize('NFKD', v).encode('ascii', 'ignore').decode('ascii')
        # A title in a script with no Latin form (Japanese, Cyrillic, Greek…)
        # folds to nothing or to a stray digit. Keep it as written then:
        # otherwise every such disc becomes "Unknown Album" and the next rip
        # lands on top of the last one.
        kept = sum(c.isalnum() for c in folded)
        if kept and kept * 2 >= sum(c.isalnum() for c in v):
            v = re.sub(r"[^A-Za-z0-9 ._\-()&',]", '_', folded)
            v = re.sub(r'_+', '_', v)
    v = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', v)
    v = ' '.join(v.split())[:120]
    # ext4 counts bytes, not characters: 120 kana are 360 bytes and flac or
    # makedirs fail with ENAMETOOLONG. 200 leaves room for "NN - " and ".flac".
    while len(v.encode('utf-8')) > 200:
        v = v[:-1]
    return v.strip(' .') or fallback


def unused_dir(path):
    """`path`, or "path (2)", "path (3)"… when a folder with something in it
    is already there. A second disc with the same artist and title — two
    unknown discs both named "Unknown Album", a reissue — gets a folder of its
    own instead of replacing the files of the first."""
    def taken(p):
        try:
            return os.path.lexists(p) and (not os.path.isdir(p) or bool(os.listdir(p)))
        except OSError:
            return True
    if not taken(path):
        return path
    for n in range(2, 1000):
        cand = f'{path} ({n})'
        if not taken(cand):
            return cand
    return f'{path} ({int(time.time())})'


# ── The audio of a WAV, for the log ─────────────────────────────────
def wav_crc32(path):
    """CRC32 of the PCM samples of a RIFF/WAVE file (what EAC calls the copy
    CRC), or None when the file is not a WAV. Streams: a track is ~50 MB."""
    crc = 0
    try:
        with open(path, 'rb') as f:
            head = f.read(12)
            if len(head) < 12 or head[:4] != b'RIFF' or head[8:12] != b'WAVE':
                return None
            while True:
                ch = f.read(8)
                if len(ch) < 8:
                    return None
                cid, size = ch[:4], struct.unpack('<I', ch[4:8])[0]
                if cid == b'data':
                    left = size
                    while left > 0:
                        buf = f.read(min(1 << 20, left))
                        if not buf:
                            break
                        crc = zlib.crc32(buf, crc)
                        left -= len(buf)
                    return crc & 0xFFFFFFFF
                f.seek(size + (size & 1), 1)
    except OSError:
        return None
