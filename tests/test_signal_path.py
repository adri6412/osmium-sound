"""Tests for hifi_signal_path.py — Now Playing's signal path: what the DAC is
really fed (from hw_params) and the verdict drawn from it.

Hermetic: /proc/asound is a temporary tree.

Run with:  python3 tests/test_signal_path.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import hifi_signal_path as sp  # noqa: E402
import hifi_squeezelite as sq  # noqa: E402

MAC = '02:ad:c8:31:53:44'
ZONE_MAC = '02:11:22:33:44:55'
CARDS = """ 0 [PCH            ]: HDA-Intel - HDA Intel PCH
                      HDA Intel PCH at 0x81410000 irq 126
 1 [D50s           ]: USB-Audio - D50s
                      Topping D50s at usb-0000:00:14.0-1, high speed
"""


def hw(fmt, rate):
    return f"access: MMAP_INTERLEAVED\nformat: {fmt}\nsubformat: STD\nchannels: 2\nrate: {rate} ({rate}/1)\nperiod_size: 882\n"


_TREES = []


def tearDownModule():
    for d in _TREES:
        d.cleanup()


class Tree:
    """A /proc/asound with the D50s on card1 (USB) and HDMI on card0."""

    def __init__(self, d50s_hw='closed', hdmi_hw='closed'):
        self.dir = tempfile.TemporaryDirectory()
        _TREES.append(self.dir)
        r = self.root = self.dir.name
        with open(os.path.join(r, 'cards'), 'w') as f:
            f.write(CARDS)
        for num, name, dev, text, info in ((1, 'D50s', 0, d50s_hw, 'id: USB Audio\nname: USB Audio\n'),
                                           (0, 'PCH', 3, hdmi_hw, 'id: HDMI 0\nname: HDMI 0\n')):
            card = os.path.join(r, f'card{num}')
            os.makedirs(os.path.join(card, f'pcm{dev}p', 'sub0'))
            with open(os.path.join(card, f'pcm{dev}p', 'sub0', 'hw_params'), 'w') as f:
                f.write(text)
            with open(os.path.join(card, f'pcm{dev}p', 'info'), 'w') as f:
                f.write(info)
            os.symlink(f'card{num}', os.path.join(r, name))
        open(os.path.join(r, 'card1', 'usbid'), 'w').close()

    def describe(self, source, lyrion=None, player=MAC, main=None, zones=(), fmt='u32be'):
        main = sq.normalize(dict({'mac': MAC, 'output': 'hw:CARD=D50s,DEV=0'}, **(main or {})))
        return sp.describe(source, lyrion or {}, player, main, list(zones),
                           probe_fn=lambda dev: fmt if 'D50s' in dev else sq.PCM_ONLY,
                           hw_fn=lambda dev: sp.read_hw(dev, self.root),
                           card_fn=lambda dev: sp.card_info(dev, self.root))


FLAC_96 = {'type': 'flc', 'rate': '96000', 'bits': '24'}
DSF_64 = {'type': 'dsf', 'rate': '2822400', 'bits': '1'}


class ParseTest(unittest.TestCase):
    def test_closed(self):
        self.assertIsNone(sp.parse_hw_params('closed\n'))

    def test_native_dsd(self):
        d = sp.describe_hw(sp.parse_hw_params(hw('DSD_U32_BE', 88200)), 'native')
        self.assertEqual((d['kind'], d['dsd'], d['bit_rate']), ('dsd', 'DSD64', 2822400))

    def test_dsd_names(self):
        self.assertEqual(sp.dsd_name(5644800), 'DSD128')
        self.assertEqual(sp.dsd_name(6144000), 'DSD128')
        self.assertEqual(sp.dsd_name(11289600), 'DSD256')

    def test_pcm_bits(self):
        self.assertEqual(sp.pcm_bits('S32_LE'), 32)
        self.assertEqual(sp.pcm_bits('S24_3LE'), 24)
        self.assertEqual(sp.pcm_bits('S16_LE'), 16)

    def test_card_info(self):
        t = Tree()
        self.assertEqual(sp.card_info('hw:CARD=D50s,DEV=0', t.root),
                         {'card': 'D50s', 'name': 'Topping D50s', 'kind': 'usb'})
        self.assertEqual(sp.card_info('hw:CARD=PCH,DEV=3', t.root)['kind'], 'hdmi')
        self.assertEqual(sp.card_info('default', t.root)['kind'], 'unknown')


class QualityTest(unittest.TestCase):
    def test_lossless_codecs(self):
        for ty in ('flc', 'wav', 'aif', 'alc', 'wvp', 'ape', 'wmal', 'ogf'):
            self.assertEqual(sp.source_quality(ty, False), 'lossless', ty)

    def test_lossy_codecs(self):
        for ty in ('mp3', 'aac', 'mp4', 'm4a', 'ogg', 'opus', 'wma', 'mpc'):
            self.assertEqual(sp.source_quality(ty, False), 'lossy', ty)

    def test_dsd_is_lossless(self):
        self.assertEqual(sp.source_quality('dsf', True), 'lossless')

    def test_unknown_or_empty_says_nothing(self):
        # a radio whose codec Lyrion does not name plainly must NOT read lossless
        for ty in ('', 'wmadrm', 'unknown', 'http'):
            self.assertEqual(sp.source_quality(ty, False), '', ty)

    def test_describe_passes_quality_through(self):
        r = Tree(hw('S32_LE', 96000)).describe(FLAC_96)
        self.assertEqual(r['source']['quality'], 'lossless')
        r = Tree(hw('S16_LE', 44100)).describe({'type': 'aac', 'rate': '44100', 'bits': '16'})
        self.assertEqual(r['source']['quality'], 'lossy')
        r = Tree(hw('S16_LE', 44100)).describe({'type': '', 'rate': '44100', 'bits': '16', 'remote': True})
        self.assertEqual(r['source']['quality'], '')


class VerdictTest(unittest.TestCase):
    def test_bitperfect_pcm(self):
        r = Tree(hw('S32_LE', 96000)).describe(FLAC_96)
        self.assertEqual(r['verdict'], 'bitperfect')
        self.assertEqual(r['hw']['kind'], 'pcm')
        self.assertEqual(r['dac']['name'], 'Topping D50s')

    def test_resampled(self):
        r = Tree(hw('S32_LE', 48000)).describe(FLAC_96)
        self.assertEqual(r['verdict'], 'processed')
        self.assertIn('resampled', r['changes'])

    def test_replaygain_and_volume(self):
        r = Tree(hw('S32_LE', 96000)).describe(FLAC_96, {'replaygain': True, 'digital_volume': True, 'volume': '60'})
        self.assertEqual(r['changes'], ['replaygain', 'volume'])

    def test_volume_at_100_is_untouched(self):
        r = Tree(hw('S32_LE', 96000)).describe(FLAC_96, {'digital_volume': True, 'volume': '100'})
        self.assertEqual(r['verdict'], 'bitperfect')

    def test_hardware_volume_is_untouched(self):
        r = Tree(hw('S32_LE', 96000)).describe(FLAC_96, {'digital_volume': True, 'volume': '40'},
                                               main={'volume': 'hardware', 'mixer': 'PCM'})
        self.assertEqual(r['verdict'], 'bitperfect')
        self.assertEqual(r['player']['volume'], 'hardware')

    def test_native_dsd(self):
        r = Tree(hw('DSD_U32_BE', 88200)).describe(DSF_64, main={'dsd': 'native'})
        self.assertEqual(r['verdict'], 'bitperfect')
        self.assertEqual((r['hw']['kind'], r['hw']['dsd']), ('dsd', 'DSD64'))

    def test_volume_does_not_touch_dsd(self):
        r = Tree(hw('DSD_U32_BE', 88200)).describe(DSF_64, {'digital_volume': True, 'volume': '40'})
        self.assertEqual(r['verdict'], 'bitperfect')
        self.assertEqual(r['player']['volume'], 'software')

    def test_dop(self):
        r = Tree(hw('S32_LE', 176400)).describe(DSF_64, main={'dsd': 'dop'}, fmt='dop')
        self.assertEqual(r['verdict'], 'bitperfect')
        self.assertEqual((r['hw']['kind'], r['hw']['dsd']), ('dop', 'DSD64'))

    def test_dsd_to_pcm(self):
        r = Tree(hw('S32_LE', 176400)).describe(DSF_64, main={'dsd': 'off'})
        self.assertEqual(r['verdict'], 'processed')
        self.assertIn('dsdToPcm', r['changes'])
        self.assertEqual(r['hw']['kind'], 'pcm')

    def test_pcm_to_dsd_is_converted(self):
        orig = sq.tools_present
        sq.tools_present = lambda: True
        try:
            r = Tree(hw('DSD_U32_BE', 88200)).describe(FLAC_96, main={'pcm2dsd': 'dsd64'})
        finally:
            sq.tools_present = orig
        self.assertEqual(r['verdict'], 'converted')
        self.assertEqual(r['changes'], ['pcmToDsd'])
        self.assertEqual(r['player']['pcm2dsd']['state'], 'active')

    def test_pcm_to_dsd_on_the_player_side(self):
        # another Lyrion: the player converts after its own volume, and a DSD
        # track goes through PCM on the way
        orig = (sq.tools_present, sq.player_side_present)
        sq.tools_present = sq.player_side_present = lambda: True
        try:
            t = Tree(hw('DSD_U32_BE', 88200))
            main = {'pcm2dsd': 'dsd64', 'server': '192.168.1.9', 'volume': 'hardware', 'mixer': 'PCM'}
            r = t.describe(FLAC_96, {'digital_volume': True, 'volume': '100'}, main=main)
            self.assertEqual((r['verdict'], r['changes']), ('converted', ['pcmToDsd']))
            self.assertEqual((r['player']['pcm2dsd']['state'], r['player']['volume']), ('player', 'software'))
            r = t.describe(FLAC_96, {'digital_volume': True, 'volume': '40'}, main=main)
            self.assertEqual((r['verdict'], r['changes']), ('processed', ['pcmToDsd', 'volume']))
            r = t.describe(DSF_64, main=main)
            self.assertEqual((r['verdict'], r['changes']), ('processed', ['dsdToPcm', 'pcmToDsd']))
        finally:
            sq.tools_present, sq.player_side_present = orig

    def test_idle(self):
        r = Tree().describe(FLAC_96)
        self.assertEqual(r['verdict'], 'idle')
        self.assertIsNone(r['hw'])

    def test_other_device(self):
        r = Tree().describe(FLAC_96, player='aa:bb:cc:dd:ee:ff')
        self.assertFalse(r['local'])
        self.assertEqual(r['verdict'], 'unknown')
        self.assertNotIn('hw', r)

    def test_zone(self):
        zone = {'mac': ZONE_MAC, 'output': 'hw:CARD=PCH,DEV=3', 'name': 'Kitchen'}
        r = Tree(hdmi_hw=hw('S16_LE', 44100)).describe({'type': 'flc', 'rate': '44100', 'bits': '16'},
                                                         player=ZONE_MAC, zones=[zone])
        self.assertEqual(r['zone'], 'Kitchen')
        self.assertEqual(r['dac']['kind'], 'hdmi')
        self.assertEqual(r['verdict'], 'bitperfect')


if __name__ == '__main__':
    unittest.main()
