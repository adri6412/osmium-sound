import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { QRCodeSVG } from 'qrcode.react';
import {
  Wifi, Network, Lock, Music, Server, FolderTree,
  Check, ChevronRight, ChevronLeft, RefreshCw, X, Loader2, AlertCircle, Disc3
} from 'lucide-react';
import { systemAPI } from '../utils/api';

const SOURCES_PORT = 8080;
const LYRION_PORT = 9000;

const signalBars = (signal) => {
  const s = parseInt(signal) || 0;
  if (s >= 75) return 4;
  if (s >= 50) return 3;
  if (s >= 25) return 2;
  return 1;
};

/**
 * First-setup wizard.
 * Steps: welcome → network (wired/wifi, DHCP forced) → sources URL → lyrion URL → done
 */
const SetupWizard = ({ onComplete }) => {
  const [step, setStep] = useState('welcome');
  const [deviceIp, setDeviceIp] = useState(null);

  // network sub-state
  const [netMode, setNetMode] = useState(null); // 'wired' | 'wifi'
  const [busy, setBusy] = useState(false);
  const [statusMsg, setStatusMsg] = useState('');
  const [networks, setNetworks] = useState([]);
  const [selectedSsid, setSelectedSsid] = useState(null);
  const [wifiPassword, setWifiPassword] = useState('');
  const [netError, setNetError] = useState('');

  // Resolve the device IP whenever we need to show service URLs
  const refreshIp = async () => {
    const res = await systemAPI.getNetworkStatus();
    if (res.success && res.data?.ip) {
      setDeviceIp(res.data.ip);
      return res.data.ip;
    }
    // Fallbacks for dev / API down
    const info = await systemAPI.getSystemInfo();
    if (info.success && info.data?.local_ip && info.data.local_ip !== 'Unknown') {
      setDeviceIp(info.data.local_ip);
      return info.data.local_ip;
    }
    return null;
  };

  // ── Wired ──────────────────────────────────────────────────────
  const chooseWired = async () => {
    setNetMode('wired');
    setBusy(true);
    setNetError('');
    setStatusMsg('Connessione via cavo (DHCP) in corso…');
    const res = await systemAPI.useWiredDhcp();
    setBusy(false);
    if (res.success) {
      const ip = res.data?.ip || (await refreshIp());
      setStatusMsg(ip ? `Connesso · IP ${ip}` : 'Connesso');
      setStep('sources');
      await refreshIp();
    } else {
      setNetError(res.message || 'Connessione cavo non riuscita. Verifica che il cavo sia collegato.');
      setStatusMsg('');
    }
  };

  // ── WiFi ───────────────────────────────────────────────────────
  const chooseWifi = async () => {
    setNetMode('wifi');
    setStep('wifi-scan');
    scanWifi();
  };

  const scanWifi = async () => {
    setBusy(true);
    setNetError('');
    setNetworks([]);
    const res = await systemAPI.scanWifi();
    setBusy(false);
    if (res.success && Array.isArray(res.data?.networks)) {
      // de-dup by ssid, strongest first
      const seen = new Set();
      const list = res.data.networks
        .filter(n => n.ssid && !seen.has(n.ssid) && seen.add(n.ssid))
        .sort((a, b) => (parseInt(b.signal) || 0) - (parseInt(a.signal) || 0));
      setNetworks(list);
    } else {
      setNetError(res.message || 'Scansione WiFi non disponibile.');
    }
  };

  const connectWifi = async () => {
    if (!selectedSsid) return;
    setBusy(true);
    setNetError('');
    setStatusMsg(`Connessione a ${selectedSsid}…`);
    const res = await systemAPI.connectWifi(selectedSsid, wifiPassword);
    setBusy(false);
    if (res.success && res.data?.success !== false) {
      const ip = res.data?.ip || (await refreshIp());
      setStatusMsg(ip ? `Connesso a ${selectedSsid} · IP ${ip}` : `Connesso a ${selectedSsid}`);
      setStep('sources');
      await refreshIp();
    } else {
      setNetError(res.data?.message || res.message || 'Connessione WiFi non riuscita. Controlla la password.');
      setStatusMsg('');
    }
  };

  useEffect(() => {
    if ((step === 'sources' || step === 'lyrion') && !deviceIp) refreshIp();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  const finish = () => {
    localStorage.setItem('firstSetupComplete', 'true');
    onComplete?.();
  };

  const ipDisplay = deviceIp || 'questo dispositivo';
  const sourcesUrl = `http://${deviceIp || 'localhost'}:${SOURCES_PORT}`;
  const lyrionUrl = `http://${deviceIp || 'localhost'}:${LYRION_PORT}`;

  // ── Shared chrome ──────────────────────────────────────────────
  const Shell = ({ children, footer }) => (
    <div className="absolute inset-0 z-[60] bg-hifi-dark flex flex-col font-display overflow-hidden">
      {/* subtle top brand bar */}
      <div className="flex items-center justify-between px-6 h-12 shrink-0 border-b border-hifi-border/60">
        <div className="flex items-center space-x-2">
          <div className="w-2 h-2 rounded-full bg-hifi-gold shadow-[0_0_6px_rgba(212,175,55,0.8)]" />
          <span className="text-[11px] font-bold tracking-[0.2em] text-hifi-silver/70 uppercase">HiFi Player · Setup</span>
        </div>
        <button onClick={finish} className="text-[11px] text-hifi-silver/40 hover:text-hifi-silver/80 transition-colors">
          Salta
        </button>
      </div>
      <div className="flex-1 min-h-0 flex flex-col items-center justify-center px-8 overflow-y-auto content-scrollbar">
        {children}
      </div>
      {footer && <div className="shrink-0 px-8 py-4 border-t border-hifi-border/60 flex items-center justify-between">{footer}</div>}
    </div>
  );

  const stepIndex = ['welcome', 'network', 'wifi-scan', 'sources', 'lyrion'].indexOf(
    step === 'wifi-scan' ? 'wifi-scan' : step
  );
  const Dots = () => (
    <div className="flex items-center space-x-2">
      {['welcome', 'network', 'sources', 'lyrion'].map((s, i) => {
        const order = { welcome: 0, network: 1, 'wifi-scan': 1, sources: 2, lyrion: 3 }[step];
        return <div key={s} className={`h-1.5 rounded-full transition-all ${i === order ? 'w-6 bg-hifi-gold' : 'w-1.5 bg-hifi-border'}`} />;
      })}
    </div>
  );

  return (
    <AnimatePresence mode="wait">
      <motion.div key={step} initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} transition={{ duration: 0.2 }} className="absolute inset-0 z-[60]">

        {/* ───────── WELCOME ───────── */}
        {step === 'welcome' && (
          <Shell footer={<><Dots /><button onClick={() => setStep('network')} className="flex items-center space-x-2 bg-hifi-gold text-black font-semibold px-6 py-2.5 rounded-xl hover:brightness-110 transition">
            <span>Inizia</span><ChevronRight size={18} />
          </button></>}>
            <motion.div initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ delay: 0.1 }} className="flex flex-col items-center text-center max-w-md">
              <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-hifi-gold to-yellow-600 flex items-center justify-center shadow-[0_0_40px_rgba(212,175,55,0.3)] mb-6">
                <Disc3 size={40} className="text-black" />
              </div>
              <h1 className="text-3xl font-bold text-white mb-3">Benvenuto</h1>
              <p className="text-hifi-silver/70 leading-relaxed">
                Configuriamo insieme il tuo network streamer. Bastano pochi passaggi:
                rete, sorgenti musicali e sei pronto all'ascolto.
              </p>
            </motion.div>
          </Shell>
        )}

        {/* ───────── NETWORK CHOICE ───────── */}
        {step === 'network' && (
          <Shell footer={<><button onClick={() => setStep('welcome')} className="flex items-center space-x-1 text-hifi-silver/60 hover:text-white transition"><ChevronLeft size={18} /><span className="text-sm">Indietro</span></button><Dots /><div className="w-20" /></>}>
            <div className="w-full max-w-lg">
              <h2 className="text-2xl font-bold text-white mb-1 text-center">Connessione di rete</h2>
              <p className="text-hifi-silver/60 text-sm text-center mb-8">La rete sarà configurata automaticamente (DHCP).</p>
              <div className="grid grid-cols-2 gap-4">
                <button onClick={chooseWired} disabled={busy}
                  className="flex flex-col items-center justify-center py-10 bg-hifi-surface hover:bg-hifi-light rounded-2xl border border-hifi-border hover:border-hifi-gold/50 transition disabled:opacity-50">
                  <Network size={40} className="text-hifi-gold mb-4" />
                  <span className="text-white font-medium">Via cavo</span>
                  <span className="text-hifi-silver/50 text-xs mt-1">Ethernet</span>
                </button>
                <button onClick={chooseWifi} disabled={busy}
                  className="flex flex-col items-center justify-center py-10 bg-hifi-surface hover:bg-hifi-light rounded-2xl border border-hifi-border hover:border-hifi-gold/50 transition disabled:opacity-50">
                  <Wifi size={40} className="text-hifi-gold mb-4" />
                  <span className="text-white font-medium">Wi-Fi</span>
                  <span className="text-hifi-silver/50 text-xs mt-1">Wireless</span>
                </button>
              </div>
              {busy && <p className="text-center text-hifi-silver/60 text-sm mt-6 flex items-center justify-center"><Loader2 size={15} className="animate-spin mr-2" />{statusMsg}</p>}
              {netError && <p className="text-center text-red-400 text-sm mt-6 flex items-center justify-center"><AlertCircle size={15} className="mr-2" />{netError}</p>}
            </div>
          </Shell>
        )}

        {/* ───────── WIFI SCAN ───────── */}
        {step === 'wifi-scan' && (
          <Shell footer={<>
            <button onClick={() => setStep('network')} className="flex items-center space-x-1 text-hifi-silver/60 hover:text-white transition"><ChevronLeft size={18} /><span className="text-sm">Indietro</span></button>
            <Dots />
            <button onClick={connectWifi} disabled={!selectedSsid || busy}
              className="flex items-center space-x-2 bg-hifi-gold text-black font-semibold px-5 py-2.5 rounded-xl hover:brightness-110 transition disabled:opacity-40 disabled:cursor-not-allowed">
              {busy ? <Loader2 size={16} className="animate-spin" /> : <span>Connetti</span>}
            </button>
          </>}>
            <div className="w-full max-w-lg">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-2xl font-bold text-white">Reti Wi-Fi</h2>
                <button onClick={scanWifi} disabled={busy} className="p-2 text-hifi-silver/60 hover:text-white rounded-lg hover:bg-white/10 transition">
                  <RefreshCw size={16} className={busy ? 'animate-spin' : ''} />
                </button>
              </div>

              {netError && <p className="text-red-400 text-sm mb-3 flex items-center"><AlertCircle size={15} className="mr-2" />{netError}</p>}

              <div className="space-y-1.5 max-h-[230px] overflow-y-auto content-scrollbar pr-1">
                {networks.length === 0 && !busy && <p className="text-hifi-silver/40 text-sm text-center py-8">Nessuna rete trovata.</p>}
                {busy && networks.length === 0 && <p className="text-hifi-silver/40 text-sm text-center py-8 flex items-center justify-center"><Loader2 size={16} className="animate-spin mr-2" />Scansione…</p>}
                {networks.map((n) => {
                  const active = selectedSsid === n.ssid;
                  const bars = signalBars(n.signal);
                  return (
                    <button key={n.ssid} onClick={() => { setSelectedSsid(n.ssid); setWifiPassword(''); }}
                      className={`w-full flex items-center justify-between px-4 py-3 rounded-xl border transition ${active ? 'bg-hifi-gold/10 border-hifi-gold/60' : 'bg-hifi-surface border-hifi-border hover:bg-hifi-light'}`}>
                      <div className="flex items-center space-x-3 min-w-0">
                        <Wifi size={18} className={active ? 'text-hifi-gold' : 'text-hifi-silver/70'} />
                        <span className="text-white text-sm truncate">{n.ssid}</span>
                        {n.security && n.security !== '--' && <Lock size={12} className="text-hifi-silver/40 shrink-0" />}
                      </div>
                      <div className="flex items-end space-x-0.5 h-4">
                        {[1, 2, 3, 4].map(b => <div key={b} className={`w-1 rounded-sm ${b <= bars ? (active ? 'bg-hifi-gold' : 'bg-hifi-silver/60') : 'bg-hifi-border'}`} style={{ height: `${b * 25}%` }} />)}
                      </div>
                    </button>
                  );
                })}
              </div>

              {selectedSsid && (
                <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} className="mt-4">
                  <label className="text-hifi-silver/60 text-xs mb-1.5 block">Password per “{selectedSsid}”</label>
                  <input type="password" value={wifiPassword} onChange={(e) => setWifiPassword(e.target.value)}
                    placeholder="Inserisci la password"
                    className="w-full bg-hifi-dark border border-hifi-border focus:border-hifi-gold rounded-xl px-4 py-3 text-white outline-none transition" />
                </motion.div>
              )}
            </div>
          </Shell>
        )}

        {/* ───────── SOURCES ───────── */}
        {step === 'sources' && (
          <Shell footer={<>
            <button onClick={() => setStep('network')} className="flex items-center space-x-1 text-hifi-silver/60 hover:text-white transition"><ChevronLeft size={18} /><span className="text-sm">Indietro</span></button>
            <Dots />
            <button onClick={() => setStep('lyrion')} className="flex items-center space-x-2 bg-hifi-gold text-black font-semibold px-6 py-2.5 rounded-xl hover:brightness-110 transition">
              <span>Avanti</span><ChevronRight size={18} />
            </button>
          </>}>
            <div className="w-full max-w-2xl flex flex-col items-center text-center">
              <div className="w-14 h-14 rounded-xl bg-hifi-surface border border-hifi-border flex items-center justify-center mb-4">
                <FolderTree size={26} className="text-hifi-gold" />
              </div>
              <h2 className="text-2xl font-bold text-white mb-2">Sorgenti musicali</h2>
              <p className="text-hifi-silver/70 text-sm max-w-md mb-6">
                Apri questo indirizzo dal tuo computer o telefono per aggiungere le tue cartelle
                musicali — locali sul dispositivo o condivise in rete (SMB).
              </p>
              <div className="flex items-center gap-6 bg-hifi-surface border border-hifi-border rounded-2xl p-5">
                <div className="bg-white p-2.5 rounded-xl shrink-0">
                  <QRCodeSVG value={sourcesUrl} size={120} level="M" />
                </div>
                <div className="text-left">
                  <p className="text-hifi-silver/50 text-xs uppercase tracking-wide mb-1">Indirizzo configurazione</p>
                  <p className="text-hifi-gold text-2xl font-mono font-bold">{deviceIp || '—'}<span className="text-hifi-silver/50">:{SOURCES_PORT}</span></p>
                  <p className="text-hifi-silver/40 text-xs mt-2">Scansiona il QR o digita l'indirizzo nel browser</p>
                </div>
              </div>
            </div>
          </Shell>
        )}

        {/* ───────── LYRION ───────── */}
        {step === 'lyrion' && (
          <Shell footer={<>
            <button onClick={() => setStep('sources')} className="flex items-center space-x-1 text-hifi-silver/60 hover:text-white transition"><ChevronLeft size={18} /><span className="text-sm">Indietro</span></button>
            <Dots />
            <button onClick={finish} className="flex items-center space-x-2 bg-hifi-gold text-black font-semibold px-6 py-2.5 rounded-xl hover:brightness-110 transition">
              <Check size={18} /><span>Termina</span>
            </button>
          </>}>
            <div className="w-full max-w-2xl flex flex-col items-center text-center">
              <div className="w-14 h-14 rounded-xl bg-hifi-surface border border-hifi-border flex items-center justify-center mb-4">
                <Server size={26} className="text-hifi-gold" />
              </div>
              <h2 className="text-2xl font-bold text-white mb-2">Server musicale pronto</h2>
              <p className="text-hifi-silver/70 text-sm max-w-md mb-6">
                Lyrion Music Server è attivo. Da qui puoi accedere alle impostazioni avanzate
                della libreria dal tuo computer, quando vuoi.
              </p>
              <div className="flex items-center gap-6 bg-hifi-surface border border-hifi-border rounded-2xl p-5">
                <div className="bg-white p-2.5 rounded-xl shrink-0">
                  <QRCodeSVG value={lyrionUrl} size={120} level="M" />
                </div>
                <div className="text-left">
                  <p className="text-hifi-silver/50 text-xs uppercase tracking-wide mb-1">Lyrion Music Server</p>
                  <p className="text-hifi-gold text-2xl font-mono font-bold">{deviceIp || '—'}<span className="text-hifi-silver/50">:{LYRION_PORT}</span></p>
                  <p className="text-hifi-silver/40 text-xs mt-2">Interfaccia web completa del server</p>
                </div>
              </div>
            </div>
          </Shell>
        )}

      </motion.div>
    </AnimatePresence>
  );
};

export default SetupWizard;
