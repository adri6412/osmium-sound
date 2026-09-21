<script setup>
// Every save of tags, newest first, and a way to take one back. An undo
// writes the old values again as a new job; if a file was changed after the
// save (by another save, or from a computer), the device refuses unless the
// owner says to go ahead anyway.
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue';
import { useI18n } from '../../i18n';
import Icon from '../../components/Icon.vue';
import Modal from '../components/Modal.vue';
import { lib, errorText } from '../libraryApi.js';
import { useJob, isBusy, isChangedSince } from '../jobs.js';
import { fmtWhen } from '../meta.js';

const { t } = useI18n();
const jobs = ref([]);
const loading = ref(true);
const error = ref('');
const confirmJob = ref(null);     // the entry being undone
const changedSince = ref(null);   // null, or the server's message when it refused
const sending = ref(false);
const actionError = ref('');
const { job, follow } = useJob();
let refresh = null;

async function load() {
  const r = await lib.history();
  loading.value = false;
  if (!r.ok || !r.data) { error.value = errorText(r); return; }
  error.value = '';
  jobs.value = r.data.jobs || [];
  // a job still running: look again shortly
  clearTimeout(refresh);
  if (jobs.value.some((j) => j.state === 'running' || j.state === 'queued')) refresh = setTimeout(load, 2000);
}
onMounted(load);
onBeforeUnmount(() => clearTimeout(refresh));

const byId = computed(() => Object.fromEntries(jobs.value.map((j) => [j.job_id, j])));
function stateText(j) {
  if (j.state === 'running' || j.state === 'queued') return t('library.history.running');
  if (j.state === 'error') return t('library.history.failed');
  if (j.undone) return t('library.history.undone');
  return t('library.history.done');
}
function canUndo(j) {
  return j.state === 'done' && !j.undone && j.undoable !== false;
}

function askUndo(j) {
  confirmJob.value = j;
  changedSince.value = null;
  actionError.value = '';
  job.value = null;
}
async function doUndo(force = false) {
  const j = confirmJob.value;
  if (!j) return;
  sending.value = true;
  actionError.value = '';
  const r = await lib.undo(j.job_id, force);
  sending.value = false;
  if (isChangedSince(r)) { changedSince.value = (r.data && r.data.message) || ''; return; }
  if (isBusy(r)) { actionError.value = (r.data && r.data.message) || t('library.tags.busy'); return; }
  if (!r.ok || !r.data || !r.data.job_id) { actionError.value = errorText(r); return; }
  changedSince.value = null;
  follow(r.data.job_id, j.tracks || 0);
}
const running = computed(() => job.value && (job.value.state === 'running' || job.value.state === 'queued'));
watch(running, (v, was) => { if (was && !v) load(); });
function close() {
  if (running.value) return;
  confirmJob.value = null;
  job.value = null;
  load();
}
</script>

<template>
  <RouterLink to="/" class="backlink"><Icon name="chevron-left" :size="16" />{{ t('library.album.back') }}</RouterLink>
  <h2 class="page">{{ t('library.history.title') }}</h2>
  <p class="muted lb-lead">{{ t('library.history.lead') }}</p>

  <div class="msg err" v-if="error">{{ error }}</div>
  <p class="lb-empty" v-if="loading">{{ t('common.loading') }}</p>
  <p class="lb-empty" v-else-if="!jobs.length && !error">{{ t('library.history.empty') }}</p>

  <div class="card lb-list" v-if="jobs.length">
    <div class="lb-hist" v-for="j in jobs" :key="j.job_id" :class="{ undone: j.undone }">
      <Icon :name="j.undo_of ? 'undo-2' : 'tag'" :size="18" class="gold" />
      <div class="lb-hist-tx">
        <div>
          <RouterLink v-if="j.album_id" :to="'/album/' + j.album_id">{{ j.album || t('library.history.album') }}</RouterLink>
          <span v-else>{{ j.album || t('library.history.album') }}</span>
        </div>
        <div class="muted">
          {{ fmtWhen(j.when) }} ·
          {{ j.undo_of ? t('library.history.undoOf', { when: byId[j.undo_of] ? fmtWhen(byId[j.undo_of].when) : '' }) : (j.tracks === 1 ? t('library.history.oneFile') : t('library.history.nFiles', { n: j.tracks || 0 })) }}
          · <span :class="{ bad: j.state === 'error' }">{{ stateText(j) }}</span>
        </div>
      </div>
      <button v-if="canUndo(j)" type="button" class="ghost fit lb-hist-btn" @click="askUndo(j)">
        <Icon name="undo-2" :size="15" /><span>{{ t('library.history.undo') }}</span>
      </button>
    </div>
  </div>

  <Modal v-if="confirmJob" :title="t('library.history.undoTitle')" :locked="running || sending" @close="close">
    <template v-if="!job">
      <p class="sub">{{ t('library.history.undoLead', { album: confirmJob.album || '', when: fmtWhen(confirmJob.when) }) }}</p>
      <div class="msg" v-if="changedSince !== null">
        <Icon name="alert-triangle" :size="15" class="gold" /> {{ t('library.history.changedSince') }}
        <template v-if="changedSince"><br /><span class="muted">{{ changedSince }}</span></template>
      </div>
    </template>
    <template v-else>
      <div v-if="running">
        <p class="sub">{{ t('library.tags.progress', { done: job.done || 0, total: job.total || confirmJob.tracks || 0 }) }}</p>
        <div class="fm-prog"><i :style="{ width: (job.total ? Math.round((100 * (job.done || 0)) / job.total) : 0) + '%' }"></i></div>
      </div>
      <template v-else>
        <p class="lb-result" :class="{ bad: job.state === 'error' || (job.errors && job.errors.length) }">
          <Icon :name="job.state === 'done' && !(job.errors && job.errors.length) ? 'check' : 'alert-triangle'" :size="18" />
          <span>{{ job.state === 'done' && !(job.errors && job.errors.length) ? t('library.tags.undoDone') : job.message || t('library.history.undoProblems', { n: (job.errors || []).length }) }}</span>
        </p>
        <ul class="lb-errors" v-if="job.errors && job.errors.length">
          <li v-for="e in job.errors" :key="String(e.track_id) + e.message"><span class="muted">{{ e.message }}</span></li>
        </ul>
        <p class="muted">{{ job.rescan === 'started' ? t('library.tags.rescanStarted') : job.rescan === 'failed' ? t('library.tags.rescanFailed') : t('library.tags.rescanSkipped') }}</p>
      </template>
    </template>
    <div class="msg err" v-if="actionError">{{ actionError }}</div>
    <template #foot>
      <template v-if="!job">
        <button type="button" class="ghost fit" :disabled="sending" @click="close">{{ t('common.cancel') }}</button>
        <button v-if="changedSince !== null" type="button" class="danger fit" :disabled="sending" @click="doUndo(true)">{{ t('library.history.undoAnyway') }}</button>
        <button v-else type="button" class="fit" :disabled="sending" @click="doUndo(false)">{{ t('library.history.undo') }}</button>
      </template>
      <button v-else-if="!running" type="button" class="fit" @click="close">{{ t('common.close') }}</button>
    </template>
  </Modal>
</template>
