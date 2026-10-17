<script setup>
// The file manager of Music sources (web admin): two panes side by side, each
// showing a place (the menu next to its path shows another one). Clicking a
// pane makes it the active one: Copy and Move go FROM it TO the other (the
// arrow says which way), New folder / Rename / Delete act on it. "If it is
// already there" says what a copy does with a name the other pane already
// has. The operation runs on the appliance and its line stays at the bottom.
import { ref, computed, onBeforeUnmount } from 'vue';
import { api } from '../api.js';
import { useI18n } from '../i18n';
import Icon from './Icon.vue';
import PaneList from './PaneList.vue';
import { placeFor } from '../sources-model.js';

const props = defineProps({ places: { type: Array, default: () => [] }, start: { type: String, default: '' } });
const { lang } = useI18n();
const lt = (it, en) => (lang.value === 'it' ? it : en);

const act = ref(0);
const lp = ref(null); const rp = ref(null);
const from = computed(() => (act.value === 0 ? lp.value : rp.value));
const to = computed(() => (act.value === 0 ? rp.value : lp.value));
const exists = ref('skip');
const job = ref(null); const msg = ref(''); const bad = ref(false);
let timer = null;
onBeforeUnmount(() => clearInterval(timer));

const ok = computed(() => props.places.filter((p) => p.ok && p.root));
const leftPlace = computed(() => placeFor(ok.value, props.start) || ok.value[0] || null);
const leftStart = computed(() => props.start || (leftPlace.value ? leftPlace.value.root : ''));
const leftTop = computed(() => (leftPlace.value ? leftPlace.value.root : leftStart.value));
const rightStart = computed(() => { const o = ok.value.find((p) => !leftPlace.value || p.key !== leftPlace.value.key) || ok.value[0]; return o ? o.root : ''; });

function say(t, b = false) { msg.value = t; bad.value = b; }
function reloadBoth() { if (lp.value) lp.value.reload(); if (rp.value) rp.value.reload(); }
async function start(promise) {
  const r = await promise;
  if (!r.ok || !r.data || r.data.success === false || !r.data.job) { say((r.data && r.data.message) || lt('Non è riuscito', 'That did not work'), true); reloadBoth(); return; }
  job.value = { state: 'running', progress: 0 }; msg.value = '';
  clearInterval(timer);
  timer = setInterval(async () => {
    const j = await api.filesJob(r.data.job);
    if (!j.ok) { clearInterval(timer); job.value = null; return; }
    job.value = j.data;
    if (j.data.state === 'done' || j.data.state === 'error') {
      clearInterval(timer); job.value = null;
      say(j.data.state === 'error' ? (j.data.message || lt('Non è riuscito', 'That did not work'))
        : lt('Fatto', 'Done') + (j.data.skipped ? lt(` · saltati perché c'erano già: ${j.data.skipped}`, ` · skipped, already there: ${j.data.skipped}`) : ''), j.data.state === 'error');
      reloadBoth();
    }
  }, 700);
}
const canCopy = computed(() => from.value && to.value && from.value.sel.length > 0 && to.value.writable && !job.value);
function copyMove(op) {
  if (!canCopy.value) return;
  const paths = [...from.value.sel], dest = to.value.path;
  start(op === 'copy' ? api.filesCopy(paths, dest, exists.value) : api.filesMove(paths, dest, exists.value));
}
async function newFolder() {
  const f = from.value;
  if (!f || !f.path || !f.writable) return;
  const name = (window.prompt(lt('Nome della nuova cartella', 'Name of the new folder'), '') || '').trim();
  if (!name) return;
  const r = await api.filesMkdir(f.path, name);
  if (!r.ok || (r.data && r.data.success === false)) say((r.data && r.data.message) || lt('Non è riuscito', 'That did not work'), true);
  f.reload();
}
async function rename() {
  const f = from.value;
  if (!f || f.sel.length !== 1) return;
  const p = f.sel[0], old = p.split('/').pop();
  const name = (window.prompt(lt('Nuovo nome', 'New name'), old) || '').trim();
  if (!name || name === old) return;
  const r = await api.filesRename(p, name);
  if (!r.ok || (r.data && r.data.success === false)) say((r.data && r.data.message) || lt('Non è riuscito', 'That did not work'), true);
  f.reload();
}
function remove() {
  const f = from.value;
  if (!f || !f.sel.length) return;
  const n = f.sel.length, first = f.sel[0].split('/').pop();
  if (!window.confirm(n === 1 ? lt(`Eliminare «${first}»? Non si può annullare.`, `Delete «${first}»? This cannot be undone.`) : lt(`Eliminare ${n} elementi? Non si può annullare.`, `Delete ${n} items? This cannot be undone.`))) return;
  start(api.filesDelete([...f.sel]));
}
const markFor = (side) => { const other = side === 0 ? rp.value : lp.value; return act.value !== side && other ? other.sel.map((p) => p.split('/').pop()) : []; };
</script>

<template>
  <div class="cm">
    <div class="cm-top">
      <button :disabled="!from || !from.path || !from.writable || from.ram" @click="newFolder"><Icon name="folder-plus" :size="16" />{{ lt('Nuova cartella', 'New folder') }}</button>
      <button :disabled="!from || from.sel.length !== 1 || !from.writable" @click="rename"><Icon name="pencil" :size="16" />{{ lt('Rinomina', 'Rename') }}</button>
      <button class="danger" :disabled="!from || !from.sel.length || !from.writable" @click="remove"><Icon name="trash-2" :size="16" />{{ lt('Elimina', 'Delete') }}</button>
      <span class="sp"></span>
      <small>{{ lt("Se c'è già", 'If already there') }}</small>
      <div class="seg"><button v-for="o in [['skip', lt('Salta', 'Skip')], ['replace', lt('Sostituisci', 'Replace')], ['keep', lt('Tieni entrambi', 'Keep both')]]" :key="o[0]" :class="{ on: exists === o[0] }" @click="exists = o[0]">{{ o[1] }}</button></div>
    </div>
    <div class="cm-panes">
      <PaneList ref="lp" :tag="act === 0 ? lt('DA', 'FROM') : lt('A', 'TO')" :active="act === 0" :start="leftStart" :top="leftTop" :places="places" can-change-place :mark="markFor(0)" @activated="act = 0" />
      <div class="mid">
        <button class="go" :disabled="!canCopy" @click="copyMove('copy')"><Icon :name="act === 0 ? 'chevron-right' : 'chevron-left'" :size="20" />{{ lt('Copia', 'Copy') }}</button>
        <button class="ghost2" :disabled="!canCopy || !from.writable" @click="copyMove('move')"><Icon :name="act === 0 ? 'chevron-right' : 'chevron-left'" :size="20" />{{ lt('Sposta', 'Move') }}</button>
      </div>
      <PaneList ref="rp" :tag="act === 1 ? lt('DA', 'FROM') : lt('A', 'TO')" :active="act === 1" :start="rightStart" :places="places" can-change-place :mark="markFor(1)" @activated="act = 1" />
    </div>
    <div class="cm-status">
      <template v-if="job"><span class="gold">{{ lt('Sto lavorando… ', 'Working… ') }}{{ job.progress || 0 }}%</span><small>{{ job.current }}</small><div class="fm-prog"><i :style="{ width: (job.progress || 0) + '%' }"></i></div></template>
      <span v-else-if="msg" :class="bad ? 'bad' : 'gold'">{{ msg }}</span>
      <span v-else>{{ lt("Clicca un pannello per sceglierlo: Copia e Sposta vanno da lui all'altro.", 'Click a pane to pick it: Copy and Move go from it to the other one.') }}</span>
    </div>
  </div>
</template>

<style scoped>
.cm-top { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
.cm-top > button { display: inline-flex; align-items: center; gap: 6px; padding: 8px 12px; font-size: 13px; font-weight: 500; background: var(--panel); color: var(--text); border: 1px solid var(--border); border-radius: 9px; }
.cm-top > button :deep(.ic) { color: var(--silver); }
.cm-top > button:disabled { opacity: 0.4; }
.cm-top > button.danger, .cm-top > button.danger :deep(.ic) { color: #f0b4b4; }
.cm-top small { font-size: 10.5px; letter-spacing: 1.2px; text-transform: uppercase; color: var(--muted); font-weight: 700; }
.sp { flex: 1 1 auto; }
.seg { display: inline-flex; background: var(--bg); border: 1px solid var(--border); border-radius: 18px; padding: 3px; }
.seg button { background: transparent; border: 0; color: var(--silver); font-size: 13px; padding: 6px 14px; border-radius: 15px; }
.seg button.on { background: var(--gold); color: #111; font-weight: 700; }
.cm-panes { display: grid; grid-template-columns: 1fr 100px 1fr; gap: 10px; }
.cm-panes :deep(.pn) { height: 500px; }
.mid { display: flex; flex-direction: column; justify-content: center; gap: 10px; }
.mid button { display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 12px 6px; border-radius: 12px; font-size: 14px; }
.go { background: var(--gold); color: #111; border: 0; font-weight: 700; }
.ghost2 { background: var(--panel); color: var(--text); border: 1px solid var(--border); }
.mid button:disabled { opacity: 0.4; }
.cm-status { display: flex; align-items: center; gap: 12px; padding: 12px 4px 0; font-size: 12.5px; color: var(--muted); flex-wrap: wrap; }
.cm-status small { color: var(--muted); overflow-wrap: anywhere; }
.cm-status .fm-prog { flex: 1 1 160px; margin: 0; }
.gold { color: var(--gold); }
.bad { color: #f0b4b4; }
@media (max-width: 760px) { .cm-panes { grid-template-columns: 1fr; } .mid { flex-direction: row; } .mid button { flex: 1 1 0; } .cm-panes :deep(.pn) { height: 380px; } }
</style>
