<script setup>
import { computed } from 'vue';
import { RouterView, useRoute } from 'vue-router';
import { api } from './api.js';
import { useI18n } from './i18n';
import UpdateProgressOverlay from './components/UpdateProgressOverlay.vue';
import kofiLogo from './assets/kofi.png';

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
      <!-- The only place a person who already uses the appliance is reminded
           that the project can be supported. The link goes through the site so
           that opening it can be counted. On a phone the label goes, the cup stays. -->
      <a v-if="showLibrary" class="topbar-link topbar-kofi" href="https://osmiumsound.it/kofi?from=admin"
         target="_blank" rel="noopener" :title="t('app.support')">
        <img :src="kofiLogo" alt="Ko-fi" width="24" height="19">
        <span>{{ t('app.support') }}</span>
      </a>
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

<style>
.topbar-kofi {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 8px 12px 8px 10px;
  background: rgba(255, 255, 255, 0.04);
}
.topbar-kofi img { width: 24px; height: auto; display: block; }
@media (max-width: 420px) {
  .topbar-kofi { padding: 8px; }
  .topbar-kofi span { display: none; }
}
</style>
