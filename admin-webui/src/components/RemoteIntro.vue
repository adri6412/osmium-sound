<script setup>
// The key map of a remote the appliance knows out of the box (Fire TV,
// G20S PRO, Xiaomi), shown once per browser the first time one of them is
// among the connected remotes — which, from this page, means right after it
// has been paired. The same annotated pictures the kiosk shows
// (native-ui-qt/qml/RemoteIntro.qml), served from public/remotes/.
//
// Pass the device list as it comes from /api/system/remote (each device may
// carry `model`); `show(model)` opens it on demand (Settings → Remote).
// "Already shown" is a per-browser convenience in localStorage: the kiosk
// keeps its own, so pairing from here does not spare the person in front of
// the screen their introduction.
import { ref, watch, computed } from 'vue';
import { useI18n } from '../i18n';

const props = defineProps({ devices: { type: Array, default: () => [] } });
const { t, lang } = useI18n();

const MODELS = { firetv: 'Fire TV', g20s: 'G20S PRO', xiaomi: 'Xiaomi' };
const KEY = 'osmium.remoteIntroSeen';
const model = ref('');

function seen() {
  try { return (localStorage.getItem(KEY) || '').split(',').filter(Boolean); } catch (_) { return []; }
}
function markSeen(m) {
  const s = seen();
  if (s.includes(m)) return;
  s.push(m);
  try { localStorage.setItem(KEY, s.join(',')); } catch (_) {}
}

function check() {
  if (model.value) return;
  const s = seen();
  const d = (props.devices || []).find((x) => x && MODELS[x.model] && !s.includes(x.model));
  if (d) model.value = d.model;
}
watch(() => props.devices, check, { immediate: true, deep: true });

const picture = computed(() => (model.value
  ? `remotes/${model.value}-${lang.value === 'it' ? 'it' : 'en'}.jpg` : ''));

function close() {
  if (model.value) markSeen(model.value);
  model.value = '';
  check();                 // two new remotes paired together: the next one
}
function show(m) { if (MODELS[m]) model.value = m; }
defineExpose({ show });
</script>

<template>
  <div v-if="model" class="overlay" @click.self="close">
    <div class="card rmi">
      <h3>{{ t('settings.remote.intro.title', { name: MODELS[model] }) }}</h3>
      <p class="sub">{{ t('settings.remote.intro.body') }}</p>
      <div class="rmi-pic">
        <img :src="picture" :alt="MODELS[model]" />
      </div>
      <div class="rmi-bar">
        <p class="muted">{{ t('settings.remote.intro.later') }}</p>
        <button type="button" @click="close">{{ t('settings.remote.intro.gotIt') }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rmi {
  width: 760px; max-width: calc(100vw - 32px);
  max-height: calc(100vh - 32px); max-height: calc(100dvh - 32px);
  display: flex; flex-direction: column; margin: 0;
}
.rmi h3 { margin-bottom: 4px; }
.rmi-pic {
  flex: 1 1 auto; min-height: 0; overflow-y: auto;
  border-radius: 10px; background: #0a0a0a; margin: 10px 0 12px;
}
.rmi-pic img { display: block; width: 100%; height: auto; }
.rmi-bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.rmi-bar .muted { margin: 0; font-size: 12.5px; }
.rmi-bar button { flex: none; min-width: 120px; }
</style>
