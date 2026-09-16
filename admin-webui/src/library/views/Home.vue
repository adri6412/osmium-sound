<script setup>
// The Library's first screen: find an album or an artist to fix. A search
// box over both, albums as covers, artists as a list, a page at a time.
import { ref, computed, onMounted, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useI18n } from '../../i18n';
import Icon from '../../components/Icon.vue';
import Cover from '../components/Cover.vue';
import StatusBanner from '../components/StatusBanner.vue';
import { lib, errorText } from '../libraryApi.js';

const { t } = useI18n();
const route = useRoute();
const router = useRouter();

const PAGE_ALBUMS = 60;
const PAGE_ARTISTS = 100;

// The search and the tab live in the address (#/?q=…&tab=artists), so Back
// from an album returns to the same list instead of an empty box.
const q = ref(String(route.query.q || ''));
const tab = ref(route.query.tab === 'artists' ? 'artists' : 'albums');
const albums = ref([]);
const albumsTotal = ref(0);
const artists = ref([]);
const artistsTotal = ref(0);
const loading = ref(false);
const error = ref('');
let seq = 0;
let debounce = null;

async function load(more = false) {
  const mine = ++seq;
  loading.value = true;
  error.value = '';
  if (tab.value === 'albums') {
    const r = await lib.albums(q.value.trim(), more ? albums.value.length : 0, PAGE_ALBUMS);
    if (mine !== seq) return;
    if (!r.ok) error.value = errorText(r);
    else {
      const got = r.data.albums || [];
      albums.value = more ? albums.value.concat(got) : got;
      albumsTotal.value = Number(r.data.total || 0);
    }
  } else {
    const r = await lib.artists(q.value.trim(), more ? artists.value.length : 0, PAGE_ARTISTS);
    if (mine !== seq) return;
    if (!r.ok) error.value = errorText(r);
    else {
      const got = r.data.artists || [];
      artists.value = more ? artists.value.concat(got) : got;
      artistsTotal.value = Number(r.data.total || 0);
    }
  }
  loading.value = false;
}

function syncQuery() {
  const query = {};
  if (q.value.trim()) query.q = q.value.trim();
  if (tab.value === 'artists') query.tab = 'artists';
  router.replace({ query });
}

watch(q, () => {
  clearTimeout(debounce);
  debounce = setTimeout(() => { syncQuery(); load(); }, 350);
});
watch(tab, () => { syncQuery(); load(); });

const moreAlbums = computed(() => albums.value.length < albumsTotal.value);
const moreArtists = computed(() => artists.value.length < artistsTotal.value);

onMounted(() => load());
</script>

<template>
  <h2 class="page">{{ t('library.home.title') }}</h2>
  <p class="muted lb-lead">{{ t('library.home.lead') }}</p>

  <StatusBanner />

  <div class="lb-search">
    <Icon name="search" :size="18" />
    <input v-model="q" type="search" :placeholder="t('library.home.searchPlaceholder')" :aria-label="t('library.home.searchPlaceholder')" />
  </div>

  <div class="seg lb-tabs" role="tablist">
    <button type="button" role="tab" :class="{ active: tab === 'albums' }" :aria-selected="tab === 'albums'" @click="tab = 'albums'">
      {{ t('library.home.albums') }}<template v-if="tab === 'albums' && albumsTotal"> · {{ albumsTotal }}</template>
    </button>
    <button type="button" role="tab" :class="{ active: tab === 'artists' }" :aria-selected="tab === 'artists'" @click="tab = 'artists'">
      {{ t('library.home.artists') }}<template v-if="tab === 'artists' && artistsTotal"> · {{ artistsTotal }}</template>
    </button>
  </div>

  <div class="msg err" v-if="error">{{ error }}</div>

  <template v-if="tab === 'albums'">
    <div class="lb-grid" v-if="albums.length">
      <RouterLink v-for="a in albums" :key="a.album_id" :to="'/album/' + a.album_id" class="lb-album">
        <Cover :track-id="a.artwork_track_id" />
        <span class="lb-album-t">{{ a.title }}</span>
        <span class="lb-album-a">{{ a.artist }}<template v-if="a.year"> · {{ a.year }}</template></span>
      </RouterLink>
    </div>
    <p class="lb-empty" v-else-if="!loading && !error">{{ q.trim() ? t('library.home.noAlbumsFound') : t('library.home.noAlbums') }}</p>
    <div class="lb-more" v-if="moreAlbums">
      <button class="secondary" :disabled="loading" @click="load(true)">{{ t('library.home.loadMore') }}</button>
    </div>
  </template>

  <template v-else>
    <div class="card lb-list" v-if="artists.length">
      <RouterLink v-for="a in artists" :key="a.artist_id" :to="{ path: '/artist/' + a.artist_id, query: { name: a.name } }" class="lb-row">
        <Icon name="user" :size="18" class="gold" />
        <span class="lb-row-t">{{ a.name }}</span>
        <span class="muted" v-if="a.album_count">{{ a.album_count === 1 ? t('library.home.oneAlbum') : t('library.home.nAlbums', { n: a.album_count }) }}</span>
        <Icon name="chevron-right" :size="16" class="muted" />
      </RouterLink>
    </div>
    <p class="lb-empty" v-else-if="!loading && !error">{{ q.trim() ? t('library.home.noArtistsFound') : t('library.home.noArtists') }}</p>
    <div class="lb-more" v-if="moreArtists">
      <button class="secondary" :disabled="loading" @click="load(true)">{{ t('library.home.loadMore') }}</button>
    </div>
  </template>

  <p class="lb-empty" v-if="loading && !albums.length && !artists.length">{{ t('common.loading') }}</p>
</template>
