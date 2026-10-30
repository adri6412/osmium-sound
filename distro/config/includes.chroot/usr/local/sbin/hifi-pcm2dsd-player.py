#!/usr/bin/env python3
"""Osmium Sound — PCM to DSD on the player's side.

When this device is its own Lyrion server, Lyrion converts every PCM track
on its way to the player (hifi-pcm2dsd.py, run from the rules
hifi_squeezelite.py writes into custom-convert.conf). The rules of another
Lyrion server are out of reach, so when the music comes from one the
conversion happens here instead, on the same path the DSP takes:

    squeezelite ─PCM─▶ Loopback ─▶ this ─▶ sox_ng ─DSD─▶ the DAC

squeezelite plays into the Loopback at one fixed rate (it resamples every
track to it, -r … -R); this reads the other end with arecord and feeds
sox_ng, which applies the same chain as Lyrion's side (gain -6, rate to the
DSD rate, sdm) and hands the DAC either DoP (sox_ng's `dop` effect, straight
into aplay) or native DSD (a DSDIFF stream, repacked here into the DAC's
DSD_U32_BE/… words).

Two things the DSP path leaves to CamillaDSP are done here:

  * the Loopback runs on the system clock, the DAC on its own crystal. The
    PCM that waits here between the two shows which one is faster, and the
    Loopback's "PCM Rate Shift 100000" control slows it down or speeds it up
    (squeezelite with it) so that the backlog stays put;
  * while nothing plays, the Loopback only gives silence: after IDLE_SECONDS
    of it sox_ng and aplay go away (the DAC is free and the CPU idle), and
    the first sound brings them back.

Settings come from /run/hifi-pcm2dsd/player.json, which hifi_squeezelite.py
writes whenever it renders squeezelite's line (and removes when this path
does not apply): a change of rate, filter or DAC is picked up within a
second. Runs as hifi-pcm2dsd-player.service.
"""
import collections
import fcntl
import json
import os
import signal
import subprocess
import sys
import threading
import time

CONF = '/run/hifi-pcm2dsd/player.json'
# How far behind squeezelite the DAC sounds, in seconds, while the DAC side
# runs: vu_meter_daemon.py holds the meters back by as much, or they would
# move half a second before the music.
LATENCY = '/run/hifi-pcm2dsd/latency'
SOX_NG = '/usr/local/bin/sox_ng'
RATES = {'dsd64': 2822400, 'dsd128': 5644800, 'dsd256': 11289600,
         'dsd512': 22579200}
FILTERS = ('clans-8', 'sdm-8')
# squeezelite's native DSD formats (hifi_squeezelite.NATIVE_FORMAT_NAMES) →
# (ALSA format, bytes per channel word, big endian)
NATIVE = {
    'u32be': ('DSD_U32_BE', 4, True),
    'u32le': ('DSD_U32_LE', 4, False),
    'u16be': ('DSD_U16_BE', 2, True),
    'u16le': ('DSD_U16_LE', 2, False),
    'u8': ('DSD_U8', 1, True),
}
FRAME_BYTES = 8                 # S32_LE stereo, what squeezelite plays into the Loopback
READ_BYTES = 16384
IDLE_SECONDS = 15
# The PCM waiting here between the Loopback and sox_ng. Whatever it settles
# at once sox_ng and aplay have filled up (~0.3 s) is what it is kept at:
# only the drift between the two clocks is corrected, never the start-up's
# own backlog, which would take a needlessly large rate change. Never less
# than MIN_TARGET_SECONDS, the cushion for a busy moment of the box.
SETTLE_SECONDS = 10
MIN_TARGET_SECONDS = 0.1
MAX_SECONDS = 2.0               # past this the DAC is not taking anything: drop
CONTROL_PERIOD = 2.0
# Rate shift, in ppm of the Loopback's clock: proportional to the backlog's
# distance from the target, plus an integral that learns the steady
# difference between the two clocks (a PI loop on what is an integrator,
# tuned critically damped at ~200 s: 2ζω·1e6 and ω²·1e6 with ω = 0.005).
# Crystals are within ±100 ppm of nominal; ±2000 (3 cents) leaves room and
# stays inaudible.
KP_PPM_PER_S = 10000.0
KI_PPM_PER_S2 = 25.0
MAX_PPM = 2000.0
RETRY_SECONDS = 5
APLAY_BUFFER_US = 200000
# sox_ng's own share of the delay: it works through its input in blocks
# (8192 samples, 46 ms at 176.4 kHz), plus the rate filter's and sdm's
SOX_SECONDS = 0.05
F_GETPIPE_SZ = getattr(fcntl, 'F_GETPIPE_SZ', 1032)
SHIFT_CTL = 'iface=PCM,name=PCM Rate Shift 100000,device=1,subdevice={sub}'
DEBUG = bool(os.environ.get('HIFI_P2D_DEBUG'))


def log(msg):
    print(f'hifi-pcm2dsd-player: {msg}', flush=True)


# ── settings ───────────────────────────────────────────────────────
def clean_conf(doc):
    """The settings this needs from the file, or None when they are not
    usable (no file: the path is off)."""
    if not isinstance(doc, dict):
        return None
    mode, flt, carrier = doc.get('mode'), doc.get('filter'), doc.get('carrier')
    rate, dac, cap = doc.get('rate'), doc.get('dac'), doc.get('capture')
    if mode not in RATES or carrier not in ('dop',) + tuple(NATIVE):
        return None
    if not isinstance(rate, int) or rate <= 0 or not isinstance(dac, str) or not dac:
        return None
    if not isinstance(cap, str) or not cap:
        return None
    bits = doc.get('dop_bits') if doc.get('dop_bits') in (24, 32) else 32
    return {'mode': mode, 'filter': flt if flt in FILTERS else FILTERS[0], 'carrier': carrier,
            'rate': rate, 'dac': dac, 'capture': cap, 'dop_bits': bits,
            'subdevice': _subdevice(cap)}


def _subdevice(device):
    for part in device.split(','):
        if part.startswith('SUBDEV='):
            return part[len('SUBDEV='):]
    return '0'


def read_conf(path=CONF):
    try:
        with open(path, encoding='utf-8') as f:
            return clean_conf(json.load(f))
    except (OSError, ValueError):
        return None


# ── command lines ──────────────────────────────────────────────────
def arecord_argv(conf):
    return ['arecord', '-q', '-D', conf['capture'], '-t', 'raw', '-f', 'S32_LE', '-c', '2',
            '-r', str(conf['rate'])]


def sox_argv(conf, sox=SOX_NG):
    dsd = RATES[conf['mode']]
    source = ['-t', 'raw', '-r', str(conf['rate']), '-e', 'signed', '-b', '32', '-c', '2', '-']
    chain = ['gain', '-6', 'rate', '-v', str(dsd), 'sdm', '-f', conf['filter']]
    if conf['carrier'] == 'dop':
        # 16 DSD bits per channel in every 24-bit sample, marked 0x05/0xFA
        sink = ['-t', 'raw', '-e', 'signed', '-b', str(conf['dop_bits']), '-r', str(dsd // 16), '-']
        return [sox, '-q', '--multi-threaded', *source, *sink, *chain, 'dop']
    return [sox, '-q', '--multi-threaded', *source, '-t', 'dff', '-', *chain]


def aplay_argv(conf):
    if conf['carrier'] == 'dop':
        fmt = 'S24_3LE' if conf['dop_bits'] == 24 else 'S32_LE'
    else:
        fmt = NATIVE[conf['carrier']][0]
    return ['aplay', '-q', '-D', conf['dac'], '-t', 'raw', '-f', fmt, '-c', '2',
            '-r', str(aplay_rate(conf)), '-B', str(APLAY_BUFFER_US)]


def aplay_rate(conf):
    """Frames per second the DAC is opened at."""
    dsd = RATES[conf['mode']]
    if conf['carrier'] == 'dop':
        return dsd // 16
    return dsd // (8 * NATIVE[conf['carrier']][1])


def dac_bytes_per_second(conf):
    """What sox_ng writes per second, both channels: DoP samples, or the
    1-bit stream."""
    dsd = RATES[conf['mode']]
    if conf['carrier'] == 'dop':
        return dsd // 16 * 2 * (3 if conf['dop_bits'] == 24 else 4)
    return dsd // 8 * 2


def pipe_size(fd):
    try:
        return fcntl.fcntl(fd, F_GETPIPE_SZ)
    except OSError:
        return 65536


def status_path(dac, proc_asound='/proc/asound'):
    """/proc/asound/<card>/pcm<dev>p/sub0/status for 'hw:CARD=<card>,DEV=<dev>'."""
    card, dev = None, '0'
    for part in dac.split(':', 1)[-1].split(','):
        key, _, value = part.partition('=')
        if key == 'CARD':
            card = value
        elif key == 'DEV':
            dev = value
    if not card:
        return None
    return os.path.join(proc_asound, card, f'pcm{dev}p', 'sub0', 'status')


def dac_delay_seconds(conf, path=None):
    """What the DAC has queued and not played yet (ALSA's `delay`), or the
    buffer aplay asks for when that cannot be read."""
    path = path or status_path(conf['dac'])
    try:
        with open(path, encoding='ascii', errors='replace') as f:
            for line in f:
                key, _, value = line.partition(':')
                if key.strip() == 'delay':
                    return max(0, int(value.split()[0])) / aplay_rate(conf)
    except (OSError, ValueError, IndexError, TypeError):
        pass
    return APLAY_BUFFER_US / 1e6


# ── native DSD: DSDIFF → the DAC's words ─────────────────────────────
class DffReader:
    """Strips the DSDIFF container sox_ng writes to a pipe (FRM8, then
    chunks; the sound data, chunk 'DSD ', comes last with an unknown size)
    and hands back the 1-bit data: one byte per channel in turn, earliest
    bit in the most significant place."""

    def __init__(self):
        self.buf = bytearray()
        self.state = 'form'
        self.skip = 0

    def feed(self, data):
        if self.state == 'data':
            return bytes(data)
        self.buf += data
        while True:
            if self.state == 'form':
                if len(self.buf) < 16:
                    return b''
                if self.buf[:4] != b'FRM8' or self.buf[12:16] != b'DSD ':
                    raise ValueError('not a DSDIFF stream')
                del self.buf[:16]
                self.state = 'chunks'
            elif self.skip:
                n = min(self.skip, len(self.buf))
                del self.buf[:n]
                self.skip -= n
                if self.skip:
                    return b''
            else:
                if len(self.buf) < 12:
                    return b''
                cid, size = bytes(self.buf[:4]), int.from_bytes(self.buf[4:12], 'big')
                del self.buf[:12]
                if cid == b'DSD ':
                    self.state = 'data'
                    out, self.buf = bytes(self.buf), bytearray()
                    return out
                self.skip = size + (size & 1)


def pack_native(data, word, big_endian):
    """Interleaved DSD bytes (L R L R …, as in DSDIFF) → frames of one
    `word`-byte word per channel, the earliest byte first (big endian) or
    last (little endian). len(data) must be a multiple of 2 × word."""
    if word == 1:
        return bytes(data)
    out = bytearray(len(data))
    left, right = data[0::2], data[1::2]
    step = 2 * word
    for j in range(word):
        pos = j if big_endian else word - 1 - j
        out[pos::step] = left[j::word]
        out[word + pos::step] = right[j::word]
    return bytes(out)


# ── the DAC side: sox_ng (+ the repacking) + aplay ────────────────────
class Chain:
    def __init__(self, conf):
        self.conf = conf
        self.sox = self.aplay = self.pump = None
        self.failed = self.stopping = False
        self.pipe_in = self.pipe_out = 65536

    def start(self):
        c = self.conf
        log(f"{c['mode'].upper()} {c['filter']} as {c['carrier']} to {c['dac']}")
        self.sox = subprocess.Popen(sox_argv(c), stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        # once running, every pipe on the way is full: aplay sets the pace
        self.pipe_in = pipe_size(self.sox.stdin.fileno())
        self.pipe_out = pipe_size(self.sox.stdout.fileno())
        if c['carrier'] == 'dop':
            self.aplay = subprocess.Popen(aplay_argv(c), stdin=self.sox.stdout)
            self.sox.stdout.close()           # aplay holds it now
        else:
            self.aplay = subprocess.Popen(aplay_argv(c), stdin=subprocess.PIPE)
            self.pipe_out += pipe_size(self.aplay.stdin.fileno())
            self.pump = threading.Thread(target=self._repack, daemon=True)
            self.pump.start()

    def _repack(self):
        _, word, big = NATIVE[self.conf['carrier']]
        frame = 2 * word
        reader, rest = DffReader(), b''
        try:
            while True:
                chunk = self.sox.stdout.read1(65536)
                if not chunk:
                    break
                data = rest + reader.feed(chunk)
                cut = len(data) - len(data) % frame
                rest = data[cut:]
                if cut:
                    self.aplay.stdin.write(pack_native(data[:cut], word, big))
                    self.aplay.stdin.flush()
        except (OSError, ValueError) as e:
            if not self.stopping:
                log(f'native DSD stream stopped: {e}')
            self.failed = True
        finally:
            try:
                self.aplay.stdin.close()
            except OSError:
                pass

    def latency(self, backlog_s, dac_delay=None):
        """Seconds from squeezelite's output to the DAC's: the PCM waiting
        here, the full pipes on the way, sox_ng, what the DAC holds."""
        c = self.conf
        if dac_delay is None:
            dac_delay = dac_delay_seconds(c)
        return (backlog_s + self.pipe_in / (c['rate'] * FRAME_BYTES)
                + self.pipe_out / dac_bytes_per_second(c) + SOX_SECONDS + dac_delay)

    def write(self, data):
        try:
            self.sox.stdin.write(data)
            self.sox.stdin.flush()
            return True
        except (OSError, ValueError):
            self.failed = True
            return False

    def alive(self):
        return (not self.failed and self.sox.poll() is None and self.aplay.poll() is None)

    def stop(self):
        # Processes first, pipes after: the writer thread may be blocked in a
        # write to sox_ng's stdin, and closing that file waits for the write.
        self.stopping = True
        procs = [p for p in (self.sox, self.aplay) if p is not None]
        for p in procs:
            if p.poll() is None:
                # sox_ng has nothing worth flushing, and on SIGTERM it does
                # try, into a pipe aplay has just let go of
                p.kill() if p is self.sox else p.terminate()
        for p in procs:
            t0 = time.monotonic()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
            if DEBUG:
                log(f'{p.args[0]} gone in {time.monotonic() - t0:.2f} s')
        for p in procs:
            for f in (p.stdin, p.stdout):
                try:
                    if f:
                        f.close()
                except (OSError, ValueError):
                    pass


# ── the Loopback side ───────────────────────────────────────────────
def is_silent(chunk):
    return chunk.count(0) == len(chunk)


class RateControl:
    """Keeps the PCM waiting here where it settled after the DAC side
    started, by moving the Loopback's clock: more backlog than that means the
    Loopback runs fast against the DAC, and a higher shift slows it (and
    squeezelite) down. The integral stays across stops: it is the difference
    between the two clocks, which does not change with the music."""

    def __init__(self, subdevice, run=None):
        self.ctl = SHIFT_CTL.format(sub=subdevice)
        self.run = run or (lambda argv: subprocess.run(argv, capture_output=True, timeout=5))
        self.integral = 0.0
        self.value = None
        self.target = None
        self.since = 0.0

    def restart(self, now):
        """The DAC side (re)started: learn the level to keep again."""
        self.target = None
        self.since = now

    def set(self, value):
        if value == self.value:
            return
        try:
            self.run(['amixer', '-q', '-c', 'Loopback', 'cset', self.ctl, str(value)])
            self.value = value
        except Exception as e:
            log(f'cannot set the Loopback rate: {e}')

    def update(self, backlog_s, dt, now):
        if self.target is None:
            if now - self.since < SETTLE_SECONDS:
                return self.value
            self.target = max(MIN_TARGET_SECONDS, backlog_s)
        err = backlog_s - self.target
        self.integral += err * dt
        limit = MAX_PPM / KI_PPM_PER_S2
        self.integral = max(-limit, min(limit, self.integral))
        ppm = max(-MAX_PPM, min(MAX_PPM, KP_PPM_PER_S * err + KI_PPM_PER_S2 * self.integral))
        value = 100000 + int(round(ppm / 10.0))
        self.set(value)
        return value

    def reset(self):
        self.set(100000)


class Player:
    def __init__(self, conf, conf_path=CONF, latency_path=LATENCY):
        self.conf, self.conf_path, self.latency_path = conf, conf_path, latency_path
        self.lock = threading.Lock()
        self.wake = threading.Condition(self.lock)
        self.queue = collections.deque()
        self.queued = 0
        self.want = False             # sound came: the DAC side should run
        self.last_sound = 0.0
        self.chain = None
        self.rec = None
        self.stopping = False
        self.backlog_sum = 0.0
        self.backlog_n = 0
        self.rate = RateControl(conf['subdevice'])
        self.bps = conf['rate'] * FRAME_BYTES

    # reader thread: arecord → queue
    def _read(self):
        fd = self.rec.stdout.fileno()
        while not self.stopping:
            chunk = os.read(fd, READ_BYTES)
            if not chunk:
                break
            silent = is_silent(chunk)
            with self.lock:
                if not silent:
                    self.last_sound = time.monotonic()
                    self.want = True
                if not self.want:
                    continue
                self.queue.append(chunk)
                self.queued += len(chunk)
                while self.queued > MAX_SECONDS * self.bps:
                    self.queued -= len(self.queue.popleft())
                self.backlog_sum += self.queued / self.bps
                self.backlog_n += 1
                self.wake.notify()
        with self.lock:
            self.stopping = True
            self.wake.notify_all()

    # writer thread: queue → sox_ng
    def _write(self):
        while True:
            with self.lock:
                while not self.stopping and not (self.queue and self.chain is not None):
                    self.wake.wait(0.5)
                if self.stopping:
                    return
                chain = self.chain
                chunk = self.queue.popleft()
                self.queued -= len(chunk)
            chain.write(chunk)

    def _start_chain(self):
        chain = Chain(self.conf)
        try:
            chain.start()
        except OSError as e:
            log(f'cannot start the DAC side: {e}')
            chain.stop()
            return None
        return chain

    def _stop_chain(self, why):
        with self.lock:
            chain, self.chain = self.chain, None
            self.queue.clear()
            self.queued = 0
            self.want = False
            self.backlog_sum = self.backlog_n = 0
        self._publish(None)
        if chain is not None:
            chain.stop()
            log(why)

    def _publish(self, seconds):
        """The delay for the VU meters; None: nothing plays through here."""
        try:
            if seconds is None:
                os.unlink(self.latency_path)
                return
            tmp = self.latency_path + '.tmp'
            with open(tmp, 'w') as f:
                f.write(f'{seconds:.3f}\n')
            os.replace(tmp, self.latency_path)
        except OSError:
            pass

    def run(self):
        self.rec = subprocess.Popen(arecord_argv(self.conf), stdout=subprocess.PIPE)
        reader = threading.Thread(target=self._read, daemon=True)
        writer = threading.Thread(target=self._write, daemon=True)
        reader.start()
        writer.start()
        self.rate.reset()
        retry_at = 0.0
        last_control = time.monotonic()
        mtime = _mtime(self.conf_path)
        try:
            while not self.stopping:
                time.sleep(0.25)
                now = time.monotonic()
                m = _mtime(self.conf_path)
                if m != mtime:
                    mtime = m
                    new = read_conf(self.conf_path)
                    if new is None or (new['capture'], new['rate']) != (self.conf['capture'], self.conf['rate']):
                        return 'reload'
                    if new != self.conf:
                        # same Loopback end: only the DAC side starts again,
                        # with the next sound
                        self._stop_chain('settings changed')
                        self.conf = new
                        continue
                with self.lock:
                    want, chain = self.want, self.chain
                if chain is not None and not chain.alive():
                    self._stop_chain('the DAC side stopped: trying again in a few seconds')
                    retry_at = now + RETRY_SECONDS
                    continue
                if chain is not None and now - self.last_sound > IDLE_SECONDS:
                    self._stop_chain('silence: DAC released')
                    continue
                if chain is None and want and now >= retry_at:
                    chain = self._start_chain()
                    if chain is None:
                        retry_at = now + RETRY_SECONDS
                        with self.lock:
                            self.want = False
                            self.queue.clear()
                            self.queued = 0
                        continue
                    with self.lock:
                        self.chain = chain
                        self.backlog_sum = self.backlog_n = 0
                        self.wake.notify_all()
                    self.rate.restart(now)
                    last_control = now
                if chain is not None and now - last_control >= CONTROL_PERIOD:
                    with self.lock:
                        n, s = self.backlog_n, self.backlog_sum
                        self.backlog_sum = self.backlog_n = 0
                    if n:
                        self._publish(chain.latency(s / n))
                        value = self.rate.update(s / n, now - last_control, now)
                        if DEBUG:
                            log(f'backlog {s / n:.3f} s (keeping {self.rate.target}), Loopback rate {value}')
                    last_control = now
            return 'capture-ended'
        finally:
            self.stopping = True
            self._stop_chain('stopped')
            if self.rec.poll() is None:
                self.rec.kill()             # on SIGTERM arecord takes seconds to go
                self.rec.wait()
            self.rate.reset()


def _mtime(path):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def main(argv):
    if len(argv) > 1:
        print('usage: hifi-pcm2dsd-player.py', file=sys.stderr)
        return 2
    def on_term(signum, frame):
        raise SystemExit(0)             # Player.run's `finally` lets go of the DAC

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    while True:
        conf = read_conf()
        if conf is None:
            log(f'{CONF}: nothing to do')
            return 0
        if Player(conf).run() != 'reload':
            log('the Loopback stopped giving sound')
            return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
