'use strict';

/**
 * Osmium Flasher — main process.
 *
 * Stays unprivileged for its whole life. It fetches the manifest, downloads and
 * verifies the installer image, and lists candidate drives; the actual raw write
 * is delegated to an elevated helper (see src/elevate.js).
 */

const path = require('path');
const { app, BrowserWindow, dialog, ipcMain, shell } = require('electron');

const image = require('./image');
const { DriveWatcher } = require('./drives');
const { writeElevated } = require('./elevate');

const PUBLIC_KEY = path.join(__dirname, '..', 'assets', 'ota-pubkey.pem');

let mainWindow = null;
let watcher = null;
let downloadAbort = null;

function send(channel, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, payload);
  }
}

/** Turns any thrown error into the {ok:false, code} shape the renderer expects. */
function failure(err) {
  return {
    ok: false,
    code: err && err.code ? err.code : 'EUNKNOWN',
    message: err && err.message ? err.message : String(err),
    // Kept when the helper left a report behind: it holds the elevated side's
    // account of the failure, which is the only record of it.
    progressFile: err && err.progressFile ? err.progressFile : undefined,
  };
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 760,
    height: 620,
    minWidth: 640,
    minHeight: 560,
    backgroundColor: '#101214',
    title: 'Osmium Flasher',
    // Linux does not take the window icon from the packaged metadata the way
    // Windows takes it from the .exe, so it has to be set here.
    icon: path.join(__dirname, '..', 'assets', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.removeMenu();
  mainWindow.loadFile(path.join(__dirname, 'index.html'));

  // External links belong in the user's browser, never in this window.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https:\/\//.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ── IPC ────────────────────────────────────────────────────────────────────

ipcMain.handle('app:info', () => ({
  ok: true,
  version: app.getVersion(),
  locale: app.getLocale(),
  platform: process.platform,
}));

ipcMain.handle('manifest:fetch', async () => {
  try {
    return { ok: true, release: await image.fetchManifest() };
  } catch (err) {
    return failure(err);
  }
});

ipcMain.handle('image:prepare', async (_event, release) => {
  downloadAbort = new AbortController();
  const cacheDir = path.join(app.getPath('userData'), 'images');
  try {
    const result = await image.prepare(release, cacheDir, PUBLIC_KEY, {
      signal: downloadAbort.signal,
      onProgress: (p) => send('image:progress', p),
    });
    return { ok: true, ...result };
  } catch (err) {
    return failure(err);
  } finally {
    downloadAbort = null;
  }
});

ipcMain.handle('image:cancel', () => {
  if (downloadAbort) downloadAbort.abort();
  return { ok: true };
});

ipcMain.handle('image:pick', async () => {
  // Escape hatch for testers who already have an .iso on disk.
  const result = await dialog.showOpenDialog(mainWindow, {
    title: 'Select an Osmium Sound image',
    filters: [{ name: 'Disk image', extensions: ['iso', 'img'] }],
    properties: ['openFile'],
  });
  if (result.canceled || result.filePaths.length === 0) return { ok: false, code: 'ECANCELLED' };
  const file = result.filePaths[0];
  const { size } = require('fs').statSync(file);
  return { ok: true, file, size, digest: null, unverified: true };
});

ipcMain.handle('drives:watch', () => {
  if (!watcher) {
    watcher = new DriveWatcher((list) => send('drives:changed', list));
    watcher.start();
  } else {
    watcher.emit();
  }
  return { ok: true };
});

ipcMain.handle('write:start', async (_event, { devicePath, imagePath, imageSize, verify }) => {
  try {
    const result = await writeElevated({
      devicePath,
      imagePath,
      expectSize: imageSize,
      verify: verify !== false,
      onEvent: (event) => send('write:progress', event),
    });
    return { ok: true, ...result };
  } catch (err) {
    return failure(err);
  }
});

ipcMain.handle('restore:start', async (_event, { devicePath, label }) => {
  try {
    const result = await writeElevated({
      devicePath,
      mode: 'restore',
      label: label || 'OSMIUM',
      onEvent: (event) => send('write:progress', event),
    });
    return { ok: true, ...result };
  } catch (err) {
    return failure(err);
  }
});

ipcMain.handle('shell:open', (_event, url) => {
  if (/^https:\/\//.test(url) || /^mailto:/.test(url)) shell.openExternal(url);
  return { ok: true };
});

// ── lifecycle ──────────────────────────────────────────────────────────────

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(createWindow);

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
}

app.on('window-all-closed', () => {
  if (watcher) watcher.stop();
  app.quit();
});
