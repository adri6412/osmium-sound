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
  try {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const result = await response.json();
    return { success: true, data: result };
  } catch (error) {
    console.error(`API POST ${endpoint} error:`, error);
    return { 
      success: false, 
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
  try {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const result = await response.json();
    return { success: true, data: result };
  } catch (error) {
    console.error(`API GET ${endpoint} error:`, error);
    return { 
      success: false, 
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
  update: () => apiPost('/update_system'),
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
  // OTA release channel: { channel: 'prod'|'dev' }
  getOtaChannel: () => apiGet('/ota_channel'),
  // Switch channel. Returns { success, channel }
  setOtaChannel: (channel) => apiPost('/ota_channel', { channel }),
  // List ALSA output devices (DAC): { devices: [{ id, name, card, device }] }
  getAudioDevices: () => apiGet('/audio_devices'),
  // Set squeezelite output device and restart it. Returns { success, message }
  setAudioDevice: (device) => apiPost('/set_audio_device', { device }),

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

  // ── Lyrion Music Server update ──────────────────────────────────
  // Check downloads server: { current, latest, update_available, asset_url }
  checkLyrionUpdate: () => apiGet('/lyrion_update/check'),
  // Start the Lyrion update (download + apt install + restart). { started, version|message }
  applyLyrionUpdate: () => apiPost('/lyrion_update/apply'),
  // Poll Lyrion update progress: { state, progress, version, message }
  getLyrionUpdateStatus: () => apiGet('/lyrion_update/status'),
};