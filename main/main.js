import { app, BrowserWindow, ipcMain, session, globalShortcut, screen } from 'electron';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { exec } from 'child_process';
import { promisify } from 'util';
import { appendFileSync, readFileSync, mkdirSync, writeFileSync, readdirSync } from 'fs';

const execAsync = promisify(exec);

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

let mainWindow;

// The xsession restart loop (distro/os-update/files/xsession) relaunches this
// binary in a `while true` loop whenever it exits, and a UI-channel OTA
// update restarts lightdm (which re-runs xsession) to pick up new files —
// neither of those is guaranteed to have actually killed the previous
// process tree first (e.g. lightdm restarting while the old xsession's
// process group is still mid-shutdown). Without this lock, that races into
// two full Electron process trees running at once — seen live on the test
// VM as 9 renderer processes and 2 gpu-process/main-process pairs in htop —
// each polling LMS/the local API on its own timers, silently doubling real
// network+CPU load behind a single visible (frontmost) window. Electron's
// single-instance lock makes any second launch detect the first and exit
// immediately instead of standing up its own window/subprocess tree.
if (!app.requestSingleInstanceLock()) {
  app.quit();
  process.exit(0);
}
app.on('second-instance', () => {
  if (mainWindow && !mainWindow.isDestroyed()) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  }
});

// The kiosk has no keyboard/mouse to drive DevTools during normal operation,
// but debugging on the actual device is sometimes the only way to chase a
// hardware-specific bug — this flag file lets that be toggled over SSH
// without shipping a special build, mirroring the other on-device toggles
// under /etc/hifi-player (ota-channel, pointer-enabled, ota-alpha-unlocked).
// Read once at window creation (not watched live): flip it and restart the
// app to take effect. Missing file / anything other than exactly "true" ⇒ off.
function shouldOpenDevTools() {
  try {
    return readFileSync('/etc/hifi-player/devtools', 'utf8').trim() === 'true';
  } catch {
    return false;
  }
}

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

// Where Settings.jsx's Debug section saves HAR captures (see the
// har-capture-* IPC handlers near the bottom of this file). api_server.py
// serves this exact same path to the web admin for download — the two must
// stay in sync (grep HAR_CAPTURE_DIR there if this ever moves).
const HAR_CAPTURE_DIR = join(app.getPath('logs'), 'har-captures');

// Same idea as HAR_CAPTURE_DIR, for long-running perf-capture-* below.
// api_server.py mirrors this path too (grep PERF_CAPTURE_DIR there).
const PERF_CAPTURE_DIR = join(app.getPath('logs'), 'perf-captures');

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
  } else {
    const indexPath = join(__dirname, '../renderer-dist/index.html');
    mainWindow.loadFile(indexPath).catch(err => {
      console.error('Failed to load file:', err);
      // Fallback to a simple HTML page
      mainWindow.loadURL('data:text/html,<html><body><h1>Loading...</h1><p>Please wait...</p></body></html>');
    });
  }

  // 'bottom' docks the panel inside mainWindow itself rather than opening a
  // separate top-level window — this kiosk has no window manager, so a
  // detached DevTools window can't be moved, focused, or recovered if it
  // ends up off-screen or behind the main window.
  if (isDev || shouldOpenDevTools()) {
    mainWindow.webContents.openDevTools({ mode: 'bottom' });
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
    // A crash/reload (recoverRenderer above) tears down the old CDP session —
    // if a perf capture was in progress, re-enable the domain on the fresh
    // one instead of silently going dark on the renderer-side half of its
    // data for the rest of the (possibly multi-hour) capture.
    if (perfCapture && mainWindow) {
      const dbg = mainWindow.webContents.debugger;
      Promise.resolve()
        .then(() => { if (!dbg.isAttached()) dbg.attach('1.3'); })
        .then(() => dbg.sendCommand('Performance.enable'))
        .catch((err) => console.error('perf-capture: re-attach after reload failed:', err));
    }
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
  pollPhysicalKeyboard(); // establish the initial state immediately, don't wait 2s
  setInterval(pollPhysicalKeyboard, 2000);
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

/**
 * Physical keyboard presence, for the on-screen (simple-keyboard) auto-show
 * in App.jsx — a plugged-in USB keyboard should suppress it, and unplugging
 * one should bring it back, live, without a restart. There's no renderer-side
 * HID enumeration API in Chromium/Electron, so this reads real hardware
 * state from the main process instead: udev symlinks any device it
 * recognizes as a keyboard (USB or PS/2) to `*-event-kbd` under
 * /dev/input/by-id (falling back to /dev/input/by-path for devices with no
 * stable by-id link). Polled rather than watched — fs.watch on these dirs is
 * unreliable across filesystems/distros, and this isn't latency-sensitive.
 */
const KBD_DEVICE_DIRS = ['/dev/input/by-id', '/dev/input/by-path'];
let lastPhysicalKeyboard = null;

function hasPhysicalKeyboardNow() {
  for (const dir of KBD_DEVICE_DIRS) {
    try {
      if (readdirSync(dir).some((f) => f.endsWith('-event-kbd'))) return true;
    } catch (_) { /* dir may not exist, e.g. dev build off-target */ }
  }
  return false;
}

ipcMain.handle('get-physical-keyboard', () => hasPhysicalKeyboardNow());

function pollPhysicalKeyboard() {
  const now = hasPhysicalKeyboardNow();
  if (now === lastPhysicalKeyboard) return;
  lastPhysicalKeyboard = now;
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('physical-keyboard-changed', now);
  }
}

/**
 * HAR (network traffic) capture, for Settings.jsx's Debug section. The kiosk
 * has no keyboard to drive DevTools' own Network panel, so this drives the
 * same underlying Chrome DevTools Protocol from the main process instead:
 * attach webContents.debugger, record Network.* events between start/stop,
 * and write a standard .har file the user later downloads from the web
 * admin (api_server.py serves HAR_CAPTURE_DIR — see the constant above).
 *
 * Deliberately headers/status/timing only, no response bodies: fetching
 * Network.getResponseBody for every request would mean an extra CDP
 * round-trip per request and could balloon the file with image/audio
 * payloads, on a device that's already tight on CPU. That's still enough to
 * diagnose the failures this is meant for (wrong URL, CORS, 4xx/5xx, slow
 * requests) without the overhead.
 *
 * Mutually exclusive with openDevTools() (shouldOpenDevTools()/NODE_ENV=
 * development, above) — Chromium only allows one CDP client per target, so
 * dbg.attach() throws if real DevTools is already open on this window; the
 * error is surfaced to the caller rather than crashing anything.
 */
let harCapture = null; // { entries: Map<requestId, entry>, startedAt } | null

function harDebuggerListener(_event, method, params) {
  if (!harCapture) return;
  const entries = harCapture.entries;
  switch (method) {
    case 'Network.requestWillBeSent': {
      const { requestId, request, timestamp, wallTime, type } = params;
      entries.set(requestId, {
        _resourceType: type || '',
        _startTimestamp: timestamp,
        _endTimestamp: null,
        _failed: null,
        startedDateTime: new Date(wallTime * 1000).toISOString(),
        request: {
          method: request.method,
          url: request.url,
          httpVersion: 'HTTP/1.1',
          headers: Object.entries(request.headers || {}).map(([name, value]) => ({ name, value: String(value) })),
          queryString: [],
          cookies: [],
          headersSize: -1,
          bodySize: request.postData ? Buffer.byteLength(request.postData) : 0,
        },
        response: null,
      });
      break;
    }
    case 'Network.responseReceived': {
      const e = entries.get(params.requestId);
      if (!e) return;
      const { response } = params;
      e.response = {
        status: response.status,
        statusText: response.statusText || '',
        httpVersion: response.protocol || 'HTTP/1.1',
        headers: Object.entries(response.headers || {}).map(([name, value]) => ({ name, value: String(value) })),
        cookies: [],
        content: { size: 0, mimeType: response.mimeType || '' },
        redirectURL: '',
        headersSize: -1,
        bodySize: -1,
      };
      break;
    }
    case 'Network.loadingFinished': {
      const e = entries.get(params.requestId);
      if (!e) return;
      if (e.response) {
        e.response.content.size = params.encodedDataLength || 0;
        e.response.bodySize = params.encodedDataLength || 0;
      }
      e._endTimestamp = params.timestamp;
      break;
    }
    case 'Network.loadingFailed': {
      const e = entries.get(params.requestId);
      if (!e) return;
      e._failed = params.errorText || 'failed';
      e._endTimestamp = params.timestamp;
      break;
    }
    default:
      break;
  }
}

function buildHarLog(capture) {
  const emptyResponse = (reason) => ({
    status: 0, statusText: reason || '', httpVersion: '',
    headers: [], cookies: [], content: { size: 0, mimeType: '' },
    redirectURL: '', headersSize: -1, bodySize: -1,
  });
  const entries = [...capture.entries.values()].map((e) => ({
    startedDateTime: e.startedDateTime,
    time: e._endTimestamp != null ? Math.max(0, (e._endTimestamp - e._startTimestamp) * 1000) : 0,
    request: e.request,
    response: e.response || emptyResponse(e._failed || 'no response received'),
    cache: {},
    timings: { send: 0, wait: 0, receive: 0 },
    _resourceType: e._resourceType,
  }));
  entries.sort((a, b) => a.startedDateTime.localeCompare(b.startedDateTime));
  return {
    log: {
      version: '1.2',
      creator: { name: 'HiFi Player Debug Capture', version: app.getVersion() },
      pages: [],
      entries,
    },
  };
}

ipcMain.handle('har-capture-start', async () => {
  if (harCapture) return { success: false, message: 'Capture already running' };
  if (!mainWindow || mainWindow.isDestroyed()) return { success: false, message: 'No window' };
  const dbg = mainWindow.webContents.debugger;
  try {
    if (!dbg.isAttached()) dbg.attach('1.3');
    await dbg.sendCommand('Network.enable');
  } catch (err) {
    return { success: false, message: err.message || String(err) };
  }
  harCapture = { entries: new Map(), startedAt: Date.now() };
  dbg.on('message', harDebuggerListener);
  dbg.once('detach', () => {
    // Something else took the CDP session (or the window died) — don't leave
    // the renderer thinking a capture is still running with no way to stop it.
    harCapture = null;
  });
  return { success: true };
});

ipcMain.handle('har-capture-stop', async () => {
  if (!harCapture) return { success: false, message: 'No capture running' };
  const capture = harCapture;
  harCapture = null;
  try {
    if (mainWindow && !mainWindow.isDestroyed()) {
      const dbg = mainWindow.webContents.debugger;
      dbg.removeListener('message', harDebuggerListener);
      // perf-capture-* below shares this same CDP session — only let go of it
      // if that capture isn't also relying on it right now.
      if (dbg.isAttached() && !perfCapture) dbg.detach();
    }
  } catch (err) {
    console.error('har-capture-stop: debugger detach failed:', err);
  }

  const har = buildHarLog(capture);
  const count = har.log.entries.length;
  if (count === 0) return { success: true, empty: true, count: 0 };

  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const filename = `capture-${stamp}.har`;
  try {
    mkdirSync(HAR_CAPTURE_DIR, { recursive: true });
    writeFileSync(join(HAR_CAPTURE_DIR, filename), JSON.stringify(har));
  } catch (err) {
    return { success: false, message: err.message || String(err) };
  }
  return { success: true, filename, count };
});

ipcMain.handle('har-capture-status', () => ({
  running: !!harCapture,
  startedAt: harCapture ? harCapture.startedAt : null,
}));

/**
 * Performance capture, for Settings.jsx's Debug section. Same motivation as
 * the HAR capture above (no keyboard on the kiosk to drive DevTools) but for
 * a different question: "is something leaking over hours of normal use?" —
 * suspected after a field report of GPU usage climbing back up over a few
 * hours of playback after every OTA-triggered restart (which resets it).
 *
 * Samples once a minute for as long as it runs (meant to be left recording
 * across hours, unattended) and appends one JSON line per sample rather than
 * building the whole thing in memory + writing once at the end like the HAR
 * capture does — a multi-hour capture that's still running when the renderer
 * eventually OOMs (see recoverRenderer's own doc comment above) would
 * otherwise lose everything.
 *
 * Two data sources per sample:
 *  - app.getAppMetrics() — Electron/Chromium's own per-process CPU+memory
 *    breakdown (browser, renderer, gpu, utility). Doesn't need the debugger
 *    at all, so it keeps working even across a renderer crash/reload.
 *  - CDP Performance.getMetrics() — renderer-side detail (DOM node count,
 *    JS event listener count, JS heap) the app-metrics view above can't see.
 *    Shares the same debugger session as HAR capture (see the detach guards
 *    on both sides); if the renderer dies mid-capture this domain has to be
 *    re-enabled after the reload, see did-finish-load below.
 */
let perfCapture = null; // { startedAt, filePath, intervalId, sampleCount } | null

function perfMetricsFromAppMetrics() {
  try {
    return app.getAppMetrics().map((m) => ({
      type: m.type,
      pid: m.pid,
      cpuPct: m.cpu ? m.cpu.percentCPUUsage : null,
      workingSetKb: m.memory ? m.memory.workingSetSize : null,
    }));
  } catch (err) {
    return { error: err.message || String(err) };
  }
}

async function samplePerfCapture() {
  if (!perfCapture) return;
  const sample = { ts: new Date().toISOString(), appMetrics: perfMetricsFromAppMetrics() };
  try {
    if (mainWindow && !mainWindow.isDestroyed()) {
      const dbg = mainWindow.webContents.debugger;
      if (dbg.isAttached()) {
        const { metrics } = await dbg.sendCommand('Performance.getMetrics');
        sample.domMetrics = Object.fromEntries((metrics || []).map((m) => [m.name, m.value]));
        // window.__hifiPerfState (LyrionServer.jsx) — which screen/state this
        // sample's numbers belong to, so a multi-hour capture is legible
        // afterwards without having to remember what was on screen when.
        const { result } = await dbg.sendCommand('Runtime.evaluate', {
          expression: 'JSON.stringify(window.__hifiPerfState || null)',
          returnByValue: true,
        });
        if (result && typeof result.value === 'string') {
          try { sample.uiState = JSON.parse(result.value); } catch (_) {}
        }
      }
    }
  } catch (err) {
    sample.domMetricsError = err.message || String(err);
  }
  if (!perfCapture) return; // capture may have been stopped while awaiting above
  perfCapture.sampleCount += 1;
  try {
    appendFileSync(perfCapture.filePath, JSON.stringify(sample) + '\n');
  } catch (err) {
    console.error('perf-capture: write failed:', err);
  }
}

ipcMain.handle('perf-capture-start', async () => {
  if (perfCapture) return { success: false, message: 'Capture already running' };
  if (!mainWindow || mainWindow.isDestroyed()) return { success: false, message: 'No window' };
  const dbg = mainWindow.webContents.debugger;
  try {
    if (!dbg.isAttached()) dbg.attach('1.3');
    await dbg.sendCommand('Performance.enable');
  } catch (err) {
    return { success: false, message: err.message || String(err) };
  }
  mkdirSync(PERF_CAPTURE_DIR, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const filePath = join(PERF_CAPTURE_DIR, `perf-${stamp}.jsonl`);
  perfCapture = { startedAt: Date.now(), filePath, sampleCount: 0 };
  perfCapture.intervalId = setInterval(samplePerfCapture, 60000);
  samplePerfCapture(); // first sample immediately, don't wait a full minute
  dbg.once('detach', () => {
    if (perfCapture) console.error('perf-capture: CDP session detached unexpectedly (devtools opened elsewhere?)');
  });
  return { success: true };
});

ipcMain.handle('perf-capture-stop', async () => {
  if (!perfCapture) return { success: false, message: 'No capture running' };
  const { filePath, sampleCount, intervalId } = perfCapture;
  clearInterval(intervalId);
  perfCapture = null;
  try {
    if (mainWindow && !mainWindow.isDestroyed()) {
      const dbg = mainWindow.webContents.debugger;
      // HAR capture above shares this same CDP session — only let go of it
      // if that capture isn't also relying on it right now.
      if (dbg.isAttached() && !harCapture) dbg.detach();
    }
  } catch (err) {
    console.error('perf-capture-stop: debugger detach failed:', err);
  }
  if (sampleCount === 0) return { success: true, empty: true, sampleCount: 0 };
  return { success: true, filename: filePath.split(/[\\/]/).pop(), sampleCount };
});

ipcMain.handle('perf-capture-status', () => ({
  running: !!perfCapture,
  startedAt: perfCapture ? perfCapture.startedAt : null,
  sampleCount: perfCapture ? perfCapture.sampleCount : 0,
}));
