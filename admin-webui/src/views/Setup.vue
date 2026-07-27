<script setup>
import { ref, onMounted, onUnmounted } from 'vue';
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

// Lyrion presence check + install fallback — mirrors the kiosk wizard's
// 'lyrion' step (SetupWizard.jsx checkLyrion/installLyrion). The installer
// purges Lyrion and the first-boot reinstall can fail if the network isn't up
// yet, so a headless setup (no screen to run the kiosk wizard's own check)
// needs this same fallback, or the box is left without a music server.
const lyrionState = ref('checking'); // 'checking' | 'missing' | 'installed'
const lyrionInstalling = ref(false);
const lyrionProgress = ref(0);
const lyrionMsg = ref('');
const lyrionError = ref('');
let lyrionPoll = null;

async function checkLyrion() {
  lyrionError.value = '';
  lyrionState.value = 'checking';
  const r = await api.sys('updates/lyrion/check');
  // `current` comes from local dpkg, so it's reliable even if the downloads
  // server is unreachable (data.error set, but current still tells us
  // whether Lyrion is installed). 'unknown' ⇒ not installed.
  const cur = r.ok ? r.data.current : null;
  lyrionState.value = (cur && cur !== 'unknown') ? 'installed' : 'missing';
}

async function installLyrion() {
  lyrionInstalling.value = true;
  lyrionError.value = '';
  lyrionProgress.value = 5;
  lyrionMsg.value = t('setup.lyrionInstalling');
  const r = await api.sysPost('updates/lyrion/apply', {});
  if (!(r.ok && r.data.started !== false)) {
    lyrionInstalling.value = false;
    lyrionError.value = (r.data && r.data.message) || t('setup.lyrionInstallFailed');
    return;
  }
  // The install runs as a detached systemd unit; poll its status file.
  lyrionPoll = setInterval(async () => {
    const s = await api.sys('updates/lyrion/status');
    const d = s.data || {};
    if (typeof d.progress === 'number') lyrionProgress.value = d.progress;
    if (d.message) lyrionMsg.value = d.message;
    if (d.state === 'done' || d.state === 'error') {
      clearInterval(lyrionPoll); lyrionPoll = null;
      lyrionInstalling.value = false;
      if (d.state === 'done') { lyrionProgress.value = 100; lyrionState.value = 'installed'; }
      else lyrionError.value = d.message || t('setup.lyrionInstallFailed');
    }
  }, 2000);
}

onUnmounted(() => { if (lyrionPoll) clearInterval(lyrionPoll); });

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
  if (stage.value === 'configure') checkLyrion();
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
      <h3><span class="dot"></span>{{ t('setup.lyrionTitle') }}</h3>
      <p v-if="lyrionState === 'checking'" class="sub">{{ t('setup.lyrionChecking') }}</p>
      <template v-else-if="lyrionState === 'missing'">
        <p class="sub">{{ t('setup.lyrionMissingHint') }}</p>
        <template v-if="!lyrionInstalling">
          <button @click="installLyrion">{{ t('setup.lyrionInstall') }}</button>
          <div v-if="lyrionError" class="msg err">{{ lyrionError }}</div>
        </template>
        <template v-else>
          <div style="width: 100%; height: 8px; background: var(--panel); border-radius: 99px; overflow: hidden; margin: 10px 0;">
            <div style="height: 100%; background: var(--gold); transition: width .4s;" :style="{ width: lyrionProgress + '%' }"></div>
          </div>
          <p class="muted">{{ lyrionMsg || t('setup.lyrionInstalling') }}</p>
        </template>
      </template>
      <p v-else class="sub">{{ t('setup.lyrionInstalled') }}</p>
      <p class="item" v-if="lyrionState === 'installed'"><a :href="`http://${host}:9000`" target="_blank">{{ t('setup.openLyrion') }}</a></p>
    </div>
    <div class="card">
      <h3><span class="dot"></span>{{ t('setup.musicTitle') }}</h3>
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
