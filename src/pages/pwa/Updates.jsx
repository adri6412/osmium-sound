import React, { useState, useEffect } from 'react';
import { ChevronDown, RefreshCw, Download } from 'lucide-react';
import { useI18n } from '../../i18n';
import { applianceApi } from '../../utils/applianceApi';

const KINDS = ['app', 'system', 'os', 'lyrion'];

// OTA channel + check/apply update per kind (app/system/os/lyrion) —
// equivalent of UpdatesActivity.java, via applianceApi.js (requires pairing).
const Updates = ({ onClose }) => {
  const { t } = useI18n();
  const [channel, setChannel] = useState(null);
  const [checks, setChecks] = useState({});
  const [busyKind, setBusyKind] = useState(null);

  useEffect(() => {
    applianceApi.otaChannel().then((r) => setChannel(r.channel)).catch(() => {});
  }, []);

  const handleChannelChange = async (ch) => {
    setChannel(ch);
    try { await applianceApi.setOtaChannel(ch); } catch (_) {}
  };

  const check = async (kind) => {
    setBusyKind(kind);
    try {
      const res = await applianceApi.checkUpdate(kind);
      setChecks((c) => ({ ...c, [kind]: res }));
    } catch (e) {
      setChecks((c) => ({ ...c, [kind]: { error: e.message } }));
    } finally {
      setBusyKind(null);
    }
  };

  const apply = async (kind) => {
    setBusyKind(kind);
    try {
      await applianceApi.applyUpdate(kind);
      setChecks((c) => ({ ...c, [kind]: { ...c[kind], applying: true } }));
    } catch (e) {
      setChecks((c) => ({ ...c, [kind]: { ...c[kind], error: e.message } }));
    } finally {
      setBusyKind(null);
    }
  };

  return (
    <div className="flex flex-col h-full bg-hifi-dark overflow-y-auto">
      <div className="flex items-center h-12 px-2 shrink-0 pwa-divider">
        <button onClick={onClose} className="p-2 text-white"><ChevronDown size={22} /></button>
        <h1 className="text-[15px] font-semibold text-white ml-1">{t('applianceScreens.updates')}</h1>
      </div>

      <p className="pwa-section-header">{t('applianceScreens.channel')}</p>
      <div className="flex gap-2 px-4 pb-2">
        {['prod', 'dev'].map((ch) => (
          <button key={ch} onClick={() => handleChannelChange(ch)}
            className={`flex-1 py-2 text-sm rounded-flat border ${channel === ch ? 'border-hifi-gold text-hifi-gold' : 'border-hifi-accent text-hifi-silver/60'}`}>
            {ch === 'prod' ? t('applianceScreens.channelProd') : t('applianceScreens.channelDev')}
          </button>
        ))}
      </div>

      <p className="pwa-section-header">{t('applianceScreens.components')}</p>
      <ul>
        {KINDS.map((kind) => {
          const info = checks[kind];
          return (
            <li key={kind} className="pwa-row pwa-divider !items-start !flex-col !py-3">
              <div className="flex items-center w-full gap-3">
                <span className="text-[15px] text-white flex-1 capitalize">{t(`applianceScreens.kind.${kind}`)}</span>
                {!info?.update_available && (
                  <button onClick={() => check(kind)} disabled={busyKind === kind}
                    className="p-2 text-hifi-silver/70"><RefreshCw size={16} className={busyKind === kind ? 'animate-spin' : ''} /></button>
                )}
                {info?.update_available && !info?.applying && (
                  <button onClick={() => apply(kind)} disabled={busyKind === kind}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-hifi-gold text-black rounded-flat text-xs font-semibold">
                    <Download size={13} /> {t('applianceScreens.update')}
                  </button>
                )}
              </div>
              {info && (
                <p className="text-[12px] text-hifi-silver/50 mt-1">
                  {info.error
                    ? info.error
                    : info.applying
                      ? t('applianceScreens.applying')
                      : info.update_available
                        ? t('applianceScreens.updateAvailable', { version: info.latest })
                        : t('applianceScreens.upToDate', { version: info.current })}
                </p>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
};

export default Updates;
