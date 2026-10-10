<script setup>
// Settings → CD ripping → "Rip the CD": the web admin's copy of the kiosk's
// rip window (native-ui-qt/qml/CdRip.qml), on the same sources_server
// endpoints (/api/cd/info, /api/cd/rip, /api/cd/rip/status) through
// webui_server's session-gated /api/system/cd/<rest>. The disc is read only
// when asked: every /api/cd/info runs cd-discid and a MusicBrainz lookup.
import { ref, computed, watch, onBeforeUnmount } from 'vue';
import { api } from '../api.js';
import { useI18n } from '../i18n';
import FolderPicker from './FolderPicker.vue';

const props = defineProps({
  enabled: { type: Boolean, default: true },
  ripping: { type: Boolean, default: false },
});
// changed: a rip started or ended, the settings above want reloading
const emit = defineEmits(['changed', 'say']);
const { t } = useI18n();

const open = ref(false);
const loading = ref(false);
const busy = ref(false);
const info = ref(null);
const artist = ref('');
const album = ref('');
const titles = ref([]);
// the disc's track numbers beside `titles`, and which get ripped: all of them
// for a new disc, untick the ones to leave out
const nums = ref([]);
const picked = ref([]);
const pickedCount = computed(() => picked.value.filter(Boolean).length);
const allPicked = computed(() => pickedCount.value === picked.value.length);
function pickAll(on) { picked.value = titles.value.map(() => on); }
const release = ref('');
const dest = ref('');          // '__default__' or a source_id
const destPath = ref('');      // a folder picked in the browser, overrides `dest`
const picking = ref(false);
const status = ref(null);
let timer = null;

const ENDED = ['done', 'error', 'idle', 'cancelled'];
const running = computed(() => !!status.value && !ENDED.includes(status.value.state));
const ended = computed(() => !!status.value && ['done', 'error', 'cancelled'].includes(status.value.state));
const dests = computed(() => {
  const d = info.value || {};
  const out = [];
  if (d.default_target && d.default_target.path) {
    out.push({ id: '__default__', label: t('settings.cdRip.ripDefaultDest', { path: d.default_target.path }) });
  }
  for (const x of d.destinations || []) out.push({ id: x.source_id, label: x.name && x.name !== x.path ? `${x.name} (${x.path})` : x.path });
  return out;
});
const canStart = computed(() => !busy.value && !!info.value && !info.value.no_disc && pickedCount.value > 0
  && (!!destPath.value || dests.value.length > 0));

function releaseLabel(r) {
  const bits = [r.date, r.country, [r.label, r.catno].filter(Boolean).join(' ')];
  if (Number(r.disc_count) > 1) bits.push(t('settings.cdRip.ripDisc', { n: r.disc_position, total: r.disc_count }));
  return [r.title, bits.filter(Boolean).join(' · ')].filter(Boolean).join(' — ');
}

function stopPoll() { if (timer) { clearInterval(timer); timer = null; } }
async function pollStatus() {
  const r = await api.cdRipStatus();
  if (!r.ok || !r.data) return;
  const was = running.value;
  status.value = r.data;
  if (!running.value) {
    stopPoll();
    if (was) emit('changed');
  }
}
function startPoll() { stopPoll(); pollStatus(); timer = setInterval(pollStatus, 2000); }
onBeforeUnmount(stopPoll);

async function readDisc(rel = '') {
  loading.value = true;
  try {
    const r = await api.cdInfo(rel);
    if (!r.ok || !r.data) { emit('say', (r.data && r.data.message) || t('common.error'), true); return; }
    const d = r.data;
    info.value = d;
    if (d.no_disc) return;
    artist.value = d.artist || '';
    album.value = d.album || '';
    titles.value = (d.tracks || []).map((x) => x.title || '');
    const n = (d.tracks || []).map((x, i) => Number(x.num || i + 1));
    // another edition of the same disc keeps the ticks; a new disc gets them all
    if (n.join() !== nums.value.join()) { nums.value = n; pickAll(true); }
    release.value = d.mbid || '';
    dest.value = dests.value.length ? dests.value[0].id : '';
    if (d.ripping) startPoll();
  } finally { loading.value = false; }
}

async function toggle() {
  if (open.value) { open.value = false; stopPoll(); return; }
  open.value = true;
  picking.value = false;
  destPath.value = '';
  status.value = null;
  if (props.ripping) { startPoll(); return; }
  await readDisc();
}
watch(release, (v, old) => { if (old && v && v !== old && info.value && v !== info.value.mbid) readDisc(v); });

async function start() {
  const selected = nums.value.filter((_, i) => picked.value[i]);
  const body = { artist: artist.value, album: album.value, tracks: titles.value, selected };
  if (destPath.value) body.target = destPath.value;
  else body.source_id = dest.value;
  if (release.value) body.release = release.value;
  busy.value = true;
  try {
    const r = await api.cdRip(body);
    if (!r.ok || (r.data && r.data.success === false)) {
      emit('say', (r.data && r.data.message) || t('settings.cdRip.ripFailed'), true);
      return;
    }
    status.value = { state: 'starting', track: 0, total: selected.length, progress: 0, message: '' };
    emit('changed');
    startPoll();
  } finally { busy.value = false; }
}
async function cancel() {
  busy.value = true;
  try {
    const r = await api.cdCancel();
    const ok = r.ok && r.data.success !== false;
    emit('say', (r.data && r.data.message) || (ok ? t('settings.cdRip.cancelled') : t('settings.cdRip.cancelFailed')), !ok);
    pollStatus();
  } finally { busy.value = false; }
}
async function eject() {
  busy.value = true;
  try {
    const r = await api.cdEject();
    const ok = r.ok && r.data.success !== false;
    emit('say', (r.data && r.data.message) || (ok ? t('settings.cdRip.ejected') : t('settings.cdRip.ejectFailed')), !ok);
    if (ok) { info.value = { no_disc: true }; status.value = null; }
  } finally { busy.value = false; }
}
function pickFolder(p) { destPath.value = p; picking.value = false; }
</script>

<template>
  <div class="riprow">
    <button class="fit" :class="{ secondary: open }" :disabled="!enabled && !ripping" @click="toggle">
      {{ open ? t('common.close') : (ripping ? t('settings.cdRip.ripOpen') : t('settings.cdRip.ripNow')) }}
    </button>
    <p class="muted" v-if="!open">{{ enabled || ripping ? t('settings.cdRip.ripNowHelp') : t('settings.cdRip.ripNowDisabled') }}</p>

    <div v-if="open" class="ripbox">
      <!-- a rip running or just ended -->
      <template v-if="status && status.state !== 'idle'">
        <template v-if="running">
          <!-- the worker's own line already names the track ("Traccia 2/12: …") -->
          <p class="sub">{{ status.message || (status.total ? t('settings.cdRip.ripTrack', { track: status.track || 0, total: status.total }) : t('settings.cdRip.ripStarting')) }}</p>
          <div class="ripbar"><i :style="{ width: Math.max(0, Math.min(100, status.progress || 0)) + '%' }"></i></div>
          <button class="secondary fit" :disabled="busy" @click="cancel">{{ t('settings.cdRip.cancelRip') }}</button>
        </template>
        <template v-else-if="ended">
          <p :class="status.state === 'done' ? 'ok' : status.state === 'error' ? 'bad' : 'muted'">
            {{ status.state === 'done' ? t('settings.cdRip.ripDone') : status.state === 'cancelled' ? t('settings.cdRip.cancelled') : t('settings.cdRip.ripFailed') }}
          </p>
          <!-- what was copied, or why it failed -->
          <p class="muted" v-if="status.message && status.state !== 'cancelled'">{{ status.message }}</p>
          <div class="row" style="flex-wrap: wrap;">
            <button class="fit" :disabled="busy" @click="eject">{{ t('settings.cdRip.ejectNow') }}</button>
            <button class="secondary fit" :disabled="busy || loading" @click="status = null; readDisc()">{{ t('settings.cdRip.ripReadAgain') }}</button>
          </div>
        </template>
      </template>

      <p class="muted" v-else-if="loading">{{ t('settings.cdRip.ripReading') }}</p>

      <template v-else-if="info && info.no_disc">
        <p class="muted">{{ t('settings.cdRip.ripNoDisc') }}</p>
        <button class="secondary fit" @click="readDisc()">{{ t('settings.cdRip.ripReadAgain') }}</button>
      </template>

      <!-- the disc: titles, edition, destination, start -->
      <template v-else-if="info">
        <div class="row" style="flex-wrap: wrap;">
          <input v-model="artist" :placeholder="t('settings.cdRip.ripArtist')" style="flex: 1 1 200px;" />
          <input v-model="album" :placeholder="t('settings.cdRip.ripAlbum')" style="flex: 1 1 200px;" />
        </div>
        <template v-if="(info.releases || []).length > 1">
          <label>{{ t('settings.cdRip.ripEdition') }}</label>
          <select v-model="release" :disabled="loading">
            <option v-for="r in info.releases" :key="r.mbid" :value="r.mbid">{{ releaseLabel(r) }}</option>
          </select>
        </template>
        <div class="pickhead">
          <label>{{ t('settings.cdRip.ripTracks') }} · {{ t('settings.cdRip.ripPicked', { n: pickedCount, total: titles.length }) }}</label>
          <button class="ghost fit" @click="pickAll(!allPicked)">{{ allPicked ? t('settings.cdRip.ripPickNone') : t('settings.cdRip.ripPickAll') }}</button>
        </div>
        <ul class="riptracks">
          <li v-for="(_, i) in titles" :key="i" :class="{ off: !picked[i] }">
            <input type="checkbox" v-model="picked[i]" :aria-label="t('settings.cdRip.ripPickTrack', { n: nums[i] })" />
            <span class="num">{{ nums[i] }}</span>
            <input v-model="titles[i]" :disabled="!picked[i]" />
          </li>
        </ul>

        <label>{{ t('settings.cdRip.ripDestination') }}</label>
        <p class="muted" v-if="!dests.length && !destPath">{{ t('settings.cdRip.ripNoDestination') }}</p>
        <div class="row" style="flex-wrap: wrap; align-items: center;">
          <span v-if="destPath" class="muted" style="word-break: break-all; flex: 1 1 220px;">{{ destPath }}</span>
          <select v-else-if="dests.length" v-model="dest" style="flex: 1 1 220px;">
            <option v-for="d in dests" :key="d.id" :value="d.id">{{ d.label }}</option>
          </select>
          <button class="secondary fit" @click="picking = !picking">{{ picking ? t('common.close') : t('settings.cdRip.ripPickFolder') }}</button>
          <button class="secondary fit" v-if="destPath" @click="destPath = ''">{{ t('settings.cdRip.targetClear') }}</button>
        </div>
        <FolderPicker v-if="picking" :start-at="destPath || (info.default_target && info.default_target.path) || ''" :pick-label="t('settings.cdRip.targetUse')" @pick="pickFolder" @error="(m) => emit('say', m, true)" />

        <div class="row" style="margin-top: 14px; flex-wrap: wrap;">
          <button class="fit" :disabled="!canStart" @click="start">{{ t('settings.cdRip.ripStart') }}</button>
          <button class="secondary fit" :disabled="busy" @click="eject">{{ t('settings.cdRip.ejectNow') }}</button>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.riprow { margin-bottom: 18px; }
.ripbox { margin-top: 12px; padding: 14px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }
.ripbar { width: 100%; height: 8px; background: var(--panel); border-radius: 99px; overflow: hidden; margin: 12px 0; }
.ripbar i { display: block; height: 100%; background: var(--gold); transition: width .4s; }
.pickhead { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.riptracks { list-style: none; margin: 6px 0 0; padding: 0; max-height: 320px; overflow-y: auto; }
.riptracks li { display: flex; align-items: center; gap: 8px; margin: 4px 0; color: var(--muted); }
.riptracks li.off input:not([type=checkbox]) { opacity: .45; }
.riptracks input[type=checkbox] { width: 20px; height: 20px; flex: none; accent-color: var(--gold); margin: 0; }
.riptracks .num { width: 22px; text-align: right; flex: none; font-variant-numeric: tabular-nums; }
.riptracks input:not([type=checkbox]) { flex: 1; min-width: 0; }
.ok { color: var(--ok); }
.bad { color: var(--danger); }
select { max-width: 100%; }
</style>
