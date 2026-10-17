<script setup>
// One pane of the two-pane copy (ImportMusic.vue, advanced side): FROM / TO
// tag, up and the path, the folder's entries with a tick each when
// `selectable`, a footer line. Reads /api/system/local/list.
import { ref, computed, watch } from 'vue';
import { api } from '../api.js';
import { useI18n } from '../i18n';
import Icon from './Icon.vue';
import { placeFor, glyphOf, fmtSize, gb } from '../sources-model.js';

const props = defineProps({
  tag: String,
  start: String,
  top: { type: String, default: '' },
  places: { type: Array, default: () => [] },
  selectable: { type: Boolean, default: true },
  active: { type: Boolean, default: false },
  mark: { type: Array, default: () => [] },
  canChangePlace: { type: Boolean, default: false },
});
const emit = defineEmits(['activated']);
const { lang } = useI18n();
const lt = (it, en) => (lang.value === 'it' ? it : en);
const path = ref(''); const parent = ref(''); const entries = ref([]); const writable = ref(false); const sel = ref([]); const ram = ref(false);
async function load(p) {
  const r = await api.filesList(p || '');
  if (!r.ok || (r.data && r.data.success === false)) return;
  path.value = String(r.data.path || ''); parent.value = String(r.data.parent || '');
  writable.value = !!r.data.writable; ram.value = !!r.data.ram; entries.value = r.data.entries || []; sel.value = [];
}
const topOverride = ref('');
watch(() => props.start, (v) => { topOverride.value = ''; load(v); }, { immediate: true });
const rootTop = computed(() => topOverride.value || props.top || props.start);
function showPlace(root) { topOverride.value = root; load(root); emit('activated'); }
const pl = computed(() => placeFor(props.places, path.value));
const crumb = computed(() => {
  if (!pl.value) return path.value;
  const rest = path.value.slice(pl.value.root.length).split('/').filter(Boolean);
  return [pl.value.name, ...rest].join(' › ');
});
function isSel(e) { return sel.value.includes(e.path); }
function toggle(e) { const i = sel.value.indexOf(e.path); if (i >= 0) sel.value.splice(i, 1); else sel.value.push(e.path); emit('activated'); }
function open(e) { emit('activated'); if (e.dir) load(e.path); else if (props.selectable) toggle(e); }
const selBytes = computed(() => entries.value.filter(isSel).reduce((n, e) => n + (Number(e.size) || 0), 0));
defineExpose({ path, sel, writable, ram, reload: () => load(path.value) });
</script>

<template>
  <section class="pn" :class="{ active }" @click="emit('activated')">
    <div class="hd">
      <span class="tag">{{ tag }}</span>
      <button class="fm-ib sm" :disabled="path === rootTop || !parent" @click="emit('activated'); load(parent)"><Icon name="corner-left-up" :size="15" /></button>
      <div class="fm-path"><Icon :name="pl ? pl.glyph : 'folder'" :size="15" class="pg" /><span class="cr">{{ crumb }}</span></div>
      <span v-if="canChangePlace" class="plwrap" :title="lt('Mostra un altro posto', 'Show another place')">
        <Icon name="chevron-down" :size="15" />
        <select :value="pl ? pl.root : ''" @click.stop @change="showPlace($event.target.value)">
          <option v-for="p in places.filter((x) => x.ok && x.root)" :key="p.key" :value="p.root">{{ p.name }}</option>
        </select>
      </span>
    </div>
    <div class="cols"><span></span><span class="b">{{ lt('Nome', 'Name') }}</span><span class="r">{{ lt('Dimensione', 'Size') }}</span></div>
    <div class="list">
      <div v-for="e in entries" :key="e.path" class="row" :class="{ sel: selectable && isSel(e), there: mark.includes(e.name) }" @click="open(e)">
        <span><span v-if="selectable" class="fm-pick" :class="{ on: isSel(e) }" @click.stop="toggle(e)"><Icon name="check" :size="13" /></span></span>
        <span class="nmc"><Icon :name="glyphOf(e)" :size="16" :class="e.dir ? 'fd' : 'fl'" /><span class="nm">{{ e.name }}</span><span v-if="mark.includes(e.name)" class="pill">{{ lt("c'è già", 'already there') }}</span></span>
        <span class="r meta">{{ fmtSize(e) }}</span>
      </div>
      <p v-if="!entries.length" class="hint">{{ lt('Cartella vuota', 'Empty folder') }}</p>
    </div>
    <div class="ft" :class="{ gold: selectable && sel.length }">
      <template v-if="selectable && sel.length">{{ sel.length }} {{ lt('selezionati', 'selected') }}<template v-if="selBytes"> · {{ gb(selBytes) }}</template></template>
      <template v-else>{{ entries.length }} {{ lt('elementi', 'items') }}<template v-if="pl && pl.usage"> · {{ gb(pl.usage.free) }} {{ lt('liberi', 'free') }}</template></template>
    </div>
  </section>
</template>

<style scoped>
.pn { background: var(--bg); border: 1px solid var(--border); border-radius: 12px; padding: 10px; display: flex; flex-direction: column; min-width: 0; height: 380px; }
.pn.active { border-color: rgba(212,175,55,0.45); }
.hd { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.plwrap { position: relative; flex: 0 0 auto; width: 34px; height: 32px; display: inline-flex; align-items: center; justify-content: center; background: var(--panel); color: var(--silver); border: 1px solid rgba(212,175,55,0.3); border-radius: 8px; }
.plwrap select { position: absolute; inset: 0; opacity: 0; cursor: pointer; width: 100%; height: 100%; }
.pn:not(.active) .tag { background: var(--light); color: var(--silver); }
.tag { font-size: 10.5px; font-weight: 800; letter-spacing: 1.2px; color: #111; background: var(--gold); border-radius: 6px; padding: 3px 7px; }
.fm-ib.sm { width: 32px; height: 32px; padding: 0; }
.hd .fm-path { min-height: 32px; padding: 2px 8px; flex-wrap: nowrap; gap: 6px; font-size: 13px; color: var(--silver); }
.cr { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pg { color: var(--gold); flex: 0 0 auto; }
.cols, .row { display: grid; grid-template-columns: 24px minmax(0, 1fr) 76px; align-items: center; gap: 8px; padding: 0 8px; }
.cols { height: 28px; font-size: 12px; color: var(--muted); border-bottom: 1px solid var(--border); }
.cols .b { color: var(--text); font-weight: 600; }
.r { text-align: right; }
.list { flex: 1 1 auto; overflow: auto; margin-top: 4px; }
.row { height: 34px; border-radius: 7px; border: 1px solid transparent; font-size: 13px; cursor: pointer; }
.row:hover { background: var(--panel); }
.row.sel { background: var(--gold-dim); border-color: rgba(212,175,55,0.45); }
.row.there { background: rgba(250,204,21,0.07); border-color: rgba(250,204,21,0.35); }
.nmc { display: flex; align-items: center; gap: 8px; min-width: 0; }
.nm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fd { color: var(--gold); flex: 0 0 auto; }
.fl { color: var(--muted); flex: 0 0 auto; }
.meta { color: var(--muted); font-size: 12px; }
.pill { font-size: 10.5px; border-radius: 10px; padding: 1px 7px; color: #facc15; border: 1px solid rgba(250,204,21,0.4); flex: 0 0 auto; }
.hint { color: var(--muted); font-size: 13px; padding: 8px; margin: 0; }
.ft { margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border); font-size: 12px; color: var(--muted); }
.ft.gold { color: var(--gold); }
</style>
