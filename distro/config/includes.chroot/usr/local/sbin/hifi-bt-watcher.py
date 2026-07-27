#!/usr/bin/env python3
"""HiFi Player — Bluetooth DAC handover + Now Playing metadata.

Started by hifi-bt-watcher.service whenever Bluetooth is enabled
(api_server.py's set_bluetooth). Watches BlueZ over D-Bus for two things:

  * org.bluez.MediaTransport1 "State" — when a phone starts actively
    streaming A2DP, the local Lyrion player is paused (and CamillaDSP is
    stopped if it was running) so the real DAC is free, THEN
    hifi-bt-aplay.service is restarted to open it — same "release before
    open" ordering api_server.py already uses between squeezelite and
    CamillaDSP. When the last transport goes idle/disconnects, CamillaDSP
    is restarted if this watcher was the one that stopped it. Local
    playback is never auto-resumed — the user resumes manually.

  * org.bluez.MediaPlayer1 "Track"/"Status"/"Position" — AVRCP metadata
    from the phone, published to /run/hifi-bt/now-playing.json for the UI
    (api_server.py's GET /bluetooth_now_playing adds an online cover-art
    lookup on top — BlueZ's own AVRCP cover art support is not reliable
    enough to depend on).

Watches D-Bus via `dbus-monitor` text output rather than python3-dbus: the
rest of the appliance already shells out to CLI tools for D-Bus-backed
services (nmcli for NetworkManager, bluetoothctl here) instead of carrying
extra Python binding dependencies, and dbus-monitor's line-oriented output
is stable enough for the handful of signals this needs. Best-effort
throughout — a parsing miss just means a stale/missing metadata field, not
a broken handover (the transport State handling, which does the DAC
handover, is checked independently of the metadata parsing).
"""
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request

try:
    # hifi_logging.py ships in /usr/local/bin alongside the Python daemons;
    # this script lives in /usr/local/sbin, so it isn't found without this.
    # Best-effort: a missing module must never stop Bluetooth handover.
    sys.path.insert(0, '/usr/local/bin')
    from hifi_logging import tee_stdio_to_file
    tee_stdio_to_file('bt-watcher')
except Exception:
    pass

RUNDIR = "/run/hifi-bt"
NOW_PLAYING_FILE = os.path.join(RUNDIR, "now-playing.json")
CAMILLA_STOPPED_FLAG = os.path.join(RUNDIR, "camilla-stopped")
SQ_DEFAULT = "/etc/default/squeezelite"
DSP_UNIT = "camilladsp.service"
BT_APLAY_UNIT = "hifi-bt-aplay.service"

os.makedirs(RUNDIR, exist_ok=True)

_stop = False


def _on_sigterm(signum, frame):
    global _stop
    _stop = True


signal.signal(signal.SIGTERM, _on_sigterm)
signal.signal(signal.SIGINT, _on_sigterm)


def log(msg):
    print(f"[hifi-bt-watcher] {msg}", file=sys.stderr, flush=True)


def run(cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:
        log(f"command failed: {cmd}")
        return None


# ── squeezelite config (player name + LMS host, for pause + alias) ──
def _sq_args():
    try:
        with open(SQ_DEFAULT) as f:
            return f.read()
    except Exception:
        return ""


def _player_name():
    m = re.search(r"-n\s+(\S+)", _sq_args())
    return m.group(1) if m else "OsmiumSound"


def _lms_host():
    m = re.search(r"-s\s+(\S+)", _sq_args())
    return m.group(1) if m else "127.0.0.1"


# ── LMS JSON-RPC (pause only) ───────────────────────────────────────
def _lms_request(host, playerid, command, timeout=5):
    url = f"http://{host}:9000/jsonrpc.js"
    payload = json.dumps({"id": 1, "method": "slim.request", "params": [playerid, command]}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read()).get("result")


def _pause_local_player():
    """Best-effort: pause THIS device's own squeezelite instance if it's
    playing. Local server: matched by IP (127.0.0.1). Following a remote
    LMS (multiroom "follow" mode): matched by player name instead, since the
    local squeezelite's source IP on a remote server isn't localhost."""
    host = _lms_host()
    local = host in ("127.0.0.1", "localhost")
    name = _player_name()
    try:
        result = _lms_request(host, "-", ["serverstatus", 0, 999]) or {}
        for p in result.get("players_loop", []):
            match = str(p.get("ip", "")).startswith("127.0.0.1:") if local else (p.get("name") == name)
            if not match:
                continue
            playerid = p.get("playerid")
            st = _lms_request(host, playerid, ["status", "-", 1]) or {}
            if st.get("mode") == "play":
                _lms_request(host, playerid, ["pause", "1"])
                log(f"paused local LMS player {playerid}")
            return
    except Exception:
        log("_pause_local_player failed (LMS unreachable?)")


# ── adapter bring-up ─────────────────────────────────────────────────
def _bring_up_adapter():
    name = _player_name()
    for _ in range(60):
        if _stop:
            return False
        r = run(["bluetoothctl", "show"])
        if r and r.returncode == 0 and r.stdout:
            if "Powered: yes" not in r.stdout:
                run(["bluetoothctl", "power", "on"])
            run(["bluetoothctl", "pairable", "on"])
            run(["bluetoothctl", "system-alias", name])
            log(f"adapter ready, alias={name!r}")
            return True
        time.sleep(2)
    log("no Bluetooth adapter found after ~2min; will keep watching D-Bus")
    return False


# ── transport (DAC handover) state ──────────────────────────────────
_transport_state = {}  # object path -> 'idle' | 'pending' | 'active'


def _active_transport_count():
    return sum(1 for s in _transport_state.values() if s == "active")


def _on_dac_needed():
    log("Bluetooth streaming started — releasing the DAC")
    _pause_local_player()
    r = run(["systemctl", "is-active", DSP_UNIT])
    if r and (r.stdout or "").strip() == "active":
        run(["systemctl", "stop", DSP_UNIT])
        open(CAMILLA_STOPPED_FLAG, "w").close()
        log("stopped camilladsp so Bluetooth can use the DAC")
    # Give squeezelite's -C 5 idle timeout (and/or the camilladsp stop above)
    # time to actually close the ALSA device before hifi-bt-aplay tries to
    # open it — same reasoning as the DSP apply path's pause-then-restart.
    time.sleep(6)
    run(["systemctl", "restart", BT_APLAY_UNIT])
    log("restarted hifi-bt-aplay")


def _on_dac_freed():
    if os.path.exists(CAMILLA_STOPPED_FLAG):
        run(["systemctl", "start", DSP_UNIT])
        try:
            os.remove(CAMILLA_STOPPED_FLAG)
        except OSError:
            pass
        log("restarted camilladsp; Bluetooth session ended")
    _clear_now_playing()


def _set_transport_state(path, state):
    before = _active_transport_count()
    _transport_state[path] = state
    after = _active_transport_count()
    if before == 0 and after > 0:
        _on_dac_needed()
    elif before > 0 and after == 0:
        _on_dac_freed()


def _remove_transport(path):
    if path in _transport_state:
        del _transport_state[path]
        if _active_transport_count() == 0:
            _on_dac_freed()


# ── now playing metadata ────────────────────────────────────────────
_now_playing = {}
_device_alias_cache = {}


def _write_now_playing():
    tmp = NOW_PLAYING_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(_now_playing, f)
        os.replace(tmp, NOW_PLAYING_FILE)
    except Exception:
        log("failed to write now-playing.json")


def _clear_now_playing():
    global _now_playing
    _now_playing = {}
    try:
        os.remove(NOW_PLAYING_FILE)
    except OSError:
        pass


def _device_path_from_player_path(player_path):
    # .../hci0/dev_AA_BB_CC_DD_EE_FF/playerN -> .../hci0/dev_AA_BB_CC_DD_EE_FF
    parts = player_path.rsplit("/", 1)
    return parts[0] if len(parts) == 2 else player_path


def _device_alias(device_path):
    if device_path in _device_alias_cache:
        return _device_alias_cache[device_path]
    r = run(["dbus-send", "--system", "--print-reply", "--dest=org.bluez",
             device_path, "org.freedesktop.DBus.Properties.Get",
             "string:org.bluez.Device1", "string:Alias"])
    alias = None
    if r and r.returncode == 0 and r.stdout:
        m = re.search(r'string "([^"]*)"', r.stdout)
        if m:
            alias = m.group(1)
    _device_alias_cache[device_path] = alias
    return alias


def _update_now_playing_from_player(player_path, block):
    global _now_playing
    title = _extract_str(block, "Title")
    artist = _extract_str(block, "Artist")
    album = _extract_str(block, "Album")
    duration = _extract_uint(block, "Duration")
    position = _extract_uint(block, "Position")
    if title is not None:
        _now_playing["title"] = title
    if artist is not None:
        _now_playing["artist"] = artist
    if album is not None:
        _now_playing["album"] = album
    if duration is not None:
        _now_playing["duration"] = round(duration / 1000.0, 1)
    if position is not None:
        _now_playing["position"] = round(position / 1000.0, 1)
    alias = _device_alias(_device_path_from_player_path(player_path))
    if alias:
        _now_playing["device_name"] = alias
    _now_playing["active"] = _active_transport_count() > 0
    _write_now_playing()


# ── dbus-monitor text parsing ────────────────────────────────────────
# PropertiesChanged signature is (STRING interface, DICT changed, ARRAY
# invalidated); dbus-monitor prints the interface as the first `string "…"`
# line in the body, followed by `dict entry( string "Prop" variant … )`
# blocks for each changed property. We don't parse the nested structure —
# just scan the whole block text for the couple of property names we care
# about, which is robust to the exact nesting dbus-monitor prints.
_HEADER_RE = re.compile(r'^signal .*?\bpath=(\S+);\s*interface=([\w.]+);\s*member=(\w+)')
_IFACE_LINE_RE = re.compile(r'^\s*string "([\w.]+)"\s*$')
_REMOVED_PATH_RE = re.compile(r'object path "([^"]+)"')


def _extract_str(block, key):
    m = re.search(r'string "' + re.escape(key) + r'"\s*\n\s*variant\s+string "([^"]*)"', block)
    return m.group(1) if m else None


def _extract_uint(block, key):
    m = re.search(r'string "' + re.escape(key) + r'"\s*\n\s*variant\s+uint32 (\d+)', block)
    return int(m.group(1)) if m else None


def _handle_properties_changed(path, block_lines):
    block = "\n".join(block_lines)
    iface = None
    if block_lines:
        m = _IFACE_LINE_RE.match(block_lines[0])
        if m:
            iface = m.group(1)
    if iface == "org.bluez.MediaTransport1":
        state = _extract_str(block, "State")
        if state:
            _set_transport_state(path, state)
    elif iface == "org.bluez.MediaPlayer1":
        _update_now_playing_from_player(path, block)


def _handle_interfaces_removed(block_lines):
    block = "\n".join(block_lines)
    m = _REMOVED_PATH_RE.search(block)
    if not m:
        return
    path = m.group(1)
    _remove_transport(path)


def _watch_dbus_once():
    proc = subprocess.Popen(
        ["dbus-monitor", "--system",
         "type='signal',interface=org.freedesktop.DBus.Properties,member=PropertiesChanged,path_namespace=/org/bluez",
         "type='signal',interface=org.freedesktop.DBus.ObjectManager,member=InterfacesRemoved"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)

    header = None  # (path, member)
    body = []

    def flush():
        if header is None:
            return
        path, member = header
        if member == "PropertiesChanged":
            _handle_properties_changed(path, body)
        elif member == "InterfacesRemoved":
            _handle_interfaces_removed(body)

    try:
        for line in iter(proc.stdout.readline, ""):
            if _stop:
                break
            line = line.rstrip("\n")
            m = _HEADER_RE.match(line)
            if m:
                flush()
                header = (m.group(1), m.group(3))
                body = []
                continue
            if header is not None:
                body.append(line)
        flush()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def main():
    log("starting")
    _bring_up_adapter()
    while not _stop:
        try:
            _watch_dbus_once()
        except Exception:
            log("dbus-monitor loop crashed, restarting")
        if _stop:
            break
        time.sleep(3)
    log("stopping")


if __name__ == "__main__":
    main()
