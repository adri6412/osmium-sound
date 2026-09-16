<script setup>
import { computed } from 'vue';
import { RouterView, useRoute } from 'vue-router';
import { api } from './api.js';
import { useI18n } from './i18n';
import UpdateProgressOverlay from './components/UpdateProgressOverlay.vue';

const { t } = useI18n();
const route = useRoute();
// Only once inside the admin: not on the login form, the first-time setup or
// the installer, where there is no library to fix yet.
const showLibrary = computed(() => !!route.meta.auth);

async function logout() {
  await api.logout();
  // Hard reload instead of router.push: a client-side route change leaves the
  // whole app instance (and its polling timers) alive on a session that no
  // longer exists, and leaves whatever the browser cached for this page in
  // place. Reloading on /login rebuilds everything from a clean, logged-out
  // state and re-asks the server who we are.
  window.location.hash = '#/login';
  window.location.reload();
}
</script>

<template>
  <div class="topbar">
    <div class="brand">OSMIUM <span class="gold">SOUND</span></div>
    <div class="topbar-actions">
      <!-- The Library editor is a page of its own next to this one (library.html,
           /library on the same origin and session), so a plain link. -->
      <a v-if="showLibrary" class="topbar-link" href="library">{{ t('app.library') }}</a>
      <button class="ghost" @click="logout">{{ t('app.logout') }}</button>
    </div>
  </div>
  <div class="wrap">
    <RouterView />
  </div>
  <UpdateProgressOverlay />
</template>
