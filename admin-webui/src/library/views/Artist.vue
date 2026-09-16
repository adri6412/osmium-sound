<script setup>
// One artist: which MusicBrainz artist the device thinks it is (and a way
// to pick another, or none), the name the pages show, the biography and the
// members listed on the kiosk's artist page, and the artist's albums here.
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue';
import { useRoute, onBeforeRouteLeave } from 'vue-router';
import { useI18n } from '../../i18n';
import Icon from '../../components/Icon.vue';
import Toggle from '../../components/Toggle.vue';
import Cover from '../components/Cover.vue';
import CandidatesDialog from '../components/CandidatesDialog.vue';
import { lib, errorText } from '../libraryApi.js';
import { fmtDate, artistTypeName, personKey, instrumentLabel } from '../meta.js';

const props = defineProps({ id: { type: String, required: true } });
const { t } = useI18n();
const route = useRoute();

const doc = ref(null);
const status = ref('');
const loadError = ref('');
const name = ref('');             // the override being edited ('' = the original)
const bioHidden = ref(false);
const hideMembers = ref([]);
const savedState = ref('');
const saving = ref(false);
const saveMsg = ref('');
const saveError = ref('');
const albums = ref([]);
const albumsLoaded = ref(false);
const choosing = ref(false);
const bioOpen = ref(false);
let tries = 0;
let timer = null;
let alive = true;

function stateKey() {
  return JSON.stringify({ name: name.value.trim(), bio: bioHidden.value, hide: [...hideMembers.value].sort() });
}
function applyOverrides(o) {
  const src = o || {};
  name.value = src.name || '';
  bioHidden.value = !!src.bio_hidden;
  hideMembers.value = Array.isArray(src.hide_members) ? src.hide_members.slice() : [];
  savedState.value = stateKey();
}
const dirty = computed(() => savedState.value !== '' && stateKey() !== savedState.value);

async function load(resetEdits = true) {
  clearTimeout(timer);
  const r = await lib.artistEdit(props.id);
  if (!alive) return;
  if (!r.ok || !r.data) { status.value = 'error'; loadError.value = errorText(r); return; }
  const d = r.data;
  status.value = String(d.status || 'error');
  loadError.value = d.status === 'error' ? d.message || '' : '';
  doc.value = d;
  if (resetEdits || !dirty.value) applyOverrides(d.overrides);
  if (d.status === 'pending' && tries++ < 45) timer = setTimeout(() => load(false), 2000);
}
async function loadAlbums() {
  const r = await lib.artistAlbums(props.id);
  if (!alive) return;
  albumsLoaded.value = true;
  if (r.ok && r.data) albums.value = r.data.albums || [];
}
onMounted(() => { load(); loadAlbums(); });
onBeforeUnmount(() => { alive = false; clearTimeout(timer); });
watch(() => props.id, () => { tries = 0; doc.value = null; albums.value = []; load(); loadAlbums(); });
onBeforeRouteLeave(() => !dirty.value || window.confirm(t('library.leaveUnsaved')));

const art = computed(() => (doc.value && doc.value.artist) || null);
const match = computed(() => (doc.value && doc.value.match) || null);
const bio = computed(() => (doc.value && doc.value.bio) || null);
// The name on the page: the library's, as the device reports it
// (`library_name`); while that is loading, the one the link passed along;
// for somebody the library does not know, MusicBrainz's.
const libraryName = computed(() => {
  if (doc.value && typeof doc.value.library_name === 'string' && doc.value.library_name) return doc.value.library_name;
  if (!doc.value && route.query.name) return String(route.query.name);
  return String((art.value && art.value.name) || route.query.name || '');
});
const shownName = computed(() => name.value.trim() || libraryName.value);
const life = computed(() => {
  const a = art.value;
  if (!a || (!a.begin && !a.end)) return '';
  return [a.begin ? fmtDate(a.begin) : '…', a.end ? fmtDate(a.end) : ''].filter((x, i) => x || i === 0).join(' – ');
});
const howText = computed(() => {
  const how = match.value && match.value.how;
  if (how === 'manual' || how === 'pin' || how === 'pinned') return t('library.credits.howManual');
  if (how === 'tag' || how === 'tags') return t('library.artist.howTag');
  if (how) return t('library.artist.howSearch');
  return '';
});
// Members once each (MusicBrainz lists a person again for a second spell).
const members = computed(() => {
  const seen = new Set();
  const out = [];
  for (const m of (art.value && art.value.members) || []) {
    const k = personKey(m);
    if (seen.has(k)) continue;
    seen.add(k);
    out.push({ ...m, k });
  }
  return out;
});
function memberShown(m) { return !hideMembers.value.includes(m.k); }
function setMember(m, shown) {
  hideMembers.value = shown ? hideMembers.value.filter((k) => k !== m.k) : [...hideMembers.value, m.k];
  saveMsg.value = '';
}
function memberLine(m) {
  const roles = (m.attrs || []).filter((a) => a !== 'original').map((a) => instrumentLabel(a).toLowerCase()).join(', ');
  const years = [m.begin ? String(m.begin).slice(0, 4) : '', m.end ? String(m.end).slice(0, 4) : ''].filter(Boolean).join('–');
  return [roles, years].filter(Boolean).join(' · ');
}

async function save() {
  saving.value = true;
  saveError.value = '';
  saveMsg.value = '';
  const overrides = { name: name.value.trim() || null, bio_hidden: bioHidden.value, hide_members: hideMembers.value.slice() };
  const r = await lib.artistEditSave(props.id, overrides);
  saving.value = false;
  if (!r.ok || (r.data && (r.data.success === false || r.data.status === 'error'))) { saveError.value = errorText(r); return; }
  savedState.value = stateKey();
  saveMsg.value = t('library.artist.saved');
  load(false);
}
function discard() {
  applyOverrides(doc.value && doc.value.overrides);
  saveMsg.value = '';
}
function onPinned() {
  choosing.value = false;
  tries = 0;
  status.value = 'pending';
  load(false);
}
</script>

<template>
  <RouterLink to="/?tab=artists" class="backlink"><Icon name="chevron-left" :size="16" />{{ t('library.artist.back') }}</RouterLink>
  <h2 class="page">{{ shownName || t('library.artist.untitled') }}</h2>
  <p class="muted lb-lead" v-if="name.trim() && libraryName && name.trim() !== libraryName">{{ t('library.artist.inLibraryAs', { name: libraryName }) }}</p>

  <div class="lb-banner" v-if="status === 'pending'"><Icon name="refresh-cw" :size="18" /><span>{{ t('library.artist.pending') }}</span></div>
  <div class="lb-banner" v-else-if="status === 'nomatch'"><Icon name="info" :size="18" /><span>{{ t('library.artist.nomatch') }}</span></div>
  <div class="lb-banner" v-else-if="status === 'offline'"><Icon name="alert-triangle" :size="18" /><span>{{ t('library.credits.status.offline') }}</span></div>
  <div class="lb-banner" v-else-if="status === 'disabled'"><Icon name="info" :size="18" /><span>{{ t('library.credits.status.disabled') }} <a href="./#/">{{ t('library.credits.status.openAdmin') }}</a></span></div>
  <div class="msg err" v-else-if="status === 'error'">{{ loadError || t('library.errors.generic') }}</div>
  <p class="lb-empty" v-else-if="!status">{{ t('common.loading') }}</p>

  <!-- MusicBrainz match -->
  <div class="card" v-if="status && status !== 'disabled' && status !== 'error'">
    <h3><span class="dot"></span>{{ t('library.artist.matchTitle') }}</h3>
    <template v-if="art">
      <div class="lb-release"><strong>{{ art.name }}</strong><span class="muted" v-if="art.disambiguation"> ({{ art.disambiguation }})</span></div>
      <div class="muted">{{ [artistTypeName(art.type), art.area, life].filter(Boolean).join(' · ') }}</div>
      <div class="muted lb-how" v-if="howText || (art.urls && art.urls.musicbrainz)">
        {{ howText }}<template v-if="art.urls && art.urls.musicbrainz"><template v-if="howText"> · </template><a :href="art.urls.musicbrainz" target="_blank" rel="noopener">musicbrainz.org <Icon name="external-link" :size="12" /></a></template>
      </div>
    </template>
    <p class="sub" v-else>{{ t('library.artist.noMatchYet') }}</p>
    <div class="lb-actions">
      <button type="button" class="secondary" @click="choosing = true"><Icon name="users" :size="15" /> {{ t('library.artist.chooseOther') }}</button>
    </div>
  </div>

  <!-- how the pages show it -->
  <div class="card" v-if="status && status !== 'disabled' && status !== 'error'">
    <h3><span class="dot"></span>{{ t('library.artist.pageTitle') }}</h3>
    <label for="ar-name">{{ t('library.artist.displayName') }}</label>
    <div class="row lb-name-row">
      <input id="ar-name" v-model="name" :placeholder="libraryName || (art && art.name) || ''" @input="saveMsg = ''" />
      <button v-if="name" type="button" class="ghost fit" @click="name = ''">{{ t('library.artist.useOriginal') }}</button>
    </div>
    <p class="muted lb-note">{{ t('library.artist.displayNameHelp') }}</p>

    <div class="between item" v-if="bio && bio.text">
      <span>{{ t('library.artist.showBio') }}</span>
      <Toggle :model-value="!bioHidden" @update:model-value="(v) => { bioHidden = !v; saveMsg = ''; }" />
    </div>
    <div v-if="bio && bio.text">
      <div class="lb-about" :class="{ open: bioOpen, off: bioHidden }">{{ bio.text }}</div>
      <div class="between lb-about-foot">
        <span class="muted">{{ t('library.credits.fromWikipedia', { license: bio.license || 'CC BY-SA' }) }}</span>
        <button type="button" class="lb-link" @click="bioOpen = !bioOpen">{{ bioOpen ? t('library.credits.less') : t('library.credits.more') }}</button>
      </div>
    </div>

    <template v-if="members.length">
      <div class="lb-group-h lb-members-h">{{ t('library.artist.members') }}</div>
      <p class="muted lb-note">{{ t('library.artist.membersHelp') }}</p>
      <div class="between item" v-for="m in members" :key="m.k">
        <span class="lb-member" :class="{ off: !memberShown(m) }">
          <span>{{ m.name }}</span>
          <span class="muted">{{ memberLine(m) }}</span>
        </span>
        <Toggle :model-value="memberShown(m)" @update:model-value="(v) => setMember(m, v)" />
      </div>
    </template>
  </div>

  <div class="msg" v-if="saveMsg"><Icon name="check" :size="15" class="gold" /> {{ saveMsg }}</div>
  <div class="msg err" v-if="saveError">{{ saveError }}</div>

  <!-- albums -->
  <div class="card" v-if="albums.length || albumsLoaded">
    <h3><span class="dot"></span>{{ t('library.artist.albums') }}</h3>
    <div class="lb-grid small" v-if="albums.length">
      <RouterLink v-for="a in albums" :key="a.album_id" :to="'/album/' + a.album_id" class="lb-album">
        <Cover :track-id="a.artwork_track_id" />
        <span class="lb-album-t">{{ a.title }}</span>
        <span class="lb-album-a" v-if="a.year">{{ a.year }}</span>
      </RouterLink>
    </div>
    <p class="muted" v-else>{{ t('library.artist.noAlbums') }}</p>
  </div>

  <div class="lb-savebar" v-if="dirty">
    <span class="lb-savebar-t">{{ t('library.credits.unsaved') }}</span>
    <button type="button" class="ghost fit" :disabled="saving" @click="discard">{{ t('library.tags.discard') }}</button>
    <button type="button" class="fit" :disabled="saving" @click="save"><Icon name="save" :size="15" /> {{ t('library.artist.save') }}</button>
  </div>

  <CandidatesDialog v-if="choosing" kind="artist" :id="id" @close="choosing = false" @pinned="onPinned" />
</template>
