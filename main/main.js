import { app, BrowserWindow, ipcMain, session, globalShortcut } from 'electron';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

let mainWindow;

// Renderer-crash recovery: how many times we've auto-reloaded, and when we last
// did. After long uptime the Chromium renderer/GPU process can die (OOM, GPU
// driver fault) leaving the window alive but blank — a white screen the user
// can't recover from. We reload it ourselves instead of leaving it dead.
let recoveryReloads = 0;
let lastRecoveryAt = 0;

/**
 * Reload the renderer after a crash/hang, with a tiny backoff so a tight
 * crash-loop can't spin the CPU. The counter resets whenever the page has been
 * healthy for a while (handled in did-finish-load).
 */
function recoverRenderer(reason) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const now = Date.now();
  // If the last recovery was very recent we're in a crash loop — back off harder.
  const tightLoop = now - lastRecoveryAt < 10000;
  lastRecoveryAt = now;
  recoveryReloads += 1;
  const delay = tightLoop ? Math.min(30000, 2000 * recoveryReloads) : 1000;
  console.error(`Renderer recovery (${reason}); reload #${recoveryReloads} in ${delay}ms`);
  setTimeout(() => {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    try {
      mainWindow.webContents.reloadIgnoringCache();
    } catch (err) {
      console.error('Recovery reload failed:', err);
    }
  }, delay);
}

/**
 * Create the main application window
 * Optimized for 1024x600 touchscreen displays
 */
function createWindow() {
  // Relax framing/CSP ONLY for the local Lyrion Music Server (port 9000), whose
  // pages we embed in the UI. Previously these headers were stripped from EVERY
  // response, globally disabling X-Frame-Options/CSP for any site the app loads
  // (remote radio/plugin content, etc.) — keep every other origin's own defenses.
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    let isLyrion = false;
    try { isLyrion = new URL(details.url).port === '9000'; } catch (_) {}
    if (isLyrion && details.responseHeaders) {
      delete details.responseHeaders['x-frame-options'];
      delete details.responseHeaders['X-Frame-Options'];
      delete details.responseHeaders['content-security-policy'];
      delete details.responseHeaders['Content-Security-Policy'];
    }
    callback({ responseHeaders: details.responseHeaders });
  });

  mainWindow = new BrowserWindow({
    width: 1024,
    height: 600,
    minWidth: 1024,
    minHeight: 600,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: join(__dirname, 'preload.js')
    },
    icon: join(__dirname, '../assets/icon.png'),
    titleBarStyle: 'hidden',
    frame: false,
    resizable: false,
    fullscreen: false,
    show: false
  });

  // Load the app
  const isDev = process.env.NODE_ENV === 'development';
  if (isDev) {
    mainWindow.loadURL('http://localhost:5173');
    mainWindow.webContents.openDevTools();
  } else {
    const indexPath = join(__dirname, '../renderer-dist/index.html');
    mainWindow.loadFile(indexPath).catch(err => {
      console.error('Failed to load file:', err);
      // Fallback to a simple HTML page
      mainWindow.loadURL('data:text/html,<html><body><h1>Loading...</h1><p>Please wait...</p></body></html>');
    });
  }

  // Show window when ready
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  // Add error handling for web contents
  mainWindow.webContents.on('did-fail-load', (event, errorCode, errorDescription, validatedURL, isMainFrame) => {
    console.error('Failed to load:', errorCode, errorDescription, validatedURL);
    // -3 (ERR_ABORTED) is benign (e.g. a superseded navigation). Anything else
    // on the main frame means we have no usable page — retry the load.
    if (isMainFrame && errorCode !== -3) {
      recoverRenderer(`did-fail-load ${errorCode}`);
    }
  });

  mainWindow.webContents.on('did-finish-load', () => {
    // Cap the compositor at 30 FPS. For this media-player UI that's visually
    // smooth and roughly halves paint/composite work on the Pi-class hardware.
    // Reapplied here (not just at creation) so it survives a recovery reload.
    try {
      mainWindow.webContents.setFrameRate(30);
    } catch (err) {
      console.error('setFrameRate failed:', err);
    }
    // The page loaded successfully; if it then stays healthy for a while, forget
    // earlier crashes so a future incident gets a fast (non-backed-off) reload.
    setTimeout(() => {
      if (mainWindow && !mainWindow.isDestroyed() && Date.now() - lastRecoveryAt > 60000) {
        recoveryReloads = 0;
      }
    }, 60000);
  });

  // Renderer process died (crash, OOM, killed). Without this the window is left
  // showing a blank/white page after long uptime. Reload it. ('crashed' is the
  // pre-Electron-22 name; 'render-process-gone' is current — handle both.)
  mainWindow.webContents.on('render-process-gone', (event, details) => {
    if (details && details.reason === 'clean-exit') return;
    recoverRenderer(`render-process-gone:${details ? details.reason : '?'}`);
  });

  // The renderer stopped responding to input/events (event-loop wedged). Reload
  // rather than leaving the user staring at a frozen screen.
  mainWindow.on('unresponsive', () => {
    recoverRenderer('unresponsive');
  });

  // Handle window closed
  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

/**
 * Register global keyboard shortcuts
 */
function registerGlobalShortcuts() {
  // Ctrl+Shift+K and Ctrl+Shift+J both toggle the in-app simple-keyboard.
  const toggle = () => {
    if (mainWindow) mainWindow.webContents.send('toggle-simple-keyboard');
  };
  for (const accel of ['CommandOrControl+Shift+K', 'CommandOrControl+Shift+J']) {
    if (!globalShortcut.register(accel, toggle)) {
      console.error(`Failed to register global shortcut: ${accel}`);
    }
  }
}

// App event handlers
app.whenReady().then(() => {
  createWindow();
  registerGlobalShortcuts();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

// Cleanup global shortcuts when app is about to quit
app.on('will-quit', () => {
  globalShortcut.unregisterAll();
});

/**
 * Set the renderer compositor frame rate. The renderer asks for 60 FPS while
 * the boot intro plays (so the animation is smooth on the x86 mini-PC) and 30
 * FPS for the steady UI (to keep idle CPU/heat down).
 */
ipcMain.handle('set-frame-rate', (event, fps) => {
  const n = Math.max(1, Math.min(120, Number(fps) || 30));
  try {
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.setFrameRate(n);
    return { success: true, fps: n };
  } catch (err) {
    console.error('set-frame-rate failed:', err);
    return { success: false };
  }
});

/**
 * Global virtual keyboard control (system on-screen keyboards). These plus
 * set-frame-rate are the only IPC channels the renderer actually invokes — all
 * system control (reboot/shutdown/update/network) goes through the Flask API
 * (src/utils/api.js → http://localhost:8000), so the old duplicate IPC handlers
 * for those (and the unused playback/simple-keyboard/info placeholders) were
 * removed to shrink the surface.
 */
ipcMain.handle('show-global-keyboard', async () => {
  // Launch the first on-screen keyboard that is actually installed.
  for (const cmd of ['onboard', 'florence', 'xvkbd', 'matchbox-keyboard']) {
    try {
      await execAsync(`which ${cmd}`);
      execAsync(`${cmd} &`);
      return { success: true, message: `Tastiera virtuale ${cmd} avviata` };
    } catch (e) {
      // not installed — try the next one
    }
  }
  return { success: false, message: 'Nessuna tastiera virtuale di sistema trovata' };
});

ipcMain.handle('hide-global-keyboard', async () => {
  for (const cmd of ['onboard', 'florence', 'xvkbd', 'matchbox-keyboard']) {
    try { await execAsync(`pkill -f ${cmd}`); } catch (e) { /* not running */ }
  }
  return { success: true, message: 'Tastiera virtuale chiusa' };
});
