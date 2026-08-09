import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { motion } from 'framer-motion';
import { AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react';
import { useI18n } from '../i18n';
import { systemAPI } from '../utils/api';
import { SCALED_CANVAS_ID } from './ScaledCanvas';

// Mirrors the fullscreen OTA-progress overlay Settings.jsx renders while it's
// open, but mounted at the app root so it survives whatever the running plan
// just did to this process (the system step restarts hifi-api, the UI step
// restarts lightdm — which kills and relaunches this very app — and an OS
// step may reboot the box) and stays visible from any screen, not only
// Settings. The server-side plan (hifi-update-runner.sh, polled here via
// /update/status) is the only state that stays accurate across all of that.
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
    const poll = async () => {
      const r = await systemAPI.getUpdatePlanStatus();
      if (!r.success || !r.data || r.data.state === 'idle') { setStatus(null); return; }
      setStatus(r.data);
    };
    poll();
    pollRef.current = setInterval(poll, 2000);
    return () => clearInterval(pollRef.current);
  }, []);

  const dismiss = async () => {
    await systemAPI.dismissUpdatePlan();
    setStatus(null);
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

  const terminal = status.state === 'error' || status.state === 'interrupted';
  const isDone = status.state === 'finished';
  const message = stepMessage(status.step_state, status.message || '')
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
        {hasPct && !terminal ? `${pct}%` : ''}
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
