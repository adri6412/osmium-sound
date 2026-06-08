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

  async getPlayerStatus(playerMac) {
    return this.request(playerMac, ['status', '-', 1, 'tags:aAbcCdeEfFgGhHijklLmoOpPqQrRsStTuvVwxXyYz']);
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
