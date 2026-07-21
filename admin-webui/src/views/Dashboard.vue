<script setup>
import { ref, onMounted } from 'vue';
import { api } from '../api.js';

const host = location.hostname;
const info = ref({});
const mode = ref('');

onMounted(async () => {
  const s = await api.sys('info');
  if (s.ok) info.value = s.data;
  const m = await api.sys('display_mode');
  if (m.ok) mode.value = m.data.mode;
});
</script>

<template>
  <div class="grid">
    <a class="tile" :href="`http://${host}:9000`" target="_blank">
      <span class="t">Music</span>
      <span class="muted">Library &amp; playback (Lyrion)</span>
    </a>
    <RouterLink class="tile" to="/settings">
      <span class="t">Settings</span>
      <span class="muted">Network, audio, updates, account…</span>
    </RouterLink>
    <a class="tile" :href="`http://${host}:8080`" target="_blank">
      <span class="t">Music sources</span>
      <span class="muted">Add folders &amp; network shares</span>
    </a>
  </div>

  <div class="card">
    <h3>Status</h3>
    <div class="between"><span class="muted">Player</span><span>{{ info.hostname || '—' }}</span></div>
    <div class="between"><span class="muted">IP</span><span>{{ info.local_ip || '—' }}</span></div>
    <div class="between"><span class="muted">Platform</span><span>{{ info.platform || '—' }}</span></div>
    <div class="between"><span class="muted">Display mode</span><span>{{ mode || '—' }}</span></div>
  </div>
</template>
