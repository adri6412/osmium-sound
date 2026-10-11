#!/usr/bin/env python3
"""Osmium Sound — PCM to DSD, the last step of Lyrion's transcoding pipe.

Lyrion runs this for every track sent to a player whose Settings → Audio has
"Convert to DSD" on (the rules hifi_squeezelite.py writes into
custom-convert.conf, keyed by the player's MAC):

    <decoder> … | hifi-pcm2dsd.py $CLIENTID$ wav|raw

It reads PCM on stdin — a WAV stream from flac/ffmpeg, or Spotty's raw 16-bit
44.1 kHz stereo — and becomes sox_ng writing a DSF stream on stdout:

    gain -6 → rate (to the DSD rate) → sdm (the 1-bit sigma-delta modulator)

-6 dB is DSD's reference level (a full-scale PCM sine is 50 % modulation):
at 0 dB the modulator overloads on loud masters and turns them into noise.
The player's rate and filter are looked up in /etc/hifi-player/pcm2dsd.json
by MAC at every track, so changing them needs no Lyrion restart.

Runs as Lyrion's user; it only reads that map and execs sox_ng.

`hifi-pcm2dsd.py --bench` times the conversion of a few seconds of audio at
each DSD rate on this CPU and prints the share of real time each one needs
(0.5 = half of the track's duration). api_server runs it once to know which
rates this machine can sustain.
"""
import json
import os
import subprocess
import sys
import time

SOX_NG = '/usr/local/bin/sox_ng'
MAP = '/etc/hifi-player/pcm2dsd.json'
RATES = {'dsd64': 2822400, 'dsd128': 5644800, 'dsd256': 11289600}
FILTERS = ('clans-8', 'sdm-8')
DEFAULT = {'mode': 'dsd64', 'filter': 'clans-8'}
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
    mode = entry.get('mode') if entry.get('mode') in RATES else DEFAULT['mode']
    flt = entry.get('filter') if entry.get('filter') in FILTERS else DEFAULT['filter']
    return mode, flt


def sox_argv(kind, mode, flt, sox=SOX_NG):
    if kind == 'raw':
        source = ['-t', 'raw', '-r', '44100', '-e', 'signed', '-b', '16', '-c', '2', '-']
    else:
        # flac and ffmpeg write the WAV header before they know the length
        source = ['--ignore-length', '-t', 'wav', '-']
    return [sox, '-q', '--multi-threaded', *source, '-t', 'dsf', '-',
            'channels', '2', 'gain', '-6', 'rate', '-v', str(RATES[mode]), 'sdm', '-f', flt]


def bench(sox=SOX_NG, seconds=BENCH_SECONDS):
    """{mode: share of real time} for a synthetic 44.1 kHz stereo track."""
    gen = [sox, '-q', '-n', '-r', '44100', '-b', '16', '-c', '2', '-t', 'wav', '-',
           'synth', str(seconds), 'pinknoise', 'gain', '-10']
    result = {}
    for mode in ('dsd64', 'dsd128', 'dsd256'):
        argv = sox_argv('wav', mode, DEFAULT['filter'], sox)
        argv[argv.index('dsf') + 1] = '/dev/null'      # the output, '-' in a real run
        t0 = time.monotonic()
        src = subprocess.Popen(gen, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        subprocess.run(argv, stdin=src.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=False, timeout=seconds * 10)
        src.wait(timeout=5)
        result[mode] = round((time.monotonic() - t0) / seconds, 3)
        if result[mode] > 1.5:
            break                       # the next rate costs twice as much: no point timing it
    return result


def main(argv):
    if len(argv) == 2 and argv[1] == '--bench':
        print(json.dumps(bench()))
        return 0
    if len(argv) != 3 or argv[2] not in ('wav', 'raw'):
        print('usage: hifi-pcm2dsd.py <clientid> wav|raw | --bench', file=sys.stderr)
        return 2
    mode, flt = settings_for(argv[1])
    args = sox_argv(argv[2], mode, flt)
    os.execv(args[0], args)
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
