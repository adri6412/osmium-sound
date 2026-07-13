import React from 'react';
import ReactDOM from 'react-dom/client';
import AppPwa from './AppPwa';
import './index.css';
import './pwa.css';

// One-scan QR hand-off: Settings' "iPhone/iPad" QR is a bare URL (not JSON)
// carrying lms/api/token as query params, so the iOS Camera app — a native
// system app, not a web page — opens it straight in Safari with zero regard
// for secure-context/camera-permission concerns. Seed localStorage from
// those params on every load (not just the first).
//
// Deliberately does NOT strip the params from the URL afterwards. iOS "Add
// to Home Screen" bookmarks whatever URL is in the bar at that moment, and a
// standalone Home Screen web app gets its OWN localStorage container,
// separate from the Safari tab it was installed from — anything written
// only to Safari's localStorage during the initial scan is invisible to the
// installed app, which looked like "everything lost, token included" on
// first launch from the icon. Keeping lms/api/token in the bookmarked URL
// means every standalone launch re-seeds localStorage from the URL itself,
// which also self-heals if iOS ever clears storage (e.g. its 7-day
// no-interaction purge). No address bar is shown in standalone display
// mode, so this isn't a history/visibility concern there; a regular Safari
// tab does show it briefly, which is an acceptable trade-off for a LAN-only,
// physical-access-gated token.
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
