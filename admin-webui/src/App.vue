<script setup>
import { RouterView } from 'vue-router';
import { api } from './api.js';
import { useI18n } from './i18n';
import UpdateProgressOverlay from './components/UpdateProgressOverlay.vue';

const { t } = useI18n();

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
    <button class="ghost" @click="logout">{{ t('app.logout') }}</button>
  </div>
  <div class="wrap">
    <RouterView />
  </div>
  <UpdateProgressOverlay />
</template>
