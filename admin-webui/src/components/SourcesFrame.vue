<script setup>
// The music-sources page lives on the separate :8080 daemon (sources_server.py)
// and is embedded rather than linked: a link sends the user off this SPA with
// no way back except the browser's back button, which is exactly what forum
// feedback flagged during first-time setup. Both Settings and the setup wizard
// mount this component, so the token/language plumbing is written once.
import { ref, watch, onMounted } from 'vue';
import { api } from '../api.js';
import { useI18n } from '../i18n';

defineProps({
  // 74vh suits the Settings page; the setup wizard wants a shorter frame so the
  // "finish setup" button stays reachable without scrolling past the iframe.
  height: { type: String, default: '74vh' },
});

const { t, lang } = useI18n();
const src = ref('');
const err = ref('');

// Mint the pairing token first and mount the frame with ?token= already in the
// src — no redirect/cookie dance inside the iframe (some browsers refuse framed
// redirects; Brave is especially strict). ?lang= makes the embedded page render
// in the same language as the admin UI around it.
async function load() {
  err.value = '';
  src.value = '';
  const r = await api.post('/api/system/pair_token', {});
  if (r.ok && r.data.token) {
    src.value = `/sources-app?token=${encodeURIComponent(r.data.token)}&lang=${encodeURIComponent(lang.value)}`;
  } else {
    err.value = (r.data && r.data.message) || t('settings.sources.openFailed');
  }
}

onMounted(load);
// Re-mount on a language switch: the page is server-rendered per language, so
// it cannot re-translate itself in place.
watch(lang, load);
</script>

<template>
  <div v-if="err" class="msg err">{{ err }}</div>
  <p v-else-if="!src" class="muted">{{ t('settings.sources.opening') }}</p>
  <iframe v-if="src" :src="src" :style="{ height }"
          style="width: 100%; border: 1px solid var(--border); border-radius: 14px; background: #0f0f0f;"></iframe>
</template>
