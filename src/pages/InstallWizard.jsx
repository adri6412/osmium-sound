import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { QRCodeSVG } from 'qrcode.react';
import { Disc3, Server, CheckCircle2 } from 'lucide-react';
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
  const [status, setStatus] = useState({ state: 'idle', progress: 0, message: '' });
  const [countdown, setCountdown] = useState(null);
  const rebootedRef = useRef(false);

  useEffect(() => {
    let alive = true;
    const pollAp = async () => {
      try {
        const res = await systemAPI.getProvisionStatus();
        if (alive && res.success && res.data?.ap?.ssid) setApInfo(res.data.ap);
      } catch (_) {}
    };
    pollAp();
    const apId = setInterval(pollAp, 5000);

    const pollInstall = async () => {
      try {
        const res = await systemAPI.getInstallStatus();
        if (alive && res.success && res.data) setStatus(res.data);
      } catch (_) {}
    };
    pollInstall();
    const installId = setInterval(pollInstall, 1500);

    return () => { alive = false; clearInterval(apId); clearInterval(installId); };
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
              {apInfo?.ssid ? (
                <div className="inline-flex flex-col items-center bg-white rounded-2xl p-4">
                  <QRCodeSVG value={`WIFI:T:WPA;S:${apInfo.ssid};P:${apInfo.psk || ''};;`} size={180} />
                  <span className="text-black text-xs mt-2">{apInfo.ssid}</span>
                </div>
              ) : (
                <div className="flex flex-col items-center text-hifi-silver/60">
                  <Server size={32} className="mb-3" />
                  <p className="text-sm">http://hifiplayer.local</p>
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
