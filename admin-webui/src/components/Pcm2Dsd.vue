<script setup>
// PCM conversion for one player — the built-in one (Settings → Audio), a zone
// (Settings → Audio zones), or an external Lyrion player. The user picks one of
// three modes: Off, PCM upsampling (×2 / ×4 / max, within the source's rate
// family), or DSD (64 / 128 / 256 + noise shaping). The two conversions are
// mutually exclusive (the backend enforces it: DSD wins). See api_server.py
// _pcm2dsd_info / hifi_squeezelite.{pcm2dsd,upsample}_state.
//
// A player of this box (built-in or zone) converts on its OWN player side —
// squeezelite soxr for PCM upsampling, the Loopback + hifi-pcm2dsd-player for
// PCM → DSD — so its controls are gated on this box's local tools, not on any
// server plugin, and `info.convert` is absent. Only an external player (on
// another Lyrion) still converts server-side through the Osmium Convert plugin;
// for it `info.convert` says whether that server can convert and why not
// (noPlugin / noServerTools), and the caps gating below applies.
import { computed } from 'vue';
import { useI18n } from '../i18n';

const props = defineProps({
  mode: { type: String, default: 'off' },        // pcm2dsd: off | dsd64 | dsd128 | dsd256 | dsd512
  filter: { type: String, default: 'clans-8' },
  upsample: { type: String, default: 'off' },     // off | x2 | x4 | max (the on/off flag)
  upsampleCap: { type: Number, default: 0 },       // box players: absolute target rate, 0 = Auto (DAC max)
  state: { type: String, default: 'off' },        // DSD state: off | active | noTools | dsp | noDsd
  upsampleState: { type: String, default: 'off' },// off | active | noTools | dsp
  info: { type: Object, required: true },         // { modes, measured, filters, available, player_available, upsample:{ modes, available }, [convert:{plugin,dsd,upsample,why}] (external only) }
  zone: { type: Boolean, default: false },
  external: { type: Boolean, default: false },    // an external Lyrion player: no CPU/volume messaging, user's responsibility
  volume: { type: String, default: 'software' },
  busy: { type: Boolean, default: false },
});
const emit = defineEmits(['set']);
const { t } = useI18n();

// ── which of the three top modes is live ─────────────────────────────────
const top = computed(() => (props.mode !== 'off' ? 'dsd' : props.upsample !== 'off' ? 'pcm' : 'off'));
// For an external player the following server's plugin gates the control: no
// plugin at all → nothing; plugin without sox_ng → PCM upsampling but no DSD.
// A box player (built-in or zone) sends no `info.convert`, so caps is empty and
// the gating falls through to this box's local tools (info.available).
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
// A box player (built-in or zone) upsamples on its own squeezelite, which has a
// single fixed output rate: the user picks an absolute target rate (caps), not a
// x2/x4 multiple. An external player converts server-side, per track, so it keeps
// the x2/x4/max modes.
const pcmLabel = (m) => (m === 'max' ? t('settings.upsample.max') : '×' + m.slice(1));
const capLabel = (r) => (r ? r / 1000 + ' kHz' : t('settings.upsample.auto'));
const pcmModes = computed(() => (props.info.upsample.modes || ['off']).filter((m) => m !== 'off'));
const pcmCaps = computed(() => props.info.upsample.caps || [0, 96000, 192000, 384000, 768000]);
const pcmActiveRate = computed(() => (props.external ? pcmLabel(props.upsample) : capLabel(props.upsampleCap)));
const pcmWhy = computed(() => (['off', 'active'].includes(props.upsampleState) ? '' : t('settings.upsample.why.' + props.upsampleState)));

// ── switching the top mode (clears the other conversion; backend also does) ──
function toOff() {
  if (top.value !== 'off') emit('set', { pcm2dsd: 'off', upsample: 'off' });
}
function toPcm() {
  if (top.value === 'pcm') return;
  if (props.external) {
    emit('set', { upsample: props.upsample !== 'off' ? props.upsample : 'x2', pcm2dsd: 'off' });
  } else {
    // box player: 'max' is just the on flag; the rate comes from upsample_cap.
    emit('set', { upsample: 'max', upsample_cap: props.upsampleCap || 0, pcm2dsd: 'off' });
  }
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

      <p class="muted" v-if="dsdOk && tooSlow && top !== 'dsd'">{{ t('settings.pcm2dsd.tooSlow') }}</p>
      <p class="muted" v-else-if="!dsdOk && caps.why === 'noServerTools' && top !== 'dsd'">{{ t('settings.pcm2dsd.why.noServerTools') }}</p>

      <!-- PCM upsampling -->
      <template v-if="top === 'pcm'">
        <label>{{ t('settings.upsample.label') }}</label>
        <span class="seg" v-if="external">
          <button v-for="m in pcmModes" :key="m" :disabled="busy" :class="{ active: upsample === m }" @click="emit('set', { upsample: m })">{{ pcmLabel(m) }}</button>
        </span>
        <span class="seg" v-else>
          <button v-for="r in pcmCaps" :key="r" :disabled="busy" :class="{ active: upsampleCap === r }" @click="emit('set', { upsample: 'max', upsample_cap: r })">{{ capLabel(r) }}</button>
        </span>
        <p class="muted">{{ t('settings.upsample.help') }}</p>
        <p class="msg err" v-if="pcmWhy">{{ pcmWhy }}</p>
        <p class="muted" v-else-if="external && upsampleState === 'active'">{{ t('settings.convert.extPcm', { rate: pcmActiveRate }) }}</p>
        <p class="muted" v-else-if="upsampleState === 'active'">{{ t('settings.upsample.active', { rate: pcmActiveRate }) }}</p>
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
