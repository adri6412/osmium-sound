<script setup>
import { ref, reactive, computed, watch, onMounted, onUnmounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import QRCode from 'qrcode';
import { api } from '../api.js';
import { useI18n } from '../i18n';
import Toggle from '../components/Toggle.vue';
import LanguageSelector from '../components/LanguageSelector.vue';
import SourcesPanel from '../components/SourcesPanel.vue';

const host = location.hostname;
const route = useRoute();
const router = useRouter();
const { t } = useI18n();

// ── kiosk-like submenu navigation ────────────────────────────────
const sections = computed(() => [
  { key: 'network',   label: t('settings.sections.network.label'),   desc: t('settings.sections.network.desc') },
  { key: 'audio',     label: t('settings.sections.audio.label'),     desc: t('settings.sections.audio.desc') },
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
  { key: 'display',   label: t('settings.sections.display.label'),   desc: t('settings.sections.display.desc') },
  { key: 'timezone',  label: t('settings.sections.timezone.label'),  desc: t('settings.sections.timezone.desc') },
  { key: 'updates',   label: t('settings.sections.updates.label'),   desc: t('settings.sections.updates.desc') },
  { key: 'companion', label: t('settings.sections.companion.label'), desc: t('settings.sections.companion.desc') },
  { key: 'account',   label: t('settings.sections.account.label'),   desc: t('settings.sections.account.desc') },
  { key: 'backup',    label: t('settings.sections.backup.label'),    desc: t('settings.sections.backup.desc') },
  { key: 'language',  label: t('settings.sections.language.label'),  desc: t('settings.sections.language.desc') },
  { key: 'system',    label: t('settings.sections.system.label'),    desc: t('settings.sections.system.desc') },
  { key: 'debug',     label: t('settings.sections.debug.label'),     desc: t('settings.sections.debug.desc') },
]);
// 'multiroom' was this section's key before it became "Lyrion Music Server";
// keep old bookmarks and the kiosk's deep links working. 'dsp' is held back
// (see the sections list above) — redirect a hand-typed ?open=dsp back to the
// section list instead of rendering the card.
const normalizeSection = (k) => (k === 'multiroom' ? 'lyrion' : k === 'dsp' ? '' : (k || ''));
const open = ref(normalizeSection(route.query.open));
watch(() => route.query.open, (v) => { open.value = normalizeSection(v); });
function goto(k) { router.replace({ query: k ? { open: k } : {} }); }
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

// ── HAR network captures (Debug section) ────────────────────────────
// Recording only happens on the kiosk itself (Settings.jsx → Electron's
// webContents.debugger, see main/main.js) — the web admin can only list,
// download and delete whatever .har files have already landed on disk.
const harCaptures = ref([]);
const harBusy = ref(false);

function fmtHarSize(n) {
  if (!n) return '0 kB';
  return n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' kB';
}
function fmtHarStamp(mtime) {
  return mtime ? new Date(mtime * 1000).toLocaleString() : '';
}

async function loadHarCaptures() {
  const r = await api.sys('har_captures');
  if (r.ok) harCaptures.value = r.data.captures || [];
}

async function downloadHarCapture(name) {
  try {
    const resp = await fetch('/api/system/har_captures/' + encodeURIComponent(name), { credentials: 'same-origin' });
    if (!resp.ok) throw new Error(await resp.text() || resp.statusText);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  } catch (e) {
    say(t('settings.debug.downloadFailed'), true);
    console.error('har capture download failed', e);
  }
}

async function deleteHarCapture(name) {
  if (!confirm(t('settings.debug.deleteConfirm'))) return;
  harBusy.value = true;
  const r = await api.del('/api/system/har_captures/' + encodeURIComponent(name));
  harBusy.value = false;
  if (!r.ok || r.data.success === false) say(bodyMsg(r, t('settings.debug.deleteFailed')), true);
  loadHarCaptures();
}

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
const lms = reactive({ mode: 'local', host: '', servers: [] });
async function loadLms() {
  const r = await api.sys('lms_role');
  if (r.ok) { lms.mode = r.data.mode || 'local'; lms.host = r.data.host || ''; }
}
async function discoverLms() {
  say(t('settings.lyrion.searching'));
  const r = await api.sys('discover_lms'); if (r.ok) { lms.servers = r.data.servers || []; say(''); }
}
async function applyLmsRole(mode, hostArg) {
  const r = await api.sysPost('lms_role', { mode, host: hostArg || lms.host || null });
  say(bodyMsg(r, t('settings.lyrion.roleUpdated')), !(r.ok && r.data.success !== false)); loadLms();
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

// ── display mode ─────────────────────────────────────────────────
const mode = ref('');
async function loadMode() { const r = await api.sys('display_mode'); if (r.ok) mode.value = r.data.mode; }
async function setMode(m) {
  if (m === 'headless' && !confirm(t('settings.display.confirmHeadless'))) return;
  const r = await api.sysPost('display_mode', { mode: m });
  if (r.ok && r.data.success !== false) { mode.value = r.data.mode || m; say(bodyMsg(r, t('settings.display.changed'))); }
  else say(bodyMsg(r, t('settings.display.changeFailed')), true);
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
  if (r.ok && r.data.success !== false) { vuMeter.value = r.data.enabled; say(bodyMsg(r, t('settings.display.vuMeterChanged'))); }
  else say(bodyMsg(r, t('settings.display.vuMeterFailed')), true);
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
  os: t('settings.updates.kindOs'),
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
  // Downgrading back to prod from dev is gated by a newer prod release, so
  // warn before the switch rather than after — the user can't just flip back.
  if (channel.value === 'prod' && c === 'dev' && !confirm(t('settings.updates.confirmProdToDev'))) return;
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
const sleep = (ms) => new Promise(res => setTimeout(res, ms));

// "What's new" popup — ui/system/os all ship from the same tagged release, so
// their `notes` are normally identical; take whichever check response has one.
const changelog = reactive({ open: false, version: '', notes: '' });
function changelogAvailable() {
  return Object.keys(kinds).some(k => upd[k] && upd[k].update_available && upd[k].notes);
}
function showChangelog() {
  const withNotes = Object.keys(kinds).map(k => upd[k]).find(u => u && u.update_available && u.notes);
  if (!withNotes) return;
  changelog.version = withNotes.latest || '';
  changelog.notes = withNotes.notes;
  changelog.open = true;
}
function closeChangelog() { changelog.open = false; }

// The whole sequence runs on the appliance (hifi-update-runner.sh, driven by a
// plan persisted under /var/lib). This page only starts it and renders its
// progress, so losing the browser — or this very daemon, which the system
// bundle restarts — no longer interrupts anything.
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
  // first stretch after an OS-step reboot, before hifi-update-resume.service
  // has come up (it waits on network-online.target). Treating the very first
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
    if (s.state === 'finished') return true;
    if (s.state === 'error' || s.state === 'interrupted') return false;
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
  applying.state = ok ? 'finished' : 'error';
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
  if (s.state === 'running' || s.state === 'interrupted') {
    // 'interrupted' here just means the page (re)loaded during the gap
    // before hifi-update-resume.service comes up after a reboot — give
    // pollPlan its own grace period instead of declaring failure on this
    // single snapshot.
    const ok = await pollPlan();
    applying.error = !ok;
    applying.state = ok ? 'finished' : 'error';
    if (ok) applying.message = t('settings.updates.allCompleted');
  } else {
    applying.error = s.state !== 'finished';
    applying.state = applying.error ? 'error' : 'finished';
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
  // Generation ids are YYYYMMDD-HHMMSS.
  if (!id || id.length < 15) return id || '';
  return `${id.slice(6, 8)}/${id.slice(4, 6)}/${id.slice(0, 4)} ${id.slice(9, 11)}:${id.slice(11, 13)}`;
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
      // A restored webui.db invalidates this very session server-side
      // (hifi-webui reopens the database it just got restarted with), so a
      // stale page here can't just keep going — reload so the browser
      // re-authenticates on its own and lands back on /login if needed.
      // Harmless when the session is still valid too: just re-fetches
      // whatever changed.
      setTimeout(() => window.location.reload(), 1200);
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
  loadNet(); loadAudio(); loadDsp(); loadFir(); loadToggles(); loadShell(); loadLms(); loadLyrion(); loadPlayback();
  loadMode(); loadPlayerEnabled(); loadUiRes(); loadTimezone(); loadVuMeter(); loadAutoExpand(); loadChannel(); checkAll(); resumePlanIfRunning(); loadBackups(); loadTailscale(); loadHarCaptures();
  timezonePoll = setInterval(pollTimezone, 10000);
  // Tell the global UpdateProgressOverlay (mounted in App.vue) that this page
  // owns the OTA modal while it's open, so the two never render on top of
  // each other. The global one takes back over as soon as this page unmounts.
  window.dispatchEvent(new CustomEvent('hifi-settings-active', { detail: true }));
});
onUnmounted(() => {
  if (lyrionPoll) clearInterval(lyrionPoll); if (tailscalePoll) clearInterval(tailscalePoll);
  if (timezonePoll) clearInterval(timezonePoll);
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
      <p class="sub" style="margin-top: 4px;">{{ t('settings.audio.playerNameHint') }}</p>
    </div>

    <!-- Sources (native — talks directly to sources_server.py through
         webui_server's session-gated /api/system/sources|usb|internal|apply
         forwarders, see SourcesPanel.vue) -->
    <div class="card" v-if="open === 'sources'">
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
          <a v-if="lyrion.current" :href="`http://${host}:9000`" target="_blank">{{ t('settings.lyrion.open') }}</a>
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
      <p class="sub">{{ t('settings.playback.autoExpandLabel') }}</p>
      <p class="muted">{{ t('settings.playback.autoExpandHelp') }}</p>
      <span class="seg">
        <button v-for="s in [0, 3, 5, 10, 15]" :key="s"
                :class="{ active: autoExpand === s }" @click="setAutoExpand(s)">
          {{ s === 0 ? t('settings.display.vuMeterOff') : s + 's' }}
        </button>
      </span>
    </div>

    <!-- Display mode -->
    <div class="card" v-if="open === 'display'">
      <p class="sub">{{ t('settings.display.currentLabel') }}: <span class="silver">{{ mode === 'headless' ? t('settings.display.headless') : t('settings.display.onscreen') }}</span></p>
      <div class="row">
        <button v-if="mode === 'headless'" @click="setMode('gui')">{{ t('settings.display.switchToOnscreen') }}</button>
        <button v-else class="secondary" @click="setMode('headless')">{{ t('settings.display.switchToHeadless') }}</button>
      </div>
      <template v-if="mode !== 'headless'">
        <p class="sub">{{ t('settings.display.resolutionLabel') }}</p>
        <p class="muted">{{ t('settings.display.resolutionHelp') }}</p>
        <span class="seg">
          <button v-for="opt in ['auto', '720', '1080', 'native']" :key="opt"
                  :class="{ active: uiRes === opt }" @click="setUiRes(opt)">
            {{ t('settings.display.resolution.' + opt) }}
          </button>
        </span>
      </template>
      <p class="sub">{{ t('settings.display.vuMeterLabel') }}</p>
      <p class="muted">{{ t('settings.display.vuMeterHelp') }}</p>
      <span class="seg">
        <button :class="{ active: vuMeter }" @click="setVuMeter(true)">{{ t('settings.display.vuMeterOn') }}</button>
        <button :class="{ active: !vuMeter }" @click="setVuMeter(false)">{{ t('settings.display.vuMeterOff') }}</button>
      </span>
      <p class="sub">{{ t('settings.display.playerLabel') }}</p>
      <p class="muted">{{ t('settings.display.playerHelp') }}</p>
      <span class="seg">
        <button :class="{ active: playerEnabled }" @click="setPlayerEnabled(true)">{{ t('settings.display.playerOn') }}</button>
        <button :class="{ active: !playerEnabled }" @click="setPlayerEnabled(false)">{{ t('settings.display.playerOff') }}</button>
      </span>
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
      <div class="between item">
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
            <template v-else> · {{ t('settings.updates.upToDate') }}</template>
          </span>
          <span class="muted" v-else> · —</span>
        </span>
      </div>
      <div class="row" style="margin-top: 12px;">
        <button v-if="hasUpdates()" :disabled="applying.active" @click="applyAll">{{ t('settings.updates.updateAll') }}</button>
        <button class="secondary" :disabled="updBusy || applying.active" @click="checkAll">{{ updBusy ? t('settings.updates.checking') : t('settings.updates.checkAgain') }}</button>
      </div>
      <div class="row" style="margin-top: 10px;" v-if="changelogAvailable()">
        <button class="ghost" @click="showChangelog">{{ t('settings.updates.whatsNew') }}</button>
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
        <p class="sub">{{ t('settings.system.supportBundleHint') }}</p>
        <button class="secondary" style="display: inline-block;" @click="downloadSupportBundle">{{ t('settings.system.supportBundle') }}</button>
      </div>
      <div style="margin-top: 18px; padding-top: 16px; border-top: 1px solid rgba(224,90,90,0.25);">
        <p class="sub">{{ t('settings.system.factoryHint') }}</p>
        <label>{{ t('settings.system.adminPassword') }}</label><input v-model="resetPw" type="password" />
        <div style="margin-top: 12px;"><button class="danger" @click="factoryReset">{{ t('settings.system.factoryReset') }}</button></div>
      </div>
    </div>

    <!-- Debug: HAR network captures recorded on the kiosk -->
    <div class="card" v-if="open === 'debug'">
      <p class="sub">{{ t('settings.debug.hint') }}</p>
      <p v-if="!harCaptures.length" class="sub">{{ t('settings.debug.none') }}</p>
      <div v-for="c in harCaptures" :key="c.name" class="net between" style="align-items: flex-start;">
        <div>
          <div>{{ fmtHarStamp(c.mtime) }}</div>
          <div class="muted">{{ c.name }} · {{ fmtHarSize(c.size) }}</div>
        </div>
        <div class="row">
          <button class="secondary fit" :disabled="harBusy" @click="downloadHarCapture(c.name)">⬇</button>
          <button class="danger fit" :disabled="harBusy" @click="deleteHarCapture(c.name)">✕</button>
        </div>
      </div>
    </div>
  </template>
</template>
