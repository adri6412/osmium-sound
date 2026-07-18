import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Mic, X, Ruler, RefreshCw } from 'lucide-react';
import { useI18n } from '../i18n';

// Guided room-correction wizard: pick the USB measurement mic, play the sweep,
// show measured vs corrected response, then apply the generated FIR through
// the normal DSP path. Talks straight to api_server (:8000, loopback) — raw
// fetch instead of apiPost so backend error messages (409/424/400) surface.
const API = 'http://localhost:8000';

// Log-frequency SVG chart of the measured/corrected curves.
const ResponseChart = ({ result }) => {
  if (!result?.freqs?.length) return null;
  const W = 400, H = 150, DB_MAX = 12, DB_MIN = -18;
  const fx = (f) => (Math.log10(f / 20) / Math.log10(20000 / 20)) * W;
  const fy = (db) => ((DB_MAX - Math.max(DB_MIN, Math.min(DB_MAX, db))) / (DB_MAX - DB_MIN)) * H;
  const line = (vals) => result.freqs.map((f, i) => `${fx(f).toFixed(1)},${fy(vals[i]).toFixed(1)}`).join(' ');
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-36 bg-black/30 rounded-lg">
      {[100, 1000, 10000].map((f) => (
        <line key={f} x1={fx(f)} y1="0" x2={fx(f)} y2={H} stroke="rgba(255,255,255,0.08)" />
      ))}
      <line x1="0" y1={fy(0)} x2={W} y2={fy(0)} stroke="rgba(255,255,255,0.15)" strokeDasharray="4 4" />
      <polyline points={line(result.measured_db)} fill="none" stroke="rgba(192,192,192,0.7)" strokeWidth="1.5" />
      <polyline points={line(result.corrected_db)} fill="none" stroke="#d4af37" strokeWidth="1.5" />
    </svg>
  );
};

const RoomCorrectionWizard = ({ onDone }) => {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState('intro'); // intro | mic | measuring | result
  const [mics, setMics] = useState(null);
  const [micDev, setMicDev] = useState('');
  const [status, setStatus] = useState(null);
  const [errMsg, setErrMsg] = useState('');
  const [applying, setApplying] = useState(false);
  const pollRef = useRef(null);

  const openWizard = async () => {
    setErrMsg('');
    setStatus(null);
    setStep('intro');
    setOpen(true);
    try {
      const r = await fetch(`${API}/roomcorr/mics`);
      const data = await r.json();
      setMics(data.mics || []);
      setMicDev(data.mics?.[0]?.device || '');
    } catch {
      setMics([]);
    }
  };

  const startMeasure = async () => {
    setErrMsg('');
    try {
      const r = await fetch(`${API}/roomcorr/measure`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mic_device: micDev }),
      });
      const data = await r.json();
      if (!r.ok || !data.success) {
        setErrMsg(data.message || t('settings.roomcorr.error'));
        return;
      }
      setStep('measuring');
      setStatus({ state: 'preparing', progress: 0 });
      clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const rs = await fetch(`${API}/roomcorr/status`);
          const st = await rs.json();
          setStatus(st);
          if (st.state === 'done' || st.state === 'error') {
            clearInterval(pollRef.current);
            setStep('result');
          }
        } catch {
          clearInterval(pollRef.current);
          setErrMsg(t('settings.roomcorr.error'));
          setStep('mic');
        }
      }, 1500);
    } catch {
      setErrMsg(t('settings.roomcorr.error'));
    }
  };
  useEffect(() => () => clearInterval(pollRef.current), []);

  const apply = async () => {
    setApplying(true);
    try {
      const r = await fetch(`${API}/roomcorr/apply`, { method: 'POST' });
      const data = await r.json();
      if (!data.success) {
        setErrMsg(data.message || t('settings.roomcorr.error'));
        setApplying(false);
        return;
      }
      setOpen(false);
      onDone?.();
    } catch {
      setErrMsg(t('settings.roomcorr.error'));
    }
    setApplying(false);
  };

  const discard = async () => {
    try { await fetch(`${API}/roomcorr/discard`, { method: 'POST' }); } catch { /* best effort */ }
    setOpen(false);
    onDone?.();
  };

  const busy = step === 'measuring';

  return (
    <>
      <button onClick={openWizard}
        className="w-full flex items-center justify-center gap-2 bg-hifi-accent/60 hover:bg-hifi-accent text-white rounded-lg px-4 py-2.5 text-sm transition-colors">
        <Ruler size={15} className="text-hifi-gold" />
        {t('settings.roomcorr.start')}
      </button>

      {createPortal(
        <AnimatePresence>
          {open && (
            <motion.div className="fixed inset-0 z-[70] flex items-center justify-center p-6"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <div className="absolute inset-0 bg-black/70" onClick={() => !busy && setOpen(false)} />
              <motion.div initial={{ scale: 0.94, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.94, opacity: 0 }}
                className="relative w-full max-w-lg bg-hifi-panel border border-hifi-border rounded-2xl p-5 shadow-2xl">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center space-x-2">
                    <Ruler size={16} className="text-hifi-gold" />
                    <p className="text-sm font-semibold text-white">{t('settings.roomcorr.title')}</p>
                  </div>
                  {!busy && (
                    <button onClick={() => setOpen(false)}
                      className="p-1.5 text-hifi-silver/60 hover:text-white hover:bg-white/10 rounded-lg transition-colors">
                      <X size={16} />
                    </button>
                  )}
                </div>

                {step === 'intro' && (
                  <div className="space-y-3">
                    <p className="text-sm text-hifi-silver leading-relaxed">{t('settings.roomcorr.intro')}</p>
                    <ul className="text-xs text-hifi-silver/80 space-y-1.5 list-disc pl-4">
                      <li>{t('settings.roomcorr.req1')}</li>
                      <li>{t('settings.roomcorr.req2')}</li>
                      <li>{t('settings.roomcorr.req3')}</li>
                    </ul>
                    <button onClick={() => setStep('mic')}
                      className="w-full bg-hifi-gold hover:bg-yellow-600 text-black py-2.5 rounded-lg text-sm font-semibold transition-colors">
                      {t('common.next')}
                    </button>
                  </div>
                )}

                {step === 'mic' && (
                  <div className="space-y-3">
                    {mics === null && <p className="text-sm text-hifi-silver/60">{t('common.loading')}</p>}
                    {mics && mics.length === 0 && (
                      <div className="flex items-start gap-2 bg-amber-500/10 border border-amber-500/30 rounded-lg p-3">
                        <Mic size={15} className="text-amber-300 mt-0.5 shrink-0" />
                        <p className="text-xs text-amber-200/90">{t('settings.roomcorr.noMic')}</p>
                      </div>
                    )}
                    {mics && mics.length > 0 && (
                      <>
                        <p className="text-xs text-hifi-silver">{t('settings.roomcorr.pickMic')}</p>
                        <select value={micDev} onChange={(e) => setMicDev(e.target.value)}
                          className="w-full bg-hifi-dark border border-hifi-accent rounded-lg px-3 py-2.5 text-sm text-white focus:outline-none focus:border-hifi-gold">
                          {mics.map((m) => (
                            <option key={m.device} value={m.device}>{m.name} — {m.detail}</option>
                          ))}
                        </select>
                        <p className="text-xs text-hifi-silver/70">{t('settings.roomcorr.position')}</p>
                      </>
                    )}
                    {errMsg && <p className="text-xs text-red-300">{errMsg}</p>}
                    <div className="flex gap-2">
                      <button onClick={openWizard}
                        className="px-4 bg-hifi-light hover:bg-hifi-accent text-white py-2.5 rounded-lg text-sm transition-colors">
                        <RefreshCw size={14} />
                      </button>
                      <button onClick={startMeasure} disabled={!micDev}
                        className="flex-1 bg-hifi-gold hover:bg-yellow-600 disabled:opacity-40 text-black py-2.5 rounded-lg text-sm font-semibold transition-colors">
                        {t('settings.roomcorr.measure')}
                      </button>
                    </div>
                  </div>
                )}

                {step === 'measuring' && (
                  <div className="flex flex-col items-center py-5">
                    <motion.div animate={{ scale: [1, 1.15, 1] }} transition={{ duration: 1.2, repeat: Infinity }}
                      className="mb-4 text-hifi-gold"><Mic size={36} /></motion.div>
                    <p className="text-sm text-white mb-3 text-center">{status?.message || t('settings.roomcorr.measuring')}</p>
                    <div className="w-full h-2 bg-white/10 rounded-full overflow-hidden">
                      <div className="h-full bg-gradient-to-r from-hifi-gold to-yellow-400 rounded-full transition-all"
                        style={{ width: `${status?.progress || 0}%` }} />
                    </div>
                    <p className="text-[11px] text-hifi-silver/50 mt-3">{t('settings.roomcorr.keepQuiet')}</p>
                  </div>
                )}

                {step === 'result' && (
                  <div className="space-y-3">
                    {status?.state === 'error' ? (
                      <>
                        <p className="text-sm text-red-300">{status.message || t('settings.roomcorr.error')}</p>
                        <button onClick={() => setStep('mic')}
                          className="w-full bg-hifi-gold hover:bg-yellow-600 text-black py-2.5 rounded-lg text-sm font-semibold transition-colors">
                          {t('common.retry')}
                        </button>
                      </>
                    ) : (
                      <>
                        <ResponseChart result={status?.result} />
                        <div className="flex items-center gap-4 text-[11px] text-hifi-silver/70">
                          <span className="flex items-center gap-1.5">
                            <span className="inline-block w-4 h-0.5 bg-hifi-silver/70" />{t('settings.roomcorr.measured')}
                          </span>
                          <span className="flex items-center gap-1.5">
                            <span className="inline-block w-4 h-0.5 bg-hifi-gold" />{t('settings.roomcorr.corrected')}
                          </span>
                        </div>
                        {errMsg && <p className="text-xs text-red-300">{errMsg}</p>}
                        <div className="flex gap-2">
                          <button onClick={discard}
                            className="px-4 bg-red-500/10 hover:bg-red-500/20 text-red-300 py-2.5 rounded-lg text-sm transition-colors border border-red-500/20">
                            {t('settings.roomcorr.discard')}
                          </button>
                          <button onClick={() => setStep('mic')}
                            className="px-4 bg-hifi-light hover:bg-hifi-accent text-white py-2.5 rounded-lg text-sm transition-colors">
                            {t('common.retry')}
                          </button>
                          <button onClick={apply} disabled={applying}
                            className="flex-1 bg-hifi-gold hover:bg-yellow-600 disabled:opacity-60 text-black py-2.5 rounded-lg text-sm font-semibold transition-colors">
                            {t('settings.roomcorr.apply')}
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                )}
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>,
        document.body
      )}
    </>
  );
};

export default RoomCorrectionWizard;
