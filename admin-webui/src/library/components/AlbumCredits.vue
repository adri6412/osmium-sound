<script setup>
// The online information of an album page — which edition MusicBrainz says
// it is, who played and wrote and recorded it, what Wikipedia says — with
// the owner's corrections. Corrections are one document per album
// (GET/POST /api/meta/album/edit, `overrides`), saved on the device and never
// written into the files. This page edits a copy of that document and shows
// the lines as they will read, including what was hidden (struck through,
// with a way back); "Save corrections" sends the whole document.
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue';
import { useI18n } from '../../i18n';
import Icon from '../../components/Icon.vue';
import Toggle from '../../components/Toggle.vue';
import CandidatesDialog from './CandidatesDialog.vue';
import CreditLineDialog from './CreditLineDialog.vue';
import PersonDialog from './PersonDialog.vue';
import { lib, errorText } from '../libraryApi.js';
import {
  GROUP_ORDER, groupLabel, roleLabel, roleName, trackList, fmtDate, creditKey, personKey, clone,
} from '../meta.js';

const props = defineProps({
  albumId: { type: String, required: true },
  libTracks: { type: Array, default: () => [] },   // the library's tracks, a fallback for the track picker
});
const emit = defineEmits(['dirty']);
const { t } = useI18n();

const doc = ref(null);            // GET /api/meta/album/edit
const status = ref('');
const loadError = ref('');
const ov = ref(emptyOverrides());
const saved = ref(emptyOverrides());
const saving = ref(false);
const saveMsg = ref('');
const saveError = ref('');
let tries = 0;
let timer = null;
let alive = true;

function emptyOverrides() {
  return { hide: [], people: {}, remove_people: {}, entries: {}, add: [], tracks: {}, about_hidden: false };
}
function normalise(o) {
  const src = o && typeof o === 'object' ? o : {};
  return {
    hide: Array.isArray(src.hide) ? src.hide.slice() : [],
    people: { ...(src.people || {}) },
    remove_people: clone(src.remove_people || {}),
    entries: clone(src.entries || {}),
    add: clone(src.add || []),
    tracks: clone(src.tracks || {}),      // per-track corrections: kept as they are
    about_hidden: !!src.about_hidden,
  };
}
// What goes over the wire: only the parts that say something, so an album
// with no corrections left sends `{}` (= as MusicBrainz gave it).
function compact(o) {
  const out = {};
  if (o.hide.length) out.hide = o.hide;
  if (Object.keys(o.people).length) out.people = o.people;
  const rp = {};
  for (const [k, v] of Object.entries(o.remove_people)) if (v && v.length) rp[k] = v;
  if (Object.keys(rp).length) out.remove_people = rp;
  if (Object.keys(o.entries).length) out.entries = o.entries;
  if (o.add.length) out.add = o.add;
  if (Object.keys(o.tracks).length) out.tracks = o.tracks;
  if (o.about_hidden) out.about_hidden = true;
  return out;
}
function stable(x) {
  if (Array.isArray(x)) return '[' + x.map(stable).join(',') + ']';
  if (x && typeof x === 'object') return '{' + Object.keys(x).sort().map((k) => JSON.stringify(k) + ':' + stable(x[k])).join(',') + '}';
  return JSON.stringify(x);
}
const dirty = computed(() => stable(compact(ov.value)) !== stable(compact(saved.value)));
const hasSaved = computed(() => Object.keys(compact(saved.value)).length > 0);
watch(dirty, (v) => emit('dirty', v), { immediate: true });

async function load(resetEdits = true) {
  clearTimeout(timer);
  const r = await lib.albumEdit(props.albumId);
  if (!alive) return;
  if (!r.ok || !r.data) {
    status.value = 'error';
    loadError.value = errorText(r);
    return;
  }
  const d = r.data;
  status.value = String(d.status || 'error');
  loadError.value = d.status === 'error' ? d.message || '' : '';
  if (d.credits || d.release || d.overrides) doc.value = d;
  if (resetEdits || !dirty.value) {
    ov.value = normalise(d.overrides);
    saved.value = normalise(d.overrides);
  } else {
    saved.value = normalise(d.overrides);
  }
  // looking the album up: ask again, like the kiosk's album page does
  if (d.status === 'pending' && tries++ < 45) timer = setTimeout(() => load(false), 2000);
}
onMounted(() => load());
onBeforeUnmount(() => { alive = false; clearTimeout(timer); });
watch(() => props.albumId, () => { tries = 0; doc.value = null; load(); });

const release = computed(() => (doc.value && doc.value.release) || null);
const match = computed(() => (doc.value && doc.value.match) || null);
const discs = computed(() => Number((release.value && release.value.disc_count) || 1));
const about = computed(() => (doc.value && doc.value.about) || null);
const places = computed(() => (doc.value && doc.value.places) || []);
const albumTracks = computed(() => {
  const mb = (doc.value && doc.value.tracks) || [];
  if (mb.length) return mb.map((x) => ({ disc: Number(x.disc || 1), n: Number(x.n), title: x.title || '' }));
  return props.libTracks.map((tr, i) => {
    const tg = tr.tags || {};
    const n = parseInt(String((tg.TRACKNUMBER || [])[0] || i + 1), 10);
    const d = parseInt(String((tg.DISCNUMBER || [])[0] || 1), 10);
    return { disc: d || 1, n: n || i + 1, title: String((tg.TITLE || [])[0] || '') };
  });
});

// ── the lines as they will read ──────────────────────────────────────
const lines = computed(() => {
  const o = ov.value;
  const out = [];
  for (const c of (doc.value && doc.value.credits) || []) {
    const key = creditKey(c);
    const e = o.entries[key];
    const eff = e ? { ...c, group: e.group || c.group, role: e.role || c.role, attr: e.attr ?? c.attr, credit: e.credit ?? c.credit } : c;
    const removed = new Set(o.remove_people[key] || []);
    const people = (c.people || []).map((p) => {
      const pk = personKey(p);
      const po = o.people[pk];
      return {
        key: pk,
        orig: p,
        name: (po && po.name) || p.name,
        // null keeps MusicBrainz's link; 0 and "" are a link taken away
        artist_id: po && po.artist_id != null ? po.artist_id || null : p.artist_id,
        mbid: po && po.mbid != null ? po.mbid || null : p.mbid,
        credited_as: p.credited_as || '',
        edited: !!po,
        renamed: !!(po && po.name && po.name !== p.name),
        removed: removed.has(pk),
      };
    });
    out.push({ kind: 'mb', key, orig: c, eff, changed: !!e, hidden: o.hide.includes(key), people, tracks: c.tracks });
  }
  o.add.forEach((a, i) => {
    out.push({
      kind: 'add', key: 'add:' + i, index: i, eff: a, changed: false, hidden: false, tracks: a.tracks,
      people: (a.people || []).map((p) => ({ ...p, key: '', edited: false, removed: false })),
    });
  });
  return out;
});
const groups = computed(() => {
  const by = {};
  for (const l of lines.value) {
    const g = l.eff.group || 'other';
    (by[g] = by[g] || []).push(l);
  }
  const order = GROUP_ORDER.concat(Object.keys(by).filter((k) => !GROUP_ORDER.includes(k)));
  return order.filter((g) => by[g]).map((g) => ({ group: g, lines: by[g] }));
});
const counts = computed(() => {
  const o = compact(ov.value);
  return (o.hide || []).length + Object.keys(o.people || {}).length + Object.values(o.remove_people || {}).reduce((a, v) => a + v.length, 0)
    + Object.keys(o.entries || {}).length + (o.add || []).length + (o.about_hidden ? 1 : 0);
});

// ── edits ────────────────────────────────────────────────────────────
function update(fn) {
  const next = normalise(ov.value);
  fn(next);
  ov.value = next;
  saveMsg.value = '';
}
function hideLine(l) { update((o) => { if (!o.hide.includes(l.key)) o.hide.push(l.key); }); }
function showLine(l) { update((o) => { o.hide = o.hide.filter((k) => k !== l.key); }); }
function deleteAdded(l) { update((o) => { o.add.splice(l.index, 1); }); }

const lineDialog = ref(null);      // {mode, line?}
function openAdd() { lineDialog.value = { mode: 'add', line: null }; }
function openChange(l) { lineDialog.value = { mode: l.kind === 'add' ? 'add' : 'entry', line: l }; }
function onLineSave(v) {
  const d = lineDialog.value;
  update((o) => {
    if (d.mode === 'add' && !d.line) o.add.push(v);
    else if (d.mode === 'add') o.add.splice(d.line.index, 1, v);
    else {
      const c = d.line.orig;
      const same = v.group === c.group && v.role === c.role && (v.attr || '') === (c.attr || '') && (v.credit || '') === (c.credit || '');
      if (same) delete o.entries[d.line.key];
      else o.entries[d.line.key] = { group: v.group, role: v.role, attr: v.attr, credit: v.credit };
    }
  });
  lineDialog.value = null;
}

const personDialog = ref(null);    // {line, person}
function openPerson(l, p) {
  if (l.kind === 'add') { openChange(l); return; }
  personDialog.value = { line: l, person: p };
}
function personOverride(o, pk) {
  const cur = o.people[pk] || { name: null, artist_id: null, mbid: null };
  return { name: cur.name ?? null, artist_id: cur.artist_id ?? null, mbid: cur.mbid ?? null };
}
function setPerson(o, pk, po) {
  if (po.name == null && po.artist_id == null && po.mbid == null) delete o.people[pk];
  else o.people[pk] = po;
}
function onRename(name) {
  const { person } = personDialog.value;
  update((o) => {
    const po = personOverride(o, person.key);
    po.name = name === person.orig.name ? null : name;
    setPerson(o, person.key, po);
  });
  personDialog.value = null;
}
function onLink(p) {
  const { person } = personDialog.value;
  update((o) => {
    const po = personOverride(o, person.key);
    if (p.artist_id != null) po.artist_id = p.artist_id === person.orig.artist_id ? null : p.artist_id;
    if (p.mbid) po.mbid = p.mbid === person.orig.mbid ? null : p.mbid;
    setPerson(o, person.key, po);
  });
  personDialog.value = null;
}
// In `people`, null keeps what MusicBrainz says; `artist_id: 0` and
// `mbid: ""` take the link away. A link the owner added (and MusicBrainz never
// had) just goes back to null.
function onUnlink(which) {
  const { person } = personDialog.value;
  update((o) => {
    const po = personOverride(o, person.key);
    if (which === 'library') po.artist_id = person.orig.artist_id ? 0 : null;
    else po.mbid = person.orig.mbid ? '' : null;
    setPerson(o, person.key, po);
  });
  personDialog.value = null;
}
function onRemovePerson() {
  const { line, person } = personDialog.value;
  update((o) => {
    const list = o.remove_people[line.key] || [];
    if (!list.includes(person.key)) o.remove_people[line.key] = [...list, person.key];
  });
  personDialog.value = null;
}
function onRestorePerson() {
  const { line, person } = personDialog.value;
  update((o) => {
    const list = (o.remove_people[line.key] || []).filter((k) => k !== person.key);
    if (list.length) o.remove_people[line.key] = list; else delete o.remove_people[line.key];
  });
  personDialog.value = null;
}
function onResetPerson() {
  const { person } = personDialog.value;
  update((o) => { delete o.people[person.key]; });
  personDialog.value = null;
}
function setAboutShown(v) { update((o) => { o.about_hidden = !v; }); }

function discard() {
  ov.value = normalise(saved.value);
  saveMsg.value = '';
  saveError.value = '';
}
async function save(overrides = compact(ov.value)) {
  saving.value = true;
  saveError.value = '';
  saveMsg.value = '';
  const r = await lib.albumEditSave(props.albumId, overrides);
  saving.value = false;
  if (!r.ok || (r.data && (r.data.success === false || r.data.status === 'error'))) {
    saveError.value = errorText(r);
    return false;
  }
  saved.value = normalise(overrides);
  ov.value = normalise(overrides);
  saveMsg.value = Object.keys(overrides).length ? t('library.credits.saved') : t('library.credits.resetDone');
  tries = 0;
  load(false);
  return true;
}
async function resetAll() {
  if (!window.confirm(t('library.credits.resetConfirm'))) return;
  await save({});
}

// ── the edition ──────────────────────────────────────────────────────
const choosingEdition = ref(false);
function onPinned() {
  choosingEdition.value = false;
  tries = 0;
  status.value = 'pending';
  load(false);
}
const howText = computed(() => {
  const how = match.value && match.value.how;
  if (how === 'manual' || how === 'pin' || how === 'pinned') return t('library.credits.howManual');
  if (how === 'tag' || how === 'tags') return t('library.credits.howTag');
  if (how) return t('library.credits.howSearch');
  return '';
});
const releaseLine = computed(() => {
  const r = release.value;
  if (!r) return '';
  const labels = (r.labels || []).map((l) => [l.name, l.catno].filter(Boolean).join(' ')).join(', ');
  return [fmtDate(r.date), r.country, labels, r.track_count ? t('library.credits.editionTracks', { n: r.track_count }) : '']
    .filter(Boolean).join(' · ');
});
const aboutOpen = ref(false);

function onTracksText(l) {
  return l.tracks && l.tracks.length ? t('library.credits.onTracks', { list: trackList(l.tracks, discs.value) }) : '';
}
</script>

<template>
  <div class="lb-credits" :class="{ 'has-bar': dirty }">
    <!-- status -->
    <div class="lb-banner" v-if="status === 'pending'">
      <Icon name="refresh-cw" :size="18" /><span>{{ t('library.credits.status.pending') }}</span>
    </div>
    <div class="lb-banner" v-else-if="status === 'nomatch'">
      <Icon name="info" :size="18" /><span>{{ t('library.credits.status.nomatch') }}</span>
    </div>
    <div class="lb-banner" v-else-if="status === 'offline'">
      <Icon name="alert-triangle" :size="18" /><span>{{ t('library.credits.status.offline') }}</span>
    </div>
    <div class="lb-banner" v-else-if="status === 'disabled'">
      <Icon name="info" :size="18" /><span>{{ t('library.credits.status.disabled') }} <a href="./#/">{{ t('library.credits.status.openAdmin') }}</a></span>
    </div>
    <div class="msg err" v-else-if="status === 'error'">{{ loadError || t('library.errors.generic') }}</div>
    <p class="lb-empty" v-else-if="!status">{{ t('common.loading') }}</p>

    <!-- edition -->
    <div class="card" v-if="status && status !== 'disabled' && status !== 'error'">
      <h3><span class="dot"></span>{{ t('library.credits.editionTitle') }}</h3>
      <template v-if="release">
        <div class="lb-release">
          <strong>{{ release.title }}</strong><span class="muted" v-if="release.artist"> — {{ release.artist }}</span>
        </div>
        <div class="muted">{{ releaseLine }}</div>
        <div class="muted lb-how" v-if="howText">
          {{ howText }}<template v-if="release.url"> · <a :href="release.url" target="_blank" rel="noopener">musicbrainz.org <Icon name="external-link" :size="12" /></a></template>
        </div>
      </template>
      <p class="sub" v-else>{{ status === 'nomatch' ? t('library.credits.noEdition') : t('library.credits.editionUnknown') }}</p>
      <div class="lb-actions">
        <button type="button" class="secondary" @click="choosingEdition = true"><Icon name="disc" :size="15" /> {{ t('library.credits.chooseEdition') }}</button>
      </div>
    </div>

    <!-- credits -->
    <div class="card lb-credits-card" v-if="doc && (lines.length || places.length || release)">
      <div class="lb-card-h">
        <h3><span class="dot"></span>{{ t('library.credits.creditsTitle') }}</h3>
        <span class="pill gold" v-if="counts">{{ counts === 1 ? t('library.credits.oneCorrection') : t('library.credits.nCorrections', { n: counts }) }}</span>
      </div>
      <p class="sub">{{ t('library.credits.creditsHelp') }}</p>
      <div class="lb-actions top">
        <button type="button" class="secondary" @click="openAdd"><Icon name="plus" :size="15" /> {{ t('library.credits.addCredit') }}</button>
        <button type="button" class="ghost" v-if="hasSaved" :disabled="saving" @click="resetAll"><Icon name="rotate-ccw" :size="15" /> {{ t('library.credits.reset') }}</button>
      </div>

      <p class="lb-empty" v-if="!lines.length && !places.length">{{ t('library.credits.noCredits') }}</p>

      <div class="lb-group" v-for="g in groups" :key="g.group">
        <div class="lb-group-h">{{ groupLabel(g.group) }}</div>
        <div v-for="l in g.lines" :key="l.key" class="lb-line" :class="{ hidden: l.hidden, added: l.kind === 'add', changed: l.changed }">
          <div class="lb-line-role">
            <span class="lb-line-label">{{ roleLabel(l.eff) }}</span>
            <span class="lb-line-was muted" v-if="l.changed">{{ t('library.credits.was', { label: roleLabel(l.orig) }) }}</span>
            <span class="pill gold lb-tag" v-if="l.kind === 'add'">{{ t('library.credits.addedByYou') }}</span>
            <span class="pill lb-tag" v-if="l.hidden">{{ t('library.credits.hiddenTag') }}</span>
          </div>
          <div class="lb-line-people">
            <button v-for="(p, i) in l.people" :key="i" type="button" class="lb-person"
                    :class="{ removed: p.removed, edited: p.edited, linked: p.artist_id || p.mbid }"
                    :disabled="l.hidden" @click="openPerson(l, p)">
              <Icon :name="p.artist_id ? 'library' : p.mbid ? 'globe' : 'user'" :size="13" />
              <span>{{ p.name }}</span><span class="muted" v-if="p.credited_as && p.credited_as !== p.name"> ({{ p.credited_as }})</span>
              <Icon v-if="p.edited" name="pencil" :size="11" class="gold" />
            </button>
            <span class="lb-line-tracks muted" v-if="onTracksText(l)">{{ onTracksText(l) }}</span>
          </div>
          <div class="lb-line-act">
            <template v-if="l.kind === 'mb'">
              <button v-if="!l.hidden" type="button" class="lb-ib small" :title="t('library.credits.changeRole')" :aria-label="t('library.credits.changeRole')" @click="openChange(l)"><Icon name="pencil" :size="15" /></button>
              <button v-if="!l.hidden" type="button" class="lb-ib small" :title="t('library.credits.hideLine')" :aria-label="t('library.credits.hideLine')" @click="hideLine(l)"><Icon name="eye-off" :size="15" /></button>
              <button v-else type="button" class="lb-link" @click="showLine(l)"><Icon name="eye" :size="14" /> {{ t('library.credits.showLine') }}</button>
            </template>
            <template v-else>
              <button type="button" class="lb-ib small" :title="t('library.credits.editAdded')" :aria-label="t('library.credits.editAdded')" @click="openChange(l)"><Icon name="pencil" :size="15" /></button>
              <button type="button" class="lb-ib small" :title="t('library.credits.deleteAdded')" :aria-label="t('library.credits.deleteAdded')" @click="deleteAdded(l)"><Icon name="trash-2" :size="15" /></button>
            </template>
          </div>
        </div>
      </div>

      <div class="lb-group" v-if="places.length">
        <div class="lb-group-h">{{ groupLabel('places') }}</div>
        <div v-for="(p, i) in places" :key="'pl' + i" class="lb-line">
          <div class="lb-line-role"><span class="lb-line-label">{{ roleName(p.role) }}</span></div>
          <div class="lb-line-people"><span class="silver">{{ p.name }}<template v-if="p.area"> ({{ p.area }})</template></span></div>
          <div class="lb-line-act"></div>
        </div>
      </div>
    </div>

    <!-- Wikipedia -->
    <div class="card" v-if="about && about.text">
      <div class="between">
        <h3><span class="dot"></span>{{ t('library.credits.aboutTitle') }}</h3>
        <Toggle :model-value="!ov.about_hidden" @update:model-value="setAboutShown" :aria-label="t('library.credits.aboutShow')" />
      </div>
      <p class="sub">{{ ov.about_hidden ? t('library.credits.aboutHidden') : t('library.credits.aboutShow') }}</p>
      <div class="lb-about" :class="{ open: aboutOpen, off: ov.about_hidden }">{{ about.text }}</div>
      <div class="between lb-about-foot">
        <span class="muted">{{ t('library.credits.fromWikipedia', { license: about.license || 'CC BY-SA' }) }}<template v-if="about.url"> · <a :href="about.url" target="_blank" rel="noopener">{{ String(about.url).replace(/^https?:\/\//, '').split('/')[0] }}</a></template></span>
        <button type="button" class="lb-link" @click="aboutOpen = !aboutOpen">{{ aboutOpen ? t('library.credits.less') : t('library.credits.more') }}</button>
      </div>
    </div>

    <div class="msg" v-if="saveMsg"><Icon name="check" :size="15" class="gold" /> {{ saveMsg }}</div>
    <div class="msg err" v-if="saveError">{{ saveError }}</div>

    <div class="lb-savebar" v-if="dirty">
      <span class="lb-savebar-t">{{ t('library.credits.unsaved') }}</span>
      <button type="button" class="ghost fit" :disabled="saving" @click="discard">{{ t('library.tags.discard') }}</button>
      <button type="button" class="fit" :disabled="saving" @click="save()"><Icon name="save" :size="15" /> {{ t('library.credits.save') }}</button>
    </div>

    <CandidatesDialog v-if="choosingEdition" kind="album" :id="albumId" @close="choosingEdition = false" @pinned="onPinned" />
    <CreditLineDialog v-if="lineDialog" :mode="lineDialog.mode" :initial="lineDialog.line ? lineDialog.line.eff : null"
                      :album-tracks="albumTracks" :discs="discs" @close="lineDialog = null" @save="onLineSave" />
    <PersonDialog v-if="personDialog" :person="personDialog.person" :line="roleLabel(personDialog.line.eff)" :line-hidden="personDialog.line.hidden"
                  @close="personDialog = null" @rename="onRename" @link="onLink" @unlink="onUnlink" @remove="onRemovePerson" @restore="onRestorePerson" @reset="onResetPerson" />
  </div>
</template>
