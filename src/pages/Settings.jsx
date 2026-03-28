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
  const [networkMode, setNetworkMode] = useState('dhcp');
  const [staticIP, setStaticIP] = useState('192.168.1.100');
  const [staticGateway, setStaticGateway] = useState('192.168.1.1');
  const [staticDNS, setStaticDNS] = useState('8.8.8.8');
  const [lyrionUrl, setLyrionUrl] = useState(localStorage.getItem('lyrionUrl') || 'http://localhost:9000');
  const [isUpdating, setIsUpdating] = useState(false);
  const [updateMessage, setUpdateMessage] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [apiConnected, setApiConnected] = useState(false);

  // Refs for input fields with automatic keyboard
  const ipInputRef = useKeyboardInput(staticIP, setStaticIP);
  const gatewayInputRef = useKeyboardInput(staticGateway, setStaticGateway);
  const dnsInputRef = useKeyboardInput(staticDNS, setStaticDNS);
  const lyrionUrlRef = useKeyboardInput(lyrionUrl, setLyrionUrl);
  
  // Test keyboard context
  const { showKeyboard, isKeyboardVisible } = useKeyboard();

  // Load system and network data on component mount
  useEffect(() => {
    loadSystemData();
  }, []);

  // Input change handlers
  const handleInputChange = (e, setter) => {
    setter(e.target.value);
  };

  // Keyboard input handlers that work with the virtual keyboard
  const handleIPChange = (e) => {
    setStaticIP(e.target.value);
  };

  const handleGatewayChange = (e) => {
    setStaticGateway(e.target.value);
  };

  const handleDNSChange = (e) => {
    setStaticDNS(e.target.value);
  };

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

  const handleNetworkModeChange = async () => {
    if (!apiConnected) {
      setUpdateMessage('Errore: Server API non disponibile');
      return;
    }

    if (!selectedInterface) {
      setUpdateMessage('Seleziona un\'interfaccia di rete');
      return;
    }

    setUpdateMessage('Configurazione di rete in corso...');
    
    try {
      const config = {
        interface: selectedInterface,
        mode: networkMode,
        ...(networkMode === 'static' && {
          ip: staticIP,
          gateway: staticGateway,
          dns: staticDNS
        })
      };

      const result = await systemAPI.configureNetwork(config);
      if (result.success) {
        setUpdateMessage(result.data.message || 'Configurazione di rete applicata!');
        // Reload network info after configuration
        setTimeout(() => {
          loadSystemData();
        }, 2000);
      } else {
        setUpdateMessage(result.message || 'Errore durante la configurazione di rete');
      }
    } catch (error) {
      setUpdateMessage('Errore durante la configurazione di rete');
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

                    {/* Network Mode Selection */}
                    <div className="space-y-3">
                      <label className="text-white font-medium">Modalità Rete</label>
                      <div className="flex gap-4">
                        <motion.button
                          onClick={() => setNetworkMode('dhcp')}
                          className={`flex-1 py-3 rounded-lg font-semibold transition-colors ${
                            networkMode === 'dhcp'
                              ? 'bg-hifi-gold text-black'
                              : 'bg-hifi-light text-white hover:bg-hifi-accent'
                          }`}
                          whileTap={{ scale: 0.95 }}
                        >
                          DHCP (Automatico)
                        </motion.button>
                        <motion.button
                          onClick={() => setNetworkMode('static')}
                          className={`flex-1 py-3 rounded-lg font-semibold transition-colors ${
                            networkMode === 'static'
                              ? 'bg-hifi-gold text-black'
                              : 'bg-hifi-light text-white hover:bg-hifi-accent'
                          }`}
                          whileTap={{ scale: 0.95 }}
                        >
                          IP Statico
                        </motion.button>
                      </div>
                    </div>

                    {/* Static IP Configuration */}
                    {networkMode === 'static' && (
                      <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto' }}
                        className="space-y-3"
                      >
                        <div>
                          <label className="text-sm text-hifi-silver mb-1 block">Indirizzo IP</label>
                          <div 
                            onClick={() => {
                              console.log('🖱️ IP Input wrapper clicked!');
                              showKeyboard(ipInputRef, staticIP);
                            }}
                            className="cursor-pointer"
                          >
                            <input
                              ref={ipInputRef}
                              type="text"
                              value={staticIP}
                              onChange={handleIPChange}
                              className="w-full bg-hifi-dark border border-hifi-accent rounded-lg px-4 py-2 text-white font-mono focus:outline-none focus:border-hifi-gold cursor-pointer"
                              placeholder="192.168.1.100"
                            />
                          </div>
                        </div>
                        <div>
                          <label className="text-sm text-hifi-silver mb-1 block">Gateway</label>
                          <div 
                            onClick={() => {
                              console.log('🖱️ Gateway Input wrapper clicked!');
                              showKeyboard(gatewayInputRef, staticGateway);
                            }}
                            className="cursor-pointer"
                          >
                            <input
                              ref={gatewayInputRef}
                              type="text"
                              value={staticGateway}
                              onChange={handleGatewayChange}
                              className="w-full bg-hifi-dark border border-hifi-accent rounded-lg px-4 py-2 text-white font-mono focus:outline-none focus:border-hifi-gold cursor-pointer"
                              placeholder="192.168.1.1"
                            />
                          </div>
                        </div>
                        <div>
                          <label className="text-sm text-hifi-silver mb-1 block">DNS</label>
                          <div 
                            onClick={() => {
                              console.log('🖱️ DNS Input wrapper clicked!');
                              showKeyboard(dnsInputRef, staticDNS);
                            }}
                            className="cursor-pointer"
                          >
                            <input
                              ref={dnsInputRef}
                              type="text"
                              value={staticDNS}
                              onChange={handleDNSChange}
                              className="w-full bg-hifi-dark border border-hifi-accent rounded-lg px-4 py-2 text-white font-mono focus:outline-none focus:border-hifi-gold cursor-pointer"
                              placeholder="8.8.8.8"
                            />
                          </div>
                        </div>
                        <motion.button
                          onClick={handleNetworkModeChange}
                          className="w-full bg-hifi-gold text-black py-3 rounded-lg font-semibold hover:bg-yellow-600 transition-colors"
                          whileTap={{ scale: 0.95 }}
                        >
                          Applica Configurazione
                        </motion.button>
                      </motion.div>
                    )}

                    {/* Test Virtual Keyboard Button */}
                    <motion.button
                      onClick={() => {
                        console.log('🧪 Test keyboard button clicked!');
                        showKeyboard({ current: null }, 'Test value');
                      }}
                      className="w-full bg-purple-600 hover:bg-purple-700 text-white py-2 rounded-lg font-medium flex items-center justify-center space-x-2 transition-colors"
                      whileTap={{ scale: 0.95 }}
                    >
                      <span>🧪 Test Tastiera Virtuale</span>
                    </motion.button>

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