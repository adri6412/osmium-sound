#!/usr/bin/env python3
"""Osmium Sound — one squeezelite instance for one Bluetooth speaker.

ExecStart of hifi-bt-player@<instance>.service, where <instance> is the
speaker's Bluetooth address with '-' in place of ':'. Looks the speaker up in
/etc/hifi-player/bluetooth.json, builds the squeezelite command line and
execs it, so the service tracks squeezelite itself and not a Python parent.

The output device is BlueALSA's predefined `bluealsa` PCM, which is of type
`plug`: rate and format conversion happen inside ALSA, so nothing here has to
know what the speaker's codec negotiated. squeezelite is still told to
advertise 44.1/48 kHz only (-r) and to resample with soxr (-R): A2DP carries
nothing above 48 kHz, and letting squeezelite downsample a 96 kHz track with
soxr sounds better than letting the ALSA plug plugin do it with linear
interpolation.

Which Lyrion server it joins is copied from /etc/default/squeezelite, so a
Bluetooth speaker follows this device's Multiroom choice ("standalone" or
"follow another Osmium") exactly like the built-in player does.
"""
import json
import os
import re
import sys

SQ_DEFAULT = "/etc/default/squeezelite"
STATE_FILE = "/etc/hifi-player/bluetooth.json"
SQUEEZELITE = "/usr/bin/squeezelite"

# ALSA buffer for a Bluetooth sink: <buffer_ms>:<periods>:<format>:<mmap>.
# 200 ms because a Bluetooth link hiccups in ways a USB DAC never does, and
# mmap off because the BlueALSA PCM plugin does not implement it.
DEFAULT_ALSA = "200:4::0"


def mac_from_instance(inst):
    """'f4-2b-7d-63-98-d7' -> 'F4:2B:7D:63:98:D7' (None if it isn't one)."""
    mac = inst.replace("-", ":").upper()
    return mac if re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", mac) else None


def read_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f) or {}
    except Exception:
        return {}


def main_server():
    """The -s value the built-in player uses, so both join the same Lyrion."""
    try:
        with open(SQ_DEFAULT) as f:
            args = ""
            for line in f:
                m = re.match(r"\s*ARGS=['\"](.*)['\"]", line)
                if m:
                    args = m.group(1)
                    break
        m = re.search(r"-s\s+(\S+)", args)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "127.0.0.1"


def main():
    if len(sys.argv) != 2:
        print("usage: hifi-bt-player-run.py <mac-with-dashes>", file=sys.stderr)
        return 2
    mac = mac_from_instance(sys.argv[1])
    if not mac:
        print(f"not a Bluetooth address: {sys.argv[1]}", file=sys.stderr)
        return 2

    state = read_state()
    speaker = None
    for s in (state.get("speakers") or []):
        if str(s.get("mac", "")).upper() == mac:
            speaker = s
            break
    if speaker is None:
        print(f"{mac} is not a configured speaker", file=sys.stderr)
        return 1
    if not speaker.get("enabled", True):
        print(f"{mac} is switched off in Settings", file=sys.stderr)
        return 1

    # The PCM name. CODEC= is only appended when the owner pinned one: left
    # out, BlueALSA keeps whatever it negotiated with the speaker, which is
    # already the best codec both ends share.
    pcm = f"bluealsa:DEV={mac},PROFILE=a2dp,SRV=org.bluealsa"
    codec = str(speaker.get("codec") or "").strip()
    if codec:
        pcm += f",CODEC={codec}"

    name = str(speaker.get("player") or speaker.get("name") or "Bluetooth").strip()
    # squeezelite splits its arguments on whitespace, so a name with a space
    # in it has to reach it as a single argv entry — which execv does, unlike
    # the ARGS= line the built-in player goes through.
    player_mac = str(speaker.get("player_mac") or "").strip()

    argv = [
        SQUEEZELITE,
        "-o", pcm,
        "-n", name,
        "-M", "Osmium",
        "-s", main_server(),
        "-r", "44100,48000",
        "-R",
        "-a", str(speaker.get("alsa") or DEFAULT_ALSA),
        # Close the output (and so release the Bluetooth transport) after five
        # idle seconds, so a speaker is free to go to sleep between albums.
        "-C", "5",
    ]
    if player_mac:
        argv += ["-m", player_mac]

    os.execv(SQUEEZELITE, argv)


if __name__ == "__main__":
    sys.exit(main())
