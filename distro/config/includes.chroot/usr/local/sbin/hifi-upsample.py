#!/usr/bin/env python3
"""Osmium Sound — PCM upsampling, the last step of Lyrion's transcoding pipe.

Lyrion runs this for every track sent to a player whose Settings → Audio has
"PCM upsampling" on (the rules hifi_squeezelite.py writes into
custom-convert.conf, keyed by the player's MAC):

    <decoder> … | hifi-upsample.py $CLIENTID$ wav|raw

It reads PCM on stdin — a WAV stream from flac/ffmpeg, or Spotty's raw 16-bit
44.1 kHz stereo — resamples it with sox_ng and writes a FLAC stream on stdout:

    channels 2 → rate -v (to the target rate) → FLAC

The output is FLAC, so it is lossless and self-describing: the player reads the
new rate from the stream itself, no capability token needed. FLAC also
compresses, which keeps a high-rate stream lighter on the LAN than raw PCM.
The project's sox_ng is built with the `sdm` DSD effect but WITHOUT a FLAC
handler, so sox_ng resamples to WAV and the standalone `flac` CLI encodes it
(a SoX that does carry FLAC would encode in one process).

The target rate stays inside the source's rate family — 44.1 kHz
(44.1/88.2/176.4/352.8/705.6) or 48 kHz (48/96/192/384/768) — never mixing the
two, because crossing families means an actual resample ratio, not a clean
integer upsample. "x2"/"x4" are that multiple of the source; "max" is the top
family multiple that fits the player's declared ceiling (`cap`, 0 = none).

The player's multiple and cap are looked up in /etc/hifi-player/upsample.json by
MAC at every track, so changing them needs no Lyrion restart. Unlike DSD, the
source rate matters here, so the WAV header is read to learn it before sox runs;
Spotty's raw input is always 44.1 kHz.

Runs as Lyrion's user; it only reads that map and runs sox_ng and flac.

`hifi-upsample.py --bench` times the conversion of a few seconds of audio at a
few target rates on this CPU and prints the share of real time each one needs
(0.5 = half of the track's duration). PCM upsampling is far lighter than DSD.
"""
import json
import os
import shutil
import subprocess
import sys
import time

SOX_NG = '/usr/local/bin/sox_ng'
FLAC_BIN = '/usr/bin/flac'
MAP = '/etc/hifi-player/upsample.json'
MULTS = {'x2': 2, 'x4': 4}
FAMILY_BASE = (44100, 48000)
CEILING = 768000
RAW_RATE = 44100
DEFAULT = {'mult': 'x2', 'cap': 0}
BENCH_SECONDS = 3


def mac_from_clientid(clientid):
    """Lyrion's $CLIENTID$ is the MAC with ':' turned into '-'."""
    return str(clientid or '').strip().replace('-', ':').lower()


def settings_for(clientid, path=MAP):
    try:
        with open(path, encoding='utf-8') as f:
            players = json.load(f)
    except (OSError, ValueError):
        players = {}
    entry = players.get(mac_from_clientid(clientid)) if isinstance(players, dict) else None
    entry = entry if isinstance(entry, dict) else {}
    mult = entry.get('mult') if entry.get('mult') in MULTS or entry.get('mult') == 'max' else DEFAULT['mult']
    cap = entry.get('cap')
    cap = cap if isinstance(cap, int) and cap > 0 else 0
    return mult, cap


def family_base(src_rate):
    """The base of `src_rate`'s PCM family (44100 or 48000); 48000 for anything
    that fits neither cleanly."""
    r = int(src_rate or 0)
    for base in FAMILY_BASE:
        if r and r % base == 0:
            return base
    return 48000


def target_rate(mult, cap, src_rate):
    """The output rate to aim for, inside `src_rate`'s family. 0 means leave the
    stream as it is (nothing larger fits, or the source rate is unknown)."""
    src = int(src_rate or 0)
    if src <= 0:
        return 0
    ceiling = cap if cap and cap > 0 else CEILING
    if mult in MULTS:
        target = src * MULTS[mult]
        return target if src < target <= ceiling else 0
    base, best = family_base(src), 0
    rate = base
    while rate <= ceiling:
        if rate > src:
            best = rate
        rate *= 2
    return best


def read_wav_rate(stream):
    """(sample rate, bytes already read off `stream`) for a WAV stream, or
    (None, bytes) when it is not WAV. Only the header up to the `fmt ` chunk is
    consumed; those bytes are returned so the caller can forward them to sox."""
    buf = bytearray()

    def need(n):
        while len(buf) < n:
            chunk = stream.read(n - len(buf))
            if not chunk:
                return False
            buf.extend(chunk)
        return True

    if not need(12) or buf[0:4] != b'RIFF' or buf[8:12] != b'WAVE':
        return None, bytes(buf)
    pos = 12
    while need(pos + 8):
        cid = bytes(buf[pos:pos + 8][:4])
        size = int.from_bytes(buf[pos + 4:pos + 8], 'little')
        if cid == b'fmt ':
            if not need(pos + 8 + size):
                return None, bytes(buf)
            fmt = buf[pos + 8:pos + 8 + size]
            return int.from_bytes(fmt[4:8], 'little'), bytes(buf)
        pos += 8 + size + (size & 1)        # chunks are word-aligned
    return None, bytes(buf)


def sox_has_flac(sox):
    """True when this SoX has the FLAC handler compiled in. The project's sox_ng
    fork carries the `sdm` effect for DSD but is built without FLAC."""
    if not sox:
        return False
    try:
        r = subprocess.run([sox, '--help'], stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    for line in r.stdout.decode('utf-8', 'replace').splitlines():
        if 'AUDIO FILE FORMATS' in line:
            return 'flac' in line.split()
    return False


def find_flac():
    """The standalone FLAC encoder, used because sox_ng has no FLAC handler."""
    return FLAC_BIN if os.access(FLAC_BIN, os.X_OK) else shutil.which('flac')


def sox_argv(kind, target, sox=SOX_NG, out_type='flac'):
    """sox_ng reading PCM (`kind` wav|raw) on stdin, writing `out_type` on
    stdout. `target` 0 means re-encode without changing the rate."""
    if kind == 'raw':
        source = ['-t', 'raw', '-r', str(RAW_RATE), '-e', 'signed', '-b', '16', '-c', '2', '-']
    else:
        # flac and ffmpeg write the WAV header before they know the length
        source = ['--ignore-length', '-t', 'wav', '-']
    argv = [sox, '-q', '--multi-threaded', *source, '-t', out_type, '-', 'channels', '2']
    if target:
        argv += ['rate', '-v', str(target)]
    return argv


def run(kind, mult, cap, stdin=None, sox=SOX_NG):
    """Learn the source rate, then stream stdin through the upsampler. The output
    is FLAC; sox_ng has no FLAC handler, so it resamples to WAV and the `flac`
    CLI encodes. Returns the pipeline's exit code. Kept separate from main() so
    it is easy to test."""
    stdin = stdin if stdin is not None else sys.stdin.buffer
    sox_flac = sox_has_flac(sox)
    flac = None if sox_flac else find_flac()
    if not sox_flac and not flac:
        print('hifi-upsample: no FLAC encoder (need a SoX with FLAC or the '
              '`flac` CLI)', file=sys.stderr)
        return 3
    if kind == 'raw':
        src, head = RAW_RATE, b''
    else:
        src, head = read_wav_rate(stdin)
    target = target_rate(mult, cap, src)
    out_type = 'flac' if sox_flac else 'wav'
    encoder = None
    if sox_flac:
        proc = subprocess.Popen(sox_argv(kind, target, sox, out_type), stdin=subprocess.PIPE)
    else:
        encoder = subprocess.Popen([flac, '--silent', '--stdout', '-'], stdin=subprocess.PIPE)
        proc = subprocess.Popen(sox_argv(kind, target, sox, out_type),
                                stdin=subprocess.PIPE, stdout=encoder.stdin)
        encoder.stdin.close()   # only sox writes to the encoder
    try:
        if head:
            proc.stdin.write(head)
        shutil.copyfileobj(stdin, proc.stdin, length=1 << 16)
    except BrokenPipeError:
        pass
    finally:
        try:
            proc.stdin.close()
        except BrokenPipeError:
            pass
    rc = proc.wait()
    if encoder is not None:
        rc = rc or encoder.wait()
    return rc


def bench(sox=SOX_NG, seconds=BENCH_SECONDS, tries=2):
    """{label: share of real time} upsampling a 44.1 kHz stereo track to a few
    targets. Like the DSD bench, the track is rendered first so only the
    conversion is timed, and each target is timed `tries` times keeping the
    best."""
    import tempfile
    targets = {'x2': 88200, 'x4': 176400, 'max': 705600}
    result = {}
    with tempfile.TemporaryDirectory(prefix='upsample-bench-') as tmp:
        wav = os.path.join(tmp, 'in.wav')
        subprocess.run([sox, '-q', '-n', '-r', '44100', '-b', '16', '-c', '2', wav,
                        'synth', str(seconds), 'pinknoise', 'gain', '-10'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=60)
        for label, target in targets.items():
            # Time the resample alone (FLAC encoding is light); out to a WAV
            # file. The two bare '-' tokens are the input and output streams.
            argv = sox_argv('wav', target, sox, out_type='wav')
            i_in = argv.index('-')
            argv[i_in] = wav                                   # the input, stdin in a real run
            argv[argv.index('-', i_in + 1)] = '/dev/null'      # the output, stdout in a real run
            best = None
            for _ in range(tries):
                t0 = time.monotonic()
                subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               check=False, timeout=seconds * 10)
                took = (time.monotonic() - t0) / seconds
                best = took if best is None else min(best, took)
            result[label] = round(best, 3)
    return result


def main(argv):
    if len(argv) == 2 and argv[1] == '--bench':
        print(json.dumps(bench()))
        return 0
    if len(argv) != 3 or argv[2] not in ('wav', 'raw'):
        print('usage: hifi-upsample.py <clientid> wav|raw | --bench', file=sys.stderr)
        return 2
    mult, cap = settings_for(argv[1])
    return run(argv[2], mult, cap)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
