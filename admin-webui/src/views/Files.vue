<script setup>
// A graphical file manager for the music folders.
//
// Sources can add a folder but never tidy what is inside one: the only way to
// rename an album or delete a stray copy was to mount the share from a PC.
// This is that job, shaped like the file explorer everybody already knows —
// places on the left, a path bar across the top, folders as tiles you can
// see — in the same gold-on-near-black language as the rest of the admin.
//
// It runs over /api/system/local/* (sources_server.py), which confines every
// path to the same roots the folder pickers offer and refuses to touch a
// source's own mountpoint. Web admin only, on purpose: copy/cut/rename with
// no keyboard, on a screen across the room, is not a job anyone wants to do
// from the sofa.
import { ref, computed, onMounted, onBeforeUnmount } from 'vue';
import { useRouter } from 'vue-router';
import { api } from '../api.js';
import { useI18n } from '../i18n';
import Icon from '../components/Icon.vue';

const { t, lang } = useI18n();
const router = useRouter();

const path = ref('');
const parent = ref('');
const entries = ref([]);
const writable = ref(false);
const places = ref([]);          // the allowed roots, named by the appliance
const loading = ref(false);
const msg = ref('');
const err = ref(false);
const selected = ref([]);
const clipboard = ref(null);     // { op: 'copy' | 'move', paths: [] }
const job = ref(null);
const view = ref(readView());
const history = ref([]);         // for Back — where we came from, in order
const naming = ref(false);       // the "new folder" field is open
const newName = ref('');
const renaming = ref(null);      // entry being renamed
const renameTo = ref('');
let jobTimer = null;

const VIEW_KEY = 'osmiumFilesView';
function readView() {
  try { return localStorage.getItem(VIEW_KEY) === 'list' ? 'list' : 'grid'; } catch (_) { return 'grid'; }
}
function setView(v) {
  view.value = v;
  try { localStorage.setItem(VIEW_KEY, v); } catch (_) { /* private mode */ }
}

function say(text, isErr = false) { msg.value = text; err.value = isErr; }
// "Elimino 1 elementi?" is the sort of thing that makes an interface feel
// machine-written, and this one sits on a confirmation nobody can undo.
function plural(key, count, name) {
  return count === 1 ? t(key + 'One', { count, name }) : t(key, { count, name });
}
function firstName() {
  const e = entries.value.find((x) => x.path === selected.value[0]);
  return e ? e.name : '';
}

async function load(next = path.value, remember = true) {
  loading.value = true;
  const r = await api.filesList(next);
  loading.value = false;
  if (!r.ok || (r.data && r.data.success === false)) {
    say((r.data && r.data.message) || t('common.error'), true);
    return;
  }
  if (remember && path.value !== (r.data.path || '')) history.value.push(path.value);
  path.value = r.data.path || '';
  parent.value = r.data.parent || '';
  entries.value = r.data.entries || [];
  writable.value = !!r.data.writable;
  selected.value = [];
  renaming.value = null;
  naming.value = false;
  // The top level IS the list of roots, so one listing feeds both the rail
  // and the first screen; no second endpoint and no hardcoded path list.
  if (!path.value) places.value = r.data.entries || [];
}
function goBack() {
  const prev = history.value.pop();
  if (prev !== undefined) load(prev, false);
}
const atRoot = computed(() => !path.value);
const crumbs = computed(() => {
  if (!path.value) return [];
  // Name the crumb the appliance's own name for the root it sits under
  // ("Musica su questo apparecchio"), not the bare directory it happens to be.
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

// ── selection ─────────────────────────────────────────────────────────
function isSel(e) { return selected.value.includes(e.path); }
function toggle(e) {
  const i = selected.value.indexOf(e.path);
  if (i >= 0) selected.value.splice(i, 1);
  else selected.value.push(e.path);
}
// A plain click opens a folder — one tap, which is what a phone expects and
// what a novice tries first. Selecting is the checkbox (always drawn, since a
// touch screen has no hover), or ctrl/cmd-click for anyone used to a desktop.
function activate(e, ev) {
  if (ev && (ev.ctrlKey || ev.metaKey)) { toggle(e); return; }
  if (e.dir) load(e.path);
  else toggle(e);
}
const allSelected = computed(() => entries.value.length > 0 && selected.value.length === entries.value.length);
function toggleAll() { selected.value = allSelected.value ? [] : entries.value.map((e) => e.path); }

// ── looks ─────────────────────────────────────────────────────────────
const AUDIO = /\.(flac|mp3|wav|m4a|aac|ogg|opus|aiff?|dsf|dff|ape|wma|wv|mpc)$/i;
const IMAGE = /\.(jpe?g|png|webp|gif|bmp|tiff?)$/i;
const PLAYLIST = /\.(m3u8?|pls|xspf|cue)$/i;
function glyph(e) {
  if (e.dir) return 'folder';
  if (AUDIO.test(e.name)) return 'music';
  if (IMAGE.test(e.name)) return 'image';
  if (PLAYLIST.test(e.name)) return 'list-music';
  return 'file';
}
function placeGlyph(p) {
  const n = (p.path || '').toLowerCase();
  if (n.includes('hifi-sources')) return 'network';
  if (n.includes('hifi-usb')) return 'usb';
  if (n.includes('hifi-internal')) return 'hard-drive';
  if (n.includes('playlist')) return 'list-music';
  if (n.startsWith('/home')) return 'home';
  if (n.includes('music')) return 'music';
  return 'folder';
}
function fmtSize(e) {
  if (e.dir) return '';
  const n = Number(e.size) || 0;
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} kB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(1)} GB`;
}
function fmtDate(e) {
  if (!e.mtime) return '';
  return new Date(e.mtime * 1000).toLocaleDateString(lang.value === 'it' ? 'it-IT' : 'en-GB',
                                                     { year: 'numeric', month: 'short', day: 'numeric' });
}

// ── operations ────────────────────────────────────────────────────────
// Copy, move and delete come back as a job id: copying an album onto a NAS
// takes far longer than one request may, so the work runs on the appliance
// and this follows it.
function stopJob() { if (jobTimer) { clearInterval(jobTimer); jobTimer = null; } }
function watchJob(id) {
  stopJob();
  jobTimer = setInterval(async () => {
    const r = await api.filesJob(id);
    if (!r.ok) { stopJob(); job.value = null; return; }
    job.value = r.data;
    if (r.data.state === 'done' || r.data.state === 'error') {
      stopJob();
      say(r.data.state === 'error' ? (r.data.message || t('files.opFailed')) : t('files.done'),
          r.data.state === 'error');
      job.value = null;
      load(path.value, false);
    }
  }, 700);
}
async function start(promise) {
  const r = await promise;
  if (!r.ok || (r.data && r.data.success === false)) {
    say((r.data && r.data.message) || t('common.error'), true);
    return;
  }
  if (r.data.job) { job.value = { state: 'running', progress: 0, current: '' }; watchJob(r.data.job); }
  else load(path.value, false);
}
function copySelection(op) {
  if (!selected.value.length) return;
  const name = firstName();
  clipboard.value = { op, paths: [...selected.value] };
  say(plural(op === 'copy' ? 'files.copiedReady' : 'files.cutReady', selected.value.length, name));
}
function paste() {
  const c = clipboard.value;
  if (!c || !path.value) return;
  start(c.op === 'copy' ? api.filesCopy(c.paths, path.value) : api.filesMove(c.paths, path.value));
  clipboard.value = null;
}
function removeSelection() {
  if (!selected.value.length) return;
  // No wastebasket on the appliance and no undo: this confirmation is the
  // only thing between a tap and somebody's music being gone.
  if (!window.confirm(plural('files.confirmDelete', selected.value.length, firstName()))) return;
  start(api.filesDelete([...selected.value]));
}
async function createFolder() {
  const name = newName.value.trim();
  if (!name || !path.value) return;
  const r = await api.filesMkdir(path.value, name);
  if (!r.ok || (r.data && r.data.success === false)) {
    say((r.data && r.data.message) || t('common.error'), true);
    return;
  }
  newName.value = '';
  load(path.value, false);
}
function startRename() {
  const one = entries.value.find((e) => e.path === selected.value[0]);
  if (!one) return;
  renaming.value = one;
  renameTo.value = one.name;
}
async function commitRename() {
  const name = renameTo.value.trim();
  if (!renaming.value || !name || name === renaming.value.name) { renaming.value = null; return; }
  const r = await api.filesRename(renaming.value.path, name);
  if (!r.ok || (r.data && r.data.success === false)) {
    say((r.data && r.data.message) || t('common.error'), true);
    return;
  }
  load(path.value, false);
}

onMounted(() => load('', false));
onBeforeUnmount(stopJob);
</script>

<template>
  <a class="backlink" href="#" @click.prevent="router.push('/settings')">‹ {{ t('settings.backToSettings') }}</a>
  <h2 class="page">{{ t('files.title') }}</h2>

  <div class="card wide">
    <p class="sub">{{ t('files.hint') }}</p>

    <div class="fm">
      <!-- places -->
      <nav class="fm-side">
        <div class="lbl">{{ t('files.places') }}</div>
        <button
          v-for="p in places" :key="p.path"
          class="fm-place" :class="{ on: activePlace === p.path }"
          @click="load(p.path)"
        >
          <Icon :name="placeGlyph(p)" :size="17" />
          <span>{{ p.name }}</span>
        </button>
      </nav>

      <section>
        <!-- path bar -->
        <div class="fm-bar">
          <button class="fm-ib" :disabled="!history.length" :title="t('common.back')" @click="goBack">
            <Icon name="chevron-left" :size="18" />
          </button>
          <button class="fm-ib" :disabled="atRoot" :title="t('files.up')" @click="load(parent)">
            <Icon name="corner-left-up" :size="18" />
          </button>
          <div class="fm-path">
            <button class="fm-crumb" :class="{ here: atRoot }" @click="load('')">{{ t('files.root') }}</button>
            <template v-for="(c, i) in crumbs" :key="c.path">
              <span class="sep">›</span>
              <button
                class="fm-crumb" :class="{ here: i === crumbs.length - 1 }"
                @click="i === crumbs.length - 1 ? null : load(c.path)"
              >{{ c.name }}</button>
            </template>
          </div>
          <div class="fm-views">
            <button class="fm-ib" :class="{ on: view === 'grid' }" :title="t('files.viewGrid')" @click="setView('grid')">
              <Icon name="layout-grid" :size="17" />
            </button>
            <button class="fm-ib" :class="{ on: view === 'list' }" :title="t('files.viewList')" @click="setView('list')">
              <Icon name="list" :size="17" />
            </button>
          </div>
        </div>

        <!-- actions -->
        <div v-if="!atRoot" class="fm-tools">
          <button class="primary" :disabled="!writable" @click="naming = !naming">
            <Icon name="folder-plus" :size="16" /><span class="t">{{ t('files.newFolder') }}</span>
          </button>
          <button :disabled="selected.length !== 1 || !writable" @click="startRename">
            <Icon name="pencil" :size="16" /><span class="t">{{ t('files.rename') }}</span>
          </button>
          <button :disabled="!selected.length" @click="copySelection('copy')">
            <Icon name="copy" :size="16" /><span class="t">{{ t('files.copy') }}</span>
          </button>
          <button :disabled="!selected.length || !writable" @click="copySelection('move')">
            <Icon name="scissors" :size="16" /><span class="t">{{ t('files.cut') }}</span>
          </button>
          <button :disabled="!clipboard || !writable" @click="paste">
            <Icon name="clipboard" :size="16" />
            <span class="t">{{ t('files.paste') }}<template v-if="clipboard"> ({{ clipboard.paths.length }})</template></span>
          </button>
          <button class="danger" :disabled="!selected.length || !writable" @click="removeSelection">
            <Icon name="trash-2" :size="16" /><span class="t">{{ t('files.delete') }}</span>
          </button>
          <button :disabled="!entries.length" @click="toggleAll">
            <Icon name="check" :size="16" /><span class="t">{{ allSelected ? t('files.clearSel') : t('files.selectAll') }}</span>
          </button>
        </div>

        <div v-if="naming && !atRoot" class="row" style="margin-bottom: 12px;">
          <input v-model="newName" type="text" :placeholder="t('files.newFolderName')" @keyup.enter="createFolder" />
          <button class="fit" :disabled="!newName.trim()" @click="createFolder">{{ t('files.create') }}</button>
        </div>
        <div v-if="renaming" class="row" style="margin-bottom: 12px;">
          <input v-model="renameTo" type="text" @keyup.enter="commitRename" @keyup.esc="renaming = null" />
          <button class="fit" @click="commitRename">{{ t('common.save') }}</button>
          <button class="ghost fit" @click="renaming = null">{{ t('common.cancel') }}</button>
        </div>

        <div v-if="msg" class="msg" :class="{ err }">{{ msg }}</div>
        <div v-if="job" class="msg">
          {{ t('files.working') }} <span class="muted">{{ job.current }}</span>
          <div class="fm-prog"><i :style="{ width: (job.progress || 0) + '%' }"></i></div>
        </div>
        <p v-if="!atRoot && !writable" class="sub" style="margin: 0 0 10px;">{{ t('files.readOnly') }}</p>

        <p v-if="loading" class="sub">{{ t('common.loading') }}</p>
        <div v-else-if="!entries.length" class="fm-empty">
          <Icon name="folder-open" :size="40" />
          <span>{{ t('files.empty') }}</span>
        </div>

        <!-- tiles -->
        <div v-else-if="view === 'grid'" class="fm-grid">
          <div
            v-for="e in entries" :key="e.path"
            class="fm-tile" :class="{ sel: isSel(e) }"
            @click="activate(e, $event)"
          >
            <button
              v-if="!atRoot" class="fm-pick" :class="{ on: isSel(e) }"
              :aria-label="e.name" @click.stop="toggle(e)"
            ><Icon name="check" :size="13" /></button>
            <Icon class="gl" :class="{ file: !e.dir }" :name="glyph(e)" :size="34" />
            <span class="nm">{{ e.name }}</span>
          </div>
        </div>

        <!-- rows -->
        <div v-else class="fm-list">
          <div
            v-for="e in entries" :key="e.path"
            class="fm-row" :class="{ sel: isSel(e) }"
            @click="activate(e, $event)"
          >
            <button
              v-if="!atRoot" class="fm-pick" :class="{ on: isSel(e) }"
              :aria-label="e.name" @click.stop="toggle(e)"
            ><Icon name="check" :size="13" /></button>
            <Icon class="gl" :class="{ file: !e.dir }" :name="glyph(e)" :size="19" />
            <span class="nm">{{ e.name }}</span>
            <span class="meta">{{ fmtSize(e) }}</span>
            <span class="meta date">{{ fmtDate(e) }}</span>
          </div>
        </div>
        <div v-if="!atRoot && entries.length" class="fm-status">
          <span>{{ plural('files.items', entries.length) }}</span>
          <span v-if="selected.length" class="gold">{{ plural('files.selected', selected.length) }}</span>
        </div>
      </section>
    </div>
  </div>
</template>
