<script setup>
// The tags inside the album's files. The album's own fields at the top
// (written to every track), the tracks below with their title, artist and
// composer, each opening onto all its tags. Nothing is written while typing:
// the Save bar collects what changed, a dialog says it back in plain words,
// and one background job writes the files (journaled, so History can undo it).
import { ref, reactive, computed, watch } from 'vue';
import { useI18n } from '../../i18n';
import Icon from '../../components/Icon.vue';
import Toggle from '../../components/Toggle.vue';
import Modal from './Modal.vue';
import ValuesEditor from './ValuesEditor.vue';
import { lib, errorText } from '../libraryApi.js';
import { useJob, isBusy, isChangedSince } from '../jobs.js';
import { EDITABLE_KEYS, EDITABLE, SINGLE_KEYS, NUMERIC_KEYS, tagLabel, fmtDuration, clone } from '../meta.js';

const props = defineProps({
  albumId: { type: String, required: true },
  data: { type: Object, required: true },     // GET /api/library/album
});
const emit = defineEmits(['dirty', 'reload', 'moved']);
const { t } = useI18n();

// ── working copy ─────────────────────────────────────────────────────
// `orig` is what the files hold, `work` what the page shows; the save sends
// the difference, so a field nobody touched is never written.
const orig = ref({});
const work = reactive({});
const open = reactive({});          // track_id -> the "all tags" panel is open
const addKey = reactive({});        // track_id -> key picked in "Add a tag"

function init() {
  const o = {};
  for (const k of Object.keys(work)) delete work[k];
  for (const tr of props.data.tracks || []) {
    o[tr.track_id] = clone(tr.tags || {});
    work[tr.track_id] = clone(tr.tags || {});
  }
  orig.value = o;
}
watch(() => props.data, init, { immediate: true });

const tracks = computed(() => props.data.tracks || []);
const writableTracks = computed(() => tracks.value.filter((tr) => tr.writable));
const readOnlyCount = computed(() => tracks.value.length - writableTracks.value.length);
const canEdit = computed(() => writableTracks.value.length > 0);
const discs = computed(() => {
  const n = Number((props.data.album && props.data.album.disc_count) || 0);
  if (n > 1) return n;
  const seen = new Set(tracks.value.map((tr) => firstValue(work[tr.track_id], 'DISCNUMBER').split('/')[0] || '1'));
  return seen.size;
});

const nonEmpty = (list) => (Array.isArray(list) ? list : []).filter((v) => String(v).trim() !== '');
const sameList = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);
function firstValue(tags, key) {
  const v = nonEmpty(tags && tags[key]);
  return v.length ? String(v[0]) : '';
}

// ── album-level fields ───────────────────────────────────────────────
const ALBUM_FIELDS = [
  { key: 'ALBUM' },
  { key: 'ALBUMARTIST', multi: true },
  { key: 'DATE', label: 'library.tags.year' },
  { key: 'GENRE', multi: true },
  { key: 'COMPOSER', multi: true },
  { key: 'LABEL' },
  { key: 'CATALOGNUMBER' },
  { key: 'DISCTOTAL', numeric: true },
  { key: 'COMPILATION', toggle: true },
];
// The tracks an album field speaks for: the ones that can be written (a
// read-only file would otherwise keep the field "various" forever).
const targets = computed(() => (writableTracks.value.length ? writableTracks.value : tracks.value));

function fieldState(source, key) {
  const lists = targets.value.map((tr) => nonEmpty(source[tr.track_id] && source[tr.track_id][key]));
  if (!lists.length) return { various: false, values: [] };
  const first = JSON.stringify(lists[0]);
  return lists.every((l) => JSON.stringify(l) === first) ? { various: false, values: lists[0] } : { various: true, values: [] };
}
const fields = computed(() => ALBUM_FIELDS.map((f) => {
  const now = fieldState(work, f.key);
  const before = fieldState(orig.value, f.key);
  const dirty = targets.value.some((tr) => !sameList(nonEmpty(orig.value[tr.track_id][f.key]), nonEmpty(work[tr.track_id][f.key])));
  return { ...f, ...now, wasVarious: before.various, dirty };
}));

function setAlbumField(f, values) {
  const list = values.slice();
  // Typing into a "(various)" field and deleting it again means "leave it":
  // back to what each file had. Clearing it on purpose is the button below.
  if (!nonEmpty(list).length && f.wasVarious) return revertField(f);
  for (const tr of writableTracks.value) {
    if (nonEmpty(list).length) work[tr.track_id][f.key] = list.slice();
    else delete work[tr.track_id][f.key];
  }
}
function clearField(f) {
  for (const tr of writableTracks.value) delete work[tr.track_id][f.key];
}
function revertField(f) {
  for (const tr of writableTracks.value) {
    const o = orig.value[tr.track_id][f.key];
    if (o === undefined) delete work[tr.track_id][f.key];
    else work[tr.track_id][f.key] = clone(o);
  }
}
function compilationOn(f) {
  return !f.various && f.values.length > 0 && !['0', 'false', 'no'].includes(String(f.values[0]).toLowerCase());
}
function setCompilation(on) {
  for (const tr of writableTracks.value) {
    if (on) work[tr.track_id].COMPILATION = ['1'];
    else delete work[tr.track_id].COMPILATION;
  }
}

// ── tracks ───────────────────────────────────────────────────────────
function trackNo(tr, i) {
  const n = firstValue(work[tr.track_id], 'TRACKNUMBER').split('/')[0];
  const d = firstValue(work[tr.track_id], 'DISCNUMBER').split('/')[0] || '1';
  const num = n || String(i + 1);
  return discs.value > 1 ? d + '.' + num : num;
}
function inlineMulti(tr, key) {
  return nonEmpty(work[tr.track_id][key]).length > 1;
}
function setInline(tr, key, v) {
  if (v === '' && orig.value[tr.track_id][key] === undefined) delete work[tr.track_id][key];
  else work[tr.track_id][key] = v === '' ? [] : [v];
}
function setTrackKey(tr, key, values) {
  work[tr.track_id][key] = values;
}
function removeTrackKey(tr, key) {
  delete work[tr.track_id][key];
}
function shownKeys(tr) {
  const w = work[tr.track_id];
  return EDITABLE_KEYS.filter((k) => w[k] !== undefined);
}
function missingKeys(tr) {
  const w = work[tr.track_id];
  return EDITABLE_KEYS.filter((k) => w[k] === undefined);
}
function addTrackKey(tr) {
  const k = addKey[tr.track_id];
  if (k && EDITABLE.has(k)) work[tr.track_id][k] = [];
  addKey[tr.track_id] = '';
}
// Tags this page cannot change (ReplayGain, encoder…), shown so nobody
// wonders where they went: the save keeps them as they are.
function otherTags(tr) {
  const out = { ...(tr.other_tags || {}) };
  for (const [k, v] of Object.entries(tr.tags || {})) if (!EDITABLE.has(k)) out[k] = v;
  return Object.entries(out);
}
function reasonText(reason) {
  const key = 'library.tags.reason.' + (reason || 'readonly');
  const s = t(key);
  return s === key ? t('library.tags.reason.readonly') : s;
}

// ── validation ───────────────────────────────────────────────────────
const NUMBER_RE = /^\d+(\/\d+)?$/;
// eslint-disable-next-line no-control-regex
const CONTROL_RE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/;
function problems(tr) {
  const out = [];
  const w = work[tr.track_id];
  for (const k of EDITABLE_KEYS) {
    const vals = nonEmpty(w[k]);
    if (NUMERIC_KEYS.has(k) && vals.some((v) => !NUMBER_RE.test(String(v).trim()))) out.push(t('library.tags.badNumber', { field: tagLabel(k) }));
    else if (vals.some((v) => CONTROL_RE.test(String(v)))) out.push(t('library.tags.badChars', { field: tagLabel(k) }));
  }
  return out;
}

// ── the difference ───────────────────────────────────────────────────
function diffTrack(o, w) {
  const set = {};
  const remove = [];
  for (const k of EDITABLE_KEYS) {
    const a = nonEmpty(o[k]);
    const b = nonEmpty(w[k]);
    if (sameList(a, b)) continue;
    const trimmed = b.map((v) => String(v).trim());
    if (sameList(a, trimmed)) continue;
    if (trimmed.length) set[k] = trimmed;
    else if (o[k] !== undefined) remove.push(k);
  }
  return { set, remove };
}
const changes = computed(() => {
  const out = [];
  for (const tr of writableTracks.value) {
    const d = diffTrack(orig.value[tr.track_id] || {}, work[tr.track_id] || {});
    if (Object.keys(d.set).length || d.remove.length) out.push({ track_id: tr.track_id, set: d.set, remove: d.remove });
  }
  return out;
});
const changedIds = computed(() => new Set(changes.value.map((c) => c.track_id)));
const invalid = computed(() => writableTracks.value.some((tr) => changedIds.value.has(tr.track_id) && problems(tr).length));
const dirty = computed(() => changes.value.length > 0);
watch(dirty, (v) => emit('dirty', v), { immediate: true });

function discard() {
  init();
}

// What the confirmation says: one line per change, the tracks it touches
// counted (or named, when they are few).
const titleOf = (id) => {
  const i = tracks.value.findIndex((x) => x.track_id === id);
  const tr = tracks.value[i];
  return tr ? trackNo(tr, i) + '. ' + (firstValue(orig.value[id], 'TITLE') || tr.file || '') : String(id);
};
const summary = computed(() => {
  const groups = new Map();
  for (const c of changes.value) {
    for (const [k, v] of Object.entries(c.set)) {
      const id = k + '\u0001set\u0001' + JSON.stringify(v);
      if (!groups.has(id)) groups.set(id, { key: k, action: 'set', values: v, ids: [] });
      groups.get(id).ids.push(c.track_id);
    }
    for (const k of c.remove) {
      const id = k + '\u0001remove';
      if (!groups.has(id)) groups.set(id, { key: k, action: 'remove', values: [], ids: [] });
      groups.get(id).ids.push(c.track_id);
    }
  }
  const order = (g) => EDITABLE_KEYS.indexOf(g.key);
  return [...groups.values()].sort((a, b) => order(a) - order(b)).map((g) => ({
    ...g,
    where: g.ids.length === writableTracks.value.length && g.ids.length > 1
      ? t('library.tags.onAllTracks', { n: g.ids.length })
      : g.ids.length > 2 ? t('library.tags.onNTracks', { n: g.ids.length }) : g.ids.map(titleOf).join(' · '),
  }));
});

// ── saving ───────────────────────────────────────────────────────────
const confirming = ref(false);
const saveError = ref('');
const sending = ref(false);
const { job, follow } = useJob();
const jobKind = ref('save');         // 'save' | 'undo'
const forceOffer = ref(null);        // an undo refused because a file changed since

const running = computed(() => job.value && (job.value.state === 'running' || job.value.state === 'queued'));
// A new album name or artist gives the album a new number once the music
// server has rescanned: the page follows the files there (new_album_id).
const following = computed(() => !!job.value && job.value.follow === 'waiting');
const movedTo = computed(() => {
  const j = job.value;
  return j && j.follow === 'done' && j.new_album_id && String(j.new_album_id) !== String(props.albumId) ? j.new_album_id : null;
});
const leaveWhenMoved = ref(false);     // the dialog was closed while still waiting
watch(movedTo, (id) => { if (id && leaveWhenMoved.value) emit('moved', id); });
const pct = computed(() => {
  const j = job.value;
  if (!j || !j.total) return 0;
  return Math.min(100, Math.round((100 * (j.done || 0)) / j.total));
});

function askSave() {
  saveError.value = '';
  job.value = null;
  forceOffer.value = null;
  confirming.value = true;
}
async function doSave() {
  sending.value = true;
  saveError.value = '';
  const r = await lib.saveTags(props.albumId, changes.value);
  sending.value = false;
  if (!r.ok || !r.data || !r.data.job_id) {
    saveError.value = isBusy(r) ? (r.data && r.data.message) || t('library.tags.busy') : errorText(r);
    return;
  }
  jobKind.value = 'save';
  follow(r.data.job_id, changes.value.length);
}
async function undoJob(force = false) {
  const id = job.value && job.value.job_id;
  if (!id) return;
  sending.value = true;
  saveError.value = '';
  forceOffer.value = null;
  const r = await lib.undo(id, force);
  sending.value = false;
  if (isChangedSince(r)) { forceOffer.value = (r.data && r.data.message) || ''; return; }
  if (isBusy(r)) { saveError.value = (r.data && r.data.message) || t('library.tags.busy'); return; }
  if (!r.ok || !r.data || !r.data.job_id) { saveError.value = errorText(r); return; }
  jobKind.value = 'undo';
  follow(r.data.job_id, job.value ? job.value.total : 0);
}
function closeDialog() {
  const finished = job.value && !running.value;
  confirming.value = false;
  if (!finished) return;
  if (movedTo.value) { emit('moved', movedTo.value); return; }
  if (following.value) { leaveWhenMoved.value = true; return; }
  job.value = null;
  emit('reload');
}
const rescanText = computed(() => {
  const s = job.value && job.value.rescan;
  if (s === 'started') return t('library.tags.rescanStarted');
  if (s === 'failed') return t('library.tags.rescanFailed');
  return t('library.tags.rescanSkipped');
});
</script>

<template>
  <div class="lb-tags" :class="{ 'has-bar': dirty }">
    <div class="lb-banner" v-if="!canEdit">
      <Icon name="info" :size="18" />
      <span>{{ reasonText(data.reason || (tracks[0] && tracks[0].reason)) }} {{ t('library.tags.readOnlyAll') }}</span>
    </div>
    <div class="lb-banner soft" v-else-if="readOnlyCount > 0">
      <Icon name="info" :size="18" />
      <span>{{ readOnlyCount === 1 ? t('library.tags.someReadOnlyOne') : t('library.tags.someReadOnly', { n: readOnlyCount }) }}</span>
    </div>

    <!-- album-level fields -->
    <div class="card">
      <h3><span class="dot"></span>{{ t('library.tags.albumTitle') }}</h3>
      <p class="sub" v-if="canEdit">{{ t('library.tags.albumHelp') }}</p>
      <div class="lb-fields">
        <div class="lb-field" v-for="f in fields" :key="f.key" :class="{ changed: f.dirty }">
          <div class="lb-field-l">
            <label>{{ f.label ? t(f.label) : tagLabel(f.key) }}</label>
            <button v-if="f.dirty && canEdit" type="button" class="lb-link" @click="revertField(f)">
              <Icon name="rotate-ccw" :size="13" /> {{ t('library.tags.revert') }}
            </button>
          </div>
          <div v-if="f.toggle" class="lb-toggle-row">
            <Toggle :model-value="compilationOn(f)" :disabled="!canEdit" @update:model-value="setCompilation" />
            <span class="muted">{{ f.various ? t('library.tags.various') : compilationOn(f) ? t('library.tags.compilationYes') : t('library.tags.compilationNo') }}</span>
          </div>
          <template v-else>
            <ValuesEditor
              :model-value="f.values" :multi="!!f.multi" :numeric="!!f.numeric" :disabled="!canEdit"
              :placeholder="f.various ? t('library.tags.various') : ''"
              @update:model-value="(v) => setAlbumField(f, v)"
            />
            <button v-if="f.various && f.wasVarious && canEdit" type="button" class="lb-link lb-clear" @click="clearField(f)">
              {{ t('library.tags.clearAll') }}
            </button>
          </template>
        </div>
      </div>
    </div>

    <!-- tracks -->
    <div class="card lb-tracks-card">
      <h3><span class="dot"></span>{{ t('library.tags.tracksTitle') }}</h3>
      <p class="sub">{{ t('library.tags.tracksHelp') }}</p>
      <div class="lb-tr lb-tr-head" aria-hidden="true">
        <span>#</span><span>{{ tagLabel('TITLE') }}</span><span>{{ tagLabel('ARTIST') }}</span><span>{{ tagLabel('COMPOSER') }}</span><span></span>
      </div>
      <div v-for="(tr, i) in tracks" :key="tr.track_id" class="lb-trk" :class="{ ro: !tr.writable, changed: changedIds.has(tr.track_id), open: open[tr.track_id] }">
        <div class="lb-tr">
          <span class="lb-tr-n">{{ trackNo(tr, i) }}</span>
          <template v-for="key in ['TITLE', 'ARTIST', 'COMPOSER']" :key="key">
            <label class="lb-tr-cell">
              <span class="lb-tr-lbl">{{ tagLabel(key) }}</span>
              <button v-if="inlineMulti(tr, key)" type="button" class="lb-in lb-in-multi" @click="open[tr.track_id] = true">
                {{ t('library.tags.nValues', { n: work[tr.track_id][key].filter(Boolean).length }) }}
              </button>
              <input v-else class="lb-in" :value="firstValue(work[tr.track_id], key)" :disabled="!tr.writable"
                     @input="setInline(tr, key, $event.target.value)" />
            </label>
          </template>
          <button type="button" class="lb-ib lb-tr-more" :aria-expanded="!!open[tr.track_id]"
                  :title="t('library.tags.allTags')" @click="open[tr.track_id] = !open[tr.track_id]">
            <Icon :name="open[tr.track_id] ? 'chevron-up' : 'chevron-down'" :size="17" />
            <span class="lb-tr-more-t">{{ t('library.tags.allTags') }}</span>
          </button>
        </div>
        <div class="lb-tr-ro" v-if="!tr.writable">
          <Icon name="info" :size="14" /> {{ reasonText(tr.reason) }}
        </div>
        <div class="lb-tr-problems" v-for="p in (changedIds.has(tr.track_id) ? problems(tr) : [])" :key="p">
          <Icon name="alert-triangle" :size="14" /> {{ p }}
        </div>

        <div class="lb-alltags" v-if="open[tr.track_id]">
          <div class="lb-file">
            <span class="mono">{{ tr.file }}</span>
            <span class="muted">{{ String(tr.format || '').toUpperCase() }}<template v-if="tr.duration"> · {{ fmtDuration(tr.duration) }}</template><template v-if="tr.has_picture"> · {{ t('library.tags.hasPicture') }}</template></span>
          </div>
          <div class="lb-tagrow" v-for="k in shownKeys(tr)" :key="k">
            <div class="lb-tagrow-l">
              <span>{{ tagLabel(k) }}</span>
              <span class="lb-key">{{ k }}</span>
            </div>
            <ValuesEditor
              :model-value="work[tr.track_id][k]" :multi="!SINGLE_KEYS.has(k)" :numeric="NUMERIC_KEYS.has(k)"
              :disabled="!tr.writable"
              :hint="k === 'PERFORMER' ? t('library.tags.performerHint') : ''"
              @update:model-value="(v) => setTrackKey(tr, k, v)"
            />
            <button v-if="tr.writable" type="button" class="lb-ib small" :title="t('library.tags.removeTag')" :aria-label="t('library.tags.removeTag')" @click="removeTrackKey(tr, k)">
              <Icon name="trash-2" :size="15" />
            </button>
          </div>
          <div class="lb-addtag" v-if="tr.writable && missingKeys(tr).length">
            <select :value="addKey[tr.track_id] || ''" :aria-label="t('library.tags.addTag')" @change="addKey[tr.track_id] = $event.target.value">
              <option value="">{{ t('library.tags.addTag') }}</option>
              <option v-for="k in missingKeys(tr)" :key="k" :value="k">{{ tagLabel(k) }}</option>
            </select>
            <button type="button" class="secondary fit" :disabled="!addKey[tr.track_id]" @click="addTrackKey(tr)">
              <Icon name="plus" :size="15" /> {{ t('library.tags.add') }}
            </button>
          </div>
          <details class="lb-other" v-if="otherTags(tr).length">
            <summary>{{ t('library.tags.otherTags', { n: otherTags(tr).length }) }}</summary>
            <div class="lb-other-row" v-for="[k, v] in otherTags(tr)" :key="k">
              <span class="lb-key">{{ k }}</span><span class="silver">{{ (Array.isArray(v) ? v : [v]).join(' · ') }}</span>
            </div>
          </details>
        </div>
      </div>
    </div>

    <!-- save bar -->
    <div class="lb-savebar" v-if="dirty">
      <span class="lb-savebar-t">{{ changes.length === 1 ? t('library.tags.pendingOne') : t('library.tags.pending', { n: changes.length }) }}</span>
      <button type="button" class="ghost fit" @click="discard">{{ t('library.tags.discard') }}</button>
      <button type="button" class="fit" :disabled="invalid" @click="askSave">
        <Icon name="save" :size="15" /> {{ changes.length === 1 ? t('library.tags.saveOne') : t('library.tags.save', { n: changes.length }) }}
      </button>
    </div>

    <!-- confirm / progress / result -->
    <Modal v-if="confirming" :title="job ? (jobKind === 'undo' ? t('library.tags.undoTitle') : t('library.tags.savingTitle')) : t('library.tags.confirmTitle')"
           :locked="running || sending" wide @close="closeDialog">
      <template v-if="!job">
        <p class="sub">{{ changes.length === 1 ? t('library.tags.confirmLeadOne') : t('library.tags.confirmLead', { n: changes.length }) }}</p>
        <ul class="lb-summary">
          <li v-for="g in summary" :key="g.key + g.action + JSON.stringify(g.values)">
            <strong>{{ tagLabel(g.key) }}</strong>
            <span v-if="g.action === 'remove'" class="lb-removed">{{ t('library.tags.removed') }}</span>
            <span v-else> → <span class="silver">{{ g.values.join(' · ') }}</span></span>
            <span class="muted lb-where">{{ g.where }}</span>
          </li>
        </ul>
        <p class="muted">{{ t('library.tags.confirmNote') }}</p>
      </template>
      <template v-else>
        <div v-if="running">
          <p class="sub">{{ t('library.tags.progress', { done: job.done || 0, total: job.total || changes.length }) }}</p>
          <div class="fm-prog"><i :style="{ width: pct + '%' }"></i></div>
        </div>
        <div v-else>
          <p class="lb-result" :class="{ bad: job.state === 'error' || (job.errors && job.errors.length) }">
            <Icon :name="job.state === 'done' && !(job.errors && job.errors.length) ? 'check' : 'alert-triangle'" :size="18" />
            <span v-if="job.state === 'done' && !(job.errors && job.errors.length)">
              {{ jobKind === 'undo' ? t('library.tags.undoDone') : t('library.tags.doneAll', { n: job.total || changes.length }) }}
            </span>
            <span v-else-if="job.state === 'done'">{{ t('library.tags.doneSome', { bad: job.errors.length, n: job.total }) }}</span>
            <span v-else>{{ job.message || t('library.tags.failed') }}</span>
          </p>
          <ul class="lb-errors" v-if="job.errors && job.errors.length">
            <li v-for="e in job.errors" :key="String(e.track_id) + e.message">
              <strong>{{ titleOf(e.track_id) }}</strong> <span class="muted">{{ e.message }}</span>
            </li>
          </ul>
          <p class="muted">{{ rescanText }}</p>
          <p class="muted" v-if="following">{{ t('library.tags.following') }}</p>
          <p class="muted" v-else-if="movedTo">{{ t('library.tags.moved') }}</p>
          <div class="msg" v-if="forceOffer !== null">
            {{ t('library.history.changedSince') }}<template v-if="forceOffer"> ({{ forceOffer }})</template>
          </div>
        </div>
      </template>
      <div class="msg err" v-if="saveError">{{ saveError }}</div>

      <template #foot>
        <template v-if="!job">
          <button type="button" class="ghost fit" :disabled="sending" @click="closeDialog">{{ t('common.cancel') }}</button>
          <button type="button" class="fit" :disabled="sending || !changes.length" @click="doSave">
            {{ changes.length === 1 ? t('library.tags.saveOne') : t('library.tags.save', { n: changes.length }) }}
          </button>
        </template>
        <template v-else-if="!running">
          <button v-if="forceOffer !== null" type="button" class="danger fit" :disabled="sending" @click="undoJob(true)">{{ t('library.history.undoAnyway') }}</button>
          <button v-else-if="jobKind === 'save' && job.undoable && job.state === 'done'" type="button" class="ghost fit" :disabled="sending" @click="undoJob(false)">
            <Icon name="undo-2" :size="15" /> {{ t('library.history.undo') }}
          </button>
          <button type="button" class="fit" :disabled="sending" @click="closeDialog">{{ t('common.close') }}</button>
        </template>
      </template>
    </Modal>
  </div>
</template>
