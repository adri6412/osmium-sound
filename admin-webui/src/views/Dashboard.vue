<script setup>
import { ref, onMounted } from 'vue';
import { api } from '../api.js';

const host = location.hostname;
const info = ref({});
const net = ref({});
const mode = ref('');

onMounted(async () => {
  const s = await api.sys('info');
  if (s.ok) info.value = s.data;
  // network_status has the real LAN IP (system_info.local_ip can resolve to
  // 127.0.1.1 via /etc/hosts on Debian).
  const n = await api.sys('network_status');
  if (n.ok) net.value = n.data;
  const m = await api.sys('display_mode');
  if (m.ok) mode.value = m.data.mode;
});
</script>

<template>
  <h2 class="page">Dashboard</h2>
  <div class="grid">
    <a class="tile" :href="`http://${host}:9000`" target="_blank">
      <span class="t gold">Musica</span>
      <span class="muted">Libreria e riproduzione (Lyrion)</span>
    </a>
    <RouterLink class="tile" to="/settings">
      <span class="t gold">Impostazioni</span>
      <span class="muted">Rete, audio, DSP, Bluetooth, aggiornamenti…</span>
    </RouterLink>
  </div>

  <div class="card">
    <h3><span class="dot"></span>Stato</h3>
    <div class="between item"><span class="muted">Player</span><span class="silver">{{ info.hostname || '—' }}</span></div>
    <div class="between item"><span class="muted">Rete</span>
      <span class="silver">{{ net.type === 'wireless' ? 'Wi-Fi' : net.type === 'wired' ? 'Cavo' : '—' }}<template v-if="net.ip"> · {{ net.ip }}</template></span>
    </div>
    <div class="between item"><span class="muted">Piattaforma</span><span class="silver">{{ info.platform || '—' }}</span></div>
    <div class="between item"><span class="muted">Modalità schermo</span>
      <span class="silver">{{ mode === 'headless' ? 'Headless' : mode === 'gui' ? 'Su schermo' : '—' }}</span>
    </div>
  </div>
</template>
