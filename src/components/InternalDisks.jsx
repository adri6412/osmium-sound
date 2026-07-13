import React, { useState, useEffect, useCallback, useRef } from 'react';
import { motion } from 'framer-motion';
import { HardDrive, AlertTriangle, Loader2, CheckCircle2, Eye, EyeOff, Copy, Check } from 'lucide-react';
import { useI18n } from '../i18n';
import { useKeyboardInput } from '../hooks/useKeyboardInput';

// Talks to the same on-device sources service as SourcesManager (plain fetch,
// no auth needed from loopback).
const SRC = 'http://localhost:8080';

const formatSize = (bytes) => {
  const n = Number(bytes) || 0;
  const gb = n / 1024 ** 3;
  if (gb <= 0) return '';
  if (gb >= 1000) return `${(gb / 1024).toFixed(1)} TB`;
  return `${Math.round(gb)} GB`;
};

function FormatWizard({ disk, t, onClose, onDone }) {
  const [step, setStep] = useState('choose'); // choose | confirm | progress | done | error
  const [fs, setFs] = useState('ext4');
  const [label, setLabel] = useState('Musica');
  const labelRef = useKeyboardInput(label, setLabel);
  const [typed, setTyped] = useState('');
  const typedRef = useKeyboardInput(typed, setTyped);
  const [status, setStatus] = useState(null);
  const [errorMsg, setErrorMsg] = useState('');
  const pollRef = useRef(null);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const startFormat = async () => {
    setStep('progress');
    try {
      const r = await fetch(SRC + '/api/internal/format', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ device: disk.path, fs, label, confirm: disk.confirm }),
      });
      const d = await r.json();
      if (!r.ok || d.success === false) {
        setErrorMsg(d.message || t('common.error'));
        setStep('error');
        return;
      }
    } catch (_) {
      setErrorMsg(t('common.error'));
      setStep('error');
      return;
    }

    pollRef.current = setInterval(async () => {
      try {
        const r = await fetch(SRC + '/api/internal/format/status');
        const d = await r.json();
        setStatus(d);
        if (d.state === 'done') {
          clearInterval(pollRef.current);
          setStep('done');
        } else if (d.state === 'error') {
          clearInterval(pollRef.current);
          setErrorMsg(d.message || t('common.error'));
          setStep('error');
        }
      } catch (_) { /* transient network hiccup, keep polling */ }
    }, 2000);
  };

  const canFormat = typed.trim() === label.trim() && label.trim().length > 0;
  const pct = status && typeof status.progress === 'number' ? Math.max(0, Math.min(100, Math.round(status.progress))) : 0;

  return (
    <motion.div
      className="fixed inset-0 z-[10050] flex items-center justify-center bg-black/80 backdrop-blur-sm p-6"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      onClick={() => { if (step === 'choose' || step === 'confirm') onClose(); }}
    >
      <motion.div
        className="bg-hifi-light border border-hifi-accent rounded-2xl p-6 max-w-md w-full shadow-2xl"
        initial={{ scale: 0.92, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        onClick={(e) => e.stopPropagation()}
      >
        {step === 'choose' && (
          <>
            <h3 className="text-white text-lg font-semibold mb-1">{t('sources.internal.wizardTitle')}</h3>
            <p className="text-hifi-silver/70 text-sm mb-4">{disk.model || disk.path} · {formatSize(disk.size)}</p>

            <label className="text-sm text-hifi-silver mb-2 block">{t('sources.internal.fsLabel')}</label>
            <div className="grid grid-cols-2 gap-3 mb-4">
              <button
                onClick={() => setFs('ext4')}
                className={`text-left rounded-lg p-3 border ${fs === 'ext4' ? 'border-hifi-gold bg-hifi-gold/10' : 'border-hifi-accent bg-hifi-dark'}`}
              >
                <div className="text-white text-sm font-medium">{t('sources.internal.fsExt4')}</div>
                <div className="text-hifi-silver/60 text-xs mt-1">{t('sources.internal.fsExt4Hint')}</div>
              </button>
              <button
                onClick={() => setFs('exfat')}
                className={`text-left rounded-lg p-3 border ${fs === 'exfat' ? 'border-hifi-gold bg-hifi-gold/10' : 'border-hifi-accent bg-hifi-dark'}`}
              >
                <div className="text-white text-sm font-medium">{t('sources.internal.fsExfat')}</div>
                <div className="text-hifi-silver/60 text-xs mt-1">{t('sources.internal.fsExfatHint')}</div>
              </button>
            </div>

            <label className="text-sm text-hifi-silver mb-2 block">{t('sources.internal.labelField')}</label>
            <input
              ref={labelRef}
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              maxLength={fs === 'exfat' ? 11 : 16}
              className="w-full bg-hifi-dark border border-hifi-accent rounded-lg px-4 py-3 text-white focus:outline-none focus:border-hifi-gold mb-6"
            />

            <div className="flex gap-3">
              <button onClick={onClose} className="flex-1 bg-hifi-accent hover:bg-hifi-dark text-white py-3 rounded-lg font-medium transition-colors">
                {t('common.cancel')}
              </button>
              <button
                onClick={() => setStep('confirm')}
                disabled={!label.trim()}
                className="flex-1 bg-hifi-gold hover:bg-yellow-600 disabled:opacity-40 text-black py-3 rounded-lg font-semibold transition-colors"
              >
                {t('common.next')}
              </button>
            </div>
          </>
        )}

        {step === 'confirm' && (
          <>
            <div className="flex items-center gap-2 mb-3 text-red-400">
              <AlertTriangle size={22} />
              <h3 className="text-white text-lg font-semibold">{t('sources.internal.warnTitle')}</h3>
            </div>
            <p className="text-hifi-silver text-sm mb-4">
              {t('sources.internal.warnBody', { model: disk.model || disk.path, size: formatSize(disk.size), path: disk.path })}
            </p>
            <label className="text-sm text-hifi-silver mb-2 block">
              {t('sources.internal.typeToConfirm', { label: label.trim() })}
            </label>
            <input
              ref={typedRef}
              type="text"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              className="w-full bg-hifi-dark border border-red-500/40 rounded-lg px-4 py-3 text-white focus:outline-none focus:border-red-400 mb-6"
            />
            <div className="flex gap-3">
              <button onClick={() => setStep('choose')} className="flex-1 bg-hifi-accent hover:bg-hifi-dark text-white py-3 rounded-lg font-medium transition-colors">
                {t('common.back')}
              </button>
              <button
                onClick={startFormat}
                disabled={!canFormat}
                className="flex-1 bg-red-600 hover:bg-red-700 disabled:opacity-40 text-white py-3 rounded-lg font-semibold transition-colors"
              >
                {t('sources.internal.formatNow')}
              </button>
            </div>
          </>
        )}

        {step === 'progress' && (
          <div className="text-center py-4">
            <Loader2 className="w-14 h-14 text-hifi-accent animate-spin mx-auto mb-6" />
            <p className="text-white/80 text-base mb-6 min-h-[1.5rem]">{status?.message || t('sources.internal.phasePreparing')}</p>
            <div className="w-full h-3 bg-hifi-dark rounded-full overflow-hidden">
              <motion.div
                className="h-full rounded-full bg-hifi-accent"
                animate={{ width: `${pct}%` }}
                transition={{ ease: 'easeOut', duration: 0.4 }}
              />
            </div>
            <p className="mt-3 text-hifi-silver/50 text-sm">{t('sources.internal.keepPowered')}</p>
          </div>
        )}

        {step === 'done' && (
          <div className="text-center py-4">
            <CheckCircle2 className="w-14 h-14 text-green-500 mx-auto mb-6" />
            <p className="text-white text-lg font-semibold mb-2">{t('sources.internal.doneAdopted')}</p>
            <p className="text-hifi-silver/70 text-sm mb-6">{t('sources.internal.doneHint')}</p>
            <button onClick={onDone} className="w-full bg-hifi-gold hover:bg-yellow-600 text-black py-3 rounded-lg font-semibold transition-colors">
              {t('sources.internal.close')}
            </button>
          </div>
        )}

        {step === 'error' && (
          <div className="text-center py-4">
            <AlertTriangle className="w-14 h-14 text-red-500 mx-auto mb-6" />
            <p className="text-white text-lg font-semibold mb-2">{t('common.error')}</p>
            <p className="text-hifi-silver/70 text-sm mb-6">{errorMsg}</p>
            <button onClick={onClose} className="w-full bg-hifi-accent hover:bg-hifi-dark text-white py-3 rounded-lg font-semibold transition-colors">
              {t('sources.internal.close')}
            </button>
          </div>
        )}
      </motion.div>
    </motion.div>
  );
}

function SmbCard({ smb, t, onRegenerated }) {
  const [showPass, setShowPass] = useState(false);
  const [copied, setCopied] = useState(false);
  const [regenBusy, setRegenBusy] = useState(false);

  const copyPass = async () => {
    try {
      await navigator.clipboard.writeText(smb.password || '');
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (_) { /* clipboard unavailable, ignore */ }
  };

  const regenerate = async () => {
    setRegenBusy(true);
    try {
      await fetch(SRC + '/api/internal/smb/regenerate', { method: 'POST' });
      if (onRegenerated) onRegenerated();
    } catch (_) { /* transient network hiccup, user can retry */ } finally { setRegenBusy(false); }
  };

  if (!smb.installed) {
    return (
      <div className="mt-3 rounded-lg p-3 text-sm bg-yellow-900/20 text-yellow-300 border border-yellow-500/30">
        {t('sources.internal.needOsUpdate')}
      </div>
    );
  }

  return (
    <div className="mt-3 bg-hifi-dark rounded-lg p-4 space-y-3">
      <h4 className="text-white font-semibold">{t('sources.internal.smbTitle')}</h4>
      <p className="text-hifi-silver/70 text-sm">{t('sources.internal.smbHelp')}</p>
      <div className="space-y-1 text-sm">
        {smb.shares.map((s) => (
          <React.Fragment key={s.source_id}>
            {smb.ip && <div className="text-hifi-silver">{`\\\\${smb.ip}\\${s.name}`}</div>}
            <div className="text-hifi-silver/70">{`\\\\${smb.host}\\${s.name}`}</div>
          </React.Fragment>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <div className="text-hifi-silver/60 text-xs mb-1">{t('sources.internal.smbUser')}</div>
          <div className="text-white font-mono">{smb.username}</div>
        </div>
        <div>
          <div className="text-hifi-silver/60 text-xs mb-1">{t('sources.internal.smbPass')}</div>
          <div className="flex items-center gap-2">
            <span className="text-white font-mono">{showPass ? smb.password : '••••••••••'}</span>
            <button onClick={() => setShowPass((v) => !v)} className="text-hifi-silver/60 hover:text-white">
              {showPass ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
            <button onClick={copyPass} className="text-hifi-silver/60 hover:text-white">
              {copied ? <Check size={14} className="text-green-400" /> : <Copy size={14} />}
            </button>
          </div>
        </div>
      </div>
      <div className="flex items-center justify-between pt-1">
        <p className="text-hifi-silver/50 text-xs">{t('sources.internal.smbRegenerateHint')}</p>
        <button
          onClick={regenerate}
          disabled={regenBusy}
          className="text-xs text-hifi-silver/70 hover:text-white underline disabled:opacity-50 shrink-0 ml-3"
        >
          {t('sources.internal.smbRegenerate')}
        </button>
      </div>
    </div>
  );
}

export default function InternalDisks({ onSourcesChanged }) {
  const { t } = useI18n();
  const [disks, setDisks] = useState([]);
  const [smb, setSmb] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [wizardDisk, setWizardDisk] = useState(null);

  const j = async (url, opts) => { const r = await fetch(SRC + url, opts); return r.json(); };
  const post = (url, body) => j(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

  const loadDisks = useCallback(async () => {
    try { const d = await j('/api/internal/disks'); setDisks(d.disks || []); } catch (_) { /* service not reachable yet */ }
  }, []);
  const loadSmb = useCallback(async () => {
    try { const d = await j('/api/internal/smb'); setSmb(d); } catch (_) { /* service not reachable yet */ }
  }, []);

  useEffect(() => {
    loadDisks();
    loadSmb();
    const id = setInterval(loadDisks, 5000);
    return () => clearInterval(id);
  }, [loadDisks, loadSmb]);

  const notifyChanged = () => {
    loadDisks();
    loadSmb();
    if (onSourcesChanged) onSourcesChanged();
  };

  const adopt = async (device) => {
    setBusy(true);
    setMsg(t('sources.internal.adopting'));
    try {
      const r = await post('/api/internal/adopt', { device });
      setMsg(r.success ? t('sources.internal.adopted') : (r.message || t('common.error')));
      if (r.success) notifyChanged();
    } catch (_) { setMsg(t('common.error')); } finally { setBusy(false); }
  };

  const removeSource = async (sourceId) => {
    if (!sourceId) return;
    setBusy(true);
    try {
      await j('/api/sources/' + sourceId, { method: 'DELETE' });
      setMsg(t('sources.internal.removed'));
      notifyChanged();
    } catch (_) { setMsg(t('common.error')); } finally { setBusy(false); }
  };

  const hasAdoptedShares = smb && Array.isArray(smb.shares) && smb.shares.length > 0;

  return (
    <div>
      <h3 className="text-white font-semibold mb-3 flex items-center space-x-2">
        <HardDrive size={18} className="text-hifi-gold" />
        <span>{t('sources.internal.title')}</span>
      </h3>
      <div className="space-y-3">
        {disks.length === 0 && <p className="text-sm text-hifi-silver/70">{t('sources.internal.none')}</p>}
        {disks.map((d) => {
          const fsPartitions = (d.partitions || []).filter((p) => p.fstype);
          return (
            <div key={d.path} className="bg-hifi-dark rounded-lg p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-white text-sm truncate">
                    {d.model || d.path}
                    <span className="ml-2 text-[10px] uppercase tracking-wide text-hifi-gold/80">{formatSize(d.size)}</span>
                    {d.adopted && (
                      <span className="ml-2 text-[10px] uppercase tracking-wide text-green-400">{t('sources.internal.adoptedBadge')}</span>
                    )}
                    {!d.adopted && d.has_data && (
                      <span className="ml-2 text-[10px] uppercase tracking-wide text-hifi-silver/60">{t('sources.internal.hasData')}</span>
                    )}
                  </div>
                  <div className="text-xs text-hifi-silver/70 truncate">
                    {d.path}{d.fstype ? ` · ${d.fstype}` : ''}{d.label ? ` · ${d.label}` : ''}
                  </div>
                </div>
                {d.adopted ? (
                  <div className="flex gap-2 shrink-0">
                    <button
                      onClick={() => removeSource(d.source_id)}
                      disabled={busy}
                      className="text-xs bg-red-900/30 hover:bg-red-900/60 text-red-300 py-1.5 px-3 rounded-md"
                    >
                      {t('sources.internal.remove')}
                    </button>
                  </div>
                ) : (
                  <div className="flex gap-2 shrink-0">
                    {fsPartitions.length === 1 && (
                      <button
                        onClick={() => adopt(fsPartitions[0].path)}
                        disabled={busy}
                        className="text-xs bg-hifi-accent hover:bg-hifi-light text-white py-1.5 px-3 rounded-md"
                      >
                        {t('sources.internal.adopt')}
                      </button>
                    )}
                    <button
                      onClick={() => setWizardDisk(d)}
                      disabled={busy}
                      className="text-xs bg-red-900/40 hover:bg-red-900/70 text-red-300 py-1.5 px-3 rounded-md"
                    >
                      {t('sources.internal.format')}
                    </button>
                  </div>
                )}
              </div>
              {!d.adopted && fsPartitions.length > 1 && (
                <div className="mt-2 space-y-1">
                  {fsPartitions.map((p) => (
                    <div key={p.path} className="flex items-center justify-between pl-2">
                      <span className="text-hifi-silver text-sm truncate">{p.path} · {p.fstype}{p.label ? ` · ${p.label}` : ''}</span>
                      <button
                        onClick={() => adopt(p.path)}
                        disabled={busy}
                        className="ml-3 shrink-0 text-xs bg-hifi-gold/20 hover:bg-hifi-gold/30 text-hifi-gold py-1 px-3 rounded-md"
                      >
                        {t('sources.internal.adopt')}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {msg && (
        <div className="mt-3 rounded-lg p-3 text-center text-sm bg-hifi-dark text-hifi-silver">{msg}</div>
      )}

      {hasAdoptedShares && <SmbCard smb={smb} t={t} onRegenerated={loadSmb} />}

      {wizardDisk && (
        <FormatWizard
          disk={wizardDisk}
          t={t}
          onClose={() => setWizardDisk(null)}
          onDone={() => { setWizardDisk(null); notifyChanged(); }}
        />
      )}
    </div>
  );
}
