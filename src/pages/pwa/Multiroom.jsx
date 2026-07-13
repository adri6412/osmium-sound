import React, { useState, useEffect } from 'react';
import { ChevronDown, RadioTower } from 'lucide-react';
import { useI18n } from '../../i18n';
import { applianceApi } from '../../utils/applianceApi';

// Player name + LMS role (local / follow another device on the LAN) —
// equivalent of MultiroomActivity.java. This is "which server does my
// squeezelite point at" (device-level), distinct from the in-player sync
// group controls already available via lyrionApi.js in NowPlayingScreen.
const Multiroom = ({ onClose }) => {
  const { t } = useI18n();
  const [name, setName] = useState('');
  const [role, setRole] = useState(null);
  // Which mode is selected in the UI — distinct from `role` (the last
  // confirmed/applied mode): picking "follow" just reveals the host picker,
  // it doesn't take effect until a host is chosen and confirmed.
  const [pendingMode, setPendingMode] = useState(null);
  const [servers, setServers] = useState([]);
  const [followHost, setFollowHost] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    applianceApi.playerName().then((r) => setName(r.name || '')).catch(() => {});
    applianceApi.lmsRole().then((r) => { setRole(r.mode); setPendingMode(r.mode); setFollowHost(r.host || ''); }).catch(() => {});
  }, []);

  const saveName = async () => {
    setBusy(true);
    try { await applianceApi.setPlayerName(name); setMessage(t('applianceScreens.saved')); }
    catch (e) { setMessage(e.message); }
    finally { setBusy(false); }
  };

  const scan = async () => {
    setBusy(true);
    try { setServers((await applianceApi.discoverLms()).servers || []); }
    catch (_) {}
    finally { setBusy(false); }
  };

  const applyRole = async (mode, host) => {
    setBusy(true);
    try {
      await applianceApi.setLmsRole(mode, host);
      setRole(mode);
      setPendingMode(mode);
      setMessage(t('applianceScreens.saved'));
    } catch (e) { setMessage(e.message); }
    finally { setBusy(false); }
  };

  return (
    <div className="flex flex-col h-full bg-hifi-dark overflow-y-auto">
      <div className="flex items-center h-12 px-2 shrink-0 pwa-divider">
        <button onClick={onClose} className="p-2 text-white"><ChevronDown size={22} /></button>
        <h1 className="text-[15px] font-semibold text-white ml-1">{t('applianceScreens.multiroom')}</h1>
      </div>

      <p className="pwa-section-header">{t('applianceScreens.playerName')}</p>
      <div className="px-4 pb-2 flex gap-2">
        <input value={name} onChange={(e) => setName(e.target.value)} className="pwa-input flex-1" />
        <button onClick={saveName} disabled={busy} className="pwa-btn-outlined w-auto px-4">{t('common.confirm')}</button>
      </div>

      <p className="pwa-section-header">{t('applianceScreens.role')}</p>
      <div className="px-4 space-y-2">
        <label className="flex items-center gap-2 text-sm text-white">
          <input type="radio" checked={pendingMode === 'local'}
            onChange={() => { setPendingMode('local'); applyRole('local'); }} className="accent-hifi-gold" />
          {t('applianceScreens.roleLocal')}
        </label>
        <label className="flex items-center gap-2 text-sm text-white">
          <input type="radio" checked={pendingMode === 'follow'}
            onChange={() => setPendingMode('follow')} className="accent-hifi-gold" />
          {t('applianceScreens.roleFollow')}
        </label>

        {pendingMode === 'follow' && (
          <div className="pl-6 space-y-2">
            <button onClick={scan} disabled={busy}
              className="flex items-center gap-2 text-xs text-hifi-gold"><RadioTower size={14} /> {t('applianceScreens.scan')}</button>
            {servers.map((s) => (
              <label key={s.ip} className="flex items-center gap-2 text-sm text-white">
                <input type="radio" name="follow-host" checked={followHost === s.ip}
                  onChange={() => setFollowHost(s.ip)} className="accent-hifi-gold" />
                {s.name} ({s.ip})
              </label>
            ))}
            <input value={followHost} onChange={(e) => setFollowHost(e.target.value)}
              placeholder="192.168.1.x" className="pwa-input" />
            <button onClick={() => applyRole('follow', followHost)} disabled={busy || !followHost}
              className="pwa-btn-outlined">{t('common.confirm')}</button>
          </div>
        )}
      </div>

      {message && <p className="text-xs text-hifi-silver/50 px-4 pt-4">{message}</p>}
    </div>
  );
};

export default Multiroom;
