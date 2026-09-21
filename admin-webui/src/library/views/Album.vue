<script setup>
// One album, two jobs: the tags written inside its files, and the credits
// the device found online for its page on the kiosk. Two tabs, because they
// are saved in different places and one never changes the other.
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue';
import { useRoute, useRouter, onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router';
import { useI18n } from '../../i18n';
import Icon from '../../components/Icon.vue';
import Cover from '../components/Cover.vue';
import AlbumTags from '../components/AlbumTags.vue';
import AlbumCredits from '../components/AlbumCredits.vue';
import { lib, errorText } from '../libraryApi.js';
import { useLibraryStatus } from '../status.js';

const props = defineProps({ id: { type: String, required: true } });
const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const { status } = useLibraryStatus();

const data = ref(null);         // GET /api/library/album
const loadError = ref('');
const loading = ref(true);
// The tab lives in the address (?tab=credits), so Back and a reload keep it.
// A device that plays from another server has no files to edit: without an
// explicit choice it opens on the credits, which it can still correct.
const tab = computed(() => {
  if (route.query.tab === 'credits' || route.query.tab === 'tags') return route.query.tab;
  return status.value && status.value.local === false ? 'credits' : 'tags';
});
function setTab(v) {
  if (v !== tab.value) router.replace({ query: { ...route.query, tab: v } });
}
const dirty = ref({ tags: false, credits: false });

async function load() {
  loading.value = true;
  loadError.value = '';
  const r = await lib.album(props.id);
  loading.value = false;
  if (!r.ok || !r.data || !r.data.album) {
    data.value = null;
    loadError.value = errorText(r);
    return;
  }
  data.value = r.data;
}

const album = computed(() => (data.value && data.value.album) || null);

function setDirty(which, v) { dirty.value = { ...dirty.value, [which]: v }; }
const anyDirty = computed(() => dirty.value.tags || dirty.value.credits);

function onBeforeUnload(e) {
  if (!anyDirty.value) return;
  e.preventDefault();
  e.returnValue = '';
}
onMounted(() => { load(); window.addEventListener('beforeunload', onBeforeUnload); });
onBeforeUnmount(() => window.removeEventListener('beforeunload', onBeforeUnload));
const leaveOk = () => !anyDirty.value || window.confirm(t('library.leaveUnsaved'));
onBeforeRouteLeave(leaveOk);
onBeforeRouteUpdate((to, from) => (to.path === from.path ? true : leaveOk()));
watch(() => props.id, () => { dirty.value = { tags: false, credits: false }; load(); });
// after a rename the album has a new number: open that one (the tags were saved)
function onMoved(id) {
  dirty.value = { tags: false, credits: false };
  router.replace({ path: '/album/' + id, query: route.query });
}
</script>

<template>
  <RouterLink to="/" class="backlink"><Icon name="chevron-left" :size="16" />{{ t('library.album.back') }}</RouterLink>

  <div class="lb-head" v-if="album">
    <Cover :track-id="album.artwork_track_id" :size="300" class="lb-head-cover" />
    <div class="lb-head-tx">
      <h2 class="page">{{ album.title }}</h2>
      <div class="silver">
        <RouterLink v-if="album.artist_id" :to="{ path: '/artist/' + album.artist_id, query: { name: album.artist } }">{{ album.artist }}</RouterLink>
        <span v-else>{{ album.artist }}</span>
      </div>
      <div class="muted">
        <template v-if="album.year">{{ album.year }} · </template>
        {{ data.tracks.length === 1 ? t('library.album.oneTrack') : t('library.album.nTracks', { n: data.tracks.length }) }}
        <template v-if="album.disc_count > 1"> · {{ t('library.album.nDiscs', { n: album.disc_count }) }}</template>
      </div>
    </div>
  </div>
  <div class="msg err" v-else-if="loadError && !loading">{{ loadError }}</div>
  <p class="lb-empty" v-else-if="loading">{{ t('common.loading') }}</p>

  <div class="seg lb-tabs" role="tablist">
    <button type="button" role="tab" :class="{ active: tab === 'tags' }" :aria-selected="tab === 'tags'" @click="setTab('tags')">
      <Icon name="tag" :size="15" /> {{ t('library.album.tabTags') }}<span class="dot-new" v-if="dirty.tags"></span>
    </button>
    <button type="button" role="tab" :class="{ active: tab === 'credits' }" :aria-selected="tab === 'credits'" @click="setTab('credits')">
      <Icon name="globe" :size="15" /> {{ t('library.album.tabCredits') }}<span class="dot-new" v-if="dirty.credits"></span>
    </button>
  </div>

  <!-- v-show, not v-if: switching tab must not throw away unsaved edits -->
  <AlbumTags v-show="tab === 'tags'" v-if="data" :album-id="id" :data="data" @dirty="(v) => setDirty('tags', v)" @reload="load" @moved="onMoved" />
  <AlbumCredits v-show="tab === 'credits'" :album-id="id" :lib-tracks="data ? data.tracks : []" @dirty="(v) => setDirty('credits', v)" />
</template>
