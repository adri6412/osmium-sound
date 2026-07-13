import React from 'react';
import ReactDOM from 'react-dom/client';
import AppPwa from './AppPwa';
import './index.css';
import './pwa.css';

// One-scan QR hand-off: Settings' "iPhone/iPad" QR is a bare URL (not JSON)
// carrying lms/api/token as query params, so the iOS Camera app — a native
// system app, not a web page — opens it straight in Safari with zero regard
// for secure-context/camera-permission concerns. Seed localStorage from
// those params on first load so the PWA boots already paired, then strip
// them from the address bar (the pair token shouldn't linger in history).
// The in-app QR scanner (ServerConnect.jsx) stays as a manual fallback for
// re-pairing later.
function seedFromQueryString() {
  const params = new URLSearchParams(window.location.search);
  const lms = params.get('lms');
  const api = params.get('api');
  const token = params.get('token');

  if (lms) {
    const url = /^https?:\/\//i.test(lms) ? lms : `http://${lms}`;
    localStorage.setItem('lyrionUrl', url.replace(/\/$/, ''));
    localStorage.setItem('hifiPwaServerConfigured', '1');
  }
  if (api) {
    const url = /^https?:\/\//i.test(api) ? api : `http://${api}`;
    localStorage.setItem('hifiApplianceApiUrl', url.replace(/\/$/, ''));
  }
  if (token) {
    localStorage.setItem('hifiPairToken', token);
  }

  if (lms || api || token) {
    params.delete('lms');
    params.delete('api');
    params.delete('token');
    const rest = params.toString();
    const cleanUrl = window.location.pathname + (rest ? `?${rest}` : '');
    window.history.replaceState({}, '', cleanUrl);
  }
}

seedFromQueryString();

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <AppPwa />
  </React.StrictMode>
);

if ('serviceWorker' in navigator) {
  import('virtual:pwa-register')
    .then(({ registerSW }) => registerSW({ immediate: true }))
    .catch(() => {});
}
