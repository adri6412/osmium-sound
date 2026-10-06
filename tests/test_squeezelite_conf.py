"""Tests for hifi_squeezelite.py — the model behind /etc/default/squeezelite —
and its wiring in api_server.py (DAC choice, player name, Lyrion role, DSP
on/off and the Settings → Audio endpoints all go through the one model).

Hermetic: the JSON, the defaults file, /proc/asound and the DSP target are
temporary files; systemctl and amixer are fakes.

Run with:  python3 tests/test_squeezelite_conf.py
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import hifi_squeezelite as sq  # noqa: E402

STREAM_NATIVE_BE = """Topping D50s at usb-0000:00:14.0-3, high speed : USB Audio

Playback:
  Status: Stop
  Interface 1
    Altset 1
    Format: S32_LE
    Channels: 2
    Rates: 44100, 48000, 88200, 96000, 176400, 192000, 352800, 384000
  Interface 1
    Altset 2
    Format: DSD_U32_BE
    Channels: 2
    Rates: 44100, 48000, 88200, 96000, 176400, 192000, 352800, 384000
"""
STREAM_PCM_ONLY = """Generic USB Audio at usb-0000:00:14.0-4, full speed : USB Audio

Playback:
  Status: Stop
  Interface 1
    Altset 1
    Format: S24_3LE
    Channels: 2
    Rates: 44100, 48000, 96000
"""
STREAM_CAPTURE_DSD = """Some ADC

Playback:
  Status: Stop
  Interface 1
    Altset 1
    Format: S32_LE

Capture:
  Status: Stop
  Interface 2
    Altset 1
    Format: DSD_U32_BE
"""
SCONTENTS = """Simple mixer control 'PCM',0
  Capabilities: pvolume pswitch
  Playback channels: Front Left - Front Right
Simple mixer control 'D50s Clock Selector',0
  Capabilities: enum
Simple mixer control 'Mic',0
  Capabilities: cvolume cswitch
"""
LEGACY = "-o hw:CARD=D50s,DEV=0 -D -v -C 5 -s 127.0.0.1 -n OsmiumSound -M Osmium"
LEGACY_MAC = "-m 02:ab:cd:ef:01:23 " + LEGACY


class Sandbox:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix='sq-')
        self.conf = os.path.join(self.dir, 'hifi-player', 'squeezelite.json')
        self.default = os.path.join(self.dir, 'default', 'squeezelite')
        self.asound = os.path.join(self.dir, 'asound')
        self.dsp_target = os.path.join(self.dir, 'dsp-target')

    def card(self, cid, text, dev=0):
        """A USB audio card: snd-usb-audio's streamN file (and usbid)."""
        d = os.path.join(self.asound, cid)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f'stream{dev}'), 'w') as f:
            f.write(text)
        with open(os.path.join(d, 'usbid'), 'w') as f:
            f.write('152a:8750\n')

    def hda(self, cid, number, pcms):
        """An HDA card as the kernel lays it out: cardN with pcmXp/info, and
        /proc/asound/<id> a symlink to it. `pcms` = {dev: pcm id}."""
        d = os.path.join(self.asound, f'card{number}')
        for dev, pcm_id in pcms.items():
            os.makedirs(os.path.join(d, f'pcm{dev}p'), exist_ok=True)
            with open(os.path.join(d, f'pcm{dev}p', 'info'), 'w') as f:
                f.write(f'card: {number}\ndevice: {dev}\nsubdevice: 0\nstream: PLAYBACK\n'
                        f'id: {pcm_id}\nname: {pcm_id}\n')
        with open(os.path.join(d, 'id'), 'w') as f:
            f.write(cid + '\n')
        os.symlink(f'card{number}', os.path.join(self.asound, cid))

    def write_default(self, args, header="# legacy comment\n"):
        os.makedirs(os.path.dirname(self.default), exist_ok=True)
        with open(self.default, 'w') as f:
            f.write(header + f"ARGS='{args}'\n")

    def read_default(self):
        with open(self.default) as f:
            return f.read()

    def args(self):
        return sq.read_args_line(self.default)

    def conf_json(self):
        with open(self.conf) as f:
            return json.load(f)

    def probe(self, device):
        return sq.probe(device, self.asound)


class TestDsdProbe(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(sq.native_format_from_stream(STREAM_NATIVE_BE), 'u32be')
        self.assertEqual(sq.native_format_from_stream(STREAM_NATIVE_BE.replace('U32_BE', 'U32_LE')), 'u32le')
        self.assertIsNone(sq.native_format_from_stream(STREAM_PCM_ONLY))
        self.assertIsNone(sq.native_format_from_stream(STREAM_CAPTURE_DSD))
        self.assertIsNone(sq.native_format_from_stream(''))

    def test_probe(self):
        sb = Sandbox()
        sb.card('D50s', STREAM_NATIVE_BE)
        sb.card('Gen', STREAM_PCM_ONLY)
        self.assertEqual(sb.probe('hw:CARD=D50s,DEV=0'), 'u32be')
        self.assertEqual(sb.probe('hw:CARD=Gen,DEV=0'), 'dop')
        self.assertEqual(sb.probe('hw:CARD=D50s,DEV=1'), 'dop')     # a USB card, no stream for that device
        # not a USB audio device, or nothing to read: PCM, never DoP
        self.assertEqual(sb.probe('default'), sq.PCM_ONLY)
        self.assertEqual(sb.probe('hw:1,0'), sq.PCM_ONLY)
        self.assertEqual(sq.probe('hw:CARD=D50s,DEV=0', '/nonexistent'), sq.PCM_ONLY)


class TestMixer(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(sq.parse_mixer_controls(SCONTENTS), ['PCM'])
        self.assertEqual(sq.parse_mixer_controls(''), [])

    def test_mixer_controls(self):
        calls = []

        def run(cmd):
            calls.append(cmd)
            return SCONTENTS
        self.assertEqual(sq.mixer_controls('hw:CARD=D50s,DEV=0', run), ['PCM'])
        self.assertEqual(calls, [['amixer', '-c', 'D50s', 'scontents']])
        self.assertEqual(sq.mixer_controls('default', run), [])
        self.assertEqual(sq.mixer_controls('hw:CARD=Loopback,DEV=0', run), [])


class TestModel(unittest.TestCase):
    def test_defaults_are_normal(self):
        self.assertEqual(sq.normalize({}), sq.normalize(sq.DEFAULTS))
        self.assertEqual(sq.normalize(None)['dsd'], 'auto')

    def test_normalize_is_lenient(self):
        m = sq.normalize({'output': "hw:CARD=X,DEV=0'; rm -rf /", 'name': 'has space', 'server': 'bad host',
                          'mac': 'zz', 'dsd': 'weird', 'dsd_delay_ms': 'x', 'max_rate': 12345,
                          'volume': 'loud', 'mixer': 'My Control', 'alsa_buffer': 'huge',
                          'realtime': 'yes', 'extra': "-R -u v::3 $(reboot) 'x' -o hw:1,0", 'dsp': 'on'})
        self.assertEqual(m['output'], 'default')
        self.assertEqual(m['name'], 'OsmiumSound')
        self.assertEqual(m['server'], '127.0.0.1')
        self.assertEqual(m['mac'], '')
        self.assertEqual(m['dsd'], 'auto')
        self.assertEqual(m['dsd_delay_ms'], 0)
        self.assertEqual(m['max_rate'], 0)
        self.assertEqual(m['volume'], 'software')
        self.assertEqual(m['mixer'], '')
        self.assertEqual(m['alsa_buffer'], 'auto')
        self.assertTrue(m['realtime'])
        # the safe tokens survive; the dangerous ones and the managed flag
        # (with its value) do not
        self.assertEqual(m['extra'], '-R -u v::3')
        self.assertEqual(m['dsp'], {'enabled': False})

    def test_set_fields_is_strict(self):
        base = sq.normalize({})
        m = sq.set_fields(base, {'dsd': 'dop', 'dsd_delay_ms': 250, 'max_rate': 192000,
                                 'alsa_buffer': 'large', 'realtime': True, 'extra': '-R -u vE'})
        self.assertEqual((m['dsd'], m['dsd_delay_ms'], m['max_rate']), ('dop', 250, 192000))
        self.assertEqual(m['extra'], '-R -u vE')
        for bad in ({'dsd': 'u32be'}, {'dsd_delay_ms': 5000}, {'dsd_delay_ms': '100'}, {'max_rate': 12345},
                    {'volume': 'loud'}, {'mixer': 'PCM Playback'}, {'alsa_buffer': 'huge'},
                    {'realtime': 1}, {'nope': 1}):
            with self.assertRaises(sq.InvalidField, msg=str(bad)):
                sq.set_fields(base, bad)
        with self.assertRaises(sq.InvalidField) as cm:
            sq.set_fields(base, {'extra': '-o hw:1,0 -R'})
        self.assertEqual(cm.exception.code, 'squeezelite.extraManaged')
        self.assertEqual(cm.exception.detail, '-o')
        with self.assertRaises(sq.InvalidField) as cm:
            sq.set_fields(base, {'extra': "-R 'x'"})
        self.assertEqual(cm.exception.code, 'squeezelite.extraInvalid')
        # the refused change leaves the model untouched
        self.assertEqual(base, sq.normalize({}))

    def test_reset_keeps_the_identity_fields(self):
        m = sq.normalize({'output': 'hw:CARD=D50s,DEV=0', 'name': 'Salotto', 'server': '192.168.1.5',
                          'mac': '02:ab:cd:ef:01:23', 'dsd': 'dop', 'max_rate': 96000, 'extra': '-R'})
        r = sq.reset_tunables(m)
        self.assertEqual((r['output'], r['name'], r['server'], r['mac']),
                         ('hw:CARD=D50s,DEV=0', 'Salotto', '192.168.1.5', '02:ab:cd:ef:01:23'))
        self.assertEqual((r['dsd'], r['max_rate'], r['extra']), ('auto', 0, ''))


class TestImport(unittest.TestCase):
    """A device that predates the model: its ARGS line, field by field."""

    def test_legacy_default_line(self):
        m = sq.parse_args(LEGACY)
        self.assertEqual(m['output'], 'hw:CARD=D50s,DEV=0')
        self.assertEqual(m['dsd'], 'auto')
        self.assertEqual(m['name'], 'OsmiumSound')
        self.assertEqual(m['server'], '127.0.0.1')
        self.assertEqual(m['model'], 'Osmium')
        self.assertEqual(m['extra'], '')
        self.assertFalse(m['dsp']['enabled'])

    def test_mac_follow_and_name(self):
        m = sq.parse_args("-m 02:ab:cd:ef:01:23 -o default -D -v -C 5 -s 192.168.1.50 -n Salotto -M Osmium")
        self.assertEqual((m['mac'], m['server'], m['name']), ('02:ab:cd:ef:01:23', '192.168.1.50', 'Salotto'))

    def test_dsd_variants(self):
        self.assertEqual(sq.parse_args(LEGACY.replace(' -D', ''))['dsd'], 'off')
        self.assertEqual(sq.parse_args(LEGACY.replace('-D', '-D :dop'))['dsd'], 'dop')
        m = sq.parse_args(LEGACY.replace('-D', '-D 100:u32be'))
        self.assertEqual((m['dsd'], m['dsd_delay_ms']), ('native', 100))
        self.assertEqual(sq.parse_args(LEGACY.replace('-D', '-D 250'))['dsd_delay_ms'], 250)

    def test_hand_set_options_land_in_their_fields(self):
        m = sq.parse_args(LEGACY + " -r 192000 -V PCM -a 200:8 -b 16384:8192 -p 45 -R -u v::3.1")
        self.assertEqual(m['max_rate'], 192000)
        self.assertEqual((m['volume'], m['mixer']), ('hardware', 'PCM'))
        self.assertEqual((m['alsa_buffer'], m['stream_buffer'], m['realtime']), ('large', 'large', True))
        self.assertEqual(m['extra'], '-R -u v::3.1')

    def test_unknown_values_of_managed_options_are_dropped(self):
        # a rate range or a custom buffer has no field: gone, with no stray
        # value left on the line; the unknown flags are kept as extra
        m = sq.parse_args(LEGACY + " -r 44100-96000 -a 80:4 -b 2048:1024 -W -Z")
        self.assertEqual(m['max_rate'], 0)
        self.assertEqual(m['alsa_buffer'], 'auto')
        self.assertEqual(m['stream_buffer'], 'auto')
        self.assertEqual(m['extra'], '-W -Z')

    def test_check_extra_drops_a_managed_flag_with_its_value(self):
        self.assertEqual(sq.check_extra('-R -o hw:1,0 -u vE -n Pirata -W'), ('-R -u vE -W', [], ['-o', '-n']))
        self.assertEqual(sq.check_extra("-R $(reboot) 'x'"), ('-R', ['$(reboot)', "'x'"], []))

    def test_dsp_path_is_imported_as_dsp_on(self):
        m = sq.parse_args("-o hw:CARD=Loopback,DEV=0 -r 48000 -R -v -C 5 -s 127.0.0.1 -n OsmiumSound -M Osmium",
                          dsp_target='hw:CARD=D50s,DEV=0')
        self.assertTrue(m['dsp']['enabled'])
        self.assertEqual(m['output'], 'hw:CARD=D50s,DEV=0')
        self.assertEqual(m['max_rate'], 0)
        self.assertEqual(m['extra'], '')
        self.assertEqual(m['dsd'], 'off')   # no -D on the loopback; the render ignores it while DSP is on


class TestRender(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.sb.card('D50s', STREAM_NATIVE_BE)
        self.sb.card('Gen', STREAM_PCM_ONLY)
        self.base = sq.normalize({'output': 'hw:CARD=D50s,DEV=0'})

    def r(self, **changes):
        m = dict(self.base)
        m['dsp'] = dict(self.base['dsp'])
        m.update(changes)
        return sq.render(m, self.sb.probe)

    def test_legacy_line_round_trips(self):
        # a device imported from the stock line renders the stock line, with
        # the only intended change: native DSD where the DAC declares it
        self.assertEqual(sq.render(sq.parse_args(LEGACY), self.sb.probe), LEGACY.replace('-D', '-D :u32be'))
        self.assertEqual(sq.render(sq.parse_args(LEGACY_MAC), self.sb.probe), LEGACY_MAC.replace('-D', '-D :u32be'))
        gen = LEGACY.replace('D50s', 'Gen')
        self.assertEqual(sq.render(sq.parse_args(gen), self.sb.probe), gen)
        # the stock line had `-D` on `default` too: auto no longer sends DoP there
        stock = "-o default -D -v -C 5 -s 127.0.0.1 -n OsmiumSound -M Osmium"
        self.assertEqual(sq.render(sq.parse_args(stock), self.sb.probe), stock.replace(' -D', ''))

    def test_dsd_modes(self):
        self.assertIn(' -D :u32be ', self.r(dsd='auto'))
        self.assertIn(' -D -v', self.r(dsd='dop'))
        self.assertIn(' -D :u32be ', self.r(dsd='native'))
        self.assertNotIn('-D', self.r(dsd='off'))
        # native asked on a DAC that does not declare it: DoP, not a format it cannot take
        self.assertIn(' -D -v', self.r(dsd='native', output='hw:CARD=Gen,DEV=0'))
        self.assertIn(' -D 250:u32be ', self.r(dsd_delay_ms=250))
        self.assertIn(' -D 250 -v', self.r(dsd='dop', dsd_delay_ms=250))

    def test_tunables(self):
        self.assertIn(' -r 192000', self.r(max_rate=192000))
        self.assertNotIn(' -r ', self.r(max_rate=0))
        self.assertIn(' -V PCM', self.r(volume='hardware', mixer='PCM'))
        self.assertNotIn(' -V ', self.r(volume='software', mixer='PCM'))
        self.assertNotIn(' -V ', self.r(volume='hardware', mixer=''))
        self.assertIn(' -a 200:8', self.r(alsa_buffer='large'))
        self.assertIn(' -b 16384:8192', self.r(stream_buffer='large'))
        self.assertIn(' -p 45', self.r(realtime=True))
        self.assertTrue(self.r(extra='-R -u vE').endswith(' -R -u vE'))

    def test_dsp_on(self):
        line = self.r(dsp={'enabled': True}, max_rate=192000, volume='hardware', mixer='PCM')
        self.assertTrue(line.startswith('-o hw:CARD=Loopback,DEV=0 -v -C 5 '), line)
        self.assertIn(' -r 48000 -R', line)
        self.assertNotIn('-D', line)
        self.assertNotIn('-V', line)
        self.assertNotIn('192000', line)
        # and back
        self.assertIn('-o hw:CARD=D50s,DEV=0 -D :u32be -v', self.r(dsp={'enabled': False}))

    def test_v_is_always_there(self):
        for line in (self.r(), self.r(dsp={'enabled': True}), self.r(dsd='off', extra='-W')):
            self.assertIn(' -v ', line)


class TestDsdAuto(unittest.TestCase):
    """`auto` sends DoP only to a USB audio device: HDMI, the onboard codec
    and `default` take 176.4 kHz PCM and would play DoP as loud noise."""

    def setUp(self):
        self.sb = Sandbox()
        self.sb.card('D50s', STREAM_NATIVE_BE)
        self.sb.card('Gen', STREAM_PCM_ONLY)
        self.sb.hda('PCH', 0, {0: 'ALC269VC Analog', 3: 'HDMI 0', 7: 'HDMI 1', 8: 'HDMI 2'})
        self.sb.hda('NVidia', 1, {3: 'HDMI 0'})

    def r(self, output, dsd='auto'):
        return sq.render(sq.normalize({'output': output, 'dsd': dsd}), self.sb.probe)

    def test_hdmi_gets_no_dop(self):
        for out in ('hw:CARD=PCH,DEV=3', 'hw:CARD=PCH,DEV=7', 'hw:CARD=PCH,DEV=8',
                    'hw:CARD=NVidia,DEV=3', 'hw:0,3', 'plughw:CARD=PCH,DEV=3'):
            self.assertEqual(self.sb.probe(out), sq.PCM_ONLY, out)
            self.assertNotIn('-D', self.r(out), out)

    def test_onboard_codec_and_default_get_no_dop(self):
        self.assertNotIn('-D', self.r('hw:CARD=PCH,DEV=0'))
        self.assertNotIn('-D', self.r('default'))
        self.assertNotIn('-D', self.r('hw:CARD=Missing,DEV=0'))

    def test_usb_dac_without_native_dsd_gets_dop(self):
        self.assertIn('-o hw:CARD=Gen,DEV=0 -D -v ', self.r('hw:CARD=Gen,DEV=0'))

    def test_usb_dac_with_native_dsd_gets_native(self):
        self.assertIn('-o hw:CARD=D50s,DEV=0 -D :u32be -v ', self.r('hw:CARD=D50s,DEV=0'))

    def test_either_usb_mark_is_enough(self):
        os.unlink(os.path.join(self.sb.asound, 'Gen', 'usbid'))
        self.assertEqual(self.sb.probe('hw:CARD=Gen,DEV=0'), 'dop')
        os.makedirs(os.path.join(self.sb.asound, 'Bare'))
        with open(os.path.join(self.sb.asound, 'Bare', 'usbid'), 'w') as f:
            f.write('20b1:3008\n')
        self.assertEqual(self.sb.probe('hw:CARD=Bare,DEV=0'), 'dop')

    def test_explicit_choices_are_kept(self):
        self.assertIn(' -D -v ', self.r('hw:CARD=PCH,DEV=3', dsd='dop'))
        self.assertNotIn('-D', self.r('hw:CARD=D50s,DEV=0', dsd='off'))

    def test_native_on_an_output_with_no_dsd_converts_instead_of_dop(self):
        # A device in the field had `native` stored with HDMI as its output:
        # falling back to DoP there plays the stream as noise.
        self.assertNotIn('-D', self.r('hw:CARD=PCH,DEV=3', dsd='native'))
        self.assertNotIn('-D', self.r('default', dsd='native'))

    def test_the_field_device_loses_its_dop_on_hdmi(self):
        # the line a device in the field had: imported as `auto`, rendered without -D
        self.sb.write_default('-o hw:CARD=PCH,DEV=3 -D -v -C 5 -s 127.0.0.1 -n OsmiumSound -M Osmium')
        model, args, changed = sq.apply(self.sb.conf, self.sb.default, self.sb.dsp_target, self.sb.probe,
                                        None, os.path.join(self.sb.dir, 'no-machine-id'))
        self.assertEqual(model['dsd'], 'auto')
        self.assertEqual(args, '-o hw:CARD=PCH,DEV=3 -v -C 5 -s 127.0.0.1 -n OsmiumSound -M Osmium')


def _append_token(conf, default, asound, token, count):
    """One writer of TestConcurrency: `count` updates, each adding a token."""
    probe = lambda d: sq.probe(d, asound)   # noqa: E731
    for i in range(count):
        sq.update(lambda m: m.update(extra=(m['extra'] + f' {token}{i}').strip()),
                  conf, default, os.path.join(os.path.dirname(conf), 'no-dsp-target'), probe)


def _apply_loop(conf, default, asound, count):
    """The ExecStartPre of a crash-looping squeezelite, sped up."""
    for _ in range(count):
        sq.apply(conf, default, os.path.join(os.path.dirname(conf), 'no-dsp-target'),
                 lambda d: sq.probe(d, asound), None, '/nonexistent-machine-id')


class TestConcurrency(unittest.TestCase):
    """Writers in threads (api_server's requests) and processes (the
    ExecStartPre) never lose each other's change nor trip on a temp file."""

    def setUp(self):
        self.sb = Sandbox()
        self.sb.card('D50s', STREAM_NATIVE_BE)
        self.sb.write_default(LEGACY)

    def tokens(self):
        return set(self.sb.conf_json()['extra'].split())

    def assert_no_leftovers(self):
        for d in (os.path.dirname(self.sb.conf), os.path.dirname(self.sb.default)):
            self.assertEqual([f for f in os.listdir(d) if f.endswith('.tmp')], [], d)

    def test_threads(self):
        import threading
        errors = []

        def worker(n):
            try:
                _append_token(self.sb.conf, self.sb.default, self.sb.asound, f't{n}x', 10)
            except Exception as e:      # pragma: no cover - the failure being tested for
                errors.append(e)
        threads = [threading.Thread(target=worker, args=(n,)) for n in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(self.tokens(), {f't{n}x{i}' for n in range(12) for i in range(10)})
        self.assertIn(' -D :u32be ', self.sb.args())
        self.assert_no_leftovers()

    def test_processes_and_apply(self):
        import multiprocessing
        ctx = multiprocessing.get_context('fork')
        procs = [ctx.Process(target=_append_token,
                             args=(self.sb.conf, self.sb.default, self.sb.asound, f'p{n}x', 15))
                 for n in range(4)]
        procs += [ctx.Process(target=_apply_loop, args=(self.sb.conf, self.sb.default, self.sb.asound, 30))
                  for _ in range(2)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(60)
        self.assertEqual([p.exitcode for p in procs], [0] * len(procs))
        self.assertEqual(self.tokens(), {f'p{n}x{i}' for n in range(4) for i in range(15)})
        # the file is the render of the model as it ended up, not of an older one
        self.assertEqual(self.sb.args(), sq.render(self.sb.conf_json(), self.sb.probe))
        self.assert_no_leftovers()

    def test_a_held_lock_times_out(self):
        with sq.locked(self.sb.conf):
            with self.assertRaises(sq.LockTimeout):
                sq.update(lambda m: m.update(name='Late'), self.sb.conf, self.sb.default,
                          self.sb.dsp_target, self.sb.probe, timeout=0.1)
            # the ExecStartPre still renders: the player must get its line
            out = io.StringIO()
            model, args, _ = sq.apply(self.sb.conf, self.sb.default, self.sb.dsp_target, self.sb.probe,
                                      out, '/nonexistent-machine-id', lock_timeout=0.1)
            self.assertIn('without the lock', out.getvalue())
            self.assertEqual(self.sb.args(), args)
        self.assertEqual(self.sb.conf_json()['name'], 'OsmiumSound')
        # released: the next writer gets in
        sq.update(lambda m: m.update(name='Late'), self.sb.conf, self.sb.default,
                  self.sb.dsp_target, self.sb.probe, timeout=0.1)
        self.assertIn(' -n Late ', self.sb.args())

    def test_a_refused_change_writes_nothing(self):
        sq.apply(self.sb.conf, self.sb.default, self.sb.dsp_target, self.sb.probe, None,
                 '/nonexistent-machine-id')
        before = (self.sb.read_default(), self.sb.conf_json())
        with self.assertRaises(sq.InvalidField):
            sq.update(lambda m: sq.set_fields(m, {'dsd': 'nope'}), self.sb.conf, self.sb.default,
                      self.sb.dsp_target, self.sb.probe)
        self.assertEqual((self.sb.read_default(), self.sb.conf_json()), before)
        self.assert_no_leftovers()


class TestFiles(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.sb.card('D50s', STREAM_NATIVE_BE)

    def apply(self, out=None, machine_id=None):
        return sq.apply(self.sb.conf, self.sb.default, self.sb.dsp_target, self.sb.probe, out,
                        machine_id or os.path.join(self.sb.dir, 'no-machine-id'))

    def test_a_missing_mac_is_derived_from_the_machine_id_once(self):
        mid = os.path.join(self.sb.dir, 'machine-id')
        with open(mid, 'w') as f:
            f.write('1d58b9851f6943edad4961af9ee2cff6\n')
        model, args, changed = self.apply(machine_id=mid)
        # the same value migration 0042 computes in shell for this id
        self.assertEqual(model['mac'], '02:c8:27:89:b2:a6')
        self.assertIn('-m 02:c8:27:89:b2:a6 ', args)
        self.assertEqual(self.sb.conf_json()['mac'], '02:c8:27:89:b2:a6')
        # a later machine-id (or none) never moves it again
        with open(mid, 'w') as f:
            f.write('ffffffffffffffffffffffffffffffff\n')
        self.assertEqual(self.apply(machine_id=mid)[0]['mac'], '02:c8:27:89:b2:a6')
        self.assertFalse(self.apply()[2])

    def test_a_mac_already_there_is_kept(self):
        self.sb.write_default(LEGACY_MAC)
        mid = os.path.join(self.sb.dir, 'machine-id')
        with open(mid, 'w') as f:
            f.write('1d58b9851f6943edad4961af9ee2cff6\n')
        self.assertEqual(self.apply(machine_id=mid)[0]['mac'], '02:ab:cd:ef:01:23')

    def test_first_apply_imports_the_file(self):
        self.sb.write_default(LEGACY_MAC)
        out = io.StringIO()
        model, args, changed = self.apply(out)
        self.assertTrue(changed)
        self.assertEqual(args, LEGACY_MAC.replace('-D', '-D :u32be'))
        self.assertEqual(self.sb.args(), args)
        self.assertEqual(self.sb.conf_json()['mac'], '02:ab:cd:ef:01:23')
        self.assertIn('GENERATED FILE', self.sb.read_default())
        self.assertIn('imported', out.getvalue())
        # second apply: nothing to do
        self.assertFalse(self.apply()[2])

    def test_no_file_no_json_gives_defaults(self):
        model, args, changed = self.apply()
        self.assertTrue(changed)
        self.assertEqual(args, "-o default -v -C 5 -s 127.0.0.1 -n OsmiumSound -M Osmium")

    def test_hand_edit_of_the_file_is_overwritten(self):
        self.sb.write_default(LEGACY)
        self.apply()
        with open(self.sb.default, 'a') as f:
            pass
        hacked = self.sb.read_default().replace("-n OsmiumSound", "-n Pirata -r 44100")
        with open(self.sb.default, 'w') as f:
            f.write(hacked)
        self.assertIn('Pirata', self.sb.args())
        self.assertTrue(self.apply()[2])
        self.assertNotIn('Pirata', self.sb.args())
        self.assertEqual(self.sb.conf_json()['name'], 'OsmiumSound')

    def test_hand_edit_of_the_json_is_honoured(self):
        self.sb.write_default(LEGACY)
        self.apply()
        j = self.sb.conf_json()
        j['dsd'] = 'dop'
        j['extra'] = '-R -u v::3.1'
        with open(self.sb.conf, 'w') as f:
            json.dump(j, f)
        self.assertTrue(self.apply()[2])
        self.assertIn(' -D -v', self.sb.args())
        self.assertTrue(self.sb.args().endswith(' -R -u v::3.1'))

    def test_broken_json_falls_back_to_the_file(self):
        self.sb.write_default(LEGACY)
        os.makedirs(os.path.dirname(self.sb.conf), exist_ok=True)
        with open(self.sb.conf, 'w') as f:
            f.write('{ not json')
        model, args, _ = self.apply()
        self.assertEqual(model['output'], 'hw:CARD=D50s,DEV=0')
        self.assertEqual(self.sb.conf_json()['output'], 'hw:CARD=D50s,DEV=0')

    def test_cli(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(sq.main(['x', 'probe', 'default']), 0)
        self.assertEqual(out.getvalue().strip(), sq.PCM_ONLY)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(sq.main(['x']), 2)
        self.assertIn('usage', err.getvalue())


class TestApiServer(unittest.TestCase):
    """The writers in api_server.py all go through the model."""

    @classmethod
    def setUpClass(cls):
        import api_server
        cls.api = api_server

    def setUp(self):
        self.sb = Sandbox()
        self.sb.card('D50s', STREAM_NATIVE_BE)
        self.sb.card('Gen', STREAM_PCM_ONLY)
        self.sb.write_default(LEGACY)
        self._saved = {}
        api = self.api
        self._patch('SQUEEZELITE_DEFAULT', self.sb.default)
        self._patch('SQUEEZELITE_CONF', self.sb.conf)
        self._patch('DSP_TARGET_FILE', self.sb.dsp_target)
        self._patch('PLAYER_ENABLED_FILE', os.path.join(self.sb.dir, 'player-enabled'))
        self._patch('DSP_STATE_FILE', os.path.join(self.sb.dir, 'dsp.json'))
        self._patch('CAMILLA_CONFIG', os.path.join(self.sb.dir, 'camilladsp', 'config.yml'))
        self.calls = []
        self._patch('_run', self._fake_run)
        self._patch('_read_bt_state', lambda: None)
        self._patch('_local_playing_player', lambda: (None, None))
        # the DSD probe and the mixer list read the sandbox, not /proc and amixer
        self._sq_saved = (sq.PROC_ASOUND, sq.mixer_controls)
        sq.PROC_ASOUND = self.sb.asound
        sq.mixer_controls = lambda device, run=None: ['PCM'] if 'D50s' in device else []
        devices = {'devices': [{'id': 'default'}, {'id': 'hw:CARD=D50s,DEV=0'}, {'id': 'hw:CARD=Gen,DEV=0'}]}
        self._patch('list_audio_devices', lambda: devices)
        self.api = api

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(self.api, name, value)
        sq.PROC_ASOUND, sq.mixer_controls = self._sq_saved

    def _patch(self, name, value):
        self._saved[name] = getattr(self.api, name)
        setattr(self.api, name, value)

    def _fake_run(self, cmd, timeout=20):
        self.calls.append(list(cmd))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout='', stderr='')

    def restarts(self):
        return [c for c in self.calls if c[:3] == ['systemctl', 'restart', 'squeezelite']]

    def test_set_audio_device(self):
        r = self.api.set_audio_device('hw:CARD=Gen,DEV=0')
        self.assertTrue(r['success'], r)
        self.assertEqual(self.sb.args(), LEGACY.replace('D50s', 'Gen'))
        self.assertEqual(self.sb.conf_json()['output'], 'hw:CARD=Gen,DEV=0')
        self.assertEqual(len(self.restarts()), 1)
        r = self.api.set_audio_device('hw:CARD=D50s,DEV=0')
        self.assertIn('-o hw:CARD=D50s,DEV=0 -D :u32be -v', self.sb.args())
        self.assertFalse(self.api.set_audio_device('hw:CARD=Evil,DEV=0')['success'])
        self.assertEqual(self.api._current_real_dac(), 'hw:CARD=D50s,DEV=0')

    def test_player_name_and_lms_role(self):
        self.assertTrue(self.api.set_player_name('Salotto')['success'])
        self.assertIn(' -n Salotto ', self.sb.args())
        self.assertEqual(self.api.get_player_name(), {'name': 'Salotto'})
        self.assertTrue(self.api.set_lms_role('follow', '192.168.1.50')['success'])
        self.assertIn(' -s 192.168.1.50 ', self.sb.args())
        self.assertIn(' -n Salotto ', self.sb.args())    # the two fields do not clobber each other
        self.assertEqual(self.api.get_lms_role(), {'mode': 'follow', 'host': '192.168.1.50'})
        self.assertTrue(self.api.set_lms_role('local', None)['success'])
        self.assertIn(' -s 127.0.0.1 ', self.sb.args())

    def test_conf_endpoints(self):
        g = self.api.get_squeezelite_conf()
        self.assertEqual(g['conf']['dsd'], 'auto')
        self.assertEqual(g['dsd_detected'], 'native')
        self.assertEqual(g['mixers'], ['PCM'])
        # `args` is what the model renders now (what the next start gets); the
        # file itself is rendered by the service's ExecStartPre or by a change
        self.assertEqual(g['args'], LEGACY.replace('-D', '-D :u32be'))
        r = self.api.set_squeezelite_conf({'dsd': 'dop', 'max_rate': 96000, 'volume': 'hardware'})
        self.assertTrue(r['success'], r)
        self.assertEqual(r['conf']['mixer'], 'PCM')            # picked for the owner
        self.assertIn('-o hw:CARD=D50s,DEV=0 -D -v -C 5 -s 127.0.0.1 -n OsmiumSound -M Osmium -r 96000 -V PCM',
                      self.sb.args())
        self.assertEqual(len(self.restarts()), 1)
        # same values again: nothing changes, no restart
        r = self.api.set_squeezelite_conf({'dsd': 'dop'})
        self.assertTrue(r['success'])
        self.assertEqual(len(self.restarts()), 1)
        # refusals carry the i18n message and touch nothing
        r = self.api.set_squeezelite_conf({'extra': '-o hw:1,0'})
        self.assertFalse(r['success'])
        self.assertEqual(r['code'], 'squeezelite.extraManaged')
        self.assertIn('-o', r['message'])
        r = self.api.set_squeezelite_conf({'dsd': 'nope'})
        self.assertEqual(r['code'], 'squeezelite.invalidValue')
        self.assertEqual(len(self.restarts()), 1)
        # hardware volume on an output without a mixer is refused
        self.api.set_audio_device('hw:CARD=Gen,DEV=0')
        r = self.api.set_squeezelite_conf({'volume': 'hardware', 'mixer': ''})
        self.assertEqual(r['code'], 'squeezelite.noMixer')
        # reset: tunables back, identity kept
        r = self.api.reset_squeezelite_conf()
        self.assertTrue(r['success'])
        self.assertEqual(r['conf']['dsd'], 'auto')
        self.assertEqual(r['conf']['output'], 'hw:CARD=Gen,DEV=0')
        self.assertEqual(self.sb.args(), LEGACY.replace('D50s', 'Gen'))

    def test_concurrent_requests_keep_every_change(self):
        # three requests on three fields at once, many times over: each one
        # reads the model under the lock, so none writes back a stale copy
        import threading
        for i in range(15):
            jobs = [lambda: self.api.set_player_name(f'Room{i}'),
                    lambda: self.api.set_lms_role('follow', f'192.168.1.{i + 10}'),
                    lambda: self.api.set_squeezelite_conf({'max_rate': (96000, 192000)[i % 2]})]
            results = []
            threads = [threading.Thread(target=lambda j=j: results.append(j())) for j in jobs]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertTrue(all(r['success'] for r in results), results)
            conf = self.sb.conf_json()
            self.assertEqual((conf['name'], conf['server'], conf['max_rate']),
                             (f'Room{i}', f'192.168.1.{i + 10}', (96000, 192000)[i % 2]))
            self.assertIn(f' -n Room{i} ', self.sb.args())
            self.assertIn(f' -s 192.168.1.{i + 10} ', self.sb.args())

    def test_dsp_on_and_off(self):
        from unittest import mock
        self.api.set_squeezelite_conf({'max_rate': 192000})
        self.calls = []
        fake = mock.Mock(return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr=''))
        with mock.patch('subprocess.run', fake):     # the `sudo systemctl` calls of the DSP unit
            with self.api._dsp_apply_lock:
                self.api._apply_dsp_on_locked('hw:CARD=D50s,DEV=0', [], False, False, 0.0, {'devices': {}})
            self.assertEqual(self.sb.args(),
                             "-o hw:CARD=Loopback,DEV=0 -v -C 5 -s 127.0.0.1 -n OsmiumSound -M Osmium -r 48000 -R")
            self.assertEqual(self.api._current_audio_device(), 'hw:CARD=Loopback,DEV=0')
            self.assertEqual(self.api._current_real_dac(), 'hw:CARD=D50s,DEV=0')
            self.assertEqual(len(self.restarts()), 1)
            # a second apply with DSP already on does not restart the player
            with self.api._dsp_apply_lock:
                self.api._apply_dsp_on_locked('hw:CARD=D50s,DEV=0', [], False, False, 0.0, {'devices': {}})
            self.assertEqual(len(self.restarts()), 1)
            self.api._apply_dsp_off()
        self.assertEqual(self.sb.args(), LEGACY.replace('-D', '-D :u32be') + ' -r 192000')
        self.assertEqual(self.api._current_audio_device(), 'hw:CARD=D50s,DEV=0')


if __name__ == '__main__':
    unittest.main()
