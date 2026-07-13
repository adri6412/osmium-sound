import React, { useState, useEffect } from 'react';
import { ChevronDown, Power, RotateCcw, Terminal } from 'lucide-react';
import { useI18n } from '../../i18n';
import { applianceApi } from '../../utils/applianceApi';

const Toggle = ({ checked, onChange, disabled }) => (
  <button
    role="switch" aria-checked={checked} disabled={disabled}
    onClick={() => onChange(!checked)}
    className={`w-10 h-6 rounded-full shrink-0 transition-colors relative disabled:opacity-40 ${checked ? 'bg-hifi-gold' : 'bg-hifi-accent'}`}>
    <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-transform ${checked ? 'translate-x-4' : 'translate-x-0.5'}`} />
  </button>
);

// Reboot/shutdown + SSH toggle + basic system info — equivalent of
// SystemAdminActivity.java, via applianceApi.js (requires pairing).
const SystemAdmin = ({ onClose }) => {
  const { t } = useI18n();
  const [info, setInfo] = useState(null);
  const [ssh, setSsh] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    applianceApi.systemInfo().then(setInfo).catch(() => {});
    applianceApi.sshStatus().then(setSsh).catch(() => {});
  }, []);

  const handleSshToggle = async (enabled) => {
    setSsh((s) => ({ ...s, enabled }));
    try { await applianceApi.setSsh(enabled); } catch (_) { applianceApi.sshStatus().then(setSsh).catch(() => {}); }
  };

  const handleReboot = async () => {
    if (!window.confirm(t('applianceScreens.confirmReboot'))) return;
    setBusy(true);
    try { await applianceApi.reboot(); setMessage(t('applianceScreens.rebooting')); }
    catch (e) { setMessage(e.message); }
    finally { setBusy(false); }
  };

  const handleShutdown = async () => {
    if (!window.confirm(t('applianceScreens.confirmShutdown'))) return;
    setBusy(true);
    try { await applianceApi.shutdown(); setMessage(t('applianceScreens.shuttingDown')); }
    catch (e) { setMessage(e.message); }
    finally { setBusy(false); }
  };

  return (
    <div className="flex flex-col h-full bg-hifi-dark overflow-y-auto">
      <div className="flex items-center h-12 px-2 shrink-0 pwa-divider">
        <button onClick={onClose} className="p-2 text-white"><ChevronDown size={22} /></button>
        <h1 className="text-[15px] font-semibold text-white ml-1">{t('applianceScreens.systemAdmin')}</h1>
      </div>

      {info && (
        <>
          <p className="pwa-section-header">{t('applianceScreens.systemInfo')}</p>
          <ul>
            {info.hostname && <li className="pwa-row pwa-divider"><span className="text-[13px] text-hifi-silver/60">{t('applianceScreens.hostname')}</span><span className="ml-auto text-[13px] text-white">{info.hostname}</span></li>}
            {info.uptime && <li className="pwa-row pwa-divider"><span className="text-[13px] text-hifi-silver/60">{t('applianceScreens.uptime')}</span><span className="ml-auto text-[13px] text-white">{info.uptime}</span></li>}
          </ul>
        </>
      )}

      <p className="pwa-section-header">SSH</p>
      <ul>
        <li className="pwa-row pwa-divider">
          <Terminal size={18} className="text-hifi-silver/70" />
          <span className="text-[15px] text-white flex-1">SSH</span>
          {ssh && <Toggle checked={!!ssh.enabled} onChange={handleSshToggle} disabled={!ssh.available} />}
        </li>
      </ul>

      <p className="pwa-section-header">{t('applianceScreens.power')}</p>
      <div className="px-4 space-y-2 pb-6">
        <button onClick={handleReboot} disabled={busy} className="pwa-btn-outlined flex items-center justify-center gap-2">
          <RotateCcw size={16} /> {t('applianceScreens.reboot')}
        </button>
        <button onClick={handleShutdown} disabled={busy}
          className="w-full py-3 rounded-flat border border-red-500/50 text-red-400 font-semibold text-sm flex items-center justify-center gap-2">
          <Power size={16} /> {t('applianceScreens.shutdown')}
        </button>
        {message && <p className="text-xs text-hifi-silver/60 text-center pt-2">{message}</p>}
      </div>
    </div>
  );
};

export default SystemAdmin;
