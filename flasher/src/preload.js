'use strict';

const { contextBridge, ipcRenderer } = require('electron');

/**
 * The renderer gets exactly these calls and nothing else — no fs, no child
 * processes, no direct access to the device path handling.
 */
contextBridge.exposeInMainWorld('flasher', {
  info: () => ipcRenderer.invoke('app:info'),

  fetchManifest: () => ipcRenderer.invoke('manifest:fetch'),
  prepareImage: (release) => ipcRenderer.invoke('image:prepare', release),
  cancelImage: () => ipcRenderer.invoke('image:cancel'),
  pickImage: () => ipcRenderer.invoke('image:pick'),

  watchDrives: () => ipcRenderer.invoke('drives:watch'),
  write: (args) => ipcRenderer.invoke('write:start', args),
  restore: (args) => ipcRenderer.invoke('restore:start', args),
  openExternal: (url) => ipcRenderer.invoke('shell:open', url),

  onImageProgress: (fn) => ipcRenderer.on('image:progress', (_e, p) => fn(p)),
  onDrives: (fn) => ipcRenderer.on('drives:changed', (_e, list) => fn(list)),
  onWriteProgress: (fn) => ipcRenderer.on('write:progress', (_e, p) => fn(p)),
});
