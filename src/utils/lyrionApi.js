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

  getArtworkUrl(trackId, size = 300) {
    if (!trackId) return null;
    return `${this.baseUrl}/music/${trackId}/cover.jpg?size=${size}`;
  }
}

// Export a singleton instance
export const lyrionApi = new LyrionAPI();
