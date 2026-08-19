// Tiny fetch wrapper for the webui_server.py backend. Same-origin, so the
// session cookie rides along automatically. Mutations carry the double-submit
// CSRF token (read from the non-HttpOnly `csrf` cookie the server sets).

import { useI18n } from './i18n';

const { t, lang } = useI18n();

function csrfToken() {
  const m = document.cookie.match(/(?:^|;\s*)csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : '';
}

async function req(path, { method = 'GET', body } = {}) {
  const headers = {};
  const opts = { method, headers, credentials: 'same-origin' };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  // So api_server/sources_server (behind webui_server's proxy — see _proxy()
  // there) return `message` text in the language the owner actually picked,
  // instead of always Italian.
  headers['X-UI-Lang'] = lang.value;
  if (method !== 'GET') headers['X-CSRF-Token'] = csrfToken();
  let res, data;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    return { ok: false, status: 0, data: { message: t('common.networkError') } };
  }
  try {
    data = await res.json();
  } catch (_) {
    data = {};
  }
  return { ok: res.ok, status: res.status, data };
}

// Lyrion JSON-RPC (per-player prefs: transitions, ReplayGain, fixed volume).
// Proxied through webui_server's /api/lyrion to avoid CORS — see that route's
// comment in webui_server.py. Same request shape as the kiosk's own
// lyrionApi.js (LYRION_BASE there is always this device's local LMS, so this
// only resolves prefs for a local server, same as the proxy).
async function lyrionRequest(playerMac, command) {
  const r = await req('/api/lyrion', { method: 'POST', body: { id: 1, method: 'slim.request', params: [playerMac, command] } });
  return { ok: r.ok, status: r.status, data: r.data && r.data.result };
}

export const api = {
  get: (p) => req(p),
  post: (p, body) => req(p, { method: 'POST', body }),
  del: (p) => req(p, { method: 'DELETE' }),

  lyrionPlayers: async () => {
    const r = await lyrionRequest('', ['serverstatus', 0, 999]);
    return (r.data && r.data.players_loop) || [];
  },
  // Lyrion returns the queried value under `_p2` (and sometimes under the
  // pref name itself) — same fallback as the kiosk's getPlayerPref.
  lyrionGetPref: async (playerMac, pref) => {
    const r = await lyrionRequest(playerMac, ['playerpref', pref, '?']);
    return (r.data && (r.data._p2 ?? r.data[pref])) ?? null;
  },
  lyrionSetPref: (playerMac, pref, value) => lyrionRequest(playerMac, ['playerpref', pref, value]),

  // auth
  authStatus: () => req('/api/auth/status'),
  setup: (username, password) => req('/api/auth/setup', { method: 'POST', body: { username, password } }),
  login: (username, password) => req('/api/auth/login', { method: 'POST', body: { username, password } }),
  logout: () => req('/api/auth/logout', { method: 'POST' }),
  changePassword: (username, current_password, new_password) =>
    req('/api/auth/change-password', { method: 'POST', body: { username, current_password, new_password } }),

  // provisioning
  provisionStatus: () => req('/api/provision/status'),
  provisionWifiConnect: (ssid, password) =>
    req('/api/provision/wifi_connect', { method: 'POST', body: { ssid, password } }),
  provisionClaimMode: (mode) =>
    req('/api/provision/claim_mode', { method: 'POST', body: { mode, source: 'web' } }),
  provisionFinalize: () => req('/api/provision/finalize', { method: 'POST' }),

  // system (proxied to api_server through webui_server)
  sys: (p) => req('/api/system/' + p),
  sysPost: (p, body) => req('/api/system/' + p, { method: 'POST', body }),

  // DSP room-correction filter (FIR) — file lives on sources_server, forwarded
  // raw through webui_server; upload takes multipart/form-data.
  dspFirStatus: () => req('/api/system/dsp_fir'),
  dspFirUpload: async (file) => {
    const body = new FormData();
    body.append('file', file);
    const headers = { 'X-CSRF-Token': csrfToken() };
    let res, data;
    try {
      res = await fetch('/api/system/dsp_fir', { method: 'POST', body, headers, credentials: 'same-origin' });
    } catch (e) {
      return { ok: false, status: 0, data: { message: t('common.networkError') } };
    }
    try { data = await res.json(); } catch (_) { data = {}; }
    return { ok: res.ok, status: res.status, data };
  },
  dspFirRemove: () => req('/api/system/dsp_fir', { method: 'DELETE' }),

  // Backup/restore — files live on sources_server.py, forwarded raw through
  // webui_server (session-gated: see /api/system/backup* in webui_server.py).
  backupList: () => req('/api/system/backup/list'),
  backupStatus: () => req('/api/system/backup/status'),
  backupSettings: () => req('/api/system/backup/settings'),
  backupSettingsSave: (settings) => req('/api/system/backup/settings', { method: 'POST', body: settings }),
  backupCreate: (passphrase, categories) =>
    req('/api/system/backup/create', { method: 'POST', body: { passphrase, categories } }),
  backupDelete: (id) => req('/api/system/backup/' + id, { method: 'DELETE' }),
  backupRestore: (id, passphrase, categories) =>
    req('/api/system/backup/' + id + '/restore', { method: 'POST', body: { passphrase, categories } }),
  backupDownloadUrl: (id) => (id ? '/api/system/backup/' + id : '/api/system/backup'),
  restoreStatus: () => req('/api/system/restore/status'),
  restoreUpload: async (file, passphrase, categories) => {
    const body = new FormData();
    body.append('file', file);
    if (passphrase) body.append('passphrase', passphrase);
    if (categories) body.append('categories', categories.join(','));
    const headers = { 'X-CSRF-Token': csrfToken() };
    let res, data;
    try {
      res = await fetch('/api/system/restore', { method: 'POST', body, headers, credentials: 'same-origin' });
    } catch (e) {
      return { ok: false, status: 0, data: { message: t('common.networkError') } };
    }
    try { data = await res.json(); } catch (_) { data = {}; }
    return { ok: res.ok, status: res.status, data };
  },

  // Music sources — live on sources_server.py, forwarded raw through
  // webui_server (session-gated: see /api/system/sources|usb|internal|apply
  // in webui_server.py). Powers SourcesPanel.vue.
  sourcesList: () => req('/api/system/sources'),
  sourcesAddLocal: (path) => req('/api/system/sources/local', { method: 'POST', body: { path } }),
  sourcesAddSmb: ({ server, share, username, password, rw }) =>
    req('/api/system/sources/smb', { method: 'POST', body: { server, share, username, password, rw } }),
  sourcesSetRw: (id, rw) => req('/api/system/sources/' + id + '/rw', { method: 'POST', body: { rw } }),
  sourcesSetSubpath: (id, subpath) => req('/api/system/sources/' + id + '/subpath', { method: 'POST', body: { subpath } }),
  sourcesBrowse: (id, path = '') => req('/api/system/sources/' + id + '/browse?path=' + encodeURIComponent(path)),
  sourcesRemove: (id) => req('/api/system/sources/' + id, { method: 'DELETE' }),
  sourcesApply: () => req('/api/system/apply', { method: 'POST' }),
  usbList: () => req('/api/system/usb'),
  usbAdopt: (device) => req('/api/system/usb/adopt', { method: 'POST', body: { device } }),
  internalDisks: () => req('/api/system/internal/disks'),
  internalAdopt: (device) => req('/api/system/internal/adopt', { method: 'POST', body: { device } }),
  internalFormat: ({ device, fs, label, confirm }) =>
    req('/api/system/internal/format', { method: 'POST', body: { device, fs, label, confirm } }),
  internalFormatStatus: () => req('/api/system/internal/format/status'),
  internalSmb: () => req('/api/system/internal/smb'),
  internalSmbRegenerate: () => req('/api/system/internal/smb/regenerate', { method: 'POST' }),
};
