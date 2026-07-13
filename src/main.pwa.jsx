import React from 'react';
import ReactDOM from 'react-dom/client';
import AppPwa from './AppPwa';
import './index.css';
import './pwa.css';

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
