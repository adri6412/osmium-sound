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

  async getRadios(limit = 9999, offset = 0) {
    return this.request('', ['radios', offset, limit]);
  }

  async getApps(limit = 9999, offset = 0) {
    return this.request('', ['apps', offset, limit]);
  }

  async getPluginItems(pluginCmd, limit = 9999, offset = 0, itemId = null) {
    const params = [pluginCmd, 'items', offset, limit];
    if (itemId) {
      params.push(`item_id:${itemId}`);
    }
    return this.request('', params);
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
