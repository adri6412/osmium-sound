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

🚨 One speaker must never take another one down with it. Everything here is
asked of BlueZ through bluetoothctl, one process per question, and the moment
a speaker walks out of range those questions are exactly the ones that come
back slowly or not at all — the adapter is busy paging, bluetoothd is busy
tearing a link down. An unanswered question used to read as "not connected",
and acting on that stopped the OTHER speaker's player and sent the adapter
paging a speaker that was streaming perfectly well: switch the headphones
off, lose the speakers too. So a question now has three answers — yes, no,
and "could not ask" — and nothing is ever torn down on the third. The passes
are ordered to match: every speaker's state is read first, while the radio is
quiet, and only then is at most ONE connection attempt made.

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
# A page attempt takes the radio away from whatever is playing on another
# speaker, so it is kept short and there is never more than one per pass.
CONNECT_SECONDS = 20

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
    """The CompletedProcess, or None when the command produced no answer at
    all — it timed out, it isn't installed, it was killed. 🚨 None is not the
    same as an answer of "no", and the difference is load-bearing here: see
    device_connected()."""
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


def unit_stamp(unit):
    """A fingerprint that changes when a unit restarts. Cheap enough to take
    every pass, and it is what turns "all my speakers dropped at once" from a
    mystery into a line in the journal."""
    r = run(["systemctl", "show", "-p", "MainPID",
             "-p", "ActiveEnterTimestampMonotonic", "--value", unit], 10)
    if not r:
        return None
    values = tuple(line.strip() for line in (r.stdout or "").splitlines() if line.strip())
    return values or None


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


_CONNECTED_RE = re.compile(r"^\s*Connected:\s*(yes|no)\s*$", re.M)


def device_connected(mac):
    """True, False, or None when BlueZ could not be asked.

    🚨 That third answer is the whole point. `bluetoothctl info` is a fresh
    process and a fresh D-Bus client every time, and it is slowest — or dies
    on its timeout — exactly when a link is being torn down or the adapter is
    paging. Reading that silence as "not connected" is what let one speaker
    going out of range stop the other one's player and have the adapter chase
    a speaker that was already playing.
    """
    r = run(["bluetoothctl", "info", mac], 10)
    if r is None:
        return None
    text = (r.stdout or "") + (r.stderr or "")
    m = _CONNECTED_RE.search(text)
    if m:
        return m.group(1) == "yes"
    if re.search(r"not available", text, re.I):
        # BlueZ has never heard of this address: unpaired by hand, or
        # /var/lib/bluetooth restored from a backup older than the pairing.
        # The only case where no Connected: line still means a definite no.
        return False
    return None


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
        # mac -> the last answer BlueZ actually gave. What the screen is told
        # while a question goes unanswered, so a slow pass never shows up as a
        # speaker dropping out.
        self.seen = {}
        self.quiet_since = {}     # mac -> when the answers stopped coming
        self.state_cache = None   # the last state file that parsed
        self.stamps = {}          # unit -> restart fingerprint

    # ── The owner's choice ───────────────────────────────────────────
    def read_state(self):
        """🚨 A file that cannot be read is NOT taken as "Bluetooth off".
        Off means tearing the whole stack down, which disconnects every
        speaker at once — far too violent an answer to a transient read
        error. Only a file that genuinely isn't there means off, which is a
        device where the feature was never switched on."""
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("not an object")
            self.state_cache = data
            return data
        except FileNotFoundError:
            self.state_cache = None
            return {}
        except Exception:
            if self.state_cache is None:
                log(f"{STATE_FILE} cannot be read and nothing is cached; "
                    f"treating Bluetooth as off")
                return {}
            log(f"{STATE_FILE} cannot be read; keeping the last good copy")
            return self.state_cache

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
        self.seen.clear()
        self.quiet_since.clear()
        self.stamps.clear()

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

    def watch_restarts(self):
        """Say in the log when BlueZ or BlueALSA has restarted under us.

        Either one takes every connected speaker with it: bluetoothd for the
        obvious reason, BlueALSA because the A2DP endpoint it registers with
        BlueZ dies with the daemon and BlueZ tears down every transport that
        was using it. If speakers ever drop *together* rather than one at a
        time, this is the line that names the culprit."""
        for unit in (BLUEZ_UNIT, BLUEALSA_UNIT):
            stamp = unit_stamp(unit)
            if stamp is None:
                continue
            before = self.stamps.get(unit)
            self.stamps[unit] = stamp
            if before and before != stamp and before[0] not in ("0", ""):
                log(f"{unit} restarted ({before} -> {stamp}); every connected "
                    f"speaker will have been dropped with it")

    # ── What BlueZ says ──────────────────────────────────────────────
    def observe(self, mac):
        """The speaker's connection state, or the last one BlueZ gave us if it
        did not answer this time. None only while nothing has ever been
        heard about this address."""
        answer = device_connected(mac)
        if answer is None:
            if mac not in self.quiet_since:
                self.quiet_since[mac] = time.monotonic()
                held = self.seen.get(mac)
                log(f"{mac}: BlueZ did not answer; holding "
                    f"{'connected' if held else 'disconnected' if held is False else 'unknown'}")
            return self.seen.get(mac)
        if mac in self.quiet_since:
            waited = int(time.monotonic() - self.quiet_since.pop(mac))
            log(f"{mac}: BlueZ is answering again after {waited}s")
        if self.seen.get(mac) is not answer:
            log(f"{mac} is {'connected' if answer else 'disconnected'}")
        self.seen[mac] = answer
        return answer

    # ── The player follows the state we are sure of ──────────────────
    def apply_player(self, sp, state):
        mac = sp["mac"]
        unit = PLAYER_UNIT.format(instance(mac))
        if not bool(sp.get("enabled", True)):
            stop_unit(unit)
            return
        if state is True:
            self.retry.pop(mac, None)
            if not unit_active(unit):
                # A speaker switched off mid-track leaves squeezelite
                # restarting until this loop catches up, and enough of those
                # in a row put the unit in `failed`, where a later start is
                # refused. Only on the way up: every tick would be a systemctl
                # call for nothing.
                run(["systemctl", "reset-failed", unit], 10)
                log(f"starting {unit}")
                run(["systemctl", "start", unit], 45)
        elif state is False:
            stop_unit(unit)
        # state is None — we do not know, so nothing moves. Whatever is
        # playing keeps playing: squeezelite exits by itself if its PCM has
        # really gone, and stopping it on a guess is how one speaker used to
        # silence another.

    # ── Reconnecting ─────────────────────────────────────────────────
    def due_for_connect(self, speakers, states):
        """The speaker most overdue for a connection attempt, or None.

        One per pass on purpose: the adapter can only page one device at a
        time anyway, and two attempts in the same pass would keep the radio
        away from a speaker that is playing for twice as long. A speaker
        whose state is merely unknown is never paged — it may well be
        connected and streaming."""
        now = time.monotonic()
        due = []
        for sp in speakers:
            mac = sp["mac"]
            if states.get(mac) is not False:
                continue
            if not sp.get("enabled", True) or not sp.get("autoconnect", True):
                continue
            slot = self.retry.setdefault(mac, {"next": 0.0, "delay": RETRY_MIN})
            if now >= slot["next"]:
                due.append((slot["next"], mac, sp))
        if not due:
            return None
        due.sort(key=lambda row: row[0])
        return due[0][2]

    def try_connect(self, sp):
        mac = sp["mac"]
        slot = self.retry.setdefault(mac, {"next": 0.0, "delay": RETRY_MIN})
        log(f"connecting {mac} ({sp.get('name') or 'speaker'})")
        run(["bluetoothctl", "connect", mac], CONNECT_SECONDS)
        # Ask BlueZ rather than trust what bluetoothctl printed: it reports
        # "Connection successful" for a link that then drops straight back
        # out, and a player started on a PCM that isn't there only earns a
        # restart loop.
        answer = self.observe(mac)
        if answer:
            self.retry.pop(mac, None)
        else:
            slot["next"] = time.monotonic() + slot["delay"]
            slot["delay"] = min(slot["delay"] * 2, RETRY_MAX)
        return answer

    def prune(self, keep_macs):
        """Stop players for speakers that were removed from the list."""
        keep = {PLAYER_UNIT.format(instance(m)) for m in keep_macs}
        for unit in running_players():
            if unit not in keep:
                stop_unit(unit)
                run(["systemctl", "reset-failed", unit], 10)

    def tick(self):
        state = self.read_state()
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
        self.watch_restarts()
        self.prune([s["mac"] for s in speakers])

        # Pass one: read every speaker's state while the radio is quiet.
        # Nothing below this line may run before all of them have answered —
        # a page attempt is the one thing that makes bluetoothctl slow, and a
        # slow answer for one speaker must never be read as another speaker
        # dropping out.
        states = {sp["mac"]: (self.observe(sp["mac"]) if up else self.seen.get(sp["mac"]))
                  for sp in speakers}

        # Pass two: the players follow.
        for sp in speakers:
            self.apply_player(sp, states[sp["mac"]])

        # Pass three: at most one connection attempt, last, so the blocking
        # part of the pass cannot poison anybody else's answer.
        if up:
            sp = self.due_for_connect(speakers, states)
            if sp is not None:
                states[sp["mac"]] = self.try_connect(sp)
                self.apply_player(sp, states[sp["mac"]])

        rows = []
        for sp in speakers:
            mac = sp["mac"]
            unit = PLAYER_UNIT.format(instance(mac))
            connected = states.get(mac)
            rows.append({
                "mac": mac,
                "name": sp.get("name") or "",
                "player": sp.get("player") or sp.get("name") or "",
                "enabled": bool(sp.get("enabled", True)),
                "autoconnect": bool(sp.get("autoconnect", True)),
                "connected": bool(connected),
                "playing": bool(connected) and unit_active(unit),
                # True while this row is the last thing BlueZ said rather than
                # what it says now. Nothing acts on it; it is there so a
                # support log can tell a stale row from a fresh one.
                "stale": connected is None or mac in self.quiet_since,
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
