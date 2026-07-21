import { createApp } from 'vue';
import { createRouter, createWebHashHistory } from 'vue-router';
import App from './App.vue';
import Login from './views/Login.vue';
import Dashboard from './views/Dashboard.vue';
import Settings from './views/Settings.vue';
import Setup from './views/Setup.vue';
import { api } from './api.js';
import './style.css';

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: Dashboard, meta: { auth: true } },
    { path: '/login', component: Login },
    { path: '/setup', component: Setup },
    { path: '/settings', component: Settings, meta: { auth: true } },
  ],
});

// Route guard: send unauthenticated users to login (or setup if there's no
// account yet, or the captive setup flow if the box is still provisioning).
router.beforeEach(async (to) => {
  if (!to.meta.auth) return true;
  const { data } = await api.authStatus();
  if (data.logged_in) return true;
  if (!data.has_account || data.provisioning) return '/setup';
  return '/login';
});

createApp(App).use(router).mount('#app');
