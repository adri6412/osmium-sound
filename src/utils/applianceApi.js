/**
 * Appliance device-management client (DSP, OTA updates, reboot/shutdown,
 * multiroom role, SSH toggle) — talks to sources_server.py's authenticated
 * `/api/*` proxy on port 8080, which itself relays to api_server.py
 * (loopback-only) for the actual work. This is the same proxy the Android
 * companion app uses via ApplianceHttpClient.java — same routes, same
 * `Authorization: Bearer <pairToken>` scheme. See sources_server.py's
 * _SYSTEM_PROXY_ROUTES table and _require_pair_token().
 *
 * Unlike lyrionApi.js (LMS playback, no auth needed), every route here
 * except /api/dsp/fir and /api/backup|restore requires a pairing token —
 * there is no way to self-mint one from a phone (the mint endpoint is
 * localhost-only); it only ever arrives via scanning the kiosk's QR
 * (see ServerConnect.jsx).
 */

class ApplianceAPI {
  constructor() {
    this.baseUrl = localStorage.getItem('hifiApplianceApiUrl') || '';
  }

  setBaseUrl(url) {
    this.baseUrl = url.replace(/\/$/, '');
    localStorage.setItem('hifiApplianceApiUrl', this.baseUrl);
  }

  getToken() {
    return localStorage.getItem('hifiPairToken') || '';
  }

  isPaired() {
    return !!this.getToken();
  }

  // Falls back to the LMS server's host on the default port 8080 (matches
  // ApplianceHttpClient.java's baseUrl() fallback) when no explicit API
  // address was captured from the pairing QR yet.
  resolveBaseUrl() {
    if (this.baseUrl) return this.baseUrl;
    const lyrionUrl = localStorage.getItem('lyrionUrl') || '';
    try {
      const host = new URL(lyrionUrl).hostname;
      return host ? `http://${host}:8080` : '';
    } catch (_) {
      return '';
    }
  }

  async request(path, { method = 'GET', body } = {}) {
    const base = this.resolveBaseUrl();
    if (!base) throw new Error('No appliance address configured');
    const headers = {};
    const token = this.getToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;
    let fetchBody;
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      fetchBody = JSON.stringify(body);
    }
    const res = await fetch(`${base}${path}`, { method, headers, body: fetchBody });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(data.message || `HTTP ${res.status}`);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  // ── DSP ──────────────────────────────────────────────────────
  dspStatus() { return this.request('/api/dsp/status'); }
  dspSet(config) { return this.request('/api/dsp/set', { method: 'POST', body: config }); }
  firStatus() { return this.request('/api/dsp/fir'); }
  firDelete() { return this.request('/api/dsp/fir', { method: 'DELETE' }); }

  // ── System info / SSH ───────────────────────────────────────
  systemInfo() { return this.request('/api/system/info'); }
  sshStatus() { return this.request('/api/system/ssh'); }
  setSsh(enabled) { return this.request('/api/system/ssh', { method: 'POST', body: { enable: enabled } }); }

  // ── OTA channel + updates (kind: 'app' | 'system' | 'os' | 'lyrion') ──
  otaChannel() { return this.request('/api/system/ota_channel'); }
  setOtaChannel(channel) { return this.request('/api/system/ota_channel', { method: 'POST', body: { channel } }); }
  checkUpdate(kind) { return this.request(`/api/system/updates/${kind}/check`); }
  applyUpdate(kind) { return this.request(`/api/system/updates/${kind}/apply`, { method: 'POST' }); }
  updateStatus(kind) { return this.request(`/api/system/updates/${kind}/status`); }

  // ── Reboot / shutdown ───────────────────────────────────────
  reboot() { return this.request('/api/system/reboot', { method: 'POST' }); }
  shutdown() { return this.request('/api/system/shutdown', { method: 'POST' }); }

  // ── Multiroom (player identity + which LMS this device follows) ────
  playerName() { return this.request('/api/system/player_name'); }
  setPlayerName(name) { return this.request('/api/system/player_name', { method: 'POST', body: { name } }); }
  lmsRole() { return this.request('/api/system/lms_role'); }
  setLmsRole(mode, host) { return this.request('/api/system/lms_role', { method: 'POST', body: { mode, host } }); }
  discoverLms() { return this.request('/api/system/discover_lms'); }
}

export const applianceApi = new ApplianceAPI();
