// The Library editor: a second page of the web admin's build (library.html,
// served by webui_server on /library) for fixing the music library by hand —
// the tags inside the files and the online credits of the album and artist
// pages. Same origin as the admin, so the session cookie and the CSRF token of
// src/api.js work unchanged; there is no login of its own; a visitor without
// a session goes to the admin's.
import { createApp, watchEffect } from 'vue';
import { createRouter, createWebHashHistory } from 'vue-router';
import LibraryApp from './LibraryApp.vue';
import Home from './views/Home.vue';
import Album from './views/Album.vue';
import Artist from './views/Artist.vue';
import History from './views/History.vue';
import { api } from '../api.js';
import { useI18n } from '../i18n';
import { goToAdmin } from './libraryApi.js';
import '../style.css';
import './library.css';

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: Home },
    { path: '/album/:id(\\d+)', component: Album, props: true },
    { path: '/artist/:id(\\d+)', component: Artist, props: true },
    { path: '/history', component: History },
    { path: '/:rest(.*)*', redirect: '/' },
  ],
  scrollBehavior: (to, from, saved) => saved || { top: 0 },
});

// Same checks as the admin's own guard (src/main.js), except that every
// "not here" answer leaves this page for the admin, which knows what to show:
// the login form, the first-time setup or the installer.
router.beforeEach(async () => {
  const { ok, data } = await api.authStatus();
  if (ok && data.logged_in && !data.installer) return true;
  if (ok && data.installer) goToAdmin('#/install');
  else if (ok && (!data.has_account || data.provisioning)) goToAdmin('#/setup');
  else goToAdmin('#/login');
  return false;
});

const { t, lang } = useI18n();
watchEffect(() => {
  document.title = t('library.pageTitle');
  document.documentElement.lang = lang.value;
});

createApp(LibraryApp).use(router).mount('#app');
