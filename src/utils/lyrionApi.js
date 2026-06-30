/**
 * Lyrion Media Server (LMS) API Client
 * Uses JSON-RPC over HTTP
 */

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

    try {
      const response = await fetch(this.rpcUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      return data.result;
    } catch (error) {
      console.error('Lyrion API Error:', error);
      throw error;
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
    // (The old request asked for every available tag every poll — wasted work
    // on the server for fields the UI never reads.)
    return this.request(playerMac, ['status', '-', 1, 'tags:aldoTIN']);
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
    const params = ['albums', offset, limit, 'tags:alSj'];
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

  async playItem(playerMac, itemType, itemId) {
    // itemType can be 'artist_id', 'album_id', 'track_id', or 'folder_id'
    return this.request(playerMac, ['playlistcontrol', 'cmd:load', `${itemType}:${itemId}`]);
  }

  getArtworkUrl(trackId, size = 300) {
    if (!trackId) return null;
    return `${this.baseUrl}/music/${trackId}/cover?size=${size}`;
  }
}

// Export a singleton instance
export const lyrionApi = new LyrionAPI();
