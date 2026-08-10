import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { QRCodeSVG } from 'qrcode.react';
import { Disc3 } from 'lucide-react';
import { systemAPI } from '../utils/api';
import { useI18n } from '../i18n';

/**
 * First-setup wizard.
 *
 * No mouse/keyboard/touch is required: the screen's only job is to display
 * branding and the setup hotspot's Wi-Fi QR code the instant it boots, then
 * wait. Every actual setup step (language, restore-from-backup, network,
 * device mode, audio, Lyrion, sources, timezone) happens on a phone/browser
 * connected to that hotspot, served by webui_server.py's captive portal —
 * see SETUP_CAPTIVE_HTML there. This component only polls provisioning
 * status and reacts once the phone side finishes (`finalize`).
 */
const SetupWizard = ({ onComplete }) => {
  const { t } = useI18n();
  const [apInfo, setApInfo] = useState(null); // { ssid, psk } from provision status
  const [deviceIp, setDeviceIp] = useState(null);
  const doneRef = useRef(false);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      if (doneRef.current) return;
      try {
        const res = await systemAPI.getProvisionStatus();
        if (!alive) return;
        if (res.success && res.data) {
          if (res.data.ap?.ssid) setApInfo(res.data.ap);
          // The phone finished setup (claim_mode + finalize already ran
          // server-side) — pick up and move on. No button, no local step.
          if (res.data.pending === false) {
            doneRef.current = true;
            localStorage.setItem('firstSetupComplete', 'true');
            onComplete?.();
          }
        }
      } catch (_) {}
    };
    poll();
    const id = setInterval(poll, 3000);

    // The device's own IP, not just the hostname: hifiplayer.local is
    // ambiguous the moment more than one Osmium Sound unit is on the same
    // network (mDNS resolves to whichever one answers first) — the IP is
    // always unambiguous, so it's what the fallback QR should encode.
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

    return () => { alive = false; clearInterval(id); clearInterval(ipId); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Optional, touch-only fallback for a bench/dev unit with no phone handy —
  // never required, never advertised beyond this one small link.
  const skip = () => {
    localStorage.setItem('firstSetupComplete', 'true');
    onComplete?.();
  };

  return (
    <AnimatePresence>
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}
        className="absolute inset-0 z-[60] bg-hifi-dark flex flex-col items-center justify-center font-display overflow-hidden px-8">
        <motion.div initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ delay: 0.1 }}
          className="flex flex-col items-center text-center max-w-md">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-hifi-gold to-yellow-600 flex items-center justify-center shadow-[0_0_40px_rgba(212,175,55,0.3)] mb-6">
            <Disc3 size={32} className="text-black" />
          </div>
          <h1 className="text-2xl font-bold text-white mb-2">{t('wizard.qr.title')}</h1>
          <p className="text-hifi-silver/70 text-sm leading-relaxed mb-8">{t('wizard.qr.subtitle')}</p>

          {apInfo?.ssid ? (
            <div className="inline-flex flex-col items-center bg-white rounded-2xl p-4">
              <QRCodeSVG value={`WIFI:T:WPA;S:${apInfo.ssid};P:${apInfo.psk || ''};;`} size={180} />
              <span className="text-black text-xs mt-2">{apInfo.ssid}</span>
            </div>
          ) : (
            // No hotspot info (yet) — still show a scannable QR pointing at the
            // URL directly. Prefer the device's own IP over hifiplayer.local:
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
        </motion.div>

        <button onClick={skip} className="absolute bottom-4 right-4 text-[11px] text-hifi-silver/30 hover:text-hifi-silver/70 transition-colors">
          {t('wizard.skip')}
        </button>
      </motion.div>
    </AnimatePresence>
  );
};

export default SetupWizard;
