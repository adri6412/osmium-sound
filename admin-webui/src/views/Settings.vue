<script setup>
import { ref, reactive, computed, watch, onMounted, onUnmounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import QRCode from 'qrcode';
import { api } from '../api.js';
import { useI18n } from '../i18n';
import Toggle from '../components/Toggle.vue';
import LanguageSelector from '../components/LanguageSelector.vue';

const host = location.hostname;
const route = useRoute();
const router = useRouter();
const { t } = useI18n();

// ── kiosk-like submenu navigation ────────────────────────────────
const sections = computed(() => [
  { key: 'network',   label: t('settings.sections.network.label'),   desc: t('settings.sections.network.desc') },
  { key: 'audio',     label: t('settings.sections.audio.label'),     desc: t('settings.sections.audio.desc') },
  { key: 'sources',   label: t('settings.sections.sources.label'),   desc: t('settings.sections.sources.desc') },
  { key: 'dsp',       label: t('settings.sections.dsp.label'),       desc: t('settings.sections.dsp.desc') },
  { key: 'bluetooth', label: t('settings.sections.bluetooth.label'), desc: t('settings.sections.bluetooth.desc') },
  { key: 'services',  label: t('settings.sections.services.label'),  desc: t('settings.sections.services.desc') },
  { key: 'multiroom', label: t('settings.sections.multiroom.label'), desc: t('settings.sections.multiroom.desc') },
  { key: 'display',   label: t('settings.sections.display.label'),   desc: t('settings.sections.display.desc') },
  { key: 'updates',   label: t('settings.sections.updates.label'),   desc: t('settings.sections.updates.desc') },
  { key: 'companion', label: t('settings.sections.companion.label'), desc: t('settings.sections.companion.desc') },
  { key: 'account',   label: t('settings.sections.account.label'),   desc: t('settings.sections.account.desc') },
  { key: 'language',  label: t('settings.sections.language.label'),  desc: t('settings.sections.language.desc') },
  { key: 'system',    label: t('settings.sections.system.label'),    desc: t('settings.sections.system.desc') },
]);
const open = ref(route.query.open || '');
watch(() => route.query.open, (v) => { open.value = v || ''; });
function goto(k) { router.replace({ query: k ? { open: k } : {} }); }
function title(k) { const s = sections.value.find(x => x.key === k); return s ? s.label : ''; }

// Sources iframe: mint the pairing token first and mount the frame with
// ?token= already in the src — no redirect/cookie dance inside the iframe
// (some browsers refuse framed redirects; Brave is especially strict).
const sourcesSrc = ref('');
const sourcesErr = ref('');
watch(open, async (v) => {
  if (v !== 'sources' || sourcesSrc.value) return;
  sourcesErr.value = '';
  const r = await api.post('/api/system/pair_token', {});
  if (r.ok && r.data.token) sourcesSrc.value = `/sources-app?token=${encodeURIComponent(r.data.token)}`;
  else sourcesErr.value = (r.data && r.data.message) || t('settings.sources.openFailed');
}, { immediate: true });

const msg = ref(''); const err = ref(false);
function say(m, isErr = false) { msg.value = m; err.value = isErr; if (m) setTimeout(() => { if (msg.value === m) msg.value = ''; }, 6000); }
function bodyMsg(r, fallback) { return (r.data && r.data.message) || fallback; }

// ── network ──────────────────────────────────────────────────────
const net = ref({}); const wifi = ref([]); const ssid = ref(''); const wifiPass = ref('');
const netBusy = ref(false);
async function loadNet() { const r = await api.sys('network_status'); if (r.ok) net.value = r.data; }
async function scanWifi() {
  netBusy.value = true; const r = await api.sys('wifi_scan'); netBusy.value = false;
  if (r.ok) wifi.value = r.data.networks || []; else say(t('settings.network.scanFailed'), true);
}
async function connectWifi() {
  netBusy.value = true; say(t('settings.network.connecting'));
  const r = await api.sysPost('wifi_connect', { ssid: ssid.value, password: wifiPass.value });
  netBusy.value = false;
  if (r.ok && r.data.success !== false) { say(t('settings.network.connected')); loadNet(); }
  else say(bodyMsg(r, t('settings.network.connectFailed')), true);
}
async function wired() {
  netBusy.value = true; const r = await api.sysPost('wired_dhcp', {}); netBusy.value = false;
  if (r.ok && r.data.success !== false) { say(t('settings.network.connectedWired')); loadNet(); }
  else say(bodyMsg(r, t('settings.network.wiredFailed')), true);
}

// ── audio + player name ──────────────────────────────────────────
const devices = ref([]); const currentDevice = ref('default'); const playerName = ref('');
async function loadAudio() {
  const r = await api.sys('audio_devices');
  if (r.ok) { devices.value = r.data.devices || []; currentDevice.value = r.data.current || 'default'; }
  const p = await api.sys('player_name'); if (p.ok) playerName.value = p.data.name || '';
}
async function pickDevice(id) {
  currentDevice.value = id;
  const r = await api.sysPost('audio_device', { device: id });
  say(r.ok && r.data.success !== false ? t('settings.audio.changed') : bodyMsg(r, t('settings.audio.changeFailed')), !(r.ok && r.data.success !== false));
}
async function saveName() {
  const r = await api.sysPost('player_name', { name: playerName.value });
  say(r.ok && r.data.success !== false ? t('settings.audio.nameSaved') : bodyMsg(r, t('settings.audio.saveFailed')), !(r.ok && r.data.success !== false));
}

// ── DSP ──────────────────────────────────────────────────────────
const dsp = reactive({ available: false, enabled: false, crossfeed: false, presets: [], active: null });
async function loadDsp() {
  const r = await api.sys('dsp');
  if (r.ok) { dsp.available = !!r.data.available; dsp.enabled = !!r.data.enabled; dsp.crossfeed = !!r.data.crossfeed; }
  const p = await api.sys('dsp_presets');
  if (p.ok) { dsp.presets = p.data.presets || []; dsp.active = p.data.active || null; }
}
async function setDspEnabled(v) {
  dsp.enabled = v;
  const r = await api.sysPost('dsp', { enabled: v });
  say(bodyMsg(r, v ? t('settings.dsp.engineOn') : t('settings.dsp.engineOff')), !(r.ok && r.data.success !== false));
  loadDsp();
}
async function setCrossfeed(v) {
  dsp.crossfeed = v;
  const r = await api.sysPost('dsp', { crossfeed: v });
  say(bodyMsg(r, t('settings.dsp.crossfeedUpdated')), !(r.ok && r.data.success !== false));
}
async function loadPreset(name) {
  say(t('settings.dsp.presetApplying'));
  const r = await api.sysPost('dsp_preset_load', { name });
  say(bodyMsg(r, r.ok ? t('settings.dsp.presetApplied', { name }) : t('settings.dsp.presetFailed')), !(r.ok && r.data.success !== false));
  loadDsp();
}
async function deletePreset(name) {
  if (!confirm(t('settings.dsp.presetDeleteConfirm', { name }))) return;
  await api.sysPost('dsp_preset_delete', { name }); loadDsp();
}

// ── DSP: room-correction filter (FIR) ─────────────────────────────
const fir = reactive({ present: false, filename: '', size: 0 });
const firBusy = ref(false);
async function loadFir() {
  const r = await api.dspFirStatus();
  if (r.ok) { fir.present = !!r.data.present; fir.filename = r.data.filename || ''; fir.size = r.data.size || 0; }
}
async function uploadFir(e) {
  const file = e.target.files && e.target.files[0];
  e.target.value = '';
  if (!file) return;
  firBusy.value = true; say(t('settings.dsp.firUploading'));
  const r = await api.dspFirUpload(file);
  firBusy.value = false;
  say(bodyMsg(r, r.ok && r.data.success !== false ? t('settings.dsp.firUploaded') : t('settings.dsp.firUploadFailed')), !(r.ok && r.data.success !== false));
  loadFir();
}
async function removeFir() {
  firBusy.value = true;
  const r = await api.dspFirRemove();
  firBusy.value = false;
  say(r.ok && r.data.removed ? t('settings.dsp.firRemoved') : bodyMsg(r, t('settings.dsp.firNoneToRemove')));
  loadFir();
}

// ── Bluetooth ────────────────────────────────────────────────────
const bt = reactive({ available: false, enabled: false, devices: [], countdown: 0 });
let btTimer = null;
async function loadBt() {
  const r = await api.sys('bluetooth');
  if (r.ok) { bt.available = !!r.data.available; bt.enabled = !!r.data.enabled; bt.devices = r.data.devices || []; }
}
async function setBt(v) {
  bt.enabled = v; say(v ? t('settings.bluetooth.enabling') : t('settings.bluetooth.disabling'));
  const r = await api.sysPost('bluetooth', { enable: v });
  say(bodyMsg(r, t('settings.bluetooth.updated')), !(r.ok && r.data.success !== false));
  loadBt();
}
async function btDiscoverable() {
  const r = await api.sysPost('bluetooth_discoverable', {});
  if (r.ok && r.data.success !== false) {
    bt.countdown = r.data.seconds || 120;
    clearInterval(btTimer);
    btTimer = setInterval(() => { if (--bt.countdown <= 0) clearInterval(btTimer); }, 1000);
  } else say(bodyMsg(r, t('settings.bluetooth.operationFailed')), true);
}
async function btForget(mac) {
  const r = await api.sysPost('bluetooth_forget', { mac });
  if (r.ok) bt.devices = r.data.devices || []; loadBt();
}

// ── Tidal / SSH ──────────────────────────────────────────────────
const tidal = reactive({ available: false, enabled: false });
const sshState = reactive({ available: false, enabled: false });
async function loadToggles() {
  const tv = await api.sys('tidal'); if (tv.ok) { tidal.available = !!tv.data.available; tidal.enabled = !!tv.data.enabled; }
  const s = await api.sys('ssh'); if (s.ok) { sshState.available = !!s.data.available; sshState.enabled = !!s.data.enabled; }
}
async function setTidal(v) {
  tidal.enabled = v; const r = await api.sysPost('tidal', { enable: v });
  say(bodyMsg(r, t('settings.services.tidalUpdated')), !(r.ok && r.data.success !== false)); loadToggles();
}
async function setSsh(v) {
  sshState.enabled = v; const r = await api.sysPost('ssh', { enable: v });
  say(bodyMsg(r, v ? t('settings.services.sshOn') : t('settings.services.sshOff')), !(r.ok && r.data.success !== false)); loadToggles();
}

// ── multiroom / ruolo LMS ────────────────────────────────────────
const lms = reactive({ mode: 'local', host: '', servers: [] });
async function loadLms() {
  const r = await api.sys('lms_role');
  if (r.ok) { lms.mode = r.data.mode || 'local'; lms.host = r.data.host || ''; }
}
async function discoverLms() {
  say(t('settings.multiroom.searching'));
  const r = await api.sys('discover_lms'); if (r.ok) { lms.servers = r.data.servers || []; say(''); }
}
async function applyLmsRole(mode, hostArg) {
  const r = await api.sysPost('lms_role', { mode, host: hostArg || lms.host || null });
  say(bodyMsg(r, t('settings.multiroom.roleUpdated')), !(r.ok && r.data.success !== false)); loadLms();
}

// ── display mode ─────────────────────────────────────────────────
const mode = ref('');
async function loadMode() { const r = await api.sys('display_mode'); if (r.ok) mode.value = r.data.mode; }
async function setMode(m) {
  if (m === 'headless' && !confirm(t('settings.display.confirmHeadless'))) return;
  const r = await api.sysPost('display_mode', { mode: m });
  if (r.ok && r.data.success !== false) { mode.value = r.data.mode || m; say(bodyMsg(r, t('settings.display.changed'))); }
  else say(bodyMsg(r, t('settings.display.changeFailed')), true);
}

// ── updates (prod/dev channel; single "update all" + blocking modal) ─
const channel = ref('prod');
const upd = reactive({ ui: null, system: null, os: null, lyrion: null });
const updBusy = ref(false);
const kinds = { ui: 'app', system: 'system', os: 'os', lyrion: 'lyrion' };
const kindLabels = computed(() => ({
  ui: t('settings.updates.kindUi'), system: t('settings.updates.kindSystem'),
  os: t('settings.updates.kindOs'), lyrion: t('settings.updates.kindLyrion'),
}));
// Blocking overlay state — mirrors the kiosk's forced update modal: while an
// apply is running nothing else is clickable, so double-applies can't happen.
const applying = reactive({ active: false, kind: '', label: '', state: '', progress: null, message: '', error: false, doneList: [] });
async function loadChannel() { const r = await api.sys('ota_channel'); if (r.ok) channel.value = r.data.channel || 'prod'; }
async function setChannel(c) {
  if (applying.active) return;
  channel.value = c;
  const r = await api.sysPost('ota_channel', { channel: c });
  say(r.ok && r.data.success !== false ? (c === 'dev' ? t('settings.updates.channelChangedDev') : t('settings.updates.channelChangedProd')) : bodyMsg(r, t('settings.updates.channelFailed')), !(r.ok && r.data.success !== false));
  checkAll();
}
async function checkAll() {
  updBusy.value = true;
  for (const k of Object.keys(kinds)) {
    const r = await api.sys(`updates/${kinds[k]}/check`);
    upd[k] = r.ok ? r.data : null;
  }
  updBusy.value = false;
}
const hasUpdates = () => Object.keys(kinds).some(k => upd[k] && upd[k].update_available);
const sleep = (ms) => new Promise(res => setTimeout(res, ms));

async function pollUntilDone(k, timeoutMs = 15 * 60 * 1000) {
  const t0 = Date.now();
  // Network errors are EXPECTED mid-way: the system bundle restarts this very
  // daemon, and an OS update may reboot — keep polling, the status file
  // written by the updater script survives the restart.
  while (Date.now() - t0 < timeoutMs) {
    await sleep(2000);
    const r = await api.sys(`updates/${kinds[k]}/status`);
    if (!r.ok) continue;
    const s = r.data || {};
    applying.state = s.state || '';
    applying.progress = (typeof s.progress === 'number') ? s.progress : null;
    applying.message = s.message || '';
    if (s.state === 'done') return true;
    if (s.state === 'error') return false;
  }
  applying.message = t('settings.updates.timeout');
  return false;
}

async function applyAll() {
  if (applying.active || !hasUpdates()) return;
  applying.active = true; applying.error = false; applying.doneList = [];
  // System last: applying it restarts this daemon (brief connection blip the
  // polling rides out). UI/OS/Lyrion first.
  const order = ['ui', 'os', 'lyrion', 'system'].filter(k => upd[k] && upd[k].update_available);
  for (const k of order) {
    applying.kind = k; applying.label = kindLabels.value[k];
    applying.state = 'starting'; applying.progress = null; applying.message = '';
    const r = await api.sysPost(`updates/${kinds[k]}/apply`, {});
    if (!(r.ok && (r.data.started || r.data.success !== false))) {
      applying.error = true; applying.message = bodyMsg(r, t('settings.updates.startFailed')); break;
    }
    const ok = await pollUntilDone(k);
    if (!ok) { applying.error = true; break; }
    applying.doneList.push(kindLabels.value[k]);
  }
  applying.state = applying.error ? 'error' : 'finished';
  if (!applying.error) { applying.message = t('settings.updates.allCompleted'); }
  // Keep the modal up until the user closes it (shows the outcome).
}
function closeApplyModal() {
  applying.active = false; applying.kind = ''; applying.state = '';
  checkAll();
}

// ── companion pairing ────────────────────────────────────────────
const pairQr = ref(null); const pairBusy = ref(false);
async function mintPair() {
  pairBusy.value = true; pairQr.value = null;
  const r = await api.post('/api/system/pair_token', {});
  pairBusy.value = false;
  if (r.ok && r.data.token) {
    const payload = JSON.stringify({ lms: `http://${host}:9000`, api: `${host}:8080`, token: r.data.token });
    pairQr.value = await QRCode.toDataURL(payload, { margin: 1, width: 380 });
  } else say(bodyMsg(r, t('settings.companion.tokenFailed')), true);
}
async function revokePairs() {
  if (!confirm(t('settings.companion.revokeConfirm'))) return;
  const r = await api.post('/api/system/pair_revoke_all', {});
  say(r.ok ? t('settings.companion.revoked') : bodyMsg(r, t('settings.companion.revokeFailed')), !r.ok);
  pairQr.value = null;
}

// ── system: reboot/shutdown/reset ────────────────────────────────
async function reboot() { if (confirm(t('settings.system.confirmReboot'))) { await api.sysPost('reboot', {}); say(t('settings.system.rebooting')); } }
async function shutdown() { if (confirm(t('settings.system.confirmShutdown'))) { await api.sysPost('shutdown', {}); say(t('settings.system.shuttingDown')); } }
const resetPw = ref('');
async function factoryReset() {
  if (!confirm(t('settings.system.factoryConfirm'))) return;
  const r = await api.post('/api/system/factory_reset', { password: resetPw.value });
  if (r.ok && r.data.success !== false) say(t('settings.system.factoryStarted'));
  else say(bodyMsg(r, t('settings.system.factoryFailed')), true);
}

// ── account ──────────────────────────────────────────────────────
const acc = reactive({ username: '', current: '', next: '' });
async function changePw() {
  const r = await api.changePassword(acc.username, acc.current, acc.next);
  if (r.ok && r.data.success) { say(t('settings.account.updated')); acc.username = ''; acc.current = ''; acc.next = ''; }
  else say(bodyMsg(r, t('settings.account.updateFailed')), true);
}

onMounted(async () => {
  loadNet(); loadAudio(); loadDsp(); loadFir(); loadBt(); loadToggles(); loadLms(); loadMode(); loadChannel(); checkAll();
});
onUnmounted(() => clearInterval(btTimer));
</script>

<template>
  <!-- section menu (kiosk-like) -->
  <template v-if="!open">
    <RouterLink class="backlink" to="/">← {{ t('dashboard.title') }}</RouterLink>
    <h2 class="page">{{ t('settings.title') }}</h2>
    <div v-if="msg" class="msg" :class="{ err }">{{ msg }}</div>
    <div class="card" style="padding: 6px 16px;">
      <div v-for="s in sections" :key="s.key" class="net between" @click="goto(s.key)">
        <span>
          <span style="display:block;">{{ s.label }}</span>
          <span class="muted">{{ s.desc }}</span>
        </span>
        <span class="silver" style="font-size: 18px;">›</span>
      </div>
    </div>
  </template>

  <!-- single open section -->
  <template v-else>
    <a class="backlink" href="#" @click.prevent="goto('')">← {{ t('settings.backToSettings') }}</a>
    <h2 class="page">{{ title(open) }}</h2>
    <div v-if="msg" class="msg" :class="{ err }">{{ msg }}</div>

    <!-- Network -->
    <div class="card" v-if="open === 'network'">
      <p class="sub">{{ t('settings.network.activeLabel') }}: {{ net.type === 'wireless' ? t('dashboard.wifi') : net.type === 'wired' ? t('settings.network.cable') : '—' }}
        <span v-if="net.ssid"> · {{ net.ssid }}</span><span v-if="net.ip"> · {{ net.ip }}</span></p>
      <div class="row">
        <button class="secondary" :disabled="netBusy" @click="scanWifi">{{ t('settings.network.scanWifi') }}</button>
        <button class="secondary" :disabled="netBusy" @click="wired">{{ t('settings.network.useWired') }}</button>
      </div>
      <div v-for="n in wifi" :key="n.ssid" class="net between" @click="ssid = n.ssid">
        <span>{{ n.ssid }} <span class="check" v-if="n.in_use">✓</span></span>
        <span class="muted">{{ n.signal }}%</span>
      </div>
      <template v-if="wifi.length || ssid">
        <label>{{ t('settings.network.ssidLabel') }}</label><input v-model="ssid" />
        <label>{{ t('settings.network.passwordLabel') }}</label><input v-model="wifiPass" type="password" />
        <div style="margin-top: 12px;"><button :disabled="netBusy" @click="connectWifi">{{ t('settings.network.connect') }}</button></div>
      </template>
    </div>

    <!-- Audio -->
    <div class="card" v-if="open === 'audio'">
      <p class="sub">{{ t('settings.audio.hint') }}</p>
      <div v-for="d in devices" :key="d.id" class="net between" @click="pickDevice(d.id)">
        <span>{{ d.name || d.id }}</span><span class="check" v-if="d.id === currentDevice">✓</span>
      </div>
      <label>{{ t('settings.audio.playerName') }}</label>
      <div class="row"><input v-model="playerName" /><button class="secondary fit" @click="saveName">{{ t('common.save') }}</button></div>
    </div>

    <!-- Sources (embedded :8080 SPA over HTTPS proxy) -->
    <div v-if="open === 'sources'">
      <p class="sub" style="margin: 0 0 10px;">{{ t('settings.sources.hint') }}</p>
      <div v-if="sourcesErr" class="msg err">{{ sourcesErr }}</div>
      <p v-else-if="!sourcesSrc" class="muted">{{ t('settings.sources.opening') }}</p>
      <iframe v-if="sourcesSrc" :src="sourcesSrc"
              style="width: 100%; height: 74vh; border: 1px solid var(--border); border-radius: 14px; background: #0f0f0f;"></iframe>
    </div>

    <!-- DSP -->
    <div class="card" v-if="open === 'dsp'">
      <p class="sub" v-if="!dsp.available">{{ t('settings.dsp.unavailable') }}</p>
      <template v-else>
        <div class="between item"><span>{{ t('settings.dsp.engine') }}</span><Toggle :model-value="dsp.enabled" @update:model-value="setDspEnabled" /></div>
        <div class="between item"><span>{{ t('settings.dsp.crossfeed') }}</span><Toggle :model-value="dsp.crossfeed" @update:model-value="setCrossfeed" /></div>
        <label v-if="dsp.presets.length">{{ t('settings.dsp.presets') }}</label>
        <div v-for="p in dsp.presets" :key="p.name" class="net between">
          <span @click="loadPreset(p.name)" style="cursor: pointer;">{{ p.name }}
            <span class="pill gold" v-if="p.active">{{ t('settings.dsp.active') }}</span>
            <span class="pill" v-else-if="p.builtin">{{ t('settings.dsp.builtin') }}</span>
          </span>
          <button v-if="!p.builtin" class="ghost fit" @click="deletePreset(p.name)">{{ t('settings.dsp.delete') }}</button>
        </div>
        <p class="sub" style="margin-top: 10px;">{{ t('settings.dsp.editorHint') }}</p>

        <label>{{ t('settings.dsp.firLabel') }}</label>
        <p class="sub" style="margin: 0 0 10px;">
          {{ fir.present ? t('settings.dsp.firPresent', { filename: fir.filename, size: Math.round(fir.size / 1024) }) : t('settings.dsp.firMissing') }}
        </p>
        <div class="row">
          <label class="upload-btn fit">
            {{ firBusy ? '…' : t('settings.dsp.firUpload') }}
            <input type="file" accept=".wav,.txt" :disabled="firBusy" style="display: none;" @change="uploadFir" />
          </label>
          <button v-if="fir.present" class="danger fit" :disabled="firBusy" @click="removeFir">{{ t('settings.dsp.firRemove') }}</button>
        </div>
      </template>
    </div>

    <!-- Bluetooth -->
    <div class="card" v-if="open === 'bluetooth'">
      <p class="sub">{{ t('settings.bluetooth.hint') }}</p>
      <div class="between item"><span>{{ t('settings.bluetooth.toggleLabel') }}</span><Toggle :model-value="bt.enabled" @update:model-value="setBt" /></div>
      <template v-if="bt.enabled">
        <div class="between item">
          <span>{{ t('settings.bluetooth.discoverableLabel') }} <span class="pill gold" v-if="bt.countdown > 0">{{ bt.countdown }}s</span></span>
          <button class="secondary fit" @click="btDiscoverable">{{ t('settings.bluetooth.makeDiscoverable') }}</button>
        </div>
        <label v-if="bt.devices.length">{{ t('settings.bluetooth.pairedDevices') }}</label>
        <div v-for="d in bt.devices" :key="d.mac" class="net between">
          <span>{{ d.name || d.mac }} <span class="pill gold" v-if="d.connected">{{ t('settings.bluetooth.connected') }}</span></span>
          <button class="ghost fit" @click="btForget(d.mac)">{{ t('settings.bluetooth.forget') }}</button>
        </div>
      </template>
    </div>

    <!-- Services -->
    <div class="card" v-if="open === 'services'">
      <div class="between item" v-if="tidal.available">
        <span>{{ t('settings.services.tidal') }}</span>
        <Toggle :model-value="tidal.enabled" @update:model-value="setTidal" />
      </div>
      <div class="between item">
        <span>{{ t('settings.services.ssh') }} <span class="muted">{{ t('settings.services.sshHint') }}</span></span>
        <Toggle :model-value="sshState.enabled" @update:model-value="setSsh" />
      </div>
    </div>

    <!-- Multiroom -->
    <div class="card" v-if="open === 'multiroom'">
      <p class="sub">{{ t('settings.multiroom.hint') }}</p>
      <div class="seg">
        <button :class="{ active: lms.mode === 'local' }" @click="applyLmsRole('local')">{{ t('settings.multiroom.ownServer') }}</button>
        <button :class="{ active: lms.mode === 'follow' }" @click="lms.mode = 'follow'">{{ t('settings.multiroom.followAnother') }}</button>
      </div>
      <template v-if="lms.mode === 'follow'">
        <div class="row" style="margin-top: 12px;">
          <input v-model="lms.host" :placeholder="t('settings.multiroom.serverIpPlaceholder')" />
          <button class="secondary fit" @click="discoverLms">{{ t('settings.multiroom.search') }}</button>
          <button class="fit" @click="applyLmsRole('follow', lms.host)">{{ t('common.apply') }}</button>
        </div>
        <div v-for="s in lms.servers" :key="s.ip" class="net between" @click="lms.host = s.ip">
          <span>{{ s.name || s.ip }}</span><span class="muted">{{ s.ip }}</span>
        </div>
      </template>
    </div>

    <!-- Display mode -->
    <div class="card" v-if="open === 'display'">
      <p class="sub">{{ t('settings.display.currentLabel') }}: <span class="silver">{{ mode === 'headless' ? t('settings.display.headless') : t('settings.display.onscreen') }}</span></p>
      <div class="row">
        <button v-if="mode === 'headless'" @click="setMode('gui')">{{ t('settings.display.switchToOnscreen') }}</button>
        <button v-else class="secondary" @click="setMode('headless')">{{ t('settings.display.switchToHeadless') }}</button>
      </div>
    </div>

    <!-- Updates -->
    <div class="card" v-if="open === 'updates'">
      <div class="between item">
        <span>{{ t('settings.updates.channel') }}
          <span class="pill" :class="{ gold: channel === 'dev' }">{{ channel === 'dev' ? t('settings.updates.channelDev') : t('settings.updates.channelProd') }}</span>
        </span>
        <span class="seg fit">
          <button :class="{ active: channel === 'prod' }" @click="setChannel('prod')">{{ t('settings.updates.stable') }}</button>
          <button :class="{ active: channel === 'dev' }" @click="setChannel('dev')">{{ t('settings.updates.dev') }}</button>
        </span>
      </div>
      <div v-for="k in Object.keys(kinds)" :key="k" class="between item">
        <span>{{ kindLabels[k] }}
          <span class="muted" v-if="upd[k]">
            {{ upd[k].current || '—' }}<template v-if="upd[k].update_available"> → <span class="gold">{{ upd[k].latest }}</span></template>
            <template v-else> · {{ t('settings.updates.upToDate') }}</template>
          </span>
          <span class="muted" v-else> · —</span>
        </span>
      </div>
      <div class="row" style="margin-top: 12px;">
        <button v-if="hasUpdates()" :disabled="applying.active" @click="applyAll">{{ t('settings.updates.updateAll') }}</button>
        <button class="secondary" :disabled="updBusy || applying.active" @click="checkAll">{{ updBusy ? t('settings.updates.checking') : t('settings.updates.checkAgain') }}</button>
      </div>
    </div>

    <!-- Companion -->
    <div class="card" v-if="open === 'companion'">
      <p class="sub">{{ t('settings.companion.hint') }}</p>
      <div class="row">
        <button class="secondary" :disabled="pairBusy" @click="mintPair">{{ pairBusy ? t('settings.companion.generating') : t('settings.companion.generateQr') }}</button>
        <button class="ghost" @click="revokePairs">{{ t('settings.companion.revokeAll') }}</button>
      </div>
      <div v-if="pairQr" style="margin-top: 14px;"><span class="qrbox"><img :src="pairQr" alt="QR pairing" /></span></div>
    </div>

    <!-- Account -->
    <div class="card" v-if="open === 'account'">
      <label>{{ t('settings.account.newUsername') }}</label><input v-model="acc.username" autocomplete="username" />
      <label>{{ t('settings.account.currentPassword') }}</label><input v-model="acc.current" type="password" autocomplete="current-password" />
      <label>{{ t('settings.account.newPassword') }}</label><input v-model="acc.next" type="password" autocomplete="new-password" />
      <div style="margin-top: 12px;"><button @click="changePw">{{ t('settings.account.change') }}</button></div>
    </div>

    <!-- Language -->
    <div class="card" v-if="open === 'language'">
      <p class="sub">{{ t('settings.language.hint') }}</p>
      <LanguageSelector variant="list" />
    </div>

    <!-- forced blocking update modal (kiosk-style) -->
    <div v-if="applying.active" class="overlay">
      <div class="card" style="width: 340px; text-align: center;">
        <template v-if="applying.state !== 'finished' && applying.state !== 'error'">
          <div class="spinner"></div>
          <h3 style="justify-content: center;">{{ t('settings.updates.updating', { label: applying.label }) }}</h3>
          <p class="sub" style="margin-bottom: 6px;">
            {{ applying.message || applying.state || t('common.loading') }}
            <template v-if="applying.progress !== null"> · {{ applying.progress }}%</template>
          </p>
          <p class="muted">{{ t('settings.updates.dontClose') }}</p>
        </template>
        <template v-else>
          <h3 style="justify-content: center;">{{ applying.error ? t('settings.updates.interrupted') : t('settings.updates.completed') }}</h3>
          <p class="sub">{{ applying.message || (applying.error ? t('settings.updates.genericError') : '') }}</p>
          <p class="muted" v-if="applying.doneList.length">{{ t('settings.updates.updatedList') }}: {{ applying.doneList.join(', ') }}</p>
          <button style="margin-top: 10px;" @click="closeApplyModal">{{ t('common.close') }}</button>
        </template>
      </div>
    </div>

    <!-- System -->
    <div class="card" v-if="open === 'system'">
      <div class="row">
        <button class="secondary" @click="reboot">{{ t('settings.system.reboot') }}</button>
        <button class="secondary" @click="shutdown">{{ t('settings.system.shutdown') }}</button>
      </div>
      <div style="margin-top: 18px; padding-top: 16px; border-top: 1px solid rgba(224,90,90,0.25);">
        <p class="sub">{{ t('settings.system.factoryHint') }}</p>
        <label>{{ t('settings.system.adminPassword') }}</label><input v-model="resetPw" type="password" />
        <div style="margin-top: 12px;"><button class="danger" @click="factoryReset">{{ t('settings.system.factoryReset') }}</button></div>
      </div>
    </div>
  </template>
</template>
