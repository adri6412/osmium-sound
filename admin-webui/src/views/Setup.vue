<script setup>
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { api } from '../api.js';
import { useI18n } from '../i18n';
import LanguageSelector from '../components/LanguageSelector.vue';

const router = useRouter();
const { t } = useI18n();
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
  else error.value = data.message || t('setup.createFailed');
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
  <!-- Persistent language selector across every setup stage (mirrors the
       kiosk wizard's shared top-bar LanguageSelector, not just the first
       screen) — the language choice must stay available for the whole flow,
       not just at account creation. -->
  <div class="row" style="justify-content: flex-end; margin-bottom: 10px;">
    <LanguageSelector variant="compact" />
  </div>

  <div v-if="stage === 'account'" style="max-width: 420px; margin: 0 auto;">
    <div class="card">
      <h3><span class="dot"></span>{{ t('setup.accountTitle') }}</h3>
      <p class="sub">{{ t('setup.accountHint') }}</p>
      <label>{{ t('setup.username') }}</label>
      <input v-model="username" autocomplete="username" />
      <label>{{ t('setup.password') }}</label>
      <input v-model="password" type="password" autocomplete="new-password" />
      <div style="margin-top: 16px;">
        <button :disabled="busy" @click="createAccount" style="width: 100%;">{{ busy ? t('setup.creating') : t('setup.createAccount') }}</button>
      </div>
      <div v-if="error" class="msg err">{{ error }}</div>
    </div>
  </div>

  <div v-else-if="stage === 'configure'">
    <h2 class="page">{{ t('setup.configureTitle') }}</h2>
    <div class="card">
      <h3><span class="dot"></span>{{ t('setup.audioTitle') }}</h3>
      <p class="sub">{{ t('setup.audioHint') }}</p>
      <div v-for="d in devices" :key="d.id" class="net between" @click="pickDevice(d.id)">
        <span>{{ d.name || d.id }}</span>
        <span class="check" v-if="d.id === currentDevice">✓</span>
      </div>
      <p v-if="!devices.length" class="muted">{{ t('setup.noDevices') }}</p>
    </div>
    <div class="card">
      <h3><span class="dot"></span>{{ t('setup.musicTitle') }}</h3>
      <p class="item"><a :href="`http://${host}:9000`" target="_blank">{{ t('setup.openLyrion') }}</a></p>
      <p class="item"><a href="/sources-app" target="_blank">{{ t('setup.openSources') }}</a></p>
    </div>
    <button :disabled="busy" @click="finish">{{ busy ? t('setup.finishing') : t('setup.finishSetup') }}</button>
  </div>

  <div v-else-if="stage === 'done'" class="card" style="max-width: 420px; margin: 0 auto; text-align: center;">
    <h3>{{ t('setup.doneTitle') }}</h3>
    <button @click="router.push('/')">{{ t('setup.goDashboard') }}</button>
  </div>

  <div v-else class="center"><span class="muted">{{ t('setup.loading') }}</span></div>
</template>
