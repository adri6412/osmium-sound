<script setup>
// "Which one is it?": the MusicBrainz releases that could be this album, or
// the MusicBrainz artists that could be this artist. Picking one pins it on
// the device; "Automatic" drops the pin, "None of these" says there is no
// match (no online information for it).
import { ref, onMounted, onBeforeUnmount } from 'vue';
import { useI18n } from '../../i18n';
import Icon from '../../components/Icon.vue';
import Modal from './Modal.vue';
import { lib, errorText } from '../libraryApi.js';
import { fmtDate, artistTypeName as typeName } from '../meta.js';

const props = defineProps({
  kind: { type: String, default: 'album' },    // 'album' | 'artist'
  id: { type: [String, Number], required: true },
});
const emit = defineEmits(['close', 'pinned']);
const { t } = useI18n();

const state = ref('loading');     // loading | ready | empty | error | offline | disabled
const cands = ref([]);
const current = ref('');
const pinned = ref(null);
const error = ref('');
const busy = ref(false);
let tries = 0;
let timer = null;

async function load() {
  const r = props.kind === 'artist' ? await lib.artistCandidates(props.id) : await lib.albumCandidates(props.id);
  if (!r.ok || !r.data) { state.value = 'error'; error.value = errorText(r); return; }
  const d = r.data;
  if (d.status === 'pending' && tries++ < 30) { timer = setTimeout(load, 2000); return; }
  if (d.status === 'offline' || d.status === 'disabled') { state.value = d.status; return; }
  if (d.status && d.status !== 'ok') { state.value = 'error'; error.value = d.message || ''; return; }
  cands.value = d.candidates || [];
  pinned.value = d.pinned ?? null;
  current.value = String(d.pinned && d.pinned !== 'none' ? d.pinned : d.current || '');
  state.value = cands.value.length ? 'ready' : 'empty';
}
onMounted(load);
onBeforeUnmount(() => clearTimeout(timer));

async function pin(mbid) {
  busy.value = true;
  error.value = '';
  const r = props.kind === 'artist' ? await lib.artistPin(props.id, mbid) : await lib.albumPin(props.id, mbid);
  busy.value = false;
  if (!r.ok || (r.data && r.data.status === 'error')) { error.value = errorText(r); return; }
  emit('pinned', mbid);
}

function albumLine(c) {
  return [fmtDate(c.date), c.country, c.labels, c.format,
    c.track_count ? t('library.credits.editionTracks', { n: c.track_count }) : ''].filter(Boolean).join(' · ');
}
function artistLine(c) {
  const life = c.begin || c.end ? [c.begin ? fmtDate(c.begin) : '…', c.end ? fmtDate(c.end) : ''].join(' – ').replace(/ – $/, '') : '';
  return [typeName(c.type), c.area, life].filter(Boolean).join(' · ');
}
</script>

<template>
  <Modal :title="kind === 'artist' ? t('library.artist.candidatesTitle') : t('library.credits.editionsTitle')" wide :locked="busy" @close="emit('close')">
    <p class="sub">{{ kind === 'artist' ? t('library.artist.candidatesHelp') : t('library.credits.editionsHelp') }}</p>
    <p class="lb-empty" v-if="state === 'loading'">{{ t('library.credits.editionsLoading') }}</p>
    <p class="lb-empty" v-else-if="state === 'empty'">{{ t('library.credits.editionsNone') }}</p>
    <p class="lb-empty" v-else-if="state === 'offline'">{{ t('library.credits.status.offline') }}</p>
    <p class="lb-empty" v-else-if="state === 'disabled'">{{ t('library.credits.status.disabled') }}</p>
    <div class="msg err" v-else-if="state === 'error'">{{ error || t('library.errors.generic') }}</div>
    <div class="lb-cands" v-if="state === 'ready'">
      <button v-for="c in cands" :key="c.mbid" type="button" class="lb-cand" :class="{ on: String(c.mbid) === current }" :disabled="busy" @click="pin(String(c.mbid))">
        <span class="lb-cand-t">
          <template v-if="kind === 'artist'">{{ c.name }}<span class="muted" v-if="c.disambiguation"> ({{ c.disambiguation }})</span></template>
          <template v-else>{{ c.title }}<span class="muted" v-if="c.artist"> — {{ c.artist }}</span></template>
        </span>
        <span class="muted lb-cand-s">{{ kind === 'artist' ? artistLine(c) : albumLine(c) }}</span>
        <span class="pill gold lb-cand-cur" v-if="String(c.mbid) === current">{{ pinned && pinned !== 'none' ? t('library.credits.chosenByHand') : t('library.credits.inUse') }}</span>
      </button>
    </div>
    <div class="msg err" v-if="error && state !== 'error'">{{ error }}</div>
    <template #foot>
      <button type="button" class="ghost fit" :disabled="busy" @click="pin(null)" :class="{ active: pinned === null }">
        <Icon name="sparkles" :size="15" /> {{ t('library.credits.auto') }}
      </button>
      <button type="button" class="ghost fit" :disabled="busy" @click="pin('none')" :class="{ active: pinned === 'none' }">
        <Icon name="x" :size="15" /> {{ t('library.credits.none') }}
      </button>
    </template>
  </Modal>
</template>
