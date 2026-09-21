<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { api } from '../api.js';
import { useI18n } from '../i18n';
import Toggle from '../components/Toggle.vue';

const { t, lang } = useI18n();
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

// The music server's library: counts and last scan from Lyrion itself
// (`info total`, `serverstatus`), a refresh on demand (`rescan`). Read with
// the stats, so a scan started here — or from the kiosk — shows its progress.
const lib = ref({ albums: null, artists: null, songs: null, duration: 0, lastScan: 0, scanning: false, progress: '', pct: -1, ok: false, busy: false });

async function loadLibrary() {
  const ss = await api.lyrionQuery(['serverstatus', 0, 0]);
  if (!ss.ok || !ss.data) { lib.value = { ...lib.value, ok: false }; return; }
  const d = ss.data;
  const total = Number(d.progresstotal || 0);
  const scanning = Number(d.rescan || 0) !== 0;
  const next = {
    ...lib.value, ok: true, lastScan: Number(d.lastscan || 0), scanning,
    progress: scanning && d.progressname ? String(d.progressname) : '',
    pct: scanning && total > 0 ? Math.min(100, Math.round((100 * Number(d.progressdone || 0)) / total)) : -1,
  };
  for (const e of ['albums', 'artists', 'songs', 'duration']) {
    const r = await api.lyrionQuery(['info', 'total', e, '?']);
    if (r.ok && r.data && r.data['_' + e] !== undefined) next[e] = Number(r.data['_' + e]);
  }
  lib.value = next;
}

async function rescan() {
  lib.value = { ...lib.value, busy: true };
  await api.lyrionQuery(['rescan']);
  lib.value = { ...lib.value, busy: false, scanning: true, pct: -1, progress: '' };
  setTimeout(loadLibrary, 1500);
}

async function abortScan() {
  await api.lyrionQuery(['abortscan']);
  setTimeout(loadLibrary, 800);
}

// Album and artist information from the web (hifi_metadata.py behind
// sources_server): the two switches, what is saved on the device and how far
// the background download has got.
const meta = ref(null);
const metaBusy = ref(false);
const metaCleared = ref(false);
const metaWhereError = ref('');

async function loadMeta() {
  const r = await api.get('/api/system/meta/settings');
  meta.value = r.ok && r.data && typeof r.data.online === 'boolean' ? r.data : null;
}

async function setMeta(key, value) {
  metaBusy.value = true;
  const r = await api.post('/api/system/meta/settings', { [key]: value });
  if (r.ok && r.data && typeof r.data.online === 'boolean') meta.value = r.data;
  metaBusy.value = false;
}

// Where the downloaded information is kept. The list comes from the device
// (its own storage first, then every disk mounted on it); picking another one
// carries the archive over rather than downloading it all again, so it can
// take a moment on a big library.
async function setMetaWhere(value) {
  metaBusy.value = true;
  metaWhereError.value = '';
  const r = await api.post('/api/system/meta/settings', { cache_location: value });
  if (r.ok && r.data && typeof r.data.online === 'boolean') meta.value = r.data;
  else metaWhereError.value = (r.data && r.data.message) || t('dashboard.meta.whereFailed');
  metaBusy.value = false;
  if (!r.ok) await loadMeta();
}

function metaPlace(p) {
  const name = { internal: 'placeHere', data: 'placeData', usb: 'placeUsb', network: 'placeNetwork' }[p.kind]
    || 'placeDisk';
  const label = t('dashboard.meta.' + name, { name: p.label });
  if (!p.usable) {
    const why = { network: 'placeNoNetwork', readonly: 'placeReadonly' }[p.reason] || 'placeAway';
    return label + ' — ' + t('dashboard.meta.' + why);
  }
  return p.total ? label + ' — ' + t('dashboard.meta.placeFree', { size: fmtGb(p.free / 1024 ** 3) }) : label;
}

async function clearMeta() {
  if (!confirm(t('dashboard.meta.clearConfirm'))) return;
  metaBusy.value = true;
  const r = await api.post('/api/system/meta/cache/clear', {});
  metaBusy.value = false;
  metaCleared.value = r.ok;
  await loadMeta();
}

function fmtBytes(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n <= 0) return '0 MB';
  const mb = n / 1024 ** 2;
  // the decimal separator of the page's language (11,8 MB in Italian)
  return mb >= 10 ? Math.round(mb) + ' MB' : mb.toFixed(1).replace('.', lang.value === 'it' ? ',' : '.') + ' MB';
}

function fmtDuration(sec) {
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
  if (d > 0) return `${d} ${t('dashboard.library.days')} ${h} h`;
  if (h > 0) return `${h} h ${m} min`;
  return `${m} min`;
}

function fmtWhen(ts) {
  return new Date(ts * 1000).toLocaleString(lang.value === 'it' ? 'it-IT' : 'en-GB', { dateStyle: 'medium', timeStyle: 'short' });
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
  await loadLibrary();
  await loadMeta();
  // CPU/RAM/disk/temperature/GPU are live figures -- keep the status card
  // current without requiring a manual page reload.
  statsPoll = setInterval(() => { loadStats(); loadLibrary(); loadMeta(); }, 5000);
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

  <div class="card" v-if="lib.ok">
    <h3><span class="dot"></span>{{ t('dashboard.library.title') }}</h3>
    <div class="between item"><span class="muted">{{ t('dashboard.library.albums') }}</span><span class="silver">{{ lib.albums ?? '—' }}</span></div>
    <div class="between item"><span class="muted">{{ t('dashboard.library.artists') }}</span><span class="silver">{{ lib.artists ?? '—' }}</span></div>
    <div class="between item"><span class="muted">{{ t('dashboard.library.tracks') }}</span><span class="silver">{{ lib.songs ?? '—' }}</span></div>
    <div class="between item" v-if="lib.duration > 0"><span class="muted">{{ t('dashboard.library.duration') }}</span><span class="silver">{{ fmtDuration(lib.duration) }}</span></div>
    <div class="between item"><span class="muted">{{ t('dashboard.library.lastScan') }}</span>
      <span class="silver">{{ lib.lastScan > 0 ? fmtWhen(lib.lastScan) : t('dashboard.library.never') }}</span>
    </div>
    <div class="between item" v-if="lib.scanning">
      <span class="muted">{{ t('dashboard.library.scanning') }}<template v-if="lib.pct >= 0">&nbsp;{{ lib.pct }}%</template><template v-if="lib.progress">&nbsp;· {{ lib.progress }}</template></span>
      <button class="ghost fit" @click="abortScan">{{ t('dashboard.library.stop') }}</button>
    </div>
    <div class="row" style="margin-top: 12px" v-else>
      <button class="secondary" :disabled="lib.busy" @click="rescan">{{ t('dashboard.library.refresh') }}</button>
    </div>
  </div>

  <div class="card" v-if="meta">
    <h3><span class="dot"></span>{{ t('dashboard.meta.title') }}</h3>
    <p class="sub">{{ t('dashboard.meta.desc') }}</p>
    <div class="between item">
      <span>{{ t('dashboard.meta.online') }}</span>
      <Toggle :model-value="meta.online" :disabled="metaBusy" @update:model-value="(v) => setMeta('online', v)" />
    </div>
    <div class="between item" v-if="meta.online">
      <span>{{ t('dashboard.meta.prefetch') }} <span class="muted">{{ t('dashboard.meta.prefetchHint') }}</span></span>
      <Toggle :model-value="meta.prefetch" :disabled="metaBusy" @update:model-value="(v) => setMeta('prefetch', v)" />
    </div>
    <div class="between item" v-if="meta.online && meta.prefetch && meta.prefetch_state && meta.prefetch_state.total > 0">
      <span class="muted">{{ meta.prefetch_state.running ? t('dashboard.meta.progressRunning') : t('dashboard.meta.progress') }}</span>
      <span class="silver">{{ t('dashboard.meta.progressValue', { done: meta.prefetch_state.done, total: meta.prefetch_state.total }) }}</span>
    </div>
    <div class="between item">
      <span class="muted">{{ t('dashboard.meta.saved') }}</span>
      <span class="silver">{{ t('dashboard.meta.savedValue', { albums: meta.cache.albums, artists: meta.cache.artists, size: fmtBytes(meta.cache.bytes) }) }}</span>
    </div>
    <div class="between item">
      <span>{{ t('dashboard.meta.keep') }} <span class="muted">{{ t('dashboard.meta.keepHint') }}</span></span>
      <Toggle :model-value="meta.keep" :disabled="metaBusy" @update:model-value="(v) => setMeta('keep', v)" />
    </div>
    <label>{{ t('dashboard.meta.where') }}</label>
    <select :value="meta.cache.location || ''" :disabled="metaBusy"
            @change="setMetaWhere($event.target.value)">
      <option v-for="p in (meta.locations || [])" :key="p.id" :value="p.path"
              :disabled="!p.usable && !p.current">{{ metaPlace(p) }}</option>
    </select>
    <p class="sub" style="margin: 8px 0 0">{{ t('dashboard.meta.whereHint') }}</p>
    <div class="msg" v-if="meta.cache.detached">{{ t('dashboard.meta.whereAway') }}</div>
    <div class="msg err" v-if="metaWhereError">{{ metaWhereError }}</div>
    <div class="row" style="margin-top: 12px">
      <button class="secondary" :disabled="metaBusy" @click="clearMeta">{{ t('dashboard.meta.clear') }}</button>
    </div>
    <p class="sub" style="margin: 10px 0 0">{{ metaCleared ? t('dashboard.meta.cleared') : t('dashboard.meta.clearHint') }}</p>
    <div class="between item stack-narrow" style="margin-top: 8px; border-top: 1px solid var(--border); padding-top: 14px">
      <span>{{ t('dashboard.meta.fix') }} <span class="muted">{{ t('dashboard.meta.fixHint') }}</span></span>
      <a class="secondary fit" style="text-align: center" href="library">{{ t('dashboard.meta.fixOpen') }}</a>
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
