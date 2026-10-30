"""Tests for hifi-upsample.py, the PCM upsampling wrapper Lyrion runs as the
last step of its transcoding pipe. Mirror of TestWrapper in
test_zones_pcm2dsd.py. Hermetic: no sox_ng is actually run except in
test_run_streams_through_sox, which is skipped when sox_ng is missing.

Run with:  python3 tests/test_upsample_wrapper.py
"""
import importlib.util
import io
import json
import os
import shutil
import struct
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
WRAPPER = os.path.join(ROOT, 'distro', 'config', 'includes.chroot', 'usr', 'local', 'sbin', 'hifi-upsample.py')
MAC = '02:aa:bb:cc:dd:ee'


def load_wrapper():
    spec = importlib.util.spec_from_file_location('hifi_upsample', WRAPPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def wav_header(rate, channels=2, bits=16):
    """A canonical 44-byte WAV header for a stream of `rate` Hz, no data."""
    byte_rate = rate * channels * bits // 8
    block = channels * bits // 8
    return (b'RIFF' + struct.pack('<I', 36) + b'WAVE'
            + b'fmt ' + struct.pack('<IHHIIHH', 16, 1, channels, rate, byte_rate, block, bits)
            + b'data' + struct.pack('<I', 0))


class TestTarget(unittest.TestCase):
    def setUp(self):
        self.w = load_wrapper()

    def test_integer_multiples_stay_in_family(self):
        t = self.w.target_rate
        self.assertEqual(t('x2', 0, 44100), 88200)
        self.assertEqual(t('x4', 0, 44100), 176400)
        self.assertEqual(t('x2', 0, 48000), 96000)
        self.assertEqual(t('x4', 0, 48000), 192000)
        self.assertEqual(t('x4', 0, 96000), 384000)       # already 48 kHz family

    def test_max_climbs_to_the_cap(self):
        t = self.w.target_rate
        self.assertEqual(t('max', 192000, 44100), 176400)  # top 44.1 multiple ≤ 192k
        self.assertEqual(t('max', 192000, 48000), 192000)  # top 48 multiple ≤ 192k
        self.assertEqual(t('max', 0, 44100), 705600)       # no cap: family ceiling under 768k
        self.assertEqual(t('max', 0, 48000), 768000)

    def test_no_change_when_nothing_larger_fits(self):
        t = self.w.target_rate
        self.assertEqual(t('x2', 80000, 44100), 0)         # 88.2k×2 over an 80k cap
        self.assertEqual(t('x2', 88200, 44100), 88200)     # cap exactly fits the x2 target
        self.assertEqual(t('max', 44100, 44100), 0)        # cap equals the source
        self.assertEqual(t('x2', 0, 0), 0)                 # unknown source rate

    def test_odd_rate_falls_back_to_48_family(self):
        self.assertEqual(self.w.family_base(37800), 48000)
        self.assertEqual(self.w.target_rate('x2', 0, 37800), 75600)


class TestSettings(unittest.TestCase):
    def setUp(self):
        self.w = load_wrapper()
        self.dir = tempfile.mkdtemp(prefix='ups-')
        self.map = os.path.join(self.dir, 'upsample.json')

    def test_settings(self):
        with open(self.map, 'w') as f:
            json.dump({MAC: {'mult': 'max', 'cap': 192000},
                       '02:00:00:00:00:01': {'mult': 'bogus'}}, f)
        self.assertEqual(self.w.settings_for('02-aa-bb-cc-dd-ee', self.map), ('max', 192000))
        self.assertEqual(self.w.settings_for('02-00-00-00-00-01', self.map), ('x2', 0))
        self.assertEqual(self.w.settings_for('02-99-99-99-99-99', self.map), ('x2', 0))
        self.assertEqual(self.w.settings_for(MAC, os.path.join(self.dir, 'none')), ('x2', 0))


class TestArgv(unittest.TestCase):
    def setUp(self):
        self.w = load_wrapper()

    def test_wav_argv_outputs_flac(self):
        a = self.w.sox_argv('wav', 176400, '/x/sox_ng')
        self.assertEqual(a[0], '/x/sox_ng')
        self.assertEqual(a[a.index('-t') + 1], 'wav')
        self.assertIn('--ignore-length', a)
        i = a.index('flac')
        self.assertEqual(a[i + 1], '-')                    # FLAC to stdout
        self.assertEqual(a[i + 2:], ['channels', '2', 'rate', '-v', '176400'])

    def test_raw_argv_is_44100(self):
        r = self.w.sox_argv('raw', 88200)
        self.assertEqual(r[r.index('-t') + 1], 'raw')
        self.assertEqual(r[r.index('-r') + 1], '44100')
        self.assertIn('88200', r)

    def test_target_zero_omits_the_rate_effect(self):
        a = self.w.sox_argv('wav', 0)
        self.assertNotIn('rate', a)
        self.assertEqual(a[-2:], ['channels', '2'])

    def test_usage(self):
        self.assertEqual(self.w.main(['x']), 2)
        self.assertEqual(self.w.main(['x', MAC, 'mp3']), 2)


class TestReadWavRate(unittest.TestCase):
    def setUp(self):
        self.w = load_wrapper()

    def test_reads_rate_and_forwards_bytes(self):
        head = wav_header(96000)
        rate, consumed = self.w.read_wav_rate(io.BytesIO(head + b'PCMDATA'))
        self.assertEqual(rate, 96000)
        self.assertTrue(head.startswith(consumed[:12]))    # it kept the RIFF header
        self.assertTrue(consumed.startswith(b'RIFF'))

    def test_extra_chunk_before_fmt_is_skipped(self):
        junk = b'LIST' + struct.pack('<I', 4) + b'INFO'
        stream = io.BytesIO(b'RIFF' + struct.pack('<I', 0) + b'WAVE' + junk + wav_header(44100)[12:])
        rate, _ = self.w.read_wav_rate(stream)
        self.assertEqual(rate, 44100)

    def test_not_wav_returns_none(self):
        rate, consumed = self.w.read_wav_rate(io.BytesIO(b'OggS' + b'\x00' * 40))
        self.assertIsNone(rate)


def _fake_exec(path, body):
    """Write an executable shell stub at `path`."""
    with open(path, 'w') as f:
        f.write('#!/bin/sh\n' + body)
    os.chmod(path, 0o755)


# A fake sox whose `--help` does NOT list flac (like the project's sox_ng): it
# echoes a marker then copies stdin, so the stream is recognisable downstream.
_FAKE_SOX_NO_FLAC = (
    'if [ "$1" = "--help" ]; then\n'
    '  echo "AUDIO FILE FORMATS: 8svx aif aiff au dsf raw wav"\n'
    '  exit 0\n'
    'fi\n'
    'printf SOXWAV; cat\n'
)
# A fake sox that DOES carry the flac handler and, on a real run, emits a FLAC
# magic header itself (single-process fast path, no external encoder).
_FAKE_SOX_WITH_FLAC = (
    'if [ "$1" = "--help" ]; then\n'
    '  echo "AUDIO FILE FORMATS: 8svx aif flac wav"\n'
    '  exit 0\n'
    'fi\n'
    'printf fLaC; cat\n'
)
# A fake standalone flac CLI: prepends the FLAC magic to whatever sox piped in.
_FAKE_FLAC = 'printf fLaC; cat\n'


class TestEncoderSelection(unittest.TestCase):
    """sox_ng cannot write FLAC, so run() must resample with sox and encode the
    FLAC output with the `flac` CLI; a FLAC-capable sox takes a single-process
    fast path instead. Both must yield a FLAC stream (magic 'fLaC')."""

    def setUp(self):
        self.w = load_wrapper()
        self.dir = tempfile.mkdtemp(prefix='ups-enc-')
        self.wav = wav_header(44100) + b'\x00' * 32

    def _run_capture(self, sox):
        r, wr = os.pipe()
        saved = os.dup(1)
        os.dup2(wr, 1)
        os.close(wr)
        try:
            rc = self.w.run('wav', 'x2', 0, stdin=io.BytesIO(self.wav), sox=sox)
        finally:
            os.dup2(saved, 1)
            os.close(saved)
        out = b''
        while True:
            chunk = os.read(r, 1 << 16)
            if not chunk:
                break
            out += chunk
        os.close(r)
        return rc, out

    def test_sox_without_flac_uses_flac_cli(self):
        sox = os.path.join(self.dir, 'sox_ng')
        flac = os.path.join(self.dir, 'flac')
        _fake_exec(sox, _FAKE_SOX_NO_FLAC)
        _fake_exec(flac, _FAKE_FLAC)
        self.w.FLAC_BIN = flac                       # make find_flac() pick the fake
        self.assertFalse(self.w.sox_has_flac(sox))
        rc, out = self._run_capture(sox)
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith(b'fLaC'), out[:16])
        self.assertIn(b'SOXWAV', out)                # sox ran before the encoder

    def test_sox_with_flac_single_process(self):
        sox = os.path.join(self.dir, 'sox')
        _fake_exec(sox, _FAKE_SOX_WITH_FLAC)
        self.w.FLAC_BIN = os.path.join(self.dir, 'nonexistent-flac')
        self.assertTrue(self.w.sox_has_flac(sox))
        rc, out = self._run_capture(sox)
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith(b'fLaC'), out[:16])
        self.assertNotIn(b'SOXWAV', out)             # the fast-path sox, not the no-flac one

    def test_no_encoder_at_all_errors(self):
        sox = os.path.join(self.dir, 'sox_ng')
        _fake_exec(sox, _FAKE_SOX_NO_FLAC)
        self.w.FLAC_BIN = os.path.join(self.dir, 'nonexistent-flac')
        orig = self.w.shutil.which
        self.w.shutil.which = lambda _n: None        # no flac CLI on PATH either
        try:
            rc = self.w.run('wav', 'x2', 0, stdin=io.BytesIO(self.wav), sox=sox)
        finally:
            self.w.shutil.which = orig
        self.assertEqual(rc, 3)


@unittest.skipUnless(shutil.which('sox') or os.path.exists('/usr/local/bin/sox_ng'),
                     'no SoX to run end to end')
class TestRunEndToEnd(unittest.TestCase):
    def setUp(self):
        self.w = load_wrapper()
        self.sox = '/usr/local/bin/sox_ng' if os.path.exists('/usr/local/bin/sox_ng') else shutil.which('sox')

    def test_run_streams_through_sox(self):
        # a real 44.1 kHz WAV body → sox upsamples x2 → a FLAC stream on stdout
        import subprocess
        tmp = tempfile.mkdtemp(prefix='ups-e2e-')
        wav = os.path.join(tmp, 'in.wav')
        subprocess.run([self.sox, '-q', '-n', '-r', '44100', '-b', '16', '-c', '2', wav,
                        'synth', '0.2', 'sine', '440'], check=True, timeout=30)
        with open(wav, 'rb') as f:
            data = f.read()
        out = os.path.join(tmp, 'out.flac')
        with open(out, 'wb') as sink:
            # feed the wav through run() with sox writing to our sink via a small shim
            proc_stdin = io.BytesIO(data)
            rc = self._run_capture(proc_stdin, sink)
        self.assertEqual(rc, 0)
        info = subprocess.run([self.sox, '--info', '-r', out], capture_output=True, text=True, timeout=30)
        self.assertEqual(info.stdout.strip(), '88200')

    def _run_capture(self, stdin, sink):
        import subprocess
        src, head = self.w.read_wav_rate(stdin)
        target = self.w.target_rate('x2', 0, src)
        proc = subprocess.Popen(self.w.sox_argv('wav', target, self.sox),
                                stdin=subprocess.PIPE, stdout=sink)
        proc.stdin.write(head)
        shutil.copyfileobj(stdin, proc.stdin, length=1 << 16)
        proc.stdin.close()
        return proc.wait()


if __name__ == '__main__':
    unittest.main()
