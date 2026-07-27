<script setup>
import { RouterView, useRouter } from 'vue-router';
import { api } from './api.js';
import { useI18n } from './i18n';

const router = useRouter();
const { t } = useI18n();

async function logout() {
  await api.logout();
  router.push('/login');
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
</template>
