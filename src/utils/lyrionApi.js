/**
 * Lyrion Media Server (LMS) API Client
 * Uses JSON-RPC over HTTP
 */

// MusicArtistInfo's `biography` command returns an HTML fragment (it's the
// same markup MAI's own web/Jive popup renders), not plain text — a <link>
// tag plus <p>/<b>/<i>/<span> wrapping the prose. We only want the words, and
// parsing it as HTML (rather than executing it) also means we never have to
// trust that markup: DOMParser-produced documents aren't inserted into a
// browsing context, so embedded <script>/<img onerror> etc. never run.
const htmlToText = (html) => {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  doc.querySelectorAll('script, style, link').forEach((el) => el.remove());
  doc.querySelectorAll('p, br, div').forEach((el) => el.append('\n\n'));
  return (doc.body.textContent || '')
    .replace(/[ \t]+/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
};

export class LyrionAPI {
  constructor(baseUrl = 'http://localhost:9000') {
    // Strip trailing slashes and /material/ if present
    this.baseUrl = baseUrl.replace(/\/material\/?$/, '').replace(/\/$/, '');
    this.rpcUrl = `${this.baseUrl}/jsonrpc.js`;
    this.reqId = 0;
  }

  setBaseUrl(url) {
    this.baseUrl = url.replace(/\/material\/?$/, '').replace(/\/$/, '');
    this.rpcUrl = `${this.baseUrl}/jsonrpc.js`;
  }

  async request(playerMac, command) {
    this.reqId++;
    const payload = {
      id: this.reqId,
      method: 'slim.request',
      params: [playerMac, command]
    };

    // Abort after 10s: without a timeout a request that hangs (e.g. LMS
    // momentarily overloaded while CamillaDSP/squeezelite restart on this
    // same small box) never settles, so the caller's failure-counting and
    // reconnect logic in useLyrionPlayer never gets a chance to kick in.
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(this.rpcUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify(payload),
        signal: controller.signal
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      return data.result;
    } catch (error) {
      console.error('Lyrion API Error:', error);
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  // API Methods

  async getServerStatus() {
    return this.request('', ['serverstatus', 0, 999]);
  }

  async getPlayers() {
    const status = await this.getServerStatus();
    return status?.players_loop || [];
  }

  // Kick off a library rescan (server-wide, not per-player). `mode`:
  //  - undefined / 'new'  → scan for new & changed media (incremental, fast)
  //  - 'full'             → clear the DB and rescan everything
  //  - 'playlists'        → rescan playlists only
  async rescanLibrary(mode) {
    return this.request('', mode ? ['rescan', mode] : ['rescan']);
  }

  // Rescan progress. While a scan runs, serverstatus carries `rescan:1` plus
  // `progressdone`/`progresstotal`/`progressname`; when idle `rescan` is absent.
  // Returns { scanning, done, total, name }.
  async getRescanProgress() {
    const s = await this.getServerStatus();
    return {
      scanning: Number(s?.rescan ?? 0) === 1,
      done: Number(s?.progressdone ?? 0),
      total: Number(s?.progresstotal ?? 0),
      name: s?.progressname || '',
    };
  }

  async getPlayerStatus(playerMac) {
    // Only request the song tags the player UI actually renders:
    //   a=artist  l=album  d=duration  o=type  T=samplerate  I=samplesize
    //   N=remote stream title (radio). title/id come back without a tag.
    //   x=remote flag (1 for any non-local source) — needed by useLyrionPlayer
    //   to know when to apply its cover-art cache-busting heartbeat, since
    //   streaming-service "radio" features (Qobuz, Tidal, ...) don't reliably
    //   update N/current_title per song the way classic ICY radio does.
    //   c=coverid — changes when a *local* track's artwork changes even
    //   though its stable db id doesn't (retag, replaced file, rescan
    //   picking different embedded art). getArtworkUrl folds it into the
    //   query string as a cache-buster so the browser's (very long-lived,
    //   no-ETag) HTTP cache for /music/{id}/cover can't get stuck serving a
    //   stale image for that id — see useLyrionPlayer's artworkUrl.
    // Cover art for *remote* tracks doesn't need a tag at all — it's fetched
    // via LMS's own /music/current/cover.jpg?player=... endpoint, which
    // resolves that artwork server-side (see useLyrionPlayer's
    // artworkUrl/artworkUrlLg).
    // (The old request asked for every available tag every poll — wasted work
    // on the server for fields the UI never reads.)
    return this.request(playerMac, ['status', '-', 1, 'tags:aldoTINxc']);
  }

  async play(playerMac) {
    return this.request(playerMac, ['play']);
  }

  async pause(playerMac) {
    return this.request(playerMac, ['pause', '1']);
  }

  async togglePause(playerMac) {
    return this.request(playerMac, ['pause']);
  }

  async stop(playerMac) {
    return this.request(playerMac, ['stop']);
  }

  async next(playerMac) {
    return this.request(playerMac, ['button', 'jump_fwd']);
  }

  async previous(playerMac) {
    return this.request(playerMac, ['button', 'jump_rew']);
  }

  async setVolume(playerMac, volume) {
    return this.request(playerMac, ['mixer', 'volume', volume]);
  }

  async seek(playerMac, time) {
    return this.request(playerMac, ['time', time]);
  }

  async power(playerMac, powerState) {
    // powerState: 0 for off, 1 for on
    return this.request(playerMac, ['power', powerState]);
  }

  // --- Playback modes (shuffle / repeat) ---

  // mode: 0 = off, 1 = song, 2 = all
  async setRepeat(playerMac, mode) {
    return this.request(playerMac, ['playlist', 'repeat', mode]);
  }

  // mode: 0 = off, 1 = songs, 2 = albums
  async setShuffle(playerMac, mode) {
    return this.request(playerMac, ['playlist', 'shuffle', mode]);
  }

  // --- Current play queue (the active playlist) ---

  // Returns the full `status` result; the queue is in `playlist_loop`,
  // current index in `playlist_cur_index`.
  async getQueue(playerMac, limit = 999) {
    return this.request(playerMac, ['status', 0, limit, 'tags:acdltK']);
  }

  // Jump to a queue position and start playing it.
  async playlistJump(playerMac, index) {
    return this.request(playerMac, ['playlist', 'index', index]);
  }

  async playlistMove(playerMac, fromIndex, toIndex) {
    return this.request(playerMac, ['playlist', 'move', fromIndex, toIndex]);
  }

  async playlistRemove(playerMac, index) {
    return this.request(playerMac, ['playlist', 'delete', index]);
  }

  async playlistClear(playerMac) {
    return this.request(playerMac, ['playlist', 'clear']);
  }

  async playlistSave(playerMac, name) {
    return this.request(playerMac, ['playlist', 'save', name]);
  }

  // --- Sleep timer ---

  // seconds: 0 cancels the timer. Status exposes `will_sleep_in` while active.
  async setSleep(playerMac, seconds) {
    return this.request(playerMac, ['sleep', seconds]);
  }

  // --- Alarm clock ---

  async getAlarms(playerMac, limit = 99) {
    return this.request(playerMac, ['alarms', 0, limit, 'filter:all']);
  }

  // params: { time (seconds since midnight), dow ("0,1,2…" 0=Sun), enabled (0|1) }
  async addAlarm(playerMac, { time, dow = '0,1,2,3,4,5,6', enabled = 1 } = {}) {
    return this.request(playerMac, ['alarm', 'add', `time:${time}`, `dow:${dow}`, `enabled:${enabled}`]);
  }

  // updates: object of key/values (e.g. { enabled: 0, time: 28800 })
  async updateAlarm(playerMac, alarmId, updates = {}) {
    const params = Object.entries(updates).map(([k, v]) => `${k}:${v}`);
    return this.request(playerMac, ['alarm', 'update', `id:${alarmId}`, ...params]);
  }

  async deleteAlarm(playerMac, alarmId) {
    return this.request(playerMac, ['alarm', 'delete', `id:${alarmId}`]);
  }

  // --- Lyrics (via the MusicArtistInfo plugin) ---

  // Returns the lyrics text, or null if the plugin isn't installed, the track
  // has none, or the request fails. `trackId` is preferred (exact match); falls
  // back to artist/title when unavailable (e.g. radio streams).
  async getLyrics(playerMac, { trackId, artist, title } = {}) {
    const params = [];
    if (trackId) params.push(`track_id:${trackId}`);
    else {
      if (artist) params.push(`artist:${artist}`);
      if (title) params.push(`title:${title}`);
    }
    if (!params.length) return null;
    try {
      const r = await this.request(playerMac, ['musicartistinfo', 'lyrics', ...params]);
      const text = r?.lyrics;
      return typeof text === 'string' && text.trim() ? text : null;
    } catch (_) {
      return null;
    }
  }

  // --- Discovery (Don't Stop The Music / Random Mix / MusicArtistInfo) ---

  // DSTM per-player provider ('' = off). Returns null when the plugin isn't
  // installed (pref unreadable) so the UI can hide the toggle entirely.
  async getDstmProvider(playerMac) {
    try {
      return await this.getPlayerPref(playerMac, 'plugin.dontstopthemusic:provider');
    } catch (_) {
      return null;
    }
  }

  async setDstmProvider(playerMac, provider) {
    return this.setPlayerPref(playerMac, 'plugin.dontstopthemusic:provider', provider || '');
  }

  // Random Mix (bundled LMS plugin): start an endless random mix.
  // mode: 'tracks' | 'albums' | 'contributors' | 'year'
  async randomPlay(playerMac, mode = 'tracks') {
    return this.request(playerMac, ['randomplay', mode]);
  }

  // --- Random Mix genre filtering ---
  // Genre inclusion is a single state per player, not scoped to a mix mode:
  // whichever genres are enabled here apply to the next randomPlay() call
  // regardless of mode ('tracks'/'albums'/'contributors').

  // All known genres with current include/exclude state. The raw response is
  // a Jive-formatted menu (like getHomeMenu()) whose first two rows are
  // "select all"/"select none" convenience entries with no `checkbox` field —
  // filtered out so callers only see real genres.
  async getRandomPlayGenres(playerMac) {
    const r = await this.request(playerMac, ['randomplaygenrelist', 0, 999]);
    const loop = r?.item_loop || [];
    return loop
      .filter((it) => typeof it.checkbox !== 'undefined')
      .map((it) => ({ name: it.text, included: Number(it.checkbox) === 1 }));
  }

  // Toggle a single genre on/off for future Random Mixes.
  async setRandomPlayGenre(playerMac, genreName, included) {
    return this.request(playerMac, ['randomplaychoosegenre', genreName, included ? 1 : 0]);
  }

  // Select/deselect every genre in one call.
  async setAllRandomPlayGenres(playerMac, included) {
    return this.request(playerMac, ['randomplaygenreselectall', included ? 1 : 0]);
  }

  // Apply an exact genre subset: clear everything, then enable just
  // `genreNames`. Used to apply a saved genre preset.
  async applyRandomPlayGenreSet(playerMac, genreNames) {
    await this.setAllRandomPlayGenres(playerMac, false);
    await Promise.all(genreNames.map((name) => this.setRandomPlayGenre(playerMac, name, true)));
  }

  // Artist biography via MusicArtistInfo (same plugin the lyrics use).
  // Returns text or null (plugin missing / nothing found).
  async getArtistBio(playerMac, artist) {
    if (!artist) return null;
    try {
      const r = await this.request(playerMac, ['musicartistinfo', 'biography', `artist:${artist}`]);
      const raw = r?.biography;
      if (typeof raw !== 'string' || !raw.trim()) return null;
      const text = htmlToText(raw);
      return text || null;
    } catch (_) {
      return null;
    }
  }

  // Similar artists via MusicArtistInfo. Not every MAI version exposes this
  // command — degrade to an empty list so the UI hides the section.
  async getSimilarArtists(playerMac, artist) {
    if (!artist) return [];
    try {
      const r = await this.request(playerMac, ['musicartistinfo', 'similarartists', `artist:${artist}`]);
      const loop = r?.item_loop || r?.similarartists_loop || [];
      return loop
        .map((it) => (typeof it === 'string' ? it : (it.artist || it.name || it.text || '')))
        .filter(Boolean);
    } catch (_) {
      return [];
    }
  }

  // --- Multiroom / synchronised zones ---
  // LMS syncs multiple players natively: a sync group has one master and any
  // number of slaves that all play the master's queue in lock-step.

  // Make `playerMac` join the group that contains `targetMac` (targetMac stays
  // master). `<player> sync <other>` is the native LMS command.
  async syncPlayer(playerMac, targetMac) {
    return this.request(playerMac, ['sync', targetMac]);
  }

  // Remove `playerMac` from its sync group.
  async unsyncPlayer(playerMac) {
    return this.request(playerMac, ['sync', '-']);
  }

  // Sync state of a player, read from its `status` (sync_master / sync_slaves are
  // top-level fields, independent of the requested tags). Returns
  // { master, slaves: [] } — `slaves` are the macs following this player.
  async getPlayerSync(playerMac) {
    const r = await this.request(playerMac, ['status', '-', 1]);
    return {
      master: r?.sync_master ?? null,
      slaves: r?.sync_slaves ? String(r.sync_slaves).split(',').filter(Boolean) : [],
    };
  }

  // --- Per-player preferences (transition / ReplayGain / …) ---

  // Returns the raw value (string) of a player preference, or null.
  // Lyrion returns the queried value under `_p2` (and sometimes under the
  // pref name itself), so fall back across both.
  async getPlayerPref(playerMac, pref) {
    const r = await this.request(playerMac, ['playerpref', pref, '?']);
    return r?._p2 ?? r?.[pref] ?? null;
  }

  async setPlayerPref(playerMac, pref, value) {
    return this.request(playerMac, ['playerpref', pref, value]);
  }

  // --- Library Browsing Methods ---

  async getArtists(limit = 9999, offset = 0) {
    return this.request('', ['artists', offset, limit, 'tags:s']);
  }

  async getAlbums(limit = 9999, offset = 0, artistId = null) {
    // j=artwork_track_id (which track's embedded art represents the album)
    // c=coverid of that art, for the same cache-busting reason as
    // getPlayerStatus above — the album grid builds its cover URL from
    // artwork_track_id, which is just as stable-but-stale-prone as a track id.
    const params = ['albums', offset, limit, 'tags:alSjc'];
    if (artistId) {
      params.push(`artist_id:${artistId}`);
    }
    return this.request('', params);
  }

  async getTracks(limit = 9999, offset = 0, albumId = null) {
    const params = ['titles', offset, limit, 'tags:aAlcdtu'];
    if (albumId) {
      params.push(`album_id:${albumId}`);
    }
    return this.request('', params);
  }

  async getMusicFolders(folderId = null, limit = 9999, offset = 0) {
    const params = ['musicfolder', offset, limit, 'tags:u'];
    if (folderId) {
      params.push(`folder_id:${folderId}`);
    }
    return this.request('', params);
  }

  // Saved playlists (the ones the user stores from the queue). Each item in
  // `playlists_loop` carries `id` and `playlist` (the name).
  async getPlaylists(limit = 9999, offset = 0) {
    return this.request('', ['playlists', offset, limit]);
  }

  // Tracks of a saved playlist → `playlisttracks_loop`.
  async getPlaylistTracks(playlistId, limit = 9999, offset = 0) {
    return this.request('', ['playlists', 'tracks', offset, limit, `playlist_id:${playlistId}`, 'tags:aAlcdtu']);
  }


  // --- Plugins (Apps, Radios) Methods ---

  async getRadios(playerMac = '', limit = 9999, offset = 0) {
    return this.request(playerMac, ['radios', offset, limit]);
  }

  async getApps(playerMac = '', limit = 9999, offset = 0) {
    return this.request(playerMac, ['apps', offset, limit]);
  }

  // --- Home menu (the "My Apps"/home node tree, like Material/the LMS app) ---
  // This is what actually exposes installed plugins (Spotty, Favourites, CD,
  // YouTube, Radio…). Each item carries `actions.go/.play/.do` to drive it.

  async getHomeMenu(playerMac = '') {
    const r = await this.request(playerMac, ['menu', 0, 999, 'direct:1']);
    return r?.item_loop || [];
  }

  // Turn a menu action ({cmd, params, …}) into a slim.request command array.
  // Browse commands ending in "items" take <offset> <limit>; others don't.
  // `__TAGGEDINPUT__` / `__INPUT__` placeholders are replaced with user text.
  _actionToRequest(action, { offset = 0, limit = 200, input } = {}) {
    const cmd = [...(action.cmd || [])];
    const params = Object.entries(action.params || {}).map(([k, v]) => {
      let val = v;
      if (val === '__TAGGEDINPUT__' || val === '__INPUT__') val = input ?? '';
      return `${k}:${val}`;
    });
    const isItems = cmd[cmd.length - 1] === 'items';
    return isItems ? [...cmd, offset, limit, ...params] : [...cmd, ...params];
  }

  // Navigate into a menu node — returns its child items plus the response `base`.
  // In the Lyrion "menu" protocol, child items often DON'T carry their own
  // `actions`; they inherit `base.actions` and only supply `params` (e.g.
  // item_id). Callers must resolve actions with resolveMenuAction(base, item).
  async menuGo(playerMac = '', action, opts = {}) {
    const r = await this.request(playerMac, this._actionToRequest(action, opts));
    return { items: r?.item_loop || [], base: r?.base || null };
  }

  // Execute a playback / toggle action (actions.play / actions.do / actions.add).
  async menuDo(playerMac = '', action, opts = {}) {
    return this.request(playerMac, this._actionToRequest(action, opts));
  }

  // Resolve the effective action for a menu item, merging the response `base`
  // with the item's own data (the Jive base+item model). `name` is
  // 'go' | 'play' | 'add' | 'do'. Returns { cmd, params } or null.
  resolveMenuAction(base, item, name) {
    const itemAction = item.actions && item.actions[name];
    const baseAction = base && base.actions && base.actions[name];
    const action = itemAction || baseAction;
    if (!action || !action.cmd) return null;
    let params = { ...(action.params || {}) };
    // `itemsParams` names the item key (usually "params") whose key/values get
    // merged into the action's params. Fall back to item.params when using base.
    const ip = action.itemsParams;
    if (ip && item[ip]) params = { ...params, ...item[ip] };
    else if (!itemAction && item.params) params = { ...params, ...item.params };
    return { cmd: [...action.cmd], params };
  }

  async getPluginItems(playerMac = '', pluginCmd, limit = 9999, offset = 0, itemId = null) {
    const params = [pluginCmd, 'items', offset, limit];
    if (itemId) {
      params.push(`item_id:${itemId}`);
    }
    return this.request(playerMac, params);
  }

  async playPluginItem(playerMac, pluginCmd, itemId) {
    return this.request(playerMac, [pluginCmd, 'playlist', 'play', `item_id:${itemId}`]);
  }

  // --- Playback Commands ---

  // mode: 'load' (default, replaces the queue and plays), 'add' (append to
  // queue), 'insert' (play next).
  async playItem(playerMac, itemType, itemId, mode = 'load') {
    // itemType can be 'artist_id', 'album_id', 'track_id', or 'folder_id'
    return this.request(playerMac, ['playlistcontrol', `cmd:${mode}`, `${itemType}:${itemId}`]);
  }

  // coverid is optional and purely a cache-buster: LMS resolves the image
  // from trackId alone regardless, but its response has a very long
  // Cache-Control and no ETag/Last-Modified, so the browser can never
  // revalidate on its own — folding coverid into the query string is what
  // makes the URL actually change when the art behind trackId does.
  getArtworkUrl(trackId, size = 300, coverid = null) {
    if (!trackId) return null;
    const url = `${this.baseUrl}/music/${trackId}/cover?size=${size}`;
    return coverid ? `${url}&coverid=${encodeURIComponent(coverid)}` : url;
  }
}

// Export a singleton instance
export const lyrionApi = new LyrionAPI();
