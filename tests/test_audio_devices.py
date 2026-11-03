"""The Settings → Audio device list and the bundle's audio snapshot.

A real ASUS T101HA (Intel Cherry Trail, rt5645 codec) reached us playing out
of HDMI with no sound from the speakers or the jack, and the owner could not
fix it because the internal codec (chtrt5645) never appeared in the device
list: `aplay -l` prints its playback device with an empty "[]" description,
which the list's regex dropped. The list is now backfilled straight from
/proc/asound so a card with real playback devices can never vanish, and the
bundle now carries `aplay -l` and the mixer state so the next such report is
diagnosable from the zip alone.
"""
import os
import subprocess
import tempfile
import unittest

import api_server as a
import hifi_squeezelite as sq


# aplay -l as a Cherry Trail tablet prints it: HDMI (card 0) has a non-empty
# description the regex matches; the onboard codec (card 1) has an empty "[]"
# the regex skips.
APLAY_L = """**** List of PLAYBACK Hardware Devices ****
card 0: Audio [Intel HDMI/DP LPE Audio], device 0: Intel HDMI/DP LPE Audio [Intel HDMI/DP LPE Audio]
  Subdevices: 1/1
card 0: Audio [Intel HDMI/DP LPE Audio], device 1: Intel HDMI/DP LPE Audio [Intel HDMI/DP LPE Audio]
  Subdevices: 1/1
card 0: Audio [Intel HDMI/DP LPE Audio], device 2: Intel HDMI/DP LPE Audio [Intel HDMI/DP LPE Audio]
  Subdevices: 1/1
card 1: chtrt5645 [chtrt5645], device 0: Audio Port 10EC5645:00-0 []
  Subdevices: 1/1
"""

CARDS = (" 0 [Audio          ]: HdmiLpeAudio - Intel HDMI/DP LPE Audio\n"
         "                      Intel HDMI/DP LPE Audio\n"
         " 1 [chtrt5645      ]: chtrt5645 - chtrt5645\n"
         "                      ASUSTeKCOMPUTERINC.-T101HA-1.0\n")


class DeviceListTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        with open(os.path.join(root, 'cards'), 'w') as f:
            f.write(CARDS)
        # Only the onboard codec gets a card dir with a playback PCM: the HDMI
        # devices are already added from aplay -l, so the backfill must leave
        # them alone and add just chtrt5645.
        os.makedirs(os.path.join(root, 'card1', 'pcm0p'))
        with open(os.path.join(root, 'card1', 'pcm0p', 'info'), 'w') as f:
            f.write('card: 1\ndevice: 0\nstream: PLAYBACK\nid: Audio Port\nname: Audio Port\n')

        self._saved = {}
        self._patch('PROC_ASOUND', root)
        self._patch('_run', lambda cmd, timeout=20: subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout=APLAY_L, stderr=''))
        self._patch('_current_real_dac', lambda: 'default')
        self._patch('_lang', lambda: 'it')
        self._sq_probe = sq.probe
        sq.probe = lambda dev, proc_asound=None: sq.PCM_ONLY

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(a, name, value)
        sq.probe = self._sq_probe
        self.tmp.cleanup()

    def _patch(self, name, value):
        self._saved[name] = getattr(a, name)
        setattr(a, name, value)

    def test_onboard_codec_is_listed_even_with_empty_aplay_description(self):
        ids = [d['id'] for d in a.list_audio_devices()['devices']]
        self.assertIn('hw:CARD=chtrt5645,DEV=0', ids)

    def test_the_codec_keeps_its_proc_asound_name(self):
        dev = next(d for d in a.list_audio_devices()['devices']
                   if d['id'] == 'hw:CARD=chtrt5645,DEV=0')
        self.assertEqual(dev['name'], 'Audio Port')
        self.assertEqual((dev['card'], dev['device']), (1, 0))

    def test_hdmi_devices_are_not_duplicated_by_the_backfill(self):
        ids = [d['id'] for d in a.list_audio_devices()['devices']]
        self.assertEqual(ids.count('hw:CARD=Audio,DEV=0'), 1)
        self.assertEqual(sum(i.startswith('hw:CARD=Audio,') for i in ids), 3)

    def test_default_stays_first(self):
        self.assertEqual(a.list_audio_devices()['devices'][0]['id'], 'default')


class AudioSnapshotTests(unittest.TestCase):
    """The bundle's audio.txt now carries aplay -l and the mixer state."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        with open(os.path.join(self.tmp.name, 'cards'), 'w') as f:
            f.write(CARDS)
        self._saved_proc = a.PROC_ASOUND
        a.PROC_ASOUND = self.tmp.name
        self._saved_run = a.subprocess.run

        def fake_run(cmd, *args, **kwargs):
            out = ''
            if cmd[:2] == ['aplay', '-l']:
                out = APLAY_L
            elif cmd[0] == 'amixer' and cmd[-1] == 'scontents':
                out = "Simple mixer control 'Speaker',0\n  Mono: Playback [off]\n"
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=out, stderr='')

        a.subprocess.run = fake_run

    def tearDown(self):
        a.PROC_ASOUND = self._saved_proc
        a.subprocess.run = self._saved_run
        self.tmp.cleanup()

    def test_aplay_and_mixer_are_in_the_snapshot(self):
        txt = a._support_audio_snapshot()
        self.assertIn('== aplay -l ==', txt)
        self.assertIn('== amixer -c chtrt5645 scontents ==', txt)
        self.assertIn('== amixer -c Audio scontents ==', txt)

    def test_the_loopback_card_is_not_queried(self):
        # It is the DSP bridge, not a real output; no mixer dump for it.
        with open(os.path.join(self.tmp.name, 'cards'), 'a') as f:
            f.write(" 2 [Loopback       ]: Loopback - Loopback\n"
                    "                      Loopback 1\n")
        txt = a._support_audio_snapshot()
        self.assertNotIn('Loopback scontents', txt)


# An onboard codec with its S/PDIF transmitter muted: the usual Daphile → clean
# ALSA state gotcha the digital-switch helpers exist to fix.
SCONTENTS = (
    "Simple mixer control 'Master',0\n"
    "  Capabilities: pvolume pswitch pswitch-joined\n"
    "  Playback channels: Front Left - Front Right\n"
    "  Front Left: Playback 87 [100%] [0.00dB] [on]\n"
    "  Front Right: Playback 87 [100%] [0.00dB] [on]\n"
    "Simple mixer control 'IEC958',0\n"
    "  Capabilities: pswitch pswitch-joined\n"
    "  Playback channels: Mono\n"
    "  Mono: Playback [off]\n"
    "Simple mixer control 'Capture',0\n"
    "  Capabilities: cvolume cswitch\n"
    "  Capture channels: Front Left - Front Right\n"
    "  Front Left: Capture 31 [100%] [on]\n"
)


class MixerSwitchTests(unittest.TestCase):
    """Playback switches of a card: list them, toggle them, and auto-unmute the
    digital (S/PDIF/IEC958) ones when they boot muted."""

    def _run(self):
        calls = []

        def run(cmd):
            calls.append(cmd)
            return SCONTENTS
        return run, calls

    def test_parse_keeps_only_playback_switches(self):
        self.assertEqual(sq.parse_mixer_switches(SCONTENTS),
                         [('Master', True), ('IEC958', False)])

    def test_mixer_switches_shape(self):
        run, _ = self._run()
        self.assertEqual(sq.mixer_switches('hw:CARD=PCH,DEV=1', run=run),
                         [{'name': 'Master', 'on': True}, {'name': 'IEC958', 'on': False}])

    def test_not_a_card_has_no_switches(self):
        self.assertEqual(sq.mixer_switches('default'), [])
        self.assertEqual(sq.mixer_switches('hw:CARD=Loopback,DEV=0'), [])
        self.assertIsNone(sq.set_mixer_switch('default', 'IEC958', True))

    def test_unmute_only_touches_the_muted_digital_switch(self):
        run, calls = self._run()
        self.assertEqual(sq.unmute_digital_output('hw:CARD=PCH,DEV=1', run=run), ['IEC958'])
        ssets = [c for c in calls if 'sset' in c]
        self.assertEqual(ssets, [['amixer', '-q', '-c', 'PCH', 'sset', 'IEC958', 'unmute']])

    def test_set_mixer_switch_mutes_and_unmutes(self):
        run, calls = self._run()
        sq.set_mixer_switch('hw:CARD=PCH,DEV=0', 'Master', False, run=run)
        self.assertIn(['amixer', '-q', '-c', 'PCH', 'sset', 'Master', 'mute'], calls)
        run, calls = self._run()
        sq.set_mixer_switch('hw:CARD=PCH,DEV=0', 'IEC958', True, run=run)
        self.assertIn(['amixer', '-q', '-c', 'PCH', 'sset', 'IEC958', 'unmute'], calls)


class CurrentOutputRateTests(unittest.TestCase):
    """The rate the DAC is getting now, read from the open PCM's hw_params."""

    # hw_params as the kernel prints it for an open USB DAC playing 44.1k that a
    # 768 kHz cap upsampled synchronously to 705600 (16 x 44100).
    HW_PARAMS = ("access: MMAP_INTERLEAVED\nformat: S32_LE\nsubformat: STD\n"
                 "channels: 2\nrate: 705600 (705600/1)\nperiod_size: 7056\n"
                 "buffer_size: 28224\n")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hw = os.path.join(self.tmp.name, 'D50s', 'pcm0p', 'sub0', 'hw_params')
        os.makedirs(os.path.dirname(self.hw))

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, text):
        with open(self.hw, 'w') as f:
            f.write(text)

    def test_reads_the_open_rate(self):
        self._write(self.HW_PARAMS)
        self.assertEqual(
            sq.current_output_rate('hw:CARD=D50s,DEV=0', proc_asound=self.tmp.name), 705600)

    def test_closed_stream_is_zero(self):
        self._write('closed\n')
        self.assertEqual(
            sq.current_output_rate('hw:CARD=D50s,DEV=0', proc_asound=self.tmp.name), 0)

    def test_no_card_is_zero(self):
        self.assertEqual(sq.current_output_rate('default'), 0)
        self.assertEqual(
            sq.current_output_rate('hw:CARD=Nope,DEV=0', proc_asound=self.tmp.name), 0)


if __name__ == '__main__':
    unittest.main()
