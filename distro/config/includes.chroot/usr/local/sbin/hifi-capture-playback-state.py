#!/usr/bin/env python3
"""Quiesce every local player just before shutdown/reboot, while LMS and
squeezelite are still up -- run from hifi-quiesce-audio-shutdown.sh, BEFORE it
stops squeezelite.service.

For each player that lives on this box (the internal squeezelite and every
Bluetooth speaker's own hifi-bt-player, all connecting to Lyrion over
loopback) this:
  - pauses it, so nothing is left mid-track to blare back on the next boot;
  - clears Lyrion's own power-on resume (playingAtPowerOff) for it, so LMS
    does not start it playing again the moment squeezelite reconnects.

The appliance therefore comes back with all its local players paused, which
is the behaviour issue #124 asked for. Players on OTHER devices (a Wi-Fi
speaker, someone else's box) connect from their own address, so they are left
untouched.

Best-effort only: any failure (LMS not reachable, unexpected response shape,
one player not answering) just means that player is left as it was -- never
worth delaying or blocking a shutdown over, and a failure on one player must
not skip the rest.
"""
import json
import os
import urllib.request

LMS_RPC_URL = 'http://127.0.0.1:9000/jsonrpc.js'
# Older builds captured a single player's state here for api_server to resume
# on boot; that scheme is gone (issue #124), so a leftover file is just cleared.
STATE_FILE = '/var/lib/hifi-player/playback-state.json'


def lms_request(playerid, command, timeout=5):
    payload = json.dumps({'id': 1, 'method': 'slim.request', 'params': [playerid, command]}).encode()
    req = urllib.request.Request(LMS_RPC_URL, data=payload, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read()).get('result')


def local_player_ids(players):
    """Every player on this box: the ones connecting to Lyrion over loopback
    (the internal squeezelite and each Bluetooth speaker's hifi-bt-player)."""
    return [p.get('playerid') for p in players
            if str(p.get('ip', '')).startswith('127.0.0.1:') and p.get('playerid')]


def main():
    try:
        result = lms_request('-', ['serverstatus', 0, 999]) or {}
    except Exception:
        return
    for playerid in local_player_ids(result.get('players_loop', [])):
        for command in (['pause', '1'], ['playerpref', 'playingAtPowerOff', '0']):
            try:
                lms_request(playerid, command)
            except Exception:
                pass
    # Drop any state file written by the previous resume-on-boot scheme so an
    # upgraded box can't act on a stale one.
    try:
        os.remove(STATE_FILE)
    except OSError:
        pass


if __name__ == '__main__':
    main()
