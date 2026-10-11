<script setup>
// "Convert to DSD" for one player — the built-in one (Settings → Audio) or a
// zone (Settings → Audio zones). Lyrion converts every PCM track on its way
// to the player (api_server.py _pcm2dsd_info / hifi_squeezelite.pcm2dsd_state);
// this only shows the choice, why it may not apply, and the one thing that
// changes for the listener: digital volume no longer acts on the signal.
import { computed } from 'vue';
import { useI18n } from '../i18n';

const props = defineProps({
  mode: { type: String, default: 'off' },       // off | dsd64 | dsd128 | dsd256
  filter: { type: String, default: 'clans-8' },
  state: { type: String, default: 'off' },      // off | active | noTools | remoteServer | dsp | noDsd
  info: { type: Object, required: true },       // { modes, measured, filters, available }
  volume: { type: String, default: 'software' },
  busy: { type: Boolean, default: false },
});
const emit = defineEmits(['set']);
const { t } = useI18n();

const label = (m) => (m === 'off' ? t('settings.audio.off') : m.toUpperCase());
// a mode chosen earlier stays visible even if this CPU no longer offers it
const modes = computed(() => {
  const list = [...(props.info.modes || ['off'])];
  if (!list.includes(props.mode)) list.push(props.mode);
  return list;
});
const why = computed(() => (props.state === 'off' || props.state === 'active'
  ? '' : t('settings.pcm2dsd.why.' + props.state)));

function pick(m) {
  if (m === props.mode) return;
  if (props.mode === 'off' && m !== 'off' && props.volume !== 'hardware'
      && !confirm(t('settings.pcm2dsd.volumeConfirm'))) return;
  emit('set', { pcm2dsd: m });
}
</script>

<template>
  <div class="pcm2dsd">
    <label>{{ t('settings.pcm2dsd.label') }}</label>
    <template v-if="info.available">
      <span class="seg">
        <button v-for="m in modes" :key="m" :disabled="busy" :class="{ active: mode === m }" @click="pick(m)">{{ label(m) }}</button>
      </span>
      <p class="muted">{{ t('settings.pcm2dsd.help') }}</p>
      <p class="msg err" v-if="why">{{ why }}</p>
      <template v-else-if="state === 'active'">
        <p class="muted">{{ t('settings.pcm2dsd.active', { rate: mode.toUpperCase() }) }}</p>
        <p class="msg err" v-if="volume !== 'hardware'">{{ t('settings.pcm2dsd.volumeWarning') }}</p>
      </template>
      <p class="muted" v-if="!info.measured">{{ t('settings.pcm2dsd.measuring') }}</p>
      <template v-if="mode !== 'off'">
        <label>{{ t('settings.pcm2dsd.filterLabel') }}</label>
        <span class="seg">
          <button v-for="f in info.filters" :key="f" :disabled="busy" :class="{ active: filter === f }" @click="emit('set', { pcm2dsd_filter: f })">{{ t('settings.pcm2dsd.filter.' + f) }}</button>
        </span>
        <p class="muted">{{ t('settings.pcm2dsd.filterHelp') }}</p>
      </template>
    </template>
    <p class="muted" v-else>{{ t('settings.pcm2dsd.why.noTools') }}</p>
  </div>
</template>
