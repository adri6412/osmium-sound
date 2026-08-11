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

from hifi_logging import tee_stdio_to_file
# Every print() below keeps reaching the console/journald unchanged AND now also
# lands in a size-rotated file at /var/log/hifi/vumeter.log (journald alone is
# volatile on this image) — picked up by the support-bundle endpoint.
tee_stdio_to_file('vumeter')

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

    def find_shm_file(self):
        """Find the squeezelite shared memory file in /dev/shm"""
        files = glob.glob('/dev/shm/squeezelite-*')
        if files:
            print(f"Found Squeezelite shared memory at: {files[0]}")
            return files[0]
        return None

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

            # Autodetect the actual layout. Different Squeezelite forks (like R2)
            # or platforms have different headers.
            # For example, standard Linux 64-bit has a 32-byte header.
            # A specific DietPi x86 version has an 80-byte header with a 52-byte prefix.
            # The actual struct vis_t contains:
            # [sync: 4] [buf_size: 4] [buf_index: 4] [running: 4/1] [rate: 4] [updated: 8/4] [buffer: buf_size*2]

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

            # If buf_index is very small, we might not have enough data to read a frame
            samples_to_read = 1024  # Read last 1024 interleaved samples (512 pairs)

            if buf_index < samples_to_read * 2: # 2 bytes per s16_t sample
                start_offset = self.buffer_offset
            else:
                start_offset = self.buffer_offset + (buf_index - (samples_to_read * 2))

            # Ensure we don't read past the file limit
            file_size = self.mmap_obj.size()
            if start_offset + (samples_to_read * 2) > file_size:
                # Re-connect or reset if size is weird
                return self._zero_levels()

            self.mmap_obj.seek(start_offset)
            raw_samples = self.mmap_obj.read(samples_to_read * 2)

            num_samples = len(raw_samples) // 2
            if num_samples == 0:
                return self._zero_levels()

            if np is not None:
                dop_stereo = self._decode_dop(raw_samples, num_samples)
                if dop_stereo is not None:
                    left_env, right_env = dop_stereo
                    bars_per_channel = max(1, self.num_bars // 2)
                    return (self._bucket_rms(left_env, bars_per_channel),
                            self._bucket_rms(right_env, bars_per_channel))

                # Vectorised RMS — ~10x cheaper than the Python loop at 30 fps.
                buf = np.frombuffer(raw_samples, dtype='<i2', count=num_samples)
                return self._stereo_levels_from_values(buf.astype(np.float64))

            # Pure-Python fallback (numpy not installed).
            samples = struct.unpack(f'<{num_samples}h', raw_samples)
            dop_stereo = self._decode_dop_py(samples)
            if dop_stereo is not None:
                left_env, right_env = dop_stereo
                bars_per_channel = max(1, self.num_bars // 2)
                return (self._bucket_rms_py(left_env, bars_per_channel),
                        self._bucket_rms_py(right_env, bars_per_channel))
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

    def _decimate_dop_bytes(self, data_bytes):
        """Unpack a single channel's DSD PDM bytes and decimate them into a
        coarse PCM-like envelope. Returns None if there aren't enough bits
        for even one decimated sample."""
        bits = np.unpackbits(data_bytes).astype(np.float64) * 2.0 - 1.0
        usable_bits = (bits.size // _DSD_DECIMATE_BLOCK) * _DSD_DECIMATE_BLOCK
        if usable_bits == 0:
            return None
        decimated = bits[:usable_bits].reshape(-1, _DSD_DECIMATE_BLOCK).mean(axis=1)
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

        usable = (len(bits) // _DSD_DECIMATE_BLOCK) * _DSD_DECIMATE_BLOCK
        if usable == 0:
            return None
        decimated = []
        for i in range(0, usable, _DSD_DECIMATE_BLOCK):
            chunk = bits[i:i + _DSD_DECIMATE_BLOCK]
            avg = sum(chunk) / _DSD_DECIMATE_BLOCK
            decimated.append(max(-32767.0, min(32767.0, avg * _DSD_FS_GAIN * 32767.0)))
        return decimated


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


async def vu_meter_server(websocket, path):
    """WebSocket handler to stream VU meter data"""
    print(f"Client connected to VU meter stream")
    viz = SqueezeliteVisualizer()
    bt_tap = BluetoothTapReader()

    # Send empty data initially
    empty_left, empty_right = viz._zero_levels()

    def _payload(stereo_levels, active):
        left, right = stereo_levels
        return json.dumps({"levels_l": left, "levels_r": right, "active": active})

    try:
        while True:
            # 30 fps = ~0.033s sleep
            await asyncio.sleep(0.033)

            levels = viz.read_audio_data()
            # same_index_count > 10 means squeezelite's buffer isn't moving
            # (paused/stopped), same threshold read_audio_data itself uses to
            # force levels to zero — treat that as "nothing playing here" and
            # give the Bluetooth tap a chance instead of just showing zeros.
            sq_active = levels is not None and viz.same_index_count <= 10

            if sq_active:
                active = any(l > 0 for l in levels[0]) or any(l > 0 for l in levels[1])
                await websocket.send(_payload(levels, active))
                continue

            bt_levels = bt_tap.read_levels(viz)
            if bt_levels is not None:
                active = any(l > 0 for l in bt_levels[0]) or any(l > 0 for l in bt_levels[1])
                await websocket.send(_payload(bt_levels, active))
                continue

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