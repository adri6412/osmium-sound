import { createApp } from 'vue';
import { createRouter, createWebHashHistory } from 'vue-router';
import App from './App.vue';
import Login from './views/Login.vue';
import Dashboard from './views/Dashboard.vue';
import Settings from './views/Settings.vue';
import Setup from './views/Setup.vue';
import Install from './views/Install.vue';
import { api } from './api.js';
import './style.css';

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: Dashboard, meta: { auth: true } },
    { path: '/login', component: Login },
    { path: '/setup', component: Setup },
    { path: '/install', component: Install },
    { path: '/settings', component: Settings, meta: { auth: true } },
  ],
});

// Route guard: send unauthenticated users to login (or setup if there's no
// account yet, or the captive setup flow if the box is still provisioning).
router.beforeEach(async (to) => {
  if (!to.meta.auth) return true;
  const { ok, data } = await api.authStatus();
  // Couldn't ask the server (daemon restarting, network blip): assume NOT
  // authenticated and show the login form. Without this the checks below read
  // `undefined` and `!data.has_account` sends the visitor into the pre-auth
  // setup wizard instead.
  if (!ok) return '/login';
  // Sessione live avviata per installare: qui non c'è un sistema da
  // amministrare, c'è un disco da preparare. Senza questo il browser che
  // seguiva il QR dell'installer finiva sul modulo di accesso di un
  // apparecchio che non esiste ancora.
  if (data.installer) return to.path === '/install' ? true : '/install';
  if (data.logged_in) return true;
  if (!data.has_account || data.provisioning) return '/setup';
  return '/login';
});

createApp(App).use(router).mount('#app');
