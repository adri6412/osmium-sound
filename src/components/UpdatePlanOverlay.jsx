import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { motion } from 'framer-motion';
import { AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react';
import { useI18n } from '../i18n';
import { systemAPI } from '../utils/api';
import { SCALED_CANVAS_ID } from './ScaledCanvas';

// Mirrors the fullscreen OTA-progress overlay Settings.jsx renders while it's
// open, but mounted at the app root so it survives whatever the running
// update just did to this process — staging can restart hifi-api, and once
// everything has staged the appliance reboots into an isolated
// system-update.target session (nothing from the app stack, including this
// very kiosk, runs there) before rebooting back — and stays visible from any
// screen, not only Settings. The server-side plan/outcome (hifi-update-stage-
// runner.sh / hifi-update-apply-runner.sh, polled here via /update/status) is
// the only state that stays accurate across all of that.
//
// Settings.jsx keeps its own copy of this overlay for the "started here, user
// is watching" case and announces when it's mounted via 'hifi-settings-mounted'
// — this component stays hidden then, so the two never show at once.
const UpdatePlanOverlay = () => {
  const { t } = useI18n();
  const [status, setStatus] = useState(null); // raw /update/status payload, or null when idle
  const [settingsOpen, setSettingsOpen] = useState(false);
  const pollRef = useRef(null);

  useEffect(() => {
    const onSettings = (e) => setSettingsOpen(!!e.detail);
    window.addEventListener('hifi-settings-mounted', onSettings);
    return () => window.removeEventListener('hifi-settings-mounted', onSettings);
  }, []);

  useEffect(() => {
    // 'interrupted' means "a step was left running with nobody currently
    // resuming it" — which is also exactly what the plan looks like for the
    // first few seconds after a stage download is interrupted, before
    // hifi-update-stage-resume.service has come up (it waits on
    // network-online.target), or during the brief window right after the
    // system step restarts hifi-api. Treating a
    // single 'interrupted' read as final showed the terminal error+dismiss
    // overlay for a run that was actually still going to finish on its own —
    // and dismissing here deletes the on-disk plan server-side, permanently
    // stranding whichever steps (e.g. 'ui') hadn't run yet. Mirrors the same
    // grace-period logic as Settings.jsx's followUpdatePlan().
    let interruptedStreak = 0;
    const MAX_INTERRUPTED_POLLS = 60; // ~2 minutes at 2s/poll
    const poll = async () => {
      const r = await systemAPI.getUpdatePlanStatus();
      if (!r.success || !r.data || r.data.state === 'idle') { setStatus(null); interruptedStreak = 0; return; }
      const s = r.data;
      if (s.state === 'interrupted') {
        interruptedStreak += 1;
      } else {
        interruptedStreak = 0;
      }
      setStatus({ ...s, _stillWaiting: s.state === 'interrupted' && interruptedStreak < MAX_INTERRUPTED_POLLS });
    };
    poll();
    pollRef.current = setInterval(poll, 2000);
    return () => clearInterval(pollRef.current);
  }, []);

  const dismiss = async () => {
    const r = await systemAPI.dismissUpdatePlan();
    // The endpoint always answers 200 even when it refuses (business-logic
    // `data.success: false` while a plan is genuinely still running) — check
    // that field, not the HTTP-transport-only `r.success`, or a refused
    // dismiss would still clear the overlay out from under an active update.
    if (r.success && r.data?.success !== false) setStatus(null);
  };

  if (settingsOpen || !status) return null;

  // The updater scripts write free-text progress messages in Italian only —
  // step_state is the one locale-neutral field they emit, so it drives the
  // displayed text (mirrors Settings.jsx's progressStateMessage).
  const stepMessage = (state, rawMessage) => {
    if (state === 'error') return rawMessage || t('settings.updates.msg.updateError');
    const known = ['starting', 'downloading', 'verifying', 'applying', 'restarting', 'done'];
    return known.includes(state) ? t(`settings.updates.progressState.${state}`) : rawMessage;
  };

  // While still inside the grace window (_stillWaiting, set by the poll loop
  // above), render 'interrupted' as just another in-progress step rather than
  // the terminal error state — see the comment on the poll effect for why.
  // 'apply_error' is the same terminal failure, just discovered after the
  // isolated apply session (rather than during staging); 'staged_pending_
  // reboot'/'applying' are still in progress — only 'done' is the real finish.
  const terminal = status.state === 'error' || status.state === 'apply_error'
    || (status.state === 'interrupted' && !status._stillWaiting);
  const isDone = status.state === 'done';
  const message = status._stillWaiting
    ? t('settings.updates.progressState.restarting')
    : stepMessage(status.step_state, status.message || '')
      || (status.kind ? t(`settings.updates.${status.kind}`) : '')
      || t('settings.updates.msg.starting');
  const hasPct = typeof status.overall_progress === 'number';
  const pct = hasPct ? Math.max(0, Math.min(100, Math.round(status.overall_progress))) : 0;

  return createPortal(
    <motion.div
      className="absolute inset-0 z-[10050] flex flex-col items-center justify-center bg-black/90 backdrop-blur-md p-10 text-center"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
    >
      <div className="mb-8">
        {terminal ? (
          <AlertTriangle className="w-16 h-16 text-red-500" />
        ) : isDone ? (
          <CheckCircle2 className="w-16 h-16 text-green-500" />
        ) : (
          <Loader2 className="w-16 h-16 text-hifi-accent animate-spin" />
        )}
      </div>

      <h2 className="text-white text-3xl font-semibold mb-3">{t('settings.updates.overlay.titleAll')}</h2>
      <p className="text-white/70 text-lg mb-8 max-w-xl min-h-[1.75rem]">{message}</p>

      <div className="w-full max-w-md h-3 bg-hifi-gray rounded-full overflow-hidden">
        <motion.div
          className={`h-full rounded-full ${terminal ? 'bg-red-500' : isDone ? 'bg-green-500' : 'bg-hifi-accent'} ${!hasPct && !terminal && !isDone ? 'animate-pulse' : ''}`}
          initial={{ width: 0 }}
          animate={{ width: hasPct ? `${pct}%` : '100%' }}
          transition={{ ease: 'easeOut', duration: 0.4 }}
        />
      </div>

      <div className="mt-4 h-8 text-2xl font-semibold tabular-nums text-hifi-accent">
        {hasPct && !terminal && !isDone ? `${pct}%` : ''}
      </div>

      {terminal || isDone ? (
        <button
          onClick={dismiss}
          className="mt-6 bg-hifi-accent hover:bg-hifi-dark text-white px-8 py-3 rounded-lg font-medium transition-colors"
        >
          {t('settings.updates.overlay.dismiss')}
        </button>
      ) : (
        <p className="mt-6 text-white/50 text-sm">{t('settings.updates.overlay.keepPowered')}</p>
      )}
    </motion.div>,
    document.getElementById(SCALED_CANVAS_ID) || document.body
  );
};

export default UpdatePlanOverlay;
