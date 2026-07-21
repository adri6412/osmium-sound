<script setup>
import { ref, onMounted } from 'vue';
import { api } from '../api.js';

const msg = ref(''); const err = ref(false);
function say(m, isErr = false) { msg.value = m; err.value = isErr; }

// ── network ──────────────────────────────────────────────────────
const net = ref({}); const wifi = ref([]); const ssid = ref(''); const wifiPass = ref('');
async function loadNet() {
  const r = await api.sys('network_status'); if (r.ok) net.value = r.data;
}
async function scanWifi() {
  say('Scanning…'); const r = await api.sys('wifi_scan');
  if (r.ok) { wifi.value = r.data.networks || []; say('' ); } else say('Scan failed', true);
}
async function connectWifi() {
  say('Connecting…');
  const r = await api.sysPost('wifi_connect', { ssid: ssid.value, password: wifiPass.value });
  if (r.ok && r.data.success !== false) { say('Connected'); loadNet(); } else say(r.data.message || 'Failed', true);
}
async function wired() {
  say('Requesting DHCP…'); const r = await api.sysPost('wired_dhcp', {});
  if (r.ok && r.data.success !== false) { say('Connected'); loadNet(); } else say(r.data.message || 'Failed', true);
}

// ── audio + player name ──────────────────────────────────────────
const devices = ref([]); const currentDevice = ref('default'); const playerName = ref('');
async function loadAudio() {
  const r = await api.sys('audio_devices');
  if (r.ok) { devices.value = r.data.devices || []; currentDevice.value = r.data.current || 'default'; }
  const p = await api.sys('player_name'); if (p.ok) playerName.value = p.data.name || '';
}
async function pickDevice(id) {
  currentDevice.value = id; const r = await api.sysPost('audio_device', { device: id });
  say(r.ok ? 'Output changed' : 'Failed', !r.ok);
}
async function saveName() {
  const r = await api.sysPost('player_name', { name: playerName.value });
  say(r.ok ? 'Name saved' : 'Failed', !r.ok);
}

// ── display mode ─────────────────────────────────────────────────
const mode = ref('');
async function loadMode() { const r = await api.sys('display_mode'); if (r.ok) mode.value = r.data.mode; }
async function setMode(m) {
  if (m === 'headless' && !confirm('The screen will turn off. Continue?')) return;
  const r = await api.sysPost('display_mode', { mode: m });
  if (r.ok) { mode.value = r.data.mode || m; say(r.data.message || 'Display mode changed'); }
  else say('Failed', true);
}

// ── updates ──────────────────────────────────────────────────────
const upd = ref({ ui: null, system: null, os: null, lyrion: null });
const channels = { ui: 'app', system: 'system', os: 'os', lyrion: 'lyrion' };
async function checkUpd(kind) {
  const r = await api.sys(`updates/${channels[kind]}/check`);
  if (r.ok) upd.value[kind] = r.data;
}
async function applyUpd(kind) {
  say(`Updating ${kind}…`);
  await api.sysPost(`updates/${channels[kind]}/apply`, {});
}
async function checkAll() { for (const k of Object.keys(channels)) await checkUpd(k); }

// ── account ──────────────────────────────────────────────────────
const acc = ref({ username: '', current: '', next: '' });
async function changePw() {
  const r = await api.changePassword(acc.value.username, acc.value.current, acc.value.next);
  if (r.ok && r.data.success) { say('Password updated'); acc.value = { username: '', current: '', next: '' }; }
  else say(r.data.message || 'Failed', true);
}

// ── factory reset (password reauth) ──────────────────────────────
const resetPw = ref('');
async function factoryReset() {
  if (!confirm('This erases ALL settings and this account, then reboots into setup. Continue?')) return;
  const r = await api.post('/api/system/factory_reset', { password: resetPw.value });
  if (r.ok && r.data.success !== false) say('Factory reset started — the device will reboot');
  else say(r.data.message || 'Failed', true);
}

onMounted(async () => {
  await loadNet(); await loadAudio(); await loadMode(); await checkAll();
  const u = await api.authStatus(); acc.value.username = '';
});
</script>

<template>
  <div class="between" style="margin-bottom: 8px;">
    <RouterLink to="/">← Dashboard</RouterLink>
  </div>
  <div v-if="msg" class="msg" :class="{ err }">{{ msg }}</div>

  <div class="card">
    <h3>Network</h3>
    <p class="muted">Active: {{ net.type || '—' }} {{ net.ip ? '· ' + net.ip : '' }}</p>
    <div class="row">
      <button class="secondary" @click="scanWifi">Scan Wi-Fi</button>
      <button class="secondary" @click="wired">Use Ethernet (DHCP)</button>
    </div>
    <div v-for="n in wifi" :key="n.ssid" class="net between" @click="ssid = n.ssid">
      <span>{{ n.ssid }}</span><span class="muted">{{ n.signal }}%</span>
    </div>
    <template v-if="wifi.length">
      <label>SSID</label><input v-model="ssid" />
      <label>Password</label><input v-model="wifiPass" type="password" />
      <div style="margin-top: 10px;"><button @click="connectWifi">Connect</button></div>
    </template>
  </div>

  <div class="card">
    <h3>Audio output</h3>
    <div v-for="d in devices" :key="d.id" class="net between" @click="pickDevice(d.id)">
      <span>{{ d.name || d.id }}</span><span v-if="d.id === currentDevice">✓</span>
    </div>
    <label>Player name</label>
    <div class="row"><input v-model="playerName" /><button class="secondary" @click="saveName">Save</button></div>
  </div>

  <div class="card">
    <h3>Display mode</h3>
    <p class="muted">Current: {{ mode || '—' }}</p>
    <div class="row">
      <button v-if="mode === 'headless'" @click="setMode('gui')">Switch to on-screen</button>
      <button v-else class="secondary" @click="setMode('headless')">Switch to headless</button>
    </div>
  </div>

  <div class="card">
    <h3>Updates</h3>
    <div v-for="k in ['ui','system','os','lyrion']" :key="k" class="between" style="padding: 6px 0;">
      <span>{{ k.toUpperCase() }}
        <span class="muted" v-if="upd[k]">
          {{ upd[k].update_available ? ('→ ' + (upd[k].latest || '')) : 'up to date' }}
        </span>
      </span>
      <button class="secondary" v-if="upd[k] && upd[k].update_available" @click="applyUpd(k)">Update</button>
    </div>
    <div style="margin-top: 10px;"><button class="secondary" @click="checkAll">Check again</button></div>
  </div>

  <div class="card">
    <h3>Web account</h3>
    <label>Username</label><input v-model="acc.username" autocomplete="username" />
    <label>Current password</label><input v-model="acc.current" type="password" autocomplete="current-password" />
    <label>New password</label><input v-model="acc.next" type="password" autocomplete="new-password" />
    <div style="margin-top: 10px;"><button @click="changePw">Change password</button></div>
  </div>

  <div class="card">
    <h3>Factory reset</h3>
    <p class="muted">Erases all settings and this account, then reboots into setup.
      Confirm with your admin password.</p>
    <label>Admin password</label><input v-model="resetPw" type="password" />
    <div style="margin-top: 10px;"><button class="danger" @click="factoryReset">Factory reset</button></div>
  </div>
</template>
