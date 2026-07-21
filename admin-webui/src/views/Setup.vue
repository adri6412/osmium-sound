<script setup>
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { api } from '../api.js';

const router = useRouter();
const stage = ref('loading');   // loading | account | configure | done
const provisioning = ref(false);
const error = ref('');
const busy = ref(false);

// account
const username = ref('');
const password = ref('');

// configure
const devices = ref([]);
const currentDevice = ref('default');
const host = ref(location.hostname);

onMounted(load);

async function load() {
  const { data } = await api.authStatus();
  provisioning.value = !!data.provisioning;
  if (data.logged_in) { await afterAuth(); return; }
  if (!data.has_account) { stage.value = 'account'; return; }
  router.push('/login');
}

async function createAccount() {
  busy.value = true; error.value = '';
  const { ok, data } = await api.setup(username.value, password.value);
  busy.value = false;
  if (ok && data.success) await afterAuth();
  else error.value = data.message || 'Could not create the account';
}

async function afterAuth() {
  // Pull DAC list so the user can pick an output during setup.
  const res = await api.sys('audio_devices');
  if (res.ok) {
    devices.value = res.data.devices || [];
    currentDevice.value = res.data.current || 'default';
  }
  stage.value = provisioning.value ? 'configure' : 'done';
}

async function pickDevice(id) {
  currentDevice.value = id;
  await api.sysPost('audio_device', { device: id });
}

async function finish() {
  busy.value = true;
  await api.provisionFinalize();
  busy.value = false;
  router.push('/');
}
</script>

<template>
  <div class="card" v-if="stage === 'account'">
    <h3>Create the admin account</h3>
    <p class="muted">This account controls the web interface. Keep it safe — the
      only way to recover a lost password is a factory reset.</p>
    <label>Username</label>
    <input v-model="username" autocomplete="username" />
    <label>Password (min 8 characters)</label>
    <input v-model="password" type="password" autocomplete="new-password" />
    <div style="margin-top: 14px;">
      <button :disabled="busy" @click="createAccount">{{ busy ? '…' : 'Create account' }}</button>
    </div>
    <div v-if="error" class="msg err">{{ error }}</div>
  </div>

  <div v-else-if="stage === 'configure'">
    <div class="card">
      <h3>Audio output</h3>
      <p class="muted">Choose the DAC / output device.</p>
      <div v-for="d in devices" :key="d.id" class="net" @click="pickDevice(d.id)">
        <span>{{ d.name || d.id }}</span>
        <span v-if="d.id === currentDevice"> ✓</span>
      </div>
      <p v-if="!devices.length" class="muted">No output devices reported.</p>
    </div>
    <div class="card">
      <h3>Music &amp; sources</h3>
      <p><a :href="`http://${host}:9000`" target="_blank">Open Lyrion (music library) →</a></p>
      <p><a :href="`http://${host}:8080`" target="_blank">Add music sources →</a></p>
    </div>
    <button :disabled="busy" @click="finish">{{ busy ? '…' : 'Finish setup' }}</button>
  </div>

  <div v-else-if="stage === 'done'" class="card">
    <h3>All set</h3>
    <button @click="router.push('/')">Go to dashboard</button>
  </div>

  <div v-else class="muted">Loading…</div>
</template>
