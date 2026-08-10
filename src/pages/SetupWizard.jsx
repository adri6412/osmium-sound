import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { QRCodeSVG } from 'qrcode.react';
import { Disc3, Server } from 'lucide-react';
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
    return () => { alive = false; clearInterval(id); };
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
            <div className="flex flex-col items-center text-hifi-silver/60">
              <Server size={32} className="mb-3" />
              <p className="text-sm">http://hifiplayer.local</p>
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
