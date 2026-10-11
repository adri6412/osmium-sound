"""Tests for the audio zones (one more player per DAC) and the PCM to DSD
conversion: hifi_squeezelite.py's model, renderer, zones file and Lyrion
rules, the wrapper Lyrion runs (hifi-pcm2dsd.py) and api_server.py's
/zones and Settings → Audio wiring.

Hermetic: every file lives in a temporary directory; systemctl, amixer and
the CPU measurement are fakes.

Run with:  python3 tests/test_zones_pcm2dsd.py
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import hifi_squeezelite as sq  # noqa: E402
from test_squeezelite_conf import Sandbox, STREAM_NATIVE_BE, STREAM_PCM_ONLY, LEGACY, LEGACY_MAC  # noqa: E402

WRAPPER = os.path.join(ROOT, 'distro', 'config', 'includes.chroot', 'usr', 'local', 'sbin', 'hifi-pcm2dsd.py')
MAC = '02:aa:bb:cc:dd:ee'


def slurp(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def load_wrapper():
    spec = importlib.util.spec_from_file_location('hifi_pcm2dsd', WRAPPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ToolsSandbox(Sandbox):
    """A Sandbox where sox_ng and the wrapper "are installed"."""

    def __init__(self):
        super().__init__()
        self.sox = os.path.join(self.dir, 'sox_ng')
        self.wrapper = os.path.join(self.dir, 'hifi-pcm2dsd.py')
        for path in (self.sox, self.wrapper):
            with open(path, 'w') as f:
                f.write('#!/bin/sh\n')
        self.zones = os.path.join(self.dir, 'hifi-player', 'zones.json')
        self.map = os.path.join(self.dir, 'hifi-player', 'pcm2dsd.json')
        self.rules = os.path.join(self.dir, 'squeezeboxserver', 'custom-convert.conf')
        self.machine_id = os.path.join(self.dir, 'machine-id')
        with open(self.machine_id, 'w') as f:
            f.write('0123456789abcdef0123456789abcdef\n')


class ToolsMixin:
    def setUp(self):
        self.sb = ToolsSandbox()
        self.sb.card('D50s', STREAM_NATIVE_BE)
        self.sb.card('Gen', STREAM_PCM_ONLY)
        self._sq = (sq.SOX_NG, sq.PCM2DSD_WRAPPER, sq.PROC_ASOUND)
        sq.SOX_NG, sq.PCM2DSD_WRAPPER, sq.PROC_ASOUND = self.sb.sox, self.sb.wrapper, self.sb.asound

    def tearDown(self):
        sq.SOX_NG, sq.PCM2DSD_WRAPPER, sq.PROC_ASOUND = self._sq

    def model(self, **kw):
        m = sq.normalize({'output': 'hw:CARD=D50s,DEV=0', 'mac': MAC})
        m.update(kw)
        return m


class TestModel(ToolsMixin, unittest.TestCase):
    def test_defaults_and_normalize(self):
        m = sq.normalize({})
        self.assertEqual((m['pcm2dsd'], m['pcm2dsd_filter']), ('off', 'clans-8'))
        m = sq.normalize({'pcm2dsd': 'DSD128', 'pcm2dsd_filter': 'nonsense'})
        self.assertEqual((m['pcm2dsd'], m['pcm2dsd_filter']), ('dsd128', 'clans-8'))
        self.assertEqual(sq.normalize({'pcm2dsd': 'dsd1024'})['pcm2dsd'], 'off')

    def test_set_fields(self):
        m = sq.set_fields(sq.normalize({}), {'pcm2dsd': 'dsd64', 'pcm2dsd_filter': 'sdm-8'})
        self.assertEqual((m['pcm2dsd'], m['pcm2dsd_filter']), ('dsd64', 'sdm-8'))
        for bad in ({'pcm2dsd': 'dsd512'}, {'pcm2dsd_filter': 'clans-3'}, {'pcm2dsd': True}):
            with self.assertRaises(sq.InvalidField):
                sq.set_fields(sq.normalize({}), bad)
        # -c belongs to the model now: refused in the extra arguments
        with self.assertRaises(sq.InvalidField) as e:
            sq.set_fields(sq.normalize({}), {'extra': '-c flac'})
        self.assertEqual(e.exception.code, 'squeezelite.extraManaged')
        self.assertEqual(sq.normalize({'extra': '-c flac -W'})['extra'], '-W')

    def test_state(self):
        probe = self.sb.probe
        self.assertEqual(sq.pcm2dsd_state(self.model(), 'u32be'), 'off')
        self.assertEqual(sq.pcm2dsd_state(self.model(pcm2dsd='dsd64'), probe('hw:CARD=D50s,DEV=0')), 'active')
        self.assertEqual(sq.pcm2dsd_state(self.model(pcm2dsd='dsd64', server='192.168.1.9'), 'u32be'), 'remoteServer')
        self.assertEqual(sq.pcm2dsd_state(self.model(pcm2dsd='dsd64', dsp={'enabled': True}), 'u32be'), 'dsp')
        self.assertEqual(sq.pcm2dsd_state(self.model(pcm2dsd='dsd64', dsd='off'), 'u32be'), 'noDsd')
        self.assertEqual(sq.pcm2dsd_state(self.model(pcm2dsd='dsd64'), sq.PCM_ONLY), 'noDsd')
        # a USB DAC without native DSD gets DoP: still DSD
        self.assertEqual(sq.pcm2dsd_state(self.model(pcm2dsd='dsd64', output='hw:CARD=Gen,DEV=0'),
                                          probe('hw:CARD=Gen,DEV=0')), 'active')
        os.unlink(self.sb.sox)
        self.assertEqual(sq.pcm2dsd_state(self.model(pcm2dsd='dsd64'), 'u32be'), 'noTools')

    def test_render(self):
        args = sq.render(self.model(pcm2dsd='dsd128'), self.sb.probe)
        self.assertIn('-D :u32be', args)
        self.assertTrue(args.endswith('-b 16384:8192 -c dsd'), args)
        self.assertEqual(args.count('-b '), 1)
        args = sq.render(self.model(pcm2dsd='dsd128', stream_buffer='large', extra='-W'), self.sb.probe)
        self.assertEqual(args.count('-b '), 1)
        self.assertTrue(args.endswith('-c dsd -W'), args)
        # not active: nothing changes
        for m in (self.model(), self.model(pcm2dsd='dsd64', server='nas.local'),
                  self.model(pcm2dsd='dsd64', dsd='off')):
            self.assertNotIn('-c dsd', sq.render(m, self.sb.probe))
        # the legacy line is unchanged by the refactor
        self.assertEqual(sq.render(sq.parse_args(LEGACY), lambda d: 'dop'), LEGACY)


class TestZones(ToolsMixin, unittest.TestCase):
    def test_id_and_mac(self):
        self.assertEqual(sq.zone_id('hw:CARD=D50s,DEV=0'), 'D50s-0')
        self.assertIsNone(sq.zone_id('default'))
        self.assertIsNone(sq.zone_id('hw:1,0'))         # a card number moves between boots
        a = sq.zone_mac('hw:CARD=D50s,DEV=0', self.sb.machine_id)
        self.assertRegex(a, r'^02(:[0-9a-f]{2}){5}$')
        self.assertEqual(a, sq.zone_mac('hw:CARD=D50s,DEV=0', self.sb.machine_id))
        self.assertNotEqual(a, sq.zone_mac('hw:CARD=Gen,DEV=0', self.sb.machine_id))
        self.assertNotEqual(a, sq.derived_mac(self.sb.machine_id))
        self.assertEqual(sq.zone_mac('hw:CARD=D50s,DEV=0', os.path.join(self.sb.dir, 'none')), '')

    def test_names(self):
        self.assertEqual(sq.clean_zone_name('  Living   room '), 'Living room')
        self.assertEqual(sq.clean_zone_name('tab\there'), 'tab here')
        for bad in ('a"b', "it's", 'x$y', 'a`b', 'x' * 33, ''):
            self.assertEqual(sq.clean_zone_name(bad), '', bad)

    def test_load_save(self):
        sq.save_zones([{'output': 'hw:CARD=D50s,DEV=0', 'name': 'Studio', 'mac': MAC, 'pcm2dsd': 'dsd64'},
                       {'output': 'default', 'name': 'nope'},
                       {'output': 'hw:CARD=D50s,DEV=0', 'name': 'dup'}], self.sb.zones)
        zones = sq.load_zones(self.sb.zones)
        self.assertEqual([z['id'] for z in zones], ['D50s-0'])
        z = zones[0]
        self.assertEqual((z['name'], z['enabled'], z['pcm2dsd'], z['dsp']), ('Studio', True, 'dsd64', {'enabled': False}))
        self.assertEqual(sq.load_zones(os.path.join(self.sb.dir, 'missing.json')), [])

    def test_update_zones_is_atomic(self):
        def boom(zones):
            zones.append({'output': 'hw:CARD=Gen,DEV=0'})
            raise sq.InvalidField('x', 'y')
        with self.assertRaises(sq.InvalidField):
            sq.update_zones(boom, self.sb.zones)
        self.assertEqual(sq.load_zones(self.sb.zones), [])
        sq.update_zones(lambda zs: zs.append({'output': 'hw:CARD=Gen,DEV=0', 'name': 'Kitchen'}), self.sb.zones)
        self.assertEqual(sq.load_zones(self.sb.zones)[0]['name'], 'Kitchen')

    def test_argv(self):
        z = sq.normalize_zone({'output': 'hw:CARD=D50s,DEV=0', 'name': 'Living room', 'mac': MAC,
                               'server': 'ignored', 'pcm2dsd': 'dsd64'})
        argv = sq.zone_argv(z, '127.0.0.1', self.sb.probe)
        self.assertEqual(argv[0], sq.SQUEEZELITE_BIN)
        self.assertEqual(argv[argv.index('-n') + 1], 'Living room')    # one argument, spaces and all
        self.assertEqual(argv[argv.index('-s') + 1], '127.0.0.1')
        self.assertEqual(argv[argv.index('-m') + 1], MAC)
        self.assertNotIn('-v', argv)                                    # the VU meters are the built-in player's
        self.assertEqual(argv[-2:], ['-c', 'dsd'])
        # following another Lyrion: the zone goes there too, and converts nothing
        argv = sq.zone_argv(z, '192.168.1.50', self.sb.probe)
        self.assertEqual(argv[argv.index('-s') + 1], '192.168.1.50')
        self.assertNotIn('-c', argv)

    def test_card_present(self):
        self.assertTrue(sq.card_present('hw:CARD=D50s,DEV=0', self.sb.asound))
        self.assertFalse(sq.card_present('hw:CARD=Gone,DEV=0', self.sb.asound))
        self.assertFalse(sq.card_present('default', self.sb.asound))

    def test_run_zone_refuses_unknown(self):
        self.assertEqual(sq.run_zone('../etc', self.sb.zones), 64)
        self.assertEqual(sq.run_zone('D50s-0', self.sb.zones), 64)
        sq.save_zones([{'output': 'hw:CARD=D50s,DEV=0', 'enabled': False}], self.sb.zones)
        self.assertEqual(sq.run_zone('D50s-0', self.sb.zones), 64)

    def test_sync_zones(self):
        sq.save_zones([{'output': 'hw:CARD=D50s,DEV=0'}, {'output': 'hw:CARD=Gen,DEV=0', 'enabled': False}],
                      self.sb.zones)
        calls = []
        saved = (sq._systemctl, sq.running_zone_units)
        sq._systemctl = lambda *a: calls.append(a) or subprocess.CompletedProcess(a, 0, '', '')
        sq.running_zone_units = lambda: {'Gen-0', 'Old-0'}
        try:
            sq.sync_zones(self.sb.zones)
        finally:
            sq._systemctl, sq.running_zone_units = saved
        self.assertIn(('stop', 'hifi-zone@Gen-0.service'), calls)
        self.assertIn(('stop', 'hifi-zone@Old-0.service'), calls)
        self.assertIn(('start', '--no-block', 'hifi-zone@D50s-0.service'), calls)


class TestLyrionRules(ToolsMixin, unittest.TestCase):
    def write_main(self, **kw):
        m = self.model(**kw)
        os.makedirs(os.path.dirname(self.sb.conf), exist_ok=True)
        sq.save(m, self.sb.conf)
        os.makedirs(os.path.dirname(self.sb.rules), exist_ok=True)

    def sync(self):
        return sq.sync_pcm2dsd(self.sb.conf, self.sb.zones, self.sb.map, self.sb.rules,
                               self.sb.default, self.sb.dsp_target, self.sb.probe)

    def test_rules_text(self):
        text = sq.lms_rules({MAC: {'mode': 'dsd64', 'filter': 'clans-8'}})
        self.assertTrue(text.startswith(sq.RULES_BEGIN))
        self.assertIn(f'flc dsf * {MAC}\n\t# IFT:', text)
        self.assertIn(f'mp3 dsf * {MAC}\n', text)
        self.assertIn(f'spt dsf * {MAC}\n', text)
        self.assertIn(f'| {sq.PCM2DSD_WRAPPER} $CLIENTID$ raw', text)
        self.assertNotIn('* *\n', text)            # never for every player of the server
        self.assertEqual(sq.lms_rules({}), '')

    def test_merge_keeps_the_owners_rules(self):
        mine = 'ape flc * *\n\t[mac] $FILE$ - -d\n'
        block = sq.lms_rules({MAC: {}})
        merged = sq.merge_rules(mine, block)
        self.assertTrue(merged.startswith(mine))
        self.assertEqual(sq.merge_rules(merged, block), merged)
        self.assertEqual(sq.merge_rules(merged, ''), mine)
        self.assertEqual(sq.merge_rules('', ''), '')

    def test_sync(self):
        self.write_main()
        self.assertFalse(self.sync())                  # off everywhere: nothing to write
        self.assertFalse(os.path.exists(self.sb.rules))
        self.assertFalse(os.path.exists(self.sb.map))
        self.write_main(pcm2dsd='dsd128', pcm2dsd_filter='sdm-8')
        self.assertTrue(self.sync())
        with open(self.sb.map) as f:
            self.assertEqual(json.load(f), {MAC: {'mode': 'dsd128', 'filter': 'clans-8'.replace('clans', 'sdm')}})
        self.assertIn(f'flc dsf * {MAC}', slurp(self.sb.rules))
        # a new rate: the wrapper's map changes, Lyrion's rules do not
        self.write_main(pcm2dsd='dsd64')
        self.assertFalse(self.sync())
        with open(self.sb.map) as f:
            self.assertEqual(json.load(f)[MAC]['mode'], 'dsd64')
        # a zone that converts too, then everything off again
        zmac = sq.zone_mac('hw:CARD=Gen,DEV=0', self.sb.machine_id)
        sq.save_zones([{'output': 'hw:CARD=Gen,DEV=0', 'mac': zmac, 'pcm2dsd': 'dsd64'}], self.sb.zones)
        self.assertTrue(self.sync())
        self.assertIn(f'flc dsf * {zmac}', slurp(self.sb.rules))
        sq.save_zones([{'output': 'hw:CARD=Gen,DEV=0', 'mac': zmac, 'pcm2dsd': 'dsd64', 'enabled': False}],
                      self.sb.zones)
        self.assertTrue(self.sync())
        self.assertNotIn(zmac, slurp(self.sb.rules))
        self.write_main(pcm2dsd='dsd64', server='192.168.1.50')
        self.assertTrue(self.sync())
        self.assertEqual(slurp(self.sb.rules), '')
        with open(self.sb.map) as f:
            self.assertEqual(json.load(f), {})

    def test_no_lyrion_installed(self):
        self.write_main(pcm2dsd='dsd64')
        os.rmdir(os.path.dirname(self.sb.rules))
        self.assertFalse(self.sync())
        self.assertTrue(os.path.exists(self.sb.map))


class TestWrapper(unittest.TestCase):
    def setUp(self):
        self.w = load_wrapper()
        self.dir = tempfile.mkdtemp(prefix='p2d-')
        self.map = os.path.join(self.dir, 'pcm2dsd.json')

    def test_settings(self):
        with open(self.map, 'w') as f:
            json.dump({MAC: {'mode': 'dsd256', 'filter': 'sdm-8'}, '02:00:00:00:00:01': {'mode': 'x'}}, f)
        self.assertEqual(self.w.settings_for('02-aa-bb-cc-dd-ee', self.map), ('dsd256', 'sdm-8'))
        self.assertEqual(self.w.settings_for('02-00-00-00-00-01', self.map), ('dsd64', 'clans-8'))
        self.assertEqual(self.w.settings_for('02-99-99-99-99-99', self.map), ('dsd64', 'clans-8'))
        self.assertEqual(self.w.settings_for(MAC, os.path.join(self.dir, 'none')), ('dsd64', 'clans-8'))

    def test_argv(self):
        a = self.w.sox_argv('wav', 'dsd128', 'clans-8', '/x/sox_ng')
        self.assertEqual(a[0], '/x/sox_ng')
        self.assertEqual(a[a.index('-t') + 1], 'wav')
        self.assertIn('--ignore-length', a)
        i = a.index('dsf')
        self.assertEqual(a[i + 1], '-')
        self.assertEqual(a[i + 2:], ['channels', '2', 'gain', '-6', 'rate', '-v', '5644800', 'sdm', '-f', 'clans-8'])
        r = self.w.sox_argv('raw', 'dsd64', 'sdm-8')
        self.assertEqual(r[r.index('-t') + 1], 'raw')
        self.assertIn('2822400', r)

    def test_usage(self):
        self.assertEqual(self.w.main(['x']), 2)
        self.assertEqual(self.w.main(['x', MAC, 'flac']), 2)


class TestApi(unittest.TestCase):
    """api_server.py's /zones and the PCM to DSD wiring."""

    @classmethod
    def setUpClass(cls):
        import api_server
        cls.api = api_server

    def setUp(self):
        self.sb = ToolsSandbox()
        self.sb.card('D50s', STREAM_NATIVE_BE)
        self.sb.card('Gen', STREAM_PCM_ONLY)
        self.sb.write_default(LEGACY_MAC)
        os.makedirs(os.path.dirname(self.sb.rules), exist_ok=True)
        self._saved = {}
        p = self._patch
        p('SQUEEZELITE_DEFAULT', self.sb.default)
        p('SQUEEZELITE_CONF', self.sb.conf)
        p('DSP_TARGET_FILE', self.sb.dsp_target)
        p('PLAYER_ENABLED_FILE', os.path.join(self.sb.dir, 'player-enabled'))
        p('DSP_STATE_FILE', os.path.join(self.sb.dir, 'dsp.json'))
        p('ZONES_CONF', self.sb.zones)
        p('PCM2DSD_MAP', self.sb.map)
        p('LMS_CONVERT', self.sb.rules)
        p('PCM2DSD_BENCH_FILE', os.path.join(self.sb.dir, 'bench.json'))
        p('_cpu_model', lambda: 'Test CPU x4')
        self.calls = []
        p('_run', self._fake_run)
        devices = {'devices': [{'id': 'default', 'name': 'System default'},
                               {'id': 'hw:CARD=D50s,DEV=0', 'name': 'Topping D50s — USB Audio', 'dsd': 'native'},
                               {'id': 'hw:CARD=Gen,DEV=0', 'name': 'Generic — USB Audio', 'dsd': 'dop'}]}
        p('list_audio_devices', lambda: devices)
        self.sq_calls = []
        self._sq = {k: getattr(sq, k) for k in ('SOX_NG', 'PCM2DSD_WRAPPER', 'PROC_ASOUND', 'MACHINE_ID',
                                                 'mixer_controls', '_systemctl', 'running_zone_units')}
        sq.SOX_NG, sq.PCM2DSD_WRAPPER, sq.PROC_ASOUND = self.sb.sox, self.sb.wrapper, self.sb.asound
        sq.MACHINE_ID = self.sb.machine_id
        sq.mixer_controls = lambda device, run=None: ['PCM'] if 'D50s' in device else []
        sq._systemctl = lambda *a: self.sq_calls.append(a) or subprocess.CompletedProcess(a, 0, '', '')
        sq.running_zone_units = lambda: set()
        # zone_mac() reads MACHINE_ID through its default argument
        self._zone_mac = sq.zone_mac
        sq.zone_mac = lambda output, machine_id_path=self.sb.machine_id: self._zone_mac(output, machine_id_path)
        self.bench({'dsd64': 0.22, 'dsd128': 0.47, 'dsd256': 1.0})

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(self.api, name, value)
        for k, v in self._sq.items():
            setattr(sq, k, v)
        sq.zone_mac = self._zone_mac

    def _patch(self, name, value):
        self._saved[name] = getattr(self.api, name)
        setattr(self.api, name, value)

    def _fake_run(self, cmd, timeout=20):
        self.calls.append(list(cmd))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout='', stderr='')

    def bench(self, result):
        with open(self.api.PCM2DSD_BENCH_FILE, 'w') as f:
            json.dump({'v': self.api.PCM2DSD_BENCH_VERSION, 'cpu': 'Test CPU x4', 'result': result}, f)

    def lyrion_restarts(self):
        return [c for c in self.calls if c[:3] == ['systemctl', 'restart', 'lyrionmusicserver']]

    def test_modes_follow_the_cpu(self):
        self.assertEqual(self.api._pcm2dsd_modes(), (['off', 'dsd64', 'dsd128'], True))
        self.bench({'dsd64': 0.1, 'dsd128': 0.2, 'dsd256': 0.4})
        self.assertEqual(self.api._pcm2dsd_modes()[0], ['off', 'dsd64', 'dsd128', 'dsd256'])
        # a measurement of the old kind is not trusted: taken again
        with open(self.api.PCM2DSD_BENCH_FILE, 'w') as f:
            json.dump({'cpu': 'Test CPU x4', 'result': {'dsd64': 0.97}}, f)
        os.unlink(self.sb.sox)                      # no sox_ng: nothing measured, no thread
        self.assertEqual(self.api._pcm2dsd_modes(), (['off', 'dsd64', 'dsd128'], False))
        os.unlink(self.api.PCM2DSD_BENCH_FILE)
        self.assertEqual(self.api._pcm2dsd_modes(), (['off', 'dsd64', 'dsd128'], False))

    def test_conf_turns_conversion_on_and_off(self):
        g = self.api.get_squeezelite_conf()
        self.assertEqual(g['pcm2dsd']['state'], 'off')
        self.assertEqual(g['pcm2dsd']['modes'], ['off', 'dsd64', 'dsd128'])
        r = self.api.set_squeezelite_conf({'pcm2dsd': 'dsd256'})
        self.assertFalse(r['success'])
        self.assertEqual(r['code'], 'squeezelite.pcm2dsdTooHeavy')
        r = self.api.set_squeezelite_conf({'pcm2dsd': 'dsd128'})
        self.assertTrue(r['success'], r)
        self.assertTrue(r['lyrion_restarted'])
        self.assertEqual(r['pcm2dsd']['state'], 'active')
        self.assertIn('-c dsd', self.sb.args())
        self.assertEqual(len(self.lyrion_restarts()), 1)
        self.assertIn('flc dsf * 02:ab:cd:ef:01:23', slurp(self.sb.rules))
        # a new filter: no Lyrion restart
        r = self.api.set_squeezelite_conf({'pcm2dsd_filter': 'sdm-8'})
        self.assertNotIn('lyrion_restarted', r)
        self.assertEqual(len(self.lyrion_restarts()), 1)
        r = self.api.set_squeezelite_conf({'pcm2dsd': 'off'})
        self.assertTrue(r['lyrion_restarted'])
        self.assertNotIn('-c dsd', self.sb.args())
        self.assertNotIn('flc dsf', slurp(self.sb.rules))

    def test_zone_lifecycle(self):
        g = self.api.get_zones()
        self.assertEqual(g['zones'], [])
        # the built-in player plays the D50s (LEGACY): only the Gen is free
        self.assertEqual([d['id'] for d in g['free']], ['hw:CARD=Gen,DEV=0'])
        self.assertFalse(self.api.zone_add('hw:CARD=D50s,DEV=0')['success'])
        self.assertFalse(self.api.zone_add('hw:CARD=Gen,DEV=0', 'bad"name')['success'])
        r = self.api.zone_add('hw:CARD=Gen,DEV=0')
        self.assertTrue(r['success'], r)
        z = r['zones'][0]
        self.assertEqual((z['id'], z['name'], z['enabled']), ('Gen-0', 'Generic', True))
        self.assertIn(('start', '--no-block', 'hifi-zone@Gen-0.service'), self.sq_calls)
        self.assertEqual(r['free'], [])
        # the built-in player cannot take the zone's DAC
        r2 = self.api.set_audio_device('hw:CARD=Gen,DEV=0')
        self.assertEqual(r2['code'], 'zones.dacInUse')
        # rename, a DSD conversion, then off
        sq.running_zone_units = lambda: {'Gen-0'}
        r = self.api.zone_update('Gen-0', {'name': 'Kitchen', 'pcm2dsd': 'dsd64'})
        self.assertTrue(r['success'], r)
        self.assertTrue(r['lyrion_restarted'])
        z = r['zones'][0]
        self.assertEqual((z['name'], z['conf']['pcm2dsd'], z['pcm2dsd_state']), ('Kitchen', 'dsd64', 'active'))
        self.assertIn(('restart', '--no-block', 'hifi-zone@Gen-0.service'), self.sq_calls)
        # a new rate: the zone keeps playing, Lyrion is not restarted either
        self.sq_calls.clear()
        lyrion = len(self.lyrion_restarts())
        r = self.api.zone_update('Gen-0', {'pcm2dsd': 'dsd128'})
        self.assertEqual(r['zones'][0]['conf']['pcm2dsd'], 'dsd128')
        self.assertFalse(r['lyrion_restarted'])
        self.assertEqual(len(self.lyrion_restarts()), lyrion)
        self.assertNotIn(('restart', '--no-block', 'hifi-zone@Gen-0.service'), self.sq_calls)
        zmac = sq.load_zones(self.sb.zones)[0]['mac']
        self.assertIn(f'flc dsf * {zmac}', slurp(self.sb.rules))
        for bad in ({'nope': 1}, {'pcm2dsd': 'dsd256'}, {'name': ''}, {'volume': 'hardware'}):
            self.assertFalse(self.api.zone_update('Gen-0', bad)['success'], bad)
        self.assertFalse(self.api.zone_update('Nope-0', {'enabled': False})['success'])
        r = self.api.zone_update('Gen-0', {'enabled': False})
        self.assertFalse(r['zones'][0]['enabled'])
        self.assertIn(('stop', 'hifi-zone@Gen-0.service'), self.sq_calls)
        self.assertIn(('reset-failed', 'hifi-zone@Gen-0.service'), self.sq_calls)
        self.assertNotIn(zmac, slurp(self.sb.rules))
        r = self.api.zone_remove('Gen-0')
        self.assertTrue(r['success'])
        self.assertEqual(r['zones'], [])
        self.assertFalse(self.api.zone_remove('Gen-0')['success'])

    def test_follow_mode_restarts_the_zones(self):
        self.api.zone_add('hw:CARD=Gen,DEV=0')
        sq.running_zone_units = lambda: {'Gen-0'}
        self._patch('_set_local_lyrion_enabled', lambda on: None)
        self.api.set_lms_role('local', None)
        self.assertIn(('restart', '--no-block', 'hifi-zone@Gen-0.service'), self.sq_calls)


if __name__ == '__main__':
    unittest.main()
