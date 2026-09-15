#!/usr/bin/env python3
"""Osmium Sound — album and artist information from the web.

Credits by role come from MusicBrainz, descriptions and biographies from
Wikipedia. sources_server.py mounts the /api/meta/* routes from here (see
init_app) and the CD ripper borrows the MusicBrainz client and the TOC helpers
(cd_* below), so there is one User-Agent, one rate limit and one back-off for
every request this device sends to MusicBrainz.

🚨 Licensing (the project also sells commercial licences): from MusicBrainz
only the CC0 core data is used — releases, recordings, works, artists,
relationships, URLs, labels, places. Never genres, tags, ratings or
annotations: those are CC BY-NC-SA and must not even be requested (no `inc=`
for them anywhere in this file). Wikipedia text is CC BY-SA and always travels
with its source, URL and licence so the screens can attribute it. No other
metadata service (Last.fm, fanart.tv, TheAudioDB, AcoustID, Discogs) is used.

Shape of the thing:
  * HttpClient — throttled JSON GETs: MusicBrainz at most one request every
    1.1 s, Wikimedia a little spacing, exponential back-off on 503/429, a
    short "offline" circuit so a device without internet does not retry in a
    loop, gzip, a size cap.
  * Lyrion — the few JSON-RPC queries needed, against whichever server the
    device follows (squeezelite's -s), or HIFI_META_LMS_URL.
  * Cache — SQLite in /var/lib/hifi-player/metadata (HIFI_META_CACHE_DIR):
    60 days for data, 7 for "not found", a size cap with least-recently-used
    eviction, manual pins kept when the cache is cleared.
  * MetadataService — the HTTP handlers never touch the network: they answer
    from the cache or say `pending` and queue a job for the single worker
    thread (interactive requests first, the background prefetch last).
"""
import base64
import gzip
import hashlib
import heapq
import http.client
import itertools
import json
import os
import re
import socket
import sqlite3
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

# ── configuration ────────────────────────────────────────────────────
CACHE_DIR = '/var/lib/hifi-player/metadata'
ETC_DIR = '/etc/hifi-player'
SQUEEZELITE_DEFAULT = '/etc/default/squeezelite'
VERSION_FILES = ('/etc/hifi-player/UI_VERSION', '/opt/hifi-media-player/UI_VERSION',
                 '/usr/lib/osmium/IMAGE_VERSION')

MB_BASE = 'https://musicbrainz.org/ws/2'
MB_WEB = 'https://musicbrainz.org'
WIKIDATA_API = 'https://www.wikidata.org/w/api.php'
CONTACT = 'https://osmiumsound.it ; info@osmiumsound.it'

MB_SPACING = 1.1          # MusicBrainz asks for at most one request per second
WIKI_SPACING = 0.5
OFFLINE_HOLD = 30.0       # after a network failure, fail fast for this long
MAX_BODY = 8 * 1024 * 1024

DATA_TTL = 60 * 86400
NEGATIVE_TTL = 7 * 86400
FAILURE_HOLD = 60.0       # a failed job is reported (offline/error) this long
BUSY_RETRY = 10.0         # a job that found MusicBrainz busy is tried again after this
CACHE_MAX_BYTES = 100 * 1024 * 1024

PRIO_INTERACTIVE = 0
PRIO_BACKGROUND = 5
PRIO_PREFETCH = 9

PREFETCH_START_DELAY = 120
PREFETCH_ALBUM_GAP = 12
PREFETCH_RELIST = 4 * 3600

ABOUT_MAX_CHARS = 5000

# The release lookup that feeds an album page (and the CD ripper's tags):
# every credit on the release, its recordings and their works in one request.
RELEASE_INC = ('recordings+artist-credits+labels+release-groups+isrcs+artist-rels+place-rels'
               '+label-rels+url-rels+work-rels+recording-level-rels+work-level-rels'
               '+release-group-level-rels')
# discid lookups refuse the *-level-rels includes.
DISCID_INC = 'artist-credits+recordings+release-groups+labels+isrcs'
ARTIST_INC = 'url-rels+artist-rels+aliases'

UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I)
QID_RE = re.compile(r'^Q[0-9]+$')
VARIOUS_ARTISTS_MBID = '89ad4ac3-39f7-470e-963a-56509c546377'


def _log(msg):
    print(f'[meta] {msg}', flush=True)


# ── version and User-Agent ───────────────────────────────────────────
_version_cache = {'value': None, 'at': 0.0}


def app_version():
    """The installed interface version (what the OTA updater reads), without
    the leading `v` of the tag; the repo's package.json when running from a
    checkout. Re-read every ten minutes: an interface update changes it
    without restarting this service."""
    now = time.monotonic()
    if _version_cache['value'] and now - _version_cache['at'] < 600:
        return _version_cache['value']
    value = ''
    for path in VERSION_FILES:
        try:
            with open(path) as f:
                value = f.read().strip()
        except OSError:
            continue
        if value and value != 'unknown':
            break
        value = ''
    if not value:
        try:
            here = os.path.dirname(os.path.abspath(__file__))
            with open(os.path.join(here, 'package.json')) as f:
                value = str(json.load(f).get('version') or '')
        except (OSError, ValueError):
            value = ''
    value = re.sub(r'[^0-9A-Za-z.+-]', '', value.lstrip('vV')) or 'unknown'
    _version_cache.update(value=value, at=now)
    return value


def user_agent():
    return f'OsmiumSound/{app_version()} ( {CONTACT} )'


# ── HTTP client ──────────────────────────────────────────────────────
class OfflineError(Exception):
    """The network (or the service's host) cannot be reached."""


class NotFoundError(Exception):
    """HTTP 404: the entity does not exist (or no longer does)."""


class HttpError(Exception):
    def __init__(self, status, message=''):
        super().__init__(message or f'HTTP {status}')
        self.status = status


class HttpClient:
    """Throttled JSON GETs shared by every caller in the process.

    Spacing is kept per host group ('mb', 'wiki') as the next moment a request
    may leave; callers reserve their slot under the lock and sleep outside it,
    so a request waiting its turn never blocks anybody else's bookkeeping. A
    503/429 pushes the whole group back (MusicBrainz answers 503 even at about
    one request per second when it is busy), then the request is retried with
    exponential back-off. A transport failure (DNS, no route, refused, connect
    timeout) opens a short circuit: for OFFLINE_HOLD seconds every call fails
    at once with OfflineError instead of hammering a dead link."""

    SPACING = {'mb': MB_SPACING, 'wiki': WIKI_SPACING}

    def __init__(self, urlopen=None, clock=None, sleep=None):
        self._urlopen = urlopen or urllib.request.urlopen
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._lock = threading.Lock()
        self._next = {}
        self._offline_until = 0.0

    def offline(self):
        return self._clock() < self._offline_until

    def reset(self):
        with self._lock:
            self._offline_until = 0.0

    def _reserve(self, group, max_wait, check=None):
        spacing = self.SPACING.get(group, 1.0)
        with self._lock:
            now = self._clock()
            slot = max(now, self._next.get(group, 0.0))
            if max_wait is not None and slot - now > max_wait:
                raise HttpError(0, 'busy: rate limit slot too far away')
            self._next[group] = slot + spacing
        # In steps, so a caller that is told to stop (the setting was switched
        # off, something more urgent came in) does not sit out a long back-off.
        while True:
            left = slot - self._clock()
            if left <= 0:
                break
            if check is not None:
                check()
            self._sleep(min(left, 1.0))
        if check is not None:
            check()

    def _push_back(self, group, delay):
        with self._lock:
            self._next[group] = max(self._next.get(group, 0.0), self._clock() + delay)

    def get_json(self, url, group='mb', timeout=20, retries=3, max_wait=None, check=None):
        """`check`, when given, is called while waiting for a slot and may
        raise to abandon the request."""
        if self.offline():
            raise OfflineError('network unreachable (recent failure)')
        delay = 2.0
        attempt = 0
        while True:
            self._reserve(group, max_wait, check)
            req = urllib.request.Request(url, headers={
                'User-Agent': user_agent(),
                'Accept': 'application/json',
                'Accept-Encoding': 'gzip',
            })
            retry = False
            try:
                with self._urlopen(req, timeout=timeout) as resp:
                    raw = resp.read(MAX_BODY + 1)
                    headers = getattr(resp, 'headers', None)
                    encoding = (headers.get('Content-Encoding') or '').lower() if headers is not None else ''
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    raise NotFoundError(url)
                if e.code not in (429, 502, 503, 504) or attempt >= retries:
                    raise HttpError(e.code)
                retry = True
            except urllib.error.URLError as e:
                # DNS failure, no route, refused, or no connection within the
                # timeout: the link is down (or as good as), and waiting for
                # it again and again would only stall the worker.
                self._go_offline()
                raise OfflineError(str(e.reason))
            except (socket.timeout, TimeoutError, http.client.HTTPException):
                # Connected, but the answer did not come (in full) in time:
                # busy rather than offline, so it is retried like a 503.
                if attempt >= retries:
                    raise HttpError(0, 'timeout')
                retry = True
            except OSError as e:
                self._go_offline()
                raise OfflineError(str(e))
            if retry:
                attempt += 1
                self._push_back(group, delay)
                delay *= 2
                continue
            if len(raw) > MAX_BODY:
                raise HttpError(0, 'response too large')
            try:
                if encoding == 'gzip' or raw[:2] == b'\x1f\x8b':
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode('utf-8'))
            except (OSError, EOFError, ValueError) as e:
                raise HttpError(0, f'bad response body: {e}')

    def _go_offline(self):
        with self._lock:
            self._offline_until = self._clock() + OFFLINE_HOLD


CLIENT = HttpClient()


def _qs(params):
    """Query string for MusicBrainz/MediaWiki. `inc` keeps its literal `+`
    separators (an encoded %2B is not a separator for MusicBrainz); every
    other value is fully percent-encoded, spaces included, so a Lucene query
    never has a `+` or `&` of its own misread."""
    parts = []
    for key, value in params.items():
        if value is None:
            continue
        if key == 'inc':
            parts.append(f'inc={value}')
        else:
            parts.append(f'{key}=' + urllib.parse.quote(str(value), safe=''))
    return '&'.join(parts)


def mb_url(path, **params):
    params.setdefault('fmt', 'json')
    return f'{MB_BASE}/{path.lstrip("/")}?{_qs(params)}'


def mb_get(path, client=None, timeout=20, retries=3, max_wait=None, check=None, **params):
    kwargs = {'check': check} if check is not None else {}
    return (client or CLIENT).get_json(mb_url(path, **params), group='mb', timeout=timeout,
                                       retries=retries, max_wait=max_wait, **kwargs)


# ── text helpers ─────────────────────────────────────────────────────
def _fold(text):
    text = unicodedata.normalize('NFKD', str(text or ''))
    return ''.join(c for c in text if not unicodedata.combining(c))


def normalise(text):
    """Comparison form of a title or a name: case, accents, punctuation,
    '&'/'and', a leading or trailing 'The' ("Cranberries, The") all folded."""
    s = _fold(text).lower().replace('&', ' and ')
    s = re.sub(r"[‘’`´']", '', s)
    s = re.sub(r'[^0-9a-z-￿]+', ' ', s).strip()
    s = re.sub(r'^(.*) the$', r'the \1', s)
    s = re.sub(r'^the ', '', s)
    return re.sub(r'\s+', ' ', s)


_EDITION_WORDS = (r'deluxe|edition|editions|remaster|remastered|re-?mastered|re-?master|anniversary|bonus|'
                  r'expanded|version|explicit|clean|reissue|re-?issue|special|collector|collectors|'
                  r'limited|legacy|super|mono|stereo|mixes|remix|remixes|hi-?res|24[- ]?bit|'
                  r'sacd|flac|mp3|disc|cd|lp|ep|single|premastered|bonustracks|tracks|mix|'
                  r'édition|luxe|rimasterizzato|rimasterizzata|versione')
_TRAILING_BRACKET = re.compile(
    r'\s*[\(\[\{][^\(\)\[\]\{\}]*\b(?:' + _EDITION_WORDS + r')\b[^\(\)\[\]\{\}]*[\)\]\}]\s*$', re.I)
_TRAILING_SUFFIXES = [
    re.compile(r'\s*-\s*(?:ep|single)\s*$', re.I),
    re.compile(r'\s*[-,:]?\s*\(?\s*(?:cd|disc|disk)\s*(?:\d+|one|two|three|four|five)\s*\)?\s*\'?$', re.I),
    re.compile(r'\s*[-,:]?\s*\d+(?:st|nd|rd|th)\s+anniversary(?:\s+\w+)*\s*$', re.I),
    re.compile(r'\s*[-,:]?\s*(?:deluxe|expanded|remastered|special|super deluxe|collector\'?s)'
               r'(?:\s+(?:edition|version))?\s*$', re.I),
    re.compile(r'\s*[-,:]?\s*remastered\s+\d{4}\s*$', re.I),
    re.compile(r'\s*\(\([^()]*\)\)\s*$'),
    # "Abbey Road,(Apple Records-AP-8815,Japan)": a vinyl rip's pressing note.
    re.compile(r'\s*,\s*\([^()]*\)\s*$'),
]


def strip_edition(title):
    """The title without edition noise: "(Deluxe Edition)", "- EP",
    "[Remastered]", "30th Anniversary Edition", "(Disc 2)", "CD1"…
    Repeated until nothing more comes off; never returns an empty string."""
    t = str(title or '').strip()
    for _ in range(6):
        before = t
        t = _TRAILING_BRACKET.sub('', t).strip()
        for rx in _TRAILING_SUFFIXES:
            t = rx.sub('', t).strip()
        if t == before:
            break
    return t or str(title or '').strip()


_VARIOUS = {'various artists', 'various', 'va', 'v a', 'aa vv', 'aavv', 'artisti vari', 'vari',
            'various artist', 'verschiedene interpreten', 'varios artistas', 'artistes divers',
            'divers', 'compilation', 'no artist', 'unknown artist'}


def is_various(artist, compilation=False):
    return bool(compilation) or normalise(artist) in _VARIOUS


def fingerprint(title, artist, track_count):
    """Stable key of a library album across rescans (Lyrion's album ids are
    renumbered when the library is wiped and scanned again)."""
    raw = f'{normalise(title)}\x1f{normalise(artist)}\x1f{int(track_count or 0)}'
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:20]


def snake(text):
    return re.sub(r'[^a-z0-9]+', '_', _fold(text).lower()).strip('_')


def lucene_phrase(text):
    return '"' + str(text or '').replace('\\', ' ').replace('"', ' ').strip() + '"'


def lucene_tokens(text):
    """Plain lower-case words: no operators, wildcards or field syntax can
    leak through, and lower case keeps 'and'/'or'/'not' from being read as
    Lucene operators."""
    s = re.sub(r'[+\-&|!(){}\[\]^"~*?:\\/.,;<>=\']', ' ', str(text or '')).lower()
    words = [w for w in s.split() if w]
    return '(' + ' '.join(words) + ')' if words else ''


def artist_credit_text(credit):
    return ''.join((c.get('name') or (c.get('artist') or {}).get('name') or '') + (c.get('joinphrase') or '')
                   for c in credit or []).strip()


def artist_credit_people(credit):
    out = []
    for c in credit or []:
        a = c.get('artist') or {}
        if a.get('id'):
            out.append({'name': a.get('name') or c.get('name') or '', 'mbid': a['id']})
    return out


def format_media(media):
    """"CD", "2×CD", "CD + DVD-Video", "Digital Media"."""
    groups = []
    for m in media or []:
        fmt = m.get('format') or '?'
        if groups and groups[-1][0] == fmt:
            groups[-1][1] += 1
        else:
            groups.append([fmt, 1])
    return ' + '.join((f'{n}×{fmt}' if n > 1 else fmt) for fmt, n in groups)


def labels_text(label_info):
    parts = []
    for li in label_info or []:
        name = (li.get('label') or {}).get('name') or ''
        cat = li.get('catalog-number') or ''
        text = ' / '.join(x for x in (name, cat) if x)
        if text and text not in parts:
            parts.append(text)
    return ', '.join(parts)


def release_summary(rel, score=None):
    """One candidate line (search result, release-group browse or lookup)."""
    media = rel.get('media') or []
    tc = rel.get('track-count')
    if tc is None and media:
        tc = sum(int(m.get('track-count') or len(m.get('tracks') or [])) for m in media)
    rg = rel.get('release-group') or {}
    return {
        'mbid': rel.get('id'),
        'title': rel.get('title') or '',
        'artist': artist_credit_text(rel.get('artist-credit')),
        'date': rel.get('date') or '',
        'country': rel.get('country') or '',
        'labels': labels_text(rel.get('label-info')),
        'format': format_media(media),
        'track_count': tc,
        'media_counts': [int(m.get('track-count') or len(m.get('tracks') or [])) for m in media],
        'media_formats': [m.get('format') or '' for m in media],
        'status': rel.get('status') or '',
        'score': rel.get('score') if score is None else score,
        'release_group': rg.get('id'),
    }


def public_candidate(c):
    return {k: c.get(k) for k in ('mbid', 'title', 'artist', 'date', 'country', 'labels', 'format',
                                  'track_count', 'score', 'release_group')}


# ── matching a library album to a release ────────────────────────────
_VIDEO_FORMATS = ('dvd-video', 'blu-ray', 'dvd', 'hd-dvd', 'vhs', 'videotape', 'laserdisc', 'vcd', 'svcd')


def _is_audio_format(fmt):
    return not any(v == (fmt or '').lower() for v in _VIDEO_FORMATS)


def alignments(track_count, media_counts, media_formats=None):
    """Ways a library album with `track_count` tracks can line up with a
    release whose media have `media_counts` tracks: the whole release, only
    its audio media (a CD+DVD set), or a single medium (one disc of a box set
    kept as its own album). Returns a list of ('all'|'audio'|'medium', pos)."""
    out = []
    counts = [int(c or 0) for c in media_counts or []]
    formats = list(media_formats or [''] * len(counts))
    if not track_count or not counts:
        return out
    if sum(counts) == track_count:
        out.append(('all', None))
    audio = [c for c, f in zip(counts, formats) if _is_audio_format(f)]
    if len(audio) != len(counts) and audio and sum(audio) == track_count:
        out.append(('audio', None))
    if len(counts) > 1:
        for i, c in enumerate(counts):
            if c == track_count:
                out.append(('medium', i + 1))
    return out


def aligned_media(media, mode, position=None):
    """The media of a release selected by one alignment, in order."""
    if mode == 'medium':
        return [m for m in media if int(m.get('position') or 0) == position]
    if mode == 'audio':
        return [m for m in media if _is_audio_format(m.get('format'))]
    return list(media)


def duration_score(lib_seconds, mb_lengths_ms):
    """How well the library's track lengths (seconds, in order) agree with a
    release's (milliseconds, same order). None when the lists differ in length
    or too few lengths are known to judge. Otherwise a dict with `score`
    (0-100), `mean` and `median` absolute difference (s), `within` (share of
    tracks within 5 s) and `coverage` (share of tracks with both lengths)."""
    if not lib_seconds or len(lib_seconds) != len(mb_lengths_ms):
        return None
    diffs = []
    for lib, mb in zip(lib_seconds, mb_lengths_ms):
        if lib and mb:
            diffs.append(abs(float(lib) - float(mb) / 1000.0))
    coverage = len(diffs) / len(lib_seconds)
    if not diffs or coverage < 0.6:
        return None
    mean = sum(diffs) / len(diffs)
    ordered = sorted(diffs)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    within = sum(1 for d in diffs if d <= 5.0) / len(diffs)
    score = 100.0 - min(40.0, median * 10.0) - min(20.0, mean * 2.0) - (1.0 - within) * 40.0 \
        - (1.0 - coverage) * 20.0
    return {'score': max(0, int(round(score))), 'mean': round(mean, 2), 'median': round(median, 2),
            'within': round(within, 3), 'coverage': round(coverage, 3)}


def duration_accepted(ds):
    """Confident enough to show a release's credits for a library album. The
    median carries the decision: editions of one album often move a boundary
    (the 2003 "Dark Side of the Moon" gives 16 s of "Time" to "On the Run"),
    which wrecks the mean of two tracks but not the median, while a different
    album that merely has as many tracks is off on most of them."""
    return bool(ds) and ds['median'] <= 2.5 and ds['within'] >= 0.75 and ds['coverage'] >= 0.6


def best_alignment(lib_tracks, media):
    """Pick the alignment of a looked-up release (media with tracks and
    lengths) that fits the library tracks best. Returns (mode, position,
    duration_score-or-None) or None when no track count lines up."""
    lib_seconds = [t.get('duration') or 0 for t in lib_tracks]
    counts = [int(m.get('track-count') or len(m.get('tracks') or [])) for m in media]
    formats = [m.get('format') or '' for m in media]
    best = None
    for mode, pos in alignments(len(lib_tracks), counts, formats):
        chosen = aligned_media(media, mode, pos)
        lengths = [t.get('length') or (t.get('recording') or {}).get('length')
                   for m in chosen for t in (m.get('tracks') or [])]
        ds = duration_score(lib_seconds, lengths)
        rank = (ds['score'] if ds else -1, mode != 'medium')
        if best is None or rank > best[0]:
            best = (rank, mode, pos, ds)
    if best is None:
        return None
    return best[1], best[2], best[3]


_FORMAT_RANK = {'cd': 0, 'digital media': 0, 'hybrid sacd': 1, 'sacd': 1, 'enhanced cd': 0,
                'hdcd': 0, 'blu-spec cd': 0, 'shm-cd': 0, 'copy control cd': 0}


def rank_candidates(candidates, track_count, year=None):
    """Search results that can line up with the library album (track count),
    most promising first: a whole-release fit before a single-disc one, then
    a good MusicBrainz search score (in bands: 100 and 94 are the same title),
    official releases, CD/digital formats, the release year closest to the
    library's."""
    ranked = []
    for c in candidates:
        modes = alignments(track_count, c.get('media_counts'), c.get('media_formats'))
        if not modes:
            continue
        whole = any(m[0] != 'medium' for m in modes)
        fmts = [f.lower() for f in c.get('media_formats') or []]
        fmt_rank = min([_FORMAT_RANK.get(f, 2) for f in fmts] or [2])
        try:
            ydist = abs(int((c.get('date') or '')[:4]) - int(year)) if year else 50
        except ValueError:
            ydist = 50
        score = c.get('score') or 0
        key = (0 if whole else 1, 0 if score >= 90 else (1 if score >= 75 else 2),
               0 if c.get('status') == 'Official' else 1, fmt_rank, min(ydist, 50), -score)
        ranked.append((key, c))
    ranked.sort(key=lambda kc: kc[0])
    return [c for _, c in ranked]


def edition_shape(c):
    """What tells editions apart before looking them up: year, formats and
    track layout. Reissues pressed from one master share all three — and
    their track lengths — so looking up a second one teaches nothing."""
    return ((c.get('date') or '')[:4], tuple(c.get('media_formats') or ()), tuple(c.get('media_counts') or ()))


def diverse(ranked, n, seen_shapes=()):
    """The first `n` candidates of `ranked`, skipping ones shaped like an
    edition already picked (see edition_shape) while others remain."""
    if n <= 0:
        return []
    picked, shapes = [], set(seen_shapes)
    for c in ranked:
        if edition_shape(c) not in shapes:
            picked.append(c)
            shapes.add(edition_shape(c))
            if len(picked) == n:
                return picked
    for c in ranked:
        if c not in picked:
            picked.append(c)
            if len(picked) == n:
                break
    return picked


# ── credits ──────────────────────────────────────────────────────────
GROUP_ORDER = ['performer', 'composition', 'production', 'engineering', 'other']
ROLE_GROUPS = {
    'performer': ['instrument', 'vocal', 'performer', 'performing_orchestra', 'conductor',
                  'chorus_master', 'concertmaster'],
    'composition': ['composer', 'lyricist', 'librettist', 'writer', 'arranger', 'orchestrator',
                    'translator'],
    'production': ['producer', 'liner_notes', 'design', 'photography', 'illustration',
                   'art_direction', 'graphic_design'],
    'engineering': ['engineer', 'recording', 'mix', 'mastering', 'sound', 'audio', 'programming',
                    'balance', 'editor', 'remixer'],
}
# MusicBrainz relationship type -> our role key, where the plain snake_case of
# the type name is not already it.
ROLE_ALIASES = {
    'instrument_arranger': 'arranger',
    'vocal_arranger': 'arranger',
    'design_illustration': 'design',
}
_ROLE_TO_GROUP = {role: group for group, roles in ROLE_GROUPS.items() for role in roles}
# Relationship attributes that qualify the role rather than name an instrument
# or a voice type.
MODIFIER_ATTRS = {'additional', 'assistant', 'associate', 'co', 'executive', 'guest', 'solo',
                  'minor', 'sub', 'principal', 'task', 'original', 'founder', 'eponymous',
                  'live', 'partial', 'instrumental', 'cover', 'medley', 'karaoke', 'translated',
                  'transliterated', 'bonus', 'pre-production', 'emeritus', 'cameo'}
_PER_ATTR_ROLES = ('instrument', 'vocal', 'arranger', 'orchestrator')


def classify_relation(rel):
    """An artist relationship as credit keys: a list of (group, role, attr,
    credit). Instrument and voice relationships give one key per instrument or
    voice type; for other roles `attr` holds the qualifiers ("executive",
    "assistant")."""
    rtype = rel.get('type') or ''
    role = ROLE_ALIASES.get(snake(rtype), snake(rtype))
    group = _ROLE_TO_GROUP.get(role, 'other')
    attrs = [a for a in rel.get('attributes') or [] if a]
    credits = rel.get('attribute-credits') or {}
    values = rel.get('attribute-values') or {}
    named = [a for a in attrs if a.lower() not in MODIFIER_ATTRS]
    modifiers = sorted(a.lower() for a in attrs if a.lower() in MODIFIER_ATTRS and a.lower() != 'task')
    task = str(values.get('task') or '').strip()
    if role in _PER_ATTR_ROLES and named:
        return [(group, role, a.lower(), str(credits.get(a) or '').strip()) for a in named]
    attr = ' '.join(modifiers + [a.lower() for a in named])
    return [(group, role, attr, task)]


class _CreditSet:
    """(group, role, attr, credit) -> people, with the tracks each person is
    credited on. `None` in the tracks set means release level."""

    def __init__(self):
        self.entries = {}

    def add(self, key, person, where):
        entry = self.entries.setdefault(key, {})
        slot = entry.setdefault(person['mbid'] or person['name'],
                                {'person': dict(person), 'where': set()})
        slot['where'].add(where)
        if person.get('credited_as') and not slot['person'].get('credited_as'):
            slot['person']['credited_as'] = person['credited_as']

    def add_relations(self, relations, where):
        for rel in relations or []:
            if rel.get('target-type') != 'artist' or not rel.get('artist'):
                continue
            a = rel['artist']
            person = {'name': a.get('name') or '', 'mbid': a.get('id')}
            tc = (rel.get('target-credit') or '').strip()
            if tc and tc != person['name']:
                person['credited_as'] = tc
            for key in classify_relation(rel):
                self.add(key, person, where)


def _sort_key_entry(key, n_where):
    group, role, attr, credit = key
    roles = ROLE_GROUPS.get(group, [])
    return (GROUP_ORDER.index(group) if group in GROUP_ORDER else 99,
            roles.index(role) if role in roles else 99, role, -n_where, attr, credit)


def _serialise_credits(cset, all_tracks=None, with_tracks=True):
    """Entries in display order. With `with_tracks`, each entry carries
    `tracks`: None when release-level or covering every track of
    `all_tracks`, else the [disc, n] list it applies to."""
    out = []
    for key, slots in cset.entries.items():
        where_all = set()
        for slot in slots.values():
            where_all |= slot['where']
        people = sorted(slots.values(), key=lambda s: (None not in s['where'], -len(s['where']),
                                                        normalise(s['person']['name'])))
        entry = {'group': key[0], 'role': key[1], 'attr': key[2], 'credit': key[3],
                 'people': [dict(s['person']) for s in people]}
        if with_tracks:
            if None in where_all or (all_tracks is not None and set(all_tracks) <= where_all):
                entry['tracks'] = None
            else:
                entry['tracks'] = [list(w) for w in sorted(where_all)]
        n_where = len(all_tracks or []) + 1 if (with_tracks and entry.get('tracks') is None) else len(where_all)
        out.append((_sort_key_entry(key, n_where), entry))
    out.sort(key=lambda x: x[0])
    return [e for _, e in out]


def _work_ids_without_writers(work):
    """Parent works worth a lookup: the recording's work names no composer,
    writer or lyricist of its own (a movement whose composer is only on the
    whole work)."""
    rels = work.get('relations') or []
    has_writer = any(r.get('target-type') == 'artist'
                     and _ROLE_TO_GROUP.get(ROLE_ALIASES.get(snake(r.get('type')), snake(r.get('type')))) == 'composition'
                     for r in rels)
    if has_writer:
        return []
    return [(r.get('work') or {}).get('id') for r in rels
            if r.get('target-type') == 'work' and r.get('type') == 'parts'
            and r.get('direction') == 'backward' and (r.get('work') or {}).get('id')]


def build_release_model(rel):
    """The language-neutral, cacheable digest of a full release lookup
    (RELEASE_INC): everything an album page needs and nothing else — the
    lookup itself carries hundreds of unrelated work relationships."""
    rg = rel.get('release-group') or {}
    media = []
    parent_works = []
    for m in rel.get('media') or []:
        pos = int(m.get('position') or len(media) + 1)
        tracks = []
        for t in m.get('tracks') or []:
            rec = t.get('recording') or {}
            relations = list(rec.get('relations') or [])
            works = []
            for r in relations:
                if r.get('target-type') == 'work' and r.get('type') == 'performance' and r.get('work'):
                    w = r['work']
                    works.append({'mbid': w.get('id'), 'title': w.get('title') or '',
                                  'relations': [x for x in w.get('relations') or []
                                                if x.get('target-type') == 'artist'],
                                  'parents': _work_ids_without_writers(w)})
                    parent_works.extend(_work_ids_without_writers(w))
            places = []
            for r in relations:
                if r.get('target-type') == 'place' and r.get('place'):
                    places.append(_place(r))
            tracks.append({
                'n': int(t.get('position') or len(tracks) + 1),
                'number': t.get('number') or '',
                'mbid': t.get('id'),
                'title': t.get('title') or rec.get('title') or '',
                'length_ms': t.get('length') or rec.get('length'),
                'recording': rec.get('id'),
                'isrcs': rec.get('isrcs') or [],
                'artist_credit': artist_credit_people(t.get('artist-credit') or rec.get('artist-credit')),
                'artist': artist_credit_text(t.get('artist-credit') or rec.get('artist-credit')),
                'relations': [x for x in relations if x.get('target-type') == 'artist'],
                'works': works,
                'places': places,
            })
        media.append({'position': pos, 'format': m.get('format') or '', 'title': m.get('title') or '',
                      'track_count': int(m.get('track-count') or len(tracks)), 'tracks': tracks})
    wikidata = None
    for r in rg.get('relations') or []:
        if r.get('target-type') == 'url' and r.get('type') == 'wikidata':
            wikidata = wikidata_qid((r.get('url') or {}).get('resource'))
            if wikidata:
                break
    labels = []
    for li in rel.get('label-info') or []:
        item = {'name': (li.get('label') or {}).get('name') or '', 'catno': li.get('catalog-number') or ''}
        if (item['name'] or item['catno']) and item not in labels:
            labels.append(item)
    return {
        'mbid': rel.get('id'),
        'release_group': rg.get('id'),
        'title': rel.get('title') or '',
        'artist': artist_credit_text(rel.get('artist-credit')),
        'artist_credit': artist_credit_people(rel.get('artist-credit')),
        'rg_artist_credit': artist_credit_people(rg.get('artist-credit')),
        'date': rel.get('date') or '',
        'first_release_date': rg.get('first-release-date') or '',
        'type': (rg.get('primary-type') or '').lower(),
        'secondary_types': [s.lower() for s in rg.get('secondary-types') or []],
        'labels': labels,
        'country': rel.get('country') or '',
        'barcode': rel.get('barcode') or '',
        'status': rel.get('status') or '',
        'disc_count': len(media),
        'track_count': sum(m['track_count'] for m in media),
        'wikidata': wikidata,
        'relations': [x for x in rel.get('relations') or [] if x.get('target-type') == 'artist'],
        'places': [_place(r) for r in rel.get('relations') or [] if r.get('target-type') == 'place' and r.get('place')],
        'media': media,
        'parent_works': sorted(set(parent_works)),
        'parent_credits': {},
    }


def _place(rel):
    p = rel.get('place') or {}
    return {'role': snake(rel.get('type') or ''), 'name': p.get('name') or '',
            'area': (p.get('area') or {}).get('name') or '', 'mbid': p.get('id')}


def album_view(model, mode='all', position=None, disc_for_medium=1, coords=None):
    """Credits, tracks and places of a cached release model for one
    alignment. Track coordinates are [disc, n]. With `coords` (one per aligned
    track, in order — the library's own disc/track numbers) those are used, so
    the screens can pair them with the library's tracks even when the numbering
    differs (a 2×CD set tagged as one disc of 26 tracks). Otherwise: the medium
    position for a whole-release fit (audio media renumbered 1..k for
    'audio'), `disc_for_medium` when the album is one medium of a larger
    release."""
    chosen = aligned_media(model.get('media') or [], mode, position)
    if coords is not None and len(coords) != sum(len(m.get('tracks') or []) for m in chosen):
        coords = None
    album = _CreditSet()
    album.add_relations(model.get('relations'), None)
    tracks_out = []
    all_coords = []
    places = []
    seen_places = set()
    index = 0
    for idx, m in enumerate(chosen):
        disc = disc_for_medium if mode == 'medium' else (idx + 1 if mode == 'audio' else m['position'])
        for t in m.get('tracks') or []:
            where = tuple(coords[index]) if coords is not None else (disc, t['n'])
            index += 1
            all_coords.append(where)
            per_track = _CreditSet()
            per_track.add_relations(t.get('relations'), where)
            album.add_relations(t.get('relations'), where)
            for w in t.get('works') or []:
                per_track.add_relations(w.get('relations'), where)
                album.add_relations(w.get('relations'), where)
                for parent in w.get('parents') or []:
                    rels = (model.get('parent_credits') or {}).get(parent) or []
                    per_track.add_relations(rels, where)
                    album.add_relations(rels, where)
            for p in t.get('places') or []:
                k = (p['role'], p['name'])
                if k not in seen_places:
                    seen_places.add(k)
                    places.append({'role': p['role'], 'name': p['name'], 'area': p['area']})
            tracks_out.append({'disc': where[0], 'n': where[1], 'title': t['title'], 'length_ms': t.get('length_ms'),
                               'credits': _serialise_credits(per_track, with_tracks=False)})
    for p in model.get('places') or []:
        k = (p['role'], p['name'])
        if k not in seen_places:
            seen_places.add(k)
            places.insert(0, {'role': p['role'], 'name': p['name'], 'area': p['area']})
    return _serialise_credits(album, all_tracks=all_coords), tracks_out, places


def model_people(model):
    """mbid -> (name, set of (group, role, attr)) for everybody credited."""
    out = {}

    def take(relations):
        for rel in relations or []:
            a = rel.get('artist') or {}
            if rel.get('target-type') != 'artist' or not a.get('id'):
                continue
            slot = out.setdefault(a['id'], [a.get('name') or '', set()])
            for g, r, attr, _c in classify_relation(rel):
                slot[1].add((g, r, attr))

    take(model.get('relations'))
    for m in model.get('media') or []:
        for t in m.get('tracks') or []:
            take(t.get('relations'))
            for w in t.get('works') or []:
                take(w.get('relations'))
    for rels in (model.get('parent_credits') or {}).values():
        take(rels)
    return out


# ── artists ──────────────────────────────────────────────────────────
def _life(span):
    span = span or {}
    return span.get('begin') or '', span.get('end') or '', bool(span.get('ended'))


def build_artist_model(a):
    begin, end, ended = _life(a.get('life-span'))
    members, member_of = [], []
    urls = {'musicbrainz': f"{MB_WEB}/artist/{a.get('id')}"}
    wikidata = None
    for r in a.get('relations') or []:
        tt = r.get('target-type')
        if tt == 'artist' and r.get('type') == 'member of band' and r.get('artist'):
            o = r['artist']
            item = {'name': o.get('name') or '', 'mbid': o.get('id'),
                    'attrs': [x.lower() for x in r.get('attributes') or [] if x],
                    'begin': r.get('begin') or '', 'end': r.get('end') or '', 'ended': bool(r.get('ended'))}
            (members if r.get('direction') == 'backward' else member_of).append(item)
        elif tt == 'url':
            res = (r.get('url') or {}).get('resource') or ''
            if r.get('type') == 'wikidata' and not wikidata:
                wikidata = wikidata_qid(res)
            elif r.get('type') == 'official homepage' and 'official' not in urls and not r.get('ended'):
                urls['official'] = res
    return {
        'mbid': a.get('id'), 'name': a.get('name') or '', 'sort_name': a.get('sort-name') or '',
        'type': (a.get('type') or 'other').lower(), 'disambiguation': a.get('disambiguation') or '',
        'begin': begin, 'end': end, 'ended': ended,
        'area': (a.get('area') or {}).get('name') or '',
        'begin_area': (a.get('begin-area') or {}).get('name') or '',
        'end_area': (a.get('end-area') or {}).get('name') or '',
        'members': members, 'member_of': member_of, 'urls': urls, 'wikidata': wikidata,
        'aliases': sorted({x.get('name') for x in a.get('aliases') or [] if x.get('name')}),
    }


# ── Wikipedia ────────────────────────────────────────────────────────
def wikidata_qid(url):
    m = re.search(r'/(Q[0-9]+)\b', str(url or ''))
    return m.group(1) if m else None


def wikipedia_url(lang, title):
    return f'https://{lang}.wikipedia.org/wiki/' + urllib.parse.quote(title.replace(' ', '_'), safe="()_,'!:-.")


def clean_extract(text, limit=ABOUT_MAX_CHARS):
    """Plain intro text with paragraphs separated by one blank line, cut at a
    paragraph (or failing that, sentence) boundary under `limit`."""
    paras = [re.sub(r'[ \t]+', ' ', p).strip() for p in re.split(r'\n+', str(text or ''))]
    paras = [p for p in paras if p and not re.match(r'^=+.*=+$', p)]
    out, size = [], 0
    for p in paras:
        if size + len(p) > limit:
            if not out:
                cut = p[:limit]
                dot = max(cut.rfind('. '), cut.rfind('. '))
                out.append(cut[:dot + 1] if dot > limit // 3 else cut.rstrip() + '…')
            break
        out.append(p)
        size += len(p) + 2
    return '\n\n'.join(out)


# ── CD ripping helpers ───────────────────────────────────────────────
def freedb_disc_id(offsets, leadout):
    def digits(n):
        return sum(int(c) for c in str(n))
    n = sum(digits(off // 75) for off in offsets)
    t = leadout // 75 - offsets[0] // 75
    return '%08x' % (((n % 0xff) << 24) | (t << 8) | len(offsets))


def mb_disc_id(offsets, leadout, first_track=1):
    """The MusicBrainz disc id (libdiscid's algorithm): SHA-1 over the TOC in
    upper-case hex, base64 with the URL-safe substitutions MusicBrainz uses."""
    last = first_track + len(offsets) - 1
    s = '%02X%02X%08X' % (first_track, last, leadout)
    for i in range(99):
        s += '%08X' % (offsets[i] if i < len(offsets) else 0)
    digest = hashlib.sha1(s.encode('ascii')).digest()
    return base64.b64encode(digest).decode('ascii').replace('+', '.').replace('/', '_').replace('=', '-')


def cd_toc_string(offsets, leadout, first_track=1):
    return '+'.join(str(x) for x in [first_track, first_track + len(offsets) - 1, leadout] + list(offsets))


def cd_toc_lengths_ms(offsets, leadout):
    ends = list(offsets[1:]) + [leadout]
    return [int((e - o) * 1000 / 75) for o, e in zip(offsets, ends)]


def cd_medium_match(medium, disc_id, lengths_ms):
    """(exact, mean difference in s) of one medium against the disc in the
    drive, or None when the track counts differ."""
    tracks = medium.get('tracks') or []
    count = int(medium.get('track-count') or len(tracks))
    if count != len(lengths_ms):
        return None
    exact = any(d.get('id') == disc_id for d in medium.get('discs') or [])
    diffs = []
    for t, toc_len in zip(tracks, lengths_ms):
        mb_len = t.get('length') or (t.get('recording') or {}).get('length')
        if mb_len:
            diffs.append(abs(mb_len - toc_len) / 1000.0)
    if not exact and (len(diffs) < max(1, len(lengths_ms) // 2)):
        return None
    mean = sum(diffs) / len(diffs) if diffs else 0.0
    if not exact and mean > 6.0:
        return None
    return exact, round(mean, 2)


def cd_choices(data, disc_id, lengths_ms):
    """Every (release, medium) of a discid/TOC lookup that fits the disc, best
    first: exact disc id, official, closest track lengths, a standalone album
    before a box set that happens to contain the same disc."""
    choices = []
    for rel in data.get('releases') or ([data] if data.get('media') else []):
        for m in rel.get('media') or []:
            fit = cd_medium_match(m, disc_id, lengths_ms)
            if fit is None:
                continue
            exact, mean = fit
            key = (0 if exact else 1, 0 if rel.get('status') == 'Official' else 1, round(mean),
                   len(rel.get('media') or []), 0 if rel.get('date') else 1, mean)
            choices.append((key, rel, m))
    choices.sort(key=lambda c: c[0])
    return [{'release': rel, 'medium': m, 'exact': key[0] == 0, 'diff': key[5]} for key, rel, m in choices]


def cd_release_entry(choice):
    rel, m = choice['release'], choice['medium']
    li = (rel.get('label-info') or [{}])[0] if rel.get('label-info') else {}
    return {
        'mbid': rel.get('id'),
        'title': rel.get('title') or '',
        'artist': artist_credit_text(rel.get('artist-credit')),
        'date': rel.get('date') or '',
        'country': rel.get('country') or '',
        'label': (li.get('label') or {}).get('name') or '',
        'catno': li.get('catalog-number') or '',
        'track_count': int(m.get('track-count') or len(m.get('tracks') or [])),
        'disc_position': int(m.get('position') or 1),
        'disc_count': len(rel.get('media') or []),
    }


def _uniq(values):
    out = []
    for v in values:
        if v and v not in out:
            out.append(v)
    return out


def cd_tags(rel, medium_position):
    """Picard-style tags for one medium of a release (a discid or a full
    lookup): (album-wide [(KEY, value)], per track [[(KEY, value)]],
    per-track artist credit strings). Multi-valued fields are repeated tags.
    Composer and lyricist come from the recordings' works when the lookup
    carries them (a full RELEASE_INC lookup does, a discid lookup does not)."""
    rg = rel.get('release-group') or {}
    media = rel.get('media') or []
    medium = next((m for m in media if int(m.get('position') or 0) == int(medium_position)), None)
    if medium is None:
        return [], [], []
    album = [('MUSICBRAINZ_ALBUMID', rel.get('id') or '')]
    for p in artist_credit_people(rel.get('artist-credit')):
        album.append(('MUSICBRAINZ_ALBUMARTISTID', p['mbid']))
    album.append(('ALBUMARTIST', artist_credit_text(rel.get('artist-credit'))))
    if rg.get('id'):
        album.append(('MUSICBRAINZ_RELEASEGROUPID', rg['id']))
    album += [('DISCNUMBER', str(medium.get('position') or 1)),
              ('DISCTOTAL', str(len(media))), ('TOTALDISCS', str(len(media)))]
    for t in _uniq([(rg.get('primary-type') or '').lower()] + [s.lower() for s in rg.get('secondary-types') or []]):
        album.append(('RELEASETYPE', t))
    if rg.get('first-release-date'):
        album.append(('ORIGINALDATE', rg['first-release-date']))
        album.append(('ORIGINALYEAR', rg['first-release-date'][:4]))
    for name in _uniq((li.get('label') or {}).get('name') for li in rel.get('label-info') or []):
        album.append(('LABEL', name))
    for cat in _uniq(li.get('catalog-number') for li in rel.get('label-info') or []):
        album.append(('CATALOGNUMBER', cat))
    for key, value in (('RELEASESTATUS', (rel.get('status') or '').lower()),
                       ('RELEASECOUNTRY', rel.get('country') or ''),
                       ('BARCODE', rel.get('barcode') or ''),
                       ('MEDIA', medium.get('format') or '')):
        if value:
            album.append((key, value))
    per_track, artists = [], []
    for t in medium.get('tracks') or []:
        rec = t.get('recording') or {}
        credit = t.get('artist-credit') or rec.get('artist-credit') or rel.get('artist-credit')
        tags = []
        if rec.get('id'):
            tags.append(('MUSICBRAINZ_TRACKID', rec['id']))
        if t.get('id'):
            tags.append(('MUSICBRAINZ_RELEASETRACKID', t['id']))
        for p in artist_credit_people(credit):
            tags.append(('MUSICBRAINZ_ARTISTID', p['mbid']))
        for isrc in _uniq(rec.get('isrcs') or []):
            tags.append(('ISRC', isrc))
        composers, lyricists = [], []
        for r in rec.get('relations') or []:
            if r.get('target-type') != 'work' or r.get('type') != 'performance':
                continue
            for wr in (r.get('work') or {}).get('relations') or []:
                name = (wr.get('artist') or {}).get('name')
                if wr.get('target-type') != 'artist' or not name:
                    continue
                if wr.get('type') in ('composer', 'writer'):
                    composers.append(name)
                if wr.get('type') in ('lyricist', 'writer', 'librettist'):
                    lyricists.append(name)
        tags += [('COMPOSER', n) for n in _uniq(composers)]
        tags += [('LYRICIST', n) for n in _uniq(lyricists)]
        per_track.append(tags)
        artists.append(artist_credit_text(credit))
    return album, per_track, artists


# ── Lyrion ───────────────────────────────────────────────────────────
def lms_host_from_squeezelite(path=SQUEEZELITE_DEFAULT):
    """The Lyrion server squeezelite is pointed at (-s host[:port]), the same
    source api_server's /lms_role reads; loopback when unset."""
    try:
        with open(path) as f:
            content = f.read()
    except OSError:
        return '127.0.0.1'
    m = re.search(r"ARGS=(['\"])(.*?)\1", content)
    args = m.group(2) if m else ''
    m = re.search(r'-s\s+(\S+)', args)
    if not m:
        return '127.0.0.1'
    host = m.group(1)
    if host.startswith('['):
        return host.split(']')[0] + ']'
    return host.split(':')[0] if host.count(':') == 1 else host


def parse_raw_tags(raw):
    """Lyrion's `tags track_id:` dump (Audio::Scan keys: MUSICBRAINZ_ALBUMID
    in Vorbis comments, "MUSICBRAINZ ALBUM ID" in ID3 TXXX, "MusicBrainz Album
    Id" in MP4) folded to letter-only upper-case keys -> list of values."""
    out = {}
    for key, value in (raw or {}).items():
        k = re.sub(r'[^A-Z0-9]', '', str(key).rsplit(':', 1)[-1].upper())
        v = str(value if value is not None else '')
        if v.startswith('[ ') and v.endswith(' ]'):
            values = [x.strip() for x in v[2:-2].split(', ')]
        else:
            values = [v]
        out.setdefault(k, []).extend(x for x in values if x)
    return out


def tag_mbids(tags, *keys):
    ids = []
    for k in keys:
        for v in tags.get(k) or []:
            ids.extend(x.lower() for x in UUID_RE.findall(v))
    return _uniq(ids)


def pair_tag_artist(tags, target):
    """The MBID a track's tags give the artist whose normalised name is
    `target`: MUSICBRAINZ_ARTISTID paired with ARTISTS/ARTIST (or the
    album-artist pair), position by position. An id is only taken when the
    pairing is unambiguous — one id and one matching name, or as many ids as
    names."""
    for id_key, name_keys in (('MUSICBRAINZARTISTID', ('ARTISTS', 'ARTIST', 'TPE1')),
                              ('MUSICBRAINZALBUMARTISTID', ('ALBUMARTISTS', 'ALBUMARTIST', 'TPE2'))):
        ids = tag_mbids(tags, id_key)
        if not ids:
            continue
        names = next((tags[k] for k in name_keys if tags.get(k)), [])
        if len(ids) == len(names):
            for mbid, name in zip(ids, names):
                if normalise(name) == target:
                    return mbid
    return None


class LyrionError(Exception):
    pass


class Lyrion:
    def __init__(self, url=None, timeout=8.0, urlopen=None):
        self._url = url
        self._timeout = timeout
        self._urlopen = urlopen or urllib.request.urlopen
        self._names = {'url': None, 'at': 0.0, 'index': {}}
        self._lock = threading.Lock()

    def base_url(self):
        url = self._url or os.environ.get('HIFI_META_LMS_URL') or ''
        if not url:
            host = lms_host_from_squeezelite()
            url = f'http://{host}:9000'
        url = url.rstrip('/')
        if url.endswith('/jsonrpc.js'):
            url = url[:-len('/jsonrpc.js')]
        return url

    def request(self, params, timeout=None):
        payload = json.dumps({'id': 1, 'method': 'slim.request', 'params': ['', params]}).encode('utf-8')
        req = urllib.request.Request(self.base_url() + '/jsonrpc.js', data=payload,
                                     headers={'Content-Type': 'application/json'})
        try:
            with self._urlopen(req, timeout=timeout or self._timeout) as resp:
                return json.loads(resp.read().decode('utf-8')).get('result') or {}
        except Exception as e:
            raise LyrionError(str(e))

    def album(self, album_id):
        r = self.request(['albums', 0, 1, f'album_id:{int(album_id)}', 'tags:alyqwSj'])
        loop = r.get('albums_loop') or []
        if not loop:
            return None
        a = loop[0]
        return {'id': int(a.get('id')), 'title': a.get('album') or '', 'artist': a.get('artist') or '',
                'artist_id': a.get('artist_id'), 'year': a.get('year') or 0,
                'compilation': str(a.get('compilation') or '0') == '1',
                'artwork_track_id': a.get('artwork_track_id')}

    def album_tracks(self, album_id):
        r = self.request(['titles', 0, 2000, f'album_id:{int(album_id)}', 'tags:dtiy', 'sort:tracknum'])
        tracks = []
        for t in r.get('titles_loop') or []:
            try:
                n = int(str(t.get('tracknum') or '0').split('/')[0] or 0)
            except ValueError:
                n = 0
            try:
                disc = int(t.get('disc') or 0)
            except (TypeError, ValueError):
                disc = 0
            tracks.append({'id': t.get('id'), 'title': t.get('title') or '', 'disc': disc, 'n': n,
                           'duration': float(t.get('duration') or 0)})
        tracks.sort(key=lambda t: (t['disc'] or 1, t['n'], t['title']))
        return tracks

    def raw_tags(self, track_id):
        return parse_raw_tags(self.request(['tags', 0, 500, f'track_id:{track_id}']))

    def artist(self, artist_id):
        r = self.request(['artists', 0, 1, f'artist_id:{int(artist_id)}'])
        loop = r.get('artists_loop') or []
        return {'id': int(loop[0]['id']), 'name': loop[0].get('artist') or ''} if loop else None

    def artist_albums(self, artist_id):
        r = self.request(['albums', 0, 500, f'artist_id:{int(artist_id)}', 'tags:lyaS'])
        return [{'id': a.get('id'), 'title': a.get('album') or '', 'artist': a.get('artist') or ''}
                for a in r.get('albums_loop') or []]

    def artist_tracks(self, artist_id, limit=5):
        r = self.request(['titles', 0, limit, f'artist_id:{int(artist_id)}', 'tags:e'])
        return [t.get('id') for t in r.get('titles_loop') or [] if t.get('id') is not None]

    def artist_id_by_mbid(self, mbid):
        """Lyrion's FullTextSearch indexes contributors.musicbrainz_id, so an
        artist search for the MBID finds a tagged contributor."""
        r = self.request(['artists', 0, 2, f'search:{mbid}'])
        loop = r.get('artists_loop') or []
        return int(loop[0]['id']) if len(loop) == 1 else None

    def artist_name_index(self, max_age=600):
        with self._lock:
            url = self.base_url()
            if self._names['url'] == url and time.monotonic() - self._names['at'] < max_age:
                return self._names['index']
        r = self.request(['artists', 0, 50000, 'role_id:ARTIST,ALBUMARTIST,TRACKARTIST,COMPOSER,CONDUCTOR,BAND'],
                         timeout=30)
        index = {}
        for a in r.get('artists_loop') or []:
            index.setdefault(normalise(a.get('artist')), int(a['id']))
        with self._lock:
            self._names.update(url=url, at=time.monotonic(), index=index)
        return index

    def all_albums(self):
        r = self.request(['albums', 0, 100000, 'tags:laSj'], timeout=60)
        return [{'id': int(a['id']), 'title': a.get('album') or '', 'artist': a.get('artist') or '',
                 'artist_id': a.get('artist_id'), 'artwork_track_id': a.get('artwork_track_id')}
                for a in r.get('albums_loop') or []]

    def scanning(self):
        r = self.request(['serverstatus', 0, 0])
        return str(r.get('rescan') or '0') not in ('0', '')

    def find_album(self, title, artist):
        r = self.request(['albums', 0, 20, f'search:{title}', 'tags:laj'])
        for a in r.get('albums_loop') or []:
            if normalise(a.get('album')) == normalise(title) and normalise(a.get('artist')) == normalise(artist):
                return {'id': int(a['id']), 'artwork_track_id': a.get('artwork_track_id')}
        return None


# ── cache ────────────────────────────────────────────────────────────
class Cache:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS entries (
        key TEXT PRIMARY KEY, value TEXT NOT NULL, fetched REAL NOT NULL,
        accessed REAL NOT NULL, negative INTEGER NOT NULL DEFAULT 0, size INTEGER NOT NULL DEFAULT 0);
    CREATE INDEX IF NOT EXISTS entries_accessed ON entries(accessed);
    CREATE TABLE IF NOT EXISTS pins (
        fingerprint TEXT PRIMARY KEY, album_id INTEGER, mbid TEXT NOT NULL,
        title TEXT, artist TEXT, created REAL);
    CREATE TABLE IF NOT EXISTS appearances (
        mbid TEXT NOT NULL, fingerprint TEXT NOT NULL, album_id INTEGER, title TEXT, artist TEXT,
        artwork_track_id TEXT, roles TEXT, updated REAL, PRIMARY KEY (mbid, fingerprint));
    CREATE TABLE IF NOT EXISTS album_index (
        album_id INTEGER PRIMARY KEY, title TEXT, artist TEXT, fingerprint TEXT, updated REAL);
    """

    def __init__(self, directory, max_bytes=CACHE_MAX_BYTES, clock=None):
        self.directory = directory
        self.max_bytes = max_bytes
        self._clock = clock or time.time
        self._lock = threading.RLock()
        os.makedirs(directory, mode=0o755, exist_ok=True)
        self.path = os.path.join(directory, 'metadata.db')
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=10)
        with self._lock:
            self._db.execute('PRAGMA auto_vacuum=INCREMENTAL')
            self._db.execute('PRAGMA journal_mode=WAL')
            self._db.execute('PRAGMA synchronous=NORMAL')
            self._db.executescript(self.SCHEMA)
        self._writes = 0

    def close(self):
        with self._lock:
            self._db.close()

    # entries
    def get(self, key):
        """(value, age_seconds, negative) or None."""
        with self._lock:
            row = self._db.execute('SELECT value, fetched, negative, accessed FROM entries WHERE key=?',
                                   (key,)).fetchone()
            if row is None:
                return None
            now = self._clock()
            if now - row[3] > 3600:
                self._db.execute('UPDATE entries SET accessed=? WHERE key=?', (now, key))
        try:
            value = json.loads(row[0])
        except ValueError:
            return None
        return value, now - row[1], bool(row[2])

    def put(self, key, value, negative=False):
        text = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        now = self._clock()
        with self._lock:
            self._db.execute('INSERT OR REPLACE INTO entries(key, value, fetched, accessed, negative, size) '
                             'VALUES (?,?,?,?,?,?)', (key, text, now, now, 1 if negative else 0,
                                                     len(text.encode('utf-8'))))
            self._writes += 1
            if self._writes % 20 == 0:
                self.evict()

    def delete(self, key):
        with self._lock:
            self._db.execute('DELETE FROM entries WHERE key=?', (key,))

    # What eviction may drop: the big, re-downloadable lookups. The small
    # answers that say an album or artist is resolved (match:, artistmatch:)
    # stay, or on a library too big for the cap the prefetch would find the
    # oldest albums "unresolved" again after every pass and download them
    # over and over; their releases come back on demand when a page opens.
    EVICTABLE = ('release:', 'search:', 'rgreleases:', 'wiki:', 'artist:', 'light:')

    def evict(self):
        with self._lock:
            total = self._db.execute('SELECT COALESCE(SUM(size), 0) FROM entries').fetchone()[0]
            if total <= self.max_bytes:
                return 0
            target = int(self.max_bytes * 0.9)
            removed = 0
            where = ' OR '.join('key LIKE ?' for _ in self.EVICTABLE)
            rows = self._db.execute(f'SELECT key, size FROM entries WHERE {where} ORDER BY accessed ASC',
                                    [p + '%' for p in self.EVICTABLE]).fetchall()
            for key, size in rows:
                if total <= target:
                    break
                self._db.execute('DELETE FROM entries WHERE key=?', (key,))
                total -= size
                removed += 1
            self._db.execute('PRAGMA incremental_vacuum')
            return removed

    def clear(self):
        """Everything except the manual pins."""
        with self._lock:
            self._db.execute('DELETE FROM entries')
            self._db.execute('DELETE FROM appearances')
            self._db.execute('DELETE FROM album_index')
            self._db.execute('PRAGMA incremental_vacuum')
            try:
                self._db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            except sqlite3.DatabaseError:
                pass

    def stats(self):
        with self._lock:
            albums = self._db.execute("SELECT COUNT(*) FROM entries WHERE key LIKE 'match:%' AND negative=0").fetchone()[0]
            artists = self._db.execute("SELECT COUNT(*) FROM entries WHERE key LIKE 'artist:%' AND negative=0").fetchone()[0]
        size = 0
        for suffix in ('', '-wal'):
            try:
                size += os.path.getsize(self.path + suffix)
            except OSError:
                pass
        return {'albums': albums, 'artists': artists, 'bytes': size}

    # pins
    def get_pin(self, fp):
        with self._lock:
            row = self._db.execute('SELECT mbid, album_id FROM pins WHERE fingerprint=?', (fp,)).fetchone()
        return {'mbid': row[0], 'album_id': row[1]} if row else None

    def set_pin(self, fp, album_id, mbid, title='', artist=''):
        with self._lock:
            if mbid is None:
                self._db.execute('DELETE FROM pins WHERE fingerprint=?', (fp,))
            else:
                self._db.execute('INSERT OR REPLACE INTO pins VALUES (?,?,?,?,?,?)',
                                 (fp, album_id, mbid, title, artist, self._clock()))

    # appearances
    def set_appearances(self, fp, album_id, title, artist, artwork, people):
        now = self._clock()
        with self._lock:
            self._db.execute('DELETE FROM appearances WHERE fingerprint=?', (fp,))
            self._db.executemany(
                'INSERT OR REPLACE INTO appearances VALUES (?,?,?,?,?,?,?,?)',
                [(mbid, fp, album_id, title, artist, str(artwork) if artwork is not None else None,
                  json.dumps(sorted([list(r) for r in roles])), now) for mbid, roles in people.items()])

    def appearances(self, mbid):
        with self._lock:
            rows = self._db.execute('SELECT fingerprint, album_id, title, artist, artwork_track_id, roles '
                                    'FROM appearances WHERE mbid=? ORDER BY title', (mbid,)).fetchall()
        return [{'fingerprint': r[0], 'album_id': r[1], 'title': r[2], 'artist': r[3],
                 'artwork_track_id': r[4], 'roles': json.loads(r[5] or '[]')} for r in rows]

    def move_appearances(self, fp, album_id, artwork=None):
        with self._lock:
            self._db.execute('UPDATE appearances SET album_id=?, artwork_track_id=COALESCE(?, artwork_track_id) '
                             'WHERE fingerprint=?', (album_id, str(artwork) if artwork is not None else None, fp))

    def drop_appearances(self, fp):
        with self._lock:
            self._db.execute('DELETE FROM appearances WHERE fingerprint=?', (fp,))

    # album index (prefetch bookkeeping: album id -> fingerprint)
    def index_get(self, album_id, title, artist):
        with self._lock:
            row = self._db.execute('SELECT fingerprint FROM album_index WHERE album_id=? AND title=? AND artist=?',
                                   (album_id, title, artist)).fetchone()
        return row[0] if row else None

    def index_put(self, album_id, title, artist, fp):
        with self._lock:
            self._db.execute('INSERT OR REPLACE INTO album_index VALUES (?,?,?,?,?)',
                             (album_id, title, artist, fp, self._clock()))


# ── the service ──────────────────────────────────────────────────────
class _Yield(Exception):
    """A background job steps aside for a more urgent one."""


class _Disabled(Exception):
    pass


class _Ctx:
    def __init__(self, service, priority):
        self.service = service
        self.priority = priority

    def check(self):
        if not self.service.online_enabled():
            raise _Disabled()
        if self.priority >= PRIO_PREFETCH and not self.service.prefetch_enabled():
            raise _Disabled()
        if self.priority > PRIO_INTERACTIVE and self.service._more_urgent_waiting(self.priority):
            raise _Yield()


def _lang_ok(lang):
    return lang if lang in ('it', 'en') else 'en'


class MetadataService:
    def __init__(self, cache_dir=None, etc_dir=None, lyrion=None, client=None, clock=None,
                 start_worker=True):
        self.cache_dir = cache_dir or os.environ.get('HIFI_META_CACHE_DIR') or CACHE_DIR
        self.etc_dir = etc_dir or os.environ.get('HIFI_META_ETC_DIR') or ETC_DIR
        self.lyrion = lyrion or Lyrion()
        self.client = client or CLIENT
        self._clock = clock or time.time
        self._cache = None
        self._cache_lock = threading.Lock()
        self._cv = threading.Condition()
        self._heap = []
        self._jobs = {}
        self._running = None
        self._seq = itertools.count()
        self._failures = {}
        self._people_ids = {}
        self._settings_event = threading.Event()
        self._prefetch = {'running': False, 'done': 0, 'total': 0}
        self._prefetch_thread = None
        self._worker = None
        if start_worker:
            self._start_worker()

    # plumbing
    @property
    def cache(self):
        with self._cache_lock:
            if self._cache is None:
                self._cache = Cache(self.cache_dir)
            return self._cache

    def _start_worker(self):
        if self._worker is None:
            self._worker = threading.Thread(target=self._work_loop, daemon=True, name='meta-worker')
            self._worker.start()

    def _enqueue(self, key, fn, priority):
        with self._cv:
            if self._running and self._running[0] == key:
                return
            job = self._jobs.get(key)
            if job is not None:
                if priority < job[1]:
                    job[1] = priority
                    heapq.heappush(self._heap, (priority, next(self._seq), key))
                    self._cv.notify()
                return
            self._failures.pop(key, None)
            self._jobs[key] = [fn, priority]
            heapq.heappush(self._heap, (priority, next(self._seq), key))
            self._cv.notify()

    def _more_urgent_waiting(self, priority):
        with self._cv:
            return any(self._jobs.get(k) and self._jobs[k][1] < priority for _, _, k in self._heap)

    def _work_loop(self):
        while True:
            with self._cv:
                while not self._heap:
                    self._cv.wait()
                priority, _seq, key = heapq.heappop(self._heap)
                job = self._jobs.get(key)
                if job is None or job[1] != priority:
                    continue
                del self._jobs[key]
                self._running = (key, priority)
            self.run_job(key, job[0], priority)

    def run_job(self, key, fn, priority):
        try:
            fn(_Ctx(self, priority))
            self._failures.pop(key, None)
        except _Yield:
            with self._cv:
                self._running = None
            self._enqueue(key, fn, priority)
        except _Disabled:
            pass
        except OfflineError as e:
            self._failures[key] = ('offline', str(e), time.monotonic())
        except HttpError as e:
            # MusicBrainz busy (503/429 past every retry) or a timeout: worth
            # another go shortly, and not an error to show anybody.
            kind = 'busy' if e.status in (0, 429, 502, 503, 504) else 'error'
            _log(f'job {key}: {e}')
            self._failures[key] = (kind, str(e), time.monotonic())
        except Exception as e:  # noqa: BLE001 — a job must never kill the worker
            _log(f'job {key} failed: {type(e).__name__}: {e}')
            self._failures[key] = ('error', f'{type(e).__name__}: {e}', time.monotonic())
        finally:
            with self._cv:
                if self._running and self._running[0] == key:
                    self._running = None
                self._cv.notify_all()

    def job_state(self, key):
        with self._cv:
            if key in self._jobs or (self._running and self._running[0] == key):
                return 'pending', ''
        f = self._failures.get(key)
        if f and time.monotonic() - f[2] < FAILURE_HOLD:
            return f[0], f[1]
        return None, ''

    def wait_idle(self, timeout=60):
        """Tests and the prefetch: block until no job is queued or running."""
        deadline = time.monotonic() + timeout
        with self._cv:
            while self._heap and any(k in self._jobs for _, _, k in self._heap) or self._running:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._cv.wait(min(left, 0.5))
        return True

    def _ensure(self, key, fn, priority):
        """Queue `fn` unless it failed moments ago; returns the status to
        report meanwhile ('pending', 'offline' or 'error') and a message. A job
        that found the service busy stays 'pending' and is queued again after
        BUSY_RETRY seconds, so a polling screen simply keeps waiting."""
        state, message = self.job_state(key)
        if state in ('offline', 'error'):
            return state, message
        if state == 'busy':
            f = self._failures.get(key)
            if f and time.monotonic() - f[2] < BUSY_RETRY:
                return 'pending', ''
        self._enqueue(key, fn, priority)
        return 'pending', ''

    # settings
    def _flag(self, name):
        try:
            with open(os.path.join(self.etc_dir, name)) as f:
                return f.read().strip() != '0'
        except OSError:
            return True

    def online_enabled(self):
        return self._flag('meta-online')

    def prefetch_enabled(self):
        return self._flag('meta-prefetch')

    def _write_flag(self, name, value):
        os.makedirs(self.etc_dir, exist_ok=True)
        path = os.path.join(self.etc_dir, name)
        tmp = path + '.tmp'
        with open(tmp, 'w') as f:
            f.write('1\n' if value else '0\n')
        os.replace(tmp, path)

    def settings(self):
        try:
            stats = self.cache.stats()
        except Exception as e:  # noqa: BLE001
            _log(f'cache stats unavailable: {e}')
            stats = {'albums': 0, 'artists': 0, 'bytes': 0}
        return {'online': self.online_enabled(), 'prefetch': self.prefetch_enabled(), 'cache': stats,
                'prefetch_state': dict(self._prefetch)}

    def set_settings(self, online=None, prefetch=None):
        if online is not None:
            self._write_flag('meta-online', bool(online))
            if online:
                self.client.reset()
        if prefetch is not None:
            self._write_flag('meta-prefetch', bool(prefetch))
        self._settings_event.set()
        return self.settings()

    def clear_cache(self):
        self.cache.clear()
        self._failures.clear()
        self._people_ids.clear()
        self._prefetch['done'] = 0
        return {'ok': True}

    # cached data helpers
    def _fresh(self, key, ttl=DATA_TTL):
        """(value, negative, stale) or None."""
        hit = self.cache.get(key)
        if hit is None:
            return None
        value, age, negative = hit
        limit = NEGATIVE_TTL if negative else ttl
        return value, negative, age > limit

    def _mb(self, ctx, path, **params):
        ctx.check()
        return mb_get(path, client=self.client, retries=5, check=ctx.check, **params)

    def _wiki(self, ctx, url):
        ctx.check()
        return self.client.get_json(url, group='wiki', timeout=15, retries=2, check=ctx.check)

    # library access
    def _library_album(self, album_id):
        album = self.lyrion.album(album_id)
        if album is None:
            return None
        tracks = self.lyrion.album_tracks(album_id)
        album['tracks'] = tracks
        album['fingerprint'] = fingerprint(album['title'], album['artist'], len(tracks))
        try:
            if self.cache.index_get(album['id'], album['title'], album['artist']) != album['fingerprint']:
                self.cache.index_put(album['id'], album['title'], album['artist'], album['fingerprint'])
        except sqlite3.Error:
            pass
        discs = [t['disc'] for t in tracks if t['disc']]
        album['disc'] = max(set(discs), key=discs.count) if discs else 1
        return album

    def device_lang(self):
        try:
            with open(os.path.join(self.etc_dir, 'ui-language')) as f:
                return _lang_ok(f.read().strip().lower())
        except OSError:
            return 'en'

    # ── album ──
    def album(self, album_id, lang='en'):
        lang = _lang_ok(lang)
        if not self.online_enabled():
            return {'status': 'disabled', 'album_id': album_id}
        try:
            lib = self._library_album(album_id)
        except LyrionError as e:
            return {'status': 'error', 'album_id': album_id, 'message': f'lyrion: {e}'}
        if lib is None:
            return {'status': 'error', 'album_id': album_id, 'message': 'unknown album'}
        fp = lib['fingerprint']
        job_key = f'album:{fp}'

        def job(ctx, _id=album_id, _lang=lang):
            self._job_album(ctx, _id, fp, _lang)

        pin = self.cache.get_pin(fp)
        if pin and pin['mbid'] == 'none':
            return {'status': 'nomatch', 'album_id': album_id, 'match': {'mbid': None, 'how': 'manual'},
                    'candidates': []}
        if pin:
            match = {'mbid': pin['mbid'], 'how': 'manual', 'score': 100, 'release_group': None}
        else:
            hit = self._fresh(f'match:{fp}')
            if hit is None or (hit[1] and hit[2]):
                status, message = self._ensure(job_key, job, PRIO_INTERACTIVE)
                return {'status': status, 'album_id': album_id, 'message': message} if message else \
                    {'status': status, 'album_id': album_id}
            match, negative, stale = hit
            if stale:
                self._enqueue(job_key, job, PRIO_BACKGROUND)
            if negative:
                return {'status': 'nomatch', 'album_id': album_id,
                        'match': {'mbid': None, 'how': match.get('how') or 'search'},
                        'candidates': [public_candidate(c) for c in (match.get('candidates') or [])[:5]]}
        rel_hit = self._fresh(f"release:{match['mbid']}")
        if rel_hit is None:
            status, message = self._ensure(job_key, job, PRIO_INTERACTIVE)
            out = {'status': status, 'album_id': album_id}
            if message:
                out['message'] = message
            return out
        model, negative, stale = rel_hit
        if negative:
            return {'status': 'nomatch', 'album_id': album_id, 'match': {'mbid': match['mbid'], 'how': match.get('how')},
                    'candidates': []}
        if stale:
            self._enqueue(job_key, job, PRIO_BACKGROUND)
        status = 'ok'
        if model.get('parent_works') and not model.get('parent_done'):
            # Composers still to be read from the parent works: the data is
            # shown, and the screen keeps polling until they are in.
            if self._ensure(job_key, job, PRIO_INTERACTIVE)[0] == 'pending':
                status = 'pending'
        about = None
        if model.get('wikidata'):
            about, wstatus = self._about(model['wikidata'], lang, PRIO_INTERACTIVE)
            if wstatus == 'pending':
                status = 'pending'
        return self._album_response(album_id, lib, match, model, about, status)

    def _album_response(self, album_id, lib, match, model, about, status):
        mode, pos, ds = self._align(model, lib['tracks'])
        coords = [(t['disc'] or 1, t['n'] or i + 1) for i, t in enumerate(lib['tracks'])]
        if len(set(coords)) != len(coords):
            coords = None       # the library's numbering is ambiguous: keep MusicBrainz's
        credits, tracks, places = album_view(model, mode, pos, lib.get('disc') or 1, coords)
        names = self._name_index()
        unresolved = {p['mbid'] for e in credits for p in e['people']
                      if p.get('mbid') and p['mbid'] not in self._people_ids}
        if unresolved:
            # Library ids by MBID are a local Lyrion question, but one per
            # person: asked by the worker, used by the next request.
            self._enqueue(f'people:{match.get("mbid")}', lambda ctx, ids=unresolved: self._resolve_people_ids(ids),
                          PRIO_BACKGROUND)
        for entry in credits:
            self._link_people(entry['people'], names)
        for t in tracks:
            for entry in t['credits']:
                self._link_people(entry['people'], names)
        url = f"{MB_WEB}/release/{model['mbid']}"
        score = match.get('score')
        if score is None and ds:
            score = ds['score']
        return {
            'status': status,
            'album_id': album_id,
            'match': {'mbid': model['mbid'], 'release_group': model.get('release_group'),
                      'how': match.get('how') or 'search', 'score': score,
                      'medium': pos if mode == 'medium' else None},
            'release': {
                'title': model['title'], 'artist': model['artist'], 'date': model['date'],
                'first_release_date': model['first_release_date'], 'type': model['type'],
                'secondary_types': model['secondary_types'], 'labels': model['labels'],
                'country': model['country'], 'barcode': model['barcode'], 'disc_count': model['disc_count'],
                'track_count': model['track_count'], 'url': url,
            },
            'credits': credits,
            'tracks': tracks,
            'places': places,
            'about': about,
            'attribution': [{'source': 'MusicBrainz', 'url': url, 'license': 'CC0'}],
        }

    def _align(self, model, lib_tracks):
        media = [{'position': m['position'], 'format': m['format'], 'track-count': m['track_count'],
                  'tracks': [{'length': t.get('length_ms')} for t in m['tracks']]} for m in model.get('media') or []]
        best = best_alignment(lib_tracks, media)
        if best is None:
            return 'all', None, None
        return best

    def _name_index(self):
        try:
            return self.lyrion.artist_name_index()
        except LyrionError:
            return {}

    def _link_people(self, people, names):
        for p in people:
            aid = None
            known = self._people_ids.get(p.get('mbid'))
            if known and known[0] is not None:
                aid = known[0]
            if aid is None:
                aid = names.get(normalise(p.get('name')))
            p['artist_id'] = aid

    def _resolve_people_ids(self, mbids, limit=60):
        now = time.monotonic()
        for mbid in list(mbids)[:limit]:
            known = self._people_ids.get(mbid)
            if known and now - known[1] < 1800:
                continue
            try:
                self._people_ids[mbid] = (self.lyrion.artist_id_by_mbid(mbid), now)
            except LyrionError:
                return

    def _job_album(self, ctx, album_id, fp, lang):
        lib = self._library_album(album_id)
        if lib is None or lib['fingerprint'] != fp:
            return
        pin = self.cache.get_pin(fp)
        if pin and pin['mbid'] == 'none':
            return
        if pin:
            mbid, how = pin['mbid'], 'manual'
        else:
            hit = self._fresh(f'match:{fp}')
            if hit is None or hit[2]:
                match = self._match_album(ctx, lib)
                self._store_match(fp, lib, match)
            else:
                match = hit[0]
            mbid, how = match.get('mbid'), match.get('how')
            if not mbid:
                return
        model = self._release_model(ctx, mbid)
        if model is None:
            return
        people = model_people(model)
        roles = {k: v[1] for k, v in people.items()}
        self.cache.set_appearances(fp, album_id, lib['title'], lib['artist'], lib.get('artwork_track_id'), roles)
        self._resolve_people_ids(people.keys())
        if model.get('wikidata'):
            self._job_about(ctx, model['wikidata'], lang)

    def _store_match(self, fp, lib, match):
        """The match is keyed by the album's fingerprint (Lyrion renumbers
        albums when the library is scanned from scratch) and remembers the
        album id it was last seen under."""
        match = dict(match, album_id=lib['id'], title=lib['title'], artist=lib['artist'],
                     track_count=len(lib['tracks']))
        self.cache.put(f'match:{fp}', match, negative=not match.get('mbid'))
        self.cache.index_put(lib['id'], lib['title'], lib['artist'], fp)

    def _release_model(self, ctx, mbid):
        hit = self._fresh(f'release:{mbid}')
        if hit is not None and not hit[2]:
            model = hit[0]
            if hit[1]:
                return None
        else:
            try:
                raw = self._mb(ctx, f'release/{mbid}', inc=RELEASE_INC)
            except NotFoundError:
                self.cache.put(f'release:{mbid}', {'missing': True}, negative=True)
                return None
            model = build_release_model(raw)
            if model['mbid'] != mbid:
                # A merged release answers under its new MBID: keep both keys.
                self.cache.put(f"release:{model['mbid']}", model)
            self.cache.put(f'release:{mbid}', model)
        if model.get('parent_works') and not model.get('parent_done'):
            for wid in model['parent_works'][:6]:
                if wid in model['parent_credits']:
                    continue
                whit = self._fresh(f'work:{wid}')
                if whit is not None and not whit[2]:
                    rels = whit[0].get('relations') or []
                else:
                    try:
                        w = self._mb(ctx, f'work/{wid}', inc='artist-rels')
                        rels = [r for r in w.get('relations') or [] if r.get('target-type') == 'artist']
                    except NotFoundError:
                        rels = []
                    self.cache.put(f'work:{wid}', {'relations': rels})
                model['parent_credits'][wid] = rels
            model['parent_done'] = True
            self.cache.put(f'release:{mbid}', model)
        return model

    def remember_release(self, raw):
        """Cache a full RELEASE_INC lookup made elsewhere (the CD ripper), so
        the album page of a freshly ripped disc needs no request of its own."""
        try:
            model = build_release_model(raw)
            if model.get('mbid'):
                self.cache.put(f"release:{model['mbid']}", model)
        except Exception as e:  # noqa: BLE001
            _log(f'remember_release failed: {e}')

    def _match_album(self, ctx, lib):
        """Find the release for a library album. Tags first (MUSICBRAINZ_ALBUMID
        on the first track), then a search whose candidates must line up by
        track count and, after a light lookup of at most three of them, by
        track lengths. Returns the match record (mbid None = no confident
        match), candidates included for the manual choice."""
        tracks = lib['tracks']
        if tracks:
            try:
                tags = self.lyrion.raw_tags(tracks[0]['id'])
            except LyrionError:
                tags = {}
            ids = tag_mbids(tags, 'MUSICBRAINZALBUMID')
            if ids:
                rg = (tag_mbids(tags, 'MUSICBRAINZRELEASEGROUPID') or [None])[0]
                return {'mbid': ids[0], 'release_group': rg, 'how': 'tag', 'score': 100, 'candidates': []}
        count = len(tracks)
        if not count:
            return {'mbid': None, 'how': 'search', 'candidates': []}
        various = is_various(lib['artist'], lib.get('compilation'))
        title = lib['title']
        stripped = strip_edition(title)
        artist = lib['artist']
        queries = []
        artist_clause = '' if various or not lucene_tokens(artist) else f' AND artist:{lucene_phrase(artist)}'
        if lucene_tokens(title):
            queries.append(f'release:{lucene_phrase(title)}{artist_clause}')
        if normalise(stripped) != normalise(title) and lucene_tokens(stripped):
            queries.append(f'release:{lucene_phrase(stripped)}{artist_clause}')
        # Looser: words instead of phrases, and only the first name of a
        # "Conductor - Orchestra - Soloist" artist string.
        first_artist = lucene_tokens(re.split(r' - |/|;|,| feat\.? | & ', artist)[0])
        loose_artist = '' if various or not first_artist else f' AND artist:{first_artist}'
        if lucene_tokens(stripped):
            queries.append(f'release:{lucene_tokens(stripped)}{loose_artist}')
        candidates = {}
        year = lib.get('year') or None
        tried = set()
        tried_shapes = set()
        best = None
        for q in _uniq(queries):
            results = self._search_releases(ctx, q)
            for c in results:
                if c['mbid'] and c['mbid'] not in candidates:
                    candidates[c['mbid']] = c
            ranked = [c for c in rank_candidates(results, count, year) if c['mbid'] not in tried]
            for c in diverse(ranked, max(0, 3 - len(tried)), tried_shapes):
                tried.add(c['mbid'])
                tried_shapes.add(edition_shape(c))
                media = self._light_media(ctx, c['mbid'])
                fit = best_alignment(tracks, media)
                if fit is None:
                    continue
                ds = fit[2]
                c['score'] = ds['score'] if ds else 0
                if duration_accepted(ds) and (best is None or ds['score'] > best[1]['score']):
                    best = (c, ds)
            if best is not None or len(tried) >= 3:
                break
        cands = sorted(candidates.values(), key=lambda c: -(c.get('score') or 0))[:25]
        if best is None:
            return {'mbid': None, 'how': 'search', 'candidates': cands}
        c, ds = best
        return {'mbid': c['mbid'], 'release_group': c.get('release_group'), 'how': 'search',
                'score': ds['score'], 'candidates': cands}

    def _search_releases(self, ctx, query):
        key = 'search:' + hashlib.sha1(query.encode('utf-8')).hexdigest()[:24]
        hit = self._fresh(key, ttl=NEGATIVE_TTL)
        if hit is not None and not hit[2]:
            return [dict(c) for c in hit[0]]
        data = self._mb(ctx, 'release', query=query, limit=25)
        results = [release_summary(r) for r in data.get('releases') or []]
        self.cache.put(key, results)
        return results

    def _light_media(self, ctx, mbid):
        hit = self._fresh(f'light:{mbid}')
        if hit is not None and not hit[2]:
            return hit[0]
        try:
            data = self._mb(ctx, f'release/{mbid}', inc='recordings')
        except NotFoundError:
            data = {}
        media = [{'position': m.get('position'), 'format': m.get('format') or '',
                  'track-count': m.get('track-count'),
                  'tracks': [{'length': t.get('length') or (t.get('recording') or {}).get('length')}
                             for t in m.get('tracks') or []]}
                 for m in data.get('media') or []]
        self.cache.put(f'light:{mbid}', media)
        return media

    # ── about / bio ──
    def _about(self, qid, lang, priority):
        """(about dict or None, 'ok'|'pending'|'none')."""
        links_hit = self._fresh(f'wikidata:{qid}')
        if links_hit is None:
            state, _ = self.job_state(f'about:{qid}:{lang}')
            if state in ('offline', 'error'):
                return None, 'none'
            self._enqueue(f'about:{qid}:{lang}', lambda ctx: self._job_about(ctx, qid, lang), priority)
            return None, 'pending'
        links = links_hit[0] if not links_hit[1] else {}
        for code in _uniq([lang, 'en']):
            title = links.get(code)
            if not title:
                continue
            hit = self._fresh(f'wiki:{code}:{title}')
            if hit is None:
                state, _ = self.job_state(f'about:{qid}:{lang}')
                if state in ('offline', 'error'):
                    return None, 'none'
                self._enqueue(f'about:{qid}:{lang}', lambda ctx: self._job_about(ctx, qid, lang), priority)
                return None, 'pending'
            value, negative, stale = hit
            if stale:
                self._enqueue(f'about:{qid}:{lang}', lambda ctx: self._job_about(ctx, qid, lang), PRIO_BACKGROUND)
            if negative or not value.get('text'):
                continue
            return {'text': value['text'], 'lang': code, 'title': value.get('title') or title,
                    'url': wikipedia_url(code, value.get('title') or title), 'source': 'Wikipedia',
                    'license': 'CC BY-SA 4.0'}, 'ok'
        return None, 'none'

    def _job_about(self, ctx, qid, lang):
        if not QID_RE.match(qid or ''):
            return
        links_hit = self._fresh(f'wikidata:{qid}')
        if links_hit is None or links_hit[2]:
            url = f'{WIKIDATA_API}?' + _qs({'action': 'wbgetentities', 'ids': qid, 'props': 'sitelinks',
                                            'sitefilter': 'itwiki|enwiki', 'format': 'json'})
            try:
                data = self._wiki(ctx, url)
            except NotFoundError:
                data = {}
            sitelinks = ((data.get('entities') or {}).get(qid) or {}).get('sitelinks') or {}
            links = {k[:-4]: v.get('title') for k, v in sitelinks.items() if k.endswith('wiki') and v.get('title')}
            self.cache.put(f'wikidata:{qid}', links, negative=not links)
        else:
            links = links_hit[0] if not links_hit[1] else {}
        for code in _uniq([lang, 'en']):
            title = links.get(code)
            if not title:
                continue
            hit = self._fresh(f'wiki:{code}:{title}')
            if hit is not None and not hit[2]:
                if not hit[1] and hit[0].get('text'):
                    return
                continue
            url = f'https://{code}.wikipedia.org/w/api.php?' + _qs({
                'action': 'query', 'prop': 'extracts', 'explaintext': 1, 'exintro': 1, 'redirects': 1,
                'titles': title, 'format': 'json', 'formatversion': 2})
            try:
                data = self._wiki(ctx, url)
            except NotFoundError:
                data = {}
            pages = (data.get('query') or {}).get('pages') or []
            page = pages[0] if pages else {}
            text = clean_extract(page.get('extract') or '')
            if page.get('missing') or not text:
                self.cache.put(f'wiki:{code}:{title}', {'title': title}, negative=True)
                continue
            self.cache.put(f'wiki:{code}:{title}', {'title': page.get('title') or title, 'text': text})
            return

    # ── candidates / pin ──
    def album_candidates(self, album_id):
        if not self.online_enabled():
            return {'status': 'disabled', 'album_id': album_id, 'current': None, 'pinned': None, 'candidates': []}
        try:
            lib = self._library_album(album_id)
        except LyrionError as e:
            return {'status': 'error', 'album_id': album_id, 'message': f'lyrion: {e}', 'candidates': []}
        if lib is None:
            return {'status': 'error', 'album_id': album_id, 'message': 'unknown album', 'candidates': []}
        fp = lib['fingerprint']
        pin = self.cache.get_pin(fp)
        hit = self._fresh(f'match:{fp}')
        key = f'candidates:{fp}'

        def job(ctx, _id=album_id):
            self._job_candidates(ctx, _id, fp)

        status = 'ok'
        match = hit[0] if hit else None
        if hit is None or hit[2]:
            status, message = self._ensure(key, job, PRIO_INTERACTIVE)
        current = (pin or {}).get('mbid') if pin and pin['mbid'] != 'none' else (match or {}).get('mbid')
        rg = (match or {}).get('release_group')
        if current:
            rel_hit = self._fresh(f'release:{current}')
            if rel_hit and not rel_hit[1]:
                rg = rel_hit[0].get('release_group') or rg
        editions = []
        if rg:
            eh = self._fresh(f'rgreleases:{rg}', ttl=NEGATIVE_TTL)
            if eh is None or eh[2]:
                s, _m = self._ensure(key, job, PRIO_INTERACTIVE)
                if status == 'ok':
                    status = s
            if eh is not None:
                editions = eh[0] if not eh[1] else []
        elif current and status == 'ok':
            status, _m = self._ensure(key, job, PRIO_INTERACTIVE)
        merged = {}
        count = len(lib['tracks'])
        for c in (match or {}).get('candidates') or []:
            merged[c['mbid']] = dict(c)
        for c in editions:
            if c['mbid'] in merged:
                continue
            fits = alignments(count, c.get('media_counts'), c.get('media_formats'))
            merged[c['mbid']] = dict(c, score=50 if fits else 20)
        if current and current in merged and match and match.get('score') is not None:
            merged[current]['score'] = max(merged[current].get('score') or 0, match.get('score') or 0)
        ordered = sorted(merged.values(), key=lambda c: (c['mbid'] != current, -(c.get('score') or 0)))[:25]
        return {'status': status, 'album_id': album_id, 'current': current,
                'pinned': (pin or {}).get('mbid'), 'candidates': [public_candidate(c) for c in ordered]}

    def _job_candidates(self, ctx, album_id, fp):
        lib = self._library_album(album_id)
        if lib is None or lib['fingerprint'] != fp:
            return
        hit = self._fresh(f'match:{fp}')
        if hit is None or hit[2]:
            match = self._match_album(ctx, lib)
            self._store_match(fp, lib, match)
        else:
            match = hit[0]
        pin = self.cache.get_pin(fp)
        current = pin['mbid'] if pin and pin['mbid'] != 'none' else match.get('mbid')
        rg = match.get('release_group')
        if current and not rg:
            model = self._release_model(ctx, current)
            rg = (model or {}).get('release_group')
        if not rg:
            return
        eh = self._fresh(f'rgreleases:{rg}', ttl=NEGATIVE_TTL)
        if eh is not None and not eh[2]:
            return
        data = self._mb(ctx, 'release', **{'release-group': rg, 'inc': 'labels+media', 'limit': 100})
        editions = [release_summary(r, score=None) for r in data.get('releases') or []]
        self.cache.put(f'rgreleases:{rg}', editions)

    def album_pin(self, album_id, mbid, lang='en'):
        try:
            lib = self._library_album(album_id)
        except LyrionError as e:
            return {'status': 'error', 'album_id': album_id, 'message': f'lyrion: {e}'}
        if lib is None:
            return {'status': 'error', 'album_id': album_id, 'message': 'unknown album'}
        if mbid is not None and mbid != 'none':
            if not UUID_RE.fullmatch(str(mbid)):
                return {'status': 'error', 'album_id': album_id, 'message': 'invalid mbid'}
            mbid = mbid.lower()
        fp = lib['fingerprint']
        self.cache.set_pin(fp, album_id, mbid, lib['title'], lib['artist'])
        if mbid == 'none':
            self.cache.drop_appearances(fp)
        self._failures.pop(f'album:{fp}', None)
        return self.album(album_id, lang=lang)

    # ── artists ──
    def artist(self, artist_id, lang='en'):
        lang = _lang_ok(lang)
        if not self.online_enabled():
            return {'status': 'disabled', 'artist_id': artist_id}
        try:
            art = self.lyrion.artist(artist_id)
        except LyrionError as e:
            return {'status': 'error', 'artist_id': artist_id, 'message': f'lyrion: {e}'}
        if art is None:
            return {'status': 'error', 'artist_id': artist_id, 'message': 'unknown artist'}
        name_key = normalise(art['name'])
        if not name_key or is_various(art['name']):
            return {'status': 'nomatch', 'artist_id': artist_id}
        key = f'artist:{name_key}'

        def job(ctx, _id=artist_id, _name=art['name']):
            self._job_artist(ctx, _id, _name, lang)

        hit = self._fresh(f'artistmatch:{name_key}')
        if hit is None or (hit[1] and hit[2]):
            status, message = self._ensure(key, job, PRIO_INTERACTIVE)
            out = {'status': status, 'artist_id': artist_id}
            if message:
                out['message'] = message
            return out
        match, negative, stale = hit
        if stale:
            self._enqueue(key, job, PRIO_BACKGROUND)
        if negative:
            return {'status': 'nomatch', 'artist_id': artist_id}
        return self._artist_response(match['mbid'], lang, artist_id, key, job)

    def person(self, mbid, lang='en'):
        lang = _lang_ok(lang)
        if not self.online_enabled():
            return {'status': 'disabled', 'mbid': mbid}
        if not UUID_RE.fullmatch(str(mbid or '')):
            return {'status': 'error', 'mbid': mbid, 'message': 'invalid mbid'}
        mbid = mbid.lower()
        key = f'person:{mbid}'

        def job(ctx):
            self._artist_model(ctx, mbid, lang)

        artist_id = None
        try:
            artist_id = self.lyrion.artist_id_by_mbid(mbid)
        except LyrionError:
            pass
        out = self._artist_response(mbid, lang, artist_id, key, job)
        if out.get('artist') and out.get('artist_id') is None:
            out['artist_id'] = self._name_index().get(normalise(out['artist']['name']))
        return out

    def _artist_response(self, mbid, lang, artist_id, key, job):
        hit = self._fresh(f'artist:{mbid}')
        if hit is None:
            status, message = self._ensure(key, job, PRIO_INTERACTIVE)
            out = {'status': status, 'artist_id': artist_id}
            if message:
                out['message'] = message
            return out
        model, negative, stale = hit
        if negative:
            return {'status': 'nomatch', 'artist_id': artist_id}
        if stale:
            self._enqueue(key, job, PRIO_BACKGROUND)
        status = 'ok'
        bio = None
        if model.get('wikidata'):
            bio, wstatus = self._about(model['wikidata'], lang, PRIO_INTERACTIVE)
            if wstatus == 'pending':
                status = 'pending'
            if bio:
                model['urls'] = dict(model['urls'], wikipedia=bio['url'])
        names = self._name_index()
        artist = {k: v for k, v in model.items() if k not in ('wikidata', 'aliases')}
        artist['members'] = [dict(m) for m in artist['members']]
        artist['member_of'] = [dict(m) for m in artist['member_of']]
        self._link_people(artist['members'], names)
        self._link_people(artist['member_of'], names)
        url = f'{MB_WEB}/artist/{mbid}'
        return {'status': status, 'artist_id': artist_id, 'artist': artist, 'bio': bio,
                'attribution': [{'source': 'MusicBrainz', 'url': url, 'license': 'CC0'}]}

    def _artist_model(self, ctx, mbid, lang):
        hit = self._fresh(f'artist:{mbid}')
        if hit is None or hit[2]:
            try:
                raw = self._mb(ctx, f'artist/{mbid}', inc=ARTIST_INC)
            except NotFoundError:
                self.cache.put(f'artist:{mbid}', {'missing': True}, negative=True)
                return None
            model = build_artist_model(raw)
            self.cache.put(f'artist:{mbid}', model)
        else:
            if hit[1]:
                return None
            model = hit[0]
        if model.get('wikidata'):
            self._job_about(ctx, model['wikidata'], lang)
        self._resolve_people_ids([m['mbid'] for m in model['members'] + model['member_of'] if m.get('mbid')])
        return model

    def _job_artist(self, ctx, artist_id, name, lang):
        name_key = normalise(name)
        hit = self._fresh(f'artistmatch:{name_key}')
        if hit is None or hit[2]:
            match = self._match_artist(ctx, artist_id, name)
            self.cache.put(f'artistmatch:{name_key}', match, negative=not match.get('mbid'))
        else:
            match = hit[0]
        if match.get('mbid'):
            self._artist_model(ctx, match['mbid'], lang)
            self._people_ids[match['mbid']] = (artist_id, time.monotonic())

    def _match_artist(self, ctx, artist_id, name):
        """MBID of a library artist: tags on one of their tracks, then the
        credits of albums already matched, then a MusicBrainz search accepted
        only on an exact name plus shared album titles (or a single exact-name
        candidate with nothing contradicting it)."""
        target = normalise(name)
        try:
            track_ids = self.lyrion.artist_tracks(artist_id, limit=3)
        except LyrionError:
            track_ids = []
        for tid in track_ids:
            try:
                tags = self.lyrion.raw_tags(tid)
            except LyrionError:
                break
            found = pair_tag_artist(tags, target)
            if found:
                return {'mbid': found, 'how': 'tag'}
        try:
            albums = self.lyrion.artist_albums(artist_id)
        except LyrionError:
            albums = []
        for a in albums[:40]:
            fp = self.cache.index_get(a['id'], a['title'], a['artist'])
            if not fp:
                continue
            hit = self._fresh(f'match:{fp}')
            if not hit or hit[1] or not hit[0].get('mbid'):
                continue
            rel = self._fresh(f"release:{hit[0]['mbid']}")
            if not rel or rel[1]:
                continue
            for p in rel[0].get('artist_credit') or []:
                if normalise(p['name']) == target:
                    return {'mbid': p['mbid'], 'how': 'album'}
        data = self._mb(ctx, 'artist', query=f'artist:{lucene_phrase(name)}', limit=10)
        exact = []
        for a in data.get('artists') or []:
            names = [a.get('name'), a.get('sort-name')] + [x.get('name') for x in a.get('aliases') or []]
            if (a.get('score') or 0) >= 80 and any(normalise(n) == target for n in names if n):
                exact.append(a)
        if not exact:
            return {'mbid': None, 'how': 'search'}
        lib_titles = {normalise(strip_edition(a['title'])) for a in albums if a.get('title')}
        verdicts = []
        for a in exact[:3]:
            rg = self._mb(ctx, 'release-group', artist=a['id'], limit=100)
            titles = {normalise(strip_edition(g.get('title'))) for g in rg.get('release-groups') or []}
            overlap = len(titles & lib_titles)
            verdicts.append((overlap, len(titles), a))
        verdicts.sort(key=lambda v: -v[0])
        if verdicts[0][0] > 0 and (len(verdicts) == 1 or verdicts[1][0] < verdicts[0][0]):
            return {'mbid': verdicts[0][2]['id'], 'how': 'search'}
        if len(exact) == 1 and verdicts[0][0] == 0 and (verdicts[0][1] == 0 or not lib_titles):
            return {'mbid': exact[0]['id'], 'how': 'search'}
        return {'mbid': None, 'how': 'search'}

    # ── appearances ──
    def appearances(self, mbid):
        if not UUID_RE.fullmatch(str(mbid or '')):
            return {'status': 'error', 'message': 'invalid mbid', 'albums': []}
        rows = self.cache.appearances(mbid.lower())
        try:
            library = self._library_listing()
        except LyrionError:
            library = None
        out = []
        for row in rows[:300]:
            album_id = row['album_id']
            if library is not None:
                by_id, by_name = library
                a = by_id.get(album_id)
                if a is None or normalise(a['title']) != normalise(row['title']):
                    # Stale id (the library was scanned again): same album by
                    # title and artist, or it is gone.
                    a = by_name.get((normalise(row['title']), normalise(row['artist'])))
                    if a is None:
                        continue
                    album_id = a['id']
                    self.cache.move_appearances(row['fingerprint'], album_id, a.get('artwork_track_id'))
                row['artwork_track_id'] = a.get('artwork_track_id') or row['artwork_track_id']
            out.append({'album_id': album_id, 'title': row['title'], 'artist': row['artist'],
                        'artwork_track_id': row['artwork_track_id'],
                        'roles': [{'group': g, 'role': r, 'attr': at} for g, r, at in row['roles']]})
        return {'status': 'ok', 'albums': out}

    def _library_listing(self, max_age=300):
        cached = getattr(self, '_listing', None)
        url = self.lyrion.base_url()
        if cached and cached[0] == url and time.monotonic() - cached[1] < max_age:
            return cached[2]
        albums = self.lyrion.all_albums()
        by_id = {a['id']: a for a in albums}
        by_name = {}
        for a in albums:
            by_name.setdefault((normalise(a['title']), normalise(a['artist'])), a)
        self._listing = (url, time.monotonic(), (by_id, by_name))
        return by_id, by_name

    # ── prefetch ──
    def start_prefetch(self, delay=PREFETCH_START_DELAY):
        if self._prefetch_thread is None:
            self._prefetch_thread = threading.Thread(target=self._prefetch_loop, args=(delay,), daemon=True,
                                                     name='meta-prefetch')
            self._prefetch_thread.start()

    def _prefetch_wait(self, seconds):
        """Sleep, but wake up at once when the settings change."""
        self._settings_event.clear()
        self._settings_event.wait(seconds)

    def _prefetch_active(self):
        return self.online_enabled() and self.prefetch_enabled()

    def _prefetch_loop(self, delay):
        time.sleep(delay)
        albums, listed_at = None, 0.0
        while True:
            try:
                if not self._prefetch_active():
                    self._prefetch['running'] = False
                    self._prefetch_wait(300)
                    continue
                if self.lyrion.scanning():
                    self._prefetch['running'] = False
                    self._prefetch_wait(60)
                    continue
                if albums is None or time.monotonic() - listed_at > PREFETCH_RELIST:
                    albums = [a for a in self.lyrion.all_albums() if not normalise(a['title']) in ('no album', '')]
                    listed_at = time.monotonic()
                    self._prefetch.update(total=len(albums), done=sum(1 for a in albums if self._album_resolved(a)))
                todo = [a for a in albums if not self._album_resolved(a)]
                self._prefetch['done'] = len(albums) - len(todo)
                if not todo:
                    self._prefetch['running'] = False
                    self._prefetch_wait(PREFETCH_RELIST)
                    albums = None
                    continue
                self._prefetch['running'] = True
                if not self._prefetch_one(todo[0]):
                    continue        # known already under another id: no request was made
                if self.client.offline():
                    self._prefetch_wait(300)
                else:
                    self._prefetch_wait(PREFETCH_ALBUM_GAP)
            except LyrionError:
                self._prefetch['running'] = False
                self._prefetch_wait(120)
            except Exception as e:  # noqa: BLE001
                _log(f'prefetch error: {type(e).__name__}: {e}')
                self._prefetch_wait(300)

    def _album_resolved(self, a):
        fp = self.cache.index_get(a['id'], a['title'], a['artist'])
        if not fp:
            return False
        if self.cache.get_pin(fp):
            return True
        hit = self._fresh(f'match:{fp}')
        if hit is None or hit[2]:
            return False
        if hit[1]:
            return True
        return self._fresh(f"release:{hit[0]['mbid']}") is not None

    def _prefetch_one(self, a):
        """Resolve one library album (and its album artist). False when it
        turned out to be resolved already — the same album seen before under
        another id — so the walk can go on without its pause."""
        tracks = self.lyrion.album_tracks(a['id'])
        fp = fingerprint(a['title'], a['artist'], len(tracks))
        self.cache.index_put(a['id'], a['title'], a['artist'], fp)
        if self._album_resolved(a):
            return False
        lang = self.device_lang()
        key = f'album:{fp}'
        self._enqueue(key, lambda ctx, _id=a['id']: self._job_album(ctx, _id, fp, lang), PRIO_PREFETCH)
        self._wait_job(key)
        failure = self._failures.get(key)
        if failure and failure[0] in ('offline', 'busy'):
            return True
        if failure:
            # An album that keeps failing for another reason must not stall
            # the walk: it counts as "not found" for the negative TTL.
            self.cache.put(f'match:{fp}', {'mbid': None, 'how': 'search', 'candidates': [],
                                           'error': failure[1]}, negative=True)
            return True
        if a.get('artist_id') and not is_various(a['artist']) and self._prefetch_active():
            name_key = normalise(a['artist'])
            if name_key and self._fresh(f'artistmatch:{name_key}') is None:
                akey = f'artist:{name_key}'
                self._enqueue(akey, lambda ctx, _id=a['artist_id'], _n=a['artist']:
                              self._job_artist(ctx, int(_id), _n, lang), PRIO_PREFETCH)
                self._wait_job(akey)
        return True

    def _wait_job(self, key, timeout=900):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state, _ = self.job_state(key)
            if state != 'pending':
                return
            if not self._prefetch_active():
                return
            with self._cv:
                self._cv.wait(1.0)


# ── Flask wiring ─────────────────────────────────────────────────────
_service = None
_service_lock = threading.Lock()


def get_service():
    global _service
    with _service_lock:
        if _service is None:
            _service = MetadataService()
        return _service


def request_lang(request):
    lang = (request.args.get('lang') or '').lower()
    if lang in ('it', 'en'):
        return lang
    header = (request.headers.get('X-UI-Lang') or '').lower()
    return header if header in ('it', 'en') else 'en'


def init_app(app, require_auth, service_getter=None):
    """Mount /api/meta/* on a Flask app. `require_auth()` returns None or the
    response to send back (sources_server's _require_pair_token)."""
    from flask import jsonify, request

    svc = service_getter or get_service

    def _int_arg(name, source=None):
        raw = (source if source is not None else request.args).get(name)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    def _bad(message):
        return jsonify({'status': 'error', 'message': message}), 400

    def _guard(fn):
        def wrapper(*a, **kw):
            denied = require_auth()
            if denied:
                return denied
            try:
                return fn(*a, **kw)
            except Exception as e:  # noqa: BLE001
                _log(f'{request.path} failed: {type(e).__name__}: {e}')
                return jsonify({'status': 'error', 'message': f'{type(e).__name__}: {e}'}), 500
        wrapper.__name__ = 'meta_' + fn.__name__
        return wrapper

    @app.route('/api/meta/album', methods=['GET'])
    @_guard
    def album():
        album_id = _int_arg('album_id')
        if album_id is None:
            return _bad('album_id required')
        return jsonify(svc().album(album_id, request_lang(request)))

    @app.route('/api/meta/album/candidates', methods=['GET'])
    @_guard
    def album_candidates():
        album_id = _int_arg('album_id')
        if album_id is None:
            return _bad('album_id required')
        return jsonify(svc().album_candidates(album_id))

    @app.route('/api/meta/album/pin', methods=['POST'])
    @_guard
    def album_pin():
        data = request.get_json(silent=True) or {}
        album_id = _int_arg('album_id', data)
        if album_id is None or 'mbid' not in data:
            return _bad('album_id and mbid required')
        return jsonify(svc().album_pin(album_id, data.get('mbid'), request_lang(request)))

    @app.route('/api/meta/artist', methods=['GET'])
    @_guard
    def artist():
        artist_id = _int_arg('artist_id')
        if artist_id is None:
            return _bad('artist_id required')
        return jsonify(svc().artist(artist_id, request_lang(request)))

    @app.route('/api/meta/person', methods=['GET'])
    @_guard
    def person():
        return jsonify(svc().person(request.args.get('mbid') or '', request_lang(request)))

    @app.route('/api/meta/appearances', methods=['GET'])
    @_guard
    def appearances():
        return jsonify(svc().appearances(request.args.get('mbid') or ''))

    @app.route('/api/meta/settings', methods=['GET', 'POST'])
    @_guard
    def settings():
        if request.method == 'POST':
            data = request.get_json(silent=True) or {}
            online = data.get('online')
            prefetch = data.get('prefetch')
            if (online is not None and not isinstance(online, bool)) or \
                    (prefetch is not None and not isinstance(prefetch, bool)):
                return _bad('online/prefetch must be booleans')
            return jsonify(svc().set_settings(online=online, prefetch=prefetch))
        return jsonify(svc().settings())

    @app.route('/api/meta/cache/clear', methods=['POST'])
    @_guard
    def cache_clear():
        return jsonify(svc().clear_cache())


def start_background(delay=PREFETCH_START_DELAY):
    """Called from sources_server's __main__: the worker starts with the
    service, the library walk a couple of minutes later."""
    try:
        get_service().start_prefetch(delay)
    except Exception as e:  # noqa: BLE001
        _log(f'prefetch not started: {e}')
