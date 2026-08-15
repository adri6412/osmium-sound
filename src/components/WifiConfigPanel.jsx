import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Wifi, Lock, X, Loader2 } from 'lucide-react';
import { useI18n } from '../i18n';

/**
 * On-screen Wi-Fi network picker, shared by the first-setup kiosk wizard
 * (touch-only alternative to doing the network step from a phone connected
 * to the setup hotspot) and Settings' post-setup Network section. `networks`,
 * `scanning`, `connecting` and `error` are all driven by the parent — this
 * component only collects ssid/password and hands off to `onConnect`.
 */
const WifiConfigPanel = ({ networks, scanning, connecting, error, onConnect, onClose }) => {
  const { t } = useI18n();
  const [ssid, setSsid] = useState('');
  const [password, setPassword] = useState('');

  const submit = () => {
    if (!ssid || connecting) return;
    onConnect(ssid, password);
  };

  return (
    <AnimatePresence>
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        className="fixed inset-0 z-[70] bg-black/70 flex items-center justify-center px-6">
        <motion.div initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.95, opacity: 0 }} transition={{ duration: 0.15 }}
          className="w-full max-w-sm bg-hifi-dark border border-white/10 rounded-2xl p-5 relative">
          <button onClick={onClose} className="absolute top-4 right-4 text-hifi-silver/50 hover:text-hifi-silver">
            <X size={18} />
          </button>
          <h2 className="text-lg font-bold text-white mb-3">{t('wizard.wifi.title')}</h2>

          <div className="max-h-40 overflow-y-auto rounded-lg border border-white/10 mb-3 divide-y divide-white/5">
            {scanning ? (
              <div className="text-hifi-silver/50 text-sm px-3 py-3 flex items-center gap-2">
                <Loader2 size={14} className="animate-spin" /> {t('wizard.wifi.scanning')}
              </div>
            ) : networks.length === 0 ? (
              <div className="text-hifi-silver/50 text-sm px-3 py-3">{t('wizard.wifi.noNetworks')}</div>
            ) : networks.map((n) => (
              <button key={n.ssid} onClick={() => setSsid(n.ssid)}
                className={`w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-white/5 ${ssid === n.ssid ? 'bg-hifi-gold/10 text-hifi-gold' : 'text-hifi-silver'}`}>
                <Wifi size={14} className="shrink-0" />
                <span className="truncate flex-1">{n.ssid}</span>
                {n.security ? <Lock size={12} className="shrink-0 opacity-60" /> : null}
              </button>
            ))}
          </div>

          <input type="text" value={ssid} onChange={(e) => setSsid(e.target.value)}
            placeholder={t('wizard.wifi.title')}
            className="w-full mb-2 px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-white text-sm placeholder:text-hifi-silver/40 focus:outline-none focus:border-hifi-gold/50" />
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            placeholder={t('wizard.wifi.passwordPlaceholder')}
            className="w-full mb-3 px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-white text-sm placeholder:text-hifi-silver/40 focus:outline-none focus:border-hifi-gold/50" />

          {error && !connecting && (
            <p className="text-red-400 text-xs mb-3">{error}</p>
          )}

          <div className="flex gap-2">
            <button onClick={onClose}
              className="flex-1 py-2 rounded-lg border border-white/10 text-hifi-silver text-sm hover:bg-white/5">
              {t('common.cancel')}
            </button>
            <button onClick={submit} disabled={!ssid || connecting}
              className="flex-1 py-2 rounded-lg bg-hifi-gold text-black text-sm font-semibold disabled:opacity-40 flex items-center justify-center gap-2">
              {connecting && <Loader2 size={14} className="animate-spin" />}
              {connecting ? t('wizard.wifi.connecting', { ssid }) : t('wizard.connect')}
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
};

export default WifiConfigPanel;
