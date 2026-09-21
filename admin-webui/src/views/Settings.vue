<script setup>
import { ref, reactive, computed, watch, onMounted, onUnmounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import QRCode from 'qrcode';
import { api } from '../api.js';
import { useI18n } from '../i18n';
import Toggle from '../components/Toggle.vue';
import LanguageSelector from '../components/LanguageSelector.vue';
import SourcesPanel from '../components/SourcesPanel.vue';
import VuSkinPreview from '../components/VuSkinPreview.vue';
import animCd from '../assets/anim/cd.jpg';
import animCdfront from '../assets/anim/cdfront.jpg';
import animVinyl from '../assets/anim/vinyl.jpg';
import animCassette from '../assets/anim/cassette.jpg';

const host = location.hostname;
const route = useRoute();
const router = useRouter();
const { t, lang } = useI18n();

// ── kiosk-like submenu navigation ────────────────────────────────
const sections = computed(() => [
  { key: 'network',   label: t('settings.sections.network.label'),   desc: t('settings.sections.network.desc') },
  { key: 'audio',     label: t('settings.sections.audio.label'),     desc: t('settings.sections.audio.desc') },
  { key: 'btSpeakers', label: t('settings.sections.btSpeakers.label'), desc: t('settings.sections.btSpeakers.desc') },
  { key: 'remote',    label: t('settings.sections.remote.label'),    desc: t('settings.sections.remote.desc') },
  { key: 'sources',   label: t('settings.sections.sources.label'),   desc: t('settings.sections.sources.desc') },
  // 'dsp' is deliberately NOT listed here — the feature (and its room-correction
  // sub-flow) is being held back for a future paid tier. The card markup below
  // (v-if="open === 'dsp'") and all its backing code/API endpoints are left
  // fully intact on purpose, just unreachable: normalizeSection() below also
  // strips a hand-typed ?open=dsp so there's no direct-URL bypass either.
  { key: 'services',  label: t('settings.sections.services.label'),  desc: t('settings.sections.services.desc') },
  { key: 'tailscale', label: t('settings.sections.tailscale.label'), desc: t('settings.sections.tailscale.desc') },
  { key: 'lyrion',    label: t('settings.sections.lyrion.label'),    desc: t('settings.sections.lyrion.desc') },
  { key: 'playback',  label: t('settings.sections.playback.label'),  desc: t('settings.sections.playback.desc') },
  // A section of its own, like the kiosk's Settings → VU meter: the switch,
  // the styles with a preview each, and the store.
  { key: 'vuMeters',  label: t('settings.sections.vuMeters.label'),  desc: t('settings.sections.vuMeters.desc') },
  // What the kiosk draws in place of the meters when they are off. Only the
  // choice lives here: the animations themselves exist on the device screen.
  { key: 'animations', label: t('settings.sections.animations.label'), desc: t('settings.sections.animations.desc') },
  { key: 'display',  label: t('settings.sections.display.label'),   desc: t('settings.sections.display.desc') },
  { key: 'timezone',  label: t('settings.sections.timezone.label'),  desc: t('settings.sections.timezone.desc') },
  { key: 'updates',   label: t('settings.sections.updates.label'),   desc: t('settings.sections.updates.desc') },
  { key: 'companion', label: t('settings.sections.companion.label'), desc: t('settings.sections.companion.desc') },
  { key: 'companionIos', label: t('settings.sections.companionIos.label'), desc: t('settings.sections.companionIos.desc') },
  { key: 'account',   label: t('settings.sections.account.label'),   desc: t('settings.sections.account.desc') },
  { key: 'backup',    label: t('settings.sections.backup.label'),    desc: t('settings.sections.backup.desc') },
  { key: 'language',  label: t('settings.sections.language.label'),  desc: t('settings.sections.language.desc') },
  { key: 'system',    label: t('settings.sections.system.label'),    desc: t('settings.sections.system.desc') },
  { key: 'debug',     label: t('settings.sections.debug.label'),     desc: t('settings.sections.debug.desc') },
  // Reached from System and Updates ("Check the network"), not listed itself.
  { key: 'netCheck',  label: t('settings.sections.netCheck.label'),  desc: t('settings.sections.netCheck.desc'), hidden: true },
]);
const listedSections = computed(() => sections.value.filter(s => !s.hidden));
// 'multiroom' was this section's key before it became "Lyrion Music Server";
// keep old bookmarks and the kiosk's deep links working. 'dsp' is held back
// (see the sections list above) — redirect a hand-typed ?open=dsp back to the
// section list instead of rendering the card.
const normalizeSection = (k) => (k === 'multiroom' ? 'lyrion' : k === 'dsp' ? '' : (k || ''));
const open = ref(normalizeSection(route.query.open));
watch(() => route.query.open, (v) => { open.value = normalizeSection(v); });
function goto(k) { router.replace({ query: k ? { open: k } : {} }); }
// the network check's back link returns to the section it was opened from
function goBack() { goto(open.value === 'netCheck' ? normalizeSection(route.query.from) : ''); }
function title(k) { const s = sections.value.find(x => x.key === k); return s ? s.label : ''; }

const msg = ref(''); const err = ref(false);
function say(m, isErr = false) { msg.value = m; err.value = isErr; if (m) setTimeout(() => { if (msg.value === m) msg.value = ''; }, 6000); }
function bodyMsg(r, fallback) { return (r.data && r.data.message) || fallback; }
async function downloadSupportBundle() {
  say(t('settings.system.supportBundlePreparing') || 'Preparazione download del support bundle...');
  try {
    const resp = await fetch('/api/system/support_bundle', {
      credentials: 'same-origin',
    });
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(text || resp.statusText);
    }
    const blob = await resp.blob();
    let filename = 'support-bundle.zip';
    const cd = resp.headers.get('Content-Disposition');
    if (cd) {
      const m = /filename\*=[^']*'[^']*'([^;]+)|filename="([^"]+)"|filename=([^;\n]+)/i.exec(cd);
      const name = m && decodeURIComponent(m[1] || m[2] || m[3] || '');
      if (name) filename = name;
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    say(t('settings.system.supportBundleDownloaded') || 'Download avviato');
  } catch (err) {
    say(t('settings.system.supportBundleFailed') || 'Download support bundle fallito', true);
    console.error('support bundle download failed', err);
  }
}

// ── Boot debug flags (Settings → Debug) ──────────────────────────────
// For a box that hangs at shutdown/boot behind the Plymouth splash instead of
// crashing cleanly (possibly a kernel panic hidden behind it), or to capture
// a vmcore off a real one. Both only take effect after a reboot — offer one
// via the same reboot-wait overlay every other reboot-ending action here
// uses (see waitForReboot() below).
const plymouthDisabled = ref(false);
const kdumpEnabled = ref(false);
const kdumpInstalled = ref(true);
const debugFlagsBusy = ref(false);
async function loadDebugFlags() {
  const [py, kd] = await Promise.all([api.sys('debug_plymouth'), api.sys('debug_kdump')]);
  if (py.ok) plymouthDisabled.value = !!py.data.disabled;
  if (kd.ok) { kdumpEnabled.value = !!kd.data.enabled; kdumpInstalled.value = kd.data.installed !== false; }
}
async function togglePlymouth(disable) {
  if (debugFlagsBusy.value || disable === plymouthDisabled.value) return;
  debugFlagsBusy.value = true;
  const r = await api.sysPost('debug_plymouth', { disable });
  debugFlagsBusy.value = false;
  if (r.ok && r.data.success !== false) {
    plymouthDisabled.value = disable;
    say(bodyMsg(r, t('settings.debug.rebootRequired')));
    if (confirm(t('settings.debug.rebootPrompt'))) { await api.sysPost('reboot', {}); waitForReboot(); }
  } else {
    say(bodyMsg(r, t('settings.debug.saveFailed')), true);
  }
}
async function toggleKdump(enable) {
  if (debugFlagsBusy.value || enable === kdumpEnabled.value) return;
  debugFlagsBusy.value = true;
  say(enable ? t('settings.debug.kdumpInstalling') : '');
  const r = await api.sysPost('debug_kdump', { enable });
  debugFlagsBusy.value = false;
  if (r.ok && r.data.success !== false) {
    kdumpEnabled.value = enable;
    kdumpInstalled.value = true;
    say(bodyMsg(r, t('settings.debug.rebootRequired')));
    if (confirm(t('settings.debug.rebootPrompt'))) { await api.sysPost('reboot', {}); waitForReboot(); }
  } else {
    say(bodyMsg(r, t('settings.debug.saveFailed')), true);
  }
}

// ── network ──────────────────────────────────────────────────────
const net = ref({}); const wifi = ref([]); const ssid = ref(''); const wifiPass = ref('');
// The band picked from a dual-band row ('2.4' / '5' / '6'), '' when the name
// was typed by hand or exists on one band only: almost every home router
// broadcasts the same name on 2.4 and 5 GHz, and without this the two rows
// would be the same row.
const wifiBand = ref('');
const netBusy = ref(false);
const dualSsids = computed(() => {
  const seen = new Set(), dual = new Set();
  for (const n of wifi.value) { if (seen.has(n.ssid)) dual.add(n.ssid); seen.add(n.ssid); }
  return dual;
});
function pickNet(n) {
  ssid.value = n.ssid;
  wifiBand.value = dualSsids.value.has(n.ssid) ? (n.band || '') : '';
}
async function loadNet() { const r = await api.sys('network_status'); if (r.ok) net.value = r.data; }
async function scanWifi() {
  netBusy.value = true; const r = await api.sys('wifi_scan'); netBusy.value = false;
  if (r.ok) wifi.value = r.data.networks || []; else say(t('settings.network.scanFailed'), true);
}
async function connectWifi() {
  netBusy.value = true; say(t('settings.network.connecting'));
  const r = await api.sysPost('wifi_connect', { ssid: ssid.value, password: wifiPass.value, band: wifiBand.value });
  netBusy.value = false;
  if (r.ok && r.data.success !== false) { say(t('settings.network.connected')); loadNet(); }
  else say(bodyMsg(r, t('settings.network.connectFailed')), true);
}
async function wired() {
  netBusy.value = true; const r = await api.sysPost('wired_dhcp', {}); netBusy.value = false;
  if (r.ok && r.data.success !== false) { say(t('settings.network.connectedWired')); loadNet(); }
  else say(bodyMsg(r, t('settings.network.wiredFailed')), true);
}

// ── fixed (static) IPv4 address ──────────────────────────────────
// Deliberately webui-only: there is no equivalent on the kiosk screen, where
// a mistyped address would strand a headless box with no way to tell the
// owner where it went. The backend edits the NetworkManager profile (see
// api_server.py's set_ipv4_config), so the address survives a reboot.
const ipv4 = ref({ mode: 'auto', device: '', address: '', prefix: 24, gateway: '', dns: [] });
const ipForm = ref({ mode: 'auto', address: '', prefix: 24, gateway: '', dns: '' });
const ipBusy = ref(false);
async function loadIpv4() {
  const r = await api.sys('ipv4_config');
  if (!r.ok || r.data.success === false) return;
  ipv4.value = r.data;
  // For a DHCP box the backend hands back the *live* lease, so switching to
  // a fixed address starts from a configuration already known to work.
  ipForm.value = {
    mode: r.data.mode || 'auto',
    address: r.data.address || '',
    prefix: r.data.prefix || 24,
    gateway: r.data.gateway || '',
    dns: (r.data.dns || []).join(', '),
  };
}
async function saveIpv4() {
  if (ipForm.value.mode === 'manual' && !confirm(t('settings.network.staticConfirm', { address: ipForm.value.address }))) return;
  ipBusy.value = true;
  const r = await api.sysPost('ipv4_config', {
    mode: ipForm.value.mode,
    address: ipForm.value.address.trim(),
    prefix: Number(ipForm.value.prefix),
    gateway: ipForm.value.gateway.trim(),
    dns: ipForm.value.dns,
  });
  ipBusy.value = false;
  if (!r.ok || r.data.success === false) { say(bodyMsg(r, t('settings.network.staticFailed')), true); return; }
  say(bodyMsg(r, t('settings.network.staticApplying')));
  // The address change tears down the connection this page is talking over,
  // so nothing here can confirm the result — re-reading only works if the
  // browser is still on the old address. Give NM time, then try once; the
  // owner reconnects at the new address either way.
  setTimeout(() => { loadNet(); loadIpv4(); }, 8000);
}

// ── audio + device name ────────────────────────────────────────────
// device_name renames BOTH the Linux hostname (so <name>.local updates
// live) and the squeezelite/Bluetooth player name together — see
// api_server.py's set_device_name. Was player_name-only before, which left
// the box's hostname stuck at the factory default forever.
const devices = ref([]); const currentDevice = ref('default'); const playerName = ref('');
async function loadAudio() {
  const r = await api.sys('audio_devices');
  if (r.ok) { devices.value = r.data.devices || []; currentDevice.value = r.data.current || 'default'; }
  const p = await api.sys('device_name'); if (p.ok) playerName.value = p.data.name || '';
}
async function pickDevice(id) {
  currentDevice.value = id;
  const r = await api.sysPost('audio_device', { device: id });
  say(r.ok && r.data.success !== false ? t('settings.audio.changed') : bodyMsg(r, t('settings.audio.changeFailed')), !(r.ok && r.data.success !== false));
}
async function saveName() {
  const r = await api.sysPost('device_name', { name: playerName.value });
  say(r.ok && r.data.success !== false ? t('settings.audio.nameSaved') : bodyMsg(r, t('settings.audio.saveFailed')), !(r.ok && r.data.success !== false));
}

// ── Playback (per-player Lyrion prefs: transitions, ReplayGain, fixed volume) ──
// Mirrors the kiosk's Settings.jsx loadPlaybackPrefs: `players_loop` isn't
// necessarily "this appliance first" (companion-app SqueezePlayer, other
// multiroom players can also be in the list) — resolve by matching this
// device's own squeezelite name, same as the kiosk and the "audio" section's
// player_name lookup above.
const playbackMac = ref(null);
const transitionType = ref('0');     // 0 none … 4 fade in/out
const transitionDuration = ref('10'); // seconds
const replayGainMode = ref('0');     // 0 off / 1 track / 2 album / 3 smart
// digitalVolumeControl: 1 = LMS applies its own digital volume (adjustable),
// 0 = output fixed at 100% — required for bit-perfect playback.
const digitalVolumeControl = ref('1');
async function loadPlayback() {
  try {
    const players = await api.lyrionPlayers();
    const localName = playerName.value || (await api.sys('player_name')).data?.name;
    const local = localName && players.find((p) => p.name === localName);
    const mac = (local || players[0])?.playerid;
    if (!mac) { playbackMac.value = null; return; }
    playbackMac.value = mac;
    const [tt, td, rg, dvc] = await Promise.all([
      api.lyrionGetPref(mac, 'transitionType'),
      api.lyrionGetPref(mac, 'transitionDuration'),
      api.lyrionGetPref(mac, 'replayGainMode'),
      api.lyrionGetPref(mac, 'digitalVolumeControl'),
    ]);
    if (tt != null) transitionType.value = String(tt);
    if (td != null) transitionDuration.value = String(td);
    if (rg != null) replayGainMode.value = String(rg);
    if (dvc != null) digitalVolumeControl.value = String(dvc);
  } catch (_) { playbackMac.value = null; }
}
// The page loads everything once on mount; a player that connected to Lyrion
// afterwards would stay "not found" until a reload. Look again on opening.
watch(open, (k) => { if (k === 'playback') loadPlayback(); });
function setTransitionType(v) {
  transitionType.value = v;
  if (playbackMac.value) api.lyrionSetPref(playbackMac.value, 'transitionType', v);
  say(t('settings.playback.saved'));
}
function setTransitionDuration(v) {
  transitionDuration.value = v;
  if (playbackMac.value) api.lyrionSetPref(playbackMac.value, 'transitionDuration', v);
  say(t('settings.playback.saved'));
}
function setReplayGain(v) {
  replayGainMode.value = v;
  if (playbackMac.value) api.lyrionSetPref(playbackMac.value, 'replayGainMode', v);
  say(t('settings.playback.saved'));
}
function setFixedVolume(on) {
  const next = on ? '0' : '1';
  digitalVolumeControl.value = next;
  if (playbackMac.value) api.lyrionSetPref(playbackMac.value, 'digitalVolumeControl', next);
  say(t('settings.playback.saved'));
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

// ── Tidal / SSH ─────────────────────────────────────────────────
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
  say(bodyMsg(r, v ? t('settings.services.sshOn') : t('settings.services.sshOff')), !(r.ok && r.data.success !== false));
  loadToggles(); loadShell();
}

// ── SSH login (Linux account) ────────────────────────────────────────
// The appliance used to ship user 'hifi' with the documented password 'hifi'
// and no sudo, which made SSH both unsafe and useless. The login is now the
// admin account, mirrored into a real Linux user with sudo at account creation
// and at every password change. Devices provisioned before that shipped have no
// such user yet, so this panel can create one on demand.
const shell = reactive({ supported: true, exists: false, username: '', form: '', password: '', busy: false });
async function loadShell() {
  const r = await api.sys('shell_account');
  // Older api_server has no such endpoint — hide the whole block rather than
  // showing a broken form (the UI bundle can land before the system bundle).
  shell.supported = r.ok && r.data && typeof r.data.exists === 'boolean';
  if (!shell.supported) return;
  shell.exists = !!r.data.exists;
  shell.username = r.data.username || '';
  if (!shell.form) shell.form = r.data.username || acc.username || '';
}
async function saveShellAccount() {
  shell.busy = true;
  const r = await api.sysPost('shell_account', { username: shell.form, password: shell.password });
  shell.busy = false;
  const ok = r.ok && r.data.success !== false;
  say(bodyMsg(r, ok ? t('settings.services.sshLoginSaved') : t('settings.services.sshLoginFailed')), !ok);
  if (ok) { shell.password = ''; loadShell(); }
}
// ── Bluetooth speakers (A2DP source) ─────────────────────────────
// Pair a speaker or a pair of headphones and it becomes a Lyrion player of
// its own — its own name, its own queue — next to the device's built-in
// player, which keeps the DAC to itself throughout. api_server does the
// pairing and the connecting; a supervisor on the device does the rest (and
// the reconnecting), so everything here is: send a command, take the state
// that comes back.
const bt = reactive({
  available: false, enabled: false, adapter: false, speakers: [], found: [],
  busy: false, scanning: false, open: '', name: '',
});
let btPoll = null;
function applyBt(d) {
  bt.available = !!d.available; bt.enabled = !!d.enabled; bt.adapter = !!d.adapter;
  bt.speakers = d.speakers || []; bt.found = d.found || [];
}
async function loadBt() {
  const r = await api.sys('bt_speakers');
  if (r.ok && r.data && r.data.available !== undefined) applyBt(r.data);
}
// Every /bt_speakers/* reply carries the whole state, so one helper unpacks
// them all — and one place decides what the owner is told.
async function btCall(path, body) {
  bt.busy = true;
  const r = await api.sysPost(path, body || {});
  bt.busy = false; bt.scanning = false;
  if (r.ok && r.data && r.data.available !== undefined) {
    applyBt(r.data);
    if (r.data.message) say(r.data.message, r.data.success === false);
    return r.data.success !== false;
  }
  say(bodyMsg(r, t('settings.btSpeakers.opFailed')), true);
  return false;
}
const setBt = (v) => btCall('bt_speakers/enable', { enable: v });
async function btScan() { bt.scanning = true; await btCall('bt_speakers/scan', { seconds: 12 }); }
const btAdd = (mac) => btCall('bt_speakers/add', { mac });
const btConnect = (sp) => btCall('bt_speakers/connect', { mac: sp.mac, connect: !sp.connected });
const btAuto = (sp) => btCall('bt_speakers/update', { mac: sp.mac, autoconnect: !sp.autoconnect });
function btRename(sp) {
  const name = (bt.name || '').trim();
  if (!name || name === sp.player) return;
  return btCall('bt_speakers/update', { mac: sp.mac, player: name });
}
async function btForget(sp) {
  if (!confirm(t('settings.btSpeakers.forgetConfirm', { name: sp.player || sp.name }))) return;
  bt.open = '';
  await btCall('bt_speakers/remove', { mac: sp.mac });
}
function btToggle(sp) {
  bt.open = bt.open === sp.mac ? '' : sp.mac;
  bt.name = sp.player || '';
}
function btState(sp) {
  if (!sp.enabled) return t('settings.btSpeakers.switchedOff');
  if (sp.playing) return t('settings.btSpeakers.ready');
  if (sp.connected) return t('settings.btSpeakers.connecting');
  return t('settings.btSpeakers.notConnected');
}
// Only polled while the section is open, and never on top of a command in
// flight: with the adapter up, answering it runs bluetoothctl once per known
// device.
watch(open, (k) => {
  if (btPoll) { clearInterval(btPoll); btPoll = null; }
  if (k !== 'btSpeakers') return;
  loadBt();
  btPoll = setInterval(() => { if (!bt.busy) loadBt(); }, 5000);
}, { immediate: true });

// ── Telecomando ───────────────────────────────────────────────────
// I tasti li legge l'interfaccia sullo schermo, che possiede /dev/input
// (native-ui-qt/src/remote.cpp); qui si vede la stessa fotografia attraverso
// api_server (/remote) e si accoppia un telecomando Bluetooth (/bt_remotes).
// 🚨 La prova dei tasti apre una finestra con scadenza sull'apparecchio: per
// quel tempo i tasti si vedono qui e NON comandano l'interfaccia, cosi' chi
// prova da lontano non fa partire un album per sbaglio. Si chiude da sola.
const rc = reactive({
  devices: [], chosen: '', keys: { all: {}, devices: {} }, actions: [],
  lastKey: {}, learning: false, interfaceRunning: false,
  busy: false, testing: false,
  bt: { available: false, supported: false, adapter: false, remotes: [], found: [], scanning: false },
});
let rcPoll = null;

async function loadRemote() {
  const r = await api.sys('remote');
  if (r.ok && r.data) Object.assign(rc, r.data);
}
async function loadRemoteBt() {
  const r = await api.sys('bt_remotes');
  if (r.ok && r.data && r.data.available !== undefined) Object.assign(rc.bt, r.data);
}
async function rcCall(path, body, reload = loadRemote) {
  rc.busy = true;
  const r = await api.sysPost(path, body || {});
  rc.busy = false; rc.bt.scanning = false;
  if (r.ok && r.data) {
    if (r.data.available !== undefined) Object.assign(rc.bt, r.data);
    else Object.assign(rc, r.data);
    if (r.data.message) say(r.data.message, r.data.success === false);
    if (reload) await reload();
    return r.data.success !== false;
  }
  say(bodyMsg(r, t('settings.remote.opFailed')), true);
  return false;
}
// "questo e' il mio telecomando": l'unico modo per non confondere una
// tastiera e un telecomando, che mandano gli stessi codici
const rcMine = (d) => rcCall('remote/device', { device: rc.chosen === d.name ? '' : d.name });
// La prova dei tasti: si accende mentre la scheda e' aperta, e si spegne
// uscendo. La scadenza sull'apparecchio e' la rete di sicurezza.
async function rcTest(on) {
  rc.testing = on;
  await rcCall('remote/learn', { enable: on });
}
const rcAssign = (code, action, device) => rcCall('remote/keys', { code, action, device: device || '' });
const rcUnassign = (code, device) => rcCall('remote/keys', { code, device: device || '' });
// quale azione fa oggi quel tasto su quel dispositivo
function rcActionOf(code, device) {
  const k = String(code);
  const d = (rc.keys.devices || {})[device] || {};
  if (k in d) return d[k];
  const all = rc.keys.all || {};
  return k in all ? all[k] : '';
}
const rcIsCustom = (code, device) => {
  const k = String(code);
  return k in ((rc.keys.devices || {})[device] || {}) || k in (rc.keys.all || {});
};
const rcActionLabel = (a) => (a ? t('settings.remote.actions.' + a) : t('settings.remote.doesNothing'));
const rcWhere = (d) => (d.bus === 'bluetooth' ? t('settings.remote.viaBluetooth')
                      : d.bus === 'usb' ? t('settings.remote.viaUsb') : t('settings.remote.viaOther'));
async function rcScan() { rc.bt.scanning = true; await rcCall('bt_remotes/scan', { seconds: 12 }, loadRemoteBt); }
const rcPair = (mac) => rcCall('bt_remotes/add', { mac }, loadRemoteBt);
const rcForget = (mac) => rcCall('bt_remotes/remove', { mac }, loadRemoteBt);
// Un telecomando Bluetooth collegato dovrebbe comparire anche fra i
// dispositivi di input: se non c'e', i suoi tasti non arrivano (succede
// quando il nucleo rifiuta la mappa che il telecomando dichiara).
const rcHasKeys = (name) => !name || rc.devices.some((d) => d.name.startsWith(name) || name.startsWith(d.name));

watch(open, (k) => {
  if (rcPoll) { clearInterval(rcPoll); rcPoll = null; }
  if (k !== 'remote') { if (rc.testing) rcTest(false); return; }
  loadRemote(); loadRemoteBt();
  rcPoll = setInterval(() => { if (!rc.busy) loadRemote(); }, rc.testing ? 1000 : 4000);
}, { immediate: true });
onUnmounted(() => { if (rcPoll) clearInterval(rcPoll); if (rc.testing) rcTest(false); });

// ── Tailscale — join the owner's own tailnet, exposing every port on this
// appliance (web UI, Lyrion, SMB, ...) from anywhere that tailnet reaches, so
// the music library stays reachable away from home. Not the old remote-support
// flow: no vendor infra, no approval step — `tailscale up` prints a one-time
// login URL the owner opens on ANY device to approve this node from their own
// account, no auth key to generate/paste. If Tailscale isn't installed yet
// (device missed the build-time/OTA install), a button installs it on demand.
const tailscale = reactive({ available: true, connected: false, ip: '', busy: false, installing: false, loginUrl: '', derpRegion: '', derpLatencyMs: null });
let tailscalePoll = null;
async function loadTailscale() {
  const r = await api.sys('tailscale');
  if (r.ok) {
    tailscale.available = !!r.data.available;
    tailscale.connected = !!r.data.connected;
    tailscale.ip = r.data.ip || '';
    tailscale.derpRegion = r.data.derp_region || '';
    tailscale.derpLatencyMs = r.data.derp_latency_ms ?? null;
    if (tailscale.connected) tailscale.loginUrl = '';
  }
}
async function installTailscaleNow() {
  tailscale.installing = true;
  const r = await api.sysPost('tailscale_install', {});
  tailscale.installing = false;
  const ok = r.ok && r.data.success !== false;
  say(bodyMsg(r, ok ? t('settings.tailscale.installed') : t('settings.tailscale.installFailed')), !ok);
  if (ok) loadTailscale();
}
async function setTailscale(v) {
  tailscale.busy = true;
  if (!v) tailscale.loginUrl = '';
  const r = await api.sysPost('tailscale', { enable: v });
  tailscale.busy = false;
  const ok = r.ok && r.data.success !== false;
  if (ok && v) {
    tailscale.loginUrl = r.data.login_url || '';
    if (!tailscalePoll) {
      tailscalePoll = setInterval(async () => {
        await loadTailscale();
        if (tailscale.connected) { clearInterval(tailscalePoll); tailscalePoll = null; }
      }, 3000);
    }
  }
  say(bodyMsg(r, ok
    ? (v ? (r.data.login_url ? t('settings.tailscale.openLink') : t('settings.tailscale.on')) : t('settings.tailscale.off'))
    : t('settings.tailscale.failed')), !ok);
  loadTailscale();
}

// ── Lyrion Music Server: internal vs external, plus install/update ─────
// 'internal'/'external' is the user-facing vocabulary (forum feedback: "own /
// follow another" read as jargon). The wire protocol keeps the original
// 'local'/'follow' role names — squeezelite's -s argument is what actually
// changes, see api_server.set_lms_role.
// mode/host are what the form shows (the External button and the address
// field write to them before anything is applied); savedMode/savedHost are
// what the device actually runs, so "did this really change?" can be asked.
const lms = reactive({ mode: 'local', host: '', servers: [], savedMode: 'local', savedHost: '' });
async function loadLms() {
  const r = await api.sys('lms_role');
  if (r.ok) {
    lms.mode = r.data.mode || 'local';
    lms.host = r.data.host || '';
    lms.savedMode = lms.mode;
    lms.savedHost = lms.host;
  }
}
async function discoverLms() {
  say(t('settings.lyrion.searching'));
  const r = await api.sys('discover_lms'); if (r.ok) { lms.servers = r.data.servers || []; say(''); }
}
// Switching between this device's own server and one on the network only
// half-applies on a running box, so the change ends in a reboot — asked for
// up front, and skipped entirely when the choice is already the live one.
async function applyLmsRole(mode, hostArg) {
  const target = mode === 'follow' ? (hostArg || lms.host || null) : null;
  const unchanged = mode === 'local'
    ? lms.savedMode !== 'follow'
    : (lms.savedMode === 'follow' && target === lms.savedHost);
  if (unchanged) { lms.mode = mode; return; }
  if (!confirm(t('settings.lyrion.rebootWarning'))) return;
  const r = await api.sysPost('lms_role', { mode, host: target });
  const ok = r.ok && r.data.success !== false;
  say(bodyMsg(r, t('settings.lyrion.roleUpdated')), !ok);
  if (!ok) { loadLms(); return; }
  await api.sysPost('reboot', {});
  waitForReboot();
}

// Install/update of Lyrion itself. This used to sit on the Updates page next to
// the appliance's own components; it belongs with the internal/external choice,
// because "which server do I use" and "which build of it do I run" are one
// decision. The Updates page is now only about the appliance's own software.
const lyrion = reactive({
  supported: true,       // false on an older api_server (no /lyrion_channel yet)
  channel: 'release',
  current: '',
  channels: {},          // { release|nightly|dev: { version, url } }
  updateAvailable: false, // is channels[channel].version newer than `current`?
  busy: false, installing: false, progress: 0, message: '', error: '',
});
const LYRION_CHANNELS = ['release', 'nightly', 'dev'];
const lyrionChannelLabel = (c) => t(`settings.lyrion.channel_${c}`);

async function loadLyrion() {
  lyrion.busy = true;
  // Feature-detect: the UI bundle can land before the system bundle that ships
  // these endpoints (apply order is ui → os → system), so a 403/404 here must
  // degrade to "no channel picker" rather than an empty section.
  const ch = await api.sys('lyrion_channel');
  lyrion.supported = ch.ok && !!ch.data.channel;
  if (lyrion.supported) lyrion.channel = ch.data.channel;
  const r = await api.sys('updates/lyrion/check');
  if (r.ok) {
    lyrion.current = r.data.current && r.data.current !== 'unknown' ? r.data.current : '';
    lyrion.channels = r.data.channels || {};
    if (r.data.channel) lyrion.channel = r.data.channel;
    lyrion.error = r.data.error || '';
    lyrion.updateAvailable = !!r.data.update_available;
  }
  lyrion.busy = false;
}

async function pickLyrionChannel(c) {
  if (lyrion.installing || c === lyrion.channel) return;
  lyrion.channel = c;
  const r = await api.sysPost('lyrion_channel', { channel: c });
  say(bodyMsg(r, t('settings.lyrion.channelChanged')), !(r.ok && r.data.success !== false));
  loadLyrion();
}

let lyrionPoll = null;
async function installLyrion() {
  lyrion.installing = true; lyrion.error = ''; lyrion.progress = 5;
  lyrion.message = t('settings.lyrion.installing');
  const r = await api.sysPost('updates/lyrion/apply', { channel: lyrion.channel });
  if (!(r.ok && r.data.started !== false)) {
    lyrion.installing = false;
    lyrion.error = bodyMsg(r, t('settings.lyrion.installFailed'));
    return;
  }
  // Runs as a detached systemd unit; poll its status file.
  lyrionPoll = setInterval(async () => {
    const s = await api.sys('updates/lyrion/status');
    const d = s.data || {};
    if (typeof d.progress === 'number') lyrion.progress = d.progress;
    if (d.state) lyrion.message = progressStateMessage(d.state, d.message || '');
    if (d.state === 'done' || d.state === 'error') {
      clearInterval(lyrionPoll); lyrionPoll = null;
      lyrion.installing = false;
      if (d.state === 'done') { lyrion.progress = 100; loadLyrion(); }
      else lyrion.error = d.message || t('settings.lyrion.installFailed');
    }
  }, 2000);
}

// ── LMS web skin (Osmium / Material) ────────────────────────────────
// Which look Lyrion's web player serves. 'unset' = legacy device that never
// chose (nothing has been touched); picking either value installs Material if
// needed (sources_server does the work) and sets it as the :9000 root skin.
const skin = reactive({ choice: 'unset', supported: true, busy: false, message: '', error: '' });
let skinPoll = null;

async function loadSkin() {
  // Feature-detect like loadLyrion(): the UI bundle can land before the
  // system bundle that ships /api/system/lms_skin.
  const r = await api.sys('lms_skin');
  skin.supported = r.ok && !!r.data.skin;
  if (skin.supported) skin.choice = r.data.skin;
}

function skinStateMessage(state, raw) {
  if (state === 'installing') return t('settings.lyrion.skinInstalling');
  if (state === 'applying') return t('settings.lyrion.skinApplying');
  return raw || '';
}

async function pickSkin(v) {
  if (skin.busy || v === skin.choice) return;
  skin.busy = true; skin.error = ''; skin.message = t('settings.lyrion.skinApplying');
  const r = await api.sysPost('lms_skin', { skin: v });
  if (!(r.ok && r.data.started)) {
    skin.busy = false;
    skin.error = bodyMsg(r, t('settings.lyrion.skinFailed'));
    return;
  }
  skin.choice = v;
  skinPoll = setInterval(async () => {
    const s = await api.sys('lms_skin_status');
    const d = s.data || {};
    skin.message = skinStateMessage(d.state, d.message);
    if (d.state === 'done' || d.state === 'error') {
      clearInterval(skinPoll); skinPoll = null;
      skin.busy = false;
      if (d.state === 'done') say(t('settings.lyrion.skinChanged'));
      else skin.error = d.message || t('settings.lyrion.skinFailed');
    }
  }, 1500);
}

// Where LMS links should land: Material's page once a skin choice exists
// (with the Osmium theme pre-selected for new browsers), the bare root
// (classic skin) on legacy/unset devices. On a device that follows another
// server the music lives THERE, so the link follows it — bare root, because
// the skin choice only applies to this device's own server and /material/
// need not exist on the other one (a server's root serves its default skin).
const lmsUrl = computed(() => {
  if (lms.savedMode === 'follow' && lms.savedHost) return `http://${lms.savedHost}:9000`;
  if (skin.choice === 'osmium') return `http://${host}:9000/material/?defaultTheme=dark/Osmium`;
  if (skin.choice === 'material') return `http://${host}:9000/material/`;
  return `http://${host}:9000`;
});

// ── display mode ─────────────────────────────────────────────────
const mode = ref('');
async function loadMode() { const r = await api.sys('display_mode'); if (r.ok) mode.value = r.data.mode; }
async function setMode(m) {
  if (m === 'headless' && !confirm(t('settings.display.confirmHeadless'))) return;
  const r = await api.sysPost('display_mode', { mode: m });
  if (r.ok && r.data.success !== false) { mode.value = r.data.mode || m; say(bodyMsg(r, t('settings.display.changed'))); }
  else say(bodyMsg(r, t('settings.display.changeFailed')), true);
}

// ── Quale interfaccia gira sullo schermo ────────────────────────────
// Electron (quella storica, dentro la sessione lightdm) oppure Qt (disegna
// diritto su DRM/KMS). Il server filtra l'elenco: `engines` contiene "qt"
// solo se i suoi file sono davvero installati, così un apparecchio che non ha
// ancora ricevuto il pacchetto non mostra uno scambio che lo lascerebbe con
// lo schermo nero.
const engine = ref('');
const engines = ref([]);
async function loadEngine() {
  const r = await api.sys('ui_engine');
  if (r.ok) { engine.value = r.data.engine; engines.value = r.data.engines || []; }
}
async function setEngine(e) {
  if (e === engine.value) return;
  if (!confirm(t('settings.display.confirmEngine'))) return;
  const r = await api.sysPost('ui_engine', { engine: e });
  if (r.ok && r.data.success !== false) { engine.value = r.data.engine || e; say(bodyMsg(r, t('settings.display.engineChanged'))); }
  else say(bodyMsg(r, t('settings.display.engineFailed')), true);
}

// ── Player enabled/disabled ─────────────────────────────────────────
// Orthogonal to display mode above: whether this device plays audio at all
// (squeezelite), for a "server only" unit that keeps Lyrion running but
// never plays audio locally.
const playerEnabled = ref(true);
async function loadPlayerEnabled() {
  const r = await api.sys('player_enabled');
  if (r.ok && typeof r.data.enabled === 'boolean') playerEnabled.value = r.data.enabled;
}
async function setPlayerEnabled(enabled) {
  if (!enabled && !confirm(t('settings.display.confirmPlayerOff'))) return;
  const r = await api.sysPost('player_enabled', { enabled });
  if (r.ok && r.data.success !== false) { playerEnabled.value = r.data.enabled; say(bodyMsg(r, t('settings.display.playerChanged'))); }
  else say(bodyMsg(r, t('settings.display.playerChangeFailed')), true);
}

// ── UI render resolution ─────────────────────────────────────────
// Shrinks the X framebuffer on big panels (the GPU upscales it during
// scanout) so the appliance stops rasterizing 2..8 Mpixel per repaint.
// Applying restarts the device's graphical session, not this web page.
const uiRes = ref('');
async function loadUiRes() { const r = await api.sys('ui_resolution'); if (r.ok) uiRes.value = r.data.mode; }
async function setUiRes(m) {
  if (m === uiRes.value) return;
  if (!confirm(t('settings.display.confirmResolution'))) return;
  const r = await api.sysPost('ui_resolution', { mode: m });
  if (r.ok && r.data.success !== false) { uiRes.value = r.data.mode || m; say(bodyMsg(r, t('settings.display.resolutionChanged'))); }
  else say(bodyMsg(r, t('settings.display.resolutionFailed')), true);
}

// ── Panel refresh rate ─────────────────────────────────────────────
// Native <-> low-power CRTC refresh — orthogonal to uiRes above (that shrinks
// the framebuffer area; this only changes how many times per second it's
// scanned out). Both the X scale-blit and the on-screen compositor are
// vblank-paced, so halving the refresh roughly halves both: measured ~40%
// less GPU render-engine busy on this hardware, same content. Applies live,
// no session restart — the Electron window's size never changes. Not every
// panel offers a distinct low-refresh mode for its native resolution;
// 'supported' reflects that so the control can be hidden instead of offering
// a toggle that would silently do nothing. No auto-revert-if-unconfirmed
// here (unlike the kiosk UI) — this page isn't the screen being changed, so
// there's no risk of losing access to it.
const uiRefresh = ref('');
const uiRefreshSupported = ref(true);
async function loadUiRefresh() {
  const r = await api.sys('ui_refresh');
  if (r.ok) { uiRefresh.value = r.data.mode; uiRefreshSupported.value = r.data.supported !== false; }
}
async function setUiRefresh(m) {
  if (m === uiRefresh.value) return;
  if (m === 'low' && !confirm(t('settings.display.confirmRefresh'))) return;
  const r = await api.sysPost('ui_refresh', { mode: m });
  if (r.ok && r.data.success !== false) { uiRefresh.value = r.data.mode || m; say(bodyMsg(r, t('settings.display.refreshChanged'))); }
  else say(bodyMsg(r, t('settings.display.refreshChangeFailed')), true);
}

// ── Timezone ────────────────────────────────────────────────────────
// Fresh installs default to UTC (no timezone question in the installer —
// see distro/README.md), so this is the only place to actually correct it.
const timezone = ref('');
const timezoneList = ref([]);
const timezoneBusy = ref(false);
async function loadTimezone() {
  const [tz, list] = await Promise.all([api.sys('timezone'), api.sys('timezones')]);
  if (tz.ok) timezone.value = tz.data.timezone;
  if (list.ok && Array.isArray(list.data.timezones)) timezoneList.value = list.data.timezones;
}
async function setTimezone(tz) {
  if (!tz || tz === timezone.value) return;
  timezoneBusy.value = true;
  const r = await api.sysPost('timezone', { timezone: tz });
  timezoneBusy.value = false;
  if (r.ok && r.data.success !== false) { timezone.value = r.data.timezone || tz; say(bodyMsg(r, t('settings.timezone.changed'))); }
  else say(bodyMsg(r, t('settings.timezone.changeFailed')), true);
}
// Timezone can also change out from under this page — set from the on-device
// player UI, or vice versa. Poll it while the tab is visible, same pattern as
// the other status polls on this page, guarded against clobbering a change
// this page just made itself.
let timezonePoll = null;
async function pollTimezone() {
  if (document.visibilityState !== 'visible' || timezoneBusy.value) return;
  const tz = await api.sys('timezone');
  if (tz.ok && tz.data.timezone) timezone.value = tz.data.timezone;
}

// ── Animated VU meter ──────────────────────────────────────────────
// Pure rendering choice, no restart — but reachable from here (not just the
// on-screen Settings) because that's the only way to reach it on a headless
// unit, or without walking up to the screen at all.
const vuMeter = ref(true);
async function loadVuMeter() { const r = await api.sys('vu_meter'); if (r.ok) vuMeter.value = r.data.enabled !== false; }
async function setVuMeter(enable) {
  if (enable === vuMeter.value) return;
  const r = await api.sysPost('vu_meter', { enable });
  if (r.ok && r.data.success !== false) { vuMeter.value = r.data.enabled; say(bodyMsg(r, t('settings.vuMeters.saved'))); }
  else say(bodyMsg(r, t('settings.vuMeters.failed')), true);
}

// ── VU meter style ─────────────────────────────────────────────────
// The skins the on-screen interface has installed, as the device lists them
// (a new one appears here without touching this page). Names come in both
// languages from the skin itself.
const vuStyle = ref('classic');
const vuStyles = ref([]);
async function loadVuStyle() {
  const r = await api.sys('vu_style');
  if (r.ok) { vuStyle.value = r.data.style || 'classic'; vuStyles.value = r.data.styles || []; }
}
function vuStyleName(st) { return (st.name && (st.name[lang.value] || st.name.en)) || st.id; }
async function setVuStyle(style) {
  if (style === vuStyle.value) return;
  const r = await api.sysPost('vu_style', { style });
  if (r.ok && r.data.success !== false) { vuStyle.value = r.data.style; say(bodyMsg(r, t('settings.vuMeters.styleSaved'))); }
  else say(bodyMsg(r, t('settings.vuMeters.failed')), true);
}

// ── Now-playing animation ──────────────────────────────────────────
// A CD, vinyl record or cassette the kiosk shows where the VU meters would be,
// only while they are off. The two settings stay independent on the device,
// so this just stores the pick. Choices come from the device: the built-in
// ones this page has a name for, then those downloaded from the animation
// store, named by their own anim.json.
const NP_ANIMATION_IDS = ['none', 'cd', 'cdfront', 'vinyl', 'cassette'];
const npAnimation = ref('none');
const npAnimations = ref(NP_ANIMATION_IDS);
const npStoreAnims = ref([]);
async function loadNpAnimation() {
  const r = await api.sys('nowplaying_animation');
  if (!r.ok) return;
  npAnimation.value = r.data.animation || 'none';
  npStoreAnims.value = Array.isArray(r.data.store) ? r.data.store : [];
  const known = (r.data.choices || []).filter((id) => NP_ANIMATION_IDS.includes(id));
  if (known.length) npAnimations.value = known.concat(npStoreAnims.value.map((a) => a.id));
}
// the stills of the built-in scenes, as the kiosk draws them on its own
// cards (NpAnimation with live: false, captured from the kiosk); a store
// animation shows the preview its catalogue entry carries
const NP_ANIMATION_PREVIEWS = { cd: animCd, cdfront: animCdfront, vinyl: animVinyl, cassette: animCassette };
function npAnimPreview(id) {
  if (NP_ANIMATION_PREVIEWS[id]) return NP_ANIMATION_PREVIEWS[id];
  const a = animStore.animations.find((x) => x.id === id);
  return (a && a.preview) || null;
}
function npAnimLabel(id) {
  if (NP_ANIMATION_IDS.includes(id)) return t('settings.animations.choice.' + id);
  const a = npStoreAnims.value.find((x) => x.id === id);
  return (a && a.name && (a.name[lang.value] || a.name.en)) || id;
}

// ── Animation store ────────────────────────────────────────────────
// More animations published by Osmium Sound, downloaded and checked by the
// device itself, like the VU meter store below. A finished install refreshes
// the choices above.
const animStore = reactive({ animations: [], checking: false, busy: false, error: null, loaded: false });
const animStoreSeen = ref(false);
let animStorePoll = null;
async function loadAnimStore(markSeen) {
  const r = await api.sys('anim_store');
  if (!r.ok) { animStore.loaded = true; animStore.checking = false; animStore.busy = false; return; }
  const wasBusy = animStore.busy;
  Object.assign(animStore, { animations: r.data.animations || [], checking: !!r.data.checking, busy: !!r.data.busy, error: r.data.error || null, loaded: true });
  if (wasBusy && !animStore.busy) loadNpAnimation();
  if (markSeen && animStore.animations.length) { api.sysPost('anim_store/seen', {}); animStoreSeen.value = true; }
  if ((animStore.checking || animStore.busy) && !animStorePoll) animStorePoll = setInterval(() => loadAnimStore(false), 1500);
  if (!animStore.checking && !animStore.busy && animStorePoll) { clearInterval(animStorePoll); animStorePoll = null; }
}
function animStoreName(a) { return (a.name && (a.name[lang.value] || a.name.en)) || a.id; }
async function installAnim(a) {
  const r = await api.sysPost('anim_store/install', { id: a.id });
  if (!r.ok || r.data.success === false) say(bodyMsg(r, t('settings.animations.storeFailed')), true);
  loadAnimStore(false);
}
async function removeAnim(a) {
  if (!window.confirm(t('settings.animations.removeConfirm', { name: animStoreName(a) }))) return;
  const r = await api.sysPost('anim_store/remove', { id: a.id });
  if (!r.ok || r.data.success === false) say(bodyMsg(r, t('settings.animations.storeFailed')), true);
  loadNpAnimation(); loadAnimStore(false);
}
const animStoreNew = computed(() => (animStoreSeen.value ? 0 : animStore.animations.filter((a) => a.new || a.update).length));
watch(open, (k) => { if (k === 'animations') loadAnimStore(true); }, { immediate: true });
async function checkAnimStore() {
  await api.sysPost('anim_store/check', {});
  animStore.checking = true;
  loadAnimStore(false);
}
async function setNpAnimation(animation) {
  if (animation === npAnimation.value) return;
  const r = await api.sysPost('nowplaying_animation', { animation });
  if (r.ok && r.data.success !== false) { npAnimation.value = r.data.animation; say(bodyMsg(r, t('settings.animations.saved'))); }
  else say(bodyMsg(r, t('settings.animations.failed')), true);
}

// ── VU meter store ─────────────────────────────────────────────────
// More looks published by Osmium Sound, downloaded by the device itself (the
// list is signed and checked there). Re-read while the device checks the
// list or installs a skin; a finished install refreshes the styles above.
const vuStore = reactive({ skins: [], checking: false, busy: false, error: null, loaded: false });
const vuStoreSeen = ref(false);
let vuStorePoll = null;
async function loadVuStore(markSeen) {
  const r = await api.sys('vu_store');
  if (!r.ok) { vuStore.loaded = true; vuStore.checking = false; vuStore.busy = false; return; }
  const wasBusy = vuStore.busy;
  Object.assign(vuStore, { skins: r.data.skins || [], checking: !!r.data.checking, busy: !!r.data.busy, error: r.data.error || null, loaded: true });
  if (wasBusy && !vuStore.busy) loadVuStyle();
  if (markSeen && vuStore.skins.length) { api.sysPost('vu_store/seen', {}); vuStoreSeen.value = true; }
  if ((vuStore.checking || vuStore.busy) && !vuStorePoll) vuStorePoll = setInterval(() => loadVuStore(false), 1500);
  if (!vuStore.checking && !vuStore.busy && vuStorePoll) { clearInterval(vuStorePoll); vuStorePoll = null; }
}
function vuStoreSize(bytes) {
  return (Number(bytes || 0) / 1048576).toLocaleString(lang.value, { maximumFractionDigits: 1, minimumFractionDigits: 1 }) + ' MB';
}
async function installVuSkin(sk) {
  const r = await api.sysPost('vu_store/install', { id: sk.id });
  if (!r.ok || r.data.success === false) say(bodyMsg(r, t('settings.vuMeters.storeFailed')), true);
  loadVuStore(false);
}
async function removeVuSkin(sk) {
  if (!window.confirm(t('settings.vuMeters.removeConfirm', { name: vuStyleName(sk) }))) return;
  const r = await api.sysPost('vu_store/remove', { id: sk.id });
  if (!r.ok || r.data.success === false) say(bodyMsg(r, t('settings.vuMeters.storeFailed')), true);
  loadVuStyle(); loadVuStore(false);
}
// news in the store (new skins, or updates of downloaded ones): the dot on the
// section's row, gone once the section has been opened. The cards keep their
// NEW badge for this visit, as on the kiosk.
const vuStoreNew = computed(() => (vuStoreSeen.value ? 0 : vuStore.skins.filter((sk) => sk.new || sk.update).length));
watch(open, (k) => { if (k === 'vuMeters') loadVuStore(true); }, { immediate: true });
async function checkVuStore() {
  await api.sysPost('vu_store/check', {});
  vuStore.checking = true;
  loadVuStore(false);
}

// ── Mouse pointer (cursor) — mirrors the kiosk's Settings.jsx pointer
// toggle. Shown by default (the on-device QR/Wi-Fi wizard needs a visible
// cursor); a touchscreen owner can hide it here or from the kiosk itself.
const pointer = reactive({ available: true, enabled: true });
const pointerBusy = ref(false);
async function loadPointer() {
  const r = await api.sys('pointer_status');
  if (r.ok) { pointer.available = !!r.data.available; pointer.enabled = r.data.enabled !== false; }
}
async function setPointer(enable) {
  if (pointerBusy.value || enable === pointer.enabled) return;
  pointerBusy.value = true;
  const r = await api.sysPost('pointer_set', { enable });
  pointerBusy.value = false;
  if (r.ok && r.data.success !== false) { pointer.enabled = r.data.enabled; say(r.data.message || t('settings.display.pointerChanged')); }
  else say(bodyMsg(r, t('settings.display.pointerFailed')), true);
}

// ── Now-playing auto-expand ─────────────────────────────────────────
// How long after a song starts playing the kiosk auto-opens its fullscreen
// now-playing view on its own. 0 = disabled. Same "reachable here for a
// headless unit" reasoning as vuMeter above.
const autoExpand = ref(0);
async function loadAutoExpand() { const r = await api.sys('nowplaying_autoexpand'); if (r.ok) autoExpand.value = r.data.seconds || 0; }
async function setAutoExpand(seconds) {
  if (seconds === autoExpand.value) return;
  const r = await api.sysPost('nowplaying_autoexpand', { seconds });
  if (r.ok && r.data.success !== false) { autoExpand.value = r.data.seconds; say(bodyMsg(r, t('settings.playback.autoExpandChanged'))); }
  else say(bodyMsg(r, t('settings.playback.autoExpandFailed')), true);
}

// ── updates (prod/dev[/alpha] channel; single "update all" + blocking modal) ─
const channel = ref('prod');
// 'alpha' only ever appears here when the server reports it (i.e. the device
// has /etc/hifi-player/ota-alpha-unlocked) — mirrors the kiosk UI's
// otaChannels state (src/pages/Settings.jsx).
const channels = ref(['prod', 'dev']);
const otaChannelLabel = (c) => t(`settings.updates.${{ prod: 'channelProd', dev: 'channelDev', alpha: 'channelAlpha' }[c] || 'channelDev'}`);
const upd = reactive({ ui: null, system: null, os: null });
const updBusy = ref(false);
// Lyrion is deliberately NOT here: it is third-party software with its own
// release cadence, managed from Settings → Lyrion Music Server. This page is
// only about the appliance's own components.
const kinds = { ui: 'app', system: 'system', os: 'os' };
const kindLabels = computed(() => ({
  ui: t('settings.updates.kindUi'), system: t('settings.updates.kindSystem'),
  os: t('settings.updates.kindOs'), image: t('settings.updates.kindImage'),
}));
// Blocking overlay state — mirrors the kiosk's forced update modal: while an
// apply is running nothing else is clickable, so double-applies can't happen.
const applying = reactive({ active: false, kind: '', label: '', state: '', progress: null, message: '', error: false, doneList: [] });
async function loadChannel() {
  const r = await api.sys('ota_channel');
  if (r.ok) {
    channel.value = r.data.channel || 'prod';
    if (Array.isArray(r.data.channels) && r.data.channels.length) channels.value = r.data.channels;
  }
}
async function setChannel(c) {
  if (applying.active || c === channel.value) return;
  // Downgrading back to prod from dev/alpha is gated by a newer prod release,
  // so warn before the switch rather than after — the user can't just flip
  // back. Not just 'dev': alpha is an even more bleeding-edge preview (the
  // unfiltered newest release, prereleases included — see _fetch_release()),
  // so it's under at least the same constraint and was wrongly left out.
  if (channel.value === 'prod' && !confirm(t('settings.updates.confirmProdToDev'))) return;
  channel.value = c;
  const r = await api.sysPost('ota_channel', { channel: c });
  const changedKey = { prod: 'channelChangedProd', dev: 'channelChangedDev', alpha: 'channelChangedAlpha' }[c] || 'channelChangedDev';
  say(r.ok && r.data.success !== false ? t(`settings.updates.${changedKey}`) : bodyMsg(r, t('settings.updates.channelFailed')), !(r.ok && r.data.success !== false));
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
// Debian 12 devices can't take an update built for Debian 13 (see
// api_server.py's _check_release_update()) -- every channel check reports
// this instead of a normal available/error result.
const otaBlockedByOs = () => Object.keys(kinds).some(k => upd[k] && upd[k].blocked === 'debian12');
const sleep = (ms) => new Promise(res => setTimeout(res, ms));

// "What's new" popup — ui/system/os all ship from the same tagged release, so
// their `notes` are normally identical; take whichever check response has one.
const changelog = reactive({ open: false, version: '', notes: '' });
function changelogAvailable() {
  return Object.keys(kinds).some(k => upd[k] && upd[k].update_available && upd[k].notes);
}
// ── network check (api_server /network_check) ────────────────────
// Walks the way an update check goes — link, router, internet, DNS, clock,
// update server, download — and says at which step it stops. Reached from
// System and Updates; the result is language-neutral, the words are here.
const NC_STEPS = ['link', 'router', 'internet', 'dns', 'clock', 'ota', 'download'];
const nc = reactive({ busy: false, failed: false, data: null, advanced: false });
// What the owner sees: four plain steps, each the worst of the checks behind
// it. The seven checks with addresses and timings are "advanced".
const NC_GROUPS = [
  { id: 'device', steps: ['link'] }, { id: 'router', steps: ['router'] },
  { id: 'internet', steps: ['internet', 'dns', 'clock'] }, { id: 'server', steps: ['ota', 'download'] },
];
const NC_WARN_VERDICTS = ['link', 'router', 'internet', 'dns', 'clock', 'ota'];
function openNetCheck() { router.replace({ query: { open: 'netCheck', from: open.value } }); }
async function runNetCheck() {
  if (nc.busy) return;
  nc.busy = true; nc.failed = false;
  const r = await api.sys('network_check');
  nc.busy = false;
  if (r.ok && r.data && Array.isArray(r.data.steps)) nc.data = r.data;
  else nc.failed = true;
}
watch(open, (v) => { if (v === 'netCheck') runNetCheck(); }, { immediate: true });
const ncStep = (id) => (nc.busy || !nc.data ? null : nc.data.steps.find(s => s.id === id)) || { status: nc.busy ? 'run' : 'skip' };
const ncVerdict = () => {
  if (!nc.data) return '';
  return nc.data.verdict === 'ok' && nc.data.warn ? 'warn' : nc.data.verdict;
};
// a caveat has a sentence of its own for the step it comes from
const ncVerdictText = () => {
  const v = ncVerdict();
  return v === 'warn' && NC_WARN_VERDICTS.includes(nc.data.warn)
    ? t(`settings.netCheck.verdictWarn.${nc.data.warn}`) : t(`settings.netCheck.verdict.${v}`);
};
const NC_RANK = { run: 5, fail: 4, warn: 3, ok: 2, skip: 1 };
const ncGroup = (g) => g.steps.map(id => ncStep(id).status).reduce((w, st) => (NC_RANK[st] > NC_RANK[w] ? st : w), 'skip');
const ncMark = { ok: '✓', warn: '!', fail: '✕', skip: '○', run: '…' };
function ncSkew(sec) {
  const a = Math.abs(sec);
  if (a < 3600) return `${Math.round(a / 60)} min`;
  if (a < 86400) return `${Math.round(a / 3600)} h`;
  return `${Math.round(a / 86400)} ${t('settings.lyrion.days')}`;
}
function ncReason(s) {
  const e = s.error;
  if (!e) return '';
  if (e === 'http') return t('settings.netCheck.err.http', { code: s.http });
  if (e === 'packetLoss') return t('settings.netCheck.err.packetLoss', { loss: s.loss });
  if (e === 'clockOff') return s.skew !== undefined ? t('settings.netCheck.err.clockOff', { time: ncSkew(s.skew) }) : t('settings.netCheck.err.clockWrong');
  if (e === 'dnsPartial') return `${t('settings.netCheck.err.dnsPartial')} ${(s.failed || []).join(', ')}`;
  return t(`settings.netCheck.err.${e}`);
}
function ncDetail(s) {
  const parts = [];
  if (s.detail) parts.push(s.detail);
  if (s.kbps) parts.push(s.kbps >= 1024 ? `${(s.kbps / 1024).toFixed(1)} MB/s` : `${s.kbps} KB/s`);
  return parts.join(' · ');
}
const ncTime = () => (nc.data ? new Date(nc.data.at * 1000).toLocaleTimeString(lang.value === 'it' ? 'it-IT' : 'en-GB') : '');

function showChangelog() {
  const withNotes = Object.keys(kinds).map(k => upd[k]).find(u => u && u.update_available && u.notes);
  if (!withNotes) return;
  changelog.version = withNotes.latest || '';
  changelog.notes = withNotes.notes;
  changelog.open = true;
}
function closeChangelog() { changelog.open = false; }

// The whole sequence runs on the appliance in two isolated phases
// (hifi-update-stage-runner.sh / hifi-update-apply-runner.sh, driven by a
// plan persisted under /var/lib) — the second phase runs with nothing from
// the app stack running at all, not even this daemon. This page only starts
// it and renders its progress, so losing the browser — or this very daemon —
// no longer interrupts anything.
// The shell scripts driving each step (hifi-os-update.sh, hifi-system-update.sh)
// write free-text `message` in Italian only — not locale-aware. `state` is the
// one locale-neutral field they emit, so that's what drives the UI text; the
// raw message is kept only for 'error' (a diagnostic reason, not meant to be
// pretty) and as a last-resort fallback for an unrecognized state.
function progressStateMessage(state, rawMessage) {
  if (state === 'error') return rawMessage || t('settings.updates.genericError');
  const known = ['starting', 'downloading', 'verifying', 'applying', 'restarting', 'done'];
  return known.includes(state) ? t(`settings.updates.progressState.${state}`) : rawMessage;
}

function renderPlan(s) {
  applying.kind = s.kind || '';
  applying.label = kindLabels.value[s.kind] || '';
  applying.state = s.step_state || s.state || '';
  applying.progress = (typeof s.overall_progress === 'number') ? s.overall_progress : null;
  applying.message = progressStateMessage(applying.state, s.message || '');
  applying.doneList = (s.steps || []).filter(x => x.state === 'done')
    .map(x => kindLabels.value[x.kind] || x.kind);
}

async function pollPlan(timeoutMs = 30 * 60 * 1000) {
  const t0 = Date.now();
  // 'interrupted' means "a step was left running with nobody currently
  // resuming it" — which is also exactly what the plan looks like for the
  // first stretch after a stage download is interrupted, before
  // hifi-update-stage-resume.service has come up (it waits on
  // network-online.target). Treating the very first
  // 'interrupted' read as a final failure gave up on updates that were about
  // to continue on their own; require several consecutive reads before
  // believing it's a real, dead plan.
  let interruptedStreak = 0;
  const MAX_INTERRUPTED_POLLS = 60; // ~2 minutes at 2s/poll
  // Request failures are EXPECTED mid-way: the system bundle restarts this
  // daemon and an OS payload may reboot the appliance. Keep polling — the plan
  // is on persistent storage and the sequencer resumes on its own.
  while (Date.now() - t0 < timeoutMs) {
    await sleep(2000);
    const r = await api.sys('updates/status');
    if (!r.ok) continue;
    const s = r.data || {};
    if (s.state === 'idle') continue;
    if (s.state === 'interrupted') {
      interruptedStreak += 1;
      if (interruptedStreak < MAX_INTERRUPTED_POLLS) {
        renderPlan({ ...s, step_state: 'restarting' });
        continue;
      }
    } else {
      interruptedStreak = 0;
    }
    renderPlan(s);
    // 'staged_pending_reboot'/'applying' mean the box is mid isolated-update
    // session (about to, or already did, reboot into system-update.target) —
    // still in progress, keep polling. 'apply_error' is the same terminal
    // failure as 'error', just discovered after that isolated session.
    if (s.state === 'done') return true;
    if (s.state === 'error' || s.state === 'apply_error' || s.state === 'interrupted') return false;
  }
  applying.message = t('settings.updates.timeout');
  return false;
}

async function applyAll() {
  if (applying.active || !hasUpdates()) return;
  applying.active = true; applying.error = false; applying.doneList = [];
  applying.kind = ''; applying.label = ''; applying.state = 'starting';
  applying.progress = null; applying.message = '';
  const r = await api.sysPost('updates/apply_all', {});
  if (!(r.ok && r.data.started)) {
    applying.error = true;
    applying.state = 'error';
    applying.message = bodyMsg(r, t('settings.updates.startFailed'));
    return;
  }
  const ok = await pollPlan();
  applying.error = !ok;
  applying.state = ok ? 'done' : 'error';
  if (ok) applying.message = t('settings.updates.allCompleted');
  // Keep the modal up until the user closes it (shows the outcome).
}

// If the page is opened (or reloaded) while the appliance is mid-plan, join the
// run in progress instead of showing a stale "up to date".
async function resumePlanIfRunning() {
  const r = await api.sys('updates/status');
  if (!r.ok) return;
  const s = r.data || {};
  if (s.state === 'idle') return;
  applying.active = true;
  renderPlan(s);
  // 'staged_pending_reboot'/'applying' mean the box is mid isolated-update
  // session (about to, or already did, reboot) — still worth rejoining the
  // poll for, same as 'running'/'interrupted'.
  if (s.state === 'running' || s.state === 'interrupted'
      || s.state === 'staged_pending_reboot' || s.state === 'applying') {
    // 'interrupted' here just means the page (re)loaded during the gap
    // before hifi-update-stage-resume.service comes up after a reboot — give
    // pollPlan its own grace period instead of declaring failure on this
    // single snapshot.
    const ok = await pollPlan();
    applying.error = !ok;
    applying.state = ok ? 'done' : 'error';
    if (ok) applying.message = t('settings.updates.allCompleted');
  } else {
    // A terminal outcome ('done'/'error'/'apply_error') found on load — the
    // isolated apply session finished while this page wasn't open to watch it.
    applying.error = s.state !== 'done';
    applying.state = applying.error ? 'error' : 'done';
    if (!applying.error) applying.message = t('settings.updates.allCompleted');
  }
}

async function closeApplyModal() {
  applying.active = false; applying.kind = ''; applying.state = '';
  // Let the appliance drop the finished plan, so it doesn't re-open this modal
  // on the next page load.
  await api.sysPost('updates/dismiss', {});
  checkAll();
}

// ── companion pairing ────────────────────────────────────────────
const pairQr = ref(null); const pairBusy = ref(false);
async function mintPair() {
  pairBusy.value = true; pairQr.value = null;
  const r = await api.post('/api/system/pair_token', {});
  pairBusy.value = false;
  if (r.ok && r.data.token) {
    // lms follows the skin choice (aligned with the kiosk QR, which points at
    // /material/): legacy/unset devices keep the bare root they always had.
    const payload = JSON.stringify({ lms: lmsUrl.value, api: `${host}:8080`, token: r.data.token });
    pairQr.value = await QRCode.toDataURL(payload, { margin: 1, width: 380 });
  } else say(bodyMsg(r, t('settings.companion.tokenFailed')), true);
}
async function revokePairs() {
  if (!confirm(t('settings.companion.revokeConfirm'))) return;
  const r = await api.post('/api/system/pair_revoke_all', {});
  say(r.ok ? t('settings.companion.revoked') : bodyMsg(r, t('settings.companion.revokeFailed')), !r.ok);
  pairQr.value = null;
}

// ── iPhone/iPad: LyrPlay (third-party App Store client) ──────────
// No Osmium app exists for iOS; LyrPlay is an actively maintained App Store
// client that speaks the standard Lyrion/Squeezebox protocol. Static URL —
// no device address or pairing token involved (LyrPlay talks to Lyrion
// directly, it never touches the :8080 admin API), so the QR is just the
// store link and can be rendered once, offline. Mirrors the kiosk's own
// iPhone/iPad section (src/pages/Settings.jsx).
const LYRPLAY_APP_STORE_URL = 'https://apps.apple.com/app/lyrplay/id6746776736';
const lyrplayQr = ref(null);
async function makeLyrplayQr() {
  if (lyrplayQr.value) return;
  lyrplayQr.value = await QRCode.toDataURL(LYRPLAY_APP_STORE_URL, { margin: 1, width: 380 });
}
watch(open, (v) => { if (v === 'companionIos') makeLyrplayQr(); }, { immediate: true });

// ── system: reboot/shutdown/reset ────────────────────────────────
// Shared "device is rebooting" overlay for every action that ends in a
// reboot (manual reboot, factory reset, a restore that needs one) — polls
// auth/status (works whether or not the session is still valid, which a
// factory reset intentionally invalidates) until the box answers again,
// then reloads so the page reconnects on its own instead of leaving the
// owner staring at a dead tab.
const rebootWait = reactive({ active: false, phase: 'going-down' });
async function waitForReboot() {
  rebootWait.active = true;
  rebootWait.phase = 'going-down';
  const deadline = Date.now() + 6 * 60 * 1000;
  // Phase 1: wait for the box to actually drop off so a fast reboot can't be
  // misread as "already back up" on the very first poll.
  let sawDown = false;
  for (let i = 0; i < 10 && Date.now() < deadline; i++) {
    await sleep(1500);
    const r = await api.authStatus();
    if (!r.ok) { sawDown = true; break; }
  }
  if (!sawDown) await sleep(3000);
  rebootWait.phase = 'coming-back';
  while (Date.now() < deadline) {
    await sleep(2500);
    const r = await api.authStatus();
    if (r.ok) { window.location.reload(); return; }
  }
  rebootWait.active = false;
  say(t('settings.system.rebootTimeout'), true);
}
async function reboot() {
  if (!confirm(t('settings.system.confirmReboot'))) return;
  await api.sysPost('reboot', {});
  waitForReboot();
}
async function shutdown() { if (confirm(t('settings.system.confirmShutdown'))) { await api.sysPost('shutdown', {}); say(t('settings.system.shuttingDown')); } }
const resetPw = ref('');
async function factoryReset() {
  if (!confirm(t('settings.system.factoryConfirm'))) return;
  const r = await api.post('/api/system/factory_reset', { password: resetPw.value });
  if (r.ok && r.data.success !== false) waitForReboot();
  else say(bodyMsg(r, t('settings.system.factoryFailed')), true);
}

// ── account ──────────────────────────────────────────────────────
const acc = reactive({ username: '', current: '', next: '' });
async function changePw() {
  const r = await api.changePassword(acc.username, acc.current, acc.next);
  if (r.ok && r.data.success) { say(t('settings.account.updated')); acc.username = ''; acc.current = ''; acc.next = ''; }
  else say(bodyMsg(r, t('settings.account.updateFailed')), true);
}

// ── backup / restore ──────────────────────────────────────────────
// The passphrase is the single switch deciding whether credentials (Wi-Fi
// PSKs, SMB passwords, this very account) go into the archive at all: filled
// in means encrypted-and-complete, empty means plain-and-non-secret. It is
// held only in this component's state, sent with the one request that needs
// it, and never written anywhere.
const backupPass = ref('');
const backupGens = ref([]);
const backupSecretCats = ref([]);
const backupScheduled = ref(false);
const backupBusy = ref(false);
const restoreFileInput = ref(null);

function fmtBackupSize(n) {
  if (!n) return '';
  return n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' kB';
}
function fmtBackupStamp(id) {
  // Generation ids are UTC timestamps (hifi_backup.py: datetime.now(timezone.utc)),
  // formatted YYYYMMDD-HHMMSS. Render them in the device's configured timezone
  // instead of slicing the raw UTC digits, or the displayed time is off by
  // the device's UTC offset.
  if (!id || id.length < 15) return id || '';
  const iso = `${id.slice(0, 4)}-${id.slice(4, 6)}-${id.slice(6, 8)}T${id.slice(9, 11)}:${id.slice(11, 13)}:${id.slice(13, 15)}Z`;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return id;
  const opts = { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false };
  if (timezone.value) opts.timeZone = timezone.value;
  return new Intl.DateTimeFormat('en-GB', opts).format(d).replace(',', '');
}

async function loadBackups() {
  const r = await api.backupList();
  if (!r.ok) return;
  backupGens.value = r.data.generations || [];
  backupSecretCats.value = r.data.secret || [];
  backupScheduled.value = !!(r.data.settings && r.data.settings.scheduled);
}

async function pollBackupStatus() {
  for (let i = 0; i < 600; i++) {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    const r = await api.backupStatus();
    if (!r.ok) continue;
    const s = r.data;
    if (s.state === 'done') { say(s.message || t('settings.backup.created')); break; }
    if (s.state === 'error') { say(s.message || t('settings.backup.createFailed'), true); break; }
    say((s.message || t('settings.backup.working')) + ' ' + (s.progress || 0) + '%');
  }
  backupBusy.value = false;
  loadBackups();
}

async function createBackup() {
  backupBusy.value = true;
  say(t('settings.backup.working'));
  const r = await api.backupCreate(backupPass.value, null);
  if (r.data && r.data.success === false) {
    backupBusy.value = false;
    say(bodyMsg(r, t('settings.backup.createFailed')), true);
    return;
  }
  pollBackupStatus();
}

async function downloadBackup(id) {
  // Same fetch→blob→filename dance as downloadSupportBundle: same-origin
  // session cookie rides along, and this preserves the server-set filename.
  say(t('settings.backup.working'));
  try {
    const resp = await fetch(api.backupDownloadUrl(id), { credentials: 'same-origin' });
    if (!resp.ok) throw new Error(await resp.text() || resp.statusText);
    const blob = await resp.blob();
    let filename = 'osmium-backup.tar.gz';
    const cd = resp.headers.get('Content-Disposition');
    if (cd) {
      const m = /filename\*=[^']*'[^']*'([^;]+)|filename="([^"]+)"|filename=([^;\n]+)/i.exec(cd);
      const name = m && decodeURIComponent(m[1] || m[2] || m[3] || '');
      if (name) filename = name;
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
    say(t('settings.backup.downloaded'));
    if (!id) loadBackups(); // an immediate download may also have started a fresh listing-worthy state
  } catch (e) {
    say(t('settings.backup.downloadFailed'), true);
  }
}

// Restore runs in a background thread on the appliance (writing files back —
// a Lyrion profile is thousands of tiny ones — a pre-restore safety snapshot,
// and restarting whichever services own what was restored, up to and
// including hifi-webui itself if the restored file was webui.db). Polling its
// status is what tells "still working" apart from "actually stuck", the same
// way pollBackupStatus() does for the other direction.
async function pollRestoreStatus() {
  for (let i = 0; i < 600; i++) {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    const r = await api.restoreStatus();
    if (!r.ok) continue;
    const s = r.data;
    if (s.state === 'done') {
      say(s.message || t('settings.backup.restored'));
      // A restore can include NetworkManager profiles, timezone, DSP/audio
      // config and Lyrion prefs written straight to disk — reboot so every
      // affected service picks all of that up cleanly (same reasoning as the
      // setup wizard's own restore step), instead of leaving some of it
      // pending until whenever the box next restarts on its own.
      await api.sysPost('reboot', {});
      waitForReboot();
      return;
    }
    if (s.state === 'error') { say(s.message || t('settings.backup.restoreFailed'), true); break; }
    say((s.message || t('settings.backup.restoring')) + (typeof s.progress === 'number' ? ' ' + s.progress + '%' : ''));
  }
  loadBackups();
}

async function restoreGen(gen) {
  if (!confirm(t('settings.backup.restoreConfirm'))) return;
  say(t('settings.backup.restoring'));
  const r = await api.backupRestore(gen.id, backupPass.value, null);
  if (!(r.ok && r.data.started)) {
    say(bodyMsg(r, t('settings.backup.restoreFailed')), true);
    loadBackups();
    return;
  }
  await pollRestoreStatus();
}

async function deleteGen(gen) {
  if (!confirm(t('settings.backup.deleteConfirm'))) return;
  await api.backupDelete(gen.id);
  loadBackups();
}

async function uploadRestore(e) {
  const file = e.target.files && e.target.files[0];
  e.target.value = '';
  if (!file) return;
  if (!confirm(t('settings.backup.restoreConfirm'))) return;
  say(t('settings.backup.restoring'));
  const r = await api.restoreUpload(file, backupPass.value, null);
  if (!(r.ok && r.data.started)) {
    say(bodyMsg(r, t('settings.backup.restoreFailed')), true);
    loadBackups();
    return;
  }
  await pollRestoreStatus();
}

async function saveBackupScheduled(v) {
  backupScheduled.value = v;
  const r = await api.backupSettingsSave({ scheduled: v });
  if (r.data && r.data.success === false) say(bodyMsg(r, t('settings.backup.settingsFailed')), true);
}

onMounted(async () => {
  loadNet(); loadIpv4(); loadAudio(); loadDsp(); loadFir(); loadToggles(); loadShell(); loadLms(); loadLyrion(); loadSkin(); loadPlayback();
  loadMode(); loadEngine(); loadPlayerEnabled(); loadUiRes(); loadUiRefresh(); loadPointer(); loadTimezone(); loadVuMeter(); loadVuStyle(); loadVuStore(false); loadNpAnimation(); loadAnimStore(false); loadAutoExpand(); loadChannel(); checkAll(); resumePlanIfRunning(); loadBackups(); loadTailscale(); loadDebugFlags();
  timezonePoll = setInterval(pollTimezone, 10000);
  // Tell the global UpdateProgressOverlay (mounted in App.vue) that this page
  // owns the OTA modal while it's open, so the two never render on top of
  // each other. The global one takes back over as soon as this page unmounts.
  window.dispatchEvent(new CustomEvent('hifi-settings-active', { detail: true }));
});
onUnmounted(() => {
  if (lyrionPoll) clearInterval(lyrionPoll); if (skinPoll) clearInterval(skinPoll); if (tailscalePoll) clearInterval(tailscalePoll);
  if (timezonePoll) clearInterval(timezonePoll); if (vuStorePoll) clearInterval(vuStorePoll); if (animStorePoll) clearInterval(animStorePoll);
  if (btPoll) clearInterval(btPoll);
  window.dispatchEvent(new CustomEvent('hifi-settings-active', { detail: false }));
});
</script>

<template>
  <!-- section menu (kiosk-like) -->
  <template v-if="!open">
    <RouterLink class="backlink" to="/">← {{ t('dashboard.title') }}</RouterLink>
    <h2 class="page">{{ t('settings.title') }}</h2>
    <div v-if="msg" class="msg" :class="{ err }">{{ msg }}</div>
    <div class="card" style="padding: 6px 16px;">
      <div v-for="s in listedSections" :key="s.key" class="net between" @click="goto(s.key)">
        <span>
          <span style="display:block;">{{ s.label }}<span v-if="(s.key === 'vuMeters' && vuStoreNew) || (s.key === 'animations' && animStoreNew)" class="dot-new"></span></span>
          <span class="muted">{{ s.desc }}</span>
        </span>
        <span class="silver" style="font-size: 18px;">›</span>
      </div>
    </div>
  </template>

  <!-- single open section -->
  <template v-else>
    <a class="backlink" href="#" @click.prevent="goBack()">← {{ open === 'netCheck' && route.query.from ? title(normalizeSection(route.query.from)) : t('settings.backToSettings') }}</a>
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
      <div v-for="n in wifi" :key="n.ssid + '|' + (n.band || '')" class="net between" @click="pickNet(n)">
        <span>{{ n.ssid }}
          <span class="band" v-if="n.band && dualSsids.has(n.ssid)">{{ n.band }} GHz</span>
          <span class="check" v-if="n.in_use">✓</span></span>
        <span class="muted">{{ n.signal }}%</span>
      </div>
      <template v-if="wifi.length || ssid">
        <label>{{ t('settings.network.ssidLabel') }}</label><input v-model="ssid" @input="wifiBand = ''" />
        <!-- In clear on purpose: a Wi-Fi key is long, typed once, and a typo
             hidden behind dots is the commonest reason a join fails. -->
        <label>{{ t('settings.network.passwordLabel') }}</label>
        <input v-model="wifiPass" type="text" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" />
        <div style="margin-top: 12px;"><button :disabled="netBusy" @click="connectWifi">{{ t('settings.network.connect') }}</button></div>
      </template>

      <!-- Fixed (static) address. Applies to whichever interface is carrying
           traffic right now, wired or Wi-Fi (named below). -->
      <div style="margin-top: 18px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.1);">
        <p class="sub">{{ t('settings.network.addressTitle') }}</p>
        <p class="muted">{{ t('settings.network.addressHint') }}</p>
        <span class="seg">
          <button :class="{ active: ipForm.mode === 'auto' }" @click="ipForm.mode = 'auto'">{{ t('settings.network.modeAuto') }}</button>
          <button :class="{ active: ipForm.mode === 'manual' }" @click="ipForm.mode = 'manual'">{{ t('settings.network.modeStatic') }}</button>
        </span>
        <template v-if="ipForm.mode === 'manual'">
          <label>{{ t('settings.network.addressLabel') }}</label>
          <input v-model="ipForm.address" placeholder="192.168.1.50" inputmode="decimal" />
          <label>{{ t('settings.network.prefixLabel') }}</label>
          <input v-model="ipForm.prefix" type="number" min="1" max="30" />
          <p class="muted">{{ t('settings.network.prefixHint') }}</p>
          <label>{{ t('settings.network.gatewayLabel') }}</label>
          <input v-model="ipForm.gateway" placeholder="192.168.1.1" inputmode="decimal" />
          <label>{{ t('settings.network.dnsLabel') }}</label>
          <input v-model="ipForm.dns" placeholder="192.168.1.1, 1.1.1.1" />
          <p class="muted">{{ t('settings.network.dnsHint') }}</p>
          <p class="muted">{{ t('settings.network.staticWarn') }}</p>
        </template>
        <div style="margin-top: 12px;">
          <button :disabled="ipBusy" @click="saveIpv4">{{ t('common.save') }}</button>
        </div>
        <p class="muted" v-if="ipv4.device" style="margin-top: 8px;">
          {{ t('settings.network.appliesTo', { device: ipv4.device }) }}
        </p>
      </div>
    </div>

    <!-- Audio -->
    <div class="card" v-if="open === 'audio'">
      <p class="sub">{{ t('settings.audio.hint') }}</p>
      <div v-for="d in devices" :key="d.id" class="net between" @click="pickDevice(d.id)">
        <span>{{ d.name || d.id }}</span><span class="check" v-if="d.id === currentDevice">✓</span>
      </div>
      <label>{{ t('settings.audio.playerName') }}</label>
      <div class="row"><input v-model="playerName" /><button class="secondary fit" @click="saveName">{{ t('common.save') }}</button></div>
      <p class="sub" style="margin-top: 4px;">{{ t('settings.audio.playerNameHint') }}</p>
    </div>

    <!-- Bluetooth speakers: pair one and it turns into a player of its own,
         next to the built-in one. The DAC is untouched throughout. -->
    <div class="card" v-if="open === 'btSpeakers'">
      <p class="sub">{{ t('settings.btSpeakers.help') }}</p>
      <p class="sub" v-if="!bt.available">{{ t('settings.btSpeakers.unavailable') }}</p>
      <template v-else>
        <div class="between item">
          <span>{{ t('settings.btSpeakers.enable') }}
            <span class="muted">{{ t('settings.btSpeakers.enableHint') }}</span>
          </span>
          <Toggle :model-value="bt.enabled" :disabled="bt.busy" @update:model-value="setBt" />
        </div>

        <template v-if="bt.enabled">
          <p class="sub" v-if="!bt.adapter">{{ t('settings.btSpeakers.noAdapter') }}</p>
          <template v-else>
            <label>{{ t('settings.btSpeakers.yours') }}</label>
            <p class="sub" v-if="!bt.speakers.length">{{ t('settings.btSpeakers.none') }}</p>
            <template v-for="sp in bt.speakers" :key="sp.mac">
              <div class="net between" @click="btToggle(sp)">
                <span>
                  <span style="display:block;">{{ sp.player || sp.name }}</span>
                  <span class="muted">{{ btState(sp) }}</span>
                </span>
                <span class="check">{{ bt.open === sp.mac ? '▾' : '▸' }}</span>
              </div>
              <div v-if="bt.open === sp.mac" style="padding: 0 4px 10px;">
                <label>{{ t('settings.btSpeakers.playerName') }}</label>
                <div class="row">
                  <input v-model="bt.name" />
                  <button class="secondary fit" :disabled="bt.busy" @click="btRename(sp)">{{ t('common.save') }}</button>
                </div>
                <p class="sub">{{ t('settings.btSpeakers.playerNameHint') }}</p>
                <div class="between item">
                  <span>{{ t('settings.btSpeakers.autoconnect') }}
                    <span class="muted">{{ t('settings.btSpeakers.autoconnectHint') }}</span>
                  </span>
                  <Toggle :model-value="sp.autoconnect" :disabled="bt.busy" @update:model-value="() => btAuto(sp)" />
                </div>
                <div class="row" style="margin-top: 10px;">
                  <button class="secondary" :disabled="bt.busy" @click="btConnect(sp)">
                    {{ sp.connected ? t('settings.btSpeakers.disconnect') : t('settings.btSpeakers.connect') }}
                  </button>
                  <button class="danger fit" :disabled="bt.busy" @click="btForget(sp)">{{ t('settings.btSpeakers.forget') }}</button>
                </div>
                <p class="sub" style="margin-top: 6px;">{{ t('settings.btSpeakers.address') }}: <span class="silver">{{ sp.mac }}</span></p>
              </div>
            </template>

            <label>{{ t('settings.btSpeakers.found') }}</label>
            <p class="sub">{{ t('settings.btSpeakers.searchHint') }}</p>
            <button :disabled="bt.busy" @click="btScan">
              {{ bt.scanning ? t('settings.btSpeakers.searching') : t('settings.btSpeakers.search') }}
            </button>
            <p class="sub" v-if="bt.scanning">{{ t('settings.btSpeakers.searchingHint') }}</p>
            <p class="sub" v-else-if="!bt.found.length">{{ t('settings.btSpeakers.foundNone') }}</p>
            <div v-for="d in bt.found" :key="d.mac" class="net between" @click="btAdd(d.mac)">
              <span>
                <span style="display:block;">{{ d.name || d.mac }}</span>
                <span class="muted">{{ d.audio ? d.mac : t('settings.btSpeakers.notAudio') }}</span>
              </span>
              <span class="check">+</span>
            </div>
          </template>
        </template>
      </template>
    </div>

    <!-- Telecomando: quello che l'interfaccia sullo schermo legge da /dev/input,
         visto da qui attraverso api_server (/remote, /bt_remotes) -->
    <div class="card" v-if="open === 'remote'">
      <p class="sub">{{ t('settings.remote.help') }}</p>

      <label>{{ t('settings.remote.connected') }}</label>
      <p class="sub" v-if="!rc.devices.length">{{ t('settings.remote.none') }}</p>
      <div v-for="d in rc.devices" :key="d.name + d.address" class="net between">
        <span>
          <span style="display:block;">{{ d.name }}</span>
          <span class="muted">
            {{ rcWhere(d) }} ·
            {{ (d.kind === 'remote' || d.chosen) ? t('settings.remote.full') : t('settings.remote.mediaOnly') }}
            <template v-if="d.chosen"> · {{ t('settings.remote.isMine') }}</template>
          </span>
        </span>
        <button class="secondary fit" :disabled="rc.busy" @click="rcMine(d)">
          {{ d.chosen ? t('settings.remote.notMine') : t('settings.remote.mine') }}
        </button>
      </div>
      <p class="sub" v-if="rc.devices.length > 1">{{ t('settings.remote.mineHint') }}</p>

      <label>{{ t('settings.remote.test') }}</label>
      <p class="sub">{{ t('settings.remote.testHintWeb') }}</p>
      <p class="sub" v-if="!rc.interfaceRunning">{{ t('settings.remote.needsInterface') }}</p>
      <div class="between item">
        <span>{{ t('settings.remote.testSwitch') }}</span>
        <Toggle :model-value="rc.testing" :disabled="rc.busy || !rc.interfaceRunning"
                @update:model-value="rcTest" />
      </div>
      <template v-if="rc.testing">
        <p class="sub" v-if="!rc.lastKey || !rc.lastKey.code">{{ t('settings.remote.pressAKey') }}</p>
        <div v-else>
          <p class="sub">
            {{ t('settings.remote.keyLabel') }}: <span class="silver">{{ rc.lastKey.key }} · {{ rc.lastKey.code }}</span>
            <template v-if="rc.lastKey.device"> — {{ rc.lastKey.device }}</template>
          </p>
          <p class="sub">
            {{ t('settings.remote.doesLabel') }}:
            <span class="silver">{{ rcActionLabel(rcActionOf(rc.lastKey.code, rc.lastKey.device)) }}</span>
            <template v-if="rcIsCustom(rc.lastKey.code, rc.lastKey.device)"> ({{ t('settings.remote.custom') }})</template>
          </p>
          <label>{{ t('settings.remote.assign') }}</label>
          <select :disabled="rc.busy"
                  :value="rcActionOf(rc.lastKey.code, rc.lastKey.device)"
                  @change="rcAssign(rc.lastKey.code, $event.target.value, rc.lastKey.device)">
            <option value="">{{ t('settings.remote.assignNothing') }}</option>
            <option v-for="a in rc.actions" :key="a" :value="a">{{ t('settings.remote.actions.' + a) }}</option>
          </select>
          <button class="secondary" style="margin-top: 8px;"
                  v-if="rcIsCustom(rc.lastKey.code, rc.lastKey.device)" :disabled="rc.busy"
                  @click="rcUnassign(rc.lastKey.code, rc.lastKey.device)">
            {{ t('settings.remote.unassign') }}
          </button>
        </div>
      </template>
      <p class="sub">{{ t('settings.remote.keysBody') }}</p>

      <label>{{ t('settings.remote.btTitle') }}</label>
      <p class="sub">{{ t('settings.remote.btHelp') }}</p>
      <p class="sub" v-if="!rc.bt.available">{{ t('settings.remote.btUnavailable') }}</p>
      <p class="sub" v-else-if="!rc.bt.supported">{{ t('settings.remote.btNeedsUpdate') }}</p>
      <template v-else>
        <p class="sub" v-if="!rc.bt.remotes.length">{{ t('settings.remote.btNone') }}</p>
        <div v-for="r in rc.bt.remotes" :key="r.mac" class="net between">
          <span>
            <span style="display:block;">{{ r.name || r.mac }}</span>
            <span class="muted">
              {{ r.connected ? t('settings.remote.btConnected') : t('settings.remote.btNotConnected') }}
              <template v-if="r.connected && !rcHasKeys(r.name)"> — {{ t('settings.remote.btNoKeys') }}</template>
            </span>
          </span>
          <button class="danger fit" :disabled="rc.busy" @click="rcForget(r.mac)">{{ t('settings.remote.btForget') }}</button>
        </div>
        <button :disabled="rc.busy" @click="rcScan" style="margin-top: 10px;">
          {{ rc.bt.scanning ? t('settings.remote.btSearching') : t('settings.remote.btSearch') }}
        </button>
        <p class="sub" v-if="rc.bt.scanning">{{ t('settings.remote.btSearchingHint') }}</p>
        <template v-else>
          <p class="sub" v-if="!rc.bt.found.length">{{ t('settings.remote.btFoundNone') }}</p>
          <div v-for="d in rc.bt.found" :key="d.mac" class="net between" @click="rcPair(d.mac)">
            <span>
              <span style="display:block;">{{ d.name || d.mac }}</span>
              <span class="muted">{{ d.mac }}</span>
            </span>
            <span class="check">+</span>
          </div>
        </template>
      </template>
    </div>

    <!-- Sources (native — talks directly to sources_server.py through
         webui_server's session-gated /api/system/sources|usb|internal|apply
         forwarders, see SourcesPanel.vue) -->
    <div class="card wide" v-if="open === 'sources'">
      <p class="sub">{{ t('settings.sources.hint') }}</p>
      <SourcesPanel />
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
      <!-- SSH login. Shown once SSH is on (or a login already exists), because
           that is the only context in which it means anything. -->
      <template v-if="shell.supported && (sshState.enabled || shell.exists)">
        <p class="sub" v-if="shell.exists">
          {{ t('settings.services.sshLoginIs') }}
          <span class="silver">ssh {{ shell.username }}@{{ host }}</span>
        </p>
        <p class="sub" v-else>{{ t('settings.services.sshNoLogin') }}</p>
        <p class="sub">{{ t('settings.services.sshSudoWarning') }}</p>
        <label>{{ t('settings.services.sshUsername') }}</label>
        <input v-model="shell.form" autocomplete="username" />
        <label>{{ t('settings.services.sshPassword') }}</label>
        <input v-model="shell.password" type="password" autocomplete="new-password" />
        <div class="row" style="margin-top: 10px;">
          <button class="secondary" :disabled="shell.busy || !shell.form || shell.password.length < 8" @click="saveShellAccount">
            {{ shell.busy ? '…' : (shell.exists ? t('settings.services.sshLoginUpdate') : t('settings.services.sshLoginCreate')) }}
          </button>
        </div>
      </template>
    </div>

    <!-- Tailscale: join the owner's OWN tailnet, exposing every port on the
         appliance so the music library is reachable away from home. -->
    <div class="card" v-if="open === 'tailscale'">
      <p class="sub">{{ t('settings.tailscale.hint') }}</p>
      <template v-if="!tailscale.available">
        <p class="sub">{{ t('settings.tailscale.unavailable') }}</p>
        <button @click="installTailscaleNow" :disabled="tailscale.installing">
          {{ tailscale.installing ? '…' : t('settings.tailscale.install') }}
        </button>
      </template>
      <template v-else>
        <div class="between item">
          <span>{{ t('settings.tailscale.toggle') }}
            <span class="muted">{{ tailscale.connected ? t('settings.tailscale.connectedHint', { ip: tailscale.ip }) : t('settings.tailscale.disconnectedHint') }}</span>
          </span>
          <Toggle :model-value="tailscale.connected" :disabled="tailscale.busy" @update:model-value="setTailscale" />
        </div>
        <div class="between item" v-if="tailscale.connected && tailscale.derpRegion">
          <span class="muted">{{ t('settings.tailscale.derp') }}</span>
          <span class="silver">{{ tailscale.derpRegion }}<template v-if="tailscale.derpLatencyMs != null"> · {{ tailscale.derpLatencyMs }}ms</template></span>
        </div>
        <template v-if="!tailscale.connected && tailscale.loginUrl">
          <p class="sub">{{ t('settings.tailscale.loginHint') }}</p>
          <a :href="tailscale.loginUrl" target="_blank" rel="noopener">{{ tailscale.loginUrl }}</a>
        </template>
      </template>
    </div>

    <!-- Lyrion Music Server: internal vs external, and which build to run -->
    <div class="card" v-if="open === 'lyrion'">
      <p class="sub">{{ t('settings.lyrion.hint') }}</p>
      <div class="seg">
        <button :class="{ active: lms.mode === 'local' }" @click="applyLmsRole('local')">{{ t('settings.lyrion.internal') }}</button>
        <button :class="{ active: lms.mode === 'follow' }" @click="lms.mode = 'follow'">{{ t('settings.lyrion.external') }}</button>
      </div>

      <!-- Internal: this device runs the server, so it also owns its version. -->
      <template v-if="lms.mode === 'local'">
        <p class="sub" style="margin-top: 12px;">{{ t('settings.lyrion.internalHint') }}</p>
        <div class="between item">
          <span>{{ t('settings.lyrion.installed') }}
            <span class="muted">{{ lyrion.current || t('settings.lyrion.notInstalled') }}<template v-if="lyrion.current && lyrion.updateAvailable"> → <span class="gold">{{ lyrion.channels[lyrion.channel] && lyrion.channels[lyrion.channel].version }}</span></template><template v-else-if="lyrion.current"> · {{ t('settings.updates.upToDate') }}</template></span>
          </span>
          <a v-if="lyrion.current" :href="lmsUrl" target="_blank">{{ t('settings.lyrion.open') }}</a>
        </div>

        <template v-if="lyrion.supported">
          <label>{{ t('settings.lyrion.channel') }}</label>
          <div v-for="c in LYRION_CHANNELS" :key="c" class="net between" @click="pickLyrionChannel(c)">
            <span>{{ lyrionChannelLabel(c) }}
              <span class="muted" v-if="lyrion.channels[c]"> · {{ lyrion.channels[c].version }}</span>
            </span>
            <span class="check" v-if="lyrion.channel === c">✓</span>
          </div>
          <p class="sub" v-if="lyrion.channel !== 'release'">{{ t('settings.lyrion.channelWarning') }}</p>
        </template>

        <template v-if="!lyrion.installing">
          <div class="row" style="margin-top: 12px;">
            <button :disabled="lyrion.busy" @click="installLyrion">
              {{ lyrion.current ? t('settings.lyrion.update') : t('settings.lyrion.install') }}
            </button>
            <button class="secondary fit" :disabled="lyrion.busy" @click="loadLyrion">{{ t('settings.updates.checkAgain') }}</button>
          </div>
          <div v-if="lyrion.error" class="msg err">{{ lyrion.error }}</div>
        </template>
        <template v-else>
          <div style="width: 100%; height: 8px; background: var(--panel); border-radius: 99px; overflow: hidden; margin: 12px 0;">
            <div style="height: 100%; background: var(--gold); transition: width .4s;" :style="{ width: lyrion.progress + '%' }"></div>
          </div>
          <p class="muted">{{ lyrion.message || t('settings.lyrion.installing') }}</p>
        </template>

        <!-- Web player skin: Osmium (appliance look) vs stock Material. -->
        <template v-if="skin.supported && lyrion.current">
          <label style="margin-top: 14px;">{{ t('settings.lyrion.skinLabel') }}</label>
          <p class="sub">{{ t('settings.lyrion.skinHint') }}</p>
          <div class="seg">
            <button :class="{ active: skin.choice === 'osmium' }" :disabled="skin.busy" @click="pickSkin('osmium')">{{ t('settings.lyrion.skinOsmium') }}</button>
            <button :class="{ active: skin.choice === 'material' }" :disabled="skin.busy" @click="pickSkin('material')">{{ t('settings.lyrion.skinMaterial') }}</button>
          </div>
          <p class="sub" v-if="skin.choice === 'unset'">{{ t('settings.lyrion.skinUnset') }}</p>
          <p class="muted" v-if="skin.busy">{{ skin.message }}</p>
          <div v-if="skin.error" class="msg err">{{ skin.error }}</div>
        </template>
      </template>

      <!-- External: point squeezelite at someone else's server. -->
      <template v-else>
        <p class="sub" style="margin-top: 12px;">{{ t('settings.lyrion.externalHint') }}</p>
        <div class="row">
          <input v-model="lms.host" :placeholder="t('settings.lyrion.serverIpPlaceholder')" />
          <button class="secondary fit" @click="discoverLms">{{ t('settings.lyrion.search') }}</button>
          <button class="fit" @click="applyLmsRole('follow', lms.host)">{{ t('common.apply') }}</button>
        </div>
        <div v-for="s in lms.servers" :key="s.ip" class="net between" @click="lms.host = s.ip">
          <span>{{ s.name || s.ip }}</span><span class="muted">{{ s.ip }}</span>
        </div>
      </template>
    </div>

    <!-- Playback (per-player Lyrion prefs) -->
    <div class="card" v-if="open === 'playback'">
      <p class="sub">{{ t('settings.playback.help') }}</p>
      <p class="muted" v-if="!playbackMac">{{ t('settings.playback.noPlayer') }}</p>
      <template v-else>
        <p class="sub">{{ t('settings.playback.transition.label') }}</p>
        <span class="seg">
          <button v-for="opt in ['0', '1', '2', '3', '4']" :key="opt"
                  :class="{ active: transitionType === opt }" @click="setTransitionType(opt)">
            {{ t('settings.playback.transition.' + opt) }}
          </button>
        </span>
        <template v-if="transitionType !== '0'">
          <p class="sub">{{ t('settings.playback.transDuration') }}: <span class="silver">{{ transitionDuration }}s</span></p>
          <input type="range" min="1" max="15" :value="transitionDuration"
                 style="width: 100%; accent-color: var(--gold);"
                 @input="setTransitionDuration($event.target.value)" />
        </template>
        <p class="sub">{{ t('settings.playback.replayGain.label') }}</p>
        <span class="seg">
          <button v-for="opt in ['0', '1', '2', '3']" :key="opt"
                  :class="{ active: replayGainMode === opt }" @click="setReplayGain(opt)">
            {{ t('settings.playback.replayGain.' + opt) }}
          </button>
        </span>
        <div class="between item">
          <span>{{ t('settings.playback.fixedVolume') }}
            <span class="muted">{{ t('settings.playback.fixedVolumeHelp') }}</span>
          </span>
          <Toggle :model-value="digitalVolumeControl === '0'" @update:model-value="setFixedVolume" />
        </div>
      </template>

      <div style="margin-top: 18px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.1);">
        <p class="sub">{{ t('settings.playback.autoExpandLabel') }}</p>
        <p class="muted">{{ t('settings.playback.autoExpandHelp') }}</p>
        <span class="seg">
          <button v-for="s in [0, 3, 5, 10, 15]" :key="s"
                  :class="{ active: autoExpand === s }" @click="setAutoExpand(s)">
            {{ s === 0 ? t('settings.playback.replayGain.0') : s + 's' }}
          </button>
        </span>
      </div>
    </div>

    <!-- VU meters: same as the kiosk's Settings → VU meter -->
    <div class="card" v-if="open === 'vuMeters'">
      <p class="sub">{{ t('settings.vuMeters.help') }}</p>
      <div class="between item">
        <span>{{ t('settings.vuMeters.animated') }}
          <span class="muted">{{ t('settings.vuMeters.animatedHelp') }}</span>
        </span>
        <Toggle :model-value="vuMeter" @update:model-value="setVuMeter" />
      </div>
      <!-- meters off: the screen can show an animation instead, picked in its own section -->
      <p v-if="!vuMeter" class="muted" style="margin: 12px 0 0;">{{ t('settings.vuMeters.animationHint') }}
        <a href="#" @click.prevent="goto('animations')">{{ t('settings.vuMeters.chooseAnimation') }}</a>
      </p>

      <template v-if="vuMeter && vuStyles.length > 1">
        <label style="margin-top: 16px;">{{ t('settings.vuMeters.style') }}</label>
        <p class="muted" style="margin: 0 0 10px;">{{ t('settings.vuMeters.styleHelp') }}</p>
        <div class="vu-grid">
          <button v-for="st in vuStyles" :key="st.id" type="button" class="vu-skin" :class="{ sel: vuStyle === st.id }"
                  @click="setVuStyle(st.id)">
            <VuSkinPreview :skin-id="st.id" />
            <span class="vu-skin-name">
              <span>{{ vuStyleName(st) }}</span>
              <span v-if="vuStyle === st.id" class="check">✓</span>
            </span>
          </button>
        </div>
      </template>

      <label style="margin-top: 18px;">{{ t('settings.vuMeters.storeTitle') }}</label>
      <p class="muted" style="margin: 0 0 10px;">{{ t('settings.vuMeters.storeHelp') }}</p>
      <p v-if="vuStore.error" class="muted" style="color: #f0b4b4;">{{ vuStore.error.message }}</p>
      <p v-if="!vuStore.skins.length && (!vuStore.loaded || vuStore.checking)" class="muted">{{ t('settings.vuMeters.storeLoading') }}</p>
      <p v-else-if="!vuStore.skins.length && !vuStore.error" class="muted">{{ t('settings.vuMeters.storeEmpty') }}</p>
      <div class="vu-grid">
        <div v-for="sk in vuStore.skins" :key="sk.id" class="vu-card" :class="{ fresh: sk.new }">
          <div class="vu-preview">
            <img v-if="sk.preview" :src="sk.preview" :alt="vuStyleName(sk)" />
            <span v-if="sk.new" class="pill gold vu-badge">{{ t('settings.vuMeters.badgeNew') }}</span>
            <span v-else-if="sk.update" class="pill gold vu-badge">{{ t('settings.vuMeters.badgeUpdate') }}</span>
          </div>
          <strong>{{ vuStyleName(sk) }}</strong>
          <span class="muted">{{ [sk.author, vuStoreSize(sk.size)].filter(Boolean).join(' · ') }}</span>
          <span v-if="sk.jobError" class="muted" style="color: #f0b4b4;">{{ sk.jobError.message }}</span>
          <button v-if="sk.job === 'downloading' || sk.job === 'installing'" disabled>
            {{ sk.job === 'downloading' ? t('settings.vuMeters.downloading') : t('settings.vuMeters.installing') }}
          </button>
          <button v-else-if="!sk.supported" class="secondary" disabled>{{ t('settings.vuMeters.unsupported') }}</button>
          <button v-else-if="sk.update" @click="installVuSkin(sk)">{{ t('settings.vuMeters.update') }}</button>
          <button v-else-if="sk.installed" class="secondary" @click="removeVuSkin(sk)">{{ t('settings.vuMeters.remove') }}</button>
          <button v-else @click="installVuSkin(sk)">{{ t('settings.vuMeters.install') }}</button>
        </div>
      </div>
      <button v-if="vuStore.loaded && !vuStore.checking && !vuStore.busy" class="ghost" style="margin-top: 12px;" @click="checkVuStore">
        {{ t('settings.vuMeters.storeCheck') }}
      </button>
    </div>

    <!-- Animations: only the pick, a still of each; the animations run on the kiosk alone -->
    <div class="card" v-if="open === 'animations'">
      <p class="sub">{{ t('settings.animations.help') }}</p>
      <template v-if="vuMeter">
        <p class="muted" style="margin: 0 0 12px;">{{ t('settings.animations.vuOnNote') }}</p>
        <button class="secondary" @click="setVuMeter(false)">{{ t('settings.animations.turnOffVu') }}</button>
      </template>
      <template v-else>
        <div class="vu-grid">
          <button v-for="a in npAnimations" :key="a" type="button" class="vu-skin" :class="{ sel: npAnimation === a }"
                  @click="setNpAnimation(a)">
            <span class="anim-preview">
              <img v-if="npAnimPreview(a)" :src="npAnimPreview(a)" :alt="npAnimLabel(a)" loading="lazy" />
              <span v-else-if="a === 'none'" class="muted">{{ t('settings.animations.noneHelp') }}</span>
            </span>
            <span class="vu-skin-name">
              <span>{{ npAnimLabel(a) }}</span>
              <span v-if="npAnimation === a" class="check">✓</span>
            </span>
          </button>
        </div>
      </template>

      <label style="margin-top: 18px;">{{ t('settings.animations.storeTitle') }}</label>
      <p class="muted" style="margin: 0 0 10px;">{{ t('settings.animations.storeHelp') }}</p>
      <p v-if="animStore.error" class="muted" style="color: #f0b4b4;">{{ animStore.error.message }}</p>
      <p v-if="!animStore.animations.length && (!animStore.loaded || animStore.checking)" class="muted">{{ t('settings.animations.storeLoading') }}</p>
      <p v-else-if="!animStore.animations.length && !animStore.error" class="muted">{{ t('settings.animations.storeEmpty') }}</p>
      <div class="vu-grid">
        <div v-for="a in animStore.animations" :key="a.id" class="vu-card" :class="{ fresh: a.new }">
          <div class="vu-preview anim">
            <img v-if="a.preview" :src="a.preview" :alt="animStoreName(a)" />
            <span v-if="a.new" class="pill gold vu-badge">{{ t('settings.vuMeters.badgeNew') }}</span>
            <span v-else-if="a.update" class="pill gold vu-badge">{{ t('settings.vuMeters.badgeUpdate') }}</span>
          </div>
          <strong>{{ animStoreName(a) }}</strong>
          <span class="muted">{{ [a.author, vuStoreSize(a.size)].filter(Boolean).join(' · ') }}</span>
          <span v-if="a.jobError" class="muted" style="color: #f0b4b4;">{{ a.jobError.message }}</span>
          <button v-if="a.job === 'downloading' || a.job === 'installing'" disabled>
            {{ a.job === 'downloading' ? t('settings.vuMeters.downloading') : t('settings.vuMeters.installing') }}
          </button>
          <button v-else-if="!a.supported" class="secondary" disabled>{{ t('settings.vuMeters.unsupported') }}</button>
          <button v-else-if="a.update" @click="installAnim(a)">{{ t('settings.vuMeters.update') }}</button>
          <button v-else-if="a.installed" class="secondary" @click="removeAnim(a)">{{ t('settings.vuMeters.remove') }}</button>
          <button v-else @click="installAnim(a)">{{ t('settings.vuMeters.install') }}</button>
        </div>
      </div>
      <button v-if="animStore.loaded && !animStore.checking && !animStore.busy" class="ghost" style="margin-top: 12px;" @click="checkAnimStore">
        {{ t('settings.animations.storeCheck') }}
      </button>
    </div>

    <!-- Display mode -->
    <div class="card" v-if="open === 'display'">
      <p class="sub">{{ t('settings.display.currentLabel') }}: <span class="silver">{{ mode === 'headless' ? t('settings.display.headless') : t('settings.display.onscreen') }}</span></p>
      <div class="row">
        <button v-if="mode === 'headless'" @click="setMode('gui')">{{ t('settings.display.switchToOnscreen') }}</button>
        <button v-else class="secondary" @click="setMode('headless')">{{ t('settings.display.switchToHeadless') }}</button>
      </div>
      <template v-if="mode !== 'headless'">
        <div v-if="engines.length > 1" style="margin-top: 18px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.1);">
          <p class="sub">{{ t('settings.display.engineLabel') }}</p>
          <p class="muted">{{ t('settings.display.engineHelp') }}</p>
          <span class="seg">
            <button v-for="e in engines" :key="e"
                    :class="{ active: engine === e }" @click="setEngine(e)">
              {{ t('settings.display.engine.' + e) }}
            </button>
          </span>
        </div>

        <div style="margin-top: 18px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.1);">
          <p class="sub">{{ t('settings.display.resolutionLabel') }}</p>
          <p class="muted">{{ t('settings.display.resolutionHelp') }}</p>
          <span class="seg">
            <button v-for="opt in ['auto', '720', '1080', 'native']" :key="opt"
                    :class="{ active: uiRes === opt }" @click="setUiRes(opt)">
              {{ t('settings.display.resolution.' + opt) }}
            </button>
          </span>
        </div>

        <div style="margin-top: 18px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.1);">
          <p class="sub">{{ t('settings.display.refreshLabel') }}</p>
          <p class="muted">{{ t('settings.display.refreshHelp') }}</p>
          <p class="muted" v-if="!uiRefreshSupported">{{ t('settings.display.refreshUnsupported') }}</p>
          <span class="seg" v-else>
            <button :class="{ active: uiRefresh === 'native' }" @click="setUiRefresh('native')">{{ t('settings.display.refresh.native') }}</button>
            <button :class="{ active: uiRefresh === 'low' }" @click="setUiRefresh('low')">{{ t('settings.display.refresh.low') }}</button>
          </span>
        </div>

        <div style="margin-top: 18px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.1);">
          <p class="sub">{{ t('settings.display.pointerLabel') }}</p>
          <p class="muted">{{ t('settings.display.pointerHelp') }}</p>
          <p class="muted" v-if="!pointer.available">{{ t('settings.display.pointerUnavailable') }}</p>
          <span class="seg">
            <button :disabled="pointerBusy" :class="{ active: pointer.enabled }" @click="setPointer(true)">{{ t('settings.display.pointerOn') }}</button>
            <button :disabled="pointerBusy" :class="{ active: !pointer.enabled }" @click="setPointer(false)">{{ t('settings.display.pointerOff') }}</button>
          </span>
        </div>
      </template>

      <div style="margin-top: 18px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.1);">
        <p class="sub">{{ t('settings.display.playerLabel') }}</p>
        <p class="muted">{{ t('settings.display.playerHelp') }}</p>
        <span class="seg">
          <button :class="{ active: playerEnabled }" @click="setPlayerEnabled(true)">{{ t('settings.display.playerOn') }}</button>
          <button :class="{ active: !playerEnabled }" @click="setPlayerEnabled(false)">{{ t('settings.display.playerOff') }}</button>
        </span>
      </div>
    </div>

    <!-- Timezone -->
    <div class="card" v-if="open === 'timezone'">
      <p class="sub">{{ t('settings.timezone.hint') }}</p>
      <div class="between item">
        <span>{{ t('settings.timezone.current') }}
          <span class="muted">{{ timezone }}</span>
        </span>
      </div>
      <label>{{ t('settings.timezone.pick') }}</label>
      <select :value="timezone" :disabled="timezoneBusy" @change="setTimezone($event.target.value)">
        <option v-for="tz in timezoneList" :key="tz" :value="tz">{{ tz }}</option>
      </select>
    </div>

    <!-- Updates -->
    <div class="card" v-if="open === 'updates'">
      <div class="between item stack-narrow">
        <span>{{ t('settings.updates.channel') }}
          <span class="pill" :class="{ gold: channel !== 'prod' }">{{ otaChannelLabel(channel) }}</span>
        </span>
        <span class="seg fit">
          <button v-for="c in channels" :key="c" :class="{ active: channel === c }" @click="setChannel(c)">{{ otaChannelLabel(c) }}</button>
        </span>
      </div>
      <div v-for="k in Object.keys(kinds)" :key="k" class="between item">
        <span>{{ kindLabels[k] }}
          <span class="muted" v-if="upd[k]">
            {{ upd[k].current || '—' }}<template v-if="upd[k].update_available"> → <span class="gold">{{ upd[k].latest }}</span></template>
            <template v-else-if="upd[k].blocked === 'debian12'"> · {{ t('settings.updates.debian12Short') }}</template>
            <template v-else> · {{ t('settings.updates.upToDate') }}</template>
          </span>
          <span class="muted" v-else> · —</span>
        </span>
      </div>
      <p class="sub" v-if="otaBlockedByOs()" style="color: var(--danger); margin-top: 10px;">
        {{ t('settings.updates.debian12Banner') }}
      </p>
      <div class="row" style="margin-top: 12px;" v-if="!otaBlockedByOs()">
        <button v-if="hasUpdates()" :disabled="applying.active" @click="applyAll">{{ t('settings.updates.updateAll') }}</button>
        <button class="secondary" :disabled="updBusy || applying.active" @click="checkAll">{{ updBusy ? t('settings.updates.checking') : t('settings.updates.checkAgain') }}</button>
      </div>
      <div class="row" style="margin-top: 10px;" v-if="changelogAvailable()">
        <button class="ghost" @click="showChangelog">{{ t('settings.updates.whatsNew') }}</button>
      </div>
      <div style="margin-top: 18px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.1);">
        <p class="sub">{{ t('settings.netCheck.openHelp') }}</p>
        <button class="secondary" style="display: inline-block;" @click="openNetCheck">{{ t('settings.netCheck.open') }}</button>
      </div>
    </div>

    <!-- Network check: reached from Updates and System -->
    <div class="card" v-if="open === 'netCheck'">
      <p class="sub">{{ t('settings.netCheck.help') }}</p>
      <div v-if="nc.busy" class="msg">{{ t('settings.netCheck.running') }}</div>
      <div v-else-if="nc.failed" class="msg err">{{ t('settings.netCheck.failed') }}</div>
      <div v-else-if="nc.data" class="msg nc-verdict" :class="ncVerdict()">{{ ncVerdictText() }}</div>
      <div v-for="g in NC_GROUPS" :key="g.id" class="item nc-step nc-plain">
        <span class="nc-mark" :class="ncGroup(g)">{{ ncMark[ncGroup(g)] }}</span>
        <span class="nc-body between">
          <span>{{ t(`settings.netCheck.groups.${g.id}`) }}</span>
          <span class="nc-state" :class="ncGroup(g)">{{ t(`settings.netCheck.status.${ncGroup(g)}`) }}</span>
        </span>
      </div>
      <div class="row" style="margin-top: 12px;">
        <button :disabled="nc.busy" @click="runNetCheck">{{ nc.busy ? t('settings.netCheck.running') : (nc.data ? t('settings.netCheck.again') : t('settings.netCheck.run')) }}</button>
        <button class="ghost" @click="nc.advanced = !nc.advanced">{{ nc.advanced ? t('settings.netCheck.advancedHide') : t('settings.netCheck.advanced') }}</button>
      </div>
      <div v-if="nc.advanced" class="nc-advanced">
      <template v-for="id in NC_STEPS" :key="id">
        <div class="item nc-step">
          <span class="nc-mark" :class="ncStep(id).status">{{ ncMark[ncStep(id).status] }}</span>
          <span class="nc-body">
            <span class="between">
              <span>{{ t(`settings.netCheck.steps.${id}`) }}</span>
              <span class="muted nc-detail">{{ ncDetail(ncStep(id)) }}</span>
            </span>
            <span v-if="ncStep(id).error" class="nc-why" :class="ncStep(id).status">{{ ncReason(ncStep(id)) }}</span>
            <span v-else-if="ncStep(id).status === 'skip' && nc.data" class="nc-why">{{ t('settings.netCheck.status.skip') }}</span>
            <span v-for="src in (id === 'ota' && ncStep(id).sources) || []" :key="src.id" class="nc-src">
              <span class="nc-mark" :class="src.status">{{ ncMark[src.status] }}</span>
              <span class="nc-body">
                <span class="between">
                  <span>{{ t(`settings.netCheck.sources.${src.id}`) }}</span>
                  <span class="muted nc-detail">{{ src.host }}<template v-if="src.ms !== undefined"> · {{ src.ms }} ms</template></span>
                </span>
                <span v-if="src.error" class="nc-why" :class="src.status">{{ ncReason(src) }}</span>
              </span>
            </span>
          </span>
        </div>
      </template>
      <p class="muted" v-if="nc.data && !nc.busy" style="margin-top: 10px;">{{ t('settings.netCheck.lastRun', { time: ncTime() }) }} · {{ nc.data.channel }}</p>
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

    <!-- Companion iPhone/iPad (LyrPlay, third-party) -->
    <div class="card" v-if="open === 'companionIos'">
      <p class="sub">{{ t('settings.companionIos.hint') }}</p>
      <div v-if="lyrplayQr" style="margin-top: 14px;"><span class="qrbox"><img :src="lyrplayQr" alt="QR LyrPlay" /></span></div>
      <p style="margin-top: 12px;">
        <a :href="LYRPLAY_APP_STORE_URL" target="_blank" rel="noopener">{{ t('settings.companionIos.open') }}</a>
      </p>
      <p class="muted" style="margin-top: 10px;">{{ t('settings.companionIos.disclaimer') }}</p>
    </div>

    <!-- Account -->
    <div class="card" v-if="open === 'account'">
      <label>{{ t('settings.account.newUsername') }}</label><input v-model="acc.username" autocomplete="username" />
      <label>{{ t('settings.account.currentPassword') }}</label><input v-model="acc.current" type="password" autocomplete="current-password" />
      <label>{{ t('settings.account.newPassword') }}</label><input v-model="acc.next" type="password" autocomplete="new-password" />
      <div style="margin-top: 12px;"><button @click="changePw">{{ t('settings.account.change') }}</button></div>
    </div>

    <!-- Backup / restore -->
    <div class="card" v-if="open === 'backup'">
      <p class="sub">{{ t('settings.backup.hint') }}</p>

      <label>{{ t('settings.backup.passphrase') }}</label>
      <input v-model="backupPass" type="password" autocomplete="new-password" />
      <p class="muted" style="margin-top: 4px;">{{ t('settings.backup.passphraseHint') }}</p>

      <div class="row" style="margin-top: 12px;">
        <button :disabled="backupBusy" @click="createBackup">{{ t('settings.backup.create') }}</button>
        <button class="secondary" :disabled="backupBusy" @click="downloadBackup()">{{ t('settings.backup.downloadNow') }}</button>
        <button class="secondary" @click="restoreFileInput.click()">{{ t('settings.backup.restoreFromFile') }}</button>
        <input ref="restoreFileInput" type="file" accept=".gz,.tar.gz,application/gzip" style="display: none;" @change="uploadRestore" />
      </div>

      <div style="margin-top: 18px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.1);">
        <div class="net between">
          <span>{{ t('settings.backup.scheduled') }}</span>
          <Toggle :model-value="backupScheduled" @update:model-value="saveBackupScheduled" />
        </div>
        <p class="muted">{{ t('settings.backup.scheduledHint') }}</p>
      </div>

      <div style="margin-top: 18px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.1);">
        <label>{{ t('settings.backup.stored') }}</label>
        <p v-if="!backupGens.length" class="sub">{{ t('settings.backup.none') }}</p>
        <div v-for="g in backupGens" :key="g.id" class="net between" style="align-items: flex-start;">
          <div>
            <div>
              {{ fmtBackupStamp(g.id) }}
              <span v-if="g.encrypted" class="muted" style="font-size: 11px; margin-left: 6px;">🔒 {{ t('settings.backup.encrypted') }}</span>
              <span v-if="g.trigger && g.trigger !== 'manual'" class="muted" style="font-size: 11px; margin-left: 6px;">{{ g.trigger }}</span>
            </div>
            <div class="muted">{{ (g.categories || []).join(', ') }} · {{ fmtBackupSize(g.size) }}</div>
          </div>
          <div class="row">
            <button class="secondary fit" @click="downloadBackup(g.id)">⬇</button>
            <button class="secondary fit" @click="restoreGen(g)">{{ t('settings.backup.restoreThis') }}</button>
            <button class="danger fit" @click="deleteGen(g)">✕</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Language -->
    <div class="card" v-if="open === 'language'">
      <p class="sub">{{ t('settings.language.hint') }}</p>
      <LanguageSelector variant="list" />
    </div>

    <!-- device-rebooting overlay: reboot / factory reset / a restore that reboots -->
    <div v-if="rebootWait.active" class="overlay">
      <div class="card" style="width: 340px; max-width: 92vw; text-align: center;">
        <div class="spinner"></div>
        <h3 style="justify-content: center;">{{ t('settings.system.rebootWaitTitle') }}</h3>
        <p class="sub">{{ rebootWait.phase === 'going-down' ? t('settings.system.rebootGoingDown') : t('settings.system.rebootComingBack') }}</p>
        <p class="muted">{{ t('settings.system.rebootAutoReconnect') }}</p>
      </div>
    </div>

    <!-- forced blocking update modal (kiosk-style) -->
    <div v-if="applying.active" class="overlay">
      <div class="card" style="width: 340px; max-width: 92vw; text-align: center;">
        <template v-if="applying.state !== 'done' && applying.state !== 'error' && applying.state !== 'apply_error'">
          <div class="spinner"></div>
          <h3 style="justify-content: center;">{{ t('settings.updates.updating', { label: applying.label }) }}</h3>
          <p class="sub" style="margin-bottom: 6px;">
            {{ applying.message || applying.state || t('common.loading') }}
            <template v-if="applying.progress !== null"> · {{ applying.progress }}%</template>
          </p>
          <p class="muted" v-if="applying.doneList.length">
            {{ t('settings.updates.updatedList') }}: {{ applying.doneList.join(', ') }}
          </p>
          <!-- The appliance owns the sequence now, so leaving is safe. -->
          <p class="muted">{{ t('settings.updates.keepPowered') }}</p>
        </template>
        <template v-else>
          <h3 style="justify-content: center;">{{ applying.error ? t('settings.updates.interrupted') : t('settings.updates.completed') }}</h3>
          <p class="sub">{{ applying.message || (applying.error ? t('settings.updates.genericError') : '') }}</p>
          <p class="muted" v-if="applying.doneList.length">{{ t('settings.updates.updatedList') }}: {{ applying.doneList.join(', ') }}</p>
          <button style="margin-top: 10px;" @click="closeApplyModal">{{ t('common.close') }}</button>
        </template>
      </div>
    </div>

    <!-- dismissible "what's new" changelog popup -->
    <div v-if="changelog.open" class="overlay" @click.self="closeChangelog">
      <div class="card" style="width: 420px; max-width: 92vw;">
        <h3>{{ t('settings.updates.changelogTitle', { version: changelog.version }) }}</h3>
        <p class="sub" style="white-space: pre-wrap; word-break: break-word; max-height: 50vh; overflow-y: auto; margin-bottom: 16px;">{{ changelog.notes }}</p>
        <button @click="closeChangelog">{{ t('common.close') }}</button>
      </div>
    </div>

    <!-- System -->
    <div class="card" v-if="open === 'system'">
      <div class="row">
        <button class="secondary" @click="reboot">{{ t('settings.system.reboot') }}</button>
        <button class="secondary" @click="shutdown">{{ t('settings.system.shutdown') }}</button>
      </div>
      <div style="margin-top: 18px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.1);">
        <p class="sub">{{ t('settings.netCheck.openHelp') }}</p>
        <button class="secondary" style="display: inline-block;" @click="openNetCheck">{{ t('settings.netCheck.open') }}</button>
      </div>
      <div style="margin-top: 18px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.1);">
        <p class="sub">{{ t('settings.system.supportBundleHint') }}</p>
        <button class="secondary" style="display: inline-block;" @click="downloadSupportBundle">{{ t('settings.system.supportBundle') }}</button>
      </div>
      <div style="margin-top: 18px; padding-top: 16px; border-top: 1px solid rgba(224,90,90,0.25);">
        <p class="sub">{{ t('settings.system.factoryHint') }}</p>
        <label>{{ t('settings.system.adminPassword') }}</label><input v-model="resetPw" type="password" />
        <div style="margin-top: 12px;"><button class="danger" @click="factoryReset">{{ t('settings.system.factoryReset') }}</button></div>
      </div>
    </div>

    <!-- Debug: boot / kernel-panic troubleshooting flags -->
    <div class="card" v-if="open === 'debug'">
      <p class="sub">{{ t('settings.debug.bootHint') }}</p>
      <div class="between item">
        <span>{{ t('settings.debug.plymouth') }}
          <span class="muted">{{ t('settings.debug.plymouthHelp') }}</span>
        </span>
        <Toggle :model-value="plymouthDisabled" :disabled="debugFlagsBusy" @update:model-value="togglePlymouth" />
      </div>
      <div class="between item">
        <span>{{ t('settings.debug.kdump') }}
          <span class="muted">{{ kdumpInstalled ? t('settings.debug.kdumpHelp') : t('settings.debug.kdumpNotInstalled') }}</span>
        </span>
        <Toggle :model-value="kdumpEnabled" :disabled="debugFlagsBusy" @update:model-value="toggleKdump" />
      </div>
    </div>
  </template>
</template>
