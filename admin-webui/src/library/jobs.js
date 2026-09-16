// A background tag job (a save or an undo), followed until it ends:
// GET /api/library/job?id= once a second.
import { ref, onBeforeUnmount } from 'vue';
import { lib, errorText } from './libraryApi.js';

// A 409 from /album/tags or /undo says why in its `code`: "busy" when another
// job is still running, "changed" when a file was changed after the edit (an
// undo would overwrite that change, and only that one can be forced).
function code409(r) {
  return r && r.status === 409 ? String((r.data && r.data.code) || '') : null;
}
export function isBusy(r) {
  const c = code409(r);
  return c !== null && /busy/i.test(c);
}
export function isChangedSince(r) {
  const c = code409(r);
  return c !== null && /changed/i.test(c);
}

export function useJob() {
  const job = ref(null);          // {job_id, state, done, total, errors, rescan, undoable}
  let timer = null;
  let alive = true;

  function stop() {
    if (timer) clearTimeout(timer);
    timer = null;
  }
  async function poll(id) {
    const r = await lib.job(id);
    if (!alive) return;
    if (r.ok && r.data && r.data.job_id) {
      job.value = { errors: [], ...r.data };
    } else if (r.status === 404 || r.status === 400) {
      job.value = { ...(job.value || {}), job_id: id, state: 'error', errors: [], message: errorText(r) };
    }
    // a network blip keeps polling: the job goes on on the device regardless
    if (!job.value || job.value.state === 'running' || job.value.state === 'queued' || !job.value.state) {
      timer = setTimeout(() => poll(id), 1000);
    } else if (job.value.follow === 'waiting') {
      // the album or its artist changed: the device waits for Lyrion's rescan
      // to find the album the files are in now (new_album_id)
      timer = setTimeout(() => poll(id), 2000);
    }
  }
  function follow(id, total = 0) {
    stop();
    job.value = { job_id: id, state: 'running', done: 0, total, errors: [] };
    timer = setTimeout(() => poll(id), 400);
  }
  onBeforeUnmount(() => { alive = false; stop(); });
  return { job, follow, stop };
}
