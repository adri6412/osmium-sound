#!/usr/bin/env python3
"""The signal path: what happens to a track between the file and the DAC.

Now Playing opens it from the format chip and the format lights: source →
Lyrion → player → DAC, each step marked untouched or changed, and a verdict
at the bottom (bit-perfect, converted on purpose, processed). The kiosk knows
the source and Lyrion's per-player settings; this module adds what only this
device can see:

  * which player of this device is being driven (the built-in one or a zone)
    and how it is set up (DSD mode, volume, rate limit, PCM → DSD);
  * what the DAC is *actually* being fed right now, from the kernel:
    /proc/asound/<card>/pcm<dev>p/sub0/hw_params ("closed" when idle). That
    is the proof — a DAC's own display says "DSD" for DoP too, and a file's
    tags say nothing about a resampler on the way.

describe() takes what the kiosk knows and returns facts and codes, never
sentences: the screen words them in the reader's language.
"""
import os
import re

import hifi_squeezelite as sq

PROC_ASOUND = '/proc/asound'

# How to read a track's `type` as Lyrion names it. Lossy throws data away for
# good (worth saying next to a "bit-perfect" that would otherwise read as
# "hi-fi"); lossless keeps every sample. A `type` in neither list -- empty, or
# one of the odd tokens some internet radios report -- stays unknown, and the
# screen then says nothing about the quality rather than claim one it cannot
# vouch for. 🚨 Do NOT guess lossless from the absence of a lossy tag: an AAC
# radio stream whose type is not plainly "aac" would read as "lossless".
LOSSY_TYPES = ('mp3', 'aac', 'mp4', 'm4a', 'ogg', 'ops', 'opus', 'wma', 'wmap', 'mpc', 'spt')
LOSSLESS_TYPES = ('flc', 'ogf', 'wav', 'aif', 'aiff', 'pcm', 'l16', 'alc', 'alcx',
                  'wvp', 'wvpx', 'ape', 'wmal', 'mlp', 'shn', 'tak')
DSD_TYPES = ('dsf', 'dff', 'dsd')


def source_quality(stype, is_dsd):
    """'lossless' / 'lossy' / '' for a codec `type`; DSD counts as lossless."""
    if is_dsd or stype in LOSSLESS_TYPES:
        return 'lossless'
    if stype in LOSSY_TYPES:
        return 'lossy'
    return ''

# hw_params `format` → how many DSD bits one frame carries per channel.
_DSD_BITS = {'DSD_U8': 8, 'DSD_U16_LE': 16, 'DSD_U16_BE': 16, 'DSD_U32_LE': 32, 'DSD_U32_BE': 32}
_PCM_BITS_RE = re.compile(r'^[SU](\d+)(?:_\d+)?(?:_[LB]E)?$')
# DoP carries 16 DSD bits per channel in every 24-bit PCM frame, at these rates.
_DOP_RATES = (176400, 352800, 705600, 192000, 384000, 768000)


def parse_hw_params(text):
    """{'format', 'rate', 'channels'} from a hw_params file, None when the
    stream is closed (nothing playing, or squeezelite let the DAC go)."""
    if not text or text.strip() == 'closed':
        return None
    out = {}
    for line in text.splitlines():
        key, _, value = line.partition(':')
        key, value = key.strip(), value.strip()
        if key == 'format':
            out['format'] = value
        elif key == 'rate':
            try:
                out['rate'] = int(value.split()[0])
            except (ValueError, IndexError):
                pass
        elif key == 'channels':
            try:
                out['channels'] = int(value)
            except ValueError:
                pass
    return out if out.get('format') and out.get('rate') else None


def dsd_name(bit_rate):
    """2822400 → 'DSD64', 6144000 → 'DSD128' (the 48 kHz family too)."""
    for base in (44100, 48000):
        n = bit_rate / base
        if n >= 32 and abs(n - round(n)) < 0.01 and int(round(n)) & (int(round(n)) - 1) == 0:
            return f'DSD{int(round(n))}'
    return 'DSD'


def pcm_bits(fmt):
    """'S32_LE' → 32, 'S24_3LE' → 24; 0 for anything else."""
    m = _PCM_BITS_RE.match(fmt.replace('_3LE', '_LE').replace('_3BE', '_BE'))
    return int(m.group(1)) if m else 0


def read_hw(device, proc_asound=None):
    """What `device` is fed right now: hw_params of its first playback
    substream, or None (idle, or an output we cannot map to a card)."""
    card, dev = sq.parse_device(device)
    if card is None:
        return None
    root = os.path.realpath(proc_asound or PROC_ASOUND)
    card_dir = sq._card_dir(root, card)
    if card_dir is None:
        return None
    try:
        with open(os.path.join(card_dir, f'pcm{dev}p', 'sub0', 'hw_params'),
                  encoding='utf-8', errors='replace') as f:
            return parse_hw_params(f.read())
    except OSError:
        return None


def card_info(device, proc_asound=None):
    """{'card', 'name', 'kind'} for the output: the long name the DAC gives
    itself ('Topping D50s'), and usb | hdmi | internal | unknown."""
    card, dev = sq.parse_device(device)
    info = {'card': card or '', 'name': '', 'kind': 'unknown'}
    if card is None:
        return info
    root = os.path.realpath(proc_asound or PROC_ASOUND)
    card_dir = sq._card_dir(root, card)
    if card_dir is None:
        return info
    num = os.path.basename(card_dir)[len('card'):]
    try:
        with open(os.path.join(root, 'cards'), encoding='utf-8', errors='replace') as f:
            lines = f.read().splitlines()
        for i, line in enumerate(lines):
            if line.strip().split(' ', 1)[0] == num and i + 1 < len(lines):
                info['name'] = lines[i + 1].strip().split(' at ', 1)[0].strip()
                break
    except OSError:
        pass
    pcm_name = ''
    try:
        with open(os.path.join(card_dir, f'pcm{dev}p', 'info'), encoding='utf-8', errors='replace') as f:
            for line in f:
                if line.startswith(('id:', 'name:')):
                    pcm_name += line.split(':', 1)[1].strip() + ' '
    except OSError:
        pass
    if sq.is_usb_card(card_dir):
        info['kind'] = 'usb'
    elif re.search(r'HDMI|DisplayPort|\bDP\b', pcm_name):
        info['kind'] = 'hdmi'
    else:
        info['kind'] = 'internal'
    return info


def describe_hw(hw, dsd_carrier):
    """The stream the DAC gets, in words the screen can use. `dsd_carrier`
    is how this player sends DSD ('native', 'dop' or None): DoP is PCM to
    the kernel, so it can only be told apart by what the player was set to
    do and by its rate."""
    if hw is None:
        return None
    fmt, rate = hw['format'], hw['rate']
    if fmt in _DSD_BITS:
        bit_rate = rate * _DSD_BITS[fmt]
        return {'kind': 'dsd', 'carrier': 'native', 'dsd': dsd_name(bit_rate),
                'bit_rate': bit_rate, 'format': fmt, 'rate': rate}
    out = {'kind': 'pcm', 'bits': pcm_bits(fmt), 'rate': rate, 'format': fmt}
    if dsd_carrier == 'dop' and rate in _DOP_RATES:
        out['maybe_dop'] = dsd_name(rate * 16)
    return out


def find_player(player, main, zones):
    """(model, zone name or None) of this device's player with that MAC —
    None when it is someone else's."""
    player = (player or '').strip().lower()
    if not player:
        return None, None
    if main.get('mac') and main['mac'].lower() == player:
        return main, None
    for z in zones:
        if (z.get('mac') or '').lower() == player:
            return sq.normalize(dict(z, server=main['server'])), z.get('name') or z.get('id')
    return None, None


def _as_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def describe(source, lyrion, player, main, zones, probe_fn=None, hw_fn=None, card_fn=None):
    """The whole path. `source`: {'type', 'rate', 'bits', 'remote'} of the
    track (Lyrion's status). `lyrion`: {'replaygain', 'digital_volume',
    'crossfade', 'volume'} of the player being driven (its playerprefs).
    `player`: its MAC. Returns a dict for the screen; see the keys below."""
    probe_fn = probe_fn or sq.probe
    hw_fn = hw_fn or read_hw
    card_fn = card_fn or card_info
    stype = str(source.get('type') or '').lower()
    src_dsd = stype in DSD_TYPES
    src_rate = _as_int(source.get('rate'))
    changes = []

    # ── Lyrion: what it does to the samples before they leave ───────
    if lyrion.get('replaygain'):
        changes.append('replaygain')
    if lyrion.get('crossfade'):
        changes.append('crossfade')

    model, zone = find_player(player, main, zones)
    out = {
        'source': {'type': stype, 'rate': src_rate, 'bits': _as_int(source.get('bits')),
                   'dsd': src_dsd, 'quality': source_quality(stype, src_dsd), 'remote': bool(source.get('remote'))},
        'local': model is not None,
        'zone': zone,
        'lyrion': {'local': sq.server_is_local(main.get('server')), 'server': main.get('server') or ''},
    }

    if model is None:
        # Another device's player: its volume and its DAC are out of sight.
        if lyrion.get('digital_volume') and _as_int(lyrion.get('volume')) < 100:
            changes.append('volume')
        out['changes'] = changes
        out['verdict'] = 'processed' if changes else 'unknown'
        return out

    # ── this device's player ───────────────────────────────────────
    dsp = model['dsp']['enabled']
    fmt = None if dsp else probe_fn(model['output'])
    tok = None if dsp else sq.dsd_token(model, fmt)
    carrier = None if tok is None else ('native' if sq.is_native(fmt) and model['dsd'] in ('auto', 'native') else 'dop')
    p2d = None if dsp else sq.pcm2dsd_state(model, fmt, zone=bool(zone))
    # converted on the player's side (music from another Lyrion): squeezelite
    # plays PCM into the Loopback, its own volume included, and every track
    # -- a DSD one decoded to PCM first -- is turned into DSD after it
    player_side = p2d == 'player'
    hw = describe_hw(None if dsp else hw_fn(model['output']), carrier)
    hardware_volume = not player_side and model['volume'] == 'hardware' and bool(model['mixer'])
    out['player'] = {
        'name': model['name'], 'volume': 'hardware' if hardware_volume else 'software',
        'realtime': model['realtime'], 'max_rate': model['max_rate'],
        'dsd': carrier or 'pcm',
        'pcm2dsd': {'state': p2d or 'off', 'mode': model['pcm2dsd'], 'filter': model['pcm2dsd_filter']},
    }
    out['dac'] = card_fn(model['output'])
    out['hw'] = hw

    converted = False
    if player_side:
        converted = True
        if src_dsd:
            changes.append('dsdToPcm')
        changes.append('pcmToDsd')
    elif not src_dsd and p2d == 'active':
        converted = True
        changes.append('pcmToDsd')
    # software volume below 100 % is arithmetic on every PCM sample; a DSD
    # stream (native or DoP) goes past squeezelite's volume untouched
    dsd_out = hw['kind'] == 'dsd' or bool(hw.get('maybe_dop') and (src_dsd or converted)) if hw else \
        (src_dsd and carrier is not None) or converted
    out['player']['dsd_out'] = dsd_out
    if (not hardware_volume and (player_side or not dsd_out) and lyrion.get('digital_volume')
            and _as_int(lyrion.get('volume')) < 100):
        changes.append('volume')
    if hw is not None:
        if src_dsd and hw['kind'] == 'pcm' and not hw.get('maybe_dop'):
            changes.append('dsdToPcm')
        elif not src_dsd and hw['kind'] == 'pcm' and src_rate and hw['rate'] != src_rate:
            changes.append('resampled')
        if hw['kind'] == 'pcm' and hw.get('maybe_dop') and (src_dsd or converted):
            hw['kind'] = 'dop'
            hw['dsd'] = hw.pop('maybe_dop')
        hw.pop('maybe_dop', None)
    elif src_dsd and carrier is None:
        changes.append('dsdToPcm')            # configured to convert, idle right now
    elif not src_dsd and model['max_rate'] and src_rate > model['max_rate'] and not converted:
        changes.append('resampled')

    out['changes'] = changes
    if hw is None and not changes:
        out['verdict'] = 'idle'
    elif [c for c in changes if c != 'pcmToDsd']:
        out['verdict'] = 'processed'
    elif converted:
        out['verdict'] = 'converted'
    else:
        out['verdict'] = 'bitperfect'
    return out
