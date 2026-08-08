import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { HardDrive, ChevronRight, ChevronLeft, Loader2, AlertCircle, CheckCircle2, Disc3, RefreshCw } from 'lucide-react';
import { systemAPI } from '../utils/api';
import { useI18n } from '../i18n';

/**
 * Installer UI shown when this live session was booted from the
 * "Install Osmium Sound" boot menu entry (kernel param hifi.installer=1,
 * detected via systemAPI.getBootMode() — see api_server.py get_boot_mode()).
 * Replaces Debian Installer entirely: picks a target disk, then drives
 * hifi-disk-install.sh (via systemAPI.startInstall/getInstallStatus)
 * to partition/copy/bootloader the running live system onto it.
 *
 * Steps: welcome → disk → confirm → progress → done | error
 */
const InstallWizard = () => {
  const { t } = useI18n();
  const [step, setStep] = useState('welcome');
  const [disks, setDisks] = useState([]);
  const [disksLoading, setDisksLoading] = useState(false);
  const [disksError, setDisksError] = useState('');
  const [selectedDisk, setSelectedDisk] = useState(null);
  const [progress, setProgress] = useState(0);
  const [progressMsg, setProgressMsg] = useState('');
  const [errorMsg, setErrorMsg] = useState('');
  const pollRef = useRef(null);

  const loadDisks = useCallback(async () => {
    setDisksLoading(true);
    setDisksError('');
    try {
      const res = await systemAPI.getInstallDisks();
      if (res.success && res.data?.success) {
        setDisks(res.data.disks || []);
      } else {
        setDisksError(res.data?.message || t('installer.disk.none'));
      }
    } catch (_) {
      setDisksError(t('installer.disk.none'));
    }
    setDisksLoading(false);
  }, [t]);

  useEffect(() => {
    if (step === 'disk') loadDisks();
  }, [step, loadDisks]);

  useEffect(() => {
    if (step !== 'progress') return;
    pollRef.current = setInterval(async () => {
      try {
        const res = await systemAPI.getInstallStatus();
        const st = res.data || {};
        if (typeof st.progress === 'number') setProgress(st.progress);
        if (st.message) setProgressMsg(st.message);
        if (st.state === 'done') {
          clearInterval(pollRef.current);
          setStep('done');
        } else if (st.state === 'error') {
          clearInterval(pollRef.current);
          setErrorMsg(st.message || '');
          setStep('error');
        }
      } catch (_) {}
    }, 1500);
    return () => clearInterval(pollRef.current);
  }, [step]);

  const startInstall = async () => {
    if (!selectedDisk) return;
    setProgress(0);
    setProgressMsg('');
    setStep('progress');
    const res = await systemAPI.startInstall(selectedDisk.path);
    if (!res.success || res.data?.success === false) {
      setErrorMsg(res.data?.message || res.message || '');
      setStep('error');
    }
  };

  const formatSize = (bytes) => {
    const n = Number(bytes);
    if (!n) return '';
    const gb = n / (1024 ** 3);
    return gb >= 1000 ? `${(gb / 1024).toFixed(1)} TB` : `${gb.toFixed(0)} GB`;
  };

  const Shell = ({ children, footer }) => (
    <div className="absolute inset-0 z-[60] bg-hifi-dark flex flex-col font-display overflow-hidden">
      <div className="flex items-center px-6 h-12 shrink-0 border-b border-hifi-border/60">
        <div className="flex items-center space-x-2">
          <div className="w-2 h-2 rounded-full bg-hifi-gold shadow-[0_0_6px_rgba(212,175,55,0.8)]" />
          <span className="text-[11px] font-bold tracking-[0.2em] text-hifi-silver/70 uppercase">Osmium Sound</span>
        </div>
      </div>
      <div className="flex-1 min-h-0 flex flex-col items-center justify-center px-8 overflow-y-auto content-scrollbar">
        {children}
      </div>
      {footer && <div className="shrink-0 px-8 py-4 border-t border-hifi-border/60 flex items-center justify-between">{footer}</div>}
    </div>
  );

  return (
    <AnimatePresence mode="wait">
      <motion.div key={step} initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} transition={{ duration: 0.2 }} className="absolute inset-0 z-[60]">

        {step === 'welcome' && (
          <Shell footer={
            <div className="ml-auto">
              <button onClick={() => setStep('disk')} className="flex items-center space-x-2 bg-hifi-gold text-black font-semibold px-6 py-2.5 rounded-xl hover:brightness-110 transition">
                <span>{t('installer.start')}</span><ChevronRight size={18} />
              </button>
            </div>
          }>
            <motion.div initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ delay: 0.1 }} className="flex flex-col items-center text-center max-w-md">
              <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-hifi-gold to-yellow-600 flex items-center justify-center shadow-[0_0_40px_rgba(212,175,55,0.3)] mb-6">
                <Disc3 size={40} className="text-black" />
              </div>
              <h1 className="text-3xl font-bold text-white mb-3">{t('installer.welcome.title')}</h1>
              <p className="text-hifi-silver/70 leading-relaxed">{t('installer.welcome.subtitle')}</p>
            </motion.div>
          </Shell>
        )}

        {step === 'disk' && (
          <Shell footer={
            <button onClick={() => setStep('welcome')} className="flex items-center space-x-1 text-hifi-silver/60 hover:text-white transition">
              <ChevronLeft size={18} /><span className="text-sm">{t('common.back')}</span>
            </button>
          }>
            <div className="w-full max-w-lg">
              <h2 className="text-2xl font-bold text-white mb-1 text-center">{t('installer.disk.title')}</h2>
              <p className="text-hifi-silver/60 text-sm text-center mb-8">{t('installer.disk.subtitle')}</p>

              {disksLoading && (
                <p className="text-center text-hifi-silver/60 text-sm flex items-center justify-center">
                  <Loader2 size={15} className="animate-spin mr-2" />{t('installer.disk.loading')}
                </p>
              )}

              {!disksLoading && disks.length === 0 && (
                <div className="text-center">
                  <p className="text-hifi-silver/60 text-sm mb-4 flex items-center justify-center">
                    <AlertCircle size={15} className="mr-2" />{disksError || t('installer.disk.none')}
                  </p>
                  <button onClick={loadDisks} className="inline-flex items-center space-x-2 bg-hifi-surface hover:bg-hifi-light px-4 py-2 rounded-xl text-sm text-white transition">
                    <RefreshCw size={14} /><span>{t('installer.disk.refresh')}</span>
                  </button>
                </div>
              )}

              {!disksLoading && disks.length > 0 && (
                <div className="space-y-3">
                  {disks.map((d) => (
                    <button
                      key={d.path}
                      onClick={() => { setSelectedDisk(d); setStep('confirm'); }}
                      className="w-full flex items-center space-x-4 bg-hifi-surface hover:bg-hifi-light rounded-2xl border border-hifi-border hover:border-hifi-gold/50 transition px-5 py-4 text-left"
                    >
                      <HardDrive size={28} className="text-hifi-gold shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="text-white font-medium truncate">{d.model || d.path}</div>
                        <div className="text-hifi-silver/50 text-xs">{d.path} · {formatSize(d.size)}{d.transport ? ` · ${d.transport}` : ''}</div>
                      </div>
                      <ChevronRight size={18} className="text-hifi-silver/40 shrink-0" />
                    </button>
                  ))}
                </div>
              )}
            </div>
          </Shell>
        )}

        {step === 'confirm' && selectedDisk && (
          <Shell footer={
            <button onClick={() => setStep('disk')} className="flex items-center space-x-1 text-hifi-silver/60 hover:text-white transition">
              <ChevronLeft size={18} /><span className="text-sm">{t('common.back')}</span>
            </button>
          }>
            <div className="w-full max-w-lg text-center">
              <AlertCircle size={40} className="text-amber-400 mb-4 mx-auto" />
              <h2 className="text-2xl font-bold text-white mb-4">{t('installer.confirm.title')}</h2>
              <div className="rounded-2xl border border-amber-500/30 bg-amber-900/10 p-5 mb-6">
                <p className="text-sm text-amber-200">
                  {t('installer.confirm.warning', { disk: `${selectedDisk.model || selectedDisk.path} (${selectedDisk.path})` })}
                </p>
              </div>
              <button onClick={startInstall} className="w-full bg-amber-600 hover:bg-amber-500 text-white font-semibold px-6 py-3 rounded-xl transition">
                {t('installer.confirm.button')}
              </button>
            </div>
          </Shell>
        )}

        {step === 'progress' && (
          <Shell>
            <div className="w-full max-w-lg text-center">
              <Loader2 size={40} className="text-hifi-gold mb-4 mx-auto animate-spin" />
              <h2 className="text-2xl font-bold text-white mb-1">{t('installer.progress.title')}</h2>
              <p className="text-hifi-silver/60 text-sm mb-8">{t('installer.progress.subtitle')}</p>
              <div className="w-full h-2 rounded-full bg-hifi-border overflow-hidden mb-3">
                <div className="h-full bg-hifi-gold transition-all" style={{ width: `${Math.max(0, Math.min(100, progress))}%` }} />
              </div>
              <p className="text-hifi-silver/50 text-xs">{progressMsg}</p>
            </div>
          </Shell>
        )}

        {step === 'done' && (
          <Shell>
            <div className="w-full max-w-lg text-center">
              <CheckCircle2 size={48} className="text-green-400 mb-4 mx-auto" />
              <h2 className="text-2xl font-bold text-white mb-1">{t('installer.done.title')}</h2>
              <p className="text-hifi-silver/60 text-sm mb-8">{t('installer.done.subtitle')}</p>
              <button onClick={() => systemAPI.reboot()} className="bg-hifi-gold text-black font-semibold px-6 py-2.5 rounded-xl hover:brightness-110 transition">
                {t('installer.done.reboot')}
              </button>
            </div>
          </Shell>
        )}

        {step === 'error' && (
          <Shell>
            <div className="w-full max-w-lg text-center">
              <AlertCircle size={48} className="text-red-400 mb-4 mx-auto" />
              <h2 className="text-2xl font-bold text-white mb-1">{t('installer.error.title')}</h2>
              {errorMsg && <p className="text-hifi-silver/60 text-sm mb-8">{errorMsg}</p>}
              <button onClick={() => { setSelectedDisk(null); setStep('disk'); }} className="bg-hifi-gold text-black font-semibold px-6 py-2.5 rounded-xl hover:brightness-110 transition">
                {t('installer.error.retry')}
              </button>
            </div>
          </Shell>
        )}

      </motion.div>
    </AnimatePresence>
  );
};

export default InstallWizard;
