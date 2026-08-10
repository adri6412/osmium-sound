import { app, BrowserWindow, ipcMain, session, globalShortcut, screen } from 'electron';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { exec } from 'child_process';
import { promisify } from 'util';
import { appendFileSync } from 'fs';

const execAsync = promisify(exec);

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

let mainWindow;

// Same sink the renderer's console-message listener writes to (see below) —
// main-process events (recovery reloads, load failures) land in the same
// file/timeline so the two can be correlated over SSH without a screen.
function logToFile(prefix, message) {
  try {
    appendFileSync(
      join(app.getPath('logs'), 'renderer-console.log'),
      `${new Date().toISOString()} [${prefix}] ${message}\n`
    );
  } catch (_) {}
}

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
  logToFile('MAIN', `Renderer recovery (${reason}); reload #${recoveryReloads} in ${delay}ms, tightLoop=${tightLoop}`);
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
 * Create the main application window, sized to fill the actual display
 * (7" touchscreen, 1080p/4K TV, ...). The renderer's ScaledCanvas then scales
 * the fixed 1024x600 design canvas to fit whatever size that turns out to be.
 */
function createWindow() {
  // Relax framing/CSP ONLY for the local Lyrion Music Server (localhost:9000 —
  // Lyrion always runs on the appliance itself, see lyrionApi.js's default
  // baseUrl), whose pages we embed in the UI. Matching on port alone would
  // strip these headers for ANY device on the LAN that happens to answer on
  // 9000 too (rogue host, DNS-rebinding); host+port together pin this to the
  // one server it's actually meant for. Keep every other origin's own
  // defenses (remote radio/plugin content, etc.) untouched.
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    let isLyrion = false;
    try {
      const url = new URL(details.url);
      isLyrion = (url.hostname === 'localhost' || url.hostname === '127.0.0.1') && url.port === '9000';
    } catch (_) {}
    if (isLyrion && details.responseHeaders) {
      delete details.responseHeaders['x-frame-options'];
      delete details.responseHeaders['X-Frame-Options'];
      delete details.responseHeaders['content-security-policy'];
      delete details.responseHeaders['Content-Security-Policy'];
    }
    callback({ responseHeaders: details.responseHeaders });
  });

  // The xsession runs Chromium bare (no window manager), so the
  // `--start-fullscreen` CLI flag has nothing to make it fullscreen with —
  // that flag is a Chrome *browser* switch, not something Electron's
  // BrowserWindow reads from argv. Without a WM to honor the EWMH fullscreen
  // hint either, the only reliable way to cover the whole panel (7"
  // touchscreen, 1080p/4K TV over HDMI, ...) is to size the window to the
  // display's actual resolution ourselves, up front.
  const { width: screenWidth, height: screenHeight } = screen.getPrimaryDisplay().size;

  mainWindow = new BrowserWindow({
    width: screenWidth,
    height: screenHeight,
    minWidth: 1024,
    minHeight: 600,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      // .cjs, not .js: package.json's "type": "module" makes .js ESM by
      // default, but Electron loads preload scripts in a sandboxed context
      // that only understands CommonJS ("Cannot use import statement outside
      // a module" otherwise, on every single launch — window.electronAPI was
      // never actually available in the renderer).
      preload: join(__dirname, 'preload.cjs')
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
    // NOTE: webContents.setFrameRate() is a no-op here. Electron only honors
    // it for BrowserWindows created with webPreferences.offscreen — this
    // window isn't one (it's the real on-screen kiosk surface), so this call
    // has never actually capped anything, on any Electron version; it fails
    // silently (no exception) rather than throwing, which is why nobody
    // noticed. Left in place in case a future Electron version widens
    // support, but don't rely on it — see ipcMain 'set-frame-rate' below for
    // the same caveat, and AnalogVUMeter.jsx for where real frame-rate
    // mitigation actually lives now (throttling how often continuous
    // animations get re-targeted, since the compositor itself can't be
    // capped below the display's vsync rate from here).
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

  // The kiosk has no DevTools and no captured stdout (the X session doesn't
  // redirect it anywhere) — a renderer bug is otherwise invisible without a
  // screen/keyboard physically on the appliance. Mirror warnings/errors
  // (console-message level 2/3) to a plain file so `ssh` + `tail` can see
  // what the UI actually logged.
  mainWindow.webContents.on('console-message', (event, level, message, line, sourceId) => {
    if (level < 2) return;
    try {
      appendFileSync(
        join(app.getPath('logs'), 'renderer-console.log'),
        `${new Date().toISOString()} [${level === 3 ? 'ERROR' : 'WARN'}] ${message} (${sourceId}:${line})\n`
      );
    } catch (_) {}
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

// This kiosk has exactly one window and no way for the user to close it (no
// frame, no close button) — window-all-closed here means the window itself
// died, most likely a GPU/renderer crash severe enough that recoverRenderer's
// reload couldn't save it (e.g. under the CPU load of the DSP engine), not a
// deliberate quit. Recreate the window instead of quitting: app.quit() hands
// recovery off to the xsession relaunch loop, a full process restart (cold
// JS state, the preload script re-running, the 10s Lyrion reconnect delay)
// that's far slower and more disruptive than just opening a fresh window in
// the same still-running process.
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    createWindow();
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
 * The renderer asks for 60 FPS while the boot intro plays and 30 FPS for the
 * steady UI, intending to cap idle CPU/GPU compositor work — but
 * webContents.setFrameRate() only takes effect on offscreen-rendered
 * BrowserWindows (see the did-finish-load comment above), which this kiosk
 * window is not. The call below is kept because it's harmless (silently
 * ignored, doesn't throw), not because it works; treat this handler as
 * legacy/inert until the window is actually converted to offscreen
 * rendering, and look to per-component throttling (AnalogVUMeter.jsx) for
 * real mitigation in the meantime.
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
