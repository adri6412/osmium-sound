import { contextBridge, ipcRenderer } from 'electron';

/**
 * Preload script to expose safe IPC methods to the renderer process
 * This maintains security by using contextIsolation
 */
contextBridge.exposeInMainWorld('electronAPI', {
  // System info
  getSystemInfo: () => ipcRenderer.invoke('get-system-info'),
  getNetworkInfo: () => ipcRenderer.invoke('get-network-info'),
  
  // Playback control (for future use)
  playbackControl: (action, data) => ipcRenderer.invoke('playback-control', action, data),
  setVolume: (volume) => ipcRenderer.invoke('set-volume', volume),
  
  // System control
  systemUpdate: () => ipcRenderer.invoke('system-update'),
  systemReboot: () => ipcRenderer.invoke('system-reboot'),
  systemShutdown: () => ipcRenderer.invoke('system-shutdown'),

  // Network configuration
  setNetworkConfig: (config) => ipcRenderer.invoke('set-network-config', config),
  
  // Simple-keyboard control
  toggleSimpleKeyboard: () => ipcRenderer.invoke('toggle-simple-keyboard'),
  showSimpleKeyboard: () => ipcRenderer.invoke('show-simple-keyboard'),
  hideSimpleKeyboard: () => ipcRenderer.invoke('hide-simple-keyboard'),
  
  // Global keyboard control (system keyboards)
  showGlobalKeyboard: () => ipcRenderer.invoke('show-global-keyboard'),
  hideGlobalKeyboard: () => ipcRenderer.invoke('hide-global-keyboard'),
  
  // Event listeners for global shortcuts
  onToggleSimpleKeyboard: (callback) => {
    ipcRenderer.on('toggle-simple-keyboard', callback);
  },
  removeToggleSimpleKeyboard: (callback) => {
    ipcRenderer.removeListener('toggle-simple-keyboard', callback);
  }
});

