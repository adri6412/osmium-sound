"""Tests for the portable Osmium Convert helper (Bin/osmium-convert), the SoX
wrapper the OsmiumConvert LMS plugin runs as the last step of transcoding. The
PCM-upsampling path must produce a FLAC stream even when the resampling SoX
(the project's sox_ng) has no FLAC handler: it resamples to WAV and pipes the
output through a standalone `flac` encoder. Hermetic — no real SoX is run.

Run with:  python3 tests/test_osmium_convert.py
"""
import importlib.util
import io
import os
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
HELPER = os.path.join(ROOT, 'distro', 'config', 'includes.chroot', 'usr', 'local',
                      'share', 'osmium', 'lms-plugins', 'OsmiumConvert', 'Bin', 'osmium-convert')


def load_helper():
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader('osmium_convert', HELPER)
    spec = importlib.util.spec_from_loader('osmium_convert', loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _fake_exec(path, body):
    with open(path, 'w') as f:
        f.write('#!/bin/sh\n' + body)
    os.chmod(path, 0o755)


_FAKE_SOX_NO_FLAC = (
    'if [ "$1" = "--help" ]; then\n'
    '  echo "AUDIO FILE FORMATS: 8svx aif au dsf raw wav"\n'
    '  exit 0\n'
    'fi\n'
    'printf SOXWAV; cat\n'
)
_FAKE_SOX_WITH_FLAC = (
    'if [ "$1" = "--help" ]; then\n'
    '  echo "AUDIO FILE FORMATS: 8svx aif flac wav"\n'
    '  exit 0\n'
    'fi\n'
    'printf fLaC; cat\n'
)
_FAKE_FLAC = 'printf fLaC; cat\n'


def wav_header(rate, channels=2, bits=16):
    import struct
    byte_rate = rate * channels * bits // 8
    block = channels * bits // 8
    return (b'RIFF' + struct.pack('<I', 36) + b'WAVE'
            + b'fmt ' + struct.pack('<IHHIIHH', 16, 1, channels, rate, byte_rate, block, bits)
            + b'data' + struct.pack('<I', 0))


class TestFlacCapability(unittest.TestCase):
    def setUp(self):
        self.m = load_helper()
        self.dir = tempfile.mkdtemp(prefix='oc-caps-')

    def test_sox_has_format_parses_help(self):
        sox = os.path.join(self.dir, 'sox')
        _fake_exec(sox, _FAKE_SOX_WITH_FLAC)
        self.assertTrue(self.m.sox_has_format(sox, 'flac'))
        self.assertFalse(self.m.sox_has_format(sox, 'dsf'))
        nf = os.path.join(self.dir, 'sox_ng')
        _fake_exec(nf, _FAKE_SOX_NO_FLAC)
        self.assertFalse(self.m.sox_has_format(nf, 'flac'))

    def test_flac_available_needs_sox_or_flac_cli(self):
        nf = os.path.join(self.dir, 'sox_ng')
        _fake_exec(nf, _FAKE_SOX_NO_FLAC)
        self.m.find_sox = lambda: nf
        self.m.find_flac = lambda: None
        self.assertFalse(self.m.flac_available())
        self.m.find_flac = lambda: os.path.join(self.dir, 'flac')
        self.assertTrue(self.m.flac_available())

    def test_probe_reports_flac(self):
        self.m.find_sox = lambda: None
        self.m.find_sox_ng = lambda: None
        self.m.find_flac = lambda: None
        self.assertIn('flac', self.m.probe())
        self.assertFalse(self.m.probe()['flac'])


class TestPcmArgv(unittest.TestCase):
    def setUp(self):
        self.m = load_helper()

    def test_out_type_parametrised(self):
        a = self.m.pcm_argv('wav', 88200, '/x/sox', out_type='wav')
        out_t = a.index('-t', a.index('-t') + 1)       # the second -t is the output
        self.assertEqual(a[out_t + 1], 'wav')
        self.assertEqual(a[out_t + 2:], ['-', 'channels', '2', 'rate', '-v', '88200'])
        # default output type is FLAC (the rule's transport format)
        self.assertEqual(self.m.pcm_argv('wav', 0, '/x/sox')[-2:], ['channels', '2'])
        self.assertIn('flac', self.m.pcm_argv('wav', 0, '/x/sox'))


class TestRunPcmEncoder(unittest.TestCase):
    """run_pcm must emit a FLAC stream through either path."""

    def setUp(self):
        self.m = load_helper()
        self.dir = tempfile.mkdtemp(prefix='oc-enc-')
        self._saved_stdin = self.m.sys.stdin
        self.m.sys.stdin = types.SimpleNamespace(buffer=io.BytesIO(wav_header(44100) + b'\x00' * 32))

    def tearDown(self):
        self.m.sys.stdin = self._saved_stdin

    def _capture(self):
        r, wr = os.pipe()
        saved = os.dup(1)
        os.dup2(wr, 1)
        os.close(wr)
        try:
            rc = self.m.run_pcm('wav', 'x2', 0)
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

    def test_sox_without_flac_pipes_through_flac_cli(self):
        sox = os.path.join(self.dir, 'sox_ng')
        flac = os.path.join(self.dir, 'flac')
        _fake_exec(sox, _FAKE_SOX_NO_FLAC)
        _fake_exec(flac, _FAKE_FLAC)
        self.m.find_sox = lambda: sox
        self.m.find_flac = lambda: flac
        rc, out = self._capture()
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith(b'fLaC'), out[:16])
        self.assertIn(b'SOXWAV', out)

    def test_sox_with_flac_single_process(self):
        sox = os.path.join(self.dir, 'sox')
        _fake_exec(sox, _FAKE_SOX_WITH_FLAC)
        self.m.find_sox = lambda: sox
        self.m.find_flac = lambda: None
        rc, out = self._capture()
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith(b'fLaC'), out[:16])
        self.assertNotIn(b'SOXWAV', out)

    def test_no_encoder_errors(self):
        sox = os.path.join(self.dir, 'sox_ng')
        _fake_exec(sox, _FAKE_SOX_NO_FLAC)
        self.m.find_sox = lambda: sox
        self.m.find_flac = lambda: None
        self.assertEqual(self.m.run_pcm('wav', 'x2', 0), 3)

    def test_no_sox_errors(self):
        self.m.find_sox = lambda: None
        self.assertEqual(self.m.run_pcm('wav', 'x2', 0), 3)


class TestBrokenDecoderFix(unittest.TestCase):
    """#140: Plugin.pm must always emit wildcard ffmpeg override rules for the
    codecs whose stock decoders are missing/unstable on the image (WMA has no
    wmadec; squeezelite's built-in ffmpeg busy-loops on WMA/ALAC). The caps must
    use file input (F), not stdin (I): a piped MP4/M4A with a trailing moov atom
    (ALAC) cannot be decoded and the player stops after a beat. Device-validated
    on the Dell 2026-11-13; this guards the shape against regression."""

    def setUp(self):
        plugin = os.path.join(ROOT, 'distro', 'config', 'includes.chroot', 'usr',
                              'local', 'share', 'osmium', 'lms-plugins',
                              'OsmiumConvert', 'Plugin.pm')
        with open(plugin) as f:
            self.src = f.read()

    def test_fix_block_is_wired_into_apply(self):
        self.assertIn('_fixBlock() . _ruleBlock', self.src)

    def test_fix_block_covers_the_broken_codecs(self):
        import re
        m = re.search(r'for my \$typ \(qw\(([^)]*)\)\)', self.src)
        self.assertIsNotNone(m, 'could not find the _fixBlock type list')
        types = set(m.group(1).split())
        self.assertTrue({'wma', 'wmal', 'wmap', 'alc', 'alcx'} <= types, types)

    def test_fix_caps_use_file_input_not_stdin(self):
        m = [l for l in self.src.splitlines() if 'FIX_FFMPEG_CAPS' in l and '=' in l]
        self.assertTrue(m, 'FIX_FFMPEG_CAPS not found')
        caps = m[0].split('=', 1)[1]
        self.assertIn('F', caps)
        # The stdin flag (I) reintroduces the ALAC moov-at-end pipe failure.
        self.assertNotRegex(caps, r"#\s*[A-Z]*I[A-Z]*:")

    def test_fix_rule_decodes_with_ffmpeg(self):
        self.assertIn('[ffmpeg]', self.src)
        self.assertRegex(self.src, r"\$dst eq 'flc' \? '-c:a flac")


if __name__ == '__main__':
    unittest.main()
