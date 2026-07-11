import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { QRCodeSVG } from 'qrcode.react';
import {
  Wifi, Network, Lock, Music, Server, FolderTree,
  Check, ChevronRight, ChevronLeft, RefreshCw, X, Loader2, AlertCircle, Disc3, Speaker, Download,
  Hand, MousePointer2
} from 'lucide-react';
import { systemAPI } from '../utils/api';
import { useI18n } from '../i18n';
import LanguageSelector from '../components/LanguageSelector';

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
  const { t } = useI18n();
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

  // audio (DAC) sub-state
  const [audioDevices, setAudioDevices] = useState([]);
  const [selectedAudio, setSelectedAudio] = useState('default');
  const [audioBusy, setAudioBusy] = useState(false);
  const [audioError, setAudioError] = useState('');

  // lyrion install fallback sub-state. The installer purges Lyrion and the
  // first-boot reinstall can fail if the network isn't up yet, so the wizard
  // (where networking is already configured) checks and, if missing, installs it.
  const [lyrionState, setLyrionState] = useState('checking'); // 'checking' | 'missing' | 'installed'
  const [lyrionInstalling, setLyrionInstalling] = useState(false);
  const [lyrionProgress, setLyrionProgress] = useState(0);
  const [lyrionMsg, setLyrionMsg] = useState('');
  const [lyrionError, setLyrionError] = useState('');
  const lyrionPollRef = useRef(null);

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

  // ── Input method (touchscreen vs mouse) ────────────────────────
  // Sets the on-screen pointer flag up-front so the rest of the wizard (and the
  // app) already matches how the user drives the device. Best-effort: persists
  // the in-app class + localStorage even if the API call fails.
  const chooseInput = async (useMouse) => {
    document.documentElement.classList.toggle('hifi-hide-cursor', !useMouse);
    localStorage.setItem('hifiShowPointer', useMouse ? '1' : '0');
    try { await systemAPI.setPointer(useMouse); } catch (_) {}
    setStep('network');
  };

  // ── Wired ──────────────────────────────────────────────────────
  const chooseWired = async () => {
    setNetMode('wired');
    setBusy(true);
    setNetError('');
    setStatusMsg(t('wizard.network.connectingWired'));
    const res = await systemAPI.useWiredDhcp();
    setBusy(false);
    if (res.success) {
      const ip = res.data?.ip || (await refreshIp());
      setStatusMsg(ip ? t('wizard.network.connectedIp', { ip }) : t('wizard.network.connected'));
      setStep('audio');
      await refreshIp();
    } else {
      setNetError(res.message || t('wizard.network.wiredFailed'));
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
      setNetError(res.message || t('wizard.wifi.scanUnavailable'));
    }
  };

  const connectWifi = async () => {
    if (!selectedSsid) return;
    setBusy(true);
    setNetError('');
    setStatusMsg(t('wizard.wifi.connecting', { ssid: selectedSsid }));
    const res = await systemAPI.connectWifi(selectedSsid, wifiPassword);
    setBusy(false);
    if (res.success && res.data?.success !== false) {
      const ip = res.data?.ip || (await refreshIp());
      setStatusMsg(ip
        ? t('wizard.wifi.connectedToIp', { ssid: selectedSsid, ip })
        : t('wizard.wifi.connectedTo', { ssid: selectedSsid }));
      setStep('audio');
      await refreshIp();
    } else {
      setNetError(res.data?.message || res.message || t('wizard.wifi.connectFailed'));
      setStatusMsg('');
    }
  };

  // ── Audio output (DAC) ─────────────────────────────────────────
  const loadAudioDevices = async () => {
    setAudioBusy(true);
    setAudioError('');
    const res = await systemAPI.getAudioDevices();
    setAudioBusy(false);
    if (res.success && Array.isArray(res.data?.devices)) {
      setAudioDevices(res.data.devices);
      // prefer first real DAC (hw:...) over "default", else default
      const firstHw = res.data.devices.find(d => d.id !== 'default');
      setSelectedAudio(firstHw ? firstHw.id : 'default');
    } else {
      setAudioError(res.message || t('wizard.audio.unavailable'));
      setAudioDevices([{ id: 'default', name: t('wizard.audio.defaultDevice') }]);
    }
  };

  const confirmAudio = async () => {
    setAudioBusy(true);
    setAudioError('');
    const res = await systemAPI.setAudioDevice(selectedAudio);
    setAudioBusy(false);
    // proceed regardless: a wrong DAC can be changed later in the sources/settings
    setStep('sources');
  };

  // ── Lyrion presence check + install fallback ───────────────────
  const checkLyrion = async () => {
    setLyrionError('');
    setLyrionState('checking');
    const res = await systemAPI.checkLyrionUpdate();
    // `current` comes from local dpkg, so it's reliable even if the downloads
    // server is unreachable (in which case `data.error` is set but current still
    // tells us whether Lyrion is installed). 'unknown' ⇒ not installed.
    const cur = res?.data?.current;
    setLyrionState(cur && cur !== 'unknown' ? 'installed' : 'missing');
  };

  const installLyrion = async () => {
    setLyrionInstalling(true);
    setLyrionError('');
    setLyrionProgress(5);
    setLyrionMsg(t('wizard.lyrion.installing'));
    const res = await systemAPI.applyLyrionUpdate();
    if (!res.success || res.data?.started === false) {
      setLyrionInstalling(false);
      setLyrionError(res.data?.message || res.message || t('wizard.lyrion.installFailed'));
      return;
    }
    // The install runs as a detached systemd unit; poll its status file.
    lyrionPollRef.current = setInterval(async () => {
      const s = await systemAPI.getLyrionUpdateStatus();
      const d = s.data || {};
      if (typeof d.progress === 'number') setLyrionProgress(d.progress);
      if (d.message) setLyrionMsg(d.message);
      if (d.state === 'done' || d.state === 'error') {
        clearInterval(lyrionPollRef.current);
        lyrionPollRef.current = null;
        setLyrionInstalling(false);
        if (d.state === 'done') {
          setLyrionProgress(100);
          setLyrionState('installed');
        } else {
          setLyrionError(d.message || t('wizard.lyrion.installFailed'));
        }
      }
    }, 2000);
  };

  useEffect(() => {
    if (step === 'audio' && audioDevices.length === 0) loadAudioDevices();
    if ((step === 'sources' || step === 'lyrion') && !deviceIp) refreshIp();
    if (step === 'lyrion' && !lyrionInstalling) checkLyrion();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  // Stop polling if the wizard unmounts mid-install (the systemd unit finishes
  // on its own regardless).
  useEffect(() => () => { if (lyrionPollRef.current) clearInterval(lyrionPollRef.current); }, []);

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
          <span className="text-[11px] font-bold tracking-[0.2em] text-hifi-silver/70 uppercase">{t('wizard.brand')}</span>
        </div>
        <div className="flex items-center space-x-3">
          <LanguageSelector variant="compact" />
          <button onClick={finish} className="text-[11px] text-hifi-silver/40 hover:text-hifi-silver/80 transition-colors">
            {t('wizard.skip')}
          </button>
        </div>
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
      {['welcome', 'network', 'audio', 'sources', 'lyrion'].map((s, i) => {
        const order = { welcome: 0, input: 0, network: 1, 'wifi-scan': 1, audio: 2, sources: 3, lyrion: 4 }[step];
        return <div key={s} className={`h-1.5 rounded-full transition-all ${i === order ? 'w-6 bg-hifi-gold' : 'w-1.5 bg-hifi-border'}`} />;
      })}
    </div>
  );

  return (
    <AnimatePresence mode="wait">
      <motion.div key={step} initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} transition={{ duration: 0.2 }} className="absolute inset-0 z-[60]">

        {/* ───────── WELCOME ───────── */}
        {step === 'welcome' && (
          <Shell footer={<><Dots /><button onClick={() => setStep('input')} className="flex items-center space-x-2 bg-hifi-gold text-black font-semibold px-6 py-2.5 rounded-xl hover:brightness-110 transition">
            <span>{t('wizard.start')}</span><ChevronRight size={18} />
          </button></>}>
            <motion.div initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ delay: 0.1 }} className="flex flex-col items-center text-center max-w-md">
              <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-hifi-gold to-yellow-600 flex items-center justify-center shadow-[0_0_40px_rgba(212,175,55,0.3)] mb-6">
                <Disc3 size={40} className="text-black" />
              </div>
              <h1 className="text-3xl font-bold text-white mb-3">{t('wizard.welcome.title')}</h1>
              <p className="text-hifi-silver/70 leading-relaxed">
                {t('wizard.welcome.subtitle')}
              </p>
            </motion.div>
          </Shell>
        )}

        {/* ───────── INPUT METHOD (touchscreen vs mouse) ───────── */}
        {step === 'input' && (
          <Shell footer={<><button onClick={() => setStep('welcome')} className="flex items-center space-x-1 text-hifi-silver/60 hover:text-white transition"><ChevronLeft size={18} /><span className="text-sm">{t('common.back')}</span></button><Dots /><div className="w-20" /></>}>
            <div className="w-full max-w-lg">
              <h2 className="text-2xl font-bold text-white mb-1 text-center">{t('wizard.input.title')}</h2>
              <p className="text-hifi-silver/60 text-sm text-center mb-8">{t('wizard.input.subtitle')}</p>
              <div className="grid grid-cols-2 gap-4">
                <button onClick={() => chooseInput(false)}
                  className="flex flex-col items-center justify-center py-10 bg-hifi-surface hover:bg-hifi-light rounded-2xl border border-hifi-border hover:border-hifi-gold/50 transition">
                  <Hand size={40} className="text-hifi-gold mb-4" />
                  <span className="text-white font-medium">{t('wizard.input.touch')}</span>
                  <span className="text-hifi-silver/50 text-xs mt-1">{t('wizard.input.touchSub')}</span>
                </button>
                <button onClick={() => chooseInput(true)}
                  className="flex flex-col items-center justify-center py-10 bg-hifi-surface hover:bg-hifi-light rounded-2xl border border-hifi-border hover:border-hifi-gold/50 transition">
                  <MousePointer2 size={40} className="text-hifi-gold mb-4" />
                  <span className="text-white font-medium">{t('wizard.input.mouse')}</span>
                  <span className="text-hifi-silver/50 text-xs mt-1">{t('wizard.input.mouseSub')}</span>
                </button>
              </div>
            </div>
          </Shell>
        )}

        {/* ───────── NETWORK CHOICE ───────── */}
        {step === 'network' && (
          <Shell footer={<><button onClick={() => setStep('input')} className="flex items-center space-x-1 text-hifi-silver/60 hover:text-white transition"><ChevronLeft size={18} /><span className="text-sm">{t('common.back')}</span></button><Dots /><div className="w-20" /></>}>
            <div className="w-full max-w-lg">
              <h2 className="text-2xl font-bold text-white mb-1 text-center">{t('wizard.network.title')}</h2>
              <p className="text-hifi-silver/60 text-sm text-center mb-8">{t('wizard.network.subtitle')}</p>
              <div className="grid grid-cols-2 gap-4">
                <button onClick={chooseWired} disabled={busy}
                  className="flex flex-col items-center justify-center py-10 bg-hifi-surface hover:bg-hifi-light rounded-2xl border border-hifi-border hover:border-hifi-gold/50 transition disabled:opacity-50">
                  <Network size={40} className="text-hifi-gold mb-4" />
                  <span className="text-white font-medium">{t('wizard.network.wired')}</span>
                  <span className="text-hifi-silver/50 text-xs mt-1">{t('wizard.network.wiredSub')}</span>
                </button>
                <button onClick={chooseWifi} disabled={busy}
                  className="flex flex-col items-center justify-center py-10 bg-hifi-surface hover:bg-hifi-light rounded-2xl border border-hifi-border hover:border-hifi-gold/50 transition disabled:opacity-50">
                  <Wifi size={40} className="text-hifi-gold mb-4" />
                  <span className="text-white font-medium">{t('wizard.network.wifi')}</span>
                  <span className="text-hifi-silver/50 text-xs mt-1">{t('wizard.network.wifiSub')}</span>
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
            <button onClick={() => setStep('network')} className="flex items-center space-x-1 text-hifi-silver/60 hover:text-white transition"><ChevronLeft size={18} /><span className="text-sm">{t('common.back')}</span></button>
            <Dots />
            <button onClick={connectWifi} disabled={!selectedSsid || busy}
              className="flex items-center space-x-2 bg-hifi-gold text-black font-semibold px-5 py-2.5 rounded-xl hover:brightness-110 transition disabled:opacity-40 disabled:cursor-not-allowed">
              {busy ? <Loader2 size={16} className="animate-spin" /> : <span>{t('wizard.connect')}</span>}
            </button>
          </>}>
            <div className="w-full max-w-lg">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-2xl font-bold text-white">{t('wizard.wifi.title')}</h2>
                <button onClick={scanWifi} disabled={busy} className="p-2 text-hifi-silver/60 hover:text-white rounded-lg hover:bg-white/10 transition">
                  <RefreshCw size={16} className={busy ? 'animate-spin' : ''} />
                </button>
              </div>

              {netError && <p className="text-red-400 text-sm mb-3 flex items-center"><AlertCircle size={15} className="mr-2" />{netError}</p>}

              <div className="space-y-1.5 max-h-[230px] overflow-y-auto content-scrollbar pr-1">
                {networks.length === 0 && !busy && <p className="text-hifi-silver/40 text-sm text-center py-8">{t('wizard.wifi.noNetworks')}</p>}
                {busy && networks.length === 0 && <p className="text-hifi-silver/40 text-sm text-center py-8 flex items-center justify-center"><Loader2 size={16} className="animate-spin mr-2" />{t('wizard.wifi.scanning')}</p>}
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
                  <label className="text-hifi-silver/60 text-xs mb-1.5 block">{t('wizard.wifi.passwordLabel', { ssid: selectedSsid })}</label>
                  <input type="password" value={wifiPassword} onChange={(e) => setWifiPassword(e.target.value)}
                    placeholder={t('wizard.wifi.passwordPlaceholder')}
                    className="w-full bg-hifi-dark border border-hifi-border focus:border-hifi-gold rounded-xl px-4 py-3 text-white outline-none transition" />
                </motion.div>
              )}
            </div>
          </Shell>
        )}

        {/* ───────── AUDIO / DAC ───────── */}
        {step === 'audio' && (
          <Shell footer={<>
            <button onClick={() => setStep('network')} className="flex items-center space-x-1 text-hifi-silver/60 hover:text-white transition"><ChevronLeft size={18} /><span className="text-sm">{t('common.back')}</span></button>
            <Dots />
            <button onClick={confirmAudio} disabled={audioBusy}
              className="flex items-center space-x-2 bg-hifi-gold text-black font-semibold px-6 py-2.5 rounded-xl hover:brightness-110 transition disabled:opacity-50">
              {audioBusy ? <Loader2 size={16} className="animate-spin" /> : <><span>{t('common.next')}</span><ChevronRight size={18} /></>}
            </button>
          </>}>
            <div className="w-full max-w-lg">
              <div className="flex flex-col items-center text-center mb-6">
                <div className="w-14 h-14 rounded-xl bg-hifi-surface border border-hifi-border flex items-center justify-center mb-4">
                  <Speaker size={26} className="text-hifi-gold" />
                </div>
                <h2 className="text-2xl font-bold text-white mb-1">{t('wizard.audio.title')}</h2>
                <p className="text-hifi-silver/60 text-sm max-w-sm">{t('wizard.audio.subtitle')}</p>
              </div>

              <div className="flex items-center justify-end mb-2">
                <button onClick={loadAudioDevices} disabled={audioBusy} className="p-2 text-hifi-silver/60 hover:text-white rounded-lg hover:bg-white/10 transition">
                  <RefreshCw size={15} className={audioBusy ? 'animate-spin' : ''} />
                </button>
              </div>

              {audioError && <p className="text-amber-400/80 text-xs mb-3 flex items-center"><AlertCircle size={14} className="mr-2" />{audioError}</p>}

              <div className="space-y-1.5 max-h-[260px] overflow-y-auto content-scrollbar pr-1">
                {audioBusy && audioDevices.length === 0 && (
                  <p className="text-hifi-silver/40 text-sm text-center py-8 flex items-center justify-center"><Loader2 size={16} className="animate-spin mr-2" />{t('wizard.audio.searching')}</p>
                )}
                {audioDevices.map((d) => {
                  const active = selectedAudio === d.id;
                  return (
                    <button key={d.id} onClick={() => setSelectedAudio(d.id)}
                      className={`w-full flex items-center justify-between px-4 py-3 rounded-xl border transition ${active ? 'bg-hifi-gold/10 border-hifi-gold/60' : 'bg-hifi-surface border-hifi-border hover:bg-hifi-light'}`}>
                      <div className="flex items-center space-x-3 min-w-0">
                        <Speaker size={18} className={active ? 'text-hifi-gold' : 'text-hifi-silver/70'} />
                        <div className="text-left min-w-0">
                          <p className="text-white text-sm truncate">{d.name}</p>
                          <p className="text-hifi-silver/40 text-xs font-mono">{d.id}</p>
                        </div>
                      </div>
                      {active && <Check size={16} className="text-hifi-gold shrink-0" />}
                    </button>
                  );
                })}
              </div>
            </div>
          </Shell>
        )}

        {/* ───────── SOURCES ───────── */}
        {step === 'sources' && (
          <Shell footer={<>
            <button onClick={() => setStep('audio')} className="flex items-center space-x-1 text-hifi-silver/60 hover:text-white transition"><ChevronLeft size={18} /><span className="text-sm">{t('common.back')}</span></button>
            <Dots />
            <button onClick={() => setStep('lyrion')} className="flex items-center space-x-2 bg-hifi-gold text-black font-semibold px-6 py-2.5 rounded-xl hover:brightness-110 transition">
              <span>{t('common.next')}</span><ChevronRight size={18} />
            </button>
          </>}>
            <div className="w-full max-w-2xl flex flex-col items-center text-center">
              <div className="w-14 h-14 rounded-xl bg-hifi-surface border border-hifi-border flex items-center justify-center mb-4">
                <FolderTree size={26} className="text-hifi-gold" />
              </div>
              <h2 className="text-2xl font-bold text-white mb-2">{t('wizard.sources.title')}</h2>
              <p className="text-hifi-silver/70 text-sm max-w-md mb-6">
                {t('wizard.sources.subtitle')}
              </p>
              <div className="flex items-center gap-6 bg-hifi-surface border border-hifi-border rounded-2xl p-5">
                <div className="bg-white p-2.5 rounded-xl shrink-0">
                  <QRCodeSVG value={sourcesUrl} size={120} level="M" />
                </div>
                <div className="text-left">
                  <p className="text-hifi-silver/50 text-xs uppercase tracking-wide mb-1">{t('wizard.sources.addressLabel')}</p>
                  <p className="text-hifi-gold text-2xl font-mono font-bold">{deviceIp || '—'}<span className="text-hifi-silver/50">:{SOURCES_PORT}</span></p>
                  <p className="text-hifi-silver/40 text-xs mt-2">{t('wizard.sources.scanHint')}</p>
                </div>
              </div>
            </div>
          </Shell>
        )}

        {/* ───────── LYRION ───────── */}
        {step === 'lyrion' && (
          <Shell footer={<>
            <button onClick={() => setStep('sources')} className="flex items-center space-x-1 text-hifi-silver/60 hover:text-white transition"><ChevronLeft size={18} /><span className="text-sm">{t('common.back')}</span></button>
            <Dots />
            <button onClick={finish} className="flex items-center space-x-2 bg-hifi-gold text-black font-semibold px-6 py-2.5 rounded-xl hover:brightness-110 transition">
              <Check size={18} /><span>{t('wizard.finish')}</span>
            </button>
          </>}>
            <div className="w-full max-w-2xl flex flex-col items-center text-center">
              <div className="w-14 h-14 rounded-xl bg-hifi-surface border border-hifi-border flex items-center justify-center mb-4">
                <Server size={26} className="text-hifi-gold" />
              </div>

              {/* Checking whether Lyrion is installed */}
              {lyrionState === 'checking' && (
                <>
                  <h2 className="text-2xl font-bold text-white mb-2">{t('wizard.lyrion.title')}</h2>
                  <p className="text-hifi-silver/60 text-sm flex items-center justify-center mt-4">
                    <Loader2 size={16} className="animate-spin mr-2" />{t('wizard.lyrion.checking')}
                  </p>
                </>
              )}

              {/* Fallback: Lyrion missing → offer to install it here */}
              {lyrionState === 'missing' && (
                <>
                  <h2 className="text-2xl font-bold text-white mb-2">{t('wizard.lyrion.notInstalledTitle')}</h2>
                  <p className="text-hifi-silver/70 text-sm max-w-md mb-6">{t('wizard.lyrion.notInstalledHint')}</p>
                  {!lyrionInstalling ? (
                    <>
                      <button onClick={installLyrion}
                        className="flex items-center space-x-2 bg-hifi-gold text-black font-semibold px-6 py-3 rounded-xl hover:brightness-110 transition">
                        <Download size={18} /><span>{t('wizard.lyrion.install')}</span>
                      </button>
                      {lyrionError && <p className="text-red-400 text-sm mt-4 flex items-center justify-center"><AlertCircle size={15} className="mr-2" />{lyrionError}</p>}
                    </>
                  ) : (
                    <div className="w-full max-w-sm">
                      <div className="h-2 bg-hifi-dark rounded-full overflow-hidden border border-hifi-border">
                        <div className="h-full bg-hifi-gold transition-all duration-500" style={{ width: `${lyrionProgress}%` }} />
                      </div>
                      <p className="text-hifi-silver/60 text-sm mt-3 flex items-center justify-center">
                        <Loader2 size={15} className="animate-spin mr-2" />{lyrionMsg || t('wizard.lyrion.installing')}
                      </p>
                    </div>
                  )}
                </>
              )}

              {/* Lyrion installed → show the web-UI address (original behaviour) */}
              {lyrionState === 'installed' && (
                <>
                  <h2 className="text-2xl font-bold text-white mb-2">{t('wizard.lyrion.title')}</h2>
                  <p className="text-hifi-silver/70 text-sm max-w-md mb-6">{t('wizard.lyrion.subtitle')}</p>
                  <div className="flex items-center gap-6 bg-hifi-surface border border-hifi-border rounded-2xl p-5">
                    <div className="bg-white p-2.5 rounded-xl shrink-0">
                      <QRCodeSVG value={lyrionUrl} size={120} level="M" />
                    </div>
                    <div className="text-left">
                      <p className="text-hifi-silver/50 text-xs uppercase tracking-wide mb-1">{t('wizard.lyrion.label')}</p>
                      <p className="text-hifi-gold text-2xl font-mono font-bold">{deviceIp || '—'}<span className="text-hifi-silver/50">:{LYRION_PORT}</span></p>
                      <p className="text-hifi-silver/40 text-xs mt-2">{t('wizard.lyrion.webHint')}</p>
                    </div>
                  </div>
                </>
              )}
            </div>
          </Shell>
        )}

      </motion.div>
    </AnimatePresence>
  );
};

export default SetupWizard;
