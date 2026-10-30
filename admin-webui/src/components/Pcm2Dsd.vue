<script setup>
// Server-side conversion for one player — the built-in one (Settings → Audio),
// a zone (Settings → Audio zones), or an external Lyrion player. This device's
// Lyrion converts every PCM track on its way to the player; the user picks one
// of three modes: Off, PCM upsampling (×2 / ×4 / max, within the source's rate
// family), or DSD (64 / 128 / 256 + noise shaping). The two conversions are
// mutually exclusive (the backend enforces it: DSD wins). See api_server.py
// _pcm2dsd_info / hifi_squeezelite.{pcm2dsd,upsample}_state. The conversion runs
// on the Lyrion server this player follows (its Osmium Convert plugin), local or
// remote alike; `info.convert` says whether that server can convert and why not
// (noPlugin / noServerTools).
import { computed } from 'vue';
import { useI18n } from '../i18n';

const props = defineProps({
  mode: { type: String, default: 'off' },        // pcm2dsd: off | dsd64 | dsd128 | dsd256 | dsd512
  filter: { type: String, default: 'clans-8' },
  upsample: { type: String, default: 'off' },     // off | x2 | x4 | max
  state: { type: String, default: 'off' },        // DSD state: off | active | noTools | dsp | noDsd
  upsampleState: { type: String, default: 'off' },// off | active | noTools | dsp
  info: { type: Object, required: true },         // { modes, measured, filters, available, convert:{plugin,dsd,upsample,why}, convert_where, player_available, upsample:{ modes, available } }
  zone: { type: Boolean, default: false },
  external: { type: Boolean, default: false },    // an external Lyrion player: no CPU/volume messaging, user's responsibility
  where: { type: String, default: 'server' },     // built-in player only: server | player
  volume: { type: String, default: 'software' },
  busy: { type: Boolean, default: false },
});
const emit = defineEmits(['set']);
const { t } = useI18n();

// ── which of the three top modes is live ─────────────────────────────────
const top = computed(() => (props.mode !== 'off' ? 'dsd' : props.upsample !== 'off' ? 'pcm' : 'off'));
// where the conversion runs — the built-in player may run it on its own
// squeezelite instead of the followed Lyrion. Zones/externals are server-only,
// and the choice only matters once a conversion is on; player-side needs the
// converter daemon + Loopback on this box (info.player_available).
const showWhere = computed(() => !props.zone && !props.external && top.value !== 'off' && !!props.info.player_available);
function setWhere(w) {
  if (props.where !== w) emit('set', { convert_where: w });
}
// the following server's plugin gates the control: no plugin at all → nothing;
// plugin without sox_ng → PCM upsampling but no DSD
const caps = computed(() => props.info.convert || {});
const noPlugin = computed(() => caps.value.plugin === false);
const dsdOk = computed(() => !!props.info.available && caps.value.dsd !== false);
const pcmOk = computed(() => !!(props.info.upsample && props.info.upsample.available) && caps.value.upsample !== false);

// ── DSD sub-panel ─────────────────────────────────────────────────────────
const dsdLabel = (m) => (m === 'off' ? t('settings.audio.off') : m.toUpperCase());
// a DSD mode chosen earlier stays visible even if this CPU no longer offers it
const dsdModes = computed(() => {
  const list = (props.info.modes || ['off']).filter((m) => m !== 'off');
  if (props.mode !== 'off' && !list.includes(props.mode)) list.push(props.mode);
  return list;
});
// measured, and not even DSD64 fits: say so instead of offering the button
const tooSlow = computed(() => props.info.measured && (props.info.modes || []).length <= 1 && props.mode === 'off');
const dsdWhy = computed(() => (['off', 'active'].includes(props.state) ? '' : t('settings.pcm2dsd.why.' + props.state)));

// ── PCM upsampling sub-panel ────────────────────────────────────────────────
const pcmLabel = (m) => (m === 'max' ? t('settings.upsample.max') : '×' + m.slice(1));
const pcmModes = computed(() => (props.info.upsample.modes || ['off']).filter((m) => m !== 'off'));
const pcmWhy = computed(() => (['off', 'active'].includes(props.upsampleState) ? '' : t('settings.upsample.why.' + props.upsampleState)));

// ── switching the top mode (clears the other conversion; backend also does) ──
function toOff() {
  if (top.value !== 'off') emit('set', { pcm2dsd: 'off', upsample: 'off' });
}
function toPcm() {
  if (top.value === 'pcm') return;
  emit('set', { upsample: props.upsample !== 'off' ? props.upsample : 'x2', pcm2dsd: 'off' });
}
function toDsd() {
  if (top.value === 'dsd') return;
  if (!props.external && props.volume !== 'hardware' && !confirm(t('settings.pcm2dsd.volumeConfirm'))) return;
  emit('set', { pcm2dsd: props.mode !== 'off' ? props.mode : dsdModes.value[0], upsample: 'off' });
}
</script>

<template>
  <div class="pcm2dsd">
    <label>{{ t('settings.convert.label') }}</label>
    <p class="msg err" v-if="noPlugin">{{ t('settings.pcm2dsd.why.noPlugin') }}</p>
    <template v-else-if="dsdOk || pcmOk">
      <span class="seg">
        <button :disabled="busy" :class="{ active: top === 'off' }" @click="toOff">{{ t('settings.audio.off') }}</button>
        <button v-if="pcmOk" :disabled="busy" :class="{ active: top === 'pcm' }" @click="toPcm">{{ t('settings.convert.pcm') }}</button>
        <button v-if="dsdOk && !tooSlow" :disabled="busy" :class="{ active: top === 'dsd' }" @click="toDsd">{{ t('settings.convert.dsd') }}</button>
      </span>
      <p class="muted">{{ t('settings.convert.help') }}</p>

      <!-- built-in player: run the conversion on the followed Lyrion or here -->
      <template v-if="showWhere">
        <label>{{ t('settings.convert.whereLabel') }}</label>
        <span class="seg">
          <button :disabled="busy" :class="{ active: where === 'server' }" @click="setWhere('server')">{{ t('settings.convert.whereServer') }}</button>
          <button :disabled="busy" :class="{ active: where === 'player' }" @click="setWhere('player')">{{ t('settings.convert.wherePlayer') }}</button>
        </span>
        <p class="muted">{{ where === 'player' ? t('settings.convert.wherePlayerHelp') : t('settings.convert.whereServerHelp') }}</p>
      </template>

      <p class="muted" v-if="dsdOk && tooSlow && top !== 'dsd'">{{ t('settings.pcm2dsd.tooSlow') }}</p>
      <p class="muted" v-else-if="!dsdOk && caps.why === 'noServerTools' && top !== 'dsd'">{{ t('settings.pcm2dsd.why.noServerTools') }}</p>

      <!-- PCM upsampling -->
      <template v-if="top === 'pcm'">
        <label>{{ t('settings.upsample.label') }}</label>
        <span class="seg">
          <button v-for="m in pcmModes" :key="m" :disabled="busy" :class="{ active: upsample === m }" @click="emit('set', { upsample: m })">{{ pcmLabel(m) }}</button>
        </span>
        <p class="muted">{{ t('settings.upsample.help') }}</p>
        <p class="msg err" v-if="pcmWhy">{{ pcmWhy }}</p>
        <p class="muted" v-else-if="external && upsampleState === 'active'">{{ t('settings.convert.extPcm', { rate: pcmLabel(upsample) }) }}</p>
        <p class="muted" v-else-if="upsampleState === 'active'">{{ t('settings.upsample.active', { rate: pcmLabel(upsample) }) }}</p>
      </template>

      <!-- DSD -->
      <template v-else-if="top === 'dsd'">
        <label>{{ t('settings.audio.dsdLabel') }}</label>
        <span class="seg">
          <button v-for="m in dsdModes" :key="m" :disabled="busy" :class="{ active: mode === m }" @click="emit('set', { pcm2dsd: m })">{{ dsdLabel(m) }}</button>
        </span>
        <p class="muted">{{ t('settings.pcm2dsd.help') }}</p>
        <p class="msg err" v-if="dsdWhy">{{ dsdWhy }}</p>
        <p class="muted" v-else-if="external && state === 'active'">{{ t('settings.convert.extDsd', { rate: mode.toUpperCase() }) }}</p>
        <template v-else-if="state === 'active'">
          <p class="muted">{{ t('settings.pcm2dsd.active', { rate: mode.toUpperCase() }) }}</p>
          <p class="msg err" v-if="volume !== 'hardware'">{{ t('settings.pcm2dsd.volumeWarning') }}</p>
        </template>
        <p class="muted" v-if="!external && !info.measured">{{ t('settings.pcm2dsd.measuring') }}</p>
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
