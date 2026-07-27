// Tiny fetch wrapper for the webui_server.py backend. Same-origin, so the
// session cookie rides along automatically. Mutations carry the double-submit
// CSRF token (read from the non-HttpOnly `csrf` cookie the server sets).

import { useI18n } from './i18n';

const { t } = useI18n();

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

export const api = {
  get: (p) => req(p),
  post: (p, body) => req(p, { method: 'POST', body }),

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
};
