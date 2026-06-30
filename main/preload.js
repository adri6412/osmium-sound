import { contextBridge, ipcRenderer } from 'electron';

/**
 * Preload script to expose safe IPC methods to the renderer process
 * This maintains security by using contextIsolation
 */
// Only expose what the renderer actually uses. System control (reboot/shutdown/
// update/network) and system/network info go through the Flask API instead
// (src/utils/api.js → http://localhost:8000), so they are intentionally NOT
// bridged here.
contextBridge.exposeInMainWorld('electronAPI', {
  // Renderer frame-rate cap (e.g. 60 during the boot intro, 30 for steady UI)
  setFrameRate: (fps) => ipcRenderer.invoke('set-frame-rate', fps),

  // Global keyboard control (system on-screen keyboards) — used by Sidebar
  showGlobalKeyboard: () => ipcRenderer.invoke('show-global-keyboard'),
  hideGlobalKeyboard: () => ipcRenderer.invoke('hide-global-keyboard'),

  // Ctrl+Shift+K/J global shortcut → toggle the in-app simple-keyboard
  onToggleSimpleKeyboard: (callback) => {
    ipcRenderer.on('toggle-simple-keyboard', callback);
  },
  removeToggleSimpleKeyboard: (callback) => {
    ipcRenderer.removeListener('toggle-simple-keyboard', callback);
  }
});

