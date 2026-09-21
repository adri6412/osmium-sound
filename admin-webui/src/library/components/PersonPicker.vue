<script setup>
// Find the person a credit should point at: an artist of this library, or a
// person MusicBrainz knows (GET /api/meta/search/people). MusicBrainz is
// asked through the device's queue, so its half may arrive a moment later.
import { ref, watch, onBeforeUnmount } from 'vue';
import { useI18n } from '../../i18n';
import Icon from '../../components/Icon.vue';
import { lib, errorText } from '../libraryApi.js';

const props = defineProps({
  initial: { type: String, default: '' },
  // offer "just this name, no link" (adding a credit); relinking needs a link
  allowPlain: Boolean,
});
const emit = defineEmits(['pick']);
const { t } = useI18n();

const q = ref(props.initial);
const library = ref([]);
const musicbrainz = ref([]);
const pending = ref(false);
const searching = ref(false);
const error = ref('');
let debounce = null;
let retry = null;
let seq = 0;
let tries = 0;

async function search() {
  clearTimeout(retry);
  const text = q.value.trim();
  const mine = ++seq;
  if (text.length < 2) {
    library.value = []; musicbrainz.value = []; pending.value = false; searching.value = false;
    return;
  }
  searching.value = true;
  const r = await lib.searchPeople(text);
  if (mine !== seq) return;
  searching.value = false;
  if (!r.ok || !r.data) { error.value = errorText(r); return; }
  error.value = '';
  library.value = r.data.library || [];
  musicbrainz.value = r.data.musicbrainz || [];
  pending.value = r.data.status === 'pending';
  if (pending.value && tries++ < 15) retry = setTimeout(search, 2000);
}
watch(q, () => {
  clearTimeout(debounce);
  tries = 0;
  debounce = setTimeout(search, 350);
}, { immediate: true });
onBeforeUnmount(() => { clearTimeout(debounce); clearTimeout(retry); });

function pickLibrary(a) {
  emit('pick', { name: a.name, artist_id: a.artist_id, mbid: null });
}
function pickMb(p) {
  emit('pick', { name: p.name, artist_id: null, mbid: p.mbid, disambiguation: p.disambiguation || '' });
}
function pickPlain() {
  emit('pick', { name: q.value.trim(), artist_id: null, mbid: null });
}
</script>

<template>
  <div class="lb-picker">
    <div class="lb-search small">
      <Icon name="search" :size="16" />
      <input v-model="q" type="search" :placeholder="t('library.people.searchPlaceholder')" :aria-label="t('library.people.searchPlaceholder')" />
    </div>
    <div class="msg err" v-if="error">{{ error }}</div>
    <div class="lb-picker-res" v-if="q.trim().length >= 2">
      <button v-if="allowPlain" type="button" class="lb-pick" @click="pickPlain">
        <Icon name="plus" :size="16" />
        <span class="lb-pick-tx"><span>{{ t('library.people.plain', { name: q.trim() }) }}</span>
          <span class="muted">{{ t('library.people.plainHint') }}</span></span>
      </button>
      <div class="lb-picker-h">{{ t('library.people.inLibrary') }}</div>
      <button v-for="a in library" :key="'l' + a.artist_id" type="button" class="lb-pick" @click="pickLibrary(a)">
        <Icon name="library" :size="16" />
        <span class="lb-pick-tx"><span>{{ a.name }}</span></span>
      </button>
      <p class="muted lb-picker-none" v-if="!library.length && !searching">{{ t('library.people.noneLibrary') }}</p>
      <div class="lb-picker-h">{{ t('library.people.onMusicBrainz') }}</div>
      <button v-for="p in musicbrainz" :key="'m' + p.mbid" type="button" class="lb-pick" @click="pickMb(p)">
        <Icon name="globe" :size="16" />
        <span class="lb-pick-tx"><span>{{ p.name }}</span>
          <span class="muted" v-if="p.disambiguation || p.type">{{ [p.disambiguation, p.type].filter(Boolean).join(' · ') }}</span></span>
      </button>
      <p class="muted lb-picker-none" v-if="pending">{{ t('library.people.waitingMb') }}</p>
      <p class="muted lb-picker-none" v-else-if="!musicbrainz.length && !searching">{{ t('library.people.noneMb') }}</p>
    </div>
    <p class="muted lb-picker-none" v-else>{{ t('library.people.typeMore') }}</p>
  </div>
</template>
