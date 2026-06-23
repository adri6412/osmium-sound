import { app, BrowserWindow, ipcMain, session, globalShortcut } from 'electron';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

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
  // Remove X-Frame-Options header to allow iframe embedding
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    if (details.responseHeaders) {
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
    console.log('Loading from:', indexPath);
    mainWindow.loadFile(indexPath).catch(err => {
      console.error('Failed to load file:', err);
      // Fallback to a simple HTML page
      mainWindow.loadURL('data:text/html,<html><body><h1>Loading...</h1><p>Please wait...</p></body></html>');
    });
  }

  // Show window when ready
  mainWindow.once('ready-to-show', () => {
    console.log('Window ready to show');
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
    console.log('Web contents finished loading');
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
  // Register Ctrl+Shift+K to toggle simple-keyboard
  const ret = globalShortcut.register('CommandOrControl+Shift+K', () => {
    console.log('Global keyboard shortcut pressed - toggling simple-keyboard');
    if (mainWindow) {
      mainWindow.webContents.send('toggle-simple-keyboard');
    }
  });

  if (!ret) {
    console.log('Registration failed for global shortcut');
  } else {
    console.log('Global shortcut registered: Ctrl+Shift+K');
  }

  // Register additional shortcuts if needed
  const ret2 = globalShortcut.register('CommandOrControl+Shift+J', () => {
    console.log('Alternative keyboard shortcut pressed');
    if (mainWindow) {
      mainWindow.webContents.send('toggle-simple-keyboard');
    }
  });

  if (ret2) {
    console.log('Alternative global shortcut registered: Ctrl+Shift+J');
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
 * Get system information
 */
ipcMain.handle('get-system-info', async () => {
  const os = await import('os');
  return {
    hostname: os.hostname(),
    platform: os.platform(),
    arch: os.arch(),
    version: '1.0.0',
    electronVersion: process.versions.electron
  };
});

/**
 * Get network interfaces with improved detection
 */
ipcMain.handle('get-network-info', async () => {
  const os = await import('os');
  const interfaces = os.networkInterfaces();
  const result = [];
  
  console.log('Available network interfaces:', Object.keys(interfaces));
  
  for (const [name, addrs] of Object.entries(interfaces)) {
    console.log(`Processing interface ${name}:`, addrs);
    
    // Skip loopback and internal interfaces
    if (name === 'lo' || name.startsWith('lo:')) {
      console.log(`Skipping loopback interface: ${name}`);
      continue;
    }
    
    const ipv4 = addrs.find(addr => addr.family === 'IPv4' && !addr.internal);
    if (ipv4) {
      console.log(`Found IPv4 address for ${name}:`, ipv4);
      
      // Determine interface type
      let type = 'unknown';
      if (name.startsWith('eth') || name.startsWith('en') || name.includes('Ethernet')) {
        type = 'wired';
      } else if (name.startsWith('wlan') || name.startsWith('wl') || name.includes('Wi-Fi')) {
        type = 'wireless';
      } else if (name.startsWith('usb') || name.includes('USB')) {
        type = 'usb';
      }
      
      result.push({
        name,
        address: ipv4.address,
        netmask: ipv4.netmask,
        type,
        active: true
      });
    } else {
      console.log(`No IPv4 address found for ${name}`);
    }
  }
  
  // Sort by priority: wired first, then wireless, then others
  result.sort((a, b) => {
    const typeOrder = { 'wired': 0, 'wireless': 1, 'usb': 2, 'unknown': 3 };
    return typeOrder[a.type] - typeOrder[b.type];
  });
  
  console.log('Final network interfaces result:', result);
  
  // If no interfaces found, try to get at least one active interface
  if (result.length === 0) {
    console.log('No active interfaces found, checking all interfaces again...');
    for (const [name, addrs] of Object.entries(interfaces)) {
      if (name !== 'lo') {
        const ipv4 = addrs.find(addr => addr.family === 'IPv4');
        if (ipv4) {
          console.log(`Adding interface ${name} with address ${ipv4.address}`);
          result.push({
            name,
            address: ipv4.address,
            netmask: ipv4.netmask,
            type: 'unknown',
            active: true
          });
        }
      }
    }
  }
  
  return result;
});

/**
 * Simple-keyboard control (internal virtual keyboard)
 */
ipcMain.handle('toggle-simple-keyboard', async () => {
  console.log('Toggle simple-keyboard requested');
  return { success: true, message: 'Simple-keyboard toggle requested' };
});

ipcMain.handle('show-simple-keyboard', async () => {
  console.log('Show simple-keyboard requested');
  return { success: true, message: 'Simple-keyboard show requested' };
});

ipcMain.handle('hide-simple-keyboard', async () => {
  console.log('Hide simple-keyboard requested');
  return { success: true, message: 'Simple-keyboard hide requested' };
});

/**
 * Global virtual keyboard control (system keyboards)
 */
ipcMain.handle('show-global-keyboard', async () => {
  console.log('Global keyboard requested');
  try {
    const { exec } = await import('child_process');
    const { promisify } = await import('util');
    const execAsync = promisify(exec);
    
    // Try different virtual keyboard solutions
    const commands = [
      'onboard', // Onboard virtual keyboard
      'florence', // Florence virtual keyboard  
      'xvkbd', // X virtual keyboard
      'matchbox-keyboard' // Matchbox keyboard
    ];
    
    for (const cmd of commands) {
      try {
        await execAsync(`which ${cmd}`);
        console.log(`Found ${cmd}, launching...`);
        execAsync(`${cmd} &`);
        return { success: true, message: `Tastiera virtuale ${cmd} avviata` };
      } catch (e) {
        console.log(`${cmd} not found, trying next...`);
      }
    }
    
    return { success: false, message: 'Nessuna tastiera virtuale di sistema trovata' };
  } catch (error) {
    console.error('Global keyboard error:', error);
    return { success: false, message: error.message };
  }
});

ipcMain.handle('hide-global-keyboard', async () => {
  console.log('Hide global keyboard requested');
  try {
    const { exec } = await import('child_process');
    const { promisify } = await import('util');
    const execAsync = promisify(exec);
    
    // Kill virtual keyboard processes
    await execAsync('pkill -f onboard');
    await execAsync('pkill -f florence');
    await execAsync('pkill -f xvkbd');
    await execAsync('pkill -f matchbox-keyboard');
    
    return { success: true, message: 'Tastiera virtuale chiusa' };
  } catch (error) {
    console.error('Hide keyboard error:', error);
    return { success: false, message: error.message };
  }
});

/**
 * Placeholder for playback control
 */
ipcMain.handle('play-pause', async () => {
  console.log('Play/Pause requested');
  return { success: true };
});

ipcMain.handle('next-track', async () => {
  console.log('Next track requested');
  return { success: true };
});

ipcMain.handle('previous-track', async () => {
  console.log('Previous track requested');
  return { success: true };
});

ipcMain.handle('volume-up', async () => {
  console.log('Volume up requested');
  return { success: true };
});

ipcMain.handle('volume-down', async () => {
  console.log('Volume down requested');
  return { success: true };
});

/**
 * System control functions
 */
ipcMain.handle('system-reboot', async () => {
  console.log('System reboot requested');
  try {
    const { exec } = await import('child_process');
    const { promisify } = await import('util');
    const execAsync = promisify(exec);
    
    // Check if we can run sudo commands
    console.log('Attempting to reboot system...');
    const result = await execAsync('sudo reboot');
    console.log('Reboot command result:', result);
    return { success: true, message: 'Sistema in riavvio...' };
  } catch (error) {
    console.error('Reboot error:', error);
    return { 
      success: false, 
      message: `Errore riavvio: ${error.message}. Assicurati che l'app abbia i privilegi necessari.` 
    };
  }
});

ipcMain.handle('system-shutdown', async () => {
  console.log('System shutdown requested');
  try {
    const { exec } = await import('child_process');
    const { promisify } = await import('util');
    const execAsync = promisify(exec);
    
    // Check if we can run sudo commands
    console.log('Attempting to shutdown system...');
    const result = await execAsync('sudo shutdown -h now');
    console.log('Shutdown command result:', result);
    return { success: true, message: 'Sistema in spegnimento...' };
  } catch (error) {
    console.error('Shutdown error:', error);
    return { 
      success: false, 
      message: `Errore spegnimento: ${error.message}. Assicurati che l'app abbia i privilegi necessari.` 
    };
  }
});

ipcMain.handle('system-update', async () => {
  console.log('System update requested');
  try {
    const { exec } = await import('child_process');
    const { promisify } = await import('util');
    const execAsync = promisify(exec);
    
    console.log('Starting system update...');
    
    // First update package lists
    console.log('Updating package lists...');
    const updateResult = await execAsync('sudo apt-get update');
    console.log('Update result:', updateResult);
    
    // Then upgrade packages
    console.log('Upgrading packages...');
    const upgradeResult = await execAsync('sudo apt-get upgrade -y');
    console.log('Upgrade result:', upgradeResult);
    
    return { 
      success: true, 
      message: 'Sistema aggiornato con successo! Riavvia per applicare le modifiche.' 
    };
  } catch (error) {
    console.error('Update error:', error);
    return { 
      success: false, 
      message: `Errore aggiornamento: ${error.message}. Controlla i log per dettagli.` 
    };
  }
});

/**
 * Network configuration with dynamic interface support
 */
ipcMain.handle('set-network-config', async (event, config) => {
  console.log('Network config:', config);
  try {
    const { exec } = await import('child_process');
    const { promisify } = await import('util');
    const execAsync = promisify(exec);
    
    const interfaceName = config.interface || 'eth0'; // Default to eth0 if not specified
    
    if (config.mode === 'dhcp') {
      // Set to DHCP
      await execAsync(`sudo dhclient ${interfaceName}`);
    } else if (config.mode === 'static') {
      // Set static IP (simplified - in production use /etc/network/interfaces or netplan)
      const commands = [
        `sudo ip addr add ${config.ip}/24 dev ${interfaceName}`,
        `sudo ip route add default via ${config.gateway}`,
        `echo "nameserver ${config.dns}" | sudo tee /etc/resolv.conf`
      ];
      
      for (const cmd of commands) {
        await execAsync(cmd);
      }
    }
    
    return { success: true, message: 'Configurazione di rete applicata' };
  } catch (error) {
    console.error('Network config error:', error);
    return { success: false, message: error.message };
  }
});