const { contextBridge, ipcRenderer } = require('electron');

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
  },

  // Physical (USB/PS2) keyboard presence — live, from udev via the main
  // process. Used by App.jsx to suppress the on-screen keyboard.
  getPhysicalKeyboard: () => ipcRenderer.invoke('get-physical-keyboard'),
  onPhysicalKeyboardChanged: (callback) => {
    ipcRenderer.on('physical-keyboard-changed', callback);
  },
  removePhysicalKeyboardChanged: (callback) => {
    ipcRenderer.removeListener('physical-keyboard-changed', callback);
  },

  // Debug section (Settings.jsx) — HAR network capture via CDP, only the
  // main process can drive webContents.debugger. The saved .har is
  // downloaded from the web admin, not from here (see api_server.py).
  startHarCapture: () => ipcRenderer.invoke('har-capture-start'),
  stopHarCapture: () => ipcRenderer.invoke('har-capture-stop'),
  getHarCaptureStatus: () => ipcRenderer.invoke('har-capture-status')
});
