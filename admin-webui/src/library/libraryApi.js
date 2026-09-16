// The Library editor's calls. Everything goes through webui_server with the
// session as the gate: /api/system/library/* reaches sources_server's
// /api/library/* (the tags inside the files, hifi_tags.py) and
// /api/system/meta/* its /api/meta/* (the online credits, hifi_metadata.py).
import { api } from '../api.js';
import { useI18n } from '../i18n';

const { t } = useI18n();
const enc = encodeURIComponent;

// The admin lives next to this page: /library -> ./ is the admin's root.
export function goToAdmin(hash = '#/') {
  window.location.replace('./' + hash);
}

// A session that expires while the page is open: back to the login form,
// like the admin does on its next navigation.
async function call(p) {
  const r = await p;
  if (r.status === 401) goToAdmin('#/login');
  return r;
}
const get = (path) => call(api.get(path));
const post = (path, body) => call(api.post(path, body));

// The message to show for a failed call: the server's own (already in the
// page's language, see X-UI-Lang in api.js) or a generic one.
export function errorText(r) {
  const d = (r && r.data) || {};
  return d.message || (r && r.status === 0 ? t('common.networkError') : t('library.errors.generic'));
}
// A reply that is an error even with HTTP 200 (the metadata service answers
// `{status: "error"}` with 200 for an unknown album).
export function failed(r) {
  return !r.ok || !r.data || r.data.success === false;
}

export const lib = {
  // ── Part 1: tags inside the files ──
  status: () => get('/api/system/library/status'),
  albums: (q = '', offset = 0, limit = 60) =>
    get(`/api/system/library/albums?q=${enc(q)}&offset=${offset}&limit=${limit}`),
  // Not in the first draft of the contract: the albums of one artist
  // (Lyrion `albums artist_id:`), for the artist page.
  artistAlbums: (artistId, offset = 0, limit = 200) =>
    get(`/api/system/library/albums?artist_id=${enc(artistId)}&offset=${offset}&limit=${limit}`),
  artists: (q = '', offset = 0, limit = 100) =>
    get(`/api/system/library/artists?q=${enc(q)}&offset=${offset}&limit=${limit}`),
  coverUrl: (trackId, size = 300) => `/api/system/library/cover/${enc(trackId)}?size=${size}`,
  album: (albumId) => get('/api/system/library/album?album_id=' + enc(albumId)),
  saveTags: (albumId, changes) => post('/api/system/library/album/tags', { album_id: Number(albumId), changes }),
  job: (id) => get('/api/system/library/job?id=' + enc(id)),
  history: () => get('/api/system/library/history'),
  undo: (jobId, force = false) =>
    post('/api/system/library/undo', force ? { job_id: jobId, force: true } : { job_id: jobId }),

  // ── Part 2: corrections to the online information ──
  albumEdit: (albumId) => get('/api/system/meta/album/edit?album_id=' + enc(albumId)),
  albumEditSave: (albumId, overrides) =>
    post('/api/system/meta/album/edit', { album_id: Number(albumId), overrides }),
  albumCandidates: (albumId) => get('/api/system/meta/album/candidates?album_id=' + enc(albumId)),
  // mbid: a MusicBrainz release id, "none" (no match) or null (automatic)
  albumPin: (albumId, mbid) => post('/api/system/meta/album/pin', { album_id: Number(albumId), mbid }),
  artistEdit: (artistId) => get('/api/system/meta/artist/edit?artist_id=' + enc(artistId)),
  artistEditSave: (artistId, overrides) =>
    post('/api/system/meta/artist/edit', { artist_id: Number(artistId), overrides }),
  artistCandidates: (artistId) => get('/api/system/meta/artist/candidates?artist_id=' + enc(artistId)),
  artistPin: (artistId, mbid) => post('/api/system/meta/artist/pin', { artist_id: Number(artistId), mbid }),
  searchPeople: (q) => get('/api/system/meta/search/people?q=' + enc(q)),
};
