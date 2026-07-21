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
  else error.value = data.message || 'Creazione account fallita';
}

async function afterAuth() {
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
  <div class="card" v-if="stage === 'account'" style="max-width: 420px; margin: 40px auto;">
    <h3><span class="dot"></span>Crea l'account amministratore</h3>
    <p class="sub">Questo account controlla l'interfaccia web. Conservalo con cura:
      una password persa si recupera solo dallo schermo del dispositivo o con un
      ripristino di fabbrica.</p>
    <label>Nome utente (min 3 caratteri)</label>
    <input v-model="username" autocomplete="username" />
    <label>Password (min 8 caratteri)</label>
    <input v-model="password" type="password" autocomplete="new-password" />
    <div style="margin-top: 16px;">
      <button :disabled="busy" @click="createAccount" style="width: 100%;">{{ busy ? '…' : 'Crea account' }}</button>
    </div>
    <div v-if="error" class="msg err">{{ error }}</div>
  </div>

  <div v-else-if="stage === 'configure'">
    <h2 class="page">Completa la configurazione</h2>
    <div class="card">
      <h3><span class="dot"></span>Uscita audio</h3>
      <p class="sub">Scegli il DAC / dispositivo di riproduzione.</p>
      <div v-for="d in devices" :key="d.id" class="net between" @click="pickDevice(d.id)">
        <span>{{ d.name || d.id }}</span>
        <span class="check" v-if="d.id === currentDevice">✓</span>
      </div>
      <p v-if="!devices.length" class="muted">Nessun dispositivo audio rilevato.</p>
    </div>
    <div class="card">
      <h3><span class="dot"></span>Musica e sorgenti</h3>
      <p class="item"><a :href="`http://${host}:9000`" target="_blank">Apri Lyrion (libreria musicale) →</a></p>
      <p class="item"><a href="/sources-app" target="_blank">Aggiungi sorgenti musicali →</a></p>
    </div>
    <button :disabled="busy" @click="finish">{{ busy ? '…' : 'Completa il setup' }}</button>
  </div>

  <div v-else-if="stage === 'done'" class="card" style="max-width: 420px; margin: 40px auto; text-align: center;">
    <h3>Tutto pronto</h3>
    <button @click="router.push('/')">Vai alla dashboard</button>
  </div>

  <div v-else class="center"><span class="muted">Caricamento…</span></div>
</template>
