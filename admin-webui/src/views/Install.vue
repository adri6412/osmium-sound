<!-- Installer, driven from a browser.

     Shown only in a live session booted from the "Install" menu entry
     (auth/status reports `installer`, read from the kernel command line). The
     appliance may have no keyboard attached at all, so the on-screen wizard
     shows a QR with this address: whoever follows it must land on the
     installation, not on the login form of a system that does not exist yet.

     English only, like the rest of the installer flow: it runs before anyone
     has chosen a language. -->
<template>
  <div style="max-width: 560px; margin: 0 auto;">
    <div v-if="stage === 'pick'" class="card">
      <h3><span class="dot"></span>Install Osmium Sound</h3>
      <p class="sub">Choose the disk to install onto. Everything on it will be erased.</p>

      <p v-if="loading" class="sub">Looking for disks…</p>
      <p v-else-if="error" class="sub" style="color: var(--red, #e57373);">{{ error }}</p>
      <p v-else-if="!disks.length" class="sub">
        No disk found. The medium you booted from is never offered.
      </p>

      <div v-for="d in disks" :key="d.path" class="row"
           style="justify-content: space-between; align-items: center; margin-top: 10px;">
        <div>
          <div><strong>{{ d.model || d.path }}</strong></div>
          <div class="sub">{{ d.path }} · {{ gb(d.size) }} · {{ d.transport || 'unknown bus' }}</div>
        </div>
        <button @click="choose(d)">Install here</button>
      </div>

      <div style="margin-top: 16px;">
        <button :disabled="loading" @click="load">Refresh</button>
      </div>
    </div>

    <div v-else-if="stage === 'confirm'" class="card">
      <h3><span class="dot"></span>Erase {{ target.path }}?</h3>
      <p class="sub">
        {{ target.model || 'Disk' }} · {{ gb(target.size) }}. Everything on this disk will be
        destroyed, including any other operating system. This cannot be undone.
      </p>
      <div class="row" style="gap: 10px; margin-top: 16px;">
        <button :disabled="busy" @click="start">{{ busy ? 'Starting…' : 'Erase and install' }}</button>
        <button :disabled="busy" @click="stage = 'pick'">Cancel</button>
      </div>
    </div>

    <div v-else class="card">
      <h3><span class="dot"></span>{{ done ? 'Installation complete' : 'Installing…' }}</h3>
      <p class="sub">{{ message }}</p>
      <div v-if="!done && !failed" style="height: 8px; background: rgba(255,255,255,.1); border-radius: 4px; margin-top: 12px;">
        <div :style="{ width: progress + '%', height: '100%', background: 'var(--gold, #d4a437)', borderRadius: '4px' }"></div>
      </div>
      <p v-if="done" class="sub" style="margin-top: 12px;">
        Remove the installation medium and restart the device.
      </p>
      <p v-if="failed" class="sub" style="margin-top: 12px; color: var(--red, #e57373);">
        The installation did not complete. Nothing else was changed on the disk.
      </p>
      <div v-if="failed" style="margin-top: 16px;">
        <button @click="stage = 'pick'">Back</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue';
import { api } from '../api';

const stage = ref('pick');
const disks = ref([]);
const target = ref({});
const loading = ref(true);
const busy = ref(false);
const error = ref('');
const message = ref('');
const progress = ref(0);
const done = ref(false);
const failed = ref(false);
let timer = null;

function gb(bytes) {
  const n = Number(bytes || 0);
  return n >= 1e9 ? (n / 1e9).toFixed(1) + ' GB' : Math.round(n / 1e6) + ' MB';
}

async function load() {
  loading.value = true; error.value = '';
  const { ok, data } = await api.installDisks();
  loading.value = false;
  if (!ok || data.success === false) { error.value = data.message || 'Could not list the disks.'; return; }
  disks.value = data.disks || [];
}

function choose(d) { target.value = d; stage.value = 'confirm'; }

async function start() {
  busy.value = true;
  const { ok, data } = await api.installStart(target.value.path);
  busy.value = false;
  if (!ok || data.success === false) { error.value = data.message || 'Could not start.'; stage.value = 'pick'; return; }
  stage.value = 'running';
  message.value = 'Preparing…';
  poll();
}

// The installation survives this page being closed — it runs on the device —
// so the poll only reflects it, never drives it.
async function poll() {
  const { ok, data } = await api.installStatus();
  if (ok && data) {
    if (data.message) message.value = data.message;
    if (typeof data.progress === 'number') progress.value = data.progress;
    if (data.state === 'done') { done.value = true; return; }
    if (data.state === 'error') { failed.value = true; return; }
  }
  timer = setTimeout(poll, 2000);
}

onMounted(load);
onBeforeUnmount(() => { if (timer) clearTimeout(timer); });
</script>
