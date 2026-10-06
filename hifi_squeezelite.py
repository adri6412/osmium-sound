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
  dsp.enabled    squeezelite plays into the CamillaDSP Loopback at 48 kHz

Writers: api_server.py (several request threads) and the ExecStartPre
`apply` (every 5 s while squeezelite crash-loops) all load, change and save
the same two files. They go through update() / apply(), which hold an
flock on `<json>.lock` for the whole load → save → render, and every file
is replaced from a temp file of its own, so no writer loses another's
change or renames someone else's half-written file.
"""
import contextlib
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
DSP_RATE = 48000
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
    'dsp': {'enabled': False},
}
# What Settings → Audio may change and "Back to defaults" resets.
TUNABLE = ('dsd', 'dsd_delay_ms', 'max_rate', 'volume', 'mixer',
           'alsa_buffer', 'stream_buffer', 'realtime', 'extra')

DSD_MODES = ('auto', 'dop', 'native', 'off')
RATES = (0, 44100, 48000, 88200, 96000, 176400, 192000, 352800, 384000, 705600, 768000)
DSD_DELAYS = (0, 100, 250, 500)
ALSA_LARGE = '200:8'
STREAM_LARGE = '16384:8192'
RT_PRIORITY = '45'
# Options the model renders itself: refused in `extra` so they cannot appear twice.
MANAGED_FLAGS = ('-o', '-n', '-s', '-m', '-M', '-D', '-r', '-V', '-a', '-b', '-p', '-v', '-C')

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


def native_format_from_stream(text):
    """The squeezelite format for the first native DSD format the *playback*
    side of a /proc/asound stream file lists, or None (PCM only / DoP)."""
    if not text:
        return None
    playback, section = [], None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith('Playback:'):
            section = 'playback'
            continue
        if s.startswith('Capture:'):
            section = 'capture'
            continue
        if section == 'playback' and s.startswith('Format:'):
            playback.extend(s[len('Format:'):].split())
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


def render(model, probe_fn=None):
    """The ARGS line for a model. `probe_fn(device)` tells what the DAC
    declares for DSD (defaults to reading /proc/asound)."""
    m = normalize(model)
    probe_fn = probe_fn or probe
    dsp = m['dsp']['enabled']
    out = []
    if m['mac']:
        out += ['-m', m['mac']]
    out += ['-o', LOOPBACK if dsp else m['output']]
    if not dsp:
        tok = dsd_token(m, probe_fn(m['output']))
        if tok:
            out.append(tok)
    out += ['-v', '-C', '5', '-s', m['server'], '-n', m['name'], '-M', m['model']]
    if dsp:
        out += ['-r', str(DSP_RATE), '-R']
    elif m['max_rate']:
        out += ['-r', str(m['max_rate'])]
    if not dsp and m['volume'] == 'hardware' and m['mixer']:
        out += ['-V', m['mixer']]
    if m['alsa_buffer'] == 'large':
        out += ['-a', ALSA_LARGE]
    if m['stream_buffer'] == 'large':
        out += ['-b', STREAM_LARGE]
    if m['realtime']:
        out += ['-p', RT_PRIORITY]
    if m['extra']:
        out.append(m['extra'])
    return ' '.join(out)


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
          probe_fn=None, out=None, machine_id_path=MACHINE_ID, lock_timeout=LOCK_TIMEOUT):
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
        return _apply(conf_path, default_path, dsp_target_path, probe_fn, out, machine_id_path)
    finally:
        if fd is not None:
            os.close(fd)


def _apply(conf_path, default_path, dsp_target_path, probe_fn, out, machine_id_path):
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
    return model, args, changed


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ''
    if cmd == 'apply' and len(argv) == 2:
        apply(out=sys.stdout)
        return 0
    if cmd == 'show' and len(argv) == 2:
        model, imported = load()
        print(json.dumps(model, indent=2, sort_keys=True))
        print(f"ARGS='{render(model)}'" + ('  (model not saved yet: imported from the file)' if imported else ''))
        return 0
    if cmd == 'probe' and len(argv) == 3:
        print(probe(argv[2]))
        return 0
    print('usage: hifi_squeezelite.py apply | show | probe <hw:CARD=…,DEV=n>', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
