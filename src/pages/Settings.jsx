import React, { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { 
  Wifi, 
  Info,
  Power,
  RotateCw,
  Download,
  Loader2,
  Network,
  Volume2
} from 'lucide-react';
import { systemAPI, checkApiServer } from '../utils/api';
import { useKeyboardInput } from '../hooks/useKeyboardInput';
import { useKeyboard } from '../contexts/KeyboardContext';

/**
 * Settings screen component - Simplified version for debugging
 * System configuration and information
 */
const Settings = () => {
  const [systemInfo, setSystemInfo] = useState({
    hostname: 'Caricamento...',
    platform: 'linux',
    arch: 'x64',
    version: '1.0.0',
    local_ip: 'Caricamento...',
    network_interfaces: []
  });
  const [networkInfo, setNetworkInfo] = useState([]);
  const [selectedInterface, setSelectedInterface] = useState('');
  const [lyrionUrl, setLyrionUrl] = useState(localStorage.getItem('lyrionUrl') || 'http://localhost:9000');
  const [isUpdating, setIsUpdating] = useState(false);
  const [updateMessage, setUpdateMessage] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [apiConnected, setApiConnected] = useState(false);

  // Audio output (DAC) selection
  const [audioDevices, setAudioDevices] = useState([]);
  const [selectedAudio, setSelectedAudio] = useState('default');
  const [audioBusy, setAudioBusy] = useState(false);
  const [audioMessage, setAudioMessage] = useState('');

  // OTA UI update state
  const [appUpdate, setAppUpdate] = useState(null); // { current, latest, update_available, ... }
  const [isCheckingUpdate, setIsCheckingUpdate] = useState(false);
  const [isApplyingUpdate, setIsApplyingUpdate] = useState(false);
  const [otaStatus, setOtaStatus] = useState(null); // { state, progress, message }
  const otaPollRef = useRef(null);

  // System-components OTA update state
  const [systemUpdate, setSystemUpdate] = useState(null);
  const [isCheckingSystem, setIsCheckingSystem] = useState(false);
  const [isApplyingSystem, setIsApplyingSystem] = useState(false);
  const [systemStatus, setSystemStatus] = useState(null);
  const systemPollRef = useRef(null);

  // Lyrion update state
  const [lyrionUpdate, setLyrionUpdate] = useState(null);
  const [isCheckingLyrion, setIsCheckingLyrion] = useState(false);
  const [isApplyingLyrion, setIsApplyingLyrion] = useState(false);
  const [lyrionStatus, setLyrionStatus] = useState(null);
  const lyrionPollRef = useRef(null);

  // OS (signed) update state
  const [osUpdate, setOsUpdate] = useState(null);
  const [isCheckingOs, setIsCheckingOs] = useState(false);
  const [isApplyingOs, setIsApplyingOs] = useState(false);
  const [osStatus, setOsStatus] = useState(null);
  const osPollRef = useRef(null);

  // Combined UI+System OTA (single-button) state
  const [isApplyingAll, setIsApplyingAll] = useState(false);
  const [allStatus, setAllStatus] = useState(null); // { phase, message } combined progress

  // "Advanced" updates (Lyrion) collapsible
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Check-for-updates-on-startup preference (persisted)
  const [autoCheck, setAutoCheck] = useState(
    localStorage.getItem('hifiAutoCheckUpdates') !== 'false'
  );

  // Refs for input fields with automatic keyboard
  const lyrionUrlRef = useKeyboardInput(lyrionUrl, setLyrionUrl);
  
  // Test keyboard context
  const { showKeyboard } = useKeyboard();

  // Load system and network data on component mount
  useEffect(() => {
    loadSystemData();
    loadAudioDevices();
  }, []);

  // ── Audio output (DAC) handlers ─────────────────────────────────
  const loadAudioDevices = async () => {
    setAudioBusy(true);
    setAudioMessage('');
    const res = await systemAPI.getAudioDevices();
    setAudioBusy(false);
    if (res.success && Array.isArray(res.data?.devices)) {
      setAudioDevices(res.data.devices);
      // preselect whatever squeezelite is currently configured to use
      if (res.data.current) setSelectedAudio(res.data.current);
    } else {
      setAudioMessage(res.message || 'Elenco dispositivi audio non disponibile.');
      setAudioDevices([{ id: 'default', name: 'Predefinito di sistema' }]);
    }
  };

  const applyAudioDevice = async () => {
    setAudioBusy(true);
    setAudioMessage('');
    const res = await systemAPI.setAudioDevice(selectedAudio);
    setAudioBusy(false);
    setAudioMessage(res.data?.message || res.message || (res.success ? 'Uscita audio aggiornata.' : 'Impostazione fallita.'));
  };

  // Auto-check for updates on mount (only if the user kept it enabled);
  // clean up any poll on unmount.
  useEffect(() => {
    if (autoCheck) {
      checkAppUpdate();
      checkSystemUpdate();
      checkLyrionUpdate();
      checkOsUpdate();
    }
    return () => {
      if (otaPollRef.current) clearInterval(otaPollRef.current);
      if (systemPollRef.current) clearInterval(systemPollRef.current);
      if (lyrionPollRef.current) clearInterval(lyrionPollRef.current);
      if (osPollRef.current) clearInterval(osPollRef.current);
    };
  }, []);

  // Publish "update available" so the Sidebar can show a badge. We consider the
  // core channels behind the single button (UI + System + OS); Lyrion and the
  // apt upgrade live on their own buttons.
  useEffect(() => {
    const available = !!(appUpdate?.update_available || systemUpdate?.update_available || osUpdate?.update_available);
    localStorage.setItem('hifiUpdateAvailable', available ? '1' : '0');
    window.dispatchEvent(new CustomEvent('hifi-update-available', { detail: available }));
  }, [appUpdate, systemUpdate, osUpdate]);

  // ── OTA UI update handlers ──────────────────────────────────────
  const checkAppUpdate = async () => {
    setIsCheckingUpdate(true);
    try {
      const result = await systemAPI.checkAppUpdate();
      if (result.success && !result.data.error) {
        setAppUpdate(result.data);
      } else {
        setAppUpdate({ error: result.data?.error || result.message });
      }
    } catch (error) {
      setAppUpdate({ error: 'Controllo aggiornamenti fallito' });
    } finally {
      setIsCheckingUpdate(false);
    }
  };

  // Resolves to true on success, false on error. Used by the combined flow.
  // Applying the UI restarts the Electron front-end, so this is run last.
  const applyAppUpdate = async () => {
    if (!apiConnected) {
      setUpdateMessage('Errore: Server API non disponibile');
      return false;
    }
    setIsApplyingUpdate(true);
    setOtaStatus({ state: 'starting', message: 'Avvio aggiornamento…' });
    try {
      const result = await systemAPI.applyAppUpdate();
      if (!result.success || !result.data.started) {
        setOtaStatus({ state: 'error', message: result.data?.message || result.message || 'Avvio fallito' });
        setIsApplyingUpdate(false);
        return false;
      }
      // Poll progress until done/error (the UI will be restarted on success).
      return await new Promise((resolve) => {
        otaPollRef.current = setInterval(async () => {
          const s = await systemAPI.getAppUpdateStatus();
          if (s.success) {
            setOtaStatus(s.data);
            if (s.data.state === 'done' || s.data.state === 'error') {
              clearInterval(otaPollRef.current);
              otaPollRef.current = null;
              setIsApplyingUpdate(false);
              resolve(s.data.state === 'done');
            }
          }
        }, 2000);
      });
    } catch (error) {
      setOtaStatus({ state: 'error', message: 'Errore durante l\'aggiornamento' });
      setIsApplyingUpdate(false);
      return false;
    }
  };

  // ── System-components OTA handlers ──────────────────────────────
  const checkSystemUpdate = async () => {
    setIsCheckingSystem(true);
    try {
      const result = await systemAPI.checkSystemUpdate();
      if (result.success && !result.data.error) {
        setSystemUpdate(result.data);
      } else {
        setSystemUpdate({ error: result.data?.error || result.message });
      }
    } catch (error) {
      setSystemUpdate({ error: 'Controllo aggiornamenti fallito' });
    } finally {
      setIsCheckingSystem(false);
    }
  };

  // Resolves to true on success, false on error.
  const applySystemUpdate = async () => {
    if (!apiConnected) {
      setUpdateMessage('Errore: Server API non disponibile');
      return false;
    }
    setIsApplyingSystem(true);
    setSystemStatus({ state: 'starting', message: 'Avvio aggiornamento…' });
    try {
      const result = await systemAPI.applySystemUpdate();
      if (!result.success || !result.data.started) {
        setSystemStatus({ state: 'error', message: result.data?.message || result.message || 'Avvio fallito' });
        setIsApplyingSystem(false);
        return false;
      }
      // Poll progress until done/error. The API itself restarts at the end, so
      // a transient network error during polling is expected near completion.
      return await new Promise((resolve) => {
        systemPollRef.current = setInterval(async () => {
          const s = await systemAPI.getSystemUpdateStatus();
          if (s.success) {
            setSystemStatus(s.data);
            if (s.data.state === 'done' || s.data.state === 'error') {
              clearInterval(systemPollRef.current);
              systemPollRef.current = null;
              setIsApplyingSystem(false);
              if (s.data.state === 'done') checkSystemUpdate();
              resolve(s.data.state === 'done');
            }
          }
        }, 2000);
      });
    } catch (error) {
      setSystemStatus({ state: 'error', message: 'Errore durante l\'aggiornamento' });
      setIsApplyingSystem(false);
      return false;
    }
  };

  // ── Combined UI + System + OS OTA (single button) ───────────────
  // One button applies every core update, in the order that survives:
  //   1. System components (API/daemons/scripts) — doesn't tear down the page.
  //   2. OS — verifies the signature and runs apply.sh. apply.sh is a clean
  //      no-op when the system already matches (so this step usually just falls
  //      through); only a real OS change reboots, which is rare and ends here.
  //   3. UI — restarts the Electron front-end, so it goes last (terminal).
  // (apt system upgrade and Lyrion stay on their own buttons.)
  const applyAllUpdates = async () => {
    if (!apiConnected) {
      setUpdateMessage('Errore: Server API non disponibile');
      return;
    }
    const hasSystem = !!systemUpdate?.update_available;
    const hasUI = !!appUpdate?.update_available;
    const hasOS = !!osUpdate?.update_available;
    if (!hasSystem && !hasUI && !hasOS) return;

    setIsApplyingAll(true);
    try {
      if (hasSystem) {
        setAllStatus({ phase: 'system', message: 'Aggiornamento componenti di sistema…' });
        if (!await applySystemUpdate()) {
          setAllStatus({ phase: 'error', message: 'Aggiornamento sistema fallito' });
          setIsApplyingAll(false);
          return;
        }
      }
      if (hasOS) {
        setAllStatus({ phase: 'os', message: 'Verifica e aggiornamento sistema operativo…' });
        // Reboots only if apply.sh made a real change; otherwise resolves and we
        // continue to the UI step.
        if (!await applyOsUpdate()) {
          setAllStatus({ phase: 'error', message: 'Aggiornamento sistema operativo fallito' });
          setIsApplyingAll(false);
          return;
        }
      }
      if (hasUI) {
        setAllStatus({ phase: 'ui', message: 'Aggiornamento interfaccia (riavvio al termine)…' });
        await applyAppUpdate(); // restarts the kiosk on success
      }
      setAllStatus({ phase: 'done', message: 'Aggiornamento completato' });
    } catch (error) {
      setAllStatus({ phase: 'error', message: 'Errore durante l\'aggiornamento' });
    } finally {
      setIsApplyingAll(false);
    }
  };

  const refreshAllChecks = () => {
    checkAppUpdate();
    checkSystemUpdate();
    checkOsUpdate();
  };

  const toggleAutoCheck = () => {
    setAutoCheck((prev) => {
      const next = !prev;
      localStorage.setItem('hifiAutoCheckUpdates', next ? 'true' : 'false');
      return next;
    });
  };

  const coreUpdateAvailable = !!(appUpdate?.update_available || systemUpdate?.update_available || osUpdate?.update_available);

  // ── Lyrion update handlers ──────────────────────────────────────
  const checkLyrionUpdate = async () => {
    setIsCheckingLyrion(true);
    try {
      const result = await systemAPI.checkLyrionUpdate();
      if (result.success && !result.data.error) {
        setLyrionUpdate(result.data);
      } else {
        setLyrionUpdate({ error: result.data?.error || result.message });
      }
    } catch (error) {
      setLyrionUpdate({ error: 'Controllo aggiornamenti Lyrion fallito' });
    } finally {
      setIsCheckingLyrion(false);
    }
  };

  const applyLyrionUpdate = async () => {
    if (!apiConnected) {
      setUpdateMessage('Errore: Server API non disponibile');
      return;
    }
    setIsApplyingLyrion(true);
    setLyrionStatus({ state: 'starting', message: 'Avvio aggiornamento Lyrion…' });
    try {
      const result = await systemAPI.applyLyrionUpdate();
      if (!result.success || !result.data.started) {
        setLyrionStatus({ state: 'error', message: result.data?.message || result.message || 'Avvio fallito' });
        setIsApplyingLyrion(false);
        return;
      }
      lyrionPollRef.current = setInterval(async () => {
        const s = await systemAPI.getLyrionUpdateStatus();
        if (s.success) {
          setLyrionStatus(s.data);
          if (s.data.state === 'done' || s.data.state === 'error') {
            clearInterval(lyrionPollRef.current);
            lyrionPollRef.current = null;
            setIsApplyingLyrion(false);
            if (s.data.state === 'done') checkLyrionUpdate();
          }
        }
      }, 2000);
    } catch (error) {
      setLyrionStatus({ state: 'error', message: 'Errore durante l\'aggiornamento di Lyrion' });
      setIsApplyingLyrion(false);
    }
  };

  // ── OS (signed) update handlers ─────────────────────────────────
  const checkOsUpdate = async () => {
    setIsCheckingOs(true);
    try {
      const result = await systemAPI.checkOsUpdate();
      if (result.success && !result.data.error) {
        setOsUpdate(result.data);
      } else {
        setOsUpdate({ error: result.data?.error || result.message });
      }
    } catch (error) {
      setOsUpdate({ error: 'Controllo aggiornamenti OS fallito' });
    } finally {
      setIsCheckingOs(false);
    }
  };

  // Resolves to true on success, false on error. Reboots the device on success
  // (so polling usually just stops as the device goes down). The reboot is
  // confirmed up-front by the combined flow, so there's no prompt here.
  const applyOsUpdate = async () => {
    if (!apiConnected) {
      setUpdateMessage('Errore: Server API non disponibile');
      return false;
    }
    setIsApplyingOs(true);
    setOsStatus({ state: 'starting', message: 'Avvio aggiornamento OS…' });
    try {
      const result = await systemAPI.applyOsUpdate();
      if (!result.success || !result.data.started) {
        setOsStatus({ state: 'error', message: result.data?.message || result.message || 'Avvio fallito' });
        setIsApplyingOs(false);
        return false;
      }
      return await new Promise((resolve) => {
        osPollRef.current = setInterval(async () => {
          const s = await systemAPI.getOsUpdateStatus();
          if (s.success) {
            setOsStatus(s.data);
            if (s.data.state === 'done' || s.data.state === 'error') {
              clearInterval(osPollRef.current);
              osPollRef.current = null;
              setIsApplyingOs(false);
              if (s.data.state === 'done') checkOsUpdate();
              resolve(s.data.state === 'done');
            }
          }
        }, 2000);
      });
    } catch (error) {
      setOsStatus({ state: 'error', message: 'Errore durante l\'aggiornamento del sistema operativo' });
      setIsApplyingOs(false);
      return false;
    }
  };

  // Keyboard input handlers that work with the virtual keyboard
  const handleLyrionUrlChange = (e) => {
    setLyrionUrl(e.target.value);
    localStorage.setItem('lyrionUrl', e.target.value);
  };

  const loadSystemData = async () => {
    setIsLoading(true);
    try {
      // Check API connection first
      const apiCheck = await checkApiServer();
      setApiConnected(apiCheck);
      
      if (apiCheck) {
        // Load system info
        const systemResult = await systemAPI.getSystemInfo();
        if (systemResult.success) {
          setSystemInfo(systemResult.data);
          setNetworkInfo(systemResult.data.network_interfaces || []);
          
          // Set default selected interface
          if (systemResult.data.network_interfaces && systemResult.data.network_interfaces.length > 0) {
            setSelectedInterface(systemResult.data.network_interfaces[0].name);
          }
        }

        // Load network info separately
        const networkResult = await systemAPI.getNetworkInfo();
        if (networkResult.success) {
          setNetworkInfo(networkResult.data);
        }
      } else {
        setUpdateMessage('Errore: Server API non disponibile. Verificare che api_server.py sia in esecuzione.');
      }
    } catch (error) {
      console.error('Error loading system data:', error);
      setUpdateMessage('Errore nel caricamento dei dati di sistema');
    } finally {
      setIsLoading(false);
    }
  };

  // System actions
  const handleSystemUpdate = async () => {
    if (!apiConnected) {
      setUpdateMessage('Errore: Server API non disponibile');
      return;
    }

    setIsUpdating(true);
    setUpdateMessage('Aggiornamento del sistema in corso...');
    
    try {
      const result = await systemAPI.update();
      if (result.success) {
        setUpdateMessage(result.data.message || 'Sistema aggiornato con successo!');
      } else {
        setUpdateMessage(result.message || 'Errore durante l\'aggiornamento');
      }
    } catch (error) {
      setUpdateMessage('Errore durante l\'aggiornamento del sistema');
    } finally {
      setIsUpdating(false);
    }
  };

  const handleReboot = async () => {
    if (!apiConnected) {
      setUpdateMessage('Errore: Server API non disponibile');
      return;
    }

    if (confirm('Sei sicuro di voler riavviare il sistema?')) {
      setUpdateMessage('Riavvio del sistema...');
      try {
        const result = await systemAPI.reboot();
        if (result.success) {
          setUpdateMessage(result.data.message || 'Sistema in riavvio...');
        } else {
          setUpdateMessage(result.message || 'Errore durante il riavvio');
        }
      } catch (error) {
        setUpdateMessage('Errore durante il riavvio del sistema');
      }
    }
  };

  const handleShutdown = async () => {
    if (!apiConnected) {
      setUpdateMessage('Errore: Server API non disponibile');
      return;
    }

    if (confirm('Sei sicuro di voler spegnere il sistema?')) {
      setUpdateMessage('Spegnimento del sistema...');
      try {
        const result = await systemAPI.shutdown();
        if (result.success) {
          setUpdateMessage(result.data.message || 'Sistema in spegnimento...');
        } else {
          setUpdateMessage(result.message || 'Errore durante lo spegnimento');
        }
      } catch (error) {
        setUpdateMessage('Errore durante lo spegnimento del sistema');
      }
    }
  };

  // Get current interface info
  const currentInterface = networkInfo.find(net => net.name === selectedInterface);
  const wiredInterfaces = networkInfo.filter(net => net.type === 'wired');
  const wirelessInterfaces = networkInfo.filter(net => net.type === 'wireless');

  const settingsSections = [
    {
      title: 'Configurazione Lyrion',
      icon: Network,
      content: 'custom-lyrion'
    },
    {
      title: 'Uscita Audio (DAC)',
      icon: Volume2,
      content: 'custom-audio'
    },
    {
      title: 'Configurazione Rete',
      icon: Wifi,
      content: 'custom-network'
    },
    {
      title: 'Informazioni Sistema',
      icon: Info,
      items: [
        { label: 'Hostname', value: systemInfo.hostname, type: 'info' },
        { label: 'IP Dispositivo', value: currentInterface?.address || systemInfo.local_ip || 'Non disponibile', type: 'info' },
        { label: 'Platform', value: `${systemInfo.platform} (${systemInfo.arch})`, type: 'info' },
        { label: 'Stato API', value: apiConnected ? 'Connesso' : 'Disconnesso', type: 'info' },
      ]
    },
    {
      title: 'Aggiornamenti',
      icon: Download,
      content: 'custom-updates'
    },
    {
      title: 'Controlli Sistema',
      icon: Power,
      content: 'custom-system-controls'
    }
  ];

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="h-full w-full overflow-y-auto p-8 bg-hifi-dark"
    >
      <div className="max-w-4xl mx-auto">
        <motion.div
          initial={{ y: -20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ delay: 0.1 }}
          className="mb-8"
        >
          <h1 className="text-4xl font-bold text-white mb-2">Settings</h1>
          <p className="text-hifi-silver text-lg">Configure your HiFi Media Player</p>
          {isLoading && (
            <div className="flex items-center space-x-2 text-hifi-gold mt-2">
              <Loader2 size={16} className="animate-spin" />
              <span className="text-sm">Caricamento dati di sistema...</span>
            </div>
          )}
          {!apiConnected && !isLoading && (
            <div className="flex items-center space-x-2 text-red-400 mt-2">
              <span className="text-sm">⚠️ Server API non disponibile</span>
            </div>
          )}
        </motion.div>

        <div className="space-y-6">
          {settingsSections.map((section, sectionIndex) => {
            const SectionIcon = section.icon;
            
            return (
              <motion.div
                key={section.title}
                initial={{ y: 20, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ delay: 0.1 * (sectionIndex + 1) }}
                className="hifi-panel p-6"
              >
                {/* Section header */}
                <div className="flex items-center space-x-3 mb-4 pb-4 border-b border-hifi-accent">
                  <div className="p-2 rounded-lg bg-hifi-gold/20">
                    <SectionIcon size={24} className="text-hifi-gold" />
                  </div>
                  <h2 className="text-xl font-semibold text-white">{section.title}</h2>
                </div>

                {/* Custom Lyrion Section */}
                {section.content === 'custom-lyrion' && (
                  <div className="space-y-4">
                    <div className="space-y-3">
                      <label className="text-white font-medium">Lyrion Server URL</label>
                      <p className="text-sm text-hifi-silver mb-2">Inserisci l'indirizzo del tuo Lyrion Media Server (es. http://192.168.1.100:9000)</p>
                      <div
                        onClick={() => showKeyboard(lyrionUrlRef, lyrionUrl)}
                        className="cursor-pointer"
                      >
                        <input
                          ref={lyrionUrlRef}
                          type="text"
                          value={lyrionUrl}
                          onChange={handleLyrionUrlChange}
                          className="w-full bg-hifi-dark border border-hifi-accent rounded-lg px-4 py-3 text-white focus:outline-none focus:border-hifi-gold cursor-pointer"
                          placeholder="http://localhost:9000"
                        />
                      </div>
                    </div>
                  </div>
                )}

                {/* Custom Audio Output (DAC) Section */}
                {section.content === 'custom-audio' && (
                  <div className="space-y-4">
                    <p className="text-sm text-hifi-silver">
                      Scegli il dispositivo di riproduzione (DAC). La selezione viene salvata
                      e mantenuta ai riavvii. La riproduzione DSD è bit-perfect (DoP).
                    </p>

                    <div className="space-y-2">
                      {audioDevices.map((dev) => (
                        <motion.button
                          key={dev.id}
                          onClick={() => setSelectedAudio(dev.id)}
                          className={`w-full p-3 rounded-lg text-left transition-colors ${
                            selectedAudio === dev.id
                              ? 'bg-hifi-gold text-black'
                              : 'bg-hifi-light text-white hover:bg-hifi-accent'
                          }`}
                          whileTap={{ scale: 0.95 }}
                        >
                          <div className="font-medium text-sm">{dev.name}</div>
                          <div className="text-xs opacity-75 font-mono">{dev.id}</div>
                        </motion.button>
                      ))}
                    </div>

                    <div className="flex gap-3">
                      <motion.button
                        onClick={loadAudioDevices}
                        disabled={audioBusy}
                        className="flex-1 bg-hifi-accent hover:bg-hifi-light disabled:bg-hifi-dark text-white py-3 rounded-lg font-medium flex items-center justify-center space-x-2 transition-colors"
                        whileTap={{ scale: audioBusy ? 1 : 0.95 }}
                      >
                        {audioBusy ? <Loader2 size={18} className="animate-spin" /> : <RotateCw size={18} />}
                        <span>Aggiorna elenco</span>
                      </motion.button>
                      <motion.button
                        onClick={applyAudioDevice}
                        disabled={audioBusy}
                        className="flex-1 bg-hifi-gold hover:bg-yellow-600 disabled:bg-hifi-accent text-black py-3 rounded-lg font-semibold flex items-center justify-center space-x-2 transition-colors"
                        whileTap={{ scale: audioBusy ? 1 : 0.95 }}
                      >
                        <Volume2 size={18} />
                        <span>Imposta uscita</span>
                      </motion.button>
                    </div>

                    {audioMessage && (
                      <div className={`rounded-lg p-3 text-center text-sm ${
                        audioMessage.toLowerCase().includes('fallit') || audioMessage.toLowerCase().includes('non disponibile')
                          ? 'bg-red-900/20 text-red-300 border border-red-500/30'
                          : 'bg-hifi-dark text-hifi-silver'
                      }`}>
                        {audioMessage}
                      </div>
                    )}
                  </div>
                )}

                {/* Custom Network Section */}
                {section.content === 'custom-network' && (
                  <div className="space-y-4">
                    {/* Interface Selection */}
                    <div className="space-y-3">
                      <label className="text-white font-medium">Interfaccia di Rete</label>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        {/* Wired Interfaces */}
                        {wiredInterfaces.length > 0 && (
                          <div className="space-y-2">
                            <div className="flex items-center space-x-2 text-hifi-silver text-sm">
                              <Network size={16} />
                              <span>Cavo Ethernet</span>
                            </div>
                            {wiredInterfaces.map((iface) => (
                              <motion.button
                                key={iface.name}
                                onClick={() => setSelectedInterface(iface.name)}
                                className={`w-full p-3 rounded-lg text-left transition-colors ${
                                  selectedInterface === iface.name
                                    ? 'bg-hifi-gold text-black'
                                    : 'bg-hifi-light text-white hover:bg-hifi-accent'
                                }`}
                                whileTap={{ scale: 0.95 }}
                              >
                                <div className="font-mono text-sm">{iface.name}</div>
                                <div className="text-xs opacity-75">{iface.address}</div>
                              </motion.button>
                            ))}
                          </div>
                        )}

                        {/* Wireless Interfaces */}
                        {wirelessInterfaces.length > 0 && (
                          <div className="space-y-2">
                            <div className="flex items-center space-x-2 text-hifi-silver text-sm">
                              <Wifi size={16} />
                              <span>Wi-Fi</span>
                            </div>
                            {wirelessInterfaces.map((iface) => (
                              <motion.button
                                key={iface.name}
                                onClick={() => setSelectedInterface(iface.name)}
                                className={`w-full p-3 rounded-lg text-left transition-colors ${
                                  selectedInterface === iface.name
                                    ? 'bg-hifi-gold text-black'
                                    : 'bg-hifi-light text-white hover:bg-hifi-accent'
                                }`}
                                whileTap={{ scale: 0.95 }}
                              >
                                <div className="font-mono text-sm">{iface.name}</div>
                                <div className="text-xs opacity-75">{iface.address}</div>
                              </motion.button>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Current Interface Info */}
                    {currentInterface && (
                      <div className="bg-hifi-dark rounded-lg p-4">
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-hifi-silver text-sm">IP Corrente ({currentInterface.name})</span>
                          <span className="text-hifi-gold font-mono">
                            {currentInterface.address || 'Non connesso'}
                          </span>
                        </div>
                        <div className="text-xs text-hifi-silver">
                          Tipo: {currentInterface.type} | Subnet: {currentInterface.netmask || 'N/A'}
                        </div>
                      </div>
                    )}

                    {/* Network info notice */}
                    <div className="flex items-start space-x-2 text-xs text-hifi-silver bg-hifi-dark rounded-lg p-3">
                      <Info size={14} className="text-hifi-gold mt-0.5 shrink-0" />
                      <span>La rete è configurata automaticamente tramite DHCP. Collega il cavo Ethernet o configura il Wi-Fi per ottenere un indirizzo IP.</span>
                    </div>

                    {/* Reload Button */}
                    <motion.button
                      onClick={loadSystemData}
                      disabled={isLoading}
                      className="w-full bg-hifi-accent hover:bg-hifi-light disabled:bg-hifi-dark text-white py-2 rounded-lg font-medium flex items-center justify-center space-x-2 transition-colors"
                      whileTap={{ scale: isLoading ? 1 : 0.95 }}
                    >
                      {isLoading ? (
                        <>
                          <Loader2 size={16} className="animate-spin" />
                          <span>Caricamento...</span>
                        </>
                      ) : (
                        <>
                          <RotateCw size={16} />
                          <span>Ricarica Dati</span>
                        </>
                      )}
                    </motion.button>

                    {/* Update Message */}
                    {updateMessage && (
                      <div className={`rounded-lg p-3 text-center text-sm ${
                        updateMessage.includes('Errore') || updateMessage.includes('non disponibile')
                          ? 'bg-red-900/20 text-red-300 border border-red-500/30'
                          : 'bg-hifi-dark text-hifi-silver'
                      }`}>
                        {updateMessage}
                      </div>
                    )}
                  </div>
                )}

                {/* Unified UI + System OTA Update Section */}
                {section.content === 'custom-updates' && (
                  <div className="space-y-4">
                    {/* Version rows: UI + System + OS */}
                    <div className="bg-hifi-dark rounded-lg p-4 space-y-3">
                      <div className="space-y-1">
                        <div className="flex items-center justify-between">
                          <span className="text-hifi-silver text-sm">Interfaccia (UI)</span>
                          <span className="text-white font-mono text-sm">
                            {appUpdate?.current || systemInfo.version || '...'}
                            {appUpdate?.update_available && (
                              <span className="text-hifi-gold"> → {appUpdate.latest}</span>
                            )}
                          </span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-hifi-silver text-sm">Sistema (API/daemon/script)</span>
                          <span className="text-white font-mono text-sm">
                            {systemUpdate?.current || '...'}
                            {systemUpdate?.update_available && (
                              <span className="text-hifi-gold"> → {systemUpdate.latest}</span>
                            )}
                          </span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-hifi-silver text-sm">
                            Sistema operativo
                            <span className="ml-1 text-[10px] uppercase tracking-wide text-hifi-gold/80">firmato</span>
                          </span>
                          <span className="text-white font-mono text-sm">
                            {osUpdate?.error ? 'N/D' : (osUpdate?.current || '...')}
                            {osUpdate?.update_available && (
                              <span className="text-hifi-gold"> → {osUpdate.latest}</span>
                            )}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Status summary */}
                    {coreUpdateAvailable ? (
                      <div className="rounded-lg p-3 text-center text-sm bg-hifi-gold/20 text-hifi-gold border border-hifi-gold/40">
                        Aggiornamento disponibile
                      </div>
                    ) : (appUpdate && systemUpdate && osUpdate && !appUpdate.error && !systemUpdate.error && !osUpdate.error) ? (
                      <div className="rounded-lg p-3 text-center text-sm bg-hifi-dark text-hifi-silver">
                        Tutto aggiornato
                      </div>
                    ) : null}
                    {(appUpdate?.error || systemUpdate?.error || osUpdate?.error) && (
                      <div className="rounded-lg p-3 text-center text-sm bg-red-900/20 text-red-300 border border-red-500/30">
                        {appUpdate?.error || systemUpdate?.error || osUpdate?.error}
                      </div>
                    )}

                    {/* Check for updates */}
                    <motion.button
                      onClick={refreshAllChecks}
                      disabled={isCheckingUpdate || isCheckingSystem || isCheckingOs || isApplyingAll}
                      className="w-full bg-hifi-accent hover:bg-hifi-light disabled:bg-hifi-dark text-white py-3 rounded-lg font-medium flex items-center justify-center space-x-2 transition-colors"
                      whileTap={{ scale: (isCheckingUpdate || isCheckingSystem || isCheckingOs) ? 1 : 0.95 }}
                    >
                      {(isCheckingUpdate || isCheckingSystem || isCheckingOs) ? (
                        <>
                          <Loader2 size={18} className="animate-spin" />
                          <span>Controllo in corso...</span>
                        </>
                      ) : (
                        <>
                          <RotateCw size={18} />
                          <span>Controlla aggiornamenti</span>
                        </>
                      )}
                    </motion.button>

                    {/* Single apply button: System → UI → OS */}
                    {coreUpdateAvailable && (
                      <motion.button
                        onClick={applyAllUpdates}
                        disabled={isApplyingAll}
                        className="w-full bg-hifi-gold hover:bg-yellow-600 disabled:bg-hifi-accent text-black py-4 rounded-lg font-semibold flex items-center justify-center space-x-2 transition-colors"
                        whileTap={{ scale: isApplyingAll ? 1 : 0.95 }}
                      >
                        {isApplyingAll ? (
                          <>
                            <Loader2 size={20} className="animate-spin" />
                            <span>Aggiornamento...</span>
                          </>
                        ) : (
                          <>
                            <Download size={20} />
                            <span>Aggiorna ora</span>
                          </>
                        )}
                      </motion.button>
                    )}

                    {isApplyingAll && (
                      <p className="text-xs text-hifi-silver text-center">
                        Si aggiornano in ordine: sistema, interfaccia e — se presente — il sistema operativo (con riavvio finale).
                      </p>
                    )}

                    {/* Combined progress */}
                    {allStatus && (
                      <div className={`rounded-lg p-3 text-center text-sm ${
                        allStatus.phase === 'error'
                          ? 'bg-red-900/20 text-red-300 border border-red-500/30'
                          : 'bg-hifi-dark text-hifi-silver'
                      }`}>
                        {allStatus.message}
                        {osStatus && allStatus.phase === 'os' && typeof osStatus.progress === 'number' && osStatus.state !== 'error' && (
                          <span className="ml-1">({osStatus.progress}%)</span>
                        )}
                      </div>
                    )}

                    {/* Auto-check toggle */}
                    <button
                      onClick={toggleAutoCheck}
                      className="w-full flex items-center justify-between bg-hifi-dark hover:bg-hifi-light/40 rounded-lg px-4 py-3 transition-colors"
                    >
                      <span className="text-sm text-white">Controlla aggiornamenti all'avvio</span>
                      <span className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${autoCheck ? 'bg-hifi-gold' : 'bg-hifi-accent'}`}>
                        <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${autoCheck ? 'translate-x-6' : 'translate-x-1'}`} />
                      </span>
                    </button>

                    {/* Advanced (Lyrion) collapsible — the OS channel is now part
                        of the single "Aggiorna ora" button above. */}
                    <button
                      onClick={() => setShowAdvanced((v) => !v)}
                      className="w-full text-left text-sm text-hifi-silver hover:text-white pt-2 transition-colors"
                    >
                      {showAdvanced ? '▾' : '▸'} Avanzate (Lyrion)
                    </button>

                    {showAdvanced && (
                      <div className="space-y-3 border-t border-hifi-accent pt-4">
                        <div className="bg-hifi-dark rounded-lg p-4 space-y-2">
                          <div className="flex items-center justify-between">
                            <span className="text-hifi-silver text-sm">Lyrion installato</span>
                            <span className="text-white font-mono text-sm">{lyrionUpdate?.current || '...'}</span>
                          </div>
                          <div className="flex items-center justify-between">
                            <span className="text-hifi-silver text-sm">Ultima versione</span>
                            <span className="text-white font-mono text-sm">
                              {lyrionUpdate?.error ? 'N/D' : (lyrionUpdate?.latest || '...')}
                            </span>
                          </div>
                        </div>

                        {lyrionUpdate?.update_available && (
                          <div className="rounded-lg p-3 text-center text-sm bg-hifi-gold/20 text-hifi-gold border border-hifi-gold/40">
                            Aggiornamento Lyrion disponibile: {lyrionUpdate.latest}
                          </div>
                        )}
                        {lyrionUpdate && !lyrionUpdate.error && !lyrionUpdate.update_available && (
                          <div className="rounded-lg p-3 text-center text-sm bg-hifi-dark text-hifi-silver">
                            Lyrion è aggiornato
                          </div>
                        )}
                        {lyrionUpdate?.error && (
                          <div className="rounded-lg p-3 text-center text-sm bg-red-900/20 text-red-300 border border-red-500/30">
                            {lyrionUpdate.error}
                          </div>
                        )}

                        <motion.button
                          onClick={checkLyrionUpdate}
                          disabled={isCheckingLyrion || isApplyingLyrion}
                          className="w-full bg-hifi-accent hover:bg-hifi-light disabled:bg-hifi-dark text-white py-3 rounded-lg font-medium flex items-center justify-center space-x-2 transition-colors"
                          whileTap={{ scale: isCheckingLyrion ? 1 : 0.95 }}
                        >
                          {isCheckingLyrion ? (
                            <>
                              <Loader2 size={18} className="animate-spin" />
                              <span>Controllo in corso...</span>
                            </>
                          ) : (
                            <>
                              <RotateCw size={18} />
                              <span>Controlla aggiornamenti Lyrion</span>
                            </>
                          )}
                        </motion.button>

                        {lyrionUpdate?.update_available && (
                          <motion.button
                            onClick={applyLyrionUpdate}
                            disabled={isApplyingLyrion}
                            className="w-full bg-hifi-gold hover:bg-yellow-600 disabled:bg-hifi-accent text-black py-4 rounded-lg font-semibold flex items-center justify-center space-x-2 transition-colors"
                            whileTap={{ scale: isApplyingLyrion ? 1 : 0.95 }}
                          >
                            {isApplyingLyrion ? (
                              <>
                                <Loader2 size={20} className="animate-spin" />
                                <span>Aggiornamento...</span>
                              </>
                            ) : (
                              <>
                                <Download size={20} />
                                <span>Aggiorna Lyrion ({lyrionUpdate.latest})</span>
                              </>
                            )}
                          </motion.button>
                        )}

                        {isApplyingLyrion && (
                          <p className="text-xs text-hifi-silver text-center">
                            Il server musicale verrà riavviato al termine.
                          </p>
                        )}

                        {lyrionStatus && (
                          <div className={`rounded-lg p-3 text-center text-sm ${
                            lyrionStatus.state === 'error'
                              ? 'bg-red-900/20 text-red-300 border border-red-500/30'
                              : 'bg-hifi-dark text-hifi-silver'
                          }`}>
                            {lyrionStatus.message || lyrionStatus.state}
                            {typeof lyrionStatus.progress === 'number' && lyrionStatus.state !== 'error' && (
                              <span className="ml-1">({lyrionStatus.progress}%)</span>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* Legacy standalone Lyrion section (now under Advanced) */}
                {section.content === 'custom-lyrion-update' && (
                  <div className="space-y-4">
                    {/* Version info */}
                    <div className="bg-hifi-dark rounded-lg p-4 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-hifi-silver text-sm">Versione installata</span>
                        <span className="text-white font-mono text-sm">
                          {lyrionUpdate?.current || '...'}
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-hifi-silver text-sm">Ultima versione</span>
                        <span className="text-white font-mono text-sm">
                          {lyrionUpdate?.error ? 'N/D' : (lyrionUpdate?.latest || '...')}
                        </span>
                      </div>
                    </div>

                    {lyrionUpdate?.update_available && (
                      <div className="rounded-lg p-3 text-center text-sm bg-hifi-gold/20 text-hifi-gold border border-hifi-gold/40">
                        Aggiornamento disponibile: {lyrionUpdate.latest}
                      </div>
                    )}
                    {lyrionUpdate && !lyrionUpdate.error && !lyrionUpdate.update_available && (
                      <div className="rounded-lg p-3 text-center text-sm bg-hifi-dark text-hifi-silver">
                        Lyrion è aggiornato
                      </div>
                    )}
                    {lyrionUpdate?.error && (
                      <div className="rounded-lg p-3 text-center text-sm bg-red-900/20 text-red-300 border border-red-500/30">
                        {lyrionUpdate.error}
                      </div>
                    )}

                    {/* Check for updates */}
                    <motion.button
                      onClick={checkLyrionUpdate}
                      disabled={isCheckingLyrion || isApplyingLyrion}
                      className="w-full bg-hifi-accent hover:bg-hifi-light disabled:bg-hifi-dark text-white py-3 rounded-lg font-medium flex items-center justify-center space-x-2 transition-colors"
                      whileTap={{ scale: isCheckingLyrion ? 1 : 0.95 }}
                    >
                      {isCheckingLyrion ? (
                        <>
                          <Loader2 size={18} className="animate-spin" />
                          <span>Controllo in corso...</span>
                        </>
                      ) : (
                        <>
                          <RotateCw size={18} />
                          <span>Controlla aggiornamenti</span>
                        </>
                      )}
                    </motion.button>

                    {/* Apply update */}
                    {lyrionUpdate?.update_available && (
                      <motion.button
                        onClick={applyLyrionUpdate}
                        disabled={isApplyingLyrion}
                        className="w-full bg-hifi-gold hover:bg-yellow-600 disabled:bg-hifi-accent text-black py-4 rounded-lg font-semibold flex items-center justify-center space-x-2 transition-colors"
                        whileTap={{ scale: isApplyingLyrion ? 1 : 0.95 }}
                      >
                        {isApplyingLyrion ? (
                          <>
                            <Loader2 size={20} className="animate-spin" />
                            <span>Aggiornamento...</span>
                          </>
                        ) : (
                          <>
                            <Download size={20} />
                            <span>Aggiorna Lyrion ({lyrionUpdate.latest})</span>
                          </>
                        )}
                      </motion.button>
                    )}

                    {isApplyingLyrion && (
                      <p className="text-xs text-hifi-silver text-center">
                        Il server musicale verrà riavviato al termine.
                      </p>
                    )}

                    {/* Lyrion update progress */}
                    {lyrionStatus && (
                      <div className={`rounded-lg p-3 text-center text-sm ${
                        lyrionStatus.state === 'error'
                          ? 'bg-red-900/20 text-red-300 border border-red-500/30'
                          : 'bg-hifi-dark text-hifi-silver'
                      }`}>
                        {lyrionStatus.message || lyrionStatus.state}
                        {typeof lyrionStatus.progress === 'number' && lyrionStatus.state !== 'error' && (
                          <span className="ml-1">({lyrionStatus.progress}%)</span>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* Custom System Controls Section */}
                {section.content === 'custom-system-controls' && (
                  <div className="space-y-4">
                    {/* System Update */}
                    <motion.button
                      onClick={handleSystemUpdate}
                      disabled={isUpdating}
                      className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-hifi-accent text-white py-4 rounded-lg font-semibold flex items-center justify-center space-x-2 transition-colors"
                      whileTap={{ scale: isUpdating ? 1 : 0.95 }}
                    >
                      {isUpdating ? (
                        <>
                          <Loader2 size={20} className="animate-spin" />
                          <span>Aggiornamento...</span>
                        </>
                      ) : (
                        <>
                          <Download size={20} />
                          <span>Aggiorna Sistema (apt-get update && upgrade)</span>
                        </>
                      )}
                    </motion.button>
                    
                    {updateMessage && (
                      <div className={`rounded-lg p-3 text-center text-sm ${
                        updateMessage.includes('Errore') || updateMessage.includes('non disponibile')
                          ? 'bg-red-900/20 text-red-300 border border-red-500/30'
                          : 'bg-hifi-dark text-hifi-silver'
                      }`}>
                        {updateMessage}
                      </div>
                    )}

                    {/* Reboot */}
                    <motion.button
                      onClick={handleReboot}
                      className="w-full bg-orange-600 hover:bg-orange-700 text-white py-4 rounded-lg font-semibold flex items-center justify-center space-x-2 transition-colors"
                      whileTap={{ scale: 0.95 }}
                    >
                      <RotateCw size={20} />
                      <span>Riavvia Sistema</span>
                    </motion.button>

                    {/* Shutdown */}
                    <motion.button
                      onClick={handleShutdown}
                      className="w-full bg-red-600 hover:bg-red-700 text-white py-4 rounded-lg font-semibold flex items-center justify-center space-x-2 transition-colors"
                      whileTap={{ scale: 0.95 }}
                    >
                      <Power size={20} />
                      <span>Spegni Sistema</span>
                    </motion.button>
                  </div>
                )}

                {/* Regular items */}
                {section.items && (
                  <div className="space-y-3">
                    {section.items.map((item, itemIndex) => (
                      <div
                        key={itemIndex}
                        className="flex items-center justify-between py-2"
                      >
                        <span className="text-hifi-silver text-sm">{item.label}</span>
                        <span className="text-white font-mono text-sm">{item.value}</span>
                      </div>
                    ))}
                  </div>
                )}
              </motion.div>
            );
          })}
        </div>

        {/* First-setup wizard */}
        <motion.button
          onClick={() => {
            localStorage.removeItem('firstSetupComplete');
            window.dispatchEvent(new Event('hifi-open-wizard'));
          }}
          className="w-full mt-6 bg-hifi-light hover:bg-hifi-accent text-white py-4 rounded-lg font-semibold flex items-center justify-center space-x-2 transition-colors"
          whileTap={{ scale: 0.95 }}
        >
          <RotateCw size={20} />
          <span>Riavvia configurazione guidata</span>
        </motion.button>

        {/* About section */}
        <motion.div
          initial={{ y: 20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ delay: 0.6 }}
          className="mt-8 text-center text-hifi-silver text-sm"
        >
          <p>HiFi Media Player v{__APP_VERSION__}</p>
          <p className="mt-1">Built with Electron, React, and Tailwind CSS</p>
        </motion.div>
      </div>
    </motion.div>
  );
};

export default Settings;