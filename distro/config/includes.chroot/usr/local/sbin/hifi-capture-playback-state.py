#!/usr/bin/env python3
"""Capture the local squeezelite player's current playback state to
PLAYBACK_STATE_FILE just before shutdown/reboot, while LMS and squeezelite
are still up — run from hifi-quiesce-audio-shutdown.sh, BEFORE it stops
squeezelite.service.

api_server.py reads this file once at its own next startup
(_resume_playback_after_boot) to restore playback to wherever it left off:
resume playing at the same track/position if it was playing, load the same
track paused at that position if it was paused, or do nothing if it was
stopped. LMS's own native playingAtPowerOff/positionAtDisconnect prefs are
not relied on for this — they exist, but this codebase already found them
unreliable for a near-identical case (see api_server.py's _local_playing_player
docstring) and they're debounced to a 10s autosave that a fast power-off can
miss entirely; capturing explicitly here, synchronously, before shutdown
proceeds, avoids both problems.

Best-effort only: any failure (LMS not reachable, unexpected response shape)
just means nothing gets captured — the appliance simply won't resume on next
boot, same as today. Never worth delaying/blocking a shutdown over.
"""
import json
import os
import urllib.request

LMS_RPC_URL = 'http://127.0.0.1:9000/jsonrpc.js'
STATE_FILE = '/var/lib/hifi-player/playback-state.json'


def lms_request(playerid, command, timeout=5):
    payload = json.dumps({'id': 1, 'method': 'slim.request', 'params': [playerid, command]}).encode()
    req = urllib.request.Request(LMS_RPC_URL, data=payload, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read()).get('result')


def main():
    try:
        result = lms_request('-', ['serverstatus', 0, 999]) or {}
    except Exception:
        return
    playerid = None
    for p in result.get('players_loop', []):
        # This device's own squeezelite always connects to LMS over loopback,
        # regardless of multiroom sync membership with other players.
        if str(p.get('ip', '')).startswith('127.0.0.1:'):
            playerid = p.get('playerid')
            break
    if not playerid:
        return
    try:
        st = lms_request(playerid, ['status', '-', 1]) or {}
    except Exception:
        return
    mode = st.get('mode')
    if mode not in ('play', 'pause', 'stop'):
        return
    try:
        elapsed = float(st.get('time') or 0.0)
    except (TypeError, ValueError):
        elapsed = 0.0
    try:
        index = int(st.get('playlist_cur_index') or 0)
    except (TypeError, ValueError):
        index = 0
    state = {'playerid': playerid, 'mode': mode, 'time': elapsed, 'playlist_cur_index': index}
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f)
    os.replace(tmp, STATE_FILE)


if __name__ == '__main__':
    main()
