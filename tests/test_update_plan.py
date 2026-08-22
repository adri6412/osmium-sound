"""Tests for the update-plan bookkeeping in api_server.py.

These cover the *client-visible* half of the two-phase sequencer: how a plan
is written, read back, and turned into progress during staging, and how the
durable post-apply outcome (UPDATE_STATE_FILE) is reported once the box comes
back from its two update-mode reboots. The shell half (walking the plan,
resuming an interrupted stage, applying in isolation) is covered by
tests/test-update-stage-runner.sh and tests/test-update-apply-runner.sh.

Run with:  python tests/test_update_plan.py
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import api_server  # noqa: E402


class PlanTestCase(unittest.TestCase):
    """Redirects every path the plan code touches into a temp dir."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='hifi-plan-test-')
        self._saved = {}
        self._patch('UPDATE_PLAN_FILE', os.path.join(self.tmp, 'update-plan'))
        self._patch('UPDATE_STATE_FILE', os.path.join(self.tmp, 'update-state'))
        self._patch('UPDATE_ERROR_FILE', os.path.join(self.tmp, 'update-error.json'))
        # Per-kind status files (the /run ones) + the version readers.
        self.status_files = {k: os.path.join(self.tmp, '%s-status.json' % k)
                             for k in ('system', 'os', 'ui')}
        self.installed = {'system': 'old', 'os': 'old', 'ui': 'old'}
        self._saved['_PLAN_KINDS'] = api_server._PLAN_KINDS
        api_server._PLAN_KINDS = {
            k: (lambda: {}, self.status_files[k], (lambda k=k: self.installed[k]))
            for k in ('system', 'os', 'ui')
        }
        # No systemd in the test environment; assume the runner is alive unless
        # a test says otherwise.
        self._saved['_runner_active'] = api_server._runner_active
        api_server._runner_active = lambda: self.runner_alive
        self.runner_alive = True

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(api_server, name, value)

    def _patch(self, name, value):
        self._saved[name] = getattr(api_server, name)
        setattr(api_server, name, value)

    def write_plan(self, steps, finished=None, overall=None):
        plan = {'plan_id': 'p1', 'channel': 'dev', 'created': int(time.time()),
                'steps': steps, 'finished': finished, 'overall': overall}
        api_server._write_update_plan(plan)
        if finished:
            with open(api_server.UPDATE_PLAN_FILE, 'a') as f:
                f.write('finished %d %s\n' % (finished, overall))
        return plan

    @staticmethod
    def step(kind, state='pending', version='v2', attempts=0, sig=None):
        return {'kind': kind, 'state': state, 'attempts': attempts,
                'version': version, 'url': 'https://e/%s.tgz' % kind,
                'sha': 'a' * 64, 'sig': sig}

    def write_status(self, kind, payload):
        with open(self.status_files[kind], 'w') as f:
            json.dump(payload, f)

    def write_state(self, phase, ts=None, message=''):
        # Mirrors what hifi-update-stage-runner.sh / hifi-update-apply-runner.sh
        # write to UPDATE_STATE_FILE — see api_server._read_update_state().
        with open(api_server.UPDATE_STATE_FILE, 'w') as f:
            f.write('phase=%s\nts=%d\nmessage=%s\n' %
                    (phase, ts if ts is not None else int(time.time()), message))

    def write_error(self, channel, message):
        with open(api_server.UPDATE_ERROR_FILE, 'w') as f:
            json.dump({'channel': channel, 'message': message}, f)


class TestPlanRoundTrip(PlanTestCase):
    def test_write_then_read_preserves_every_field(self):
        self.write_plan([self.step('system'),
                         self.step('os', sig='https://e/os.sig'),
                         self.step('ui', state='done', attempts=1)])
        got = api_server._read_update_plan()
        self.assertEqual([s['kind'] for s in got['steps']], ['system', 'os', 'ui'])
        self.assertEqual(got['steps'][1]['sig'], 'https://e/os.sig')
        # No signature is stored as '-' on disk and must come back as None, not
        # the literal string — it is passed straight to the OS updater.
        self.assertIsNone(got['steps'][0]['sig'])
        self.assertEqual(got['steps'][2]['state'], 'done')
        self.assertEqual(got['steps'][2]['attempts'], 1)

    def test_plan_file_is_whitespace_separated_and_shell_parsable(self):
        # hifi-update-stage-runner.sh parses this with awk/`set --`; a field
        # with a space in it would silently shift every later field.
        self.write_plan([self.step('system')])
        with open(api_server.UPDATE_PLAN_FILE) as f:
            step_lines = [l for l in f.read().splitlines() if l.startswith('step ')]
        self.assertEqual(len(step_lines), 1)
        self.assertEqual(len(step_lines[0].split()), 8)

    def test_no_plan_reads_as_none(self):
        self.assertIsNone(api_server._read_update_plan())
        self.assertEqual(api_server.update_plan_status(), {'state': 'idle'})


class TestPlanState(PlanTestCase):
    def test_running_while_a_step_is_running(self):
        self.write_plan([self.step('system', 'done'), self.step('os', 'running')])
        self.assertEqual(api_server.update_plan_status()['state'], 'running')

    def test_all_staged_is_pending_reboot(self):
        # Under the two-phase design, every step reaching 'done' means every
        # component has STAGED — nothing has been applied yet, and the stage
        # runner is about to (or already did) reboot into the isolated apply
        # session. This must not read as a finished/dismissable update.
        self.write_plan([self.step('system', 'done'), self.step('ui', 'done')])
        self.assertEqual(api_server.update_plan_status()['state'], 'staged_pending_reboot')

    def test_any_error_is_error(self):
        self.write_plan([self.step('system', 'done'), self.step('os', 'error'),
                         self.step('ui', 'pending')])
        self.assertEqual(api_server.update_plan_status()['state'], 'error')

    def test_running_step_without_a_live_runner_is_interrupted(self):
        # Power cut, or a reboot on a box whose resume unit isn't enabled yet.
        # Reporting 'running' forever would hang every client polling us.
        self.runner_alive = False
        self.write_plan([self.step('os', 'running')])
        self.assertEqual(api_server.update_plan_status()['state'], 'interrupted')

    def test_finished_plan_is_retired_after_its_ttl(self):
        old = int(time.time()) - api_server.UPDATE_PLAN_TTL - 1
        self.write_plan([self.step('ui', 'done')], finished=old, overall='finished')
        self.assertEqual(api_server.update_plan_status(), {'state': 'idle'})
        self.assertFalse(os.path.exists(api_server.UPDATE_PLAN_FILE))

    def test_staged_plan_is_kept_within_its_ttl(self):
        # A plan that finished staging very recently is still 'staged_pending_
        # reboot' (not yet retired) — the box hasn't rebooted into the apply
        # session yet, or a client is polling in the brief window before it does.
        self.write_plan([self.step('ui', 'done')],
                        finished=int(time.time()), overall='finished')
        self.assertEqual(api_server.update_plan_status()['state'], 'staged_pending_reboot')


class TestLiveProgress(PlanTestCase):
    def test_status_of_the_running_step_is_surfaced(self):
        self.write_plan([self.step('system', 'running')])
        self.write_status('system', {'state': 'downloading', 'progress': 40,
                                     'version': 'v2', 'message': 'Scaricamento…'})
        s = api_server.update_plan_status()
        self.assertEqual(s['kind'], 'system')
        self.assertEqual(s['step_state'], 'downloading')
        self.assertEqual(s['message'], 'Scaricamento…')

    def test_stale_status_from_a_previous_run_is_ignored(self):
        # THE regression this whole change exists for: /run/hifi-*-status.json is
        # never reset, so between the apply and the updater's first write it
        # still holds the PREVIOUS run's `done`. Clients used to read that,
        # declare the step complete and start the next component on top of a
        # running one.
        self.write_plan([self.step('system', 'running', version='v2')])
        self.write_status('system', {'state': 'done', 'progress': 100,
                                     'version': 'v1', 'message': 'old run'})
        s = api_server.update_plan_status()
        self.assertEqual(s['step_state'], 'starting')
        self.assertNotEqual(s['step_state'], 'done')
        self.assertEqual(s['message'], '')
        # And the plan as a whole is still running — not finished.
        self.assertEqual(s['state'], 'running')

    def test_missing_status_file_is_not_an_error(self):
        self.write_plan([self.step('os', 'running')])
        s = api_server.update_plan_status()
        self.assertEqual(s['state'], 'running')
        self.assertEqual(s['step_state'], 'starting')

    def test_overall_progress_spans_the_whole_plan(self):
        self.write_plan([self.step('system', 'done'), self.step('os', 'running'),
                         self.step('ui', 'pending')])
        self.write_status('os', {'state': 'applying', 'progress': 50, 'version': 'v2'})
        s = api_server.update_plan_status()
        # one of three steps done, plus half of the second
        self.assertEqual(s['overall_progress'], 50)

    def test_steps_report_what_is_actually_installed(self):
        self.installed['system'] = 'v2'
        self.write_plan([self.step('system', 'done'), self.step('ui', 'pending')])
        by_kind = {x['kind']: x for x in api_server.update_plan_status()['steps']}
        self.assertEqual(by_kind['system']['installed'], 'v2')
        self.assertEqual(by_kind['ui']['installed'], 'old')

    def test_failed_steps_real_error_message_is_surfaced(self):
        # THE bug this test guards against: the stage runner marks a failed
        # step 'error' and stops (hifi-update-stage-runner.sh), leaving the
        # updater's own
        # /run/hifi-*-status.json — written by its fail() helper, e.g. "Download
        # fallito da ..." — as the only record of *why*. If update_plan_status()
        # doesn't read that file for state=='error', the client falls back to
        # showing just the generic component name, with no explanation.
        self.write_plan([self.step('system', 'error', attempts=1)])
        self.write_status('system', {'state': 'error', 'progress': 0,
                                     'version': 'v2', 'message': 'Download fallito da https://e/x'})
        s = api_server.update_plan_status()
        self.assertEqual(s['state'], 'error')
        self.assertEqual(s['kind'], 'system')
        self.assertEqual(s['message'], 'Download fallito da https://e/x')

    def test_error_step_is_current_even_with_later_pending_steps(self):
        # The runner always stops at the first failure (system -> os -> ui
        # order), so any step still 'pending' after an 'error' one was simply
        # never reached. `current` must point at the step that actually failed,
        # not at one of the untouched ones after it.
        self.write_plan([self.step('system', 'done'), self.step('os', 'error'),
                         self.step('ui', 'pending')])
        self.write_status('os', {'state': 'error', 'progress': 0,
                                 'version': 'v2', 'message': 'Checksum non valido'})
        s = api_server.update_plan_status()
        self.assertEqual(s['kind'], 'os')
        self.assertEqual(s['message'], 'Checksum non valido')


class TestPostApplyOutcome(PlanTestCase):
    """update_plan_status() after the box has been through (or is stuck mid)
    the isolated apply session — driven entirely by UPDATE_STATE_FILE, which
    hifi-update-apply-runner.sh writes and this module only ever reads."""

    def test_applying_is_surfaced_even_with_no_plan(self):
        # The plan file may already be gone (removed by a stage-resume run
        # on some earlier, unrelated boot) — 'applying' must not depend on it.
        self.write_state('applying', message='Applicazione in corso')
        s = api_server.update_plan_status()
        self.assertEqual(s['state'], 'applying')
        self.assertEqual(s['message'], 'Applicazione in corso')

    def test_done_outcome_wins_over_a_stale_plan(self):
        # The plan the stage runner wrote before the first reboot is still on
        # disk (only the apply runner removes it, and only on full success) —
        # a terminal state-file outcome must take priority over it regardless.
        self.write_plan([self.step('ui', 'done')],
                        finished=int(time.time()), overall='finished')
        self.write_state('done', message='Aggiornamento completato')
        s = api_server.update_plan_status()
        self.assertEqual(s['state'], 'done')
        self.assertEqual(s['message'], 'Aggiornamento completato')

    def test_apply_error_surfaces_the_failing_channel_and_message(self):
        self.write_state('error', message='fallback message')
        self.write_error('os', 'apply.sh fallito: errore sconosciuto')
        s = api_server.update_plan_status()
        self.assertEqual(s['state'], 'apply_error')
        self.assertEqual(s['kind'], 'os')
        self.assertEqual(s['message'], 'apply.sh fallito: errore sconosciuto')

    def test_apply_error_falls_back_to_the_state_message_without_an_error_file(self):
        self.write_state('error', message='fallback message')
        s = api_server.update_plan_status()
        self.assertEqual(s['state'], 'apply_error')
        self.assertEqual(s['message'], 'fallback message')

    def test_done_outcome_is_retired_after_its_ttl(self):
        old = int(time.time()) - api_server.UPDATE_PLAN_TTL - 1
        self.write_state('done', ts=old)
        self.assertEqual(api_server.update_plan_status(), {'state': 'idle'})
        self.assertIsNone(api_server._read_update_state())

    def test_done_outcome_is_kept_within_its_ttl(self):
        self.write_state('done')
        self.assertEqual(api_server.update_plan_status()['state'], 'done')

    def test_error_outcome_is_retired_after_its_ttl(self):
        old = int(time.time()) - api_server.UPDATE_PLAN_TTL - 1
        self.write_state('error', ts=old)
        self.assertEqual(api_server.update_plan_status(), {'state': 'idle'})


class TestStepValidation(PlanTestCase):
    """The plan is parsed by /bin/sh and its fields become arguments to a root
    script, so anything unsafe has to be rejected before it is written."""

    def base_info(self, **over):
        info = {'update_available': True, 'latest': 'v2.5.22',
                'asset_url': 'https://e/x.tgz', 'sha_url': 'https://e/x.sha256',
                'sig_url': 'https://e/x.sig'}
        info.update(over)
        return info

    def setUp(self):
        super().setUp()
        self._patch('_fetch_sha256', lambda url: 'a' * 64)

    def test_accepts_a_well_formed_release(self):
        step = api_server._plan_step_from_info('os', self.base_info())
        self.assertIsNotNone(step)
        self.assertEqual(step['version'], 'v2.5.22')
        self.assertEqual(step['state'], 'pending')

    def test_rejects_a_version_with_whitespace_or_shell_metacharacters(self):
        # These are real-update-but-invalid-step cases: build_update_plan()
        # must surface them as errors, not silently as "no update available".
        for bad in ('v2 3', 'v2;reboot', 'v2$(id)', '../../etc/passwd', ''):
            self.assertIs(api_server._plan_step_from_info('ui', self.base_info(latest=bad)),
                          api_server._STEP_INVALID, bad)

    def test_rejects_a_non_tls_asset_url(self):
        self.assertIs(api_server._plan_step_from_info(
            'ui', self.base_info(asset_url='http://e/x.tgz')), api_server._STEP_INVALID)

    def test_rejects_an_unsigned_os_bundle(self):
        # The OS payload runs its own apply.sh as root — a checksum only proves
        # the file arrived intact, not that we authored it.
        self.assertIs(api_server._plan_step_from_info('os', self.base_info(sig_url='')),
                      api_server._STEP_INVALID)

    def test_allows_an_unsigned_ui_or_system_bundle(self):
        self.assertIsNotNone(api_server._plan_step_from_info('ui', self.base_info(sig_url='')))
        self.assertIsNotNone(api_server._plan_step_from_info('system', self.base_info(sig_url='')))

    def test_rejects_a_malformed_checksum(self):
        api_server._fetch_sha256 = lambda url: 'nothex'
        self.assertIs(api_server._plan_step_from_info('ui', self.base_info()),
                      api_server._STEP_INVALID)

    def test_skips_a_component_with_no_update(self):
        self.assertIsNone(api_server._plan_step_from_info('ui', self.base_info(update_available=False)))
        self.assertIsNone(api_server._plan_step_from_info('ui', {'error': 'boom'}))


class TestFetchSha256Retry(unittest.TestCase):
    """GitHub's release-download host resets the connection outright on a
    noticeable fraction of requests from some networks — not a timeout, just
    a bare connection failure — so _fetch_sha256() must ride through a couple
    of those the way every curl-based download elsewhere already does with
    `--retry 3`, instead of taking down the whole plan on the first blip."""

    def setUp(self):
        self._saved_urlopen = api_server.urllib.request.urlopen
        self._saved_sleep = api_server.time.sleep
        api_server.time.sleep = lambda seconds: None  # no real delay in tests

    def tearDown(self):
        api_server.urllib.request.urlopen = self._saved_urlopen
        api_server.time.sleep = self._saved_sleep

    def _resp(self, text):
        class R:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return text.encode()
        return R()

    def test_succeeds_after_transient_failures_within_budget(self):
        calls = []
        def flaky(req, timeout=None):
            calls.append(1)
            if len(calls) < 3:
                raise ConnectionResetError('connection reset')
            return self._resp('%s  file.tgz\n' % ('a' * 64))
        api_server.urllib.request.urlopen = flaky
        self.assertEqual(api_server._fetch_sha256('https://e/x.sha256'), 'a' * 64)
        self.assertEqual(len(calls), 3)

    def test_raises_the_real_error_once_retries_are_exhausted(self):
        def always_fails(req, timeout=None):
            raise ConnectionResetError('connection reset')
        api_server.urllib.request.urlopen = always_fails
        with self.assertRaises(ConnectionResetError):
            api_server._fetch_sha256('https://e/x.sha256')


class TestApplyAll(PlanTestCase):
    def setUp(self):
        super().setUp()
        self.started = []
        self._patch('_fetch_sha256', lambda url: 'a' * 64)

        def fake_run(cmd, **kw):
            self.started.append(cmd)
            class R:
                returncode = 0
                stdout = ''
                stderr = ''
            return R()
        self._saved['subprocess_run'] = api_server.subprocess.run
        api_server.subprocess.run = fake_run

    def tearDown(self):
        api_server.subprocess.run = self._saved['subprocess_run']
        super().tearDown()

    def _offer(self, kinds):
        info = {'update_available': True, 'latest': 'v2', 'asset_url': 'https://e/x.tgz',
                'sha_url': 'https://e/x.sha', 'sig_url': 'https://e/x.sig'}
        api_server._PLAN_KINDS = {
            k: ((lambda k=k: dict(info) if k in kinds else {'update_available': False}),
                self.status_files[k], (lambda k=k: self.installed[k]))
            for k in ('system', 'os', 'ui')
        }

    def test_plan_is_ordered_system_then_os_then_ui(self):
        # Order is the whole point: system delivers the API and the runner, os
        # may reboot, ui tears down the kiosk.
        self._offer(('ui', 'os', 'system'))
        r = api_server.apply_all_updates()
        self.assertTrue(r['started'])
        self.assertEqual([s['kind'] for s in r['steps']], ['system', 'os', 'ui'])
        self.assertEqual([s['kind'] for s in api_server._read_update_plan()['steps']],
                         ['system', 'os', 'ui'])

    def test_only_components_with_an_update_are_planned(self):
        self._offer(('os',))
        r = api_server.apply_all_updates()
        self.assertEqual([s['kind'] for s in r['steps']], ['os'])

    def test_nothing_to_do_does_not_write_a_plan(self):
        self._offer(())
        r = api_server.apply_all_updates()
        self.assertFalse(r['started'])
        self.assertEqual(r['code'], 'update.noneAvailable')
        self.assertIsNone(api_server._read_update_plan())

    def test_a_real_update_with_an_invalid_step_is_reported_as_a_check_failure(self):
        # Regression: an update IS on offer (as shown to the user on the
        # updates page) but _plan_step_from_info() can't build a safe step for
        # it (e.g. a transient blip fetching the checksum sidecar). This must
        # surface as 'update.checkFailed', never as the misleading
        # 'update.noneAvailable' — that message tells the user there is
        # nothing to install when in fact there is, just not right now.
        info = {'update_available': True, 'latest': 'v2',
                'asset_url': 'http://e/x.tgz',  # non-TLS -> _STEP_INVALID
                'sha_url': 'https://e/x.sha', 'sig_url': 'https://e/x.sig'}
        api_server._PLAN_KINDS = {
            k: ((lambda k=k: dict(info)), self.status_files[k], (lambda k=k: self.installed[k]))
            for k in ('system', 'os', 'ui')
        }
        r = api_server.apply_all_updates()
        self.assertFalse(r['started'])
        self.assertEqual(r['code'], 'update.checkFailed')
        self.assertIsNone(api_server._read_update_plan())

    def test_the_stage_runner_is_started_once(self):
        self._offer(('system',))
        api_server.apply_all_updates()
        self.assertEqual(len(self.started), 1)
        self.assertIn(api_server.UPDATE_STAGE_RUNNER_SCRIPT, self.started[0])

    def test_a_second_apply_is_refused_while_one_is_running(self):
        self._offer(('system', 'ui'))
        self.assertTrue(api_server.apply_all_updates()['started'])
        api_server._write_update_plan({
            'plan_id': 'p1', 'channel': 'dev', 'created': 0,
            'steps': [self.step('system', 'running')], 'finished': None, 'overall': None})
        r = api_server.apply_all_updates()
        self.assertFalse(r['started'])
        self.assertEqual(len(self.started), 1)

    def test_a_finished_plan_does_not_block_a_new_one(self):
        self._offer(('system',))
        self.write_plan([self.step('ui', 'done')],
                        finished=int(time.time()), overall='finished')
        self.assertTrue(api_server.apply_all_updates()['started'])

    def test_dismiss_refuses_a_running_or_staged_plan_but_clears_a_done_outcome(self):
        self.write_plan([self.step('os', 'running')])
        self.assertFalse(api_server.dismiss_update_plan()['success'])
        self.assertIsNotNone(api_server._read_update_plan())

        # Fully staged: the box is about to reboot into the apply session —
        # still not something the client should be able to dismiss out from
        # under.
        self.write_plan([self.step('os', 'done')])
        self.assertFalse(api_server.dismiss_update_plan()['success'])
        self.assertIsNotNone(api_server._read_update_plan())

        # The outcome the client can actually dismiss lives in the state file,
        # written only after the box has come back from both update-mode
        # reboots.
        self.write_state('done')
        r = api_server.dismiss_update_plan()
        self.assertTrue(r['success'])
        self.assertIsNone(api_server._read_update_plan())
        self.assertIsNone(api_server._read_update_state())


class TestUpdateInProgressGuard(PlanTestCase):
    def test_a_running_plan_blocks_display_mode_and_factory_reset(self):
        # These used to consult only the /run status files, which are wiped by
        # the reboot an OS payload asks for — precisely when interfering is
        # most destructive.
        self.write_plan([self.step('os', 'running')])
        self.assertTrue(api_server._update_in_progress())

    def test_a_staged_plan_still_blocks(self):
        # Every step staged means the box is about to reboot into the isolated
        # apply session — still exactly the wrong moment for a display-mode
        # switch or a factory reset to run.
        self.write_plan([self.step('os', 'done')])
        self.assertTrue(api_server._update_in_progress())

    def test_applying_state_blocks(self):
        self.write_state('applying')
        self.assertTrue(api_server._update_in_progress())

    def test_a_done_outcome_does_not_block(self):
        # Once the apply session has actually finished and the box is back on
        # a normal boot, there is nothing left to protect against.
        self.write_state('done')
        self.assertFalse(api_server._update_in_progress())

    def test_an_apply_error_outcome_does_not_block(self):
        # A failed apply leaves the box parked in update-mode, where hifi-api
        # does not even run — this state is only ever observed AFTER a manual
        # recovery + normal reboot, by which point there is nothing in
        # progress to protect against either.
        self.write_state('error')
        self.assertFalse(api_server._update_in_progress())


if __name__ == '__main__':
    unittest.main(verbosity=2)
