<script setup>
import { RouterView, RouterLink, useRoute } from 'vue-router';
import { computed } from 'vue';
import { api } from '../api.js';
import { useI18n } from '../i18n';
import Icon from '../components/Icon.vue';
import LanguageSelector from '../components/LanguageSelector.vue';
import { goToAdmin } from './libraryApi.js';

const { t } = useI18n();
const route = useRoute();
const onHistory = computed(() => route.path === '/history');

async function logout() {
  await api.logout();
  // A hard page change, like the admin's own logout: nothing of this page
  // (polling timers, unsaved edits) survives on a session that is gone.
  goToAdmin('#/login');
}
</script>

<template>
  <div class="topbar lb-topbar">
    <RouterLink to="/" class="lb-brand">
      <span class="brand">OSMIUM <span class="gold">SOUND</span></span>
      <span class="lb-brand-sub">{{ t('library.title') }}</span>
    </RouterLink>
    <nav class="lb-nav">
      <RouterLink to="/history" class="lb-navlink" :class="{ on: onHistory }" :title="t('library.nav.history')">
        <Icon name="history" :size="17" /><span class="t">{{ t('library.nav.history') }}</span>
      </RouterLink>
      <a href="./#/" class="lb-navlink" :title="t('library.nav.admin')">
        <Icon name="settings" :size="17" /><span class="t">{{ t('library.nav.admin') }}</span>
      </a>
      <button class="ghost lb-logout" @click="logout" :title="t('app.logout')">
        <Icon name="log-out" :size="16" /><span class="t">{{ t('app.logout') }}</span>
      </button>
    </nav>
  </div>
  <div class="wrap lb-wrap">
    <RouterView />
    <div class="lb-foot">
      <LanguageSelector variant="compact" />
    </div>
  </div>
</template>
