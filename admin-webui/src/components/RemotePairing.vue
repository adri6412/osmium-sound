<script setup>
// "Which remote do you have?" — the certified ones (Fire TV, G20S PRO,
// Xiaomi) get the way to put that very remote in pairing mode, and are then
// found and paired without picking anything out of a list: the scan is told
// the model and pairs the first one of it it sees (api_server
// bt_remotes_scan). Anything else emits `other`, and the page shows its
// ordinary scan and list. Same flow as the first-boot wizard in
// webui_server.py.
import { ref, onUnmounted } from 'vue';
import { api } from '../api.js';
import { useI18n } from '../i18n';

const emit = defineEmits(['paired', 'other']);
const { t } = useI18n();

const MODELS = [['firetv', 'Fire TV'], ['g20s', 'G20S PRO'], ['xiaomi', 'Xiaomi']];
const NAMES = Object.fromEntries(MODELS);
const model = ref('');
const status = ref('');
const done = ref(false);
const giveUp = ref(false);
let run = 0;                      // a new choice stops the rounds of the old one

async function choose(m) {
  const mine = ++run;
  model.value = m;
  done.value = false;
  giveUp.value = false;
  // ~2½ minutes of looking, in rounds of ten seconds
  for (let left = 12; left > 0; left--) {
    if (mine !== run) return;
    status.value = t('settings.remote.pair.looking', { name: NAMES[m] });
    const r = await api.sysPost('bt_remotes/scan', { seconds: 10, model: m });
    if (mine !== run) return;
    if (r.ok && r.data && r.data.paired) {
      status.value = t('settings.remote.pair.paired', { name: NAMES[m] });
      done.value = true;
      emit('paired', r.data.paired);
      return;
    }
    await new Promise((res) => setTimeout(res, r.ok ? 500 : 3000));
  }
  if (mine !== run) return;
  status.value = t('settings.remote.pair.notYet');
  giveUp.value = true;
}
function back() { run++; model.value = ''; status.value = ''; }
function other() { run++; model.value = ''; emit('other'); }
onUnmounted(() => { run++; });
defineExpose({ back });
</script>

<template>
  <div class="rp">
    <template v-if="!model">
      <p class="sub">{{ t('settings.remote.pair.which') }}</p>
      <div class="rp-models">
        <button v-for="[id, name] in MODELS" :key="id" class="secondary" @click="choose(id)">{{ name }}</button>
        <button class="ghost" @click="other">{{ t('settings.remote.pair.other') }}</button>
      </div>
    </template>
    <template v-else>
      <label>{{ NAMES[model] }}</label>
      <p class="rp-how">{{ t('settings.remote.pair.how.' + model) }}</p>
      <p class="sub">{{ t('settings.remote.pair.wait') }}</p>
      <p class="sub" :class="{ gold: done }">{{ status }}</p>
      <div class="rp-models">
        <button v-if="giveUp" class="secondary" @click="choose(model)">{{ t('settings.remote.pair.retry') }}</button>
        <button class="ghost" @click="back">{{ t('settings.remote.pair.change') }}</button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.rp-models { display: flex; flex-wrap: wrap; gap: 8px; margin: 6px 0 4px; }
.rp-models button { flex: 1 1 auto; min-width: 120px; }
.rp-how { font-size: 15px; line-height: 1.45; margin: 4px 0 6px; }
</style>
