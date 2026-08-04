/**
 * API utility functions for communicating with the Flask backend
 */

const API_BASE_URL = 'http://localhost:8000';

/**
 * Make a POST request to the API
 * @param {string} endpoint - The API endpoint
 * @param {Object} data - Data to send (optional)
 * @returns {Promise<Object>} - The response data
 */
export const apiPost = async (endpoint, data = {}) => {
  // 0 when the request never reached the API at all (it restarts during an
  // update). Callers use it to tell "endpoint not in this api_server build"
  // (404) apart from a transient blip.
  let status = 0;
  try {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
    });
    status = response.status;

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const result = await response.json();
    return { success: true, status, data: result };
  } catch (error) {
    console.error(`API POST ${endpoint} error:`, error);
    return {
      success: false,
      status,
      error: error.message,
      message: `Errore di connessione: ${error.message}`
    };
  }
};

/**
 * Make a GET request to the API
 * @param {string} endpoint - The API endpoint
 * @returns {Promise<Object>} - The response data
 */
export const apiGet = async (endpoint) => {
  let status = 0;
  try {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });
    status = response.status;

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const result = await response.json();
    return { success: true, status, data: result };
  } catch (error) {
    console.error(`API GET ${endpoint} error:`, error);
    return {
      success: false,
      status,
      error: error.message,
      message: `Errore di connessione: ${error.message}`
    };
  }
};

/**
 * Check if the API server is running
 * @returns {Promise<boolean>} - True if server is running
 */
export const checkApiServer = async () => {
  const result = await apiGet('/check');
  return result.success;
};

/**
 * System control API calls
 */
export const systemAPI = {
  reboot: () => apiPost('/reboot'),
  shutdown: () => apiPost('/shutdown'),
  closeAndRestart: () => apiPost('/close_and_restart'),
  getSystemInfo: () => apiGet('/system_info'),
  getNetworkInfo: () => apiGet('/network_info'),
  configureNetwork: (config) => apiPost('/configure_network', config),
  showGlobalKeyboard: () => apiPost('/show_global_keyboard'),
  hideGlobalKeyboard: () => apiPost('/hide_global_keyboard'),

  // ── First-setup wizard ──────────────────────────────────────────
  // Current active connection: { type: 'wired'|'wireless'|'none', ip, ssid, connected }
  getNetworkStatus: () => apiGet('/network_status'),
  // Scan WiFi: { networks: [{ ssid, signal, security, in_use }] }
  scanWifi: () => apiGet('/wifi_scan'),
  // Connect to a WiFi network (DHCP). Returns { success, message, ip }
  connectWifi: (ssid, password) => apiPost('/wifi_connect', { ssid, password }),
  // Force DHCP on the wired interface. Returns { success, message, ip }
  useWiredDhcp: () => apiPost('/wired_dhcp', {}),
  // SSH server state: { available, enabled, active }
  getSshStatus: () => apiGet('/ssh_status'),
  // Enable/disable the SSH server. Returns { success, enabled, active, message }
  setSsh: (enable) => apiPost('/ssh_set', { enable }),
  // Mouse pointer (cursor) state: { available, enabled }
  getPointerStatus: () => apiGet('/pointer_status'),
  // Show/hide the on-screen mouse pointer. Returns { success, available, enabled, message }
  setPointer: (enable) => apiPost('/pointer_set', { enable }),
  // Display mode: { mode: 'gui'|'headless' }. 'headless' runs the box with no
  // on-screen GUI (control via companion / Lyrion :9000 / sources :8080).
  getDisplayMode: () => apiGet('/display_mode'),
  // Switch GUI <-> headless (live + persisted). In headless the on-screen UI is
  // torn down shortly after this returns. Returns { success, mode, message }
  setDisplayMode: (mode) => apiPost('/display_mode', { mode }),
  // UI render resolution: { mode: 'auto'|'720'|'1080'|'native' }. Shrinks the X
  // framebuffer on big panels (the GPU upscales it during scanout) so Chromium
  // stops rasterizing 2..8 Mpixel per repaint.
  getUiResolution: () => apiGet('/ui_resolution'),
  // Change it (persisted). The graphical session restarts shortly after this
  // returns, so this UI goes away and comes back. Returns { success, mode, message }
  setUiResolution: (mode) => apiPost('/ui_resolution', { mode }),
  // First-boot provisioning status (proxied from webui_server): { pending,
  // stage, mode, claimed_by, ap: { active, ssid, psk }, ... }
  getProvisionStatus: () => apiGet('/provision_status'),
  // Claim the display mode during provisioning (first writer wins). source is
  // 'screen' from the kiosk wizard. Returns { success, mode }
  setProvisionMode: (mode, source) => apiPost('/provision_mode', { mode, source }),
  // Factory reset: wipe user settings + web-admin account, re-arm the first-boot
  // setup flow, reboot. Returns { success, message }
  factoryReset: () => apiPost('/factory_reset'),
  // Wipe only the web-admin account (kiosk recovery when the web password is
  // forgotten). Returns { success, message }
  resetWebuiCredentials: () => apiPost('/webui_reset_credentials'),
  // OTA release channel: { channel: 'prod'|'dev' }
  getOtaChannel: () => apiGet('/ota_channel'),
  // Switch channel. Returns { success, channel }
  setOtaChannel: (channel) => apiPost('/ota_channel', { channel }),
  // List ALSA output devices (DAC): { devices: [{ id, name, card, device }] }
  getAudioDevices: () => apiGet('/audio_devices'),
  // Set squeezelite output device and restart it. Returns { success, message }
  setAudioDevice: (device) => apiPost('/set_audio_device', { device }),
  // Which Lyrion server this device's squeezelite points at: { mode: 'local'|'follow', host: string|null }
  getLmsRole: () => apiGet('/lms_role'),
  // Point squeezelite at its own local Lyrion server ('local') or another
  // device's LMS on the LAN ('follow', host required, IPv4). Restarts
  // squeezelite. Returns { success, host, message }
  setLmsRole: (mode, host) => apiPost('/lms_role', { mode, host }),
  // This device's squeezelite display name (default "OsmiumSound"). Returns { name }
  getPlayerName: () => apiGet('/player_name'),
  // Rename this device's player and restart squeezelite. Returns { success, name, message }
  setPlayerName: (name) => apiPost('/player_name', { name }),
  // Broadcast-discover other Lyrion/LMS servers on the LAN (no IP typing needed).
  // Returns { servers: [{ ip, name, port }] }
  discoverLmsServers: () => apiGet('/discover_lms'),
  // Tidal Connect daemon state: { available, enabled, active }
  getTidalStatus: () => apiGet('/tidal_status'),
  // Enable/disable the Tidal Connect daemon. Returns { success, enabled, active, message }
  setTidal: (enable) => apiPost('/tidal_set', { enable }),

  // Currently-streaming Bluetooth track (AVRCP metadata + online cover lookup):
  // { active, title, artist, album, duration, position, device_name, cover_url }
  getBluetoothNowPlaying: () => apiGet('/bluetooth_now_playing'),
  // DSP/EQ engine state: { available, enabled, bands, crossfeed }
  getDspStatus: () => apiGet('/dsp_status'),
  // Apply DSP settings. Returns { success, enabled, message }
  setDsp: (config) => apiPost('/dsp_set', config),
  // DSP presets: { presets: [{name, builtin, active, bands, crossfeed, room_correction, balance}], active }
  getDspPresets: () => apiGet('/dsp_presets'),
  saveDspPreset: (name) => apiPost('/dsp_preset_save', { name }),
  loadDspPreset: (name) => apiPost('/dsp_preset_load', { name }),
  deleteDspPreset: (name) => apiPost('/dsp_preset_delete', { name }),

  // ── OTA update of the Electron UI ───────────────────────────────
  // Check GitHub Releases: { current, latest, update_available, notes, asset_url, asset_size }
  checkAppUpdate: () => apiGet('/app_update/check'),
  // Start the OTA update (download + swap + restart). Returns { started, version|message }
  applyAppUpdate: () => apiPost('/app_update/apply'),
  // Poll OTA progress: { state, progress, version, message }
  getAppUpdateStatus: () => apiGet('/app_update/status'),

  // ── OTA update of the custom system components (API/daemons/units) ──
  // Check GitHub Releases for the hifi-system bundle: { current, latest, update_available, ... }
  checkSystemUpdate: () => apiGet('/system_update/check'),
  // Start the system update (download + install files + restart services). { started, version|message }
  applySystemUpdate: () => apiPost('/system_update/apply'),
  // Poll system update progress: { state, progress, version, message }
  getSystemUpdateStatus: () => apiGet('/system_update/status'),

  // ── OTA update of the operating system (signed bundle + apply.sh) ──
  // Check GitHub Releases for the hifi-os bundle: { current, latest, update_available, ... }
  checkOsUpdate: () => apiGet('/os_update/check'),
  // Start the OS update (verify signature + checksum → run apply.sh as root). { started, version|message }
  applyOsUpdate: () => apiPost('/os_update/apply'),
  // Poll OS update progress: { state, progress, version, message }
  getOsUpdateStatus: () => apiGet('/os_update/status'),

  // ── Sequenced multi-component update ────────────────────────────
  // Applies every component that has an update, in the order the appliance
  // knows is safe (system → os → ui), driven entirely on the device by
  // hifi-update-runner.sh from a plan persisted under /var/lib. Preferred over
  // chaining the three apply calls from here: this page is torn down by the UI
  // step (lightdm restart) and by an OS payload that reboots, which used to
  // abandon the rest of the sequence.
  // { started, plan_id, steps: [{kind, version}] } | { started: false, message }
  applyAllUpdates: () => apiPost('/update/apply_all'),
  // { state: idle|running|finished|error|interrupted, kind, version, step_state,
  //   progress, message, overall_progress, steps: [{kind, version, state, installed}] }
  getUpdatePlanStatus: () => apiGet('/update/status'),
  // Drop a finished plan once its outcome has been shown.
  dismissUpdatePlan: () => apiPost('/update/dismiss'),

  // ── Lyrion Music Server install / update ────────────────────────
  // Managed from Settings → Lyrion Music Server, not from the appliance's own
  // update page: Lyrion is third-party software with its own release cadence.
  // Check downloads server:
  //   { current, channel, channels: { release|nightly|dev: {version, url} },
  //     latest, update_available, asset_url }
  checkLyrionUpdate: () => apiGet('/lyrion_update/check'),
  // Start the install/update for a channel (download + apt install + restart).
  // A channel switch is applied even when it is a downgrade. { started, version|message }
  applyLyrionUpdate: (channel) => apiPost('/lyrion_update/apply', channel ? { channel } : {}),
  // Poll Lyrion update progress: { state, progress, version, message }
  getLyrionUpdateStatus: () => apiGet('/lyrion_update/status'),
  // Persisted channel: { channel, channels: [...] }
  getLyrionChannel: () => apiGet('/lyrion_channel'),
  setLyrionChannel: (channel) => apiPost('/lyrion_channel', { channel }),

  // ── Shell (SSH/console) login mirrored from the admin account ───
  // { exists, username, kiosk_password_disabled }
  getShellAccount: () => apiGet('/shell_account'),
  // Create or re-password the Linux login (full sudo). { success, code, message }
  setShellAccount: (username, password) => apiPost('/shell_account', { username, password }),
};