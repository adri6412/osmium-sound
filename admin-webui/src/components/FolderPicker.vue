<script setup>
// Folder picker with the look of the File page (Files.vue): the places on
// the left, back / up / crumbs on top, a card per place on the first screen
// and a tile per folder after that, a new folder, and one button to take the
// folder you are in. Folders only: this is where "add a local folder",
// "share a local folder", "playlist folder" and the CD ripping destination
// all pick from. Same /api/local/list the File page reads, through
// webui_server's session-gated forwarder (api.js). Each instance keeps its
// own position, so opening one never moves another.
import { ref, computed, onMounted } from 'vue';
import { api } from '../api.js';
import { useI18n } from '../i18n';
import Icon from './Icon.vue';

const props = defineProps({
  startAt: { type: String, default: '' },
  pickLabel: { type: String, required: true },
  busy: { type: Boolean, default: false },
});
const emit = defineEmits(['pick', 'error']);
const { t } = useI18n();

const path = ref('');
const parent = ref('');
const entries = ref([]);
const places = ref([]);
const writable = ref(false);
const loading = ref(false);
const history = ref([]);
const naming = ref(false);
const newName = ref('');

async function load(next = '', remember = true) {
  loading.value = true;
  const r = await api.filesList(next || '');
  loading.value = false;
  if (!r.ok || (r.data && r.data.success === false)) {
    emit('error', (r.data && r.data.message) || t('common.error'));
    return;
  }
  if (remember && path.value !== (r.data.path || '')) history.value.push(path.value);
  path.value = r.data.path || '';
  parent.value = r.data.parent || '';
  const all = r.data.entries || [];
  // the first screen is the list of places, with their sizes; below it only
  // folders matter here
  entries.value = path.value ? all.filter((e) => e.dir) : all;
  writable.value = !!r.data.writable;
  naming.value = false;
  if (!path.value) places.value = all;
}
function goBack() {
  const prev = history.value.pop();
  if (prev !== undefined) load(prev, false);
}
const atRoot = computed(() => !path.value);
const crumbs = computed(() => {
  if (!path.value) return [];
  const place = places.value.find((p) => path.value === p.path || path.value.startsWith(p.path + '/'));
  const head = place ? [{ name: place.name, path: place.path }] : [];
  const rest = place ? path.value.slice(place.path.length) : path.value;
  let acc = place ? place.path : '';
  for (const part of rest.split('/').filter(Boolean)) {
    acc += '/' + part;
    head.push({ name: part, path: acc });
  }
  return head;
});
const activePlace = computed(() => {
  const p = places.value.find((x) => path.value === x.path || path.value.startsWith(x.path + '/'));
  return p ? p.path : '';
});

const KIND_GLYPH = { music: 'music', internal: 'hard-drive', network: 'network', usb: 'usb', playlists: 'list-music', home: 'home' };
function placeGlyph(p) { return KIND_GLYPH[p.kind] || 'folder'; }
function gb(n) {
  const v = Number(n) || 0;
  if (v >= 1024 ** 4) return `${(v / 1024 ** 4).toFixed(1)} TB`;
  if (v >= 10 * 1024 ** 3) return `${Math.round(v / 1024 ** 3)} GB`;
  if (v >= 1024 ** 3) return `${(v / 1024 ** 3).toFixed(1)} GB`;
  return `${Math.round(v / 1024 ** 2)} MB`;
}
const KIND_COUNT = { internal: 'files.disk', network: 'files.share', usb: 'files.usb', playlists: 'files.playlist' };
const KIND_EMPTY = { internal: 'files.noDisks', network: 'files.noShares', usb: 'files.noUsb', playlists: 'files.noPlaylists' };
function plural(key, count) { return count === 1 ? t(key + 'One', { count }) : t(key, { count }); }
function placeSub(p) {
  if (p.usage && p.usage.total) return t('files.freeOf', { free: gb(p.usage.free), total: gb(p.usage.total) });
  const n = Number(p.count) || 0;
  if (!n) return t(KIND_EMPTY[p.kind] || 'files.emptyFolder');
  const key = KIND_COUNT[p.kind];
  return key ? plural(key + 'Count', n) : plural('files.items', n);
}
function placeFull(p) {
  if (!p.usage || !p.usage.total) return 0;
  return Math.min(100, Math.round(100 * (p.usage.total - p.usage.free) / p.usage.total));
}

async function createFolder() {
  const name = newName.value.trim();
  if (!name || !path.value) return;
  loading.value = true;
  const r = await api.localMkdir(path.value, name);
  if (r.ok && r.data.success !== false) { newName.value = ''; await load(r.data.path || path.value, false); }
  else { loading.value = false; emit('error', (r.data && r.data.message) || t('common.error')); }
}

onMounted(() => load(props.startAt, false));
</script>

<template>
  <div class="card" style="margin: 8px 0;">
    <div class="fm">
      <nav class="fm-side">
        <div class="lbl">{{ t('files.places') }}</div>
        <button v-for="p in places" :key="p.path" class="fm-place" :class="{ on: activePlace === p.path }" @click="load(p.path)">
          <Icon :name="placeGlyph(p)" :size="17" />
          <span>{{ p.name }}</span>
        </button>
      </nav>

      <section>
        <div class="fm-bar">
          <button class="fm-ib" :disabled="!history.length" :title="t('common.back')" @click="goBack"><Icon name="chevron-left" :size="18" /></button>
          <button class="fm-ib" :disabled="atRoot" :title="t('files.up')" @click="load(parent)"><Icon name="corner-left-up" :size="18" /></button>
          <div class="fm-path">
            <button class="fm-crumb" :class="{ here: atRoot }" @click="load('')">{{ t('files.root') }}</button>
            <template v-for="(c, i) in crumbs" :key="c.path">
              <span class="sep">›</span>
              <button class="fm-crumb" :class="{ here: i === crumbs.length - 1 }" @click="i === crumbs.length - 1 ? null : load(c.path)">{{ c.name }}</button>
            </template>
          </div>
        </div>

        <div v-if="!atRoot" class="fm-tools">
          <button class="primary" :disabled="!writable || loading" @click="naming = !naming">
            <Icon name="folder-plus" :size="16" /><span class="t">{{ t('files.newFolder') }}</span>
          </button>
        </div>
        <div v-if="naming && !atRoot" class="row" style="margin-bottom: 12px;">
          <input v-model="newName" type="text" :placeholder="t('files.newFolderName')" @keyup.enter="createFolder" />
          <button class="fit" :disabled="!newName.trim() || loading" @click="createFolder">{{ t('files.create') }}</button>
        </div>
        <p v-if="!atRoot && !writable" class="sub" style="margin: 0 0 10px;">{{ t('files.readOnly') }}</p>

        <p v-if="loading" class="sub">{{ t('common.loading') }}</p>
        <div v-else-if="!entries.length" class="fm-empty">
          <Icon name="folder-open" :size="40" />
          <span>{{ t('files.empty') }}</span>
        </div>
        <div v-else-if="atRoot" class="fm-drives">
          <div v-for="p in entries" :key="p.path" class="fm-drive" @click="load(p.path)">
            <Icon class="gl" :name="placeGlyph(p)" :size="26" />
            <span class="tx">
              <span class="nm">{{ p.name }}</span>
              <span class="st">{{ placeSub(p) }}</span>
              <span v-if="placeFull(p)" class="bar"><i :style="{ width: placeFull(p) + '%' }"></i></span>
            </span>
          </div>
        </div>
        <div v-else class="fm-grid">
          <div v-for="e in entries" :key="e.path" class="fm-tile" @click="load(e.path)">
            <Icon class="gl" name="folder" :size="34" />
            <span class="nm">{{ e.name }}</span>
          </div>
        </div>

        <button style="margin-top: 12px;" :disabled="busy || loading || atRoot" @click="emit('pick', path)">{{ pickLabel }}</button>
      </section>
    </div>
  </div>
</template>
