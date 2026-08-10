import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { QRCodeSVG } from 'qrcode.react';
import { Disc3, CheckCircle2 } from 'lucide-react';
import { systemAPI } from '../utils/api';
import { useI18n } from '../i18n';

/**
 * Installer UI shown when this live session was booted from the
 * "Install Osmium Sound" boot menu entry (kernel param hifi.installer=1,
 * detected via systemAPI.getBootMode() — see api_server.py get_boot_mode()).
 * Replaces Debian Installer entirely.
 *
 * No mouse/keyboard/touch required: this screen only shows branding, the
 * setup hotspot's QR code, and a read-only progress mirror. Disk selection,
 * the erase confirmation, and starting the install all happen on a phone/
 * browser connected to that hotspot, served by webui_server.py's captive
 * portal (see INSTALL_CAPTIVE_HTML there), which calls
 * hifi-disk-install.sh via the same /install/* endpoints this screen only
 * reads from. Once the install finishes, this screen auto-reboots on its
 * own after a short countdown — it doesn't depend on the phone still being
 * connected.
 */
const InstallWizard = () => {
  const { t } = useI18n();
  const [apInfo, setApInfo] = useState(null);
  const [wired, setWired] = useState(false);
  const [deviceIp, setDeviceIp] = useState(null);
  const [status, setStatus] = useState({ state: 'idle', progress: 0, message: '' });
  const [countdown, setCountdown] = useState(null);
  const rebootedRef = useRef(false);

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

    const pollInstall = async () => {
      try {
        const res = await systemAPI.getInstallStatus();
        if (alive && res.success && res.data) setStatus(res.data);
      } catch (_) {}
    };
    pollInstall();
    const installId = setInterval(pollInstall, 1500);

    return () => { alive = false; clearInterval(apId); clearInterval(ipId); clearInterval(installId); };
  }, []);

  // Auto-reboot a few seconds after the install reports done — never a
  // button, and not dependent on the phone that started it still being on
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

  const showProgress = status.state === 'running' || status.state === 'done' || status.state === 'error';

  return (
    <AnimatePresence>
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}
        className="absolute inset-0 z-[60] bg-hifi-dark flex flex-col items-center justify-center font-display overflow-hidden px-8">
        <motion.div initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ delay: 0.1 }}
          className="flex flex-col items-center text-center max-w-md">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-hifi-gold to-yellow-600 flex items-center justify-center shadow-[0_0_40px_rgba(212,175,55,0.3)] mb-6">
            {status.state === 'done' ? <CheckCircle2 size={32} className="text-black" /> : <Disc3 size={32} className="text-black" />}
          </div>

          {!showProgress && (
            <>
              <h1 className="text-2xl font-bold text-white mb-2">{t('installer.qr.title')}</h1>
              <p className="text-hifi-silver/70 text-sm leading-relaxed mb-8">{t('installer.qr.subtitle')}</p>
              {apInfo?.ssid && !wired ? (
                <div className="inline-flex flex-col items-center bg-white rounded-2xl p-4">
                  <QRCodeSVG value={`WIFI:T:WPA;S:${apInfo.ssid};P:${apInfo.psk || ''};;`} size={180} />
                  <span className="text-black text-xs mt-2">{apInfo.ssid}</span>
                </div>
              ) : (
                // Either no hotspot info (yet) — e.g. no Wi-Fi radio on this
                // hardware/VM, or the AP hasn't come up — or a wired connection
                // is already up, in which case skip the hotspot and point
                // straight at the device since the phone can join the same LAN.
                // Prefer the device's own IP over the hifiplayer.local hostname:
                // the hostname is ambiguous the moment more than one Osmium Sound
                // unit is on the same network (mDNS answers with whichever
                // responds first), the IP never is.
                <div className="inline-flex flex-col items-center bg-white rounded-2xl p-4">
                  <QRCodeSVG value={`http://${deviceIp || 'hifiplayer.local'}`} size={180} />
                  <span className="text-black text-xs mt-2">
                    {deviceIp ? `http://${deviceIp}` : 'http://hifiplayer.local'}
                  </span>
                  {deviceIp && <span className="text-black/50 text-[10px] mt-0.5">http://hifiplayer.local</span>}
                </div>
              )}
            </>
          )}

          {showProgress && (
            <div className="w-full max-w-sm">
              <h2 className="text-xl font-bold text-white mb-1">
                {status.state === 'done' ? t('installer.done.title')
                  : status.state === 'error' ? t('installer.error.title')
                  : t('installer.progress.title')}
              </h2>
              <p className="text-hifi-silver/60 text-sm mb-6">
                {status.message || (status.state === 'done' ? t('installer.done.subtitle') : t('installer.progress.subtitle'))}
              </p>
              {status.state === 'running' && (
                <div className="w-full h-2 rounded-full bg-hifi-border overflow-hidden">
                  <div className="h-full bg-hifi-gold transition-all" style={{ width: `${Math.max(0, Math.min(100, status.progress || 0))}%` }} />
                </div>
              )}
              {status.state === 'done' && countdown != null && (
                <p className="text-hifi-silver/50 text-xs mt-4">{t('installer.done.rebootIn', { n: countdown })}</p>
              )}
            </div>
          )}
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
};

export default InstallWizard;
