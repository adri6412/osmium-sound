<script setup>
import { ref, onMounted } from 'vue';
import { api } from '../api.js';
import { useI18n } from '../i18n';

const { t } = useI18n();
const host = location.hostname;
const info = ref({});
const net = ref({});
const mode = ref('');
const stats = ref({});

onMounted(async () => {
  const s = await api.sys('info');
  if (s.ok) info.value = s.data;
  // network_status has the real LAN IP (system_info.local_ip can resolve to
  // 127.0.1.1 via /etc/hosts on Debian).
  const n = await api.sys('network_status');
  if (n.ok) net.value = n.data;
  const m = await api.sys('display_mode');
  if (m.ok) mode.value = m.data.mode;
  const st = await api.sys('stats');
  if (st.ok) stats.value = st.data;
});
</script>

<template>
  <h2 class="page">{{ t('dashboard.title') }}</h2>
  <div class="grid">
    <a class="tile" :href="`http://${host}:9000`" target="_blank">
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
    <div class="between item" v-if="stats.gpu_percent != null"><span class="muted">{{ t('dashboard.gpu') }}</span>
      <span class="silver">{{ stats.gpu_percent }}%</span>
    </div>
  </div>
</template>
