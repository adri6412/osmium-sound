<script setup>
import { reactive, ref, onMounted, onUnmounted } from 'vue';
import { useRoute } from 'vue-router';
import { api } from '../api.js';
import { useI18n } from '../i18n';

const { t } = useI18n();
const route = useRoute();

// Mirrors Settings.vue's own "forced blocking update modal" (applyAll /
// resumePlanIfRunning there), but mounted in App.vue so it survives whatever
// the running plan does to this page — the system step restarts hifi-api,
// which this SPA talks to through webui_server, and an OS step may reboot the
// appliance — and stays visible on every view, not only Settings. Settings.vue
// keeps its own copy for the "started here, watching it" case and announces
// when it's mounted via 'hifi-settings-active', so the two never show at once.
const applying = reactive({ active: false, kind: '', state: '', progress: null, message: '', error: false });
const settingsActive = ref(false);
let pollTimer = null;

const kindLabels = { ui: () => t('settings.updates.kindUi'), system: () => t('settings.updates.kindSystem'), os: () => t('settings.updates.kindOs') };

function onSettingsActive(e) { settingsActive.value = !!e.detail; }

function progressStateMessage(state, rawMessage) {
  if (state === 'error') return rawMessage || t('settings.updates.genericError');
  const known = ['starting', 'downloading', 'verifying', 'applying', 'restarting', 'done'];
  return known.includes(state) ? t(`settings.updates.progressState.${state}`) : rawMessage;
}

async function poll() {
  // Unauthenticated views (login/setup) have nothing to poll — a same-origin
  // fetch there would just 401 every 2s for no reason.
  if (route.path === '/login' || route.path === '/setup') { applying.active = false; return; }
  const r = await api.sys('updates/status');
  if (!r.ok) return; // expected mid-plan: hifi-api restarting, or a reboot
  const s = r.data || {};
  if (s.state === 'idle') { applying.active = false; return; }
  applying.active = true;
  applying.kind = s.kind || '';
  applying.state = s.state;
  applying.progress = (typeof s.overall_progress === 'number') ? s.overall_progress : null;
  applying.message = progressStateMessage(s.step_state || s.state, s.message || '');
  applying.error = s.state === 'error' || s.state === 'interrupted';
}

async function dismiss() {
  await api.sysPost('updates/dismiss', {});
  applying.active = false;
}

onMounted(() => {
  window.addEventListener('hifi-settings-active', onSettingsActive);
  poll();
  pollTimer = setInterval(poll, 2000);
});
onUnmounted(() => {
  window.removeEventListener('hifi-settings-active', onSettingsActive);
  clearInterval(pollTimer);
});
</script>

<template>
  <div v-if="applying.active && !settingsActive" class="overlay">
    <div class="card" style="width: 340px; text-align: center;">
      <template v-if="applying.state !== 'finished' && applying.state !== 'error' && applying.state !== 'interrupted'">
        <div class="spinner"></div>
        <h3 style="justify-content: center;">{{ t('settings.updates.updating', { label: applying.kind ? kindLabels[applying.kind]?.() : '' }) }}</h3>
        <p class="sub" style="margin-bottom: 6px;">
          {{ applying.message || t('common.loading') }}
          <template v-if="applying.progress !== null"> · {{ applying.progress }}%</template>
        </p>
        <p class="muted">{{ t('settings.updates.keepPowered') }}</p>
      </template>
      <template v-else>
        <h3 style="justify-content: center;">{{ applying.error ? t('settings.updates.interrupted') : t('settings.updates.completed') }}</h3>
        <p class="sub">{{ applying.message || (applying.error ? t('settings.updates.genericError') : '') }}</p>
        <button style="margin-top: 10px;" @click="dismiss">{{ t('common.close') }}</button>
      </template>
    </div>
  </div>
</template>
