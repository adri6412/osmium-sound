<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { api } from '../api.js';
import { useI18n } from '../i18n';

const { t } = useI18n();
const host = location.hostname;
// LMS link follows the skin choice: Material's page once a skin was chosen
// (Osmium theme pre-selected for new browsers), bare root on legacy devices.
// On a device that follows another server it follows that one instead — see
// the role check in onMounted.
const lmsUrl = ref(`http://${host}:9000`);
const info = ref({});
const net = ref({});
const mode = ref('');
const stats = ref({});
let statsPoll = null;

async function loadStats() {
  const st = await api.sys('stats');
  if (st.ok) stats.value = st.data;
}

onMounted(async () => {
  const s = await api.sys('info');
  if (s.ok) info.value = s.data;
  // network_status has the real LAN IP (system_info.local_ip can resolve to
  // 127.0.1.1 via /etc/hosts on Debian).
  const n = await api.sys('network_status');
  if (n.ok) net.value = n.data;
  const m = await api.sys('display_mode');
  if (m.ok) mode.value = m.data.mode;
  // The music is on whichever server this device actually uses: its own, or
  // the one it follows. Bare root for a followed server — the skin choice
  // only ever applied to this device's own, and /material/ need not exist
  // over there (a server's root serves its own default skin).
  const role = await api.sys('lms_role');
  if (role.ok && role.data.mode === 'follow' && role.data.host) {
    lmsUrl.value = `http://${role.data.host}:9000`;
  } else {
    const sk = await api.sys('lms_skin');
    if (sk.ok && sk.data.skin === 'osmium') lmsUrl.value = `http://${host}:9000/material/?defaultTheme=dark/Osmium`;
    else if (sk.ok && sk.data.skin === 'material') lmsUrl.value = `http://${host}:9000/material/`;
  }
  await loadStats();
  // CPU/RAM/disk/temperature/GPU are live figures -- keep the status card
  // current without requiring a manual page reload.
  statsPoll = setInterval(loadStats, 5000);
});

onUnmounted(() => {
  if (statsPoll) clearInterval(statsPoll);
});

// Busy % and temperature side by side, whichever of the two this hardware
// exposes: an Intel iGPU has no thermal sensor of its own (it shares the CPU
// package one), and a machine without intel_gpu_top/radeontop has no busy %.
const gpu = computed(() => [
  stats.value.gpu_percent != null ? `${stats.value.gpu_percent}%` : null,
  stats.value.gpu_temp_c != null ? `${stats.value.gpu_temp_c}°C` : null,
].filter(Boolean).join(' · '));
</script>

<template>
  <h2 class="page">{{ t('dashboard.title') }}</h2>
  <div class="grid">
    <a class="tile" :href="lmsUrl" target="_blank">
      <span class="t gold">{{ t('dashboard.music') }}</span>
      <span class="muted">{{ t('dashboard.musicDesc') }}</span>
    </a>
    <RouterLink class="tile" to="/settings">
      <span class="t gold">{{ t('dashboard.settings') }}</span>
      <span class="muted">{{ t('dashboard.settingsDesc') }}</span>
    </RouterLink>
  </div>

  <div class="card">
    <h3><span class="dot"></span>{{ t('dashboard.status') }}</h3>
    <div class="between item"><span class="muted">{{ t('dashboard.player') }}</span><span class="silver">{{ info.hostname || '—' }}</span></div>
    <div class="between item"><span class="muted">{{ t('dashboard.network') }}</span>
      <span class="silver">{{ net.type === 'wireless' ? t('dashboard.wifi') : net.type === 'wired' ? t('dashboard.wired') : '—' }}<template v-if="net.ip"> · {{ net.ip }}</template></span>
    </div>
    <div class="between item"><span class="muted">{{ t('dashboard.platform') }}</span><span class="silver">{{ info.platform || '—' }}</span></div>
    <div class="between item"><span class="muted">{{ t('dashboard.displayMode') }}</span>
      <span class="silver">{{ mode === 'headless' ? t('dashboard.headless') : mode === 'gui' ? t('dashboard.onscreen') : '—' }}</span>
    </div>
    <div class="between item"><span class="muted">{{ t('dashboard.cpu') }}</span>
      <span class="silver">{{ stats.cpu_percent != null ? stats.cpu_percent + '%' : '—' }}</span>
    </div>
    <div class="between item"><span class="muted">{{ t('dashboard.ram') }}</span>
      <span class="silver">{{ stats.ram_percent != null ? stats.ram_percent + '%' : '—' }}</span>
    </div>
    <div class="between item"><span class="muted">{{ t('dashboard.disk') }}</span>
      <span class="silver">{{ stats.disk_percent != null ? stats.disk_percent + '%' : '—' }}</span>
    </div>
    <div class="between item"><span class="muted">{{ t('dashboard.temperature') }}</span>
      <span class="silver">{{ stats.temp_c != null ? stats.temp_c + '°C' : '—' }}</span>
    </div>
    <div class="between item" v-if="gpu"><span class="muted">{{ t('dashboard.gpu') }}</span>
      <span class="silver">{{ gpu }}</span>
    </div>
  </div>
</template>
