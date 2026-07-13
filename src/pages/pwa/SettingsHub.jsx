import React from 'react';
import { ChevronDown, ChevronRight, Sliders, RefreshCw, Power, Speaker, Globe, Info, RotateCcw } from 'lucide-react';
import { useI18n } from '../../i18n';
import LanguageSelector from '../../components/LanguageSelector';

// Sectioned preference-style list (title+subtitle rows, bold section
// headers, 1dp dividers), replacing the panel-based PwaSettings.jsx —
// mirrors android-companion's preferences.xml grouping (Display, DSP,
// Updates, System Admin, Multiroom, Lyrion Server). DSP/Updates/System/
// Multiroom rows open their own screens (see AppPwa.jsx's router) once
// paired; unpaired they're shown disabled with a "richiede pairing" hint.
const Row = ({ Icon, title, subtitle, onClick, disabled, trailing }) => (
  <li onClick={disabled ? undefined : onClick}
    className={`pwa-row-clickable pwa-divider ${disabled ? 'opacity-40 pointer-events-none' : ''}`}>
    {Icon && <Icon size={19} className="text-hifi-silver/70 shrink-0" />}
    <div className="min-w-0 flex-1">
      <p className="text-[15px] text-white">{title}</p>
      {subtitle && <p className="text-[12px] text-hifi-silver/50 truncate">{subtitle}</p>}
    </div>
    {trailing ?? (onClick && !disabled && <ChevronRight size={16} className="text-hifi-silver/40 shrink-0" />)}
  </li>
);

const SettingsHub = ({ onClose, onOpenDsp, onOpenUpdates, onOpenMultiroom, onOpenSystemAdmin }) => {
  const { t } = useI18n();
  const lyrionUrl = localStorage.getItem('lyrionUrl') || '';
  const paired = !!localStorage.getItem('hifiPairToken');

  const handleForgetServer = () => {
    localStorage.removeItem('lyrionUrl');
    localStorage.removeItem('hifiPwaServerConfigured');
    localStorage.removeItem('hifiApplianceApiUrl');
    localStorage.removeItem('hifiPairToken');
    window.location.reload();
  };

  return (
    <div className="flex flex-col h-full bg-hifi-dark overflow-y-auto">
      <div className="flex items-center h-12 px-2 shrink-0 pwa-divider">
        <button onClick={onClose} className="p-2 text-white"><ChevronDown size={22} /></button>
        <h1 className="text-[15px] font-semibold text-white ml-1">{t('pwaSettings.title')}</h1>
      </div>

      <p className="pwa-section-header">{t('pwaSettings.language')}</p>
      <div className="px-4 pb-2"><LanguageSelector variant="list" /></div>

      <p className="pwa-section-header">{t('pwaSettings.server')}</p>
      <ul>
        <Row Icon={Globe} title={lyrionUrl || '—'} subtitle={paired ? t('pwaSettings.paired') : t('pwaSettings.notPaired')} />
        <Row Icon={RotateCcw} title={t('pwaSettings.forgetServer')} onClick={handleForgetServer} />
      </ul>

      <p className="pwa-section-header">{t('pwaSettings.appliance')}</p>
      <ul>
        <Row Icon={Sliders} title="DSP" subtitle={!paired ? t('pwaSettings.requiresPairing') : undefined} disabled={!paired} onClick={onOpenDsp} />
        <Row Icon={RefreshCw} title={t('pwaSettings.updates')} subtitle={!paired ? t('pwaSettings.requiresPairing') : undefined} disabled={!paired} onClick={onOpenUpdates} />
        <Row Icon={Speaker} title={t('pwaSettings.multiroom')} subtitle={!paired ? t('pwaSettings.requiresPairing') : undefined} disabled={!paired} onClick={onOpenMultiroom} />
        <Row Icon={Power} title={t('pwaSettings.systemAdmin')} subtitle={!paired ? t('pwaSettings.requiresPairing') : undefined} disabled={!paired} onClick={onOpenSystemAdmin} />
      </ul>

      <p className="pwa-section-header">{t('pwaSettings.about')}</p>
      <ul>
        <Row Icon={Info} title={`Osmium Sound v${__APP_VERSION__}`} />
      </ul>
    </div>
  );
};

export default SettingsHub;
