<script setup>
import { RouterView, useRouter } from 'vue-router';
import { api } from './api.js';
const router = useRouter();
async function logout() {
  await api.logout();
  router.push('/login');
}
</script>

<template>
  <div class="topbar">
    <div class="brand">OSMIUM <span class="gold">SOUND</span></div>
    <button class="ghost" @click="logout">Esci</button>
  </div>
  <div class="wrap">
    <RouterView />
  </div>
</template>
