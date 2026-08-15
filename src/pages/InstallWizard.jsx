import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { QRCodeSVG } from 'qrcode.react';
import { HardDrive, ChevronRight, ChevronLeft, Loader2, AlertCircle, CheckCircle2, Disc3, RefreshCw, Smartphone } from 'lucide-react';
import { systemAPI } from '../utils/api';

// Keyboard-only focus ring (focus-visible, not plain focus) — this screen is
// meant to be operable with just a keyboard, so tabbing through it needs to
// stay legible without adding a ring on every mouse/touch click too.
const FOCUS_RING = 'focus:outline-none focus-visible:ring-2 focus-visible:ring-hifi-gold focus-visible:ring-offset-2 focus-visible:ring-offset-hifi-dark';

// Always-on QR badge, not a step you have to click into — a box with no
// mouse/keyboard/touchscreen attached at all still needs a way in, so the
// phone hand-off can't be gated behind an on-screen tap.
const QrCorner = ({ apInfo, wired, deviceIp }) => {
  const showHotspot = apInfo?.ssid && !wired;
  const value = showHotspot
    ? `WIFI:T:WPA;S:${apInfo.ssid};P:${apInfo.psk || ''};;`
    : `http://${deviceIp || 'hifiplayer.local'}`;
  return (
    <div className="absolute top-16 right-4 z-[65] flex flex-col items-center bg-white rounded-xl p-2.5 shadow-lg">
      <QRCodeSVG value={value} size={104} />
      <span className="text-black/70 text-[10px] mt-1.5 flex items-center gap-1 max-w-[104px] text-center leading-tight">
        <Smartphone size={11} className="shrink-0" />
        {showHotspot ? apInfo.ssid : (deviceIp ? `http://${deviceIp}` : 'http://hifiplayer.local')}
      </span>
    </div>
  );
};

/**
 * Installer UI shown when this live session was booted from the
 * "Install Osmium Sound" boot menu entry (kernel param hifi.installer=1,
 * detected via systemAPI.getBootMode() — see api_server.py get_boot_mode()).
 * Replaces Debian Installer entirely.
 *
 * Two ways to drive it, both live at once and both end up calling the same
 * hifi-disk-install.sh via the same /install/* endpoints:
 *  - On-screen: welcome → disk → confirm, driven locally with a
 *    mouse/keyboard/touch attached to this machine.
 *  - Remote: the QrCorner badge is always on screen (not a step you have to
 *    click into — a box with no mouse/keyboard/touchscreen at all still
 *    needs a way in), scannable from the very first frame. It opens
 *    webui_server.py's captive portal (INSTALL_CAPTIVE_HTML) on the phone to
 *    pick the disk and confirm from there instead.
 * Either path can be the one that actually starts the install — this screen
 * always mirrors /install/status, so if the phone starts it the on-screen
 * wizard (if left open) jumps straight to the progress view too. Once the
 * install finishes, this screen auto-reboots on its own after a short
 * countdown — it doesn't depend on whichever side started it still being
 * connected.
 */
const InstallWizard = () => {
  const [step, setStep] = useState('welcome'); // welcome | disk | confirm
  const [apInfo, setApInfo] = useState(null);
  const [wired, setWired] = useState(false);
  const [deviceIp, setDeviceIp] = useState(null);
  const [disks, setDisks] = useState([]);
  const [disksLoading, setDisksLoading] = useState(false);
  const [disksError, setDisksError] = useState('');
  const [selectedDisk, setSelectedDisk] = useState(null);
  const [status, setStatus] = useState({ state: 'idle', progress: 0, message: '' });
  const [localError, setLocalError] = useState('');
  const [ignoreRemoteError, setIgnoreRemoteError] = useState(false);
  const [countdown, setCountdown] = useState(null);
  const rebootedRef = useRef(null);
  const pollRef = useRef(null);

  useEffect(() => {
    let alive = true;
    const pollAp = async () => {
      try {
        const res = await systemAPI.getProvisionStatus();
        if (!alive || !res.success || !res.data) return;
        if (res.data.ap?.ssid) setApInfo(res.data.ap);
        setWired(!!res.data.wired);
      } catch (_) {}
    };
    pollAp();
    const apId = setInterval(pollAp, 5000);

    // The device's own IP, not just the hostname: hifiplayer.local is
    // ambiguous the moment more than one Osmium Sound unit is on the same
    // network (mDNS resolves to whichever one answers first) — the IP is
    // always unambiguous, so it's what the QR should actually encode.
    const pollIp = async () => {
      try {
        const res = await systemAPI.getNetworkStatus();
        if (alive && res.success && res.data?.ip) { setDeviceIp(res.data.ip); return; }
        const info = await systemAPI.getSystemInfo();
        if (alive && info.success && info.data?.local_ip && info.data.local_ip !== 'Unknown') {
          setDeviceIp(info.data.local_ip);
        }
      } catch (_) {}
    };
    pollIp();
    const ipId = setInterval(pollIp, 5000);

    return () => { alive = false; clearInterval(apId); clearInterval(ipId); };
  }, []);

  // Always mirrors /install/status, regardless of which side (this screen or
  // a phone on the captive portal) actually kicked the install off.
  useEffect(() => {
    let alive = true;
    const pollInstall = async () => {
      try {
        const res = await systemAPI.getInstallStatus();
        if (alive && res.success && res.data) setStatus(res.data);
      } catch (_) {}
    };
    pollInstall();
    pollRef.current = setInterval(pollInstall, 1500);
    return () => { alive = false; clearInterval(pollRef.current); };
  }, []);

  // Auto-reboot a few seconds after the install reports done — never a
  // button, and not dependent on whichever side started it still being on
  // the page.
  useEffect(() => {
    if (status.state !== 'done' || rebootedRef.current) return;
    setCountdown(5);
    const id = setInterval(() => {
      setCountdown((n) => {
        if (n <= 1) {
          clearInterval(id);
          if (!rebootedRef.current) {
            rebootedRef.current = true;
            systemAPI.reboot().catch(() => {});
          }
          return 0;
        }
        return n - 1;
      });
    }, 1000);
    return () => clearInterval(id);
  }, [status.state]);

  const loadDisks = useCallback(async () => {
    setDisksLoading(true);
    setDisksError('');
    try {
      const res = await systemAPI.getInstallDisks();
      if (res.success && res.data?.success) {
        setDisks(res.data.disks || []);
      } else {
        setDisksError(res.data?.message || 'No disks available.');
      }
    } catch (_) {
      setDisksError('No disks available.');
    }
    setDisksLoading(false);
  }, []);

  useEffect(() => {
    if (step === 'disk') loadDisks();
  }, [step, loadDisks]);

  const startInstall = async () => {
    if (!selectedDisk) return;
    setLocalError('');
    setIgnoreRemoteError(false);
    const res = await systemAPI.startInstall(selectedDisk.path);
    if (!res.success || res.data?.success === false) {
      setLocalError(res.data?.message || res.message || '');
    }
  };

  const retry = () => {
    setSelectedDisk(null);
    setLocalError('');
    setIgnoreRemoteError(true);
    setStep('disk');
  };

  const formatSize = (bytes) => {
    const n = Number(bytes);
    if (!n) return '';
    const gb = n / (1024 ** 3);
    return gb >= 1000 ? `${(gb / 1024).toFixed(1)} TB` : `${gb.toFixed(0)} GB`;
  };

  // The remote (phone) side can start/finish/fail an install at any time,
  // independently of whatever step this screen happens to be sitting on —
  // so progress/done always win over the local welcome/disk/confirm wizard.
  // A remote error only wins until the user explicitly retries on-screen
  // (ignoreRemoteError), so a stale error from a previous attempt doesn't
  // trap the local disk picker.
  const showProgress = !localError && (
    status.state === 'running' ||
    status.state === 'done' ||
    (status.state === 'error' && !ignoreRemoteError)
  );
  const errorMessage = localError || (status.state === 'error' ? status.message : '');
  const showError = !!localError || (showProgress && status.state === 'error');

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

  if (showProgress || localError) {
    return (
      <AnimatePresence>
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}
          className="absolute inset-0 z-[60] bg-hifi-dark flex flex-col items-center justify-center font-display overflow-hidden px-8">
          <motion.div initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ delay: 0.1 }}
            className="flex flex-col items-center text-center max-w-md">
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-hifi-gold to-yellow-600 flex items-center justify-center shadow-[0_0_40px_rgba(212,175,55,0.3)] mb-6">
              {status.state === 'done' ? <CheckCircle2 size={32} className="text-black" /> : <Disc3 size={32} className="text-black" />}
            </div>

            <div className="w-full max-w-sm">
              <h2 className="text-xl font-bold text-white mb-1">
                {showError ? 'Installation failed'
                  : status.state === 'done' ? 'Installation complete'
                  : 'Installing…'}
              </h2>
              <p className="text-hifi-silver/60 text-sm mb-6">
                {showError ? errorMessage
                  : status.message || (status.state === 'done' ? 'Remove the boot media (USB/DVD) now — rebooting automatically.' : 'Do not power off or remove the boot media.')}
              </p>
              {!showError && status.state === 'running' && (
                <div className="w-full h-2 rounded-full bg-hifi-border overflow-hidden">
                  <div className="h-full bg-hifi-gold transition-all" style={{ width: `${Math.max(0, Math.min(100, status.progress || 0))}%` }} />
                </div>
              )}
              {!showError && status.state === 'done' && countdown != null && (
                <p className="text-hifi-silver/50 text-xs mt-4">{`Rebooting in ${countdown}s…`}</p>
              )}
              {showError && (
                <button onClick={retry} className={`mt-2 bg-hifi-gold text-black font-semibold px-6 py-2.5 rounded-xl hover:brightness-110 transition ${FOCUS_RING}`}>
                  Retry
                </button>
              )}
            </div>
          </motion.div>
        </motion.div>
      </AnimatePresence>
    );
  }

  return (
    <AnimatePresence mode="wait">
      <motion.div key={step} initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} transition={{ duration: 0.2 }} className="absolute inset-0 z-[60]">

        {step === 'welcome' && (
          <div className="absolute inset-0 z-[60] bg-hifi-dark flex flex-col items-center justify-center font-display overflow-hidden px-8">
            <QrCorner apInfo={apInfo} wired={wired} deviceIp={deviceIp} />
            <motion.div initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ delay: 0.1 }}
              className="flex flex-col items-center text-center max-w-md">
              <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-hifi-gold to-yellow-600 flex items-center justify-center shadow-[0_0_40px_rgba(212,175,55,0.3)] mb-6">
                <Disc3 size={40} className="text-black" />
              </div>
              <h1 className="text-3xl font-bold text-white mb-3">Install Osmium Sound</h1>
              <p className="text-hifi-silver/70 leading-relaxed mb-8">This will install Osmium Sound onto this computer's disk. All data on the chosen disk will be erased.</p>
              <button onClick={() => setStep('disk')} className={`flex items-center space-x-2 bg-hifi-gold text-black font-semibold px-8 py-3 rounded-xl hover:brightness-110 transition ${FOCUS_RING}`}>
                <span>Choose disk</span><ChevronRight size={18} />
              </button>
              <p className="mt-6 flex items-center space-x-1 text-hifi-silver/50 text-xs">
                <Smartphone size={13} /><span>Or scan the QR code (top right) to use your phone instead</span>
              </p>
            </motion.div>
          </div>
        )}

        {step === 'disk' && (
          <Shell footer={
            <button onClick={() => setStep('welcome')} className={`flex items-center space-x-1 text-hifi-silver/60 hover:text-white transition rounded-md px-2 py-1 ${FOCUS_RING}`}>
              <ChevronLeft size={18} /><span className="text-sm">Back</span>
            </button>
          }>
            <QrCorner apInfo={apInfo} wired={wired} deviceIp={deviceIp} />
            <div className="w-full max-w-lg">
              <h2 className="text-2xl font-bold text-white mb-1 text-center">Choose the installation disk</h2>
              <p className="text-hifi-silver/60 text-sm text-center mb-8">The selected disk will be wiped and fully replaced by Osmium Sound.</p>

              {disksLoading && (
                <p className="text-center text-hifi-silver/60 text-sm flex items-center justify-center">
                  <Loader2 size={15} className="animate-spin mr-2" />Looking for disks…
                </p>
              )}

              {!disksLoading && disks.length === 0 && (
                <div className="text-center">
                  <p className="text-hifi-silver/60 text-sm mb-4 flex items-center justify-center">
                    <AlertCircle size={15} className="mr-2" />{disksError || 'No disks available.'}
                  </p>
                  <button onClick={loadDisks} className={`inline-flex items-center space-x-2 bg-hifi-surface hover:bg-hifi-light px-4 py-2 rounded-xl text-sm text-white transition ${FOCUS_RING}`}>
                    <RefreshCw size={14} /><span>Refresh list</span>
                  </button>
                </div>
              )}

              {!disksLoading && disks.length > 0 && (
                <div className="space-y-3">
                  {disks.map((d) => (
                    <button
                      key={d.path}
                      onClick={() => { setSelectedDisk(d); setStep('confirm'); }}
                      className={`w-full flex items-center space-x-4 bg-hifi-surface hover:bg-hifi-light rounded-2xl border border-hifi-border hover:border-hifi-gold/50 transition px-5 py-4 text-left ${FOCUS_RING}`}
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
            <button onClick={() => setStep('disk')} className={`flex items-center space-x-1 text-hifi-silver/60 hover:text-white transition rounded-md px-2 py-1 ${FOCUS_RING}`}>
              <ChevronLeft size={18} /><span className="text-sm">Back</span>
            </button>
          }>
            <div className="w-full max-w-lg text-center">
              <AlertCircle size={40} className="text-amber-400 mb-4 mx-auto" />
              <h2 className="text-2xl font-bold text-white mb-4">Confirm installation?</h2>
              <div className="rounded-2xl border border-amber-500/30 bg-amber-900/10 p-5 mb-6">
                <p className="text-sm text-amber-200">
                  {`ALL DATA on ${selectedDisk.model || selectedDisk.path} (${selectedDisk.path}) will be permanently erased. This cannot be undone.`}
                </p>
              </div>
              <button onClick={startInstall} className={`w-full bg-amber-600 hover:bg-amber-500 text-white font-semibold px-6 py-3 rounded-xl transition ${FOCUS_RING}`}>
                Erase and install
              </button>
            </div>
          </Shell>
        )}

      </motion.div>
    </AnimatePresence>
  );
};

export default InstallWizard;
