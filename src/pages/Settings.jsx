import React, { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { 
  Wifi, 
  Info,
  Power,
  RotateCw,
  Download,
  Loader2,
  Network
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

  // Refs for input fields with automatic keyboard
  const lyrionUrlRef = useKeyboardInput(lyrionUrl, setLyrionUrl);
  
  // Test keyboard context
  const { showKeyboard } = useKeyboard();

  // Load system and network data on component mount
  useEffect(() => {
    loadSystemData();
  }, []);

  // Auto-check for a UI (OTA) update on mount; clean up any poll on unmount
  useEffect(() => {
    checkAppUpdate();
    checkSystemUpdate();
    checkLyrionUpdate();
    return () => {
      if (otaPollRef.current) clearInterval(otaPollRef.current);
      if (systemPollRef.current) clearInterval(systemPollRef.current);
      if (lyrionPollRef.current) clearInterval(lyrionPollRef.current);
    };
  }, []);

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

  const applyAppUpdate = async () => {
    if (!apiConnected) {
      setUpdateMessage('Errore: Server API non disponibile');
      return;
    }
    setIsApplyingUpdate(true);
    setOtaStatus({ state: 'starting', message: 'Avvio aggiornamento…' });
    try {
      const result = await systemAPI.applyAppUpdate();
      if (!result.success || !result.data.started) {
        setOtaStatus({ state: 'error', message: result.data?.message || result.message || 'Avvio fallito' });
        setIsApplyingUpdate(false);
        return;
      }
      // Poll progress until done/error (the UI will be restarted on success).
      otaPollRef.current = setInterval(async () => {
        const s = await systemAPI.getAppUpdateStatus();
        if (s.success) {
          setOtaStatus(s.data);
          if (s.data.state === 'done' || s.data.state === 'error') {
            clearInterval(otaPollRef.current);
            otaPollRef.current = null;
            setIsApplyingUpdate(false);
          }
        }
      }, 2000);
    } catch (error) {
      setOtaStatus({ state: 'error', message: 'Errore durante l\'aggiornamento' });
      setIsApplyingUpdate(false);
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

  const applySystemUpdate = async () => {
    if (!apiConnected) {
      setUpdateMessage('Errore: Server API non disponibile');
      return;
    }
    setIsApplyingSystem(true);
    setSystemStatus({ state: 'starting', message: 'Avvio aggiornamento…' });
    try {
      const result = await systemAPI.applySystemUpdate();
      if (!result.success || !result.data.started) {
        setSystemStatus({ state: 'error', message: result.data?.message || result.message || 'Avvio fallito' });
        setIsApplyingSystem(false);
        return;
      }
      // Poll progress until done/error. The API itself restarts at the end, so
      // a transient network error during polling is expected near completion.
      systemPollRef.current = setInterval(async () => {
        const s = await systemAPI.getSystemUpdateStatus();
        if (s.success) {
          setSystemStatus(s.data);
          if (s.data.state === 'done' || s.data.state === 'error') {
            clearInterval(systemPollRef.current);
            systemPollRef.current = null;
            setIsApplyingSystem(false);
            if (s.data.state === 'done') checkSystemUpdate();
          }
        }
      }, 2000);
    } catch (error) {
      setSystemStatus({ state: 'error', message: 'Errore durante l\'aggiornamento' });
      setIsApplyingSystem(false);
    }
  };

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
        { label: 'App Version', value: systemInfo.version, type: 'info' },
        { label: 'Stato API', value: apiConnected ? 'Connesso' : 'Disconnesso', type: 'info' },
      ]
    },
    {
      title: 'Aggiornamento UI',
      icon: Download,
      content: 'custom-app-update'
    },
    {
      title: 'Aggiornamento Sistema',
      icon: Download,
      content: 'custom-system-update'
    },
    {
      title: 'Aggiornamento Lyrion',
      icon: Download,
      content: 'custom-lyrion-update'
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

                {/* Custom App (OTA) Update Section */}
                {section.content === 'custom-app-update' && (
                  <div className="space-y-4">
                    {/* Version info */}
                    <div className="bg-hifi-dark rounded-lg p-4 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-hifi-silver text-sm">Versione installata</span>
                        <span className="text-white font-mono text-sm">
                          {appUpdate?.current || systemInfo.version || '...'}
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-hifi-silver text-sm">Ultima versione</span>
                        <span className="text-white font-mono text-sm">
                          {appUpdate?.error ? 'N/D' : (appUpdate?.latest || '...')}
                        </span>
                      </div>
                    </div>

                    {/* Update available badge */}
                    {appUpdate?.update_available && (
                      <div className="rounded-lg p-3 text-center text-sm bg-hifi-gold/20 text-hifi-gold border border-hifi-gold/40">
                        Aggiornamento disponibile: {appUpdate.latest}
                      </div>
                    )}
                    {appUpdate && !appUpdate.error && !appUpdate.update_available && (
                      <div className="rounded-lg p-3 text-center text-sm bg-hifi-dark text-hifi-silver">
                        L'interfaccia è aggiornata
                      </div>
                    )}
                    {appUpdate?.error && (
                      <div className="rounded-lg p-3 text-center text-sm bg-red-900/20 text-red-300 border border-red-500/30">
                        {appUpdate.error}
                      </div>
                    )}

                    {/* Check for updates */}
                    <motion.button
                      onClick={checkAppUpdate}
                      disabled={isCheckingUpdate || isApplyingUpdate}
                      className="w-full bg-hifi-accent hover:bg-hifi-light disabled:bg-hifi-dark text-white py-3 rounded-lg font-medium flex items-center justify-center space-x-2 transition-colors"
                      whileTap={{ scale: isCheckingUpdate ? 1 : 0.95 }}
                    >
                      {isCheckingUpdate ? (
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
                    {appUpdate?.update_available && (
                      <motion.button
                        onClick={applyAppUpdate}
                        disabled={isApplyingUpdate}
                        className="w-full bg-hifi-gold hover:bg-yellow-600 disabled:bg-hifi-accent text-black py-4 rounded-lg font-semibold flex items-center justify-center space-x-2 transition-colors"
                        whileTap={{ scale: isApplyingUpdate ? 1 : 0.95 }}
                      >
                        {isApplyingUpdate ? (
                          <>
                            <Loader2 size={20} className="animate-spin" />
                            <span>Aggiornamento...</span>
                          </>
                        ) : (
                          <>
                            <Download size={20} />
                            <span>Aggiorna ora ({appUpdate.latest})</span>
                          </>
                        )}
                      </motion.button>
                    )}

                    {isApplyingUpdate && (
                      <p className="text-xs text-hifi-silver text-center">
                        Il dispositivo riavvierà l'interfaccia al termine.
                      </p>
                    )}

                    {/* OTA progress */}
                    {otaStatus && (
                      <div className={`rounded-lg p-3 text-center text-sm ${
                        otaStatus.state === 'error'
                          ? 'bg-red-900/20 text-red-300 border border-red-500/30'
                          : 'bg-hifi-dark text-hifi-silver'
                      }`}>
                        {otaStatus.message || otaStatus.state}
                        {typeof otaStatus.progress === 'number' && otaStatus.state !== 'error' && (
                          <span className="ml-1">({otaStatus.progress}%)</span>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* Custom System-components Update Section */}
                {section.content === 'custom-system-update' && (
                  <div className="space-y-4">
                    <p className="text-sm text-hifi-silver">
                      Aggiorna i componenti interni: server API, daemon VU-meter, servizio sorgenti e script di sistema.
                    </p>

                    {/* Version info */}
                    <div className="bg-hifi-dark rounded-lg p-4 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-hifi-silver text-sm">Versione installata</span>
                        <span className="text-white font-mono text-sm">
                          {systemUpdate?.current || '...'}
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-hifi-silver text-sm">Ultima versione</span>
                        <span className="text-white font-mono text-sm">
                          {systemUpdate?.error ? 'N/D' : (systemUpdate?.latest || '...')}
                        </span>
                      </div>
                    </div>

                    {systemUpdate?.update_available && (
                      <div className="rounded-lg p-3 text-center text-sm bg-hifi-gold/20 text-hifi-gold border border-hifi-gold/40">
                        Aggiornamento disponibile: {systemUpdate.latest}
                      </div>
                    )}
                    {systemUpdate && !systemUpdate.error && !systemUpdate.update_available && (
                      <div className="rounded-lg p-3 text-center text-sm bg-hifi-dark text-hifi-silver">
                        I componenti di sistema sono aggiornati
                      </div>
                    )}
                    {systemUpdate?.error && (
                      <div className="rounded-lg p-3 text-center text-sm bg-red-900/20 text-red-300 border border-red-500/30">
                        {systemUpdate.error}
                      </div>
                    )}

                    {/* Check for updates */}
                    <motion.button
                      onClick={checkSystemUpdate}
                      disabled={isCheckingSystem || isApplyingSystem}
                      className="w-full bg-hifi-accent hover:bg-hifi-light disabled:bg-hifi-dark text-white py-3 rounded-lg font-medium flex items-center justify-center space-x-2 transition-colors"
                      whileTap={{ scale: isCheckingSystem ? 1 : 0.95 }}
                    >
                      {isCheckingSystem ? (
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
                    {systemUpdate?.update_available && (
                      <motion.button
                        onClick={applySystemUpdate}
                        disabled={isApplyingSystem}
                        className="w-full bg-hifi-gold hover:bg-yellow-600 disabled:bg-hifi-accent text-black py-4 rounded-lg font-semibold flex items-center justify-center space-x-2 transition-colors"
                        whileTap={{ scale: isApplyingSystem ? 1 : 0.95 }}
                      >
                        {isApplyingSystem ? (
                          <>
                            <Loader2 size={20} className="animate-spin" />
                            <span>Aggiornamento...</span>
                          </>
                        ) : (
                          <>
                            <Download size={20} />
                            <span>Aggiorna ora ({systemUpdate.latest})</span>
                          </>
                        )}
                      </motion.button>
                    )}

                    {isApplyingSystem && (
                      <p className="text-xs text-hifi-silver text-center">
                        I servizi di sistema verranno riavviati al termine.
                      </p>
                    )}

                    {/* System update progress */}
                    {systemStatus && (
                      <div className={`rounded-lg p-3 text-center text-sm ${
                        systemStatus.state === 'error'
                          ? 'bg-red-900/20 text-red-300 border border-red-500/30'
                          : 'bg-hifi-dark text-hifi-silver'
                      }`}>
                        {systemStatus.message || systemStatus.state}
                        {typeof systemStatus.progress === 'number' && systemStatus.state !== 'error' && (
                          <span className="ml-1">({systemStatus.progress}%)</span>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* Custom Lyrion Update Section */}
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
          <p>HiFi Media Player v1.0.0</p>
          <p className="mt-1">Built with Electron, React, and Tailwind CSS</p>
        </motion.div>
      </div>
    </motion.div>
  );
};

export default Settings;