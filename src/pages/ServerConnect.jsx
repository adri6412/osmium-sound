import React, { useState } from 'react';
import { Wifi, WifiOff, Loader2, QrCode, CheckCircle2 } from 'lucide-react';
import { lyrionApi } from '../utils/lyrionApi';
import { useI18n } from '../i18n';
import LanguageSelector from '../components/LanguageSelector';
import QrScanner from './pwa/QrScanner';

// First-run screen for the PWA build: point the app at a Lyrion/LMS server,
// primarily by scanning the appliance's existing "Phone control" QR
// (Settings.jsx → Impostazioni → Telefono, JSON payload { lms, api, token } —
// the same QR the Android companion app scans). That single scan gets the
// PWA both the LMS address AND a pairing token for src/utils/applianceApi.js
// (DSP/OTA/reboot/multiroom) in one step. Manual address entry stays as a
// fallback for music-only control without pairing.
const ServerConnect = ({ onConnected }) => {
  const { t } = useI18n();
  const [scanning, setScanning] = useState(false);
  const [showManual, setShowManual] = useState(false);
  const [url, setUrl] = useState(localStorage.getItem('lyrionUrl') || 'http://');
  const [status, setStatus] = useState('idle'); // idle | checking | ok | error
  const [serverName, setServerName] = useState('');
  const [paired, setPaired] = useState(false);

  const normalize = (raw) => {
    let v = raw.trim();
    if (!v) return '';
    if (!/^https?:\/\//i.test(v)) v = `http://${v}`;
    if (!/:\d+/.test(v.replace(/^https?:\/\//i, ''))) v = `${v.replace(/\/$/, '')}:9000`;
    return v.replace(/\/$/, '');
  };

  const finishConnect = async (target) => {
    setStatus('checking');
    try {
      lyrionApi.setBaseUrl(target);
      const info = await lyrionApi.getServerStatus();
      setServerName(info?.['lyrion version'] ? `Lyrion ${info['lyrion version']}` : t('serverConnect.connected'));
      localStorage.setItem('lyrionUrl', target);
      localStorage.setItem('hifiPwaServerConfigured', '1');
      setStatus('ok');
      onConnected?.();
    } catch (_) {
      setStatus('error');
    }
  };

  const handleManualConnect = (e) => {
    e.preventDefault();
    const target = normalize(url);
    if (target) finishConnect(target);
  };

  const handleQrDecode = async (raw) => {
    setScanning(false);
    let payload;
    try { payload = JSON.parse(raw); } catch (_) { setStatus('error'); return; }
    if (!payload?.lms) { setStatus('error'); return; }

    if (payload.api) {
      const apiUrl = /^https?:\/\//i.test(payload.api) ? payload.api : `http://${payload.api}`;
      localStorage.setItem('hifiApplianceApiUrl', apiUrl.replace(/\/$/, ''));
    }
    if (payload.token) {
      localStorage.setItem('hifiPairToken', payload.token);
      setPaired(true);
    }
    await finishConnect(normalize(payload.lms));
  };

  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-hifi-dark px-6 py-10">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center space-y-1">
          <h1 className="text-2xl font-semibold text-hifi-gold">Osmium Sound</h1>
          <p className="text-sm text-hifi-silver/70">{t('serverConnect.subtitle')}</p>
        </div>

        <button onClick={() => { setStatus('idle'); setScanning(true); }}
          className="pwa-btn-filled flex items-center justify-center gap-2">
          <QrCode size={18} /> {t('serverConnect.scanQr')}
        </button>

        {status === 'checking' && (
          <div className="flex items-center justify-center gap-2 text-sm text-hifi-silver/70">
            <Loader2 className="animate-spin" size={16} /> {t('serverConnect.checking')}
          </div>
        )}
        {status === 'ok' && (
          <div className="space-y-1">
            <div className="flex items-center justify-center gap-2 text-sm text-green-400">
              <Wifi size={16} /> {serverName}
            </div>
            {paired && (
              <div className="flex items-center justify-center gap-2 text-xs text-hifi-gold">
                <CheckCircle2 size={13} /> {t('serverConnect.paired')}
              </div>
            )}
          </div>
        )}
        {status === 'error' && (
          <div className="flex items-center justify-center gap-2 text-sm text-red-400">
            <WifiOff size={16} /> {t('serverConnect.error')}
          </div>
        )}

        {!showManual ? (
          <button onClick={() => setShowManual(true)}
            className="w-full text-center text-xs text-hifi-silver/50 underline">
            {t('serverConnect.orManual')}
          </button>
        ) : (
          <form onSubmit={handleManualConnect} className="space-y-3">
            <input
              className="pwa-input"
              type="text"
              inputMode="url"
              autoCapitalize="none"
              autoCorrect="off"
              placeholder="192.168.1.50"
              value={url}
              onChange={(e) => { setUrl(e.target.value); setStatus('idle'); }}
            />
            <button type="submit" className="pwa-btn-outlined" disabled={status === 'checking'}>
              {t('serverConnect.connect')}
            </button>
          </form>
        )}

        <div className="flex justify-center">
          <LanguageSelector variant="compact" />
        </div>
      </div>

      {scanning && (
        <QrScanner onDecode={handleQrDecode} onClose={() => setScanning(false)} />
      )}
    </div>
  );
};

export default ServerConnect;
