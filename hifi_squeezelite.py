#!/usr/bin/env python3
"""squeezelite's command line, owned by one place.

/etc/default/squeezelite (the `ARGS=` line squeezelite.service hands to the
player) used to be edited in four places — the DAC choice, the Lyrion
"follow" role (`-s`), the player name (`-n`) and the DSP on/off path — plus a
few legacy migrations, and by hand over SSH. Nobody owned it. Now the
settings live in a small JSON model, /etc/hifi-player/squeezelite.json, and
the file is RENDERED from that model:

  * api_server.py changes a field, saves the model, renders the file and
    restarts the player;
  * squeezelite.service runs `hifi_squeezelite.py apply` as ExecStartPre, so
    the file is rendered again at every start — a hand edit of the file does
    not survive, by construction, and the file says so in its header. Anyone
    on SSH edits the JSON instead (or uses Settings → Audio), then
    `systemctl restart squeezelite`; `hifi_squeezelite.py show` prints both.

A device that predates the model has only the file: the first load imports
its ARGS line into the model, field by field, so nothing changes for it.

Fields (the UI exposes the starred ones, the rest are set elsewhere):
  output         `-o`, the real DAC. With DSP on the file gets the Loopback
                 instead and this stays the DAC CamillaDSP plays to.
  name, server   `-n`, `-s` (player name; Lyrion host, 127.0.0.1 = own)
  mac, model     `-m` (persistent player MAC, derived from /etc/machine-id
                 the first time it is missing), `-M` (model name, fixed)
  dsd *          auto | dop | native | off. `auto` = native when the DAC
                 declares a DSD_U32/U16 format in /proc/asound, DoP when the
                 output is a USB audio device that does not, and no `-D` at
                 all (PCM) for everything else: `default`, HDMI/DisplayPort,
                 the onboard codec — those take 176.4 kHz PCM, so DoP would
                 reach the speakers as loud noise. `off` = no `-D`,
                 squeezelite converts DSD to PCM; `dop`/`native` are forced.
  dsd_delay_ms * `-D <ms>`, pause when switching between PCM and DSD
  max_rate *     `-r <max>`, 0 = let the DAC say
  volume *       software | hardware (`-V <mixer>`, the DAC's own control)
  mixer *        the ALSA control `-V` drives (first playback volume if empty)
  alsa_buffer *  auto | large (`-a 200:8`)
  stream_buffer* auto | large (`-b 16384:8192`)
  realtime *     `-p 45` for the output thread
  extra *        anything else, one line, validated: no quotes, no `$`, and
                 none of the options handled above
  pcm2dsd *      off | dsd64 | dsd128 | dsd256: every PCM track reaches the
                 DAC as DSD (sox_ng's sigma-delta modulator), when DSD
                 actually reaches the DAC. With this device as the Lyrion
                 server, Lyrion converts it on its way here (hifi-pcm2dsd.py):
                 the player advertises DSD alone (`-c dsd`) so Lyrion has to
                 use the rules this module writes into custom-convert.conf.
                 With another server, whose rules are out of reach, the
                 built-in player converts it itself: squeezelite plays PCM
                 into the Loopback and hifi-pcm2dsd-player.py turns what
                 comes out into DSD for the DAC (sync_player()).
  pcm2dsd_filter * the modulator's noise-shaping filter
  dsp.enabled    squeezelite plays into the CamillaDSP Loopback at 48 kHz

Zones: every further DAC can be a player of its own (a "zone"), one
squeezelite per DAC, run by hifi-zone@<id>.service through `run-zone <id>`.
Their settings live in /etc/hifi-player/zones.json, one model each, with the
same fields and the same renderer as the built-in player; the Lyrion server
is always the built-in player's.

Writers: api_server.py (several request threads) and the ExecStartPre
`apply` (every 5 s while squeezelite crash-loops) all load, change and save
the same two files. They go through update() / apply(), which hold an
flock on `<json>.lock` for the whole load → save → render, and every file
is replaced from a temp file of its own, so no writer loses another's
change or renames someone else's half-written file.
"""
import contextlib
import signal
import urllib.request
import fcntl
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time

CONF = '/etc/hifi-player/squeezelite.json'
DEFAULT = '/etc/default/squeezelite'
PROC_ASOUND = '/proc/asound'
DSP_TARGET_FILE = '/var/lib/hifi-player/dsp-target'
MACHINE_ID = '/etc/machine-id'
LOOPBACK = 'hw:CARD=Loopback,DEV=0'
ZONES_CONF = '/etc/hifi-player/zones.json'
# What the PCM → DSD wrapper reads to know each player's rate and filter. Not
# the models themselves: it runs as Lyrion's user, for every track.
PCM2DSD_MAP = '/etc/hifi-player/pcm2dsd.json'
# Lyrion reads custom-convert.conf next to its convert.conf, and only at start.
# /etc/squeezeboxserver points into the Lyrion version in use, so a Lyrion
# update leaves a fresh directory: the rules are written again at every boot
# (hifi-zones.service, before Lyrion) and after every Lyrion update.
LMS_CONVERT = '/etc/squeezeboxserver/custom-convert.conf'
SOX_NG = '/usr/local/bin/sox_ng'
PCM2DSD_WRAPPER = '/usr/local/sbin/hifi-pcm2dsd.py'
SQUEEZELITE_BIN = '/usr/bin/squeezelite'
DSP_RATE = 48000
# PCM → DSD after another Lyrion server: squeezelite plays every track into
# the Loopback at P2D_RATE and hifi-pcm2dsd-player.py reads the other end.
# Subdevice 0 on both sides, never in use by the DSP at the same time; the
# Bluetooth VU tap keeps to subdevice 1.
P2D_PLAYBACK = 'hw:CARD=Loopback,DEV=0,SUBDEV=0'
P2D_CAPTURE = 'hw:CARD=Loopback,DEV=1,SUBDEV=0'
P2D_RATE = 176400
P2D_PLAYER = '/usr/local/sbin/hifi-pcm2dsd-player.py'
P2D_PLAYER_CONF = '/run/hifi-pcm2dsd/player.json'
P2D_PLAYER_UNIT = 'hifi-pcm2dsd-player.service'
SYS_ALOOP = '/sys/module/snd_aloop'
LIB_MODULES = '/lib/modules'
# How long a writer waits for another one to finish. A Settings → Audio save
# may run amixer under the lock; anything longer than this is a stuck writer.
LOCK_TIMEOUT = 15.0

DEFAULTS = {
    'output': 'default',
    'name': 'OsmiumSound',
    'server': '127.0.0.1',
    'mac': '',
    'model': 'Osmium',
    'dsd': 'auto',
    'dsd_delay_ms': 0,
    'max_rate': 0,
    'volume': 'software',
    'mixer': '',
    'alsa_buffer': 'auto',
    'stream_buffer': 'auto',
    'realtime': False,
    'extra': '',
    'pcm2dsd': 'off',
    'pcm2dsd_filter': 'clans-8',
    'dsp': {'enabled': False},
}
# What Settings → Audio may change and "Back to defaults" resets.
TUNABLE = ('dsd', 'dsd_delay_ms', 'max_rate', 'volume', 'mixer',
           'alsa_buffer', 'stream_buffer', 'realtime', 'extra',
           'pcm2dsd', 'pcm2dsd_filter')

DSD_MODES = ('auto', 'dop', 'native', 'off')
RATES = (0, 44100, 48000, 88200, 96000, 176400, 192000, 352800, 384000, 705600, 768000)
DSD_DELAYS = (0, 100, 250, 500)
ALSA_LARGE = '200:8'
STREAM_LARGE = '16384:8192'
RT_PRIORITY = '45'
# Options the model renders itself: refused in `extra` so they cannot appear twice.
MANAGED_FLAGS = ('-o', '-n', '-s', '-m', '-M', '-D', '-r', '-V', '-a', '-b', '-p', '-v', '-C', '-c')

# PCM → DSD: the DSD rate for each choice. From 44.1 kHz material that is
# 64, 128 and 256 times the CD rate; 48 kHz material is resampled on the way.
PCM2DSD_MODES = ('off', 'dsd64', 'dsd128', 'dsd256')
PCM2DSD_RATES = {'dsd64': 2822400, 'dsd128': 5644800, 'dsd256': 11289600}
PCM2DSD_FILTERS = ('clans-8', 'sdm-8')

_NAME_RE = re.compile(r'^[A-Za-z0-9_.\-]{1,24}$')
_HOST_RE = re.compile(r'^[A-Za-z0-9.\-:\[\]]{1,253}$')
_MAC_RE = re.compile(r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$')
_OUTPUT_RE = re.compile(r'^[A-Za-z0-9_=,.:+\-]{1,120}$')
_MIXER_RE = re.compile(r'^[A-Za-z0-9_.\-]{1,32}$')
# One token of `extra`: squeezelite's own values never need more than this,
# and nothing here can break out of the single-quoted ARGS='…' line or be
# expanded by systemd's $ARGS splitting.
_EXTRA_TOKEN_RE = re.compile(r'^[A-Za-z0-9_:.,=/+\-]{1,64}$')

# ── DSD: what the DAC declares ──────────────────────────────────────
# ALSA format name (as /proc/asound prints it) → squeezelite `-D` format,
# in order of preference when a DAC lists more than one.
_NATIVE_FORMATS = (
    ('DSD_U32_BE', 'u32be'),
    ('DSD_U32_LE', 'u32le'),
    ('DSD_U16_BE', 'u16be'),
    ('DSD_U16_LE', 'u16le'),
    ('DSD_U8', 'u8'),
)
NATIVE_FORMAT_NAMES = tuple(f for _, f in _NATIVE_FORMATS)


def parse_device(device):
    """'hw:CARD=D50s,DEV=0' → ('D50s', 0); the numbered form a hand edit may
    have left, 'hw:1,0', → ('1', 0). Anything else → (None, None)."""
    if not device:
        return None, None
    m = re.match(r'^(?:plug)?hw:(?:CARD=)?([A-Za-z0-9_-]+)(?:,(?:DEV=)?(\d+))?$', device.strip())
    if not m:
        return None, None
    return m.group(1), int(m.group(2) or 0)


def playback_formats(text):
    """Every ALSA format the *playback* side of a /proc/asound stream file
    lists."""
    playback, section = [], None
    for line in (text or '').splitlines():
        s = line.strip()
        if s.startswith('Playback:'):
            section = 'playback'
            continue
        if s.startswith('Capture:'):
            section = 'capture'
            continue
        if section == 'playback' and s.startswith('Format:'):
            playback.extend(s[len('Format:'):].split())
    return playback


def native_format_from_stream(text):
    """The squeezelite format for the first native DSD format the *playback*
    side of a /proc/asound stream file lists, or None (PCM only / DoP)."""
    playback = playback_formats(text)
    for alsa_name, sq_name in _NATIVE_FORMATS:
        if alsa_name in playback:
            return sq_name
    return None


# What probe() answers for an output that is not a USB audio device.
PCM_ONLY = 'pcm'


def _card_dir(root, card):
    """/proc/asound/<card> (a symlink to cardN) or cardN for a numbered card,
    resolved; None when it is not a card directory under `root`."""
    name = f'card{card}' if card.isdigit() else card
    # the card comes from the device string the owner chose: stay under the tree
    path = os.path.realpath(os.path.join(root, name))
    if not path.startswith(root + os.sep) or not os.path.isdir(path):
        return None
    return path


def is_usb_card(card_dir):
    """True when the ALSA card is a USB audio device: snd-usb-audio, and only
    it, gives a card a `usbid` and its `streamN` files. The onboard HDA codec,
    its HDMI/DisplayPort outputs, the Loopback have neither."""
    return (os.path.exists(os.path.join(card_dir, 'usbid'))
            or bool(glob.glob(os.path.join(card_dir, 'stream[0-9]*'))))


def _stream_text(device, proc_asound=None):
    """The /proc/asound stream file of a USB `device`, '' for anything else."""
    card, dev = parse_device(device)
    if card is None:
        return ''
    card_dir = _card_dir(os.path.realpath(proc_asound or PROC_ASOUND), card)
    if card_dir is None:
        return ''
    try:
        with open(os.path.join(card_dir, f'stream{dev}'), encoding='utf-8', errors='replace') as f:
            return f.read()
    except OSError:
        return ''


def dop_bits(device, proc_asound=None):
    """The sample size DoP goes out in to `device`: 32 (S32_LE) unless the DAC
    lists S24_3LE and not S32_LE, as some USB DACs do."""
    formats = playback_formats(_stream_text(device, proc_asound))
    return 24 if 'S24_3LE' in formats and 'S32_LE' not in formats else 32


def probe(device, proc_asound=None):
    """How DSD can reach `device` in `auto` mode: the squeezelite format name
    ('u32be', …) when it declares native DSD, 'dop' when it is a USB audio
    device that does not (an external DAC, where DoP is the usual way in),
    PCM_ONLY for anything else. `default`, HDMI/DisplayPort and the onboard
    codec accept 176.4/192 kHz PCM and would play DoP as full-scale noise
    instead of decoding it (a device in the field had `-o hw:CARD=PCH,DEV=3
    -D`, Intel HDMI): only a USB DAC is a plausible DoP decoder. Never
    raises: an output we cannot read gets PCM, the safe answer."""
    card, dev = parse_device(device)
    if card is None:
        return PCM_ONLY
    root = os.path.realpath(proc_asound or PROC_ASOUND)     # looked up at call time: tests point it elsewhere
    card_dir = _card_dir(root, card)
    if card_dir is None or not is_usb_card(card_dir):
        return PCM_ONLY
    try:
        with open(os.path.join(card_dir, f'stream{dev}'), encoding='utf-8', errors='replace') as f:
            text = f.read()
    except OSError:
        return 'dop'
    return native_format_from_stream(text) or 'dop'


def is_native(fmt):
    return fmt in NATIVE_FORMAT_NAMES


# ── Mixer controls: what `-V` could drive ───────────────────────────
def parse_mixer_controls(scontents):
    """Names of the simple controls with a playback volume, from
    `amixer -c N scontents`. Names with spaces or quotes are skipped: the
    ARGS line is split on whitespace with no quoting."""
    names, current = [], None
    for line in (scontents or '').splitlines():
        m = re.match(r"Simple mixer control '([^']*)',\d+", line.strip())
        if m:
            current = m.group(1)
            continue
        if current and line.strip().startswith('Capabilities:'):
            caps = line.split(':', 1)[1].split()
            if 'pvolume' in caps and _MIXER_RE.match(current):
                names.append(current)
            current = None
    return names


def mixer_controls(device, run=None):
    """Mixer controls of the card behind `device` (empty for `default`,
    the Loopback and anything that is not a hw: card)."""
    card, _ = parse_device(device)
    if card is None or card == 'Loopback':
        return []
    run = run or (lambda cmd: subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout)
    try:
        return parse_mixer_controls(run(['amixer', '-c', card, 'scontents']))
    except Exception:
        return []


# ── Model ───────────────────────────────────────────────────────────
def check_extra(extra):
    """Validate the free-text field. Returns (clean_text, bad_tokens,
    managed_tokens). A managed flag goes away together with its value, so a
    lenient load never leaves a stray `hw:1,0` on the line."""
    tokens = (extra or '').split()
    bad, managed, clean = [], [], []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in MANAGED_FLAGS:
            managed.append(t)
            if i + 1 < len(tokens) and not tokens[i + 1].startswith('-'):
                i += 1
        elif not _EXTRA_TOKEN_RE.match(t):
            bad.append(t)
        else:
            clean.append(t)
        i += 1
    return ' '.join(clean), bad, managed


def normalize(model):
    """A complete, clean model from whatever was read: every field present,
    every value one the renderer accepts. Lenient on purpose — this is what
    loads a hand-edited JSON — set_fields() is the strict one."""
    m = dict(DEFAULTS)
    m['dsp'] = dict(DEFAULTS['dsp'])
    src = model if isinstance(model, dict) else {}
    out = str(src.get('output') or '').strip()
    m['output'] = out if _OUTPUT_RE.match(out) else 'default'
    name = str(src.get('name') or '').strip()
    m['name'] = name if _NAME_RE.match(name) else DEFAULTS['name']
    server = str(src.get('server') or '').strip()
    m['server'] = server if _HOST_RE.match(server) else DEFAULTS['server']
    mac = str(src.get('mac') or '').strip().lower()
    m['mac'] = mac if _MAC_RE.match(mac) else ''
    model_name = str(src.get('model') or '').strip()
    m['model'] = model_name if _NAME_RE.match(model_name) else DEFAULTS['model']
    dsd = str(src.get('dsd') or '').strip().lower()
    m['dsd'] = dsd if dsd in DSD_MODES else DEFAULTS['dsd']
    try:
        delay = int(src.get('dsd_delay_ms') or 0)
    except (TypeError, ValueError):
        delay = 0
    m['dsd_delay_ms'] = delay if 0 <= delay <= 2000 else 0
    try:
        rate = int(src.get('max_rate') or 0)
    except (TypeError, ValueError):
        rate = 0
    m['max_rate'] = rate if rate in RATES else 0
    m['volume'] = 'hardware' if str(src.get('volume') or '') == 'hardware' else 'software'
    mixer = str(src.get('mixer') or '').strip()
    m['mixer'] = mixer if _MIXER_RE.match(mixer) else ''
    m['alsa_buffer'] = 'large' if str(src.get('alsa_buffer') or '') == 'large' else 'auto'
    m['stream_buffer'] = 'large' if str(src.get('stream_buffer') or '') == 'large' else 'auto'
    m['realtime'] = bool(src.get('realtime'))
    m['extra'] = check_extra(src.get('extra'))[0]
    p2d = str(src.get('pcm2dsd') or '').strip().lower()
    m['pcm2dsd'] = p2d if p2d in PCM2DSD_MODES else 'off'
    flt = str(src.get('pcm2dsd_filter') or '').strip().lower()
    m['pcm2dsd_filter'] = flt if flt in PCM2DSD_FILTERS else DEFAULTS['pcm2dsd_filter']
    dsp = src.get('dsp') if isinstance(src.get('dsp'), dict) else {}
    m['dsp'] = {'enabled': bool(dsp.get('enabled'))}
    return m


class InvalidField(ValueError):
    """A value Settings → Audio sent that the model refuses. `code` is the
    i18n key api_server answers with, `detail` what to put in the message."""

    def __init__(self, code, field, detail=''):
        super().__init__(f'{code}: {field} {detail}'.strip())
        self.code, self.field, self.detail = code, field, detail


def set_fields(model, changes):
    """Strict partial update of the tunable fields. Returns a new model or
    raises InvalidField. Unknown keys are refused too, so a typo in a client
    cannot silently do nothing."""
    m = normalize(model)
    for key, value in (changes or {}).items():
        if key not in TUNABLE:
            raise InvalidField('squeezelite.unknownField', key)
        if key == 'dsd':
            if value not in DSD_MODES:
                raise InvalidField('squeezelite.invalidValue', key, str(value))
        elif key == 'dsd_delay_ms':
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 2000:
                raise InvalidField('squeezelite.invalidValue', key, str(value))
        elif key == 'max_rate':
            if not isinstance(value, int) or isinstance(value, bool) or value not in RATES:
                raise InvalidField('squeezelite.invalidValue', key, str(value))
        elif key == 'volume':
            if value not in ('software', 'hardware'):
                raise InvalidField('squeezelite.invalidValue', key, str(value))
        elif key == 'mixer':
            value = str(value or '').strip()
            if value and not _MIXER_RE.match(value):
                raise InvalidField('squeezelite.invalidValue', key, value)
        elif key in ('alsa_buffer', 'stream_buffer'):
            if value not in ('auto', 'large'):
                raise InvalidField('squeezelite.invalidValue', key, str(value))
        elif key == 'realtime':
            if not isinstance(value, bool):
                raise InvalidField('squeezelite.invalidValue', key, str(value))
        elif key == 'pcm2dsd':
            if value not in PCM2DSD_MODES:
                raise InvalidField('squeezelite.invalidValue', key, str(value))
        elif key == 'pcm2dsd_filter':
            if value not in PCM2DSD_FILTERS:
                raise InvalidField('squeezelite.invalidValue', key, str(value))
        elif key == 'extra':
            clean, bad, managed = check_extra(str(value or ''))
            if managed:
                raise InvalidField('squeezelite.extraManaged', key, ' '.join(managed))
            if bad:
                raise InvalidField('squeezelite.extraInvalid', key, ' '.join(bad))
            value = clean
        m[key] = value
    return m


def reset_tunables(model):
    m = normalize(model)
    for key in TUNABLE:
        m[key] = DEFAULTS[key]
    return m


# ── ARGS line ↔ model ───────────────────────────────────────────────
_VALUE_FLAGS = ('-o', '-n', '-s', '-m', '-M', '-r', '-V', '-a', '-b', '-p', '-C')
_OPTIONAL_FLAGS = ('-D', '-u', '-R')


def _tokenize(args):
    """Flag → value pairs from an ARGS line, in order, with the squeezelite
    rule for optional parameters (the next token unless it starts with '-').
    Returns a list of (flag, value_or_None) plus the leftover tokens."""
    toks = (args or '').split()
    pairs, rest, i = [], [], 0
    while i < len(toks):
        t = toks[i]
        if t in _VALUE_FLAGS and i + 1 < len(toks):
            pairs.append((t, toks[i + 1]))
            i += 2
        elif t in _OPTIONAL_FLAGS:
            if i + 1 < len(toks) and not toks[i + 1].startswith('-'):
                pairs.append((t, toks[i + 1]))
                i += 2
            else:
                pairs.append((t, None))
                i += 1
        elif t == '-v':
            pairs.append((t, None))
            i += 1
        else:
            rest.append(t)
            i += 1
    return pairs, rest


def read_dsp_target(path=DSP_TARGET_FILE):
    try:
        with open(path, encoding='utf-8') as f:
            return f.read().strip() or 'default'
    except OSError:
        return 'default'


def parse_args(args, dsp_target=None):
    """Import an existing ARGS line into a model (the one-time migration of a
    device that predates the JSON). `dsp_target` is the DAC CamillaDSP plays
    to, used when squeezelite is found on the Loopback."""
    pairs, rest = _tokenize(args)
    m = dict(DEFAULTS)
    m['dsp'] = dict(DEFAULTS['dsp'])
    extra = list(rest)
    got = dict((f, v) for f, v in pairs if f in _VALUE_FLAGS)
    output = got.get('-o', 'default')
    if 'Loopback' in output:
        m['dsp']['enabled'] = True
        output = dsp_target or read_dsp_target()
    m['output'] = output
    m['name'] = got.get('-n', DEFAULTS['name'])
    m['server'] = got.get('-s', DEFAULTS['server'])
    m['mac'] = got.get('-m', '')
    m['model'] = got.get('-M', DEFAULTS['model'])
    d = [v for f, v in pairs if f == '-D']
    if not d:
        m['dsd'] = 'off'
    else:
        param = d[-1] or ''
        delay, _, fmt = param.partition(':')
        if delay.isdigit():
            m['dsd_delay_ms'] = int(delay)
        if not fmt or fmt.startswith('dop'):
            m['dsd'] = 'dop' if fmt else 'auto'
        else:
            m['dsd'] = 'native'
    # Values of the managed options that the model has no field for (a rate
    # range, a custom buffer size) are dropped: `extra` refuses those flags,
    # and an import must not leave stray tokens behind.
    if '-r' in got and not m['dsp']['enabled']:
        rate = got['-r'].split(':', 1)[0]
        if rate.isdigit() and int(rate) in RATES:
            m['max_rate'] = int(rate)
    if '-V' in got:
        m['volume'] = 'hardware'
        m['mixer'] = got['-V']
    if got.get('-a') == ALSA_LARGE:
        m['alsa_buffer'] = 'large'
    if got.get('-b') == STREAM_LARGE:
        m['stream_buffer'] = 'large'
    if '-p' in got:
        m['realtime'] = True
    # -R / -u: the DSP path's own resampling is implied by dsp.enabled; a
    # hand-set one on the DAC path is an extra the owner wanted.
    for f, v in pairs:
        if f in ('-R', '-u') and not m['dsp']['enabled']:
            extra.append(f)
            if v is not None:
                extra.append(v)
    m['extra'] = ' '.join(extra)
    return normalize(m)


def dsd_token(model, fmt):
    """The `-D …` token for the model, given what probe() says of the output
    ('dop', PCM_ONLY or a native name). None when DSD is converted to PCM."""
    mode = model['dsd']
    # `native` asks for the DAC's own DSD; an output that is no DAC at all
    # (HDMI, the onboard codec) has none, and falling back to DoP there plays
    # the stream as loud noise. Only an explicit `dop` still goes out as DoP:
    # that is the owner saying a DoP DAC sits behind this output.
    if mode == 'off' or (mode in ('auto', 'native') and fmt == PCM_ONLY):
        return None
    delay = str(model['dsd_delay_ms']) if model['dsd_delay_ms'] else ''
    native = None
    if mode == 'native' or mode == 'auto':
        native = fmt if is_native(fmt) else None
    if native:
        return f'-D {delay}:{native}'
    return f'-D {delay}' if delay else '-D'


def tools_present():
    """sox_ng and the wrapper Lyrion runs: both come with the system image."""
    return os.path.exists(SOX_NG) and os.path.exists(PCM2DSD_WRAPPER)


def server_is_local(server):
    return str(server or '').strip() in ('127.0.0.1', 'localhost', '::1')


def loopback_available(sys_module=None, modules_dir=None):
    """snd-aloop is loaded, or the running kernel has it to load."""
    if os.path.isdir(sys_module or SYS_ALOOP):
        return True
    if modules_dir is None:
        modules_dir = os.path.join(LIB_MODULES, os.uname().release)
    return bool(glob.glob(os.path.join(modules_dir, 'kernel', 'sound', 'drivers', 'snd-aloop.ko*')))


def player_side_present():
    """What converting on the player's side needs besides sox_ng."""
    return os.path.exists(P2D_PLAYER) and loopback_available()


def pcm2dsd_state(model, fmt, zone=False):
    """Why the PCM → DSD choice of `model` does or does not apply, given what
    probe() says of its output: 'off'; 'active' (this device's Lyrion
    converts); 'player' (another server's music, converted by the built-in
    player itself); or the reason it cannot — 'noTools' (an image without
    sox_ng, or without the player side's converter or the Loopback), 'dsp'
    (the DSP path plays PCM into the Loopback), 'noDsd' (no DSD reaches the
    DAC: DSD mode off, or an output that is no DSD DAC), 'remoteServer'
    (another server, and a zone: only the built-in player has the Loopback
    path)."""
    m = normalize(model)
    if m['pcm2dsd'] == 'off':
        return 'off'
    if not tools_present():
        return 'noTools'
    if m['dsp']['enabled']:
        return 'dsp'
    if dsd_token(m, fmt) is None:
        return 'noDsd'
    if server_is_local(m['server']):
        return 'active'
    if zone:
        return 'remoteServer'
    if not player_side_present():
        return 'noTools'
    return 'player'


def render_argv(model, probe_fn=None, visualizer=True, name=None, zone=False):
    """squeezelite's arguments for a model, as a list. `probe_fn(device)`
    tells what the DAC declares for DSD (defaults to reading /proc/asound).
    `visualizer`: `-v`, the VU meters' shared memory -- the built-in player
    only. `name`: a zone's, which may have spaces (it goes through execv,
    not through the ARGS line). `zone`: the model is a zone's."""
    m = normalize(model)
    if name:
        m['name'] = name
    probe_fn = probe_fn or probe
    dsp = m['dsp']['enabled']
    fmt = None if dsp else probe_fn(m['output'])
    state = None if dsp else pcm2dsd_state(m, fmt, zone)
    # PCM → DSD on the player's side: PCM into the Loopback at one rate, like
    # the DSP path. The DAC and its DSD mode are hifi-pcm2dsd-player.py's.
    player = state == 'player'
    pcm_only = dsp or player
    out = []
    if m['mac']:
        out += ['-m', m['mac']]
    out += ['-o', LOOPBACK if dsp else P2D_PLAYBACK if player else m['output']]
    if not pcm_only:
        tok = dsd_token(m, fmt)
        if tok:
            out += tok.split()
    if visualizer:
        out.append('-v')
    out += ['-C', '5', '-s', m['server'], '-n', m['name'], '-M', m['model']]
    if dsp:
        out += ['-r', str(DSP_RATE), '-R']
    elif player:
        out += ['-r', str(P2D_RATE), '-R']
    elif m['max_rate']:
        out += ['-r', str(m['max_rate'])]
    # the Loopback has no volume control of its own: squeezelite's volume
    # acts on the PCM, before the conversion
    if not pcm_only and m['volume'] == 'hardware' and m['mixer']:
        out += ['-V', m['mixer']]
    if m['alsa_buffer'] == 'large':
        out += ['-a', ALSA_LARGE]
    p2d = state == 'active'
    # A DSD stream is 1.4 MB/s at DSD128: squeezelite's default 2 MB stream
    # buffer would hold little more than a second of it.
    if m['stream_buffer'] == 'large' or p2d:
        out += ['-b', STREAM_LARGE]
    if m['realtime']:
        out += ['-p', RT_PRIORITY]
    if p2d:
        # DSD is all the player admits to, so every PCM track has to go
        # through one of the dsf rules written for its MAC (lms_rules()).
        out += ['-c', 'dsd']
    if m['extra']:
        out += m['extra'].split()
    return out


def render(model, probe_fn=None):
    """The ARGS line for the built-in player's model."""
    return ' '.join(render_argv(model, probe_fn))


# ── Files ───────────────────────────────────────────────────────────
HEADER = """\
# Osmium Sound — squeezelite arguments. GENERATED FILE, do not edit.
#
# Rendered by hifi_squeezelite.py from /etc/hifi-player/squeezelite.json at
# every start of squeezelite.service (ExecStartPre), so anything written here
# by hand is gone at the next start. Change the settings from Settings → Audio
# (on screen or in the web admin), or edit the JSON and run
# `systemctl restart squeezelite`. `hifi_squeezelite.py show` prints both.
#
# -v is always on: it exports /dev/shm/squeezelite-* for the VU meters.
# -o uses the stable ALSA card name (hw:CARD=<name>,DEV=<n>), never a number.
"""


def read_args_line(path=DEFAULT):
    """The ARGS value of a defaults file, or None."""
    try:
        with open(path, encoding='utf-8') as f:
            content = f.read()
    except OSError:
        return None
    m = re.search(r"ARGS=(['\"])(.*?)\1", content)
    return m.group(2) if m else None


def load(conf_path=CONF, default_path=DEFAULT, dsp_target_path=DSP_TARGET_FILE):
    """The model, from the JSON — or, on a device that predates it, imported
    from the file's ARGS line. Returns (model, imported)."""
    try:
        with open(conf_path, encoding='utf-8') as f:
            return normalize(json.load(f)), False
    except (OSError, ValueError):
        pass
    args = read_args_line(default_path)
    if args is None:
        return normalize(DEFAULTS), True
    return parse_args(args, read_dsp_target(dsp_target_path)), True


def _write_atomic(path, text):
    """Replace `path` with `text` through a temp file of this writer's own
    (a fixed `<path>.tmp` let two writers rename each other's file, or find
    it already gone: FileNotFoundError)."""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + os.path.basename(path) + '.', suffix='.tmp', dir=d)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)        # mkstemp's 0600 is not what these files always had
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def save(model, conf_path=CONF):
    m = normalize(model)
    _write_atomic(conf_path, json.dumps(m, indent=2, sort_keys=True) + '\n')
    return m


def write_default(args, default_path=DEFAULT):
    """Write the defaults file for `args`. Returns True when it changed."""
    content = HEADER + f"ARGS='{args}'\n"
    try:
        with open(default_path, encoding='utf-8') as f:
            if f.read() == content:
                return False
    except OSError:
        pass
    _write_atomic(default_path, content)
    return True


# ── One writer at a time ────────────────────────────────────────────
class LockTimeout(TimeoutError):
    """Another writer held the model's lock for longer than the timeout."""


def _lock(conf_path, timeout):
    """An fd holding an exclusive flock on `<conf_path>.lock`; closing it
    releases the lock. flock belongs to the open file, so two threads of one
    process exclude each other as two processes do."""
    lock_path = conf_path + '.lock'
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LockTimeout(f'{lock_path}: still held after {timeout:g} s') from None
                time.sleep(0.02)
    except BaseException:
        os.close(fd)
        raise


@contextlib.contextmanager
def locked(conf_path=CONF, timeout=LOCK_TIMEOUT):
    """Hold the model's lock. Not re-entrant: a nested `locked()` of the same
    model waits for itself until the timeout."""
    fd = _lock(conf_path, timeout)
    try:
        yield
    finally:
        os.close(fd)


def update(fn, conf_path=CONF, default_path=DEFAULT, dsp_target_path=DSP_TARGET_FILE,
           probe_fn=None, timeout=LOCK_TIMEOUT):
    """Load → `fn(model)` → save → render, as one step no other writer can
    interleave with. `fn` changes the model in place or returns a new one; an
    exception from it (InvalidField, say) leaves both files as they were.
    Returns (model, changed): changed = the rendered ARGS line is different,
    i.e. a player restart is worth it."""
    with locked(conf_path, timeout):
        model, _ = load(conf_path, default_path, dsp_target_path)
        new = fn(model)
        if new is not None:
            model = new
        model = save(model, conf_path)
        changed = write_default(render(model, probe_fn), default_path)
    return model, changed


def derived_mac(machine_id_path=MACHINE_ID):
    """The player MAC this install keeps for life, '' when there is no
    machine-id to derive it from. Without `-m` squeezelite takes the MAC of
    the first interface that has an address -- and at boot, before DHCP, there
    is none, so the player comes up as 00:00:00:00:00:00: the same player as
    every other Osmium on that Lyrion, and a different one from itself after
    a restart with the network up. Same derivation as migration 0042, which
    only ever reached devices updated through apply.d, never an image install:
    md5 of the machine-id (unique per install, kept across a factory reset),
    first octet forced to 02 (locally administered, unicast) so it can never
    clash with a real burned-in MAC."""
    try:
        with open(machine_id_path, encoding='ascii') as f:
            seed = f.read().strip()
    except (OSError, ValueError):
        return ''
    if not seed:
        return ''
    raw = '02' + hashlib.md5(seed.encode('ascii')).hexdigest()[2:12]
    return ':'.join(raw[i:i + 2] for i in range(0, 12, 2))


def apply(conf_path=CONF, default_path=DEFAULT, dsp_target_path=DSP_TARGET_FILE,
          probe_fn=None, out=None, machine_id_path=MACHINE_ID, lock_timeout=LOCK_TIMEOUT,
          player_conf_path=None):
    """Load (importing the file once if needed), render, write. Returns
    (model, args, changed). Under the model's lock like update(); a lock that
    cannot be had (a stuck writer, a read-only /etc) does not stop it: the
    player must still get its ARGS line."""
    try:
        fd = _lock(conf_path, lock_timeout)
    except OSError as e:
        fd = None
        if out is not None:
            print(f'hifi_squeezelite: going on without the lock: {e}', file=out)
    try:
        return _apply(conf_path, default_path, dsp_target_path, probe_fn, out, machine_id_path,
                      player_conf_path)
    finally:
        if fd is not None:
            os.close(fd)


def _apply(conf_path, default_path, dsp_target_path, probe_fn, out, machine_id_path,
           player_conf_path=None):
    model, imported = load(conf_path, default_path, dsp_target_path)
    new_mac = False
    if not model['mac']:
        # Once set it is never changed again: Lyrion keys the player's
        # settings, queue and history off it.
        mac = derived_mac(machine_id_path)
        if mac:
            model['mac'] = mac
            new_mac = True
            if out is not None:
                print(f'hifi_squeezelite: player MAC set to {mac}', file=out)
    if imported or new_mac:
        try:
            save(model, conf_path)
            if out is not None and imported:
                print(f'hifi_squeezelite: imported {default_path} into {conf_path}', file=out)
        except OSError as e:
            if out is not None:
                print(f'hifi_squeezelite: could not save {conf_path}: {e}', file=out)
    args = render(model, probe_fn)
    changed = write_default(args, default_path)
    if out is not None and changed:
        print(f'hifi_squeezelite: {default_path} rendered: {args}', file=out)
    # squeezelite starts right after this: the Loopback it opens has to be
    # there, or the DAC it opens freed by the player side's conversion
    try:
        sync_player(model, probe_fn, player_conf_path)
    except Exception as e:
        if out is not None:
            print(f'hifi_squeezelite: PCM to DSD on the player side: {e}', file=out)
    return model, args, changed


# ── Zones: one more player per DAC ──────────────────────────────────
# A zone is a full model (same fields, same renderer) plus an id and an on/off
# switch. The id comes from the output, so it stays put across reboots and can
# name a systemd instance; the MAC is derived from the machine-id and the
# output, so Lyrion keeps the zone's queue and settings for life.
ZONE_UNIT = 'hifi-zone@{}.service'
# squeezelite gets the name through execv, not through the ARGS line, so a
# zone may have spaces in it ("Living room"); nothing that could confuse a
# log line or a JSON reader, and the length Lyrion shows comfortably.
_ZONE_NAME_RE = re.compile(r'^[^\x00-\x1f\x7f"\'\\`$]{1,32}$')
_ZONE_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,40}$')
MAX_ZONES = 8


def zone_id(output):
    """'hw:CARD=D50s,DEV=0' → 'D50s-0'; None for an output that is not a card."""
    card, dev = parse_device(output)
    if card is None or card.isdigit():
        return None
    return f'{card}-{dev}'


def zone_mac(output, machine_id_path=MACHINE_ID):
    """Same scheme as derived_mac(), salted with the output so every zone is
    a player of its own and never the built-in one."""
    try:
        with open(machine_id_path, encoding='ascii') as f:
            seed = f.read().strip()
    except (OSError, ValueError):
        seed = ''
    if not seed:
        return ''
    raw = '02' + hashlib.md5(f'{seed}|zone|{output}'.encode('ascii', 'replace')).hexdigest()[2:12]
    return ':'.join(raw[i:i + 2] for i in range(0, 12, 2))


def clean_zone_name(name):
    name = ' '.join(str(name or '').split())
    return name if _ZONE_NAME_RE.match(name) else ''


def normalize_zone(src):
    """A complete zone from whatever was read, or None when it cannot be one
    (no usable output). The server is not the zone's own: see zone_argv()."""
    if not isinstance(src, dict):
        return None
    z = normalize(src)
    zid = zone_id(z['output'])
    if zid is None:
        return None
    z['id'] = zid
    z['name'] = clean_zone_name(src.get('name')) or zid
    z['enabled'] = bool(src.get('enabled', True))
    z['dsp'] = {'enabled': False}
    return z


def load_zones(path=None):
    path = path or ZONES_CONF
    try:
        with open(path, encoding='utf-8') as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return []
    zones, seen = [], set()
    for src in (doc.get('zones') if isinstance(doc, dict) else None) or []:
        z = normalize_zone(src)
        if z and z['id'] not in seen:
            seen.add(z['id'])
            zones.append(z)
    return zones


def save_zones(zones, path=None):
    path = path or ZONES_CONF
    clean = [z for z in (normalize_zone(z) for z in zones) if z]
    _write_atomic(path, json.dumps({'zones': clean}, indent=2, sort_keys=True) + '\n')
    return clean


def update_zones(fn, path=None, timeout=LOCK_TIMEOUT):
    """Load → `fn(zones)` → save, under the zones' own lock. `fn` changes the
    list in place or returns a new one; an exception saves nothing."""
    path = path or ZONES_CONF
    with locked(path, timeout):
        zones = load_zones(path)
        new = fn(zones)
        if new is not None:
            zones = new
        return save_zones(zones, path)


def find_zone(zones, zid):
    for z in zones:
        if z['id'] == zid:
            return z
    return None


def zone_argv(zone, server, probe_fn=None):
    """The full squeezelite command line for a zone. `server` is the built-in
    player's: a zone joins whatever Lyrion this device plays from."""
    z = dict(zone)
    z['server'] = server
    return [SQUEEZELITE_BIN] + render_argv(z, probe_fn, visualizer=False, name=zone.get('name'), zone=True)


def card_present(output, proc_asound=None):
    card, _ = parse_device(output)
    if card is None:
        return False
    root = os.path.realpath(proc_asound or PROC_ASOUND)
    return _card_dir(root, card) is not None


# ── PCM → DSD: Lyrion's side ──────────────────────────────────────────
# Rules are keyed by the player's MAC, never `* *`: any other player on this
# Lyrion (another Osmium, a phone, a Squeezebox) keeps playing as before.
# With the player advertising DSD alone, Lyrion walks these for every track.
# `I`: the stream comes on stdin (internet radio, streaming services), and
# Lyrion puts `-` in $FILE$.
_DECODE_FLAC = ('# IFT:{START=--skip=%t}U:{END=--until=%v}',
                '[flac] -dcs $START$ $END$ -- $FILE$')
_DECODE_FFMPEG = ('# IFT:{START=-ss %s}U:{END=-to %u}',
                  '[ffmpeg] -v error -nostdin $START$ $END$ -i $FILE$ -map 0:a:0 -ac 2 -c:a pcm_s32le -f wav -')
# Every type Lyrion can hand a player, by what decodes it best.
_LMS_TYPES = (('flc', _DECODE_FLAC),) + tuple(
    (t, _DECODE_FFMPEG) for t in ('wav', 'aif', 'alc', 'alcx', 'aac', 'mp4', 'mp4x', 'mp3', 'ogg', 'ogf',
                                  'ops', 'wma', 'wmal', 'wmap', 'wvp', 'wvpx', 'ape', 'mpc'))
# Spotify (the Spotty plugin) hands over raw 16-bit 44.1 kHz stereo; Spotty
# fills in $CACHE$ itself in every spt rule. Without Spotty, [spotty] is not
# found and Lyrion skips the rule.
_SPOTTY = ('# RT:{START=--start-position %s}',
           '[spotty] -n Squeezebox -c "$CACHE$" --single-track $URL$ --bitrate 320 '
           '--disable-discovery --disable-audio-cache $START$')
RULES_BEGIN = '# BEGIN Osmium PCM to DSD -- generated by hifi_squeezelite.py, do not edit'
RULES_END = '# END Osmium PCM to DSD'


def pcm2dsd_players(main, zones, probe_fn=None):
    """{mac: {'mode', 'filter', 'name'}} for every player of this device whose
    PCM → DSD applies right now. Zones only when switched on."""
    probe_fn = probe_fn or probe
    out = {}
    candidates = [(main, False)] + [(dict(z, server=main['server']), True) for z in zones if z.get('enabled')]
    for m, zone in candidates:
        m = normalize(m)
        if not m['mac']:
            continue
        if pcm2dsd_state(m, probe_fn(m['output']), zone) == 'active':
            out[m['mac']] = {'mode': m['pcm2dsd'], 'filter': m['pcm2dsd_filter']}
    return out


def lms_rules(players):
    """The block of custom-convert.conf for `players` (pcm2dsd_players())."""
    if not players:
        return ''
    lines = [RULES_BEGIN]
    for mac in sorted(players):
        for typ, (caps, decode) in _LMS_TYPES:
            lines += [f'{typ} dsf * {mac}', f'\t{caps}', f'\t{decode} | {PCM2DSD_WRAPPER} $CLIENTID$ wav']
        caps, decode = _SPOTTY
        lines += [f'spt dsf * {mac}', f'\t{caps}', f'\t{decode} | {PCM2DSD_WRAPPER} $CLIENTID$ raw']
    lines.append(RULES_END)
    return '\n'.join(lines) + '\n'


def merge_rules(existing, block):
    """`existing` custom-convert.conf with our block replaced by `block`
    (removed when empty). Whatever else the owner put there stays."""
    text = existing or ''
    start = text.find(RULES_BEGIN)
    if start >= 0:
        end = text.find(RULES_END, start)
        end = len(text) if end < 0 else end + len(RULES_END)
        if end < len(text) and text[end] == '\n':
            end += 1
        text = text[:start] + text[end:]
    if block:
        if text and not text.endswith('\n'):
            text += '\n'
        text += block
    return text


def _write_if_changed(path, text, mode=0o644):
    try:
        with open(path, encoding='utf-8') as f:
            if f.read() == text:
                return False
    except OSError:
        if not text:
            return False
    _write_atomic(path, text)
    os.chmod(path, mode)
    return True


def player_conf(model, fmt, proc_asound=None):
    """What hifi-pcm2dsd-player.py needs to convert for the built-in player,
    or None when that path does not apply. The DSD goes to the DAC the way
    squeezelite's own `-D` would send it: native when the DAC declares it and
    the DSD mode allows it, DoP otherwise."""
    m = normalize(model)
    if pcm2dsd_state(m, fmt) != 'player':
        return None
    native = fmt if m['dsd'] in ('auto', 'native') and is_native(fmt) else None
    return {'mode': m['pcm2dsd'], 'filter': m['pcm2dsd_filter'], 'carrier': native or 'dop',
            'dop_bits': dop_bits(m['output'], proc_asound), 'rate': P2D_RATE,
            'capture': P2D_CAPTURE, 'dac': m['output']}


def _modprobe_aloop():
    subprocess.run(['modprobe', 'snd-aloop'], capture_output=True, timeout=30)


def sync_player(model, probe_fn=None, conf_path=None, systemctl=None, modprobe=None):
    """Start or stop hifi-pcm2dsd-player.service for what the built-in
    player's model says now, and give it its settings. Before squeezelite is
    (re)started: the Loopback it is about to open has to exist, and a DAC it
    is about to open directly has to be free. Returns True when the player
    side converts."""
    conf_path = conf_path or P2D_PLAYER_CONF
    systemctl = systemctl or _systemctl
    m = normalize(model)
    want = None if m['dsp']['enabled'] else player_conf(m, (probe_fn or probe)(m['output']))
    if want is None:
        if os.path.exists(conf_path):
            os.remove(conf_path)
            systemctl('stop', P2D_PLAYER_UNIT)
        return False
    if not os.path.isdir(SYS_ALOOP):
        (modprobe or _modprobe_aloop)()
    os.makedirs(os.path.dirname(conf_path), exist_ok=True)
    # the service reads the file again when it changes: a new rate, filter or
    # DAC needs no restart from here
    _write_if_changed(conf_path, json.dumps(want, indent=2, sort_keys=True) + '\n')
    systemctl('start', '--no-block', P2D_PLAYER_UNIT)
    return True


def sync_pcm2dsd(conf_path=CONF, zones_path=None, map_path=None, rules_path=None,
                 default_path=DEFAULT, dsp_target_path=DSP_TARGET_FILE, probe_fn=None,
                 player_conf_path=None):
    """Write the map the wrapper reads and Lyrion's rules for what the models
    say now, and bring the player side's conversion in line (sync_player()).
    Returns True when the rules changed: Lyrion only reads them at start, so
    the caller restarts it. A Lyrion that is not installed (no
    /etc/squeezeboxserver) is left alone."""
    main, _ = load(conf_path, default_path, dsp_target_path)
    try:
        sync_player(main, probe_fn, player_conf_path)
    except Exception as e:
        print(f'hifi_squeezelite: PCM to DSD on the player side: {e}', file=sys.stderr)
    players = pcm2dsd_players(main, load_zones(zones_path), probe_fn)
    map_path = map_path or PCM2DSD_MAP
    if players or os.path.exists(map_path):
        _write_if_changed(map_path, json.dumps(players, indent=2, sort_keys=True) + '\n')
    rules_path = rules_path or LMS_CONVERT
    if not os.path.isdir(os.path.dirname(rules_path)):
        return False
    try:
        with open(rules_path, encoding='utf-8') as f:
            existing = f.read()
    except OSError:
        existing = ''
    return _write_if_changed(rules_path, merge_rules(existing, lms_rules(players)))


def _systemctl(*args):
    return subprocess.run(['systemctl', *args], capture_output=True, text=True, timeout=30)


def running_zone_units():
    """Instance ids of the hifi-zone@ units systemd has loaded and active."""
    try:
        r = _systemctl('list-units', '--plain', '--no-legend', '--state=active', 'hifi-zone@*.service')
    except Exception:
        return set()
    ids = set()
    for line in r.stdout.splitlines():
        m = re.match(r'^hifi-zone@(.+)\.service\s', line.strip() + ' ')
        if m:
            ids.add(m.group(1))
    return ids


def sync_zones(zones_path=None, restart=()):
    """Start the zones that are on, stop the ones that are off or gone.
    `restart`: ids whose settings changed, restarted if already running.
    Starts are queued (--no-block): at boot this runs from hifi-zones.service,
    which Lyrion waits for, and a start that waited in turn would be a loop."""
    zones = load_zones(zones_path)
    want = {z['id'] for z in zones if z['enabled']}
    running = running_zone_units()
    for zid in sorted(running - want):
        _systemctl('stop', ZONE_UNIT.format(zid))
        # squeezelite answers SIGTERM with a non-zero exit: a zone switched
        # off would otherwise sit there as "failed"
        _systemctl('reset-failed', ZONE_UNIT.format(zid))
    for zid in sorted(want):
        unit = ZONE_UNIT.format(zid)
        if zid in running and zid in restart:
            _systemctl('restart', '--no-block', unit)
        elif zid not in running:
            _systemctl('reset-failed', unit)
            _systemctl('start', '--no-block', unit)
    return zones


# ── Players of this device that come and go (zones, Bluetooth) ────
# Lyrion keeps a player in its list after it disconnects, until it is told
# to forget it: a zone whose DAC was unplugged or removed, a Bluetooth
# speaker switched off, stayed there as a dead entry. Every such player
# writes what Lyrion knows it by into PLAYERS_RUN_DIR when it starts; its
# unit's ExecStopPost (`forget-unit %n`) reads that back and tells Lyrion
# to forget it. Lyrion keeps the player's settings, its queue and its sync
# group (unsync keepSyncGroupId), and does nothing if the player has already
# reconnected, so a plain restart costs nothing.
PLAYERS_RUN_DIR = '/run/hifi-players'
LMS_HTTP_PORT = 9000


def _unit_record(unit, run_dir=None):
    return os.path.join(run_dir or PLAYERS_RUN_DIR, re.sub(r'[^A-Za-z0-9@._-]', '_', unit) + '.json')


def record_player(unit, mac, server, run_dir=None):
    """What `forget-unit` will need once `unit` stops."""
    try:
        path = _unit_record(unit, run_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _write_atomic(path, json.dumps({'mac': mac, 'server': server}) + '\n')
    except OSError as e:
        print(f'hifi_squeezelite: cannot record {unit}: {e}', file=sys.stderr)


def _lms_host(server):
    """squeezelite's -s value ('127.0.0.1', 'nas.local:3483', '[::1]:3483')
    → the host Lyrion's web/JSON-RPC port answers on."""
    s = str(server or '').strip() or '127.0.0.1'
    if s.startswith('['):
        return s[:s.index(']') + 1] if ']' in s else s
    if s.count(':') == 1:
        s = s.split(':', 1)[0]
    elif s.count(':') > 1:
        s = f'[{s}]'
    return s


def forget_player(server, mac, timeout=5.0, opener=None):
    """Ask Lyrion to drop a disconnected player from its list. True when it
    answered; never raises (Lyrion may be down, or on another device)."""
    if not mac:
        return False
    url = f'http://{_lms_host(server)}:{LMS_HTTP_PORT}/jsonrpc.js'
    body = json.dumps({'id': 1, 'method': 'slim.request', 'params': [mac, ['client', 'forget']]}).encode()
    try:
        req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
        with (opener or urllib.request.urlopen)(req, timeout=timeout) as resp:
            resp.read()
        return True
    except Exception as e:
        print(f'hifi_squeezelite: Lyrion did not forget {mac}: {e}', file=sys.stderr)
        return False


def forget_unit(unit, run_dir=None, forget=None):
    """ExecStopPost of hifi-zone@ and hifi-bt-player@: the player is gone."""
    path = _unit_record(unit, run_dir)
    try:
        with open(path, encoding='utf-8') as f:
            rec = json.load(f)
    except (OSError, ValueError):
        return False
    try:
        os.remove(path)
    except OSError:
        pass
    ok = (forget or forget_player)(rec.get('server'), rec.get('mac'))
    if ok:
        print(f'hifi_squeezelite: {unit}: Lyrion told to forget {rec.get("mac")}')
    return ok


def run_zone(zid, zones_path=None, conf_path=CONF, poll=3.0, out=None):
    """ExecStart of hifi-zone@<id>: wait for the zone's DAC (a USB DAC that is
    unplugged is not an error worth a restart loop), then run squeezelite —
    and stop it again if the DAC goes away: squeezelite itself would stay
    connected to Lyrion, a player with nothing behind it. Lyrion is told to
    forget it, and the zone waits for its DAC to come back."""
    if not _ZONE_ID_RE.match(zid or ''):
        print(f'hifi_squeezelite: not a zone id: {zid!r}', file=sys.stderr)
        return 64
    zone = find_zone(load_zones(zones_path), zid)
    if zone is None or not zone['enabled']:
        print(f'hifi_squeezelite: zone {zid} is not configured or is off', file=sys.stderr)
        return 64
    unit = ZONE_UNIT.format(zid)
    state = {'proc': None}

    def say(msg):
        if out is not None:
            print(f'hifi_squeezelite: zone {zid}: {msg}', file=out)
            out.flush()

    def stop_child():
        p = state['proc']
        if p is None or p.poll() is not None:
            return
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()

    def on_term(signum, frame):
        stop_child()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    while True:
        waited = False
        while not card_present(zone['output']):
            if not waited:
                say(f'waiting for {zone["output"]}')
            waited = True
            time.sleep(poll)
        main, _ = load(conf_path)
        argv = zone_argv(zone, main['server'])
        say(' '.join(argv))
        record_player(unit, zone['mac'], main['server'])
        state['proc'] = subprocess.Popen(argv)
        while True:
            try:
                return state['proc'].wait(timeout=poll)      # it ended by itself: systemd restarts it
            except subprocess.TimeoutExpired:
                pass
            if not card_present(zone['output']):
                say(f'{zone["output"]} is gone: player stopped')
                stop_child()
                state['proc'] = None
                forget_unit(unit)
                break


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ''
    if cmd == 'apply' and len(argv) == 2:
        apply(out=sys.stdout)
        return 0
    if cmd == 'show' and len(argv) == 2:
        model, imported = load()
        print(json.dumps(model, indent=2, sort_keys=True))
        print(f"ARGS='{render(model)}'" + ('  (model not saved yet: imported from the file)' if imported else ''))
        for z in load_zones():
            print(f"zone {z['id']} ({'on' if z['enabled'] else 'off'}): "
                  + ' '.join(zone_argv(z, model['server'])))
        return 0
    if cmd == 'probe' and len(argv) == 3:
        print(probe(argv[2]))
        return 0
    if cmd == 'run-zone' and len(argv) == 3:
        return run_zone(argv[2], out=sys.stdout)
    if cmd == 'forget-unit' and len(argv) == 3:
        forget_unit(argv[2])
        return 0
    if cmd == 'lms-rules' and len(argv) == 2:
        # Lyrion's rules only: what hifi-lyrion-update.sh needs before it
        # starts a freshly installed Lyrion.
        changed = sync_pcm2dsd()
        print(f'hifi_squeezelite: Lyrion PCM to DSD rules {"written" if changed else "unchanged"}')
        return 0
    if cmd == 'zones-sync' and len(argv) == 2:
        # At boot, before Lyrion: its rules, then the zones that are on.
        sync_pcm2dsd()
        sync_zones()
        return 0
    print('usage: hifi_squeezelite.py apply | show | probe <hw:CARD=…,DEV=n> | run-zone <id> '
          '| forget-unit <unit> | lms-rules | zones-sync', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
