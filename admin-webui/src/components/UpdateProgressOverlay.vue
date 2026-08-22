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
// 'interrupted' means "a step was left running with nobody currently resuming
// it" — which is also exactly what the plan looks like for the first stretch
// after a stage download is interrupted, before hifi-update-stage-resume.
// service has come up (it waits on network-online.target). Showing the error
// card (with its "Chiudi"
// button, which calls updates/dismiss and DELETES the on-disk plan) on the
// very first 'interrupted' read let an impatient close wipe out a plan the
// resume unit hadn't gotten to yet — the remaining steps (typically the UI)
// would then never apply. Require several consecutive 'interrupted' polls —
// long enough for the resume unit to have started if it's going to — before
// treating it as a real, dismissable failure.
let interruptedStreak = 0;
const MAX_INTERRUPTED_POLLS = 60; // ~2 minutes at 2s/poll

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
  // Expected throughout: the box reboots into the isolated apply session
  // (hifi-webui itself does not run there at all), then reboots back.
  if (!r.ok) return;
  const s = r.data || {};
  if (s.state === 'idle') { applying.active = false; interruptedStreak = 0; return; }
  if (s.state === 'interrupted') {
    interruptedStreak += 1;
    if (interruptedStreak < MAX_INTERRUPTED_POLLS) {
      // Still plausibly waiting on hifi-update-stage-resume.service — show it
      // as in-progress rather than failed, and don't offer the destructive close.
      applying.active = true;
      applying.kind = s.kind || '';
      applying.state = 'restarting';
      applying.progress = (typeof s.overall_progress === 'number') ? s.overall_progress : null;
      applying.message = t('settings.updates.progressState.restarting');
      applying.error = false;
      return;
    }
  } else {
    interruptedStreak = 0;
  }
  applying.active = true;
  applying.kind = s.kind || '';
  applying.state = s.state;
  applying.progress = (typeof s.overall_progress === 'number') ? s.overall_progress : null;
  applying.message = progressStateMessage(s.step_state || s.state, s.message || '');
  // 'apply_error' is the same terminal failure as 'error', just discovered
  // after the isolated apply session (rather than during staging).
  applying.error = s.state === 'error' || s.state === 'apply_error' || s.state === 'interrupted';
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
      <template v-if="applying.state !== 'done' && applying.state !== 'error' && applying.state !== 'apply_error' && applying.state !== 'interrupted'">
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
