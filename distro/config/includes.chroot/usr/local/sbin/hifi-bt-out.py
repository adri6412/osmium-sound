#!/usr/bin/env python3
"""Osmium Sound — Bluetooth speaker supervisor.

The only Bluetooth unit that is enabled at boot. It reads the owner's choice
from /etc/hifi-player/bluetooth.json and makes the rest of the stack match:

    bluetooth.service      the BlueZ daemon
    hifi-bt-agent.service  the NoInputNoOutput pairing agent
    hifi-bluealsa.service  BlueALSA in A2DP source role
    hifi-bt-player@<mac>   one squeezelite per connected speaker

🚨 Why a supervisor instead of `systemctl enable`: on the A/B image scheme a
unit's enablement does not survive an image swap (hifi-ab-seed.sh seeds /etc
from an allow-list of state files, not from the systemd symlink farm), so a
choice expressed as an enable symlink silently undoes itself on the next
update. The choice lives in the state file — which IS seeded, and IS in the
backup — and this daemon re-applies it on every boot.

It also does the reconnecting. A Bluetooth speaker that is switched off
disappears and comes back minutes or hours later, so each speaker gets its
own retry with a backoff (15 s doubling to five minutes): a box sitting next
to a speaker that is off for the night must not spend the night in a connect
loop, and must still pick it up promptly in the morning.

A snapshot of what it sees goes to /run/hifi-bt/output.json for api_server to
serve without having to run bluetoothctl on every status poll.
"""
import json
import os
import re
import signal
import subprocess
import sys
import time

try:
    # hifi_logging.py ships in /usr/local/bin next to the Python daemons; this
    # script lives in /usr/local/sbin, so it isn't importable without this.
    # Best-effort: no log file must ever stop the speakers from connecting.
    sys.path.insert(0, '/usr/local/bin')
    from hifi_logging import tee_stdio_to_file
    tee_stdio_to_file('bt-out')
except Exception:
    pass

STATE_FILE = "/etc/hifi-player/bluetooth.json"
RUNDIR = "/run/hifi-bt"
STATUS_FILE = os.path.join(RUNDIR, "output.json")

BLUEZ_UNIT = "bluetooth.service"
AGENT_UNIT = "hifi-bt-agent.service"
BLUEALSA_UNIT = "hifi-bluealsa.service"
PLAYER_UNIT = "hifi-bt-player@{}.service"

# Units from the old "appliance as a Bluetooth speaker" (A2DP sink) design.
# The appliance is a source now: leaving these running would have BlueALSA
# claim both roles and bluealsa-aplay hold the DAC open for nothing.
SINK_UNITS = ("hifi-bt-aplay.service", "hifi-bt-watcher.service")

POLL_SECONDS = 8
RETRY_MIN = 15
RETRY_MAX = 300

_stop = False
_wake = False


def _on_sigterm(signum, frame):
    global _stop
    _stop = True


def _on_sighup(signum, frame):
    """api_server.py writes the state file, then SIGHUPs us: apply it now
    instead of at the next poll, so the UI doesn't sit on a stale answer."""
    global _wake
    _wake = True


signal.signal(signal.SIGTERM, _on_sigterm)
signal.signal(signal.SIGINT, _on_sigterm)
signal.signal(signal.SIGHUP, _on_sighup)


def log(msg):
    print(f"[hifi-bt-out] {msg}", file=sys.stderr, flush=True)


def run(cmd, timeout=15):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None


def out(cmd, timeout=15):
    r = run(cmd, timeout)
    return (r.stdout or "") if r else ""


def unit_active(unit):
    return out(["systemctl", "is-active", unit], 10).strip() == "active"


def unit_exists(unit):
    r = run(["systemctl", "show", "-p", "LoadState", "--value", unit], 10)
    return bool(r) and (r.stdout or "").strip() not in ("", "not-found", "masked")


def start_unit(unit):
    if unit_active(unit):
        return True
    log(f"starting {unit}")
    r = run(["systemctl", "start", unit], 45)
    return bool(r) and r.returncode == 0


def stop_unit(unit):
    if not unit_active(unit):
        return
    log(f"stopping {unit}")
    run(["systemctl", "stop", unit], 45)


def instance(mac):
    """'F4:2B:7D:63:98:D7' -> 'f4-2b-7d-63-98-d7' (the systemd instance name)."""
    return mac.replace(":", "-").lower()


def read_state():
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def speakers_of(state):
    out_ = []
    for s in (state.get("speakers") or []):
        mac = str(s.get("mac", "")).upper()
        if re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", mac):
            s = dict(s)
            s["mac"] = mac
            out_.append(s)
    return out_


def adapter_present():
    return bool(out(["bluetoothctl", "list"], 10).strip())


def adapter_powered():
    return "Powered: yes" in out(["bluetoothctl", "show"], 10)


def device_connected(mac):
    return "Connected: yes" in out(["bluetoothctl", "info", mac], 10)


def running_players():
    """The hifi-bt-player@ instances systemd currently has loaded."""
    text = out(["systemctl", "list-units", "--all", "--no-legend", "--plain",
                "hifi-bt-player@*.service"], 15)
    found = set()
    for line in text.splitlines():
        m = re.search(r"(hifi-bt-player@\S+\.service)", line)
        if m:
            found.add(m.group(1))
    return found


def write_status(payload):
    try:
        os.makedirs(RUNDIR, exist_ok=True)
        tmp = STATUS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, STATUS_FILE)
    except Exception:
        log("could not write the status snapshot")


class Supervisor:
    def __init__(self):
        # mac -> {"next": monotonic deadline, "delay": current backoff}
        self.retry = {}
        self.was_enabled = None

    # ── Bluetooth off ────────────────────────────────────────────────
    def tear_down(self):
        for unit in sorted(running_players()):
            stop_unit(unit)
        stop_unit(BLUEALSA_UNIT)
        stop_unit(AGENT_UNIT)
        for unit in SINK_UNITS:
            stop_unit(unit)
        if unit_active(BLUEZ_UNIT):
            run(["bluetoothctl", "power", "off"], 10)
            stop_unit(BLUEZ_UNIT)
        self.retry.clear()

    # ── Bluetooth on ─────────────────────────────────────────────────
    def bring_up(self):
        """Adapter powered and BlueALSA running. False if the box has no
        Bluetooth hardware at all, which is not an error — plenty of these
        appliances are wired-only."""
        for unit in SINK_UNITS:
            if unit_active(unit):
                stop_unit(unit)
        if not unit_active(BLUEZ_UNIT):
            # The old boot-speed migration masks bluetooth.service and
            # blacklists btusb on legacy (pre-image) devices. Undo just enough
            # to honour the owner's choice; the image itself ships neither.
            run(["systemctl", "unmask", BLUEZ_UNIT], 15)
            run(["modprobe", "btusb"], 15)
            if not start_unit(BLUEZ_UNIT):
                return False
            time.sleep(1)
        if not adapter_present():
            return False
        if not adapter_powered():
            run(["bluetoothctl", "power", "on"], 15)
        start_unit(AGENT_UNIT)
        start_unit(BLUEALSA_UNIT)
        return True

    def ensure_speaker(self, sp):
        """Connect the speaker if it should be connected, and keep its player
        instance in step with whether it actually is."""
        mac = sp["mac"]
        unit = PLAYER_UNIT.format(instance(mac))
        wanted = bool(sp.get("enabled", True))
        connected = device_connected(mac)

        if wanted and not connected and sp.get("autoconnect", True):
            slot = self.retry.setdefault(mac, {"next": 0.0, "delay": RETRY_MIN})
            if time.monotonic() >= slot["next"]:
                log(f"connecting {mac} ({sp.get('name') or 'speaker'})")
                run(["bluetoothctl", "connect", mac], 30)
                # Ask BlueZ rather than trust what bluetoothctl printed: it
                # reports "Connection successful" for a link that then drops
                # straight back out, and a player started on a PCM that isn't
                # there only earns a restart loop.
                connected = device_connected(mac)
                if connected:
                    self.retry.pop(mac, None)
                else:
                    slot["next"] = time.monotonic() + slot["delay"]
                    slot["delay"] = min(slot["delay"] * 2, RETRY_MAX)
        elif connected:
            self.retry.pop(mac, None)

        if wanted and connected:
            if not unit_active(unit):
                # A speaker switched off mid-track leaves squeezelite
                # restarting until this loop catches up, and enough of those
                # in a row put the unit in `failed`, where a later start is
                # refused. Only on the way up: every tick would be a systemctl
                # call for nothing.
                run(["systemctl", "reset-failed", unit], 10)
                log(f"starting {unit}")
                run(["systemctl", "start", unit], 45)
        else:
            stop_unit(unit)
        return connected

    def prune(self, keep_macs):
        """Stop players for speakers that were removed from the list."""
        keep = {PLAYER_UNIT.format(instance(m)) for m in keep_macs}
        for unit in running_players():
            if unit not in keep:
                stop_unit(unit)
                run(["systemctl", "reset-failed", unit], 10)

    def tick(self):
        state = read_state()
        enabled = bool(state.get("enabled"))
        speakers = speakers_of(state)

        if enabled != self.was_enabled:
            log(f"Bluetooth output is now {'on' if enabled else 'off'}")
            self.was_enabled = enabled

        if not enabled:
            self.tear_down()
            write_status({"enabled": False, "adapter": False, "bluealsa": False,
                          "speakers": [], "updated": time.time()})
            return

        up = self.bring_up()
        self.prune([s["mac"] for s in speakers])
        rows = []
        for sp in speakers:
            connected = self.ensure_speaker(sp) if up else False
            unit = PLAYER_UNIT.format(instance(sp["mac"]))
            rows.append({
                "mac": sp["mac"],
                "name": sp.get("name") or "",
                "player": sp.get("player") or sp.get("name") or "",
                "enabled": bool(sp.get("enabled", True)),
                "autoconnect": bool(sp.get("autoconnect", True)),
                "connected": connected,
                "playing": connected and unit_active(unit),
            })
        write_status({"enabled": True, "adapter": up,
                      "bluealsa": unit_active(BLUEALSA_UNIT),
                      "speakers": rows, "updated": time.time()})


def main():
    global _wake
    if not unit_exists(BLUEALSA_UNIT):
        log("hifi-bluealsa.service is missing — nothing to supervise")
    sup = Supervisor()
    while not _stop:
        try:
            sup.tick()
        except Exception:
            log("tick failed")
            import traceback
            traceback.print_exc()
        # Sleep in slices so SIGHUP (and SIGTERM) are acted on immediately.
        waited = 0.0
        while not _stop and not _wake and waited < POLL_SECONDS:
            time.sleep(0.5)
            waited += 0.5
        _wake = False
    log("stopping")
    return 0


if __name__ == "__main__":
    sys.exit(main())
