import React, { useState, useEffect } from 'react';
import { ChevronDown, Trash2 } from 'lucide-react';
import { useI18n } from '../../i18n';
import { applianceApi } from '../../utils/applianceApi';

const Toggle = ({ checked, onChange }) => (
  <button role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
    className={`w-10 h-6 rounded-full shrink-0 transition-colors relative ${checked ? 'bg-hifi-gold' : 'bg-hifi-accent'}`}>
    <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-transform ${checked ? 'translate-x-4' : 'translate-x-0.5'}`} />
  </button>
);

// DSP enable / room correction / crossfeed toggles + FIR filter status —
// equivalent of DspSettingsActivity.java. Per-band EQ editing (bands array)
// isn't exposed here, matching the Android screen (toggles + filter only,
// no per-band controls there either).
const DspSettings = ({ onClose }) => {
  const { t } = useI18n();
  const [status, setStatus] = useState(null);
  const [message, setMessage] = useState('');

  const load = () => applianceApi.dspStatus().then(setStatus).catch(() => {});
  useEffect(() => { load(); }, []);

  const patch = async (patch) => {
    const next = { ...status, ...patch };
    setStatus(next);
    try {
      await applianceApi.dspSet({
        enabled: next.enabled, crossfeed: next.crossfeed,
        room_correction: next.room_correction, bands: next.bands || [],
      });
    } catch (e) { setMessage(e.message); }
  };

  const removeFilter = async () => {
    try { await applianceApi.firDelete(); setMessage(t('applianceScreens.filterRemoved')); load(); }
    catch (e) { setMessage(e.message); }
  };

  if (!status) return (
    <div className="flex flex-col h-full bg-hifi-dark">
      <div className="flex items-center h-12 px-2 shrink-0 pwa-divider">
        <button onClick={onClose} className="p-2 text-white"><ChevronDown size={22} /></button>
        <h1 className="text-[15px] font-semibold text-white ml-1">DSP</h1>
      </div>
    </div>
  );

  return (
    <div className="flex flex-col h-full bg-hifi-dark overflow-y-auto">
      <div className="flex items-center h-12 px-2 shrink-0 pwa-divider">
        <button onClick={onClose} className="p-2 text-white"><ChevronDown size={22} /></button>
        <h1 className="text-[15px] font-semibold text-white ml-1">DSP</h1>
      </div>

      <ul>
        <li className="pwa-row pwa-divider">
          <span className="text-[15px] text-white flex-1">{t('applianceScreens.dspEnabled')}</span>
          <Toggle checked={!!status.enabled} onChange={(v) => patch({ enabled: v })} />
        </li>
        <li className="pwa-row pwa-divider">
          <span className="text-[15px] text-white flex-1">{t('applianceScreens.roomCorrection')}</span>
          <Toggle checked={!!status.room_correction} onChange={(v) => patch({ room_correction: v })} />
        </li>
        <li className="pwa-row pwa-divider">
          <span className="text-[15px] text-white flex-1">{t('applianceScreens.crossfeed')}</span>
          <Toggle checked={!!status.crossfeed} onChange={(v) => patch({ crossfeed: v })} />
        </li>
      </ul>

      <p className="pwa-section-header">{t('applianceScreens.filter')}</p>
      <div className="px-4 pb-6 space-y-2">
        <p className="text-[13px] text-hifi-silver/60">
          {status.fir_present ? t('applianceScreens.filterPresent') : t('applianceScreens.filterAbsent')}
        </p>
        {status.fir_present && (
          <button onClick={removeFilter} className="pwa-btn-outlined flex items-center justify-center gap-2">
            <Trash2 size={15} /> {t('applianceScreens.removeFilter')}
          </button>
        )}
        {message && <p className="text-xs text-hifi-silver/50">{message}</p>}
      </div>
    </div>
  );
};

export default DspSettings;
