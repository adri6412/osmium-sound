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
import hashlib
import json
import os
import sys
import urllib.request

LMS_RPC_URL = 'http://127.0.0.1:9000/jsonrpc.js'
STATE_FILE = '/var/lib/hifi-player/playback-state.json'
BT_STATE_FILE = '/etc/hifi-player/bluetooth.json'
MACHINE_ID = '/etc/machine-id'
# hifi_squeezelite.py lives next to the other Python daemons.
SQ_MODULE_DIR = '/usr/local/bin'


def lms_request(playerid, command, timeout=5):
    payload = json.dumps({'id': 1, 'method': 'slim.request', 'params': [playerid, command]}).encode()
    req = urllib.request.Request(LMS_RPC_URL, data=payload, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read()).get('result')


def own_player_mac():
    """The MAC this box's squeezelite runs with (`-m`), lower case, or ''."""
    try:
        if SQ_MODULE_DIR not in sys.path:
            sys.path.insert(0, SQ_MODULE_DIR)
        import hifi_squeezelite
        model, _ = hifi_squeezelite.load()
        return str(model.get('mac') or '').strip().lower()
    except Exception:
        return ''


def bt_player_ids():
    """The player ids of the Bluetooth speakers' own squeezelites (same
    derivation as api_server._bt_player_mac), lower case."""
    try:
        with open(BT_STATE_FILE) as f:
            speakers = json.load(f).get('speakers') or []
        try:
            with open(MACHINE_ID) as f:
                seed = f.read().strip()
        except OSError:
            seed = os.uname().nodename
        out = set()
        for s in speakers:
            mac = str(s.get('mac') or '').upper()
            if not mac:
                continue
            b = bytearray(hashlib.sha256((seed + '|' + mac).encode()).digest()[:6])
            b[0] = (b[0] & 0xFE) | 0x02
            out.add(':'.join('%02x' % x for x in b))
        return out
    except Exception:
        return set()


def own_player_id(players):
    """This device's own squeezelite among Lyrion's players.

    🚨 Not just the first one connecting over loopback: every Bluetooth
    speaker has a squeezelite of its own on this box (hifi-bt-player@),
    connecting from 127.0.0.1 too, and players_loop has no fixed order. The
    MAC identifies it; loopback minus the speakers' players is the fallback
    for a box whose MAC is not known."""
    mac = own_player_mac()
    if mac:
        for p in players:
            if str(p.get('playerid') or '').lower() == mac:
                return p.get('playerid')
        return None
    bt = bt_player_ids()
    for p in players:
        if (str(p.get('ip', '')).startswith('127.0.0.1:')
                and str(p.get('playerid') or '').lower() not in bt):
            return p.get('playerid')
    return None


def main():
    try:
        result = lms_request('-', ['serverstatus', 0, 999]) or {}
    except Exception:
        return
    playerid = own_player_id(result.get('players_loop', []))
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

    # Best-effort: tell LMS's OWN native resume-on-reconnect not to act, so it
    # can't race the explicit restore api_server.py does from the state file
    # above. Not load-bearing (that explicit restore starts with its own
    # `stop` specifically because this pref write isn't guaranteed to have
    # reached disk before LMS itself goes down) — just reduces how often
    # native resume gets a chance to briefly start the wrong track at all.
    try:
        lms_request(playerid, ['playerpref', 'playingAtPowerOff', '0'])
    except Exception:
        pass


if __name__ == '__main__':
    main()
