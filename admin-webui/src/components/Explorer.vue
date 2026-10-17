<script setup>
// The explorer of Music sources (web admin): a command bar, back / up / the
// path and a search box, the places as a tree on the left (this appliance's
// disks, USB, network — with the folders down to the one open and the ones
// inside it), the details view on the right (name, modified, type, size) and
// a status bar. `picker`: the advanced side of the add-music wizard — no
// ticks, only "new folder"; the folder open is the one taken (emit 'path').
// Same /api/system/local/* the old File page used.
import { ref, computed, watch, onBeforeUnmount } from 'vue';
import { api } from '../api.js';
import { useI18n } from '../i18n';
import Icon from './Icon.vue';
import { placeFor, glyphOf, fmtSize, gb, under } from '../sources-model.js';

const props = defineProps({
  picker: { type: Boolean, default: false },
  startAt: { type: String, default: '' },
  places: { type: Array, default: () => [] },
});
const emit = defineEmits(['path', 'changed']);
const { lang } = useI18n();
const lt = (it, en) => (lang.value === 'it' ? it : en);

const path = ref('');
const parent = ref('');
const entries = ref([]);
const writable = ref(false);
const ram = ref(false);
const loading = ref(false);
const history = ref([]);
const sel = ref([]);
const clip = ref(null);
const msg = ref('');
const err = ref(false);
const job = ref(null);
const query = ref('');
const sortBy = ref('name');
const sortUp = ref(true);
let jobTimer = null;

function say(t, bad = false) { msg.value = t; err.value = bad; }
async function load(next, remember = true) {
  loading.value = true;
  const r = await api.filesList(next || '');
  loading.value = false;
  if (!r.ok || (r.data && r.data.success === false)) { say((r.data && r.data.message) || lt('Cartella non raggiungibile', 'Folder not reachable'), true); return; }
  const p = String(r.data.path || '');
  if (remember && path.value !== p) history.value.push(path.value);
  path.value = p; parent.value = String(r.data.parent || '');
  writable.value = !!r.data.writable; ram.value = !!r.data.ram;
  entries.value = r.data.entries || [];
  sel.value = []; query.value = ''; msg.value = '';
  emit('path', p);
}
function reload() { return load(path.value, false); }
function goBack() { const prev = history.value.pop(); if (prev !== undefined) load(prev, false); }
watch(() => props.startAt, (v) => { history.value = []; load(v || '', false); }, { immediate: true });

const shown = computed(() => {
  const q = query.value.trim().toLowerCase();
  const list = entries.value.filter((e) => !q || String(e.name).toLowerCase().includes(q));
  const k = sortBy.value, dir = sortUp.value ? 1 : -1;
  return list.slice().sort((a, b) => {
    if (a.dir !== b.dir) return a.dir ? -1 : 1;
    if (k === 'size') return dir * ((a.size || 0) - (b.size || 0));
    if (k === 'mtime') return dir * ((a.mtime || 0) - (b.mtime || 0));
    return dir * String(a.name).localeCompare(String(b.name), undefined, { sensitivity: 'base' });
  });
});
function sort(k) { if (sortBy.value === k) sortUp.value = !sortUp.value; else { sortBy.value = k; sortUp.value = true; } }
const here = computed(() => placeFor(props.places, path.value));
const crumbs = computed(() => {
  const pl = here.value;
  if (!path.value || !pl) return [];
  const out = [];
  if (pl.group === 'dev') out.push({ name: lt('Questo apparecchio', 'This appliance'), path: '' });
  out.push({ name: pl.name, path: pl.root });
  let acc = pl.root;
  for (const part of path.value.slice(pl.root.length).split('/').filter(Boolean)) { acc += '/' + part; out.push({ name: part, path: acc }); }
  return out;
});
const tree = computed(() => {
  const out = [];
  const groups = [['dev', lt('Questo apparecchio', 'This appliance'), 'speaker'], ['usb', 'USB', 'usb'], ['net', lt('Rete', 'Network'), 'network']];
  for (const [g, label, glyph] of groups) {
    const items = props.places.filter((p) => p.group === g && p.ok && p.root);
    if (!items.length) continue;
    out.push({ depth: 0, glyph, name: label, head: true, key: 'h' + g });
    for (const p of items) {
      const open = here.value && here.value.key === p.key;
      out.push({ depth: 1, glyph: p.glyph, name: p.name, path: p.root, open, cur: open && path.value === p.root, key: p.key });
      if (!open) continue;
      const rest = path.value.slice(p.root.length).split('/').filter(Boolean);
      let acc = p.root;
      rest.forEach((part, k) => { acc += '/' + part; out.push({ depth: 2 + k, glyph: 'folder', name: part, path: acc, open: true, cur: acc === path.value, key: acc }); });
      entries.value.filter((e) => e.dir).slice(0, 60).forEach((e) => out.push({ depth: 2 + rest.length, glyph: 'folder', name: e.name, path: e.path, key: e.path }));
    }
  }
  return out;
});
function typeOf(e) {
  if (e.dir) return lt('Cartella', 'Folder');
  const ext = String(e.name).split('.').pop().toUpperCase();
  const g = glyphOf(e);
  return g === 'music' ? lt('Audio ', 'Audio ') + ext : g === 'image' ? lt('Immagine ', 'Image ') + ext : g === 'list-music' ? lt('Playlist ', 'Playlist ') + ext : ext;
}
function fmtDate(e) {
  return e.mtime ? new Date(e.mtime * 1000).toLocaleString(lang.value === 'it' ? 'it-IT' : 'en-GB', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '';
}
function isSel(e) { return sel.value.includes(e.path); }
function toggle(e) { const i = sel.value.indexOf(e.path); if (i >= 0) sel.value.splice(i, 1); else sel.value.push(e.path); }
function activate(e, ev) {
  if (ev && (ev.ctrlKey || ev.metaKey) && !props.picker) { toggle(e); return; }
  if (e.dir) load(e.path); else if (!props.picker) toggle(e);
}
const allSel = computed(() => shown.value.length > 0 && shown.value.every((e) => isSel(e)));
function toggleAll() { sel.value = allSel.value ? [] : shown.value.map((e) => e.path); }
const selBytes = computed(() => entries.value.filter((e) => isSel(e)).reduce((n, e) => n + (Number(e.size) || 0), 0));

// ── operations ────────────────────────────────────────────────────────
function stopJob() { if (jobTimer) { clearInterval(jobTimer); jobTimer = null; } }
async function start(promise) {
  const r = await promise;
  if (!r.ok || (r.data && r.data.success === false)) { say((r.data && r.data.message) || lt('Non è riuscito', 'That did not work'), true); return; }
  if (!r.data.job) { reload(); return; }
  job.value = { state: 'running', progress: 0 };
  stopJob();
  jobTimer = setInterval(async () => {
    const j = await api.filesJob(r.data.job);
    if (!j.ok) { stopJob(); job.value = null; return; }
    job.value = j.data;
    if (j.data.state === 'done' || j.data.state === 'error') {
      stopJob(); job.value = null;
      say(j.data.state === 'error' ? (j.data.message || lt('Non è riuscito', 'That did not work')) : lt('Fatto', 'Done') + (j.data.skipped ? lt(` · saltati ${j.data.skipped}`, ` · skipped ${j.data.skipped}`) : ''), j.data.state === 'error');
      reload(); emit('changed');
    }
  }, 700);
}
onBeforeUnmount(stopJob);
async function newFolder() {
  const name = (window.prompt(lt('Nome della nuova cartella', 'Name of the new folder'), '') || '').trim();
  if (!name || !path.value) return;
  const r = await api.filesMkdir(path.value, name);
  if (!r.ok || (r.data && r.data.success === false)) { say((r.data && r.data.message) || lt('Non è riuscito', 'That did not work'), true); return; }
  await load(r.data && r.data.path ? String(r.data.path) : path.value, !!(r.data && r.data.path));
}
async function rename() {
  if (sel.value.length !== 1) return;
  const p = sel.value[0], old = p.split('/').pop();
  const name = (window.prompt(lt('Nuovo nome', 'New name'), old) || '').trim();
  if (!name || name === old) return;
  const r = await api.filesRename(p, name);
  if (!r.ok || (r.data && r.data.success === false)) say((r.data && r.data.message) || lt('Non è riuscito', 'That did not work'), true);
  reload(); emit('changed');
}
function copySel(op) {
  if (!sel.value.length) return;
  clip.value = { op, paths: [...sel.value] };
  say((op === 'copy' ? lt('Copiati: ', 'Copied: ') : lt('Tagliati: ', 'Cut: ')) + sel.value.length + lt(' · vai dove vuoi e premi Incolla', ' · go where you want and press Paste'));
}
function paste() {
  const c = clip.value;
  if (!c || !path.value) return;
  start(c.op === 'copy' ? api.filesCopy(c.paths, path.value) : api.filesMove(c.paths, path.value));
  clip.value = null;
}
function remove() {
  if (!sel.value.length) return;
  const n = sel.value.length;
  if (!window.confirm(n === 1 ? lt(`Eliminare «${sel.value[0].split('/').pop()}»? Non si può annullare.`, `Delete «${sel.value[0].split('/').pop()}»? This cannot be undone.`)
                              : lt(`Eliminare ${n} elementi? Non si può annullare.`, `Delete ${n} items? This cannot be undone.`))) return;
  start(api.filesDelete([...sel.value]));
}
defineExpose({ path, reload });
</script>

<template>
  <div class="xp" :class="{ picker }">
    <div class="xp-cmd">
      <button class="primary" :disabled="!path || !writable || ram" @click="newFolder"><Icon name="folder-plus" :size="16" />{{ lt('Nuova cartella', 'New folder') }}</button>
      <template v-if="!picker">
        <i class="div"></i>
        <button :disabled="!sel.length || !writable" @click="copySel('move')"><Icon name="scissors" :size="16" />{{ lt('Taglia', 'Cut') }}</button>
        <button :disabled="!sel.length" @click="copySel('copy')"><Icon name="copy" :size="16" />{{ lt('Copia', 'Copy') }}</button>
        <button :disabled="!clip || !path || !writable || ram" @click="paste"><Icon name="clipboard" :size="16" />{{ lt('Incolla', 'Paste') }}<template v-if="clip"> ({{ clip.paths.length }})</template></button>
        <button :disabled="sel.length !== 1 || !writable" @click="rename"><Icon name="pencil" :size="16" />{{ lt('Rinomina', 'Rename') }}</button>
        <button class="danger" :disabled="!sel.length || !writable" @click="remove"><Icon name="trash-2" :size="16" />{{ lt('Elimina', 'Delete') }}</button>
        <span class="sp"></span>
        <button :disabled="!shown.length" @click="toggleAll"><Icon name="check" :size="16" />{{ allSel ? lt('Deseleziona', 'Clear') : lt('Seleziona tutto', 'Select all') }}</button>
      </template>
    </div>

    <div class="xp-addr">
      <button class="fm-ib" :disabled="!history.length" @click="goBack"><Icon name="chevron-left" :size="18" /></button>
      <button class="fm-ib" :disabled="!path" @click="load(parent)"><Icon name="corner-left-up" :size="18" /></button>
      <button class="fm-ib" @click="reload"><Icon name="refresh-cw" :size="16" /></button>
      <div class="fm-path">
        <Icon :name="here ? (here.group === 'dev' ? 'speaker' : here.glyph) : 'folder'" :size="15" class="pg" />
        <button v-if="!crumbs.length" class="fm-crumb here">{{ lt('Tutti i posti', 'All places') }}</button>
        <template v-for="(c, i) in crumbs" :key="c.path + i">
          <span v-if="i" class="sep">›</span>
          <button class="fm-crumb" :class="{ here: i === crumbs.length - 1 }" :disabled="i === 0 && !c.path" @click="i === crumbs.length - 1 ? null : load(c.path)">{{ c.name }}</button>
        </template>
      </div>
      <label class="xp-search"><Icon name="search" :size="15" /><input v-model="query" :placeholder="lt('Cerca qui', 'Search here')" /></label>
    </div>

    <div class="xp-body">
      <nav class="xp-tree">
        <div v-for="n in tree" :key="n.key" class="tn" :class="{ on: n.cur, head: n.head }" :style="{ paddingLeft: 6 + Math.min(n.depth, 6) * 14 + 'px' }" @click="n.path && load(n.path)">
          <span class="tw"><Icon v-if="!n.head" :name="n.open ? 'chevron-down' : 'chevron-right'" :size="12" /></span>
          <Icon :name="n.glyph" :size="15" class="tg" />
          <span class="tl">{{ n.name }}</span>
        </div>
      </nav>
      <section class="xp-list">
        <div class="hd">
          <span class="c0"><span v-if="!picker" class="fm-pick" :class="{ on: allSel }" @click="toggleAll"><Icon name="check" :size="13" /></span></span>
          <span class="c1 s" :class="{ on: sortBy === 'name' }" @click="sort('name')">{{ lt('Nome', 'Name') }} <Icon v-if="sortBy === 'name'" :name="sortUp ? 'chevron-up' : 'chevron-down'" :size="12" /></span>
          <span class="c2 s" :class="{ on: sortBy === 'mtime' }" @click="sort('mtime')">{{ lt('Ultima modifica', 'Modified') }} <Icon v-if="sortBy === 'mtime'" :name="sortUp ? 'chevron-up' : 'chevron-down'" :size="12" /></span>
          <span class="c3">{{ lt('Tipo', 'Type') }}</span>
          <span class="c4 s" :class="{ on: sortBy === 'size' }" @click="sort('size')">{{ lt('Dimensione', 'Size') }} <Icon v-if="sortBy === 'size'" :name="sortUp ? 'chevron-up' : 'chevron-down'" :size="12" /></span>
        </div>
        <p v-if="!path" class="hint">{{ lt('Scegli un posto a sinistra.', 'Pick a place on the left.') }}</p>
        <p v-else-if="loading" class="hint">{{ lt('Carico…', 'Loading…') }}</p>
        <p v-else-if="!shown.length" class="hint">{{ query ? lt('Niente con questo nome qui.', 'Nothing by that name here.') : lt('Cartella vuota', 'Empty folder') }}</p>
        <template v-else>
          <div v-for="e in shown" :key="e.path" class="row" :class="{ sel: !picker && isSel(e), dim: picker && !e.dir }" @click="activate(e, $event)">
            <span class="c0"><span v-if="!picker" class="fm-pick" :class="{ on: isSel(e) }" @click.stop="toggle(e)"><Icon name="check" :size="13" /></span></span>
            <span class="c1"><Icon :name="glyphOf(e)" :size="17" :class="e.dir ? 'fd' : 'fl'" /><span class="nm">{{ e.name }}</span></span>
            <span class="c2">{{ fmtDate(e) }}</span>
            <span class="c3">{{ typeOf(e) }}</span>
            <span class="c4">{{ fmtSize(e) }}</span>
          </div>
        </template>
      </section>
    </div>

    <div v-if="!picker" class="xp-status">
      <span v-if="job" class="gold">{{ lt('Sto lavorando… ', 'Working… ') }}{{ job.progress || 0 }}% <span class="muted">{{ job.current }}</span></span>
      <span v-else-if="msg" :class="err ? 'bad' : 'gold'">{{ msg }}</span>
      <template v-else>
        <span>{{ entries.length }} {{ lt('elementi', 'items') }}<template v-if="path && !writable"> · {{ lt('sola lettura', 'read only') }}</template><template v-if="ram"> · {{ lt('nella memoria: sparisce al riavvio', 'in memory: gone at restart') }}</template></span>
        <span v-if="sel.length" class="gold">{{ sel.length }} {{ lt('selezionati', 'selected') }}<template v-if="selBytes"> · {{ gb(selBytes) }}</template></span>
      </template>
      <span class="sp"></span>
      <span v-if="here && here.usage && here.usage.total">{{ here.name }}: {{ gb(here.usage.free) }} {{ lt('liberi su', 'free of') }} {{ gb(here.usage.total) }}</span>
    </div>
  </div>
</template>

<style scoped>
.xp-cmd { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; padding: 2px 0 12px; border-bottom: 1px solid var(--border); }
.xp-cmd button { display: inline-flex; align-items: center; gap: 6px; padding: 7px 10px; font-size: 13px; font-weight: 500; background: transparent; color: var(--text); border: 1px solid transparent; border-radius: 8px; }
.xp-cmd button :deep(.ic) { color: var(--silver); }
.xp-cmd button:hover:not(:disabled) { background: var(--light); filter: none; }
.xp-cmd button:disabled { opacity: 0.4; }
.xp-cmd button.primary { background: var(--gold); color: #111; font-weight: 700; }
.xp-cmd button.primary :deep(.ic) { color: #111; }
.xp-cmd button.danger { color: #f0b4b4; }
.xp-cmd button.danger :deep(.ic) { color: #f0b4b4; }
.xp-cmd .div { width: 1px; height: 24px; background: var(--border); margin: 0 6px; }
.sp { flex: 1 1 auto; }
.xp-addr { display: flex; align-items: center; gap: 6px; padding: 12px 0; }
.xp-addr .fm-ib { width: 34px; height: 34px; }
.xp-addr .fm-path { min-height: 34px; padding: 3px 8px; }
.xp-addr .pg { color: var(--gold); margin-right: 4px; }
.xp-search { flex: 0 0 220px; display: flex; align-items: center; gap: 8px; background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 0 10px; height: 34px; color: var(--muted); }
.xp-search input { flex: 1 1 auto; background: transparent; border: 0; padding: 0; color: var(--text); font-size: 13px; outline: none; min-width: 0; }
.xp-body { display: grid; grid-template-columns: 260px 1fr; border: 1px solid var(--border); border-radius: 12px; overflow: hidden; height: 460px; }
.picker .xp-body { height: 330px; }
.xp-tree { background: var(--panel); border-right: 1px solid var(--border); padding: 8px 6px; overflow: auto; }
.tn { display: flex; align-items: center; gap: 6px; padding-top: 5px; padding-bottom: 5px; padding-right: 8px; border-radius: 7px; font-size: 13px; color: var(--silver); cursor: pointer; white-space: nowrap; }
.tn:hover { background: var(--light); }
.tn.on { background: var(--gold-dim); color: var(--gold); }
.tn.head { cursor: default; font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; margin-top: 6px; }
.tn.head:hover { background: transparent; }
.tn.head .tg { color: var(--muted); }
.tn .tw { width: 12px; display: inline-flex; color: var(--muted); }
.tn .tg { color: var(--gold); flex: 0 0 auto; }
.tn .tl { overflow: hidden; text-overflow: ellipsis; }
.xp-list { background: var(--bg); padding: 4px 6px; min-width: 0; overflow: auto; }
.hd, .row { display: grid; grid-template-columns: 30px minmax(0, 1fr) 140px 120px 84px; align-items: center; gap: 8px; padding: 0 8px; }
.hd { height: 34px; font-size: 12px; color: var(--muted); border-bottom: 1px solid var(--border); margin-bottom: 4px; position: sticky; top: 0; background: var(--bg); }
.hd .s { cursor: pointer; display: inline-flex; align-items: center; gap: 4px; }
.hd .s.on { color: var(--text); font-weight: 600; }
.picker .hd .c0, .picker .row .c0 { visibility: hidden; }
.row { height: 36px; font-size: 13px; border-radius: 7px; border: 1px solid transparent; color: var(--silver); cursor: pointer; }
.row:hover { background: var(--panel); }
.row.sel { background: var(--gold-dim); border-color: rgba(212, 175, 55, 0.4); }
.row.dim { opacity: 0.45; cursor: default; }
.row .c1 { display: flex; align-items: center; gap: 9px; color: var(--text); min-width: 0; }
.row .nm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row .fd { color: var(--gold); flex: 0 0 auto; }
.row .fl { color: var(--muted); flex: 0 0 auto; }
.c4 { text-align: right; justify-content: flex-end; }
.c2, .c3 { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hint { color: var(--muted); font-size: 13px; padding: 10px; margin: 0; }
.xp-status { display: flex; gap: 14px; padding: 10px 4px 0; font-size: 12px; color: var(--muted); flex-wrap: wrap; }
.gold { color: var(--gold); }
.bad { color: #f0b4b4; }
@media (max-width: 760px) {
  .xp-body { grid-template-columns: 1fr; height: auto; }
  .xp-tree { display: none; }
  .hd, .row { grid-template-columns: 30px minmax(0, 1fr) 70px; }
  .c2, .c3 { display: none; }
  .xp-search { flex: 1 1 120px; }
}
</style>
