<script setup>
// Small file manager for the music folders.
//
// Sources could add a folder but never tidy what was inside one: the only way
// to rename an album or delete a stray copy was to mount the share from a PC.
// This is that, in the web admin — one pane, a breadcrumb, a selection and a
// clipboard, over the /api/system/local/* endpoints (sources_server.py, which
// confines every path to the same roots the folder pickers offer and refuses
// to touch a source's own mountpoint).
//
// Web admin only, on purpose: copy/cut/rename with no keyboard, on a screen
// across the room, is not a thing anybody wants to do from the sofa.
import { ref, computed, onMounted, onBeforeUnmount } from 'vue';
import { useRouter } from 'vue-router';
import { api } from '../api.js';
import { useI18n } from '../i18n';

const { t, lang } = useI18n();
const router = useRouter();

const path = ref('');
const parent = ref('');
const entries = ref([]);
const writable = ref(false);
const loading = ref(false);
const msg = ref('');
const err = ref(false);
const selected = ref([]);
const clipboard = ref(null);      // { op: 'copy' | 'move', paths: [] }
const job = ref(null);            // live copy/move/delete job
const newFolder = ref('');
const renaming = ref(null);       // entry being renamed
const renameTo = ref('');
let jobTimer = null;

function say(text, isErr = false) {
  msg.value = text;
  err.value = isErr;
}

async function load(next = path.value) {
  loading.value = true;
  const r = await api.filesList(next);
  loading.value = false;
  if (!r.ok || (r.data && r.data.success === false)) {
    say((r.data && r.data.message) || t('common.error'), true);
    return;
  }
  path.value = r.data.path || '';
  parent.value = r.data.parent || '';
  entries.value = r.data.entries || [];
  writable.value = !!r.data.writable;
  selected.value = [];
  renaming.value = null;
}

// The top level is a list of the roots themselves, so "up" from a root goes
// back to that list rather than nowhere.
const atRoot = computed(() => !path.value);
const crumbs = computed(() => {
  if (!path.value) return [];
  const parts = path.value.split('/').filter(Boolean);
  const out = [];
  let acc = '';
  for (const p of parts) {
    acc += '/' + p;
    out.push({ name: p, path: acc });
  }
  return out;
});

function toggle(entry) {
  const i = selected.value.indexOf(entry.path);
  if (i >= 0) selected.value.splice(i, 1);
  else selected.value.push(entry.path);
}
const allSelected = computed(() => entries.value.length > 0 && selected.value.length === entries.value.length);
function toggleAll() {
  selected.value = allSelected.value ? [] : entries.value.map((e) => e.path);
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
// takes far longer than a request may, so the work runs on the appliance and
// this polls it.
function watchJob(id) {
  stopJob();
  jobTimer = setInterval(async () => {
    const r = await api.filesJob(id);
    if (!r.ok) { stopJob(); return; }
    job.value = r.data;
    if (r.data.state === 'done' || r.data.state === 'error') {
      stopJob();
      if (r.data.state === 'error') say(r.data.message || t('files.opFailed'), true);
      else say(t('files.done'));
      job.value = null;
      load();
    }
  }, 700);
}
function stopJob() {
  if (jobTimer) { clearInterval(jobTimer); jobTimer = null; }
}

async function start(promise) {
  const r = await promise;
  if (!r.ok || (r.data && r.data.success === false)) {
    say((r.data && r.data.message) || t('common.error'), true);
    return;
  }
  if (r.data.job) { job.value = { state: 'running', progress: 0, current: '' }; watchJob(r.data.job); }
  else load();
}

function copySelection(op) {
  if (!selected.value.length) return;
  clipboard.value = { op, paths: [...selected.value] };
  say(t(op === 'copy' ? 'files.copiedReady' : 'files.cutReady', { count: selected.value.length }));
}
function paste() {
  const c = clipboard.value;
  if (!c || !path.value) return;
  start(c.op === 'copy' ? api.filesCopy(c.paths, path.value) : api.filesMove(c.paths, path.value));
  clipboard.value = null;
}
function removeSelection() {
  if (!selected.value.length) return;
  // No undo on the appliance and no wastebasket: the confirmation is the only
  // thing between a tap and somebody's music being gone.
  if (!window.confirm(t('files.confirmDelete', { count: selected.value.length }))) return;
  start(api.filesDelete([...selected.value]));
}
async function createFolder() {
  const name = newFolder.value.trim();
  if (!name || !path.value) return;
  const r = await api.filesMkdir(path.value, name);
  if (!r.ok || (r.data && r.data.success === false)) {
    say((r.data && r.data.message) || t('common.error'), true);
    return;
  }
  newFolder.value = '';
  load();
}
function startRename(entry) {
  renaming.value = entry;
  renameTo.value = entry.name;
}
async function commitRename() {
  const name = renameTo.value.trim();
  if (!renaming.value || !name || name === renaming.value.name) { renaming.value = null; return; }
  const r = await api.filesRename(renaming.value.path, name);
  if (!r.ok || (r.data && r.data.success === false)) {
    say((r.data && r.data.message) || t('common.error'), true);
    return;
  }
  renaming.value = null;
  load();
}

onMounted(() => load(''));
onBeforeUnmount(stopJob);
</script>

<template>
  <div class="card">
    <h3><span class="dot"></span>{{ t('files.title') }}</h3>
    <p class="sub">{{ t('files.hint') }}</p>

    <div class="between" style="margin-bottom: 10px;">
      <span class="muted mono" style="word-break: break-all;">
        <a href="#" @click.prevent="load('')">{{ t('files.root') }}</a>
        <template v-for="c in crumbs" :key="c.path">
          / <a href="#" @click.prevent="load(c.path)">{{ c.name }}</a>
        </template>
      </span>
      <button class="ghost fit" :disabled="atRoot" @click="load(parent)">{{ t('files.up') }}</button>
    </div>

    <div v-if="msg" class="msg" :class="{ err }">{{ msg }}</div>
    <div v-if="job" class="msg">
      {{ t('files.working') }} — {{ job.progress || 0 }}% <span class="muted">{{ job.current }}</span>
    </div>
    <p v-if="!atRoot && !writable" class="sub">{{ t('files.readOnly') }}</p>

    <!-- toolbar: only what the current selection can actually do -->
    <div v-if="!atRoot" class="row" style="flex-wrap: wrap; margin-bottom: 10px;">
      <button class="ghost fit" :disabled="!selected.length" @click="copySelection('copy')">{{ t('files.copy') }}</button>
      <button class="ghost fit" :disabled="!selected.length || !writable" @click="copySelection('move')">{{ t('files.cut') }}</button>
      <button class="ghost fit" :disabled="!clipboard || !writable" @click="paste">
        {{ t('files.paste') }}<template v-if="clipboard"> ({{ clipboard.paths.length }})</template>
      </button>
      <button class="ghost fit" :disabled="selected.length !== 1 || !writable"
              @click="startRename(entries.find((e) => e.path === selected[0]))">{{ t('files.rename') }}</button>
      <button class="danger fit" :disabled="!selected.length || !writable" @click="removeSelection">{{ t('files.delete') }}</button>
    </div>

    <div v-if="!atRoot && writable" class="row" style="margin-bottom: 10px;">
      <input v-model="newFolder" type="text" :placeholder="t('files.newFolderName')" @keyup.enter="createFolder" />
      <button class="ghost fit" :disabled="!newFolder.trim()" @click="createFolder">{{ t('files.newFolder') }}</button>
    </div>

    <p v-if="loading" class="sub">{{ t('common.loading') }}</p>
    <p v-else-if="!entries.length" class="sub">{{ t('files.empty') }}</p>

    <div v-if="!atRoot && entries.length" class="item between">
      <label class="muted" style="cursor: pointer;">
        <input type="checkbox" :checked="allSelected" style="width: auto; margin-right: 8px;" @change="toggleAll" />
        {{ t('files.selected', { count: selected.length }) }}
      </label>
    </div>

    <div v-for="e in entries" :key="e.path" class="item between">
      <span style="display: flex; align-items: center; gap: 10px; min-width: 0;">
        <input v-if="!atRoot" type="checkbox" :checked="selected.includes(e.path)"
               style="width: auto; flex: 0 0 auto;" @change="toggle(e)" />
        <span class="gold" style="flex: 0 0 auto;">{{ e.dir ? '▸' : '·' }}</span>
        <template v-if="renaming && renaming.path === e.path">
          <input v-model="renameTo" type="text" @keyup.enter="commitRename" @keyup.esc="renaming = null" />
          <button class="fit" @click="commitRename">{{ t('common.save') }}</button>
        </template>
        <a v-else-if="e.dir" href="#" style="min-width: 0; word-break: break-all;" @click.prevent="load(e.path)">{{ e.name }}</a>
        <span v-else style="min-width: 0; word-break: break-all;">{{ e.name }}</span>
      </span>
      <span class="muted" style="flex: 0 0 auto; text-align: right;">
        {{ fmtSize(e) }}<template v-if="!e.dir && e.mtime"> · </template>{{ fmtDate(e) }}
      </span>
    </div>

    <button class="ghost" style="margin-top: 16px;" @click="router.push('/settings')">{{ t('common.back') }}</button>
  </div>
</template>
