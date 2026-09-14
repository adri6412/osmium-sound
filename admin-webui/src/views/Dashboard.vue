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
// GB as the owner reads them: one decimal only where whole numbers would
// lie (a nearly full disk rounding to "0 GB"), TB past a thousand. Mirrors
// SourcesPanel's fmtBytes, but the stats endpoint already reports GB.
function fmtGb(gb) {
  const n = Number(gb);
  if (!Number.isFinite(n) || n < 0) return '—';
  if (n >= 1000) return (n / 1024).toFixed(1) + ' TB';
  return n >= 10 ? Math.round(n) + ' GB' : n.toFixed(1) + ' GB';
}

// "How much room do I have", as one table whose rows add up to the disk:
// what the system took for itself (boot partition + the two image slots —
// space the owner can never fill with music), what is already used in the
// data partition, and what is still free. Used is total minus free, so the
// filesystem's own reserve lands there and the rows really do add up. On a
// legacy install the system and the music share one filesystem:
// disk_system_gb comes back null and the table has two rows over that
// filesystem instead of inventing a split.
const disk = computed(() => {
  const st = stats.value;
  if (st.disk_free_gb == null || st.disk_total_gb == null) return null;
  const split = st.disk_system_gb != null && st.disk_device_gb != null;
  const total = split ? st.disk_device_gb : st.disk_total_gb;
  if (!(total > 0)) return null;
  const used = Math.max(0, st.disk_total_gb - st.disk_free_gb);
  const rows = [];
  if (split) rows.push({ key: 'system', gb: st.disk_system_gb });
  rows.push({ key: split ? 'used' : 'usedShared', gb: used });
  rows.push({ key: 'free', gb: st.disk_free_gb });
  for (const r of rows) r.pct = Math.min(100, Math.max(0, (r.gb / total) * 100));
  // Whole percentages that still add up to 100 (largest remainder), or the
  // table reads 45 + 12 + 44 = 101%.
  const floors = rows.map((r) => Math.floor(r.pct));
  let left = 100 - floors.reduce((a, b) => a + b, 0);
  rows.map((r, i) => i).sort((a, b) => (rows[b].pct - floors[b]) - (rows[a].pct - floors[a]))
    .forEach((i) => { rows[i].share = floors[i] + (left-- > 0 ? 1 : 0); });
  return { rows, total };
});
const pctLabel = (r) => (r.share === 0 && r.gb > 0 ? '<1%' : r.share + '%');
// In this table the parts carry a decimal, so the total does too (6.6 + 1.7
// + 6.4 is 14.7, not "15"); only past 100 GB are whole numbers exact enough.
function fmtDiskGb(gb) {
  const n = Number(gb);
  return Number.isFinite(n) && n >= 10 && n < 100 ? n.toFixed(1) + ' GB' : fmtGb(n);
}

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
    <div class="between item"><span class="muted">{{ t('dashboard.temperature') }}</span>
      <span class="silver">{{ stats.temp_c != null ? stats.temp_c + '°C' : '—' }}</span>
    </div>
    <div class="between item" v-if="gpu"><span class="muted">{{ t('dashboard.gpu') }}</span>
      <span class="silver">{{ gpu }}</span>
    </div>
  </div>

  <div class="card" v-if="disk">
    <h3><span class="dot"></span>{{ t('dashboard.disk.title') }}</h3>
    <div class="du-bar" role="img" :aria-label="disk.rows.map(r => t('dashboard.disk.' + r.key) + ' ' + fmtDiskGb(r.gb)).join(', ')">
      <span v-for="r in disk.rows" :key="r.key" :class="'du-' + r.key" :style="{ width: r.pct + '%' }"></span>
    </div>
    <div class="du-wrap">
      <table class="du">
        <thead>
          <tr><th></th><th class="num">{{ t('dashboard.disk.space') }}</th><th class="num">{{ t('dashboard.disk.share') }}</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in disk.rows" :key="r.key">
            <td>
              <span class="du-name"><span class="du-swatch" :class="'du-' + r.key"></span>{{ t('dashboard.disk.' + r.key) }}</span>
              <span class="muted du-desc">{{ t('dashboard.disk.' + r.key + 'Desc') }}</span>
            </td>
            <td class="num silver">{{ fmtDiskGb(r.gb) }}</td>
            <td class="num muted">{{ pctLabel(r) }}</td>
          </tr>
        </tbody>
        <tfoot>
          <tr><td>{{ t('dashboard.disk.total') }}</td><td class="num">{{ fmtDiskGb(disk.total) }}</td><td class="num muted">100%</td></tr>
        </tfoot>
      </table>
    </div>
  </div>
</template>
