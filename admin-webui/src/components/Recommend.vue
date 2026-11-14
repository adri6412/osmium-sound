<script setup>
// Settings → Recommended: the web admin's copy of the kiosk section
// (native-ui-qt/qml/SettingsTab.qml secRecommend), on the same api_server
// endpoints (/recommend_settings, /recommendations, /recommendations/run)
// through webui_server's session-gated /api/system/…. Only the settings live
// here: the albums themselves are shown by the kiosk (Music → Recommended).
//
// The box is not a server and is off at night, so the owner picks when the
// job runs; a missed run is caught up at the next power-on.
import { ref, computed, onMounted, onBeforeUnmount } from 'vue';
import { api } from '../api.js';
import { useI18n } from '../i18n';
import Toggle from './Toggle.vue';

const emit = defineEmits(['say']);
const { t } = useI18n();

const conf = ref(null);      // /recommend_settings
const st = ref({});          // /recommendations, minus the albums
const busy = ref(false);
const key = ref('');
let poll = null;

const BRANDS = { qobuz: 'Qobuz', tidal: 'Tidal', spotty: 'Spotify', deezer: 'Deezer' };
const srcLabel = (k) => (k === 'library' ? t('settings.recommend.srcLibrary') : BRANDS[k] || k);
const sched = computed(() => (conf.value && conf.value.schedule) || { mode: 'manual', days: [], time: '18:00' });
const lastRun = computed(() => {
  const r = st.value.last_run;
  if (!r || !r.finished) return t('settings.recommend.never');
  const when = new Date(r.finished * 1000).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' });
  return r.outcome && r.outcome !== 'ok' ? when + ' · ' + t('settings.recommend.lastRunFailed') : when;
});

async function loadStatus() {
  const r = await api.recommendStatus();
  if (!r.ok || !r.data) return;
  st.value = { ...r.data, items: undefined };
  // while a computation runs, ask now and then whether it is over
  if (st.value.running && !poll) poll = setInterval(loadStatus, 10000);
  if (!st.value.running && poll) { clearInterval(poll); poll = null; }
}
async function load() {
  const r = await api.recommendSettings();
  if (r.ok && r.data) conf.value = r.data;
  else conf.value = { available: false };
  await loadStatus();
}
async function save(body) {
  busy.value = true;
  const r = await api.recommendSettingsSet(body);
  busy.value = false;
  const ok = r.ok && r.data && r.data.success !== false;
  if (!ok) emit('say', (r.data && r.data.message) || t('settings.recommend.saveFailed'), true);
  await load();
  return ok;
}
const setSchedule = (change) => save({ schedule: { ...sched.value, ...change } });
function toggleDay(d) {
  const days = sched.value.days.includes(d) ? sched.value.days.filter((x) => x !== d) : [...sched.value.days, d].sort();
  if (days.length) setSchedule({ days });      // "chosen days" with no day would never run
}
function toggleSource(k, on) {
  const cur = conf.value.sources || [];
  save({ sources: on ? [...new Set([...cur, k])] : cur.filter((x) => x !== k) });
}
async function saveKey() {
  const k = key.value.trim();
  if (!/^[0-9a-fA-F]{32}$/.test(k)) { emit('say', t('settings.recommend.lastfmInvalid'), true); return; }
  if (await save({ lastfm_key: k })) key.value = '';
}
async function runNow() {
  busy.value = true;
  const r = await api.recommendRun();
  busy.value = false;
  if (!(r.ok && r.data && r.data.success !== false)) emit('say', (r.data && r.data.message) || t('settings.recommend.runFailed'), true);
  await loadStatus();
}

onMounted(load);
onBeforeUnmount(() => { if (poll) clearInterval(poll); });
</script>

<template>
  <p class="sub">{{ t('settings.recommend.intro') }}</p>
  <p class="muted" v-if="!conf">{{ t('common.loading') }}</p>
  <p class="muted" v-else-if="conf.available === false">{{ t('settings.recommend.unavailable') }}</p>
  <template v-else>
    <div class="between item">
      <span>{{ t('settings.recommend.enable') }}</span>
      <Toggle :model-value="!!conf.enabled" :disabled="busy" @update:model-value="(v) => save({ enabled: v })" />
    </div>
    <template v-if="conf.enabled">
      <label>{{ t('settings.recommend.whenLabel') }}</label>
      <span class="seg">
        <button :disabled="busy" :class="{ active: sched.mode === 'daily' }" @click="setSchedule({ mode: 'daily' })">{{ t('settings.recommend.daily') }}</button>
        <button :disabled="busy" :class="{ active: sched.mode === 'days' }" @click="setSchedule({ mode: 'days' })">{{ t('settings.recommend.onDays') }}</button>
        <button :disabled="busy" :class="{ active: sched.mode === 'manual' }" @click="setSchedule({ mode: 'manual' })">{{ t('settings.recommend.manual') }}</button>
      </span>
      <div v-if="sched.mode === 'days'">
        <span class="seg">
          <button v-for="d in 7" :key="d" :disabled="busy" :class="{ active: sched.days.includes(d - 1) }" @click="toggleDay(d - 1)">{{ t(`settings.recommend.d${d - 1}`) }}</button>
        </span>
      </div>
      <div v-if="sched.mode !== 'manual'">
        <input type="time" class="rec-time" :value="sched.time" :disabled="busy"
               @change="$event.target.value && setSchedule({ time: $event.target.value })" />
      </div>
      <p class="muted">{{ sched.mode === 'manual' ? t('settings.recommend.manualHelp') : t('settings.recommend.whenHelp') }}</p>

      <label>{{ t('settings.recommend.sourcesLabel') }}</label>
      <div class="between item" v-for="k in conf.all_sources || []" :key="k">
        <span>{{ srcLabel(k) }}</span>
        <Toggle :model-value="(conf.sources || []).includes(k)" :disabled="busy" @update:model-value="(v) => toggleSource(k, v)" />
      </div>
      <p class="muted">{{ t('settings.recommend.sourcesHelp') }}</p>

      <template v-if="conf.lastfm !== 'off'">
        <label>{{ t('settings.recommend.lastfmLabel') }}</label>
        <p class="muted">{{ t(`settings.recommend.lastfm_${conf.lastfm}`) }}</p>
        <div class="row" style="gap: 8px; flex-wrap: wrap;">
          <input v-model="key" type="text" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false"
                 :placeholder="t('settings.recommend.lastfmPlaceholder')" style="flex: 1; min-width: 220px;" />
          <button class="fit" :disabled="busy || !key.trim()" @click="saveKey">{{ t('settings.recommend.lastfmSave') }}</button>
          <button v-if="conf.lastfm === 'own'" class="secondary fit" :disabled="busy" @click="save({ lastfm_key: '' })">{{ t('settings.recommend.lastfmRemove') }}</button>
        </div>
      </template>

      <div class="between item" style="margin-top: 14px;">
        <span>{{ t('settings.recommend.lastRun') }}</span>
        <span class="muted">{{ lastRun }}</span>
      </div>
      <p class="muted" v-if="st.state === 'few_plays'">{{ t('settings.recommend.fewPlays', { needed: st.needed, plays: st.plays, albums: st.needed_albums }) }}</p>
      <p class="muted" v-if="st.running">{{ t('settings.recommend.running') }}</p>
      <button v-else class="fit" :disabled="busy" @click="runNow">{{ t('settings.recommend.computeNow') }}</button>
      <p class="muted" style="margin-top: 12px;">{{ t('settings.recommend.credits') }}</p>
    </template>
  </template>
</template>

<style scoped>
.rec-time { width: auto; min-width: 120px; margin-bottom: 8px; }
</style>
