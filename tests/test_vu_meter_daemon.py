"""Tests for vu_meter_daemon.py's reading of squeezelite's visualiser segment,
against a fake /dev/shm file built with squeezelite's real vis_t layout
(output_vis.c, x86-64 glibc): a 56-byte pthread_rwlock_t, then
u32 buf_size @56, u32 buf_index @60, bool running @64, u32 rate @68,
time_t updated @72 and s16_t buffer[16384] @80. buf_index counts s16 samples.

Both the numpy path (what the image runs) and the pure-Python fallback are
exercised; the numpy cases are skipped where numpy isn't installed.

Run with:  python tests/test_vu_meter_daemon.py
"""
import math
import os
import shutil
import struct
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

# The WebSocket server isn't under test; the daemon only needs the name at import.
sys.modules.setdefault('websockets', types.ModuleType('websockets'))

import vu_meter_daemon as vu  # noqa: E402

VIS_BUF_SIZE = 16384
HEADER = 80
NP = vu.np


def write_segment(path, buffer, buf_index, rate=44100, running=True):
    """A vis_t exactly as squeezelite lays it out on x86-64."""
    assert len(buffer) == VIS_BUF_SIZE
    header = bytes(56) + struct.pack('<IIB3xIq', VIS_BUF_SIZE, buf_index, running, rate, 0)
    assert len(header) == HEADER
    with open(path, 'wb') as f:
        f.write(header + struct.pack(f'<{VIS_BUF_SIZE}h', *buffer))


def vis_export(buffer, buf_index, frames):
    """output_vis.c's _vis_export: write (L, R) s32 frames as their top 16 bits
    at buf_index, wrapping at VIS_BUF_SIZE. Returns the new buf_index."""
    i = buf_index
    for left, right in frames:
        buffer[i] = struct.unpack('<h', struct.pack('<H', (left >> 16) & 0xFFFF))[0]
        buffer[i + 1] = struct.unpack('<h', struct.pack('<H', (right >> 16) & 0xFFFF))[0]
        i += 2
        if i == VIS_BUF_SIZE:
            i = 0
    return i


def sdm(signal):
    """Second-order delta-sigma modulator: floats in [-1, 1] -> bits {0, 1}."""
    v1 = v2 = 0.0
    y = 1.0
    out = []
    for s in signal:
        v1 += s - y
        v2 += v1 - y
        y = 1.0 if v2 >= 0 else -1.0
        out.append(1 if y > 0 else 0)
    return out


def dsd_u32_words(bits):
    """dsd.c's DSD_U32 packing: four bytes per word, oldest bit in the MSB."""
    words = []
    for w in range(len(bits) // 32):
        val = 0
        for b in bits[w * 32:(w + 1) * 32]:
            val = (val << 1) | b
        words.append(struct.unpack('<i', struct.pack('<I', val))[0])
    return words


class VisSegmentTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='hifi-vu-daemon-test-')
        self.path = os.path.join(self.tmp, 'squeezelite-00:11:22:33:44:55')
        self._glob = vu.glob.glob
        vu.glob.glob = lambda pattern: [self.path]
        self.viz = None

    def tearDown(self):
        vu.glob.glob = self._glob
        vu.np = NP
        if self.viz is not None:
            self.viz.disconnect()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def levels(self, buffer, buf_index, rate=44100, numpy=True):
        if numpy and NP is None:
            self.skipTest('numpy not installed')
        vu.np = NP if numpy else None
        if self.viz is not None:
            self.viz.disconnect()
        write_segment(self.path, buffer, buf_index, rate)
        if self.viz is None:
            self.viz = vu.SqueezeliteVisualizer()
        return self.viz.read_audio_data()

    # -- buf_index is a sample index ------------------------------------

    def test_layout_detected(self):
        self.levels([0] * VIS_BUF_SIZE, 4096, numpy=False)
        self.assertEqual(self.viz.buffer_offset, HEADER)
        self.assertEqual(self.viz.index_offset, 60)
        self.assertEqual(self.viz.buf_size, VIS_BUF_SIZE)
        self.assertEqual(self.viz._read_rate(), 44100)

    def _latest_only(self, buf_index, numpy):
        """Only the 512 frames just before buf_index carry signal, left only;
        everything else in the ring is silence."""
        buffer = [0] * VIS_BUF_SIZE
        start = (buf_index - 1024) % VIS_BUF_SIZE
        frames = [(int(0.9 * 2147483647 * math.sin(2 * math.pi * n / 64)), 0) for n in range(512)]
        self.assertEqual(vis_export(buffer, start, frames), buf_index)
        return self.levels(buffer, buf_index, numpy=numpy)

    def _assert_left_only(self, left, right):
        self.assertTrue(all(lv > 80 for lv in left), left)
        self.assertEqual(right, [0] * len(right))

    def test_reads_newest_samples(self):
        # The old byte-offset reading looked at samples 3000-4024 here: silence.
        for numpy in (True, False):
            with self.subTest(numpy=numpy):
                self._assert_left_only(*self._latest_only(8048, numpy))

    def test_window_never_swaps_channels(self):
        # 6002 - 2048 bytes = sample 1977, an R slot: the old reading swapped L and R.
        for buf_index in (6002, 6004, 9998, 16382):
            for numpy in (True, False):
                with self.subTest(buf_index=buf_index, numpy=numpy):
                    self._assert_left_only(*self._latest_only(buf_index, numpy))

    def test_window_wraps_around_the_ring(self):
        for buf_index in (0, 2, 200, 1022):
            for numpy in (True, False):
                with self.subTest(buf_index=buf_index, numpy=numpy):
                    self._assert_left_only(*self._latest_only(buf_index, numpy))

    def test_out_of_range_index_reads_as_silence(self):
        buffer = [20000] * VIS_BUF_SIZE
        left, right = self.levels(buffer, VIS_BUF_SIZE + 2, numpy=False)
        self.assertEqual(left + right, [0] * 32)

    # -- native DSD ------------------------------------------------------

    def _dsd(self, amplitude, frames=512):
        bits = sdm([amplitude * math.sin(2 * math.pi * 1000 * n / 2822400)
                    for n in range(frames * 32)])
        words = dsd_u32_words(bits)
        buffer = [0] * VIS_BUF_SIZE
        idx = vis_export(buffer, 4000, list(zip(words, words)))
        return buffer, idx

    def test_native_dsd_silence_reads_as_silence(self):
        # dsd.c pads with 0x69 bytes: as PCM, a constant -1.7 dBFS on both needles.
        buffer = [0x6969] * VIS_BUF_SIZE
        for numpy in (True, False):
            with self.subTest(numpy=numpy):
                left, right = self.levels(buffer, 6000, rate=88200, numpy=numpy)
                self.assertEqual(left + right, [0] * 32)
                self.viz._native_dsd_rate = None

    def test_native_dsd_is_decoded_not_read_as_pcm(self):
        loud, idx = self._dsd(0.5)
        quiet, _ = self._dsd(0.003)
        for numpy in (True, False):
            with self.subTest(numpy=numpy):
                vu.np = NP if numpy else None
                # As PCM these are near full scale whatever the music does.
                raw = self.viz_pcm_levels(quiet, idx)
                self.assertGreater(min(raw[0]), 90)
                # Quiet first, so it is recognised without the hysteresis.
                quiet_l, quiet_r = self.levels(quiet, idx, rate=88200, numpy=numpy)
                self.assertEqual(self.viz._native_dsd_rate, 88200)
                loud_l, loud_r = self.levels(loud, idx, rate=88200, numpy=numpy)
                self.assertEqual(self.viz._native_dsd_rate, 88200)
                # A coarse level: loud at the top, -50 dB well below it.
                self.assertGreater(min(loud_l), 90)
                self.assertEqual(loud_l, loud_r)
                self.assertLess(sum(quiet_l) / len(quiet_l), 50)
                self.assertGreater(sum(loud_l) / 16, sum(quiet_l) / 16 + 40)
                self.viz._native_dsd_rate = None

    def viz_pcm_levels(self, buffer, buf_index):
        viz = vu.SqueezeliteVisualizer()
        values = [buffer[(buf_index - 1024 + i) % VIS_BUF_SIZE] for i in range(1024)]
        return viz._stereo_levels_from_values_py(values)

    def test_hires_pcm_stays_pcm(self):
        for freq in (1000, 10000):
            frames = [(int(0.9 * 2147483647 * math.sin(2 * math.pi * freq * n / 88200)),) * 2
                      for n in range(512)]
            buffer = [0] * VIS_BUF_SIZE
            idx = vis_export(buffer, 3000, frames)
            for numpy in (True, False):
                with self.subTest(freq=freq, numpy=numpy):
                    left, right = self.levels(buffer, idx, rate=88200, numpy=numpy)
                    self.assertIsNone(self.viz._native_dsd_rate)
                    expected = self.viz_pcm_levels(buffer, idx)[0]
                    for got, want in zip(left, expected):
                        self.assertAlmostEqual(got, want, delta=1)

    def test_dsd_check_skipped_at_cd_rates(self):
        # White noise at 44.1 kHz would pass the statistics; the rate gate stops it.
        import random
        rnd = random.Random(7)
        buffer = [rnd.randint(-30000, 30000) for _ in range(VIS_BUF_SIZE)]
        for numpy in (True, False):
            with self.subTest(numpy=numpy):
                left, right = self.levels(buffer, 6000, rate=44100, numpy=numpy)
                self.assertIsNone(self.viz._native_dsd_rate)
                self.assertGreater(min(left), 90)

    def test_dop_still_decoded(self):
        # DoP: update_dop writes the 0x05/0xFA marker into bits 24-31 in place
        # before _vis_export, so entries are marker<<8 | first DSD byte.
        buffer = [0] * VIS_BUF_SIZE
        for i in range(0, VIS_BUF_SIZE, 2):
            marker = 0x05 if (i // 2) % 2 == 0 else 0xFA
            buffer[i] = buffer[i + 1] = struct.unpack('<h', struct.pack('<H', marker << 8 | 0x69))[0]
        for numpy in (True, False):
            with self.subTest(numpy=numpy):
                left, right = self.levels(buffer, 6000, rate=176400, numpy=numpy)
                self.assertEqual(left + right, [0] * 32)
                self.assertIsNone(self.viz._native_dsd_rate)


if __name__ == '__main__':
    unittest.main()
