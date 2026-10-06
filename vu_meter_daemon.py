#!/usr/bin/env python3
import asyncio
import mmap
import os
import struct
import json
import websockets
import math
import time
import glob
import subprocess
import threading

# numpy makes the per-frame RMS bucketing ~an order of magnitude cheaper than the
# pure-Python loop (this runs 30×/s during playback). Optional: if it isn't
# installed the daemon falls back to the original pure-Python path below.
try:
    import numpy as np
except Exception:
    np = None

# Logs go to journald only (hifi-vumeter.service sets PYTHONUNBUFFERED so each
# print() lands there at once). 🚨 No hifi_logging.tee_stdio_to_file() here:
# this daemon runs as `hifi`, and /var/log/hifi is 0750 root:root on purpose
# (SSID/hostname can show up in those logs), so the rotated file could never
# be opened — the tee silently fell back to a NullHandler and vumeter.log never
# existed. The journal is persistent on the image (/var/log/journal) and the
# support bundle already dumps it (api_server.SUPPORT_JOURNAL_UNITS has
# 'hifi-vumeter' → journal/hifi-vumeter.log in the zip).

# DoP (DSD-over-PCM) marker bytes, alternated by squeezelite every output
# frame. Squeezelite's _vis_export always copies the *top* 16 bits of each
# 32-bit output sample into the vis buffer regardless of format; for DoP that
# top half is [marker: 0x05/0xFA][first DSD data byte]. So during DSD
# playback the vis buffer's high bytes carry this marker instead of real PCM
# — that's what lets us tell DoP apart from PCM below.
_DOP_MARKERS = (0x05, 0xFA)
# Calibration knob: a DSD bitstream is 1-bit delta-sigma, so its decimated
# bit-density (see _decode_dop below) tracks the analog waveform but isn't
# naturally on the same 0..32767 scale as PCM. DSD's "0 dB" reference sits
# around 50% modulation depth, so 2.0 is a reasonable starting point — tune
# on real hardware if the DSD needle reads noticeably hotter/cooler than PCM
# at the same perceived loudness.
_DSD_FS_GAIN = 2.0
# Moving-average window (in PDM bits) used to low-pass the DSD bitstream back
# into a coarse PCM-like envelope.
_DSD_DECIMATE_BLOCK = 16

# Native DSD (-D :u32be and friends) has no marker at all: dsd.c packs the raw
# bitstream straight into each 32-bit output word (DSD_U32: b0<<24|b1<<16|b2<<8|b3,
# DSD_U16: b0<<24|b1<<16, DSD_U8: b0<<24, oldest bit in the MSB), and
# _vis_export keeps the top 16 bits — so every vis entry is 16 (8 for DSD_U8)
# consecutive PDM bits of that channel. Read as PCM that is near full-scale
# noise (squeezelite's own DSD silence, 0x69 bytes, is a constant 0x6969 =
# -1.7 dBFS), which pinned both needles to the stop. What gives it away:
#   * vis_t.rate is the output word rate, DSD rate / 32, /16 or /8 — never
#     below 88200 (DSD64 as DSD_U32), so 44.1/48 kHz PCM is never examined;
#   * as numbers, the words are white: neighbours are 8-32 PDM bits apart and
#     a 1-bit stream is dominated by its shaped HF noise, so their lag-1
#     correlation sits near 0 at a level around -4 dBFS. Hi-res PCM music is
#     heavily oversampled, so its lag-1 correlation is well above 0.9, and a
#     quiet PCM noise floor is far below the level threshold.
_NATIVE_DSD_MIN_RATE = 88200
# RMS (on the +/-32767 scale) a buffer must exceed to be taken for raw DSD;
# raw DSD words measure ~13000-21000, -12 dBFS of PCM is ~8200.
_NATIVE_DSD_MIN_RMS = 8000.0
# Lag-1 correlation below which a loud buffer is taken for raw DSD; once a
# rate has been recognised the bar is raised (hysteresis), so the periodic
# idle patterns some modulators settle into in near-silence do not flip the
# meter back to reading the bits as PCM for a frame.
_NATIVE_DSD_MAX_RHO1 = 0.5
_NATIVE_DSD_KEEP_RHO1 = 0.9
# Native DSD is decoded by bit density like DoP, over a longer window: the
# 1-bit quantisation noise is huge, and DSD_U32 only exposes the first 16
# bits of every 32, which folds the shaped HF noise back into the audio band.
# Simulated with a 5th-order modulator, 16-bit blocks left a -50 dB signal
# reading ~60% on the meter; 128-bit blocks bring that to ~35%, with loud
# passages still at the top. 512 words per channel still give 32-64 envelope
# samples, 2-4 per bar.
_NATIVE_DSD_DECIMATE_BLOCK = 128


class SqueezeliteVisualizer:
    def __init__(self):
        self.shm_file = self.find_shm_file()
        self.mmap_obj = None
        self.fd = None

        # We want to send 32 bars to the frontend
        self.num_bars = 32

        # Track the last known buffer index to detect playback state
        # instead of relying on the running boolean flag which may be incorrectly aligned.
        self.last_buf_index = -1
        self.same_index_count = 0

        # Buffer offset will be determined dynamically
        self.buffer_offset = None
        self.buf_size = 0
        # True once a scan has actually matched one of the known vis_t
        # layouts (as opposed to falling back to a guessed default) — see
        # the reuse-on-reconnect comment in connect() for why this matters.
        self._layout_confirmed = False
        # vis_t.rate at which the buffer was last recognised as raw native
        # DSD, None otherwise (see _NATIVE_DSD_KEEP_RHO1).
        self._native_dsd_rate = None

    def find_shm_file(self):
        """Find the squeezelite shared memory file in /dev/shm"""
        files = glob.glob('/dev/shm/squeezelite-*')
        if not files:
            return None
        # The name carries the player MAC, and a segment left by a player
        # that has since changed MAC (a first `-m`, see hifi_squeezelite.
        # derived_mac) stays in /dev/shm until reboot, frozen: the newest
        # one is the player that is running.
        def created(f):
            try:
                return os.stat(f).st_ctime
            except OSError:
                return 0
        newest = max(files, key=created)
        print(f"Found Squeezelite shared memory at: {newest}")
        return newest

    def connect(self):
        """Connect to the shared memory file"""
        if not self.shm_file:
            self.shm_file = self.find_shm_file()

        if not self.shm_file or not os.path.exists(self.shm_file):
            return False

        try:
            self.fd = os.open(self.shm_file, os.O_RDONLY)
            size = os.path.getsize(self.shm_file)
            self.mmap_obj = mmap.mmap(self.fd, size, access=mmap.ACCESS_READ)

            if self._layout_confirmed:
                # Squeezelite unlinks+recreates this shm segment on every
                # restart, which is exactly when connect() gets called again
                # (see shm_changed()/read_audio_data()) — but the struct
                # layout of vis_t is a fixed property of the squeezelite
                # binary on this device, it never changes across restarts.
                # Re-scanning here would race against squeezelite still
                # zero-initializing the *freshly recreated* segment's header
                # (file already ftruncate'd to full size, but buf_size not
                # written yet), which made the scan below fail and fall back
                # to a guessed offset — silently misreading buf_index/PCM
                # from the wrong region of the segment and producing
                # levels that jump around at random until the next restart
                # happened to re-detect correctly. Once genuinely detected,
                # just reuse it.
                self.buf_size = (size - self.buffer_offset) // 2
                return True

            # Autodetect the actual layout. Different Squeezelite forks (like R2)
            # or platforms have different headers.
            # The 24- and 32-byte cases below are older guesses; the 80-byte
            # one is what squeezelite really lays out on x86-64.
            # The actual struct vis_t (squeezelite output_vis.c) contains:
            # [pthread_rwlock_t] [buf_size: u32] [buf_index: u32] [running: bool, padded to 4]
            # [rate: u32] [updated: time_t] [buffer: s16_t[buf_size]]
            # On x86-64 glibc the rwlock is 56 bytes, so that is the 80-byte
            # header below (buf_index at 60, rate at 68), buf_size 16384.
            # buf_size and buf_index count s16 samples, not bytes.

            # To reliably find the buffer and index, let's scan for a matching buf_size.
            # Usually buf_size is 4096, 8192, 16384.
            # We look for a 4-byte integer `S` where `S * 2 + offset_of_buffer == file_size`.

            self.mmap_obj.seek(0)
            data = self.mmap_obj.read(128) # Read enough header
            ints = struct.unpack(f'<{len(data)//4}I', data)

            self.buffer_offset = None
            self.index_offset = None

            for i, val in enumerate(ints):
                # Check if this integer could be buf_size
                if val in (4096, 8192, 16384, 32768):
                    # In vis_t, if val is buf_size, then buf_index is the next integer (i+1)
                    # and running is i+2, rate is i+3, time_t is i+4 (or i+5 if 64-bit).
                    # Let's check if file_size perfectly matches a known header size:
                    # buffer_size_in_bytes = val * 2

                    if size - 24 == val * 2:
                        self.buffer_offset = 24
                        self.index_offset = (i + 1) * 4
                        print(f"Detected 32-bit architecture shared memory (offset 24, size {val})")
                        break
                    elif size - 32 == val * 2:
                        self.buffer_offset = 32
                        self.index_offset = (i + 1) * 4
                        print(f"Detected standard 64-bit architecture shared memory (offset 32, size {val})")
                        break
                    elif size - 80 == val * 2:
                        # Seen on DietPi x86 with some specific Squeezelite build
                        self.buffer_offset = 80
                        self.index_offset = (i + 1) * 4
                        print(f"Detected custom/DietPi 80-byte header shared memory (offset 80, size {val})")
                        break

            if self.buffer_offset is None:
                print(f"Warning: Could not auto-detect offset. File size: {size}. Defaulting to 32.")
                self.buffer_offset = 32
                self.index_offset = 8 # Default standard buf_index offset
            else:
                # A real match (not the guessed fallback above) — trust it
                # for the rest of this process's lifetime, see the
                # _layout_confirmed branch above.
                self._layout_confirmed = True

            self.buf_size = (size - self.buffer_offset) // 2

            return True
        except Exception as e:
            print(f"Error opening shared memory: {e}")
            self.disconnect()
            return False

    def shm_changed(self):
        """True if the file at self.shm_file now has a different inode than
        the one we have open (or is gone). Squeezelite unlinks and recreates
        its shm segment on every restart (e.g. a DAC change, player rename,
        or multiroom "follow another device" switch all restart it), so an
        already-open fd/mmap silently keeps reading an orphaned, frozen
        copy — buf_index never advances again, so the meter looks dead."""
        if not self.shm_file or self.fd is None:
            return False
        try:
            return os.stat(self.shm_file).st_ino != os.fstat(self.fd).st_ino
        except OSError:
            return True

    def disconnect(self):
        if self.mmap_obj:
            self.mmap_obj.close()
            self.mmap_obj = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _read_latest(self, buf_index, count):
        """Raw little-endian bytes of the `count` interleaved samples
        squeezelite wrote last, oldest first; None if the header doesn't fit.

        🚨 buf_index is a *sample* index into vis_t.buffer, not a byte
        offset: _vis_export does `vis_mmap->buffer[i++] = ...` per s16,
        wraps i at VIS_BUF_SIZE and stores `buf_index = i`, the slot the
        next sample goes in. Treating it as bytes put the window at sample
        buf_index/2 — 0-93 ms behind the audio in a sawtooth over the ring —
        and, half of the time, half a frame off, which swapped L and R.
        squeezelite writes L,R pairs into an even-sized ring, so an even
        buf_index and an even count keep the window on L."""
        ring = self.buf_size
        if count > ring or buf_index >= ring:
            return None
        buf_index -= buf_index % 2
        start = buf_index - count
        base = self.buffer_offset
        if start >= 0:
            self.mmap_obj.seek(base + start * 2)
            return self.mmap_obj.read(count * 2)
        # The window straddles the end of the ring: its tail, then its head.
        self.mmap_obj.seek(base + (ring + start) * 2)
        older = self.mmap_obj.read(-start * 2)
        self.mmap_obj.seek(base)
        return older + self.mmap_obj.read(buf_index * 2)

    def _read_rate(self):
        """vis_t.rate (output->current_sample_rate): the u32 after buf_index
        and the bool `running`, which is padded to 4 bytes. 0 if unreadable."""
        try:
            self.mmap_obj.seek(self.index_offset + 8)
            return struct.unpack('<I', self.mmap_obj.read(4))[0]
        except (struct.error, ValueError):
            return 0

    def read_audio_data(self):
        """Read current PCM data and calculate visualizer levels"""
        if not self.mmap_obj:
            if not self.connect():
                return None
        elif self.shm_changed():
            self.disconnect()
            self.shm_file = None  # force a fresh glob in case the name itself changed too
            if not self.connect():
                return None

        try:
            # We only need to reliably read buf_index
            self.mmap_obj.seek(self.index_offset)
            buf_index = struct.unpack('<I', self.mmap_obj.read(4))[0]

            # If buf_index hasn't changed for a few ticks, we consider it stopped/paused
            if buf_index == self.last_buf_index:
                self.same_index_count += 1
            else:
                self.same_index_count = 0
                self.last_buf_index = buf_index

            # If it hasn't changed for ~10 frames, send zeros
            if self.same_index_count > 10:
                return self._zero_levels()

            samples_to_read = 1024  # Read last 1024 interleaved samples (512 pairs)
            raw_samples = self._read_latest(buf_index, samples_to_read)
            if raw_samples is None:
                # Header doesn't fit the segment (e.g. caught mid-recreate)
                return self._zero_levels()

            num_samples = len(raw_samples) // 2
            if num_samples == 0:
                return self._zero_levels()

            bars_per_channel = max(1, self.num_bars // 2)
            # Only hi-res rates can carry native DSD, see _NATIVE_DSD_MIN_RATE.
            rate = self._read_rate()
            if rate < _NATIVE_DSD_MIN_RATE:
                self._native_dsd_rate = None

            if np is not None:
                dop_stereo = self._decode_dop(raw_samples, num_samples)
                if dop_stereo is not None:
                    left_env, right_env = dop_stereo
                    return (self._bucket_rms(left_env, bars_per_channel),
                            self._bucket_rms(right_env, bars_per_channel))

                # Vectorised RMS — ~10x cheaper than the Python loop at 30 fps.
                buf = np.frombuffer(raw_samples, dtype='<i2', count=num_samples)
                if rate >= _NATIVE_DSD_MIN_RATE:
                    native = self._decode_native_dsd(buf, rate)
                    if native is not None:
                        return (self._bucket_rms(native[0], bars_per_channel),
                                self._bucket_rms(native[1], bars_per_channel))
                return self._stereo_levels_from_values(buf.astype(np.float64))

            # Pure-Python fallback (numpy not installed).
            samples = struct.unpack(f'<{num_samples}h', raw_samples)
            dop_stereo = self._decode_dop_py(samples)
            if dop_stereo is not None:
                left_env, right_env = dop_stereo
                return (self._bucket_rms_py(left_env, bars_per_channel),
                        self._bucket_rms_py(right_env, bars_per_channel))
            if rate >= _NATIVE_DSD_MIN_RATE:
                native = self._decode_native_dsd_py(samples, rate)
                if native is not None:
                    return (self._bucket_rms_py(native[0], bars_per_channel),
                            self._bucket_rms_py(native[1], bars_per_channel))
            return self._stereo_levels_from_values_py(samples)

        except Exception as e:
            print(f"Error reading shared memory: {e}")
            self.disconnect()
            return None

    # dB→percent mapping (shared by PCM and decoded-DSD paths): map -50 dBFS
    # → 0% and -5 dBFS → 100%, then a slight gamma so the top end compresses
    # like an analog VU meter. 0 VU is typically around -18..-14 dBFS
    # depending on calibration.
    _MIN_DB = -50.0
    _MAX_DB = -5.0

    def _zero_levels(self):
        """(left, right) all-zero levels in the current stereo payload shape."""
        bars_per_channel = max(1, self.num_bars // 2)
        return ([0] * bars_per_channel, [0] * bars_per_channel)

    def _bucket_rms(self, values, num_bars):
        """values: 1-D numpy float64 array on the same +/-32767 full-scale as
        PCM (real PCM samples, or a decimated DSD envelope). Buckets into
        num_bars and computes RMS->dB->percent."""
        n = values.size
        samples_per_bar = max(1, n // num_bars)
        usable = samples_per_bar * num_bars
        buckets = values[:usable].reshape(num_bars, samples_per_bar)
        rms = np.sqrt(np.mean(buckets * buckets, axis=1))
        with np.errstate(divide='ignore'):
            db = 20.0 * np.log10(rms / 32767.0)
        percent = np.clip((db - self._MIN_DB) / (self._MAX_DB - self._MIN_DB) * 100.0, 0.0, 100.0)
        percent = np.power(percent / 100.0, 1.2) * 100.0
        return [int(x) for x in percent]

    def _bucket_rms_py(self, values, num_bars):
        """Pure-Python equivalent of _bucket_rms."""
        n = len(values)
        samples_per_bar = max(1, n // num_bars)
        levels = []
        for i in range(num_bars):
            start_idx = i * samples_per_bar
            chunk = values[start_idx:start_idx + samples_per_bar]
            if not chunk:
                levels.append(0)
                continue
            rms = math.sqrt(sum(float(x) * x for x in chunk) / len(chunk))
            if rms <= 0:
                levels.append(0)
                continue
            db = 20 * math.log10(rms / 32767.0)
            percent = max(0.0, min(100.0, ((db - self._MIN_DB) / (self._MAX_DB - self._MIN_DB)) * 100.0))
            percent = math.pow(percent / 100.0, 1.2) * 100.0
            levels.append(int(percent))
        return levels

    def _stereo_levels_from_values(self, values):
        """values: 1-D numpy float64 array of *interleaved* stereo samples
        ([L0, R0, L1, R1, ...]). Deinterleaves into left/right before
        bucketing so each channel's RMS is computed independently, instead
        of bucketing the raw interleaved stream into consecutive time slices
        (which mixes both channels into every bucket)."""
        left = values[0::2]
        right = values[1::2]
        bars_per_channel = max(1, self.num_bars // 2)
        return (self._bucket_rms(left, bars_per_channel),
                self._bucket_rms(right, bars_per_channel))

    def _stereo_levels_from_values_py(self, values):
        """Pure-Python equivalent of _stereo_levels_from_values."""
        left = values[0::2]
        right = values[1::2]
        bars_per_channel = max(1, self.num_bars // 2)
        return (self._bucket_rms_py(left, bars_per_channel),
                self._bucket_rms_py(right, bars_per_channel))

    def _decode_dop(self, raw_samples, num_samples):
        """Detect a DoP (DSD-over-PCM) stream in the vis buffer and turn it
        into an approximate PCM envelope so the existing RMS meter pipeline
        can read DSD playback too, without touching the bit-perfect playback
        path at all.

        Each vis-buffer entry here is the truncated top 16 bits of a 32-bit
        DoP output frame: high byte = alternating 0x05/0xFA marker, low byte
        = one byte (8 sequential PDM bits) of the native DSD bitstream for
        that channel. A delta-sigma (DSD) bitstream's short-window bit
        average tracks the analog waveform, so decimating those bits with a
        small moving average recovers a coarse but real amplitude envelope.

        Vis-buffer entries are interleaved per channel just like PCM (one
        entry per output frame), so the marker/data bytes are deinterleaved
        into left/right *before* decimation — otherwise the recovered
        envelope mixes both channels' DSD bits together.

        Returns None if the buffer doesn't look like DoP (plain PCM path
        stays untouched then). Otherwise returns (left_env, right_env).
        """
        buf_u16 = np.frombuffer(raw_samples, dtype='<i2', count=num_samples).view(np.uint16)
        high_bytes = (buf_u16 >> 8) & 0xFF
        if np.isin(high_bytes, _DOP_MARKERS).mean() < 0.9:
            return None

        data_bytes = (buf_u16 & 0xFF).astype(np.uint8)
        left_env = self._decimate_dop_bytes(data_bytes[0::2])
        right_env = self._decimate_dop_bytes(data_bytes[1::2])
        if left_env is None or right_env is None:
            return None
        return left_env, right_env

    def _decimate_dop_bytes(self, data_bytes, block=_DSD_DECIMATE_BLOCK):
        """Unpack a single channel's DSD PDM bytes and decimate them into a
        coarse PCM-like envelope, `block` bits per sample. Returns None if
        there aren't enough bits for even one decimated sample."""
        bits = np.unpackbits(data_bytes).astype(np.float64) * 2.0 - 1.0
        usable_bits = (bits.size // block) * block
        if usable_bits == 0:
            return None
        decimated = bits[:usable_bits].reshape(-1, block).mean(axis=1)
        return np.clip(decimated * _DSD_FS_GAIN * 32767.0, -32767.0, 32767.0)

    def _decode_dop_py(self, samples):
        """Pure-Python equivalent of _decode_dop (numpy not installed)."""
        if not samples:
            return None
        marker_hits = sum(1 for s in samples if ((s >> 8) & 0xFF) in _DOP_MARKERS)
        if marker_hits / len(samples) < 0.9:
            return None

        left_env = self._decimate_dop_bytes_py(samples[0::2])
        right_env = self._decimate_dop_bytes_py(samples[1::2])
        if left_env is None or right_env is None:
            return None
        return left_env, right_env

    def _decimate_dop_bytes_py(self, samples):
        """Pure-Python equivalent of _decimate_dop_bytes."""
        bits = []
        for s in samples:
            byte = s & 0xFF
            for shift in range(7, -1, -1):
                bits.append(1.0 if (byte >> shift) & 1 else -1.0)
        return self._decimate_bits_py(bits)

    def _decimate_bits_py(self, bits, block=_DSD_DECIMATE_BLOCK):
        """Pure-Python decimation of a +/-1.0 PDM bit list (see
        _decimate_dop_bytes); None if there aren't enough bits."""
        usable = (len(bits) // block) * block
        if usable == 0:
            return None
        decimated = []
        for i in range(0, usable, block):
            chunk = bits[i:i + block]
            avg = sum(chunk) / block
            decimated.append(max(-32767.0, min(32767.0, avg * _DSD_FS_GAIN * 32767.0)))
        return decimated

    def _native_dsd_max_rho1(self, rate):
        """Lag-1 correlation bar for raw DSD at `rate`, with hysteresis."""
        return _NATIVE_DSD_KEEP_RHO1 if self._native_dsd_rate == rate else _NATIVE_DSD_MAX_RHO1

    def _decode_native_dsd(self, buf, rate):
        """Recognise raw native DSD in the vis buffer (see
        _NATIVE_DSD_MIN_RATE) and decode it into (left_env, right_env) by
        bit density, exactly like DoP; None when the buffer reads as PCM.
        buf: 1-D int16 numpy array of interleaved vis entries."""
        max_rho1 = self._native_dsd_max_rho1(rate)
        if not all(self._looks_like_raw_dsd(buf[ch::2].astype(np.float64), max_rho1)
                   for ch in (0, 1)):
            self._native_dsd_rate = None
            return None
        self._native_dsd_rate = rate

        words = buf.view(np.uint16)
        high = (words >> 8).astype(np.uint8)
        low = (words & 0xFF).astype(np.uint8)
        # DSD_U8 leaves the low byte empty; otherwise both bytes are
        # bitstream, the high one first in time.
        u8 = not low.any()
        envs = []
        for ch in (0, 1):
            data = high[ch::2] if u8 else np.column_stack((high[ch::2], low[ch::2])).ravel()
            env = self._decimate_dop_bytes(data, _NATIVE_DSD_DECIMATE_BLOCK)
            if env is None:
                return None
            envs.append(env)
        return envs[0], envs[1]

    def _looks_like_raw_dsd(self, values, max_rho1):
        """values: one channel's vis entries (numpy float64), read as PCM."""
        if values.size < 2:
            return False
        lo, hi = values.min(), values.max()
        if lo == hi:
            # A modulator's idle pattern (squeezelite pads with 0x69 bytes)
            # repeats one word; PCM doesn't hold a non-zero value still.
            return lo != 0
        c = values - values.mean()
        var = float(np.mean(c * c))
        if var < _NATIVE_DSD_MIN_RMS ** 2:
            return False
        return float(np.mean(c[:-1] * c[1:])) / var < max_rho1

    def _decode_native_dsd_py(self, samples, rate):
        """Pure-Python equivalent of _decode_native_dsd."""
        max_rho1 = self._native_dsd_max_rho1(rate)
        if not all(self._looks_like_raw_dsd_py(samples[ch::2], max_rho1) for ch in (0, 1)):
            self._native_dsd_rate = None
            return None
        self._native_dsd_rate = rate

        # DSD_U8 leaves the low byte empty: only bits 15..8 are bitstream.
        lowest_bit = 8 if not any(s & 0xFF for s in samples) else 0
        envs = []
        for ch in (0, 1):
            bits = []
            for s in samples[ch::2]:
                for shift in range(15, lowest_bit - 1, -1):
                    bits.append(1.0 if (s >> shift) & 1 else -1.0)
            env = self._decimate_bits_py(bits, _NATIVE_DSD_DECIMATE_BLOCK)
            if env is None:
                return None
            envs.append(env)
        return envs[0], envs[1]

    def _looks_like_raw_dsd_py(self, values, max_rho1):
        """Pure-Python equivalent of _looks_like_raw_dsd."""
        n = len(values)
        if n < 2:
            return False
        lo, hi = min(values), max(values)
        if lo == hi:
            return lo != 0
        mean = sum(values) / n
        c = [v - mean for v in values]
        var = sum(x * x for x in c) / n
        if var < _NATIVE_DSD_MIN_RMS ** 2:
            return False
        cov = sum(c[i] * c[i + 1] for i in range(n - 1)) / (n - 1)
        return cov / var < max_rho1


class BluetoothTapReader:
    """Fallback VU source for Bluetooth playback.

    hifi-bt-aplay-run fans its A2DP audio out to an unused CamillaDSP
    Loopback subdevice pair (DEV=0/1, SUBDEV=1 — DSP itself only ever uses
    SUBDEV=0) whenever that's possible; this class captures from the read
    side of that pair with `arecord` and runs the samples through the exact
    same RMS->dB->percent mapping as the squeezelite shm path
    (_levels_from_values/_levels_from_values_py on the SqueezeliteVisualizer
    passed in), so the VU meters look identical regardless of source.
    Lower priority than squeezelite — see vu_meter_server, which only calls
    this once squeezelite itself has nothing playing.
    """
    DEVICE = 'hw:CARD=Loopback,DEV=1,SUBDEV=1'
    NOW_PLAYING_FILE = '/run/hifi-bt/now-playing.json'
    RATE = 44100
    WINDOW_SAMPLES = 1024  # interleaved L/R samples, matches the shm reader's window

    def __init__(self):
        self.proc = None
        self.thread = None
        self.running = False
        self.buf = bytearray()
        self.lock = threading.Lock()

    def _bt_active(self):
        try:
            with open(self.NOW_PLAYING_FILE) as f:
                return bool(json.load(f).get('active'))
        except Exception:
            return False

    def _reader_loop(self):
        max_bytes = self.WINDOW_SAMPLES * 2  # 2 bytes/sample (S16_LE)
        try:
            while self.running and self.proc and self.proc.poll() is None:
                chunk = self.proc.stdout.read(4096)
                if not chunk:
                    break
                with self.lock:
                    self.buf.extend(chunk)
                    if len(self.buf) > max_bytes:
                        del self.buf[:len(self.buf) - max_bytes]
        except Exception:
            pass

    def _start(self):
        if self.proc is not None:
            return
        try:
            self.proc = subprocess.Popen(
                ['arecord', '-D', self.DEVICE, '-f', 'S16_LE', '-c', '2',
                 '-r', str(self.RATE), '-t', 'raw'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            self.running = True
            self.thread = threading.Thread(target=self._reader_loop, daemon=True)
            self.thread.start()
            print(f"BT VU tap: capturing {self.DEVICE}")
        except Exception as e:
            print(f"BT VU tap: could not start arecord: {e}")
            self.proc = None

    def _stop(self):
        self.running = False
        if self.proc is not None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=2)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None
        with self.lock:
            self.buf = bytearray()

    def read_levels(self, visualizer):
        """Levels list while Bluetooth is actively streaming, else None (so
        the caller falls through to plain silence handling)."""
        if not self._bt_active():
            if self.proc is not None:
                self._stop()
            return None
        self._start()
        if self.proc is None:
            return None
        with self.lock:
            raw = bytes(self.buf)
        num_samples = len(raw) // 2
        if num_samples < 64:
            # Capture just (re)started — not enough buffered yet this tick.
            return visualizer._zero_levels()
        if np is not None:
            values = np.frombuffer(raw, dtype='<i2', count=num_samples).astype(np.float64)
            return visualizer._stereo_levels_from_values(values)
        samples = struct.unpack(f'<{num_samples}h', raw)
        return visualizer._stereo_levels_from_values_py(list(samples))


# Main-loop cadence. Full rate whenever something is actually feeding the
# meters; slower once playback has been sitting still for a while, since a UI
# left on Now Playing keeps a client connected for the whole pause and every
# one of those frames carries the same zeroed levels. The idle rate is kept
# deliberately close to full rate: resuming costs at most one idle tick before
# the loop is back at 30 fps, and both clients already throttle incoming
# levels to 20 Hz and interpolate the needle with their own spring, so that
# tick is shorter than anything the needle can render.
_FRAME_INTERVAL = 0.033
_IDLE_INTERVAL = 0.1
# Idle frames served at full rate before slowing down. The needle must first
# receive the zeroed levels (read_audio_data only zeroes them after
# same_index_count > 10, i.e. ~0.33s into the pause), and this also keeps the
# short buffer stalls between tracks from flapping the cadence.
_IDLE_SETTLE_FRAMES = 15


async def vu_meter_server(websocket, path=None):
    """WebSocket handler to stream VU meter data.

    `path` is optional on purpose, so this one handler works on both Debian
    releases the fleet spans. python3-websockets 10.x (bookworm) invokes the
    handler as handler(connection, path); 14.x (trixie) dropped the second
    argument and calls handler(connection). With a required `path` the trixie
    library raised "vu_meter_server() missing 1 required positional argument:
    'path'" on every connection, so the browser never received a level and the
    VU meters sat still while audio played perfectly well. The argument is not
    used in the body — it only ever needed to be accepted."""
    print(f"Client connected to VU meter stream")
    viz = SqueezeliteVisualizer()
    bt_tap = BluetoothTapReader()

    # Send empty data initially
    empty_left, empty_right = viz._zero_levels()

    def _payload(stereo_levels, active):
        left, right = stereo_levels
        return json.dumps({"levels_l": left, "levels_r": right, "active": active})

    # Consecutive frames with no source feeding the meters. Only the branches
    # below that actually found a live source reset it, so any signal at all
    # puts the very next sleep back at full rate.
    idle_frames = 0

    try:
        while True:
            await asyncio.sleep(_IDLE_INTERVAL if idle_frames > _IDLE_SETTLE_FRAMES else _FRAME_INTERVAL)

            levels = viz.read_audio_data()
            # same_index_count > 10 means squeezelite's buffer isn't moving
            # (paused/stopped), same threshold read_audio_data itself uses to
            # force levels to zero — treat that as "nothing playing here" and
            # give the Bluetooth tap a chance instead of just showing zeros.
            sq_active = levels is not None and viz.same_index_count <= 10

            if sq_active:
                idle_frames = 0
                active = any(l > 0 for l in levels[0]) or any(l > 0 for l in levels[1])
                await websocket.send(_payload(levels, active))
                continue

            bt_levels = bt_tap.read_levels(viz)
            if bt_levels is not None:
                idle_frames = 0
                active = any(l > 0 for l in bt_levels[0]) or any(l > 0 for l in bt_levels[1])
                await websocket.send(_payload(bt_levels, active))
                continue

            idle_frames += 1

            if levels is None:
                # Shared memory not found or error, send zeros
                await websocket.send(_payload((empty_left, empty_right), False))
                # Poll slower if not active
                await asyncio.sleep(1.0)
            else:
                await websocket.send(_payload(levels, False))

    except websockets.exceptions.ConnectionClosed:
        print("Client disconnected")
    finally:
        viz.disconnect()
        bt_tap._stop()


async def main():
    print("Starting Squeezelite VU Meter Daemon on ws://127.0.0.1:9001")
    # Loopback only: the only consumer is the Electron kiosk UI running on the
    # appliance itself (AnalogVUMeter.jsx always connects to 'localhost'/the
    # file:// origin's hostname, never a LAN address), so there is no
    # legitimate reason for this stream to be reachable from other LAN hosts.
    server = await websockets.serve(vu_meter_server, "127.0.0.1", 9001)
    await server.wait_closed()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")