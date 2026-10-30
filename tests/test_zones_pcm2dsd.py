"""Tests for the audio zones (one more player per DAC) and the per-player
conversion: hifi_squeezelite.py's model, renderer, zones file and the pure
rule helpers, the wrapper the Osmium Convert plugin runs (hifi-pcm2dsd.py),
and api_server.py's /zones and Settings → Audio wiring.

Conversion is driven by the Osmium Convert LMS plugin now: the box sends it
`osmiumconvert set|clear <mac> ...` over jsonrpc.js on whichever Lyrion the
player follows, and the plugin writes the rules and reloads the tables with no
restart. The box no longer writes custom-convert.conf itself, so the API tests
assert on the plugin commands (a fake `_lms_rpc`) rather than on a rules file.

Hermetic: every file lives in a temporary directory; systemctl, amixer, the
CPU measurement and the plugin RPC are fakes.

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
    """A Sandbox where sox_ng and the wrappers "are installed"."""

    def __init__(self):
        super().__init__()
        self.sox = os.path.join(self.dir, 'sox_ng')
        self.wrapper = os.path.join(self.dir, 'hifi-pcm2dsd.py')
        self.upsample_wrapper = os.path.join(self.dir, 'hifi-upsample.py')
        self.flac = os.path.join(self.dir, 'flac')
        for path in (self.sox, self.wrapper, self.upsample_wrapper, self.flac):
            with open(path, 'w') as f:
                f.write('#!/bin/sh\n')
            os.chmod(path, 0o755)
        self.external = os.path.join(self.dir, 'hifi-player', 'external-convert.json')
        self.upsample_map = os.path.join(self.dir, 'hifi-player', 'upsample.json')
        self.zones = os.path.join(self.dir, 'hifi-player', 'zones.json')
        self.map = os.path.join(self.dir, 'hifi-player', 'pcm2dsd.json')
        self.rules = os.path.join(self.dir, 'squeezeboxserver', 'custom-convert.conf')
        self.machine_id = os.path.join(self.dir, 'machine-id')
        with open(self.machine_id, 'w') as f:
            f.write('0123456789abcdef0123456789abcdef\n')


class ToolsMixin:
    PATCHED = ('SOX_NG', 'PCM2DSD_WRAPPER', 'UPSAMPLE_WRAPPER', 'FLAC_BIN', 'PROC_ASOUND', '_systemctl')

    def setUp(self):
        self.sb = ToolsSandbox()
        self.sb.card('D50s', STREAM_NATIVE_BE)
        self.sb.card('Gen', STREAM_PCM_ONLY)
        self._sq = {k: getattr(sq, k) for k in self.PATCHED}
        self.systemctl = []
        sq.SOX_NG, sq.PCM2DSD_WRAPPER, sq.PROC_ASOUND = self.sb.sox, self.sb.wrapper, self.sb.asound
        sq.UPSAMPLE_WRAPPER = self.sb.upsample_wrapper
        sq.FLAC_BIN = self.sb.flac
        sq._systemctl = lambda *a: self.systemctl.append(a) or subprocess.CompletedProcess(a, 0, '', '')

    def tearDown(self):
        for k, v in self._sq.items():
            setattr(sq, k, v)

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
        # enabling the conversion forces the DSD mode to auto (off would make the
        # DAC re-decode the converted DSF to PCM); an explicit dop/native stays
        self.assertEqual(sq.set_fields(sq.normalize({'dsd': 'off'}), {'pcm2dsd': 'dsd64'})['dsd'], 'auto')
        self.assertEqual(sq.set_fields(sq.normalize({'dsd': 'dop'}), {'pcm2dsd': 'dsd64'})['dsd'], 'dop')
        self.assertEqual(sq.normalize({'pcm2dsd': 'dsd64', 'dsd': 'off'})['dsd'], 'auto')
        for bad in ({'pcm2dsd': 'dsd1024'}, {'pcm2dsd_filter': 'clans-3'}, {'pcm2dsd': True}):
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
        # a remote server converts server-side too now (its Osmium Convert
        # plugin), for the built-in player and for a zone alike
        self.assertEqual(sq.pcm2dsd_state(self.model(pcm2dsd='dsd64', server='192.168.1.9'), 'u32be'), 'active')
        self.assertEqual(sq.pcm2dsd_state(self.model(pcm2dsd='dsd64', server='192.168.1.9'), 'u32be', zone=True),
                         'active')
        self.assertEqual(sq.pcm2dsd_state(self.model(pcm2dsd='dsd64', dsp={'enabled': True}), 'u32be'), 'dsp')
        # enabling the conversion forces the DSD mode to auto, so a stale dsd=off
        # can no longer silence it; only a DAC with no DSD at all stays noDsd
        self.assertEqual(sq.pcm2dsd_state(self.model(pcm2dsd='dsd64', dsd='off'), 'u32be'), 'active')
        self.assertEqual(sq.pcm2dsd_state(self.model(pcm2dsd='dsd64'), sq.PCM_ONLY), 'noDsd')
        # a USB DAC without native DSD gets DoP: still DSD
        self.assertEqual(sq.pcm2dsd_state(self.model(pcm2dsd='dsd64', output='hw:CARD=Gen,DEV=0'),
                                          probe('hw:CARD=Gen,DEV=0')), 'active')
        os.unlink(self.sb.sox)
        self.assertEqual(sq.pcm2dsd_state(self.model(pcm2dsd='dsd64'), 'u32be'), 'noTools')

    def test_upsample_state(self):
        self.assertEqual(sq.upsample_state(self.model()), 'off')
        self.assertEqual(sq.upsample_state(self.model(upsample='x4')), 'active')
        # remote server upsamples too; no 'noDsd' for PCM
        self.assertEqual(sq.upsample_state(self.model(upsample='x4', server='192.168.1.9')), 'active')
        self.assertEqual(sq.upsample_state(self.model(upsample='x4', dsp={'enabled': True})), 'dsp')
        os.unlink(self.sb.sox)
        self.assertEqual(sq.upsample_state(self.model(upsample='x4')), 'noTools')

    def test_render(self):
        args = sq.render(self.model(pcm2dsd='dsd128'), self.sb.probe)
        self.assertIn('-D :u32be', args)
        self.assertTrue(args.endswith('-b 16384:8192 -c dsd'), args)
        self.assertEqual(args.count('-b '), 1)
        args = sq.render(self.model(pcm2dsd='dsd128', stream_buffer='large', extra='-W'), self.sb.probe)
        self.assertEqual(args.count('-b '), 1)
        self.assertTrue(args.endswith('-c dsd -W'), args)
        # a remote server converts too now: -c dsd there as well
        self.assertIn('-c dsd', sq.render(self.model(pcm2dsd='dsd64', server='nas.local'), self.sb.probe))
        # off: nothing changes
        self.assertNotIn('-c dsd', sq.render(self.model(), self.sb.probe))
        # enabling the conversion forces the DSD mode to auto even if dsd=off was
        # stored, so the player still passes DSD (-D) and converts (-c dsd)
        forced = sq.render(self.model(pcm2dsd='dsd64', dsd='off'), self.sb.probe)
        self.assertIn('-c dsd', forced)
        self.assertIn('-D :u32be', forced)
        # the legacy line is unchanged by the refactor
        self.assertEqual(sq.render(sq.parse_args(LEGACY), lambda d: 'dop'), LEGACY)


class TestPlayerSideConvert(ToolsMixin, unittest.TestCase):
    """convert_where == 'player': the built-in player converts on its own
    squeezelite (PCM into the Loopback, hifi-pcm2dsd-player.py to the DAC)
    instead of letting the followed Lyrion do it."""

    PATCHED = ToolsMixin.PATCHED + ('P2D_PLAYER', 'SYS_ALOOP')

    def setUp(self):
        super().setUp()
        # the converter daemon "is installed" and the Loopback "is loadable"
        sq.P2D_PLAYER, sq.SYS_ALOOP = self.sb.wrapper, self.sb.dir

    def test_normalize_and_set_fields(self):
        self.assertEqual(sq.normalize({})['convert_where'], 'server')
        self.assertEqual(sq.normalize({'convert_where': 'PLAYER'})['convert_where'], 'player')
        self.assertEqual(sq.normalize({'convert_where': 'nonsense'})['convert_where'], 'server')
        m = sq.set_fields(sq.normalize({}), {'convert_where': 'player'})
        self.assertEqual(m['convert_where'], 'player')
        with self.assertRaises(sq.InvalidField):
            sq.set_fields(sq.normalize({}), {'convert_where': 'cloud'})

    def test_state_gates_on_player_side(self):
        probe = self.sb.probe
        fmt = probe('hw:CARD=D50s,DEV=0')
        base = self.model(pcm2dsd='dsd128', convert_where='player')
        self.assertEqual(sq.pcm2dsd_state(base, fmt), 'active')
        # no converter daemon on this box: the player side cannot run
        sq.P2D_PLAYER = os.path.join(self.sb.dir, 'absent')
        self.assertEqual(sq.pcm2dsd_state(base, fmt), 'noTools')
        # the server side is unaffected by the missing daemon
        self.assertEqual(sq.pcm2dsd_state(self.model(pcm2dsd='dsd128'), fmt), 'active')
        # a zone always converts server-side, so the daemon is irrelevant
        self.assertEqual(sq.pcm2dsd_state(base, fmt, zone=True), 'active')

    def test_render_routes_to_loopback(self):
        args = sq.render(self.model(pcm2dsd='dsd128', convert_where='player'), self.sb.probe)
        self.assertIn('-o ' + sq.P2D_PLAYBACK, args)
        self.assertIn(f'-r {sq.P2D_RATE} -R', args)
        self.assertNotIn('-c dsd', args)   # ordinary PCM, converted here
        self.assertNotIn('-D', args)
        self.assertNotIn(sq.STREAM_LARGE, args)
        # server-side (default) still sends DSD and the larger stream buffer
        srv = sq.render(self.model(pcm2dsd='dsd128'), self.sb.probe)
        self.assertIn('-c dsd', srv)
        self.assertIn('-o hw:CARD=D50s,DEV=0', srv)

    def test_player_conf(self):
        probe = self.sb.probe
        fmt = probe('hw:CARD=D50s,DEV=0')
        self.assertIsNone(sq.player_conf(self.model(pcm2dsd='dsd128'), fmt))
        self.assertIsNone(sq.player_conf(self.model(convert_where='player'), fmt))
        c = sq.player_conf(self.model(pcm2dsd='dsd128', convert_where='player'), fmt)
        self.assertEqual((c['mode'], c['filter'], c['rate']), ('dsd128', 'clans-8', sq.P2D_RATE))
        self.assertEqual(c['carrier'], fmt)        # D50s declares native DSD
        self.assertEqual(c['dac'], 'hw:CARD=D50s,DEV=0')

    def test_sync_player_starts_and_stops(self):
        conf = os.path.join(self.sb.dir, 'player.json')
        calls = []
        sc = lambda *a: calls.append(a)
        mp = lambda: calls.append(('modprobe',))
        # player side on: conf written, the unit started
        self.assertTrue(sq.sync_player(self.model(pcm2dsd='dsd128', convert_where='player'),
                                       self.sb.probe, conf, systemctl=sc, modprobe=mp))
        self.assertTrue(os.path.exists(conf))
        self.assertIn(('start', '--no-block', sq.P2D_PLAYER_UNIT), calls)
        # back to server-side: conf removed, the unit stopped
        calls.clear()
        self.assertFalse(sq.sync_player(self.model(pcm2dsd='dsd128'),
                                        self.sb.probe, conf, systemctl=sc, modprobe=mp))
        self.assertFalse(os.path.exists(conf))
        self.assertIn(('stop', sq.P2D_PLAYER_UNIT), calls)


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
        # following another Lyrion: the zone goes there too, and that server
        # converts for it (its Osmium Convert plugin), so -c dsd stays
        argv = sq.zone_argv(z, '192.168.1.50', self.sb.probe)
        self.assertEqual(argv[argv.index('-s') + 1], '192.168.1.50')
        self.assertEqual(argv[-2:], ['-c', 'dsd'])

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


class TestConvertPlayers(ToolsMixin, unittest.TestCase):
    """convert_players() / external_players(): what the box asks the plugin to
    set for each MAC it owns, and the pure rule/map helpers."""

    def test_convert_players_box_and_zones(self):
        main = self.model(pcm2dsd='dsd64')
        zmac = sq.zone_mac('hw:CARD=Gen,DEV=0', self.sb.machine_id)
        zones = [sq.normalize_zone({'output': 'hw:CARD=Gen,DEV=0', 'mac': zmac, 'upsample': 'x2', 'enabled': True}),
                 sq.normalize_zone({'output': 'hw:CARD=D50s,DEV=0', 'mac': 'de:ad:be:ef:00:01',
                                    'pcm2dsd': 'dsd128', 'enabled': False})]
        players = sq.convert_players(main, zones, external=None, probe_fn=self.sb.probe)
        self.assertEqual(players[MAC], {'kind': 'dsd', 'mode': 'dsd64', 'filter': 'clans-8'})
        self.assertEqual(players[zmac]['kind'], 'pcm')
        self.assertEqual(players[zmac]['mult'], 'x2')
        self.assertNotIn('de:ad:be:ef:00:01', players)       # disabled zone: no rule

    def test_external_players(self):
        ext = {'00:11:22:33:44:55': {'pcm2dsd': 'dsd64', 'pcm2dsd_filter': 'sdm-8',
                                     'upsample': 'off', 'upsample_cap': 0},
               '00:11:22:33:44:66': {'pcm2dsd': 'off', 'upsample': 'x4', 'upsample_cap': 96000}}
        out = sq.external_players(ext)
        self.assertEqual(out['00:11:22:33:44:55'], {'kind': 'dsd', 'mode': 'dsd64', 'filter': 'sdm-8'})
        self.assertEqual(out['00:11:22:33:44:66'], {'kind': 'pcm', 'mult': 'x4', 'cap': 96000})

    def test_rules_text(self):
        text = sq.lms_rules({MAC: {'kind': 'dsd', 'mode': 'dsd64', 'filter': 'clans-8'}})
        self.assertTrue(text.startswith(sq.RULES_BEGIN))
        self.assertIn(f'flc dsf * {MAC}\n\t# IFT:', text)
        self.assertIn(f'mp3 dsf * {MAC}\n', text)
        self.assertIn(f'spt dsf * {MAC}\n', text)
        self.assertIn(f'| {sq.PCM2DSD_WRAPPER} $CLIENTID$ raw', text)
        self.assertNotIn('* *\n', text)            # never for every player of the server
        self.assertEqual(sq.lms_rules({}), '')

    def test_rules_text_pcm_upsample(self):
        text = sq.lms_rules({MAC: {'kind': 'pcm', 'mult': 'x4', 'cap': 0}})
        self.assertTrue(text.startswith(sq.RULES_BEGIN))
        self.assertIn(f'flc flc * {MAC}\n\t# IFT:', text)   # FLAC in, FLAC out
        self.assertIn(f'spt flc * {MAC}\n', text)
        self.assertIn(f'| {sq.UPSAMPLE_WRAPPER} $CLIENTID$ raw', text)
        self.assertNotIn('dsf', text)              # no DSD for a PCM upsampling player
        self.assertNotIn('* *\n', text)

    def test_merge_keeps_the_owners_rules(self):
        mine = 'ape flc * *\n\t[mac] $FILE$ - -d\n'
        block = sq.lms_rules({MAC: {'kind': 'dsd', 'mode': 'dsd64', 'filter': 'clans-8'}})
        merged = sq.merge_rules(mine, block)
        self.assertTrue(merged.startswith(mine))
        self.assertEqual(sq.merge_rules(merged, block), merged)
        self.assertEqual(sq.merge_rules(merged, ''), mine)
        self.assertEqual(sq.merge_rules('', ''), '')


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
    """api_server.py's /zones and the per-player conversion wiring. The plugin
    RPC is a fake that records every `osmiumconvert` command."""

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
        # the plugin RPC: record every command, answer `status` as a healthy
        # local server (sox_ng + sdm present).
        self.rpc = []
        p('_lms_rpc', self._fake_rpc)
        devices = {'devices': [{'id': 'default', 'name': 'System default'},
                               {'id': 'hw:CARD=D50s,DEV=0', 'name': 'Topping D50s — USB Audio', 'dsd': 'native'},
                               {'id': 'hw:CARD=Gen,DEV=0', 'name': 'Generic — USB Audio', 'dsd': 'dop'}]}
        p('list_audio_devices', lambda: devices)
        self.sq_calls = []
        p('UPSAMPLE_MAP', self.sb.upsample_map)
        p('EXTERNAL_CONVERT', self.sb.external)
        self._sq = {k: getattr(sq, k) for k in ('SOX_NG', 'PCM2DSD_WRAPPER', 'UPSAMPLE_WRAPPER',
                                                 'FLAC_BIN', 'PROC_ASOUND', 'MACHINE_ID',
                                                 'mixer_controls', '_systemctl', 'running_zone_units')}
        sq.SOX_NG, sq.PCM2DSD_WRAPPER, sq.PROC_ASOUND = self.sb.sox, self.sb.wrapper, self.sb.asound
        sq.UPSAMPLE_WRAPPER = self.sb.upsample_wrapper
        sq.FLAC_BIN = self.sb.flac
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

    def _fake_rpc(self, host, playerid, command, timeout=5):
        command = list(command)
        self.rpc.append((host, command))
        if command[:2] == ['osmiumconvert', 'status']:
            return {'has_sox': 1, 'has_sox_ng': 1, 'has_sdm': 1, 'dsd': 1, 'upsample': 1, 'count': 0}
        return {'ok': 1}

    def convert_cmds(self):
        """(host, command) of the set/clear commands sent so far."""
        return [(h, c) for h, c in self.rpc
                if len(c) >= 2 and c[0] == 'osmiumconvert' and c[1] in ('set', 'clear')]

    def last_for(self, mac):
        """The latest set/clear command for `mac` as (host, command), or None."""
        mac = mac.lower()
        for h, c in reversed(self.convert_cmds()):
            if len(c) >= 3 and c[2].lower() == mac:
                return (h, c)
        return None

    def bench(self, result):
        with open(self.api.PCM2DSD_BENCH_FILE, 'w') as f:
            json.dump({'v': self.api.PCM2DSD_BENCH_VERSION, 'cpu': 'Test CPU x4', 'result': result}, f)

    def test_modes_ignore_cpu_during_trial(self):
        # TRIAL (.133/.105): CPU gating is disabled by request — every DSD mode
        # up to the DSD512 ceiling is always offered, regardless of the measured
        # cost or whether sox_ng is present to measure it.
        full = ['off', 'dsd64', 'dsd128', 'dsd256', 'dsd512']
        self.assertEqual(self.api._pcm2dsd_modes(), (full, True))
        self.bench({'dsd64': 0.1, 'dsd128': 0.2, 'dsd256': 0.4})
        self.assertEqual(self.api._pcm2dsd_modes(), (full, True))
        os.unlink(self.sb.sox)                      # no sox_ng: still the full set
        self.assertEqual(self.api._pcm2dsd_modes(), (full, True))
        os.unlink(self.api.PCM2DSD_BENCH_FILE)
        self.assertEqual(self.api._pcm2dsd_modes(), (full, True))

    def test_conf_turns_conversion_on_and_off(self):
        g = self.api.get_squeezelite_conf()
        self.assertEqual(g['pcm2dsd']['state'], 'off')
        self.assertEqual(g['pcm2dsd']['modes'], ['off', 'dsd64', 'dsd128', 'dsd256', 'dsd512'])
        mac = self.api._own_player_mac()
        self.assertTrue(mac)
        # a mode past the DSD512 ceiling is refused (not an offered mode)
        r = self.api.set_squeezelite_conf({'pcm2dsd': 'dsd1024'})
        self.assertFalse(r['success'])
        self.assertEqual(r['code'], 'squeezelite.pcm2dsdTooHeavy')
        # on: the box tells the local plugin to convert this MAC to DSD
        self.rpc.clear()
        r = self.api.set_squeezelite_conf({'pcm2dsd': 'dsd128'})
        self.assertTrue(r['success'], r)
        self.assertEqual(r['pcm2dsd']['state'], 'active')
        self.assertIn('-c dsd', self.sb.args())
        self.assertEqual(self.last_for(mac),
                         ('127.0.0.1', ['osmiumconvert', 'set', mac, 'dsd', 'dsd128', 'clans-8']))
        # a new filter: another set with the new rule
        self.rpc.clear()
        r = self.api.set_squeezelite_conf({'pcm2dsd_filter': 'sdm-8'})
        self.assertTrue(r['success'], r)
        self.assertEqual(self.last_for(mac),
                         ('127.0.0.1', ['osmiumconvert', 'set', mac, 'dsd', 'dsd128', 'sdm-8']))
        # off: the rule is cleared
        self.rpc.clear()
        r = self.api.set_squeezelite_conf({'pcm2dsd': 'off'})
        self.assertTrue(r['success'], r)
        self.assertNotIn('-c dsd', self.sb.args())
        self.assertEqual(self.last_for(mac), ('127.0.0.1', ['osmiumconvert', 'clear', mac]))

    def test_conf_pcm_upsampling(self):
        g = self.api.get_squeezelite_conf()
        self.assertEqual(g['pcm2dsd']['upsample']['state'], 'off')
        self.assertIn('max', g['pcm2dsd']['upsample']['modes'])
        mac = self.api._own_player_mac()
        self.rpc.clear()
        r = self.api.set_squeezelite_conf({'upsample': 'x4'})
        self.assertTrue(r['success'], r)
        self.assertEqual(r['pcm2dsd']['upsample']['state'], 'active')
        host, cmd = self.last_for(mac)
        self.assertEqual(host, '127.0.0.1')
        self.assertEqual(cmd[:5], ['osmiumconvert', 'set', mac, 'pcm', 'x4'])
        # DSD and upsampling are mutually exclusive: turning DSD on switches the
        # rule to a DSD one
        self.rpc.clear()
        r = self.api.set_squeezelite_conf({'pcm2dsd': 'dsd64'})
        self.assertTrue(r['success'], r)
        self.assertEqual(r['conf']['upsample'], 'off')
        self.assertEqual(self.last_for(mac),
                         ('127.0.0.1', ['osmiumconvert', 'set', mac, 'dsd', 'dsd64', 'clans-8']))
        self.rpc.clear()
        r = self.api.set_squeezelite_conf({'upsample': 'off', 'pcm2dsd': 'off'})
        self.assertEqual(self.last_for(mac), ('127.0.0.1', ['osmiumconvert', 'clear', mac]))

    def test_conf_exposes_server_capabilities(self):
        g = self.api.get_squeezelite_conf()
        self.assertEqual(g['pcm2dsd']['convert'],
                         {'plugin': True, 'dsd': True, 'upsample': True, 'why': None})

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
        zmac = sq.load_zones(self.sb.zones)[0]['mac']
        # rename + a DSD conversion: the zone unit restarts, the plugin is told
        sq.running_zone_units = lambda: {'Gen-0'}
        self.rpc.clear()
        r = self.api.zone_update('Gen-0', {'name': 'Kitchen', 'pcm2dsd': 'dsd64'})
        self.assertTrue(r['success'], r)
        self.assertNotIn('lyrion_restarted', r)
        z = r['zones'][0]
        self.assertEqual((z['name'], z['conf']['pcm2dsd'], z['pcm2dsd_state']), ('Kitchen', 'dsd64', 'active'))
        self.assertIn(('restart', '--no-block', 'hifi-zone@Gen-0.service'), self.sq_calls)
        self.assertEqual(self.last_for(zmac),
                         ('127.0.0.1', ['osmiumconvert', 'set', zmac, 'dsd', 'dsd64', 'clans-8']))
        # a new rate: the zone keeps playing (same command line), the plugin
        # just gets the new rule
        self.sq_calls.clear()
        self.rpc.clear()
        r = self.api.zone_update('Gen-0', {'pcm2dsd': 'dsd128'})
        self.assertEqual(r['zones'][0]['conf']['pcm2dsd'], 'dsd128')
        self.assertNotIn(('restart', '--no-block', 'hifi-zone@Gen-0.service'), self.sq_calls)
        self.assertEqual(self.last_for(zmac),
                         ('127.0.0.1', ['osmiumconvert', 'set', zmac, 'dsd', 'dsd128', 'clans-8']))
        for bad in ({'nope': 1}, {'pcm2dsd': 'dsd1024'}, {'name': ''}, {'volume': 'hardware'}):
            self.assertFalse(self.api.zone_update('Gen-0', bad)['success'], bad)
        self.assertFalse(self.api.zone_update('Nope-0', {'enabled': False})['success'])
        # disabled: the unit stops and the rule is cleared
        self.rpc.clear()
        r = self.api.zone_update('Gen-0', {'enabled': False})
        self.assertFalse(r['zones'][0]['enabled'])
        self.assertIn(('stop', 'hifi-zone@Gen-0.service'), self.sq_calls)
        self.assertIn(('reset-failed', 'hifi-zone@Gen-0.service'), self.sq_calls)
        self.assertEqual(self.last_for(zmac), ('127.0.0.1', ['osmiumconvert', 'clear', zmac]))
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

    def test_follow_remote_clears_rules_on_the_old_server(self):
        # Moving the player to a remote Lyrion clears the box's rules on the
        # server it is leaving (127.0.0.1) and resyncs on the new one.
        self.api.set_squeezelite_conf({'pcm2dsd': 'dsd64'})
        mac = self.api._own_player_mac()
        self._patch('_set_local_lyrion_enabled', lambda on: None)
        self._patch('_valid_ipv4', lambda h: True)
        self._patch('_own_host_names', lambda: set())
        self._patch('_lookup_host', lambda h, timeout=5: {'192.168.1.50'})
        self._patch('_is_own_address', lambda a: False)
        self.rpc.clear()
        r = self.api.set_lms_role('follow', '192.168.1.50')
        self.assertTrue(r['success'], r)
        cmds = self.convert_cmds()
        self.assertIn(('127.0.0.1', ['osmiumconvert', 'clear', mac]), cmds)
        self.assertIn(('192.168.1.50', ['osmiumconvert', 'set', mac, 'dsd', 'dsd64', 'clans-8']), cmds)


class TestExternalConvert(TestApi):
    """api_server.py's /external_convert: the list of external players, their
    saved conversion choice, update and remove. Reuses TestApi's sandbox."""

    EXT = '00:11:22:33:44:55'

    def own(self):
        return self.api._own_player_mac()

    def serverstatus(self, players):
        self._patch('_lms_request', lambda pid, cmd, timeout=5: {'players_loop': players})

    def with_own(self, *extra):
        own = {'playerid': self.own(), 'name': 'Osmium', 'ip': '127.0.0.1:40000', 'connected': 1}
        self.serverstatus([own, *extra])

    def ext_player(self, **kw):
        return dict({'playerid': self.EXT, 'name': 'Studio', 'ip': '192.168.1.9:3483',
                     'connected': 1, 'modelname': 'squeezelite'}, **kw)

    def test_list_excludes_this_boxs_own_players(self):
        self.with_own(self.ext_player())
        g = self.api.get_external_convert()
        self.assertTrue(g['lyrion'])
        macs = [p['mac'] for p in g['players']]
        self.assertEqual(macs, [self.EXT])
        self.assertNotIn(self.own(), macs)
        self.assertEqual(g['players'][0]['conf']['upsample'], 'off')
        self.assertIn('max', g['info']['upsample']['modes'])
        self.assertEqual(g['info']['convert']['plugin'], True)

    def test_list_excludes_other_osmium_devices(self):
        # another Osmium player (modelname 'Osmium') following this Lyrion is
        # not a third-party client: it configures conversion from its own UI, so
        # it must not show in the external-players list.
        other = {'playerid': '02:aa:aa:aa:aa:aa', 'name': 'cameretta',
                 'ip': '192.168.0.105:3483', 'connected': 1, 'modelname': 'Osmium'}
        self.with_own(other, self.ext_player())
        g = self.api.get_external_convert()
        macs = [p['mac'] for p in g['players']]
        self.assertEqual(macs, [self.EXT])

    def test_unreachable_server(self):
        def boom(*a, **k):
            raise OSError('down')
        self._patch('_lms_request', boom)
        g = self.api.get_external_convert()
        self.assertFalse(g['success'])
        self.assertEqual(g['code'], 'lms.unreachable')
        self.assertFalse(g['lyrion'])
        self.assertEqual(g['players'], [])

    def test_update_persists_and_pushes_to_the_local_plugin(self):
        self.with_own(self.ext_player())
        self.rpc.clear()
        r = self.api.update_external_convert({'mac': self.EXT, 'name': 'Studio', 'upsample': 'x2'})
        self.assertTrue(r['success'], r)
        self.assertNotIn('lyrion_restarted', r)
        host, cmd = self.last_for(self.EXT)
        self.assertEqual(host, '127.0.0.1')
        self.assertEqual(cmd[:5], ['osmiumconvert', 'set', self.EXT, 'pcm', 'x2'])
        row = [p for p in r['players'] if p['mac'] == self.EXT][0]
        self.assertEqual(row['conf']['upsample'], 'x2')
        # the same player, now to DSD: the plugin is told a DSD rule instead
        self.rpc.clear()
        r = self.api.update_external_convert({'mac': self.EXT, 'pcm2dsd': 'dsd64'})
        self.assertTrue(r['success'], r)
        self.assertEqual(self.last_for(self.EXT),
                         ('127.0.0.1', ['osmiumconvert', 'set', self.EXT, 'dsd', 'dsd64', 'clans-8']))

    def test_update_rejects_bad_mac(self):
        self.with_own(self.ext_player())
        self.assertFalse(self.api.update_external_convert({'mac': 'nope', 'upsample': 'x2'})['success'])

    def test_update_with_both_prefers_dsd(self):
        # DSD and upsampling cannot both be on: asking for both keeps DSD (as
        # set_fields does for every player), never a conflict error.
        self.with_own(self.ext_player())
        self.rpc.clear()
        r = self.api.update_external_convert({'mac': self.EXT, 'pcm2dsd': 'dsd64', 'upsample': 'x2'})
        self.assertTrue(r['success'], r)
        self.assertEqual(self.last_for(self.EXT),
                         ('127.0.0.1', ['osmiumconvert', 'set', self.EXT, 'dsd', 'dsd64', 'clans-8']))

    def test_remove_clears_the_rule(self):
        self.with_own(self.ext_player())
        self.api.update_external_convert({'mac': self.EXT, 'upsample': 'x2'})
        self.rpc.clear()
        r = self.api.remove_external_convert({'mac': self.EXT})
        self.assertTrue(r['success'])
        self.assertEqual(self.last_for(self.EXT), ('127.0.0.1', ['osmiumconvert', 'clear', self.EXT]))

    def test_saved_player_stays_listed_when_offline(self):
        self.with_own(self.ext_player())
        self.api.update_external_convert({'mac': self.EXT, 'name': 'Studio', 'upsample': 'x2'})
        self.with_own()                                   # the external player disconnects
        g = self.api.get_external_convert()
        row = [p for p in g['players'] if p['mac'] == self.EXT]
        self.assertEqual(len(row), 1)
        self.assertFalse(row[0]['connected'])
        self.assertEqual(row[0]['conf']['upsample'], 'x2')


if __name__ == '__main__':
    unittest.main()
