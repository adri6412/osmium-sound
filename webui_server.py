#!/usr/bin/env python3
"""HiFi Player — web admin + first-boot provisioning gateway.

A single root daemon that is the appliance's "second LAN bridge" (the first is
sources_server.py:8080, pairing-token gated). It has three jobs, all in one
process so there is a single service to operate:

  1. PROVISIONING / CAPTIVE (only while /etc/hifi-player/provisioning-pending
     exists): brings up a Wi-Fi hotspot, answers OS captive-portal probes, and
     serves a minimal vanilla-JS setup page so a screenless unit can be put on
     the network and have its mode chosen from a phone.

  2. AUTH: a self-contained username/password admin account in SQLite (its own
     credentials, NOT the companion pairing-token), cookie session, CSRF.

  3. WEB ADMIN + PROXY: serves the separate Vue admin app (built to
     /opt/hifi-webui/dist) and relays a whitelisted set of api_server.py:8000
     calls behind the session — api_server itself stays loopback-only and
     untrusted-network-free, exactly as today.

Security model (see the plan's "Analisi di sicurezza"):
  * api_server is NEVER exposed directly; the proxy runs here, behind the
    session, and calls 127.0.0.1:8000.
  * The cookie signing key is generated PER-DEVICE on first start and never
    shipped in the image (a shared key => forgeable sessions). Plain HTTP by
    design (no TLS): a per-device self-signed cert made every browser show a
    "connection not private" click-through on first visit, which was worse
    UX than the plain-HTTP tradeoff (session cookies are not Secure-flagged
    as a result -- see _bootstrap below).
  * Every mutating request needs a double-submit CSRF token, checked against
    a cookie that is host-only and SameSite=Strict -- neither is forgeable by
    spoofing the Host header, so normal traffic is not gated on Host. Only
    while a setup/recovery AP is up does an unrecognized Host get redirected
    to the captive portal (see _guard/_allowed_hosts).
  * The proxy whitelist is PARTITIONED: a small pre-auth set is reachable during
    the captive window (wifi/dac/lyrion-install/claim/create-account); the full
    admin set (reboot/shutdown/ssh/ota/dsp/...) needs a live session.
  * factory_reset / password reset re-validate the admin password in the body.
  * Framing is allowed for this origin plus Lyrion's (same host, :9000), which
    is what Material's "Osmium Admin" menu entry embeds -- see
    _frame_ancestors(). Same host means same site, so the session cookie above
    still travels into that frame.

Dev/local flags:
  HIFI_WEBUI_STATE_DIR   override /etc/hifi-player (default) for state files
  HIFI_WEBUI_DIST        override /opt/hifi-webui/dist (the Vue build)
  HIFI_WEBUI_PORT        override the HTTP port (default 80; use e.g. 8081
                         to run unprivileged on a dev machine)
  HIFI_PROVISION_FAKE=1  stub every nmcli call (no real Wi-Fi), for a laptop
"""

import json
import os
import re
import secrets
import socket
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from flask import Flask, jsonify, request, session, redirect, send_from_directory, Response
from werkzeug.security import generate_password_hash, check_password_hash

from hifi_logging import tee_stdio_to_file
from hifi_i18n import t as _wt
# Every print() below keeps reaching the console/journald unchanged AND now also
# lands in a size-rotated file at /var/log/hifi/webui.log (journald alone is
# volatile on this image) — picked up by the support-bundle endpoint.
tee_stdio_to_file('webui')

# ── paths / config ───────────────────────────────────────────────────
STATE_DIR = os.environ.get('HIFI_WEBUI_STATE_DIR', '/etc/hifi-player')
DIST_DIR = os.environ.get('HIFI_WEBUI_DIST', '/opt/hifi-webui/dist')
MARKER = os.path.join(STATE_DIR, 'provisioning-pending')
PROVISION_STATE = os.path.join(STATE_DIR, 'provisioning-state.json')
DB_PATH = os.path.join(STATE_DIR, 'webui.db')
SECRET_KEY_FILE = os.path.join(STATE_DIR, 'webui-secret.key')
DISPLAY_MODE_FILE = os.path.join(STATE_DIR, 'display-mode')

API_BASE = 'http://127.0.0.1:8000'
LYRION_BASE = 'http://127.0.0.1:9000'
SOURCES_BASE = 'http://127.0.0.1:8080'

AP_CON_NAME = 'hifi-setup'
AP_ADDR = '10.42.0.1'
# The setup hotspot is deliberately open (no PSK) -- see SECURITY.md. It used
# to be WPA2 with a fixed, publicly-documented PSK ('osmiumsetup'), which
# already gave a targeted attacker no real barrier, but its wpa_supplicant
# software-AP handshake also turned out to be flat-out incompatible with iOS
# (invalid MIC on message 2/4, a known upstream issue -- see the fix commit
# for the forum thread this traces to). Accepted trade-off: this is a home
# appliance, the window is the ~2 minutes first-boot setup takes, and the
# pre-auth set behind it carries no destructive endpoint.

FAKE = os.environ.get('HIFI_PROVISION_FAKE') == '1'
PORT = int(os.environ.get('HIFI_WEBUI_PORT', '80'))

app = Flask(__name__)

# Single writer for the provisioning state machine + AP transitions.
_prov_lock = threading.Lock()

# Per-IP failed-login throttle (mirrors sources_server.py's pattern: in-memory,
# single-process is fine, losing it on restart only relaxes a guess-slowdown).
_auth_fail_lock = threading.Lock()
_auth_fail_log = {}
_AUTH_FAIL_WINDOW = 60.0
_AUTH_FAIL_MAX = 20


def _rate_limited(ip):
    now = time.monotonic()
    with _auth_fail_lock:
        fails = [t for t in _auth_fail_log.get(ip, []) if now - t < _AUTH_FAIL_WINDOW]
        _auth_fail_log[ip] = fails
        return len(fails) >= _AUTH_FAIL_MAX


def _record_fail(ip):
    with _auth_fail_lock:
        _auth_fail_log.setdefault(ip, []).append(time.monotonic())


def _lang():
    """Caller's UI language, sent by admin-webui's api.js as a header on every
    request (same convention as api_server.py's own _lang()). Used both for
    the couple of messages generated directly here (_proxy()'s own
    unreachable-backend fallbacks) and to forward the caller's choice on to
    api_server/sources_server, which otherwise have no way to see it."""
    try:
        v = request.headers.get('X-UI-Lang')
    except RuntimeError:
        return 'en'
    return v if v in ('en', 'it') else 'en'


# ── local IP discovery (for Host allowlist) ───────────────────────────
def _local_ips():
    ips = {'127.0.0.1', AP_ADDR}
    try:
        for res in socket.getaddrinfo(socket.gethostname(), None):
            ips.add(res[4][0])
    except Exception:
        pass
    # Best-effort primary route IP (works even without a resolvable hostname).
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return {ip for ip in ips if ip}


# ── one-time per-device secret: cookie signing key ────────────────────
def _ensure_secret_key():
    try:
        if os.path.isfile(SECRET_KEY_FILE):
            with open(SECRET_KEY_FILE, 'rb') as f:
                data = f.read().strip()
            if data:
                return data
    except Exception:
        pass
    key = secrets.token_bytes(32)
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = SECRET_KEY_FILE + '.tmp'
        with open(tmp, 'wb') as f:
            f.write(key)
        os.chmod(tmp, 0o600)
        os.replace(tmp, SECRET_KEY_FILE)
    except Exception:
        # If we cannot persist it, fall back to an ephemeral key (sessions won't
        # survive a restart, but the daemon still works).
        pass
    return key


# ── SQLite auth store ────────────────────────────────────────────────
def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        conn = _db()
        conn.execute('CREATE TABLE IF NOT EXISTS admin_user ('
                     'id INTEGER PRIMARY KEY CHECK (id = 1), '
                     'username TEXT NOT NULL, password_hash TEXT NOT NULL, '
                     'updated_at TEXT NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)')
        # session_version lets change/reset-password invalidate every open cookie.
        conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('session_version', '1')")
        try:
            os.chmod(DB_PATH, 0o600)
        except Exception:
            pass
        conn.commit()
        conn.close()
    except Exception as e:
        print(f'[webui] DB init failed: {e}')


def _get_user():
    try:
        conn = _db()
        row = conn.execute('SELECT * FROM admin_user WHERE id = 1').fetchone()
        conn.close()
        return row
    except Exception:
        return None


def _session_version():
    try:
        conn = _db()
        row = conn.execute("SELECT value FROM meta WHERE key = 'session_version'").fetchone()
        conn.close()
        return row['value'] if row else '1'
    except Exception:
        return '1'


def _bump_session_version():
    try:
        conn = _db()
        cur = _session_version()
        conn.execute("UPDATE meta SET value = ? WHERE key = 'session_version'",
                     (str(int(cur) + 1),))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _create_user(username, password):
    conn = _db()
    conn.execute('INSERT OR REPLACE INTO admin_user (id, username, password_hash, updated_at) '
                 'VALUES (1, ?, ?, ?)',
                 (username, generate_password_hash(password),
                  time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())))
    conn.commit()
    conn.close()


def _logged_in():
    """True if the request carries a valid, current session cookie."""
    if not session.get('auth'):
        return False
    return session.get('sv') == _session_version()


def _verify_password(password):
    row = _get_user()
    return bool(row) and check_password_hash(row['password_hash'], password)


# ── provisioning marker / state ──────────────────────────────────────
def _provisioning():
    return os.path.exists(MARKER)


def _load_prov_state():
    try:
        with open(PROVISION_STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_prov_state(state):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = PROVISION_STATE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(state, f)
        os.replace(tmp, PROVISION_STATE)
    except Exception as e:
        print(f'[webui] save prov state failed: {e}')


# ── nmcli helpers (argv only, never shell; stubbed under FAKE) ───────
def _nmcli(args, timeout=60):
    if FAKE:
        print(f'[webui] FAKE nmcli {args}')
        return 0, '', ''
    try:
        r = subprocess.run(['nmcli'] + args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return 1, '', str(e)


_SSID_RE = re.compile(r'^[\x20-\x7e]{1,32}$')


def _wifi_device():
    if FAKE:
        return 'wlan0'
    rc, out, _ = _nmcli(['-t', '-f', 'DEVICE,TYPE', 'device', 'status'])
    if rc == 0:
        for line in out.splitlines():
            parts = line.split(':')
            if len(parts) >= 2 and parts[1] == 'wifi':
                return parts[0]
    return None


# dnsmasq-base is required by NetworkManager's ipv4.method=shared (the hotspot).
# It ships in the ISO package-list and is installed by OS migration 0026, but on
# an OTA-upgraded unit that hadn't applied the OS bundle it can be missing — in
# which case `nmcli connection up` for the AP fails. Ensure it at runtime,
# best-effort, once, with a clear log line.
_dnsmasq_attempted = False


def _dnsmasq_present():
    if FAKE:
        return True
    try:
        return subprocess.run(['dpkg', '-s', 'dnsmasq-base'],
                              capture_output=True, timeout=10).returncode == 0
    except Exception:
        return False


def _ensure_dnsmasq():
    global _dnsmasq_attempted
    if _dnsmasq_present():
        return True
    if _dnsmasq_attempted:
        return False
    _dnsmasq_attempted = True
    print('[webui] dnsmasq-base missing — installing (required for the setup hotspot)')
    try:
        subprocess.run(['apt-get', 'install', '-y', 'dnsmasq-base'],
                       capture_output=True, timeout=180,
                       env=dict(os.environ, DEBIAN_FRONTEND='noninteractive'))
    except Exception as e:
        print(f'[webui] dnsmasq-base install failed: {e}')
    return _dnsmasq_present()


def _ap_supported(dev):
    if FAKE:
        return True
    rc, out, _ = _nmcli(['-g', 'WIFI-PROPERTIES.AP', 'device', 'show', dev])
    return rc == 0 and 'yes' in out.lower()


def _wired_connected():
    """True if there is an active non-Wi-Fi, non-loopback uplink (ethernet).
    Used to let the user skip the Wi-Fi step when they're on a cable.

    Device-based rather than TYPE-string based: nmcli reports the connection
    type as either 'ethernet' or '802-3-ethernet' depending on the version, so
    we instead accept any active connection on a device that isn't the Wi-Fi
    radio, isn't 'lo', and isn't our own hotspot."""
    if FAKE:
        return False
    wdev = _wifi_device()
    rc, out, _ = _nmcli(['-t', '-f', 'NAME,DEVICE', 'connection', 'show', '--active'])
    if rc != 0:
        return False
    for line in out.splitlines():
        parts = re.split(r'(?<!\\):', line)
        if len(parts) < 2:
            continue
        name = parts[0].replace('\\:', ':')
        device = parts[1]
        if name != AP_CON_NAME and device and device != 'lo' and device != wdev:
            return True
    return False


def _scan_wifi():
    """Return a cached-friendly list of {ssid, signal, security, in_use}."""
    if FAKE:
        return [{'ssid': 'FakeNet', 'signal': 80, 'security': 'WPA2', 'in_use': False}]
    _nmcli(['device', 'wifi', 'rescan'], timeout=20)
    # `rescan` only requests a scan and returns immediately -- results land
    # asynchronously a few seconds later. Reading the list right away worked
    # in practice post-setup (NetworkManager already had a scan cache from its
    # own periodic background scans to fall back on), but during first-boot
    # provisioning -- the one call site that matters here, made seconds after
    # NetworkManager itself starts, with no such cache yet -- it came back
    # empty even with networks in range. Poll briefly instead of trusting the
    # first read. Worth spending real time on: _evaluate_provisioning() calls
    # this exactly ONCE, right before raising the setup hotspot, and never
    # again for the rest of first-boot provisioning -- once that hotspot is up
    # the same radio can't scan any more (single radio, see the call site), so
    # whatever list is captured here is final for the whole setup flow.
    nets = []
    for _ in range(8):
        rc, out, _ = _nmcli(['-t', '-f', 'IN-USE,SSID,SIGNAL,SECURITY', 'device', 'wifi', 'list'])
        nets = []
        if rc == 0:
            seen = set()
            for line in out.splitlines():
                # nmcli -t escapes ':' inside fields as '\:'; split on unescaped ':'
                parts = re.split(r'(?<!\\):', line)
                if len(parts) < 4:
                    continue
                ssid = parts[1].replace('\\:', ':')
                if not ssid or ssid in seen:
                    continue
                seen.add(ssid)
                nets.append({'ssid': ssid, 'signal': int(parts[2] or 0),
                             'security': parts[3] or '', 'in_use': parts[0].strip() == '*'})
        if nets:
            break
        time.sleep(1.5)
    return nets


def _raise_ap(dev):
    _ensure_dnsmasq()  # best-effort; ipv4.method=shared below needs it
    ssid = _ap_ssid(dev)
    _nmcli(['connection', 'delete', AP_CON_NAME])  # clear any stale profile
    rc, _, err = _nmcli([
        'connection', 'add', 'type', 'wifi', 'ifname', dev, 'con-name', AP_CON_NAME,
        'autoconnect', 'no', 'ssid', ssid,
        # Fixed mid-range 2.4GHz channel instead of "auto": this box's AP mode
        # is driven by wpa_supplicant's own minimal AP implementation (no
        # hostapd in the image), whose auto channel-select is known flaky
        # with iOS clients -- pin one that's valid in every regulatory domain.
        '802-11-wireless.mode', 'ap', '802-11-wireless.band', 'bg',
        '802-11-wireless.channel', '6',
        # No wifi-sec.* here on purpose -- see the module-level comment above
        # AP_CON_NAME/AP_ADDR for why. WPA2
        # pinning (key-mgmt/proto/pairwise/group/pmf) was tried first and
        # didn't fix iOS joins: the failure is in wpa_supplicant's AP-mode
        # 4-way handshake itself (invalid MIC on message 2/4), not the cipher
        # negotiation, so an open network sidesteps it at the root instead of
        # working around it.
        'ipv4.method', 'shared', 'ipv4.addresses', f'{AP_ADDR}/24',
        'ipv6.method', 'disabled'])
    if rc != 0:
        print(f'[webui] AP add failed: {err}')
        return False, ssid
    rc, _, err = _nmcli(['connection', 'up', AP_CON_NAME])
    if rc != 0:
        print(f'[webui] AP up failed: {err}')
        _nmcli(['connection', 'delete', AP_CON_NAME])
        return False, ssid
    return True, ssid


def _teardown_ap():
    _nmcli(['connection', 'down', AP_CON_NAME])
    _nmcli(['connection', 'delete', AP_CON_NAME])


def _ap_ssid(dev):
    suffix = 'XXXX'
    try:
        with open(f'/sys/class/net/{dev}/address') as f:
            mac = f.read().strip().replace(':', '')
        if len(mac) >= 4:
            suffix = mac[-4:].upper()
    except Exception:
        pass
    return f'Osmium-Setup-{suffix}'


def _connect_wifi(ssid, password, ap_fallback=True):
    """Try to join, and on failure delete the stale profile.

    `ap_fallback` (only True for the post-setup network-loss recovery
    caller): also drop any AP before joining and, on failure, re-raise it so
    the phone -- which auto-rejoins it -- sees the error. First-boot
    provisioning passes False: it never raises an AP at all any more (see
    SetupWizard.jsx).

    Builds an explicit connection profile (`connection add` + `connection
    up`) instead of the `nmcli device wifi connect SSID` shorthand. Root-caused
    live via SSH on the actual failing hardware (Intel AC 9560/iwlwifi): the
    shorthand refuses instantly with "No network with SSID found" whenever
    the SSID isn't already sitting in NetworkManager's own *passive* scan
    cache -- and a real, joinable, correctly-configured network can be
    consistently absent from that cache (reproduced: 5+ fresh
    `device wifi rescan` cycles in a row, 5s apart, never once showed a
    network that was live and reachable the whole time) while still being
    reachable, because `connection add`+`up` doesn't need the passive cache
    at all -- it drives wpa_supplicant's own active (scan_ssid=1) probe
    during activation, which found and joined the same network in ~7s on the
    very first try. This is a strictly more robust join path, not just a
    workaround for this one card: it removes a precondition (SSID visible in
    a passive scan snapshot) the join was never supposed to need.

    Returns (ok, err, ap) — ap is the *actual* outcome of an `ap_fallback`
    re-raise ({'active','ssid','psk'}, or None if it wasn't attempted / not
    needed), never assumed: a single Wi-Fi radio re-raising an AP can itself
    fail."""
    if not _SSID_RE.match(ssid or ''):
        return False, _wt('network.ssidInvalidChars', _lang()), None
    if ap_fallback:
        _teardown_ap()
    dev = _wifi_device()
    _nmcli(['connection', 'delete', 'id', ssid])  # clear any stale profile first
    add_args = ['connection', 'add', 'type', 'wifi', 'con-name', ssid, 'ssid', ssid]
    if dev:
        add_args += ['ifname', dev]
    if password:
        add_args += ['802-11-wireless-security.key-mgmt', 'wpa-psk',
                     '802-11-wireless-security.psk', password]
    rc, _, err = _nmcli(add_args)
    if rc != 0:
        return False, (err.strip() or _wt('network.connectFailed', _lang())), None
    # Association can still fail transiently on marginal signal (observed:
    # identical config, back-to-back attempts, one hung in
    # associating<->disconnected for 25s and failed, the next completed the
    # 4-way handshake in under a second) -- worth a couple of retries before
    # surfacing a hard failure, same reasoning as the old SSID-visibility
    # retry this replaces.
    rc, err = 1, ''
    for attempt in range(3):
        rc, _, err = _nmcli(['connection', 'up', ssid], timeout=45)
        if rc == 0:
            return True, '', None
        if attempt < 2:
            print(f'[webui] wifi connect: activation attempt {attempt + 1} failed ({err.strip()}), retrying')
            time.sleep(2)
    # Delete the profile on failure so NM doesn't fight any AP we're about to
    # re-raise (and so it doesn't linger and interfere with the next attempt
    # either way).
    _nmcli(['connection', 'delete', 'id', ssid])
    ap = None
    if ap_fallback:
        dev = _wifi_device()
        if dev:
            ap_ok, ap_ssid = _raise_ap(dev)
            ap = {'active': ap_ok, 'ssid': ap_ssid if ap_ok else None, 'psk': None}
    return False, (err.strip() or _wt('network.connectFailed', _lang())), ap


# ── network resilience (runs always, independent of provisioning) ───
# Two problems reported on real hardware, both addressed here:
#   1. A wired connection profile can go bad (corrupted/stale config) or never
#      get created in the first place, leaving a physically-connected cable
#      with no IP and no automatic recovery — NetworkManager here has
#      no-auto-default set, so it never recreates a profile on its own.
#   2. If NEITHER wired nor Wi-Fi has connectivity on an already-configured
#      (post-provisioning) unit, there is no way back in short of physical
#      access — this raises the SAME setup hotspot, but scoped to network
#      reconfiguration ONLY (no account/mode/wizard concepts touched).
#
# Both run from a single background loop, skipped entirely while first-boot
# provisioning owns the AP/network transitions.
_eth_fail_since = {}  # device -> monotonic timestamp first seen "carrier but no IP"
_ETH_HARD_REPAIR_AFTER = 90  # seconds of continuous failure before nuking the profile


def _eth_devices():
    if FAKE:
        return []
    rc, out, _ = _nmcli(['-t', '-f', 'DEVICE,TYPE', 'device', 'status'])
    devs = []
    if rc == 0:
        for line in out.splitlines():
            parts = line.split(':')
            if len(parts) >= 2 and parts[1] == 'ethernet':
                devs.append(parts[0])
    return devs


def _has_carrier(dev):
    """Kernel-level 'is a cable physically plugged in', independent of any
    NetworkManager profile/connection state."""
    try:
        with open(f'/sys/class/net/{dev}/carrier') as f:
            return f.read().strip() == '1'
    except Exception:
        return False


def _device_has_ip(dev):
    rc, out, _ = _nmcli(['-g', 'IP4.ADDRESS', 'device', 'show', dev])
    return rc == 0 and bool(out.strip())


def _ensure_networkmanager_state(device=None):
    """Recover from NetworkManager states where the interface is unmanaged or networking is globally off."""
    _nmcli(['networking', 'on'], timeout=15)
    if device:
        _nmcli(['device', 'set', device, 'managed', 'yes'], timeout=15)


def _wait_for_dhcp_ip(dev, timeout=15):
    """Wait briefly for NetworkManager to hand a lease to a just-connected dev."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _device_has_ip(dev):
            return True
        time.sleep(1)
    return False


def _ethernet_intentionally_disabled():
    """True once the user has explicitly picked Wi-Fi over wired from Settings
    (api_server.py's _set_interface_enabled sets connection.autoconnect=no on
    every Ethernet profile when that happens) — carrier-but-no-IP is then the
    deliberate outcome of that choice, not a fault for self-heal to 'fix' by
    reconnecting the cable it was just told to stop using."""
    rc, out, _ = _nmcli(['-t', '-f', 'NAME,TYPE', 'connection', 'show'])
    if rc != 0:
        return False
    for line in out.splitlines():
        parts = re.split(r'(?<!\\):', line)
        if len(parts) < 2 or parts[1] != '802-3-ethernet':
            continue
        rc2, ac, _ = _nmcli(['-g', 'connection.autoconnect', 'connection', 'show', parts[0].replace('\\:', ':')])
        if rc2 == 0 and ac.strip() == 'no':
            return True
    return False


def _wired_self_heal():
    """An Ethernet cable plugged in (carrier=1) with no IP means either no
    connection profile exists yet, or the existing one is broken/stale. First
    response is always just `nmcli device connect` (activates an existing
    profile or auto-creates a fresh DHCP one if none exists — same mechanism
    as api_server.py's wired_dhcp()). If that keeps failing for a while, the
    profile itself is probably corrupted: delete every Ethernet connection
    profile and retry once more with a clean slate. Never touches Wi-Fi or
    anything else."""
    if FAKE:
        return
    if _ethernet_intentionally_disabled():
        return
    now = time.monotonic()
    seen = set()
    for dev in _eth_devices():
        seen.add(dev)
        if not _has_carrier(dev):
            _eth_fail_since.pop(dev, None)
            continue
        if _device_has_ip(dev):
            _eth_fail_since.pop(dev, None)
            continue
        since = _eth_fail_since.setdefault(dev, now)
        if now - since >= _ETH_HARD_REPAIR_AFTER:
            print(f'[webui] {dev}: cable in, no IP for {int(now - since)}s — '
                  f'deleting Ethernet profile(s) and retrying fresh (possible corrupted profile)')
            rc, out, _ = _nmcli(['-t', '-f', 'NAME,TYPE', 'connection', 'show'])
            if rc == 0:
                for line in out.splitlines():
                    parts = re.split(r'(?<!\\):', line)
                    if len(parts) >= 2 and parts[1] == '802-3-ethernet':
                        _nmcli(['connection', 'delete', 'id', parts[0].replace('\\:', ':')])
            _eth_fail_since[dev] = now  # fresh grace window for the just-recreated profile
        _ensure_networkmanager_state(dev)
        _nmcli(['device', 'connect', dev], timeout=30)
        _wait_for_dhcp_ip(dev)
    for dev in list(_eth_fail_since.keys()):
        if dev not in seen:
            _eth_fail_since.pop(dev, None)  # device unplugged/removed


# ── network-loss fallback hotspot (post-provisioning, network-only) ──
_net_lock = threading.Lock()
_net_recovery = {'active': False, 'ssid': None, 'psk': None,
                 'networks': [], 'networks_cached_at': None, 'error': None}
_monitor_start = time.monotonic()
_NET_MONITOR_GRACE = 90  # seconds after daemon start before raising a recovery AP


def _has_any_connectivity():
    """True if a real (non-AP) wired or Wi-Fi connection is up. Excludes our
    own setup/recovery hotspot, which shows up as an active 'wifi' device too."""
    if FAKE:
        return True
    rc, out, _ = _nmcli(['-t', '-f', 'DEVICE,TYPE,STATE,CONNECTION', 'device', 'status'])
    if rc != 0:
        return False
    for line in out.splitlines():
        parts = re.split(r'(?<!\\):', line)
        if len(parts) >= 4 and parts[1] in ('ethernet', 'wifi') \
                and parts[2] == 'connected' and parts[3] != AP_CON_NAME:
            return True
    return False


def _raise_net_recovery_ap():
    dev = _wifi_device()
    if not dev or not _ap_supported(dev):
        _net_recovery['error'] = _wt('network.noWifiForRecoveryAp', _lang())
        return False
    _net_recovery['networks'] = _scan_wifi()
    _net_recovery['networks_cached_at'] = time.time()
    ok, ssid = _raise_ap(dev)
    if ok:
        _net_recovery.update({'active': True, 'ssid': ssid, 'psk': None, 'error': None})
        print(f'[webui] network lost — raised recovery hotspot {ssid}')
    else:
        _net_recovery['error'] = _wt('network.recoveryApFailed', _lang())
    return ok


def _teardown_net_recovery():
    if _net_recovery['active']:
        _teardown_ap()
        print('[webui] network restored — recovery hotspot dropped')
    _net_recovery.update({'active': False, 'ssid': None, 'psk': None, 'error': None})


def _network_monitor_tick():
    if _provisioning():
        return  # first-boot flow owns the AP/network transitions
    _wired_self_heal()
    if time.monotonic() - _monitor_start < _NET_MONITOR_GRACE:
        return  # boot grace window — give normal autoconnect/DHCP time to settle
    with _net_lock:
        if _has_any_connectivity():
            if _net_recovery['active']:
                _teardown_net_recovery()
        elif not _net_recovery['active']:
            _raise_net_recovery_ap()


def _network_monitor_loop():
    while True:
        try:
            _network_monitor_tick()
        except Exception as e:
            print(f'[webui] network monitor error: {e}')
        time.sleep(20)


# ── provisioning state machine ───────────────────────────────────────
def _evaluate_provisioning():
    """Called at startup and on demand. Keeps the on-screen network list
    fresh, picks up finalize, and (installer boot mode only) reconciles the
    QR/hotspot.

    Normal first-boot Wi-Fi setup no longer raises a hotspot/AP at all: it's
    done entirely from the on-screen panel, or Ethernet. Two reasons. First,
    device mode (screen vs. headless) isn't decided until *after* this step
    (see provision_claim_mode below), so a screen is always physically
    available here regardless of what the unit ends up being configured as
    -- there's no headless case to serve with a phone-facing hotspot at this
    point in the flow. Second, and what actually forced the change: the
    AP<->station radio cycling this used to require was unreliable on some
    real Wi-Fi hardware (reproduced on a Dell with an Intel/iwlwifi card --
    joins would time out with "network not found" or NetworkManager's opaque
    "secrets were required" even with a correct password and the network in
    range), while a plain station-mode scan+join never needs to leave
    station mode at all.

    The live-USB *installer* (_boot_mode() == 'installer') is a different
    problem and keeps raising its AP as before: it images a disk before any
    OS is installed, may have no keyboard/mouse/touch attached at all, and
    relies on InstallWizard.jsx's always-on QR badge (hotspot or LAN IP) to
    be driven from a phone instead -- there's no on-screen network panel to
    fall back on there, so the "a screen is always available" reasoning
    above doesn't apply to it.

    The (still AP-capable) network-loss recovery hotspot for an
    already-configured unit is untouched either way -- see
    _raise_net_recovery_ap()."""
    if not _provisioning():
        return
    with _prov_lock:
        state = _load_prov_state()
        if state.get('finalized'):
            _do_finalize()
            return
        stage = state.get('stage')
        ap = state.get('ap') or {}
        # Leave it alone mid-connect or after a successful network step.
        if stage in ('connecting', 'network-ok'):
            return
        if _boot_mode() != 'installer':
            dev = _wifi_device()
            state['networks'] = _scan_wifi() if dev else state.get('networks', [])
            state['networks_cached_at'] = time.time()
            state['stage'] = stage or 'waiting-wifi'
            _save_prov_state(state)
            return
        # Installer boot mode from here on: original AP-raising behavior.
        if ap.get('active'):
            return
        dev = _wifi_device()
        if not dev:
            # NetworkManager not ready yet (or no Wi-Fi radio): stay retryable —
            # the loop will try again shortly (fixes the startup race).
            state['ap'] = {'active': False, 'supported': None}
            state['stage'] = state.get('stage') or 'init'
            _save_prov_state(state)
            return
        if not _ap_supported(dev):
            state['ap'] = {'active': False, 'supported': False, 'ssid': None,
                           'error': _wt('network.hotspotUnsupported', _lang())}
            state['stage'] = 'waiting-lan'
            _save_prov_state(state)
            return
        # Cache a scan BEFORE raising the AP (single radio can't scan while AP).
        state['networks'] = _scan_wifi()
        state['networks_cached_at'] = time.time()
        ok, ssid = _raise_ap(dev)
        state['ap'] = {'active': ok, 'supported': True, 'ssid': ssid if ok else None,
                       'psk': None,
                       'error': None if ok else _wt('network.hotspotActivateFailed', _lang())}
        state['stage'] = 'waiting-ap' if ok else 'waiting-lan'
        _save_prov_state(state)


def _live_wifi_rescan():
    """On-demand rescan for the on-screen Wi-Fi panel -- a plain station-mode
    scan, nothing else: first-boot never raises an AP, so there's no radio
    mode to preserve/restore around it any more."""
    with _prov_lock:
        state = _load_prov_state()
        dev = _wifi_device()
        nets = _scan_wifi() if dev else state.get('networks', [])
        state['networks'] = nets
        state['networks_cached_at'] = time.time()
        _save_prov_state(state)
    return nets


def _provisioning_loop():
    """Re-evaluate the hotspot every ~20s until the box leaves provisioning
    (finalize removes the marker). This makes the AP resilient to a slow
    NetworkManager start, a transient nmcli failure, or the Ethernet cable being
    unplugged after boot — none of which the old one-shot startup handled."""
    while True:
        try:
            if not _provisioning():
                return
            _evaluate_provisioning()
        except Exception as e:
            print(f'[webui] provisioning loop error: {e}')
        time.sleep(20)


def _do_finalize():
    """Idempotent: drop AP/captive, remove marker, disable this being in
    provisioning mode. Never restarts the daemon (mode flips to normal)."""
    _teardown_ap()
    try:
        if os.path.exists(MARKER):
            os.remove(MARKER)
    except Exception as e:
        print(f'[webui] finalize: could not remove marker: {e}')
    state = _load_prov_state()
    state['finalized'] = True
    _save_prov_state(state)


def _sync_shell_account(username, password):
    """Mirror the admin credential into the Linux login used for SSH/console.

    This is the only moment the plaintext password exists on the device, so it
    is also the only moment the Linux account can be (re)provisioned. Failure is
    deliberately non-fatal: the admin account must be created even on an image
    where api_server is old or useradd is unavailable — the Settings → SSH panel
    can provision the login later from the same endpoint."""
    try:
        body, status = _proxy(API_BASE, '/shell_account', method='POST',
                              body={'username': username, 'password': password},
                              timeout=60)
        if status != 200 or not (body or {}).get('success'):
            print(f'[webui] shell account sync refused: {(body or {}).get("message")}')
            return False
        return True
    except Exception as e:
        print(f'[webui] shell account sync failed: {e}')
        return False


def _set_display_mode(mode, live):
    args = ['/usr/local/sbin/hifi-display-mode.sh', 'set', mode]
    if live:
        args.append('--live')
    try:
        subprocess.run(args, capture_output=True, text=True, timeout=30)
    except Exception as e:
        print(f'[webui] display-mode set failed: {e}')


# ── proxy to api_server (loopback, session-gated) ────────────────────
def _proxy(base, path, method='GET', body=None, timeout=15):
    req = urllib.request.Request(f'{base}{path}', method=method)
    data = None
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        req.add_header('Content-Type', 'application/json')
    # Forward the caller's UI language so api_server/sources_server (which sit
    # behind this proxy and never see the browser's own request directly) can
    # translate their own responses instead of always defaulting to Italian.
    req.add_header('X-UI-Lang', _lang())
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8')), resp.status
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode('utf-8')), e.code
        except Exception:
            return {'success': False, 'code': 'proxy.serviceUnavailable',
                    'message': _wt('proxy.serviceUnavailable', _lang())}, e.code
    except Exception as e:
        print(f'[webui] proxy {path} unreachable: {e}')
        return {'success': False, 'code': 'proxy.serviceUnreachable',
                'message': _wt('proxy.serviceUnreachable', _lang())}, 502


# Full admin whitelist (session required). (local_path, method) -> api path.
_AUTH_ROUTES = {
    ('/api/system/info', 'GET'): '/system_info',
    ('/api/system/stats', 'GET'): '/system_stats',
    ('/api/system/network_status', 'GET'): '/network_status',
    ('/api/system/network_info', 'GET'): '/network_info',
    ('/api/system/wifi_scan', 'GET'): '/wifi_scan',
    ('/api/system/wifi_connect', 'POST'): '/wifi_connect',
    ('/api/system/wired_dhcp', 'POST'): '/wired_dhcp',
    ('/api/system/ssh', 'GET'): '/ssh_status',
    ('/api/system/ssh', 'POST'): '/ssh_set',
    # Deliberately NOT in _PROVISION_ROUTES: during first setup the Linux login
    # is created server-side by _sync_shell_account(), over loopback.
    ('/api/system/shell_account', 'GET'): '/shell_account',
    ('/api/system/shell_account', 'POST'): '/shell_account',
    ('/api/system/tailscale', 'GET'): '/tailscale_status',
    ('/api/system/tailscale', 'POST'): '/tailscale_set',
    ('/api/system/tailscale_install', 'POST'): '/tailscale_install',
    ('/api/system/ota_channel', 'GET'): '/ota_channel',
    ('/api/system/ota_channel', 'POST'): '/ota_channel',
    ('/api/system/audio_devices', 'GET'): '/audio_devices',
    ('/api/system/audio_device', 'POST'): '/set_audio_device',
    ('/api/system/player_name', 'GET'): '/player_name',
    ('/api/system/player_name', 'POST'): '/player_name',
    # Renames BOTH the Linux hostname and the squeezelite/Bluetooth player
    # name together (see api_server.py's set_device_name) — the Settings.vue
    # "Audio" name field uses this instead of the player_name-only routes
    # above, so a rename also updates <name>.local, not just the LMS/BT name.
    ('/api/system/device_name', 'GET'): '/device_name',
    ('/api/system/device_name', 'POST'): '/device_name',
    ('/api/system/lms_role', 'GET'): '/lms_role',
    ('/api/system/lms_role', 'POST'): '/lms_role',
    ('/api/system/discover_lms', 'GET'): '/discover_lms',
    ('/api/system/tidal', 'GET'): '/tidal_status',
    ('/api/system/tidal', 'POST'): '/tidal_set',
    ('/api/system/dsp', 'GET'): '/dsp_status',
    ('/api/system/dsp', 'POST'): '/dsp_set',
    ('/api/system/dsp_presets', 'GET'): '/dsp_presets',
    ('/api/system/dsp_preset_save', 'POST'): '/dsp_preset_save',
    ('/api/system/dsp_preset_load', 'POST'): '/dsp_preset_load',
    ('/api/system/dsp_preset_delete', 'POST'): '/dsp_preset_delete',
    ('/api/system/display_mode', 'GET'): '/display_mode',
    ('/api/system/display_mode', 'POST'): '/display_mode',
    ('/api/system/player_enabled', 'GET'): '/player_enabled',
    ('/api/system/player_enabled', 'POST'): '/player_enabled',
    ('/api/system/ui_resolution', 'GET'): '/ui_resolution',
    ('/api/system/ui_resolution', 'POST'): '/ui_resolution',
    ('/api/system/ui_refresh', 'GET'): '/ui_refresh',
    ('/api/system/ui_refresh', 'POST'): '/ui_refresh',
    ('/api/system/timezone', 'GET'): '/timezone',
    ('/api/system/timezone', 'POST'): '/timezone',
    ('/api/system/timezones', 'GET'): '/timezones',
    ('/api/system/vu_meter', 'GET'): '/vu_meter',
    ('/api/system/vu_meter', 'POST'): '/vu_meter',
    ('/api/system/pointer_status', 'GET'): '/pointer_status',
    ('/api/system/pointer_set', 'POST'): '/pointer_set',
    ('/api/system/nowplaying_autoexpand', 'GET'): '/nowplaying_autoexpand',
    ('/api/system/nowplaying_autoexpand', 'POST'): '/nowplaying_autoexpand',
    ('/api/system/updates/app/check', 'GET'): '/app_update/check',
    ('/api/system/updates/app/apply', 'POST'): '/app_update/apply',
    ('/api/system/updates/app/status', 'GET'): '/app_update/status',
    ('/api/system/updates/system/check', 'GET'): '/system_update/check',
    ('/api/system/updates/system/apply', 'POST'): '/system_update/apply',
    ('/api/system/updates/system/status', 'GET'): '/system_update/status',
    ('/api/system/updates/os/check', 'GET'): '/os_update/check',
    ('/api/system/updates/os/apply', 'POST'): '/os_update/apply',
    ('/api/system/updates/os/status', 'GET'): '/os_update/status',
    # Sequenced multi-component update (server-side plan). Preferred over
    # applying the three components one by one from here: restarting hifi-api /
    # hifi-webui mid-run used to abort the sequence.
    ('/api/system/updates/apply_all', 'POST'): '/update/apply_all',
    ('/api/system/updates/status', 'GET'): '/update/status',
    ('/api/system/updates/dismiss', 'POST'): '/update/dismiss',
    ('/api/system/updates/lyrion/check', 'GET'): '/lyrion_update/check',
    ('/api/system/updates/lyrion/apply', 'POST'): '/lyrion_update/apply',
    ('/api/system/updates/lyrion/status', 'GET'): '/lyrion_update/status',
    ('/api/system/lyrion_channel', 'GET'): '/lyrion_channel',
    ('/api/system/lyrion_channel', 'POST'): '/lyrion_channel',
    ('/api/system/reboot', 'POST'): '/reboot',
    ('/api/system/shutdown', 'POST'): '/shutdown',
    ('/api/system/debug_plymouth', 'GET'): '/debug_plymouth',
    ('/api/system/debug_plymouth', 'POST'): '/debug_plymouth',
    ('/api/system/debug_kdump', 'GET'): '/debug_kdump',
    ('/api/system/debug_kdump', 'POST'): '/debug_kdump',
}

# Pre-auth set reachable during the captive window ONLY (no destructive ops).
_PROVISION_ROUTES = {
    ('/api/system/audio_devices', 'GET'): '/audio_devices',
    ('/api/system/audio_device', 'POST'): '/set_audio_device',
    ('/api/system/updates/lyrion/check', 'GET'): '/lyrion_update/check',
    ('/api/system/updates/lyrion/apply', 'POST'): '/lyrion_update/apply',
    ('/api/system/updates/lyrion/status', 'GET'): '/lyrion_update/status',
    ('/api/system/lyrion_channel', 'GET'): '/lyrion_channel',
    ('/api/system/lyrion_channel', 'POST'): '/lyrion_channel',
    # The wizard offers "use a server already on my network" before the account
    # exists, so the role switch and its discovery must be reachable pre-auth.
    ('/api/system/lms_role', 'GET'): '/lms_role',
    ('/api/system/lms_role', 'POST'): '/lms_role',
    ('/api/system/discover_lms', 'GET'): '/discover_lms',
}

# CAPTIVE probe endpoints answered with a redirect to the portal while the AP
# is up (this is what makes the phone auto-pop the setup page).
_CAPTIVE_PROBES = (
    '/generate_204', '/gen_204', '/hotspot-detect.html', '/library/test/success.html',
    '/connecttest.txt', '/ncsi.txt', '/redirect', '/success.txt', '/canonical.html',
)


# ── request guards: AP captive redirect + CSRF ────────────────────────
def _allowed_hosts():
    # Only consulted while an AP (setup or recovery) is up, to decide whether
    # a request is captive-portal-bound. Not a general access-control list --
    # see _guard() below for why the appliance doesn't gate normal traffic on
    # Host anymore.
    hosts = {socket.gethostname() + '.local', 'localhost', AP_ADDR}
    for ip in _local_ips():
        hosts.add(ip)
    return hosts


def _any_ap_active():
    """True while EITHER the first-boot setup AP or the post-provisioning
    network-loss recovery AP is up — the two are mutually exclusive in
    practice (the monitor skips entirely during provisioning) but share the
    same captive-probe/Host-allowlist/CSRF carve-outs below."""
    if _provisioning():
        return _load_prov_state().get('ap', {}).get('active', False)
    return _net_recovery['active']


@app.before_request
def _guard():
    # 1) Captive-AP redirect. While the setup/recovery hotspot is up, an
    # unrecognized Host is a captive-portal probe (or a client that resolved
    # the wrong name) — send it to the portal so phones/OSes auto-pop the
    # setup page. Outside an AP window there is no Host gate: the appliance
    # is meant to be reachable under any hostname/IP (custom mDNS name,
    # Tailscale, LAN IP, ...), and mutations are already protected
    # independently of Host by CSRF + the host-only, SameSite=Strict session
    # cookie (see _set_csrf_cookie/_bootstrap below) -- a spoofed Host header
    # alone can't forge either. The only unauthenticated reads reachable here
    # are /api/auth/status's two booleans and /api/netrecovery/status, which
    # isn't worth gating on Host.
    host = (request.host or '').split(':')[0]
    ap_up = _any_ap_active()
    if ap_up and host not in _allowed_hosts():
        return redirect(f'http://{AP_ADDR}/', code=302)

    # 2) Captive probes → portal (only while an AP is actually up).
    if ap_up and request.path in _CAPTIVE_PROBES:
        return redirect(f'http://{AP_ADDR}/', code=302)

    # 3) CSRF: double-submit token on every mutation. The token lives in a
    # non-HttpOnly cookie the SPA echoes back in X-CSRF-Token; a cross-site page
    # can send the cookie but cannot read it to set the header.
    # Exempt:
    #   * localhost — api_server.py makes server-to-server provisioning calls
    #     from 127.0.0.1 (no browser, no cookie), same loopback-trust as
    #     elsewhere.
    #   * /api/provision/* and /api/netrecovery/* — both captive flows are
    #     pre-auth and gated by physical/RF proximity + PSK instead; CSRF here
    #     protects the authenticated admin session, a separate surface.
    #   * forwarded sources paths — authenticated by the pairing bearer token
    #     (not cookies), so they're CSRF-immune by construction; requiring our
    #     cookie-bound header would just break the embedded :8080 SPA.
    if request.method in ('POST', 'PUT', 'DELETE', 'PATCH') \
            and request.remote_addr not in ('127.0.0.1', '::1') \
            and not request.path.startswith('/api/provision/') \
            and not request.path.startswith('/api/netrecovery/') \
            and not any(request.path == p or request.path.startswith(p + '/')
                        for p in _SOURCES_FWD_PREFIXES):
        cookie = request.cookies.get('csrf')
        header = request.headers.get('X-CSRF-Token')
        if not cookie or not header or not secrets.compare_digest(cookie, header):
            return jsonify({'success': False, 'code': 'auth.csrfInvalid',
                            'message': _wt('auth.csrfInvalid', _lang())}), 403


def _frame_ancestors():
    # Lyrion's web UI lives on the SAME host, port 9000, and its Material skin
    # carries an "Osmium Admin" entry that opens this admin in an iframe (see
    # the actions.json asset in distro/.../hifi-lms-skin). A different port is a
    # different *origin* — so it must be named here — but the same *site*, which
    # is why the SameSite=Strict session cookie still travels into that frame.
    host = request.host
    host = host[:host.index(']') + 1] if host.startswith('[') and ']' in host \
        else host.split(':')[0]
    return f"'self' http://{host}:9000 https://{host}:9000"


@app.after_request
def _set_csrf_cookie(resp):
    # Ensure a CSRF cookie exists so the SPA can read + echo it. Not HttpOnly by
    # design (double-submit needs JS to read it). Not Secure either: plain
    # HTTP, no TLS (see the module docstring's security-model note).
    if not request.cookies.get('csrf'):
        resp.set_cookie('csrf', secrets.token_urlsafe(24), samesite='Strict',
                        secure=False, httponly=False)
    # One framing policy for every response, so the whole admin (including the
    # nested /sources-app frame inside Settings) works both standalone and
    # embedded in Lyrion. X-Frame-Options cannot express "self + that origin"
    # and browsers ignore it once frame-ancestors is present, so it is not set.
    resp.headers['Content-Security-Policy'] = \
        f'frame-ancestors {_frame_ancestors()}'
    # No API answer may ever be cached. These replies are per-session state
    # (auth status above all), and a browser that reuses a cached
    # /api/auth/status keeps showing the admin to someone who just logged out
    # -- the SPA asks the server on every navigation precisely so it doesn't
    # have to trust its own memory. `Vary: Cookie` alone isn't enough: after
    # logout the cookie is gone, which is a *different* cache key, but the
    # pre-login (cookie-less) entry from before login can match it.
    if request.path.startswith('/api/'):
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
    return resp


def _require_session():
    if not _logged_in():
        return jsonify({'success': False, 'code': 'auth.required',
                        'message': _wt('auth.required', _lang())}), 401
    return None


# ── auth endpoints ───────────────────────────────────────────────────
@app.route('/api/auth/status', methods=['GET'])
def auth_status():
    return jsonify({
        'has_account': _get_user() is not None,
        'logged_in': _logged_in(),
        'provisioning': _provisioning(),
    })


def _account_setup(username, password):
    # Create the admin account — allowed ONLY when none exists yet (first setup).
    # Shared by /api/auth/setup (HTTPS, port 443) and /api/provision/create_account
    # (the AP-hotspot captive wizard, plain HTTP — see the latter for why it
    # can't just call this route directly).
    if _get_user() is not None:
        return {'success': False, 'code': 'auth.accountExists',
                'message': _wt('auth.accountExists', _lang())}, 409
    if len(username) < 3 or len(password) < 8:
        return {'success': False, 'message': _wt('auth.setupFieldsTooShort', _lang())}, 400
    _create_user(username, password)
    shell_ok = _sync_shell_account(username, password)
    session.clear()
    session['auth'] = True
    session['sv'] = _session_version()
    session.permanent = True
    return {'success': True, 'shell_account': shell_ok}, 200


@app.route('/api/auth/setup', methods=['POST'])
def auth_setup():
    data = request.get_json(silent=True) or {}
    body, status = _account_setup((data.get('username') or '').strip(), data.get('password') or '')
    return jsonify(body), status


@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    ip = request.remote_addr
    if _rate_limited(ip):
        return jsonify({'success': False, 'message': _wt('auth.tooManyAttempts', _lang())}), 429
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    row = _get_user()
    if not row or row['username'] != username or not check_password_hash(row['password_hash'], password):
        _record_fail(ip)
        return jsonify({'success': False, 'code': 'auth.invalidCredentials',
                        'message': _wt('auth.invalidCredentials', _lang())}), 401
    session.clear()
    session['auth'] = True
    session['sv'] = _session_version()
    session.permanent = True
    return jsonify({'success': True})


@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    session.clear()
    return jsonify({'success': True})


@app.route('/api/auth/change-password', methods=['POST'])
def auth_change_password():
    denied = _require_session()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    current = data.get('current_password') or ''
    new = data.get('new_password') or ''
    username = (data.get('username') or (_get_user()['username'] if _get_user() else '')).strip()
    if not _verify_password(current):
        return jsonify({'success': False, 'message': _wt('auth.wrongCurrentPassword', _lang())}), 403
    if len(username) < 3 or len(new) < 8:
        return jsonify({'success': False, 'message': _wt('auth.setupFieldsTooShort', _lang())}), 400
    _create_user(username, new)
    shell_ok = _sync_shell_account(username, new)
    _bump_session_version()  # log every other session out
    session['sv'] = _session_version()  # keep THIS session valid
    return jsonify({'success': True, 'shell_account': shell_ok})


# ── provisioning endpoints (pre-auth: physical/RF proximity is the trust) ──
@app.route('/api/provision/status', methods=['GET'])
def provision_status():
    if not _provisioning():
        # `completed` tells the kiosk that setup ran through the provisioning
        # flow (possibly entirely from the web, where the Electron localStorage
        # flag was never written), so it must NOT show its first-run wizard —
        # e.g. headless setup finished on the phone, then GUI re-enabled later.
        done = _load_prov_state()
        return jsonify({'pending': False,
                        'completed': bool(done.get('finalized')),
                        'mode': done.get('mode')})
    state = _load_prov_state()
    return jsonify({
        'pending': True,
        'stage': state.get('stage'),
        'mode': state.get('mode'),
        'claimed_by': state.get('claimed_by'),
        'ap': state.get('ap', {}),
        'networks': state.get('networks', []),
        'networks_cached_at': state.get('networks_cached_at'),
        'error': state.get('error'),
        'wired': _wired_connected(),
        'has_account': _get_user() is not None,
    })


@app.route('/api/provision/use_wired', methods=['POST'])
def provision_use_wired():
    """Use the wired connection for the box. ACTIVELY brings the Ethernet
    interface up via DHCP (a fresh unit may not have auto-connected it yet — the
    on-screen wizard's 'Wired' button does the same), then marks the network step
    done. Verified so we never mark it done with no real uplink (which would
    strand the box after the hotspot drops)."""
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    # api_server.wired_dhcp() runs `nmcli device connect <eth>` and returns the IP.
    body, _ = _proxy(API_BASE, '/wired_dhcp', method='POST', body={}, timeout=50)
    body = body or {}
    ok = bool(body.get('success') and body.get('ip')) or _wired_connected()
    if not ok:
        return jsonify({'success': False,
                        'message': body.get('message') or 'Nessuna connessione via cavo rilevata'}), 409
    with _prov_lock:
        state = _load_prov_state()
        state['stage'] = 'network-ok'
        state['error'] = None
        _save_prov_state(state)
    return jsonify({'success': True, 'ip': body.get('ip')})


@app.route('/api/provision/wifi_connect', methods=['POST'])
def provision_wifi_connect():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    data = request.get_json(silent=True) or {}
    ssid = (data.get('ssid') or '').strip()
    password = data.get('password') or ''
    # Reply first: the join itself (with its scan-and-retry dance) can take a
    # while, and the on-screen panel just needs to know it started.
    threading.Thread(target=_bg_connect, args=(ssid, password), daemon=True).start()
    return jsonify({'success': True, 'dropping_ap': True})


@app.route('/api/provision/wifi_rescan', methods=['POST'])
def provision_wifi_rescan():
    # Synchronous on purpose (unlike wifi_connect above): the caller needs
    # the real network list back, not just an acknowledgement that something
    # started.
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    nets = _live_wifi_rescan()
    return jsonify({'success': True, 'networks': nets})


def _bg_connect(ssid, password):
    with _prov_lock:
        state = _load_prov_state()
        state['stage'] = 'connecting'
        state['ssid_attempt'] = ssid
        state['error'] = None
        _save_prov_state(state)
        ok, err, ap = _connect_wifi(ssid, password, ap_fallback=False)
        state = _load_prov_state()
        if ok:
            state['stage'] = 'network-ok'
            state['ap'] = {'active': False, 'supported': True}
            state['error'] = None
        else:
            state['stage'] = 'failed'
            state['ap'] = {**(ap or {'active': False, 'ssid': None, 'psk': None}),
                           'supported': True, 'error': err}
            state['error'] = err
        _save_prov_state(state)


@app.route('/api/provision/claim_mode', methods=['POST'])
def provision_claim_mode():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    data = request.get_json(silent=True) or {}
    mode = (data.get('mode') or '').strip()
    source = (data.get('source') or 'web').strip()
    # Three-way: 'gui' (screen), 'headless' (no screen, player on — remote
    # control only), 'off' (no screen AND the player itself never plays audio
    # locally — a server-only unit; see api_server.py's player_enabled).
    if mode not in ('gui', 'headless', 'off'):
        return jsonify({'success': False, 'code': 'provision.invalidMode',
                        'message': _wt('provision.invalidMode', _lang())}), 400
    with _prov_lock:
        state = _load_prov_state()
        if state.get('mode') and state.get('claimed_by') and state.get('claimed_by') != source:
            # Someone already claimed (first wins).
            return jsonify({'success': False, 'code': 'provision.modeAlreadyClaimed',
                            'message': _wt('provision.modeAlreadyClaimed', _lang()),
                            'mode': state.get('mode'), 'claimed_by': state.get('claimed_by')}), 409
        state['mode'] = mode
        state['claimed_by'] = source
        _save_prov_state(state)
    # Persist only — never live or finalize here. The on-screen kiosk has no
    # setup steps of its own any more (it just shows the AP/QR until finalize
    # lands), so the phone always keeps driving the rest of setup (audio,
    # lyrion, sources, timezone) after mode is picked, whichever mode it was.
    # The hotspot therefore stays up, and the display-mode switch only goes
    # live at the explicit "finish" step (provision_finalize below).
    _set_display_mode('gui' if mode == 'gui' else 'headless', live=False)
    if mode == 'off':
        try:
            _proxy(API_BASE, '/player_enabled', method='POST', body={'enabled': False})
        except Exception as e:
            print(f'[webui] provision claim_mode: player disable failed: {e}')
    return jsonify({'success': True, 'mode': mode})


@app.route('/api/provision/finalize', methods=['POST'])
def provision_finalize():
    if not _provisioning():
        return jsonify({'success': True})  # already done
    data = request.get_json(silent=True) or {}
    want_reboot = bool(data.get('reboot'))
    with _prov_lock:
        state = _load_prov_state()
        mode = state.get('mode', 'gui')
        # live=True: this is the deferred half of the screen+headless path (see
        # provision_claim_mode) — the on-screen kiosk was left running the
        # 'headless-wait' step on purpose so it could show the hotspot/URL, but
        # once the web side finishes setup here, that screen must actually go
        # away, not just have the persisted target changed for next boot. This
        # daemon (hifi-webui.service, WantedBy=multi-user.target) survives the
        # isolate either way, so the HTTP response still returns normally.
        _set_display_mode(mode, live=True)
        _do_finalize()
    if want_reboot:
        # Used after restoring a backup: the restored archive can include
        # NetworkManager profiles, timezone, DSP/audio config and Lyrion
        # prefs written straight to disk — a reboot is the simple, robust way
        # to have every affected service pick all of that up cleanly. Issued
        # from here, inline, rather than as a separate client call to
        # /api/provision/reboot: that endpoint is gated on _provisioning(),
        # and _do_finalize() just removed the marker it checks — a second
        # request would always be rejected (this is why restore never
        # actually rebooted the box).
        _proxy(API_BASE, '/reboot', method='POST', body={}, timeout=15)
    return jsonify({'success': True})


def _boot_mode():
    """Mirrors api_server.py's get_boot_mode(): 'installer' if this live
    session was booted from the 'Install Osmium Sound' menu entry
    (hifi.installer=1), else 'live'. Read directly from /proc/cmdline rather
    than proxied — this is checked on every captive page load, and it's the
    same machine, so there's no reason to pay an HTTP round-trip for it."""
    try:
        with open('/proc/cmdline') as f:
            cmdline = f.read()
    except Exception:
        cmdline = ''
    return 'installer' if 'hifi.installer=1' in cmdline.split() else 'live'


# ── provisioning endpoints: setup-flow branch (audio / lyrion / sources /
#    timezone / restore) — all pre-auth, same physical/RF trust as the
#    network + mode endpoints above. Each simply forwards to the already-
#    authenticated-by-loopback api_server/sources_server endpoint the regular
#    Settings UI uses, gated here by _provisioning() instead of a session. ──
@app.route('/api/provision/pointer', methods=['GET'])
def provision_pointer_get():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    body, status = _proxy(API_BASE, '/pointer_status', method='GET')
    return jsonify(body), status


@app.route('/api/provision/pointer', methods=['POST'])
def provision_pointer_set():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    data = request.get_json(silent=True) or {}
    body, status = _proxy(API_BASE, '/pointer_set', method='POST',
                          body={'enable': bool(data.get('enable'))}, timeout=20)
    return jsonify(body), status


@app.route('/api/provision/audio_devices', methods=['GET'])
def provision_audio_devices():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    body, status = _proxy(API_BASE, '/audio_devices', method='GET')
    return jsonify(body), status


@app.route('/api/provision/set_audio_device', methods=['POST'])
def provision_set_audio_device():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    data = request.get_json(silent=True) or {}
    body, status = _proxy(API_BASE, '/set_audio_device', method='POST',
                          body={'device': data.get('device')}, timeout=30)
    return jsonify(body), status


@app.route('/api/provision/lyrion_mode', methods=['GET'])
def provision_lyrion_mode_get():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    body, status = _proxy(API_BASE, '/lms_role', method='GET')
    return jsonify(body), status


@app.route('/api/provision/lyrion_mode', methods=['POST'])
def provision_lyrion_mode_set():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    data = request.get_json(silent=True) or {}
    body, status = _proxy(API_BASE, '/lms_role', method='POST',
                          body={'mode': data.get('mode'), 'host': data.get('host')}, timeout=30)
    return jsonify(body), status


@app.route('/api/provision/discover_lms', methods=['GET'])
def provision_discover_lms():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    body, status = _proxy(API_BASE, '/discover_lms', method='GET', timeout=20)
    return jsonify(body), status


@app.route('/api/provision/set_name', methods=['POST'])
def provision_set_name():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    data = request.get_json(silent=True) or {}
    body, status = _proxy(API_BASE, '/device_name', method='POST',
                          body={'name': (data.get('name') or '').strip()}, timeout=20)
    return jsonify(body), status


@app.route('/api/provision/create_account', methods=['POST'])
def provision_create_account():
    # Same account /api/auth/setup creates, reachable from the AP-hotspot
    # captive wizard (10.42.0.1). /api/auth/setup itself isn't under
    # /api/provision/*, so it's subject to the CSRF check above -- which the
    # captive page, still mid-provisioning, can't necessarily satisfy yet.
    # This route lives under the already-exempted /api/provision/ prefix
    # instead.
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    data = request.get_json(silent=True) or {}
    body, status = _account_setup((data.get('username') or '').strip(), data.get('password') or '')
    return jsonify(body), status


# ── Mandatory OTA update gate, right after the network step ──────────
# TEMPORARY (explicit request): checks BOTH prod and dev channels, regardless
# of the device's own OTA channel setting (always 'prod' this early) -- a
# prod update applies automatically, a dev-only one needs the operator's
# confirmation in the wizard first. Drop the dev check once this has shipped
# to production and prod-only is enough again (see wizard_update_check() in
# api_server.py).
@app.route('/api/provision/update_check', methods=['GET'])
def provision_update_check():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    body, status = _proxy(API_BASE, '/wizard_update_check', method='GET', timeout=25)
    return jsonify(body), status


@app.route('/api/provision/update_apply', methods=['POST'])
def provision_update_apply():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    data = request.get_json(silent=True) or {}
    body, status = _proxy(API_BASE, '/wizard_update_apply', method='POST',
                          body={'channel': data.get('channel')}, timeout=20)
    return jsonify(body), status


@app.route('/api/provision/update_status', methods=['GET'])
def provision_update_status():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    body, status = _proxy(API_BASE, '/update/status', method='GET')
    return jsonify(body), status


# ── Lyrion install check/trigger (local mode only) ───────────────────
# hifi-firstboot.service normally installs Lyrion on its own, on the first
# real (non-live) boot — but it only retries "on the next boot" if it had no
# network yet, and the setup wizard's own network step can easily finish
# after that first attempt already failed. Without this check the wizard
# would silently leave a unit with no Lyrion installed at all once "local"
# mode is chosen; mirrors the on-screen wizard's old install-fallback logic.
@app.route('/api/provision/lyrion_check', methods=['GET'])
def provision_lyrion_check():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    body, status = _proxy(API_BASE, '/lyrion_update/check', method='GET', timeout=20)
    return jsonify(body), status


@app.route('/api/provision/lyrion_install', methods=['POST'])
def provision_lyrion_install():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    data = request.get_json(silent=True) or {}
    body, status = _proxy(API_BASE, '/lyrion_update/apply', method='POST',
                          body={'channel': data.get('channel')}, timeout=30)
    return jsonify(body), status


@app.route('/api/provision/lyrion_status', methods=['GET'])
def provision_lyrion_status():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    body, status = _proxy(API_BASE, '/lyrion_update/status', method='GET')
    return jsonify(body), status


# LMS skin choice (Osmium / Material) — the wizard's step-lms-skin. Lives on
# sources_server.py (:8080), which owns all Lyrion file operations.
@app.route('/api/provision/lms_skin', methods=['GET', 'POST'])
def provision_lms_skin():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    if request.method == 'POST':
        body, status = _proxy(SOURCES_BASE, '/api/lms_skin', method='POST',
                              body=request.get_json(silent=True) or {}, timeout=20)
    else:
        body, status = _proxy(SOURCES_BASE, '/api/lms_skin', method='GET', timeout=20)
    return jsonify(body), status


@app.route('/api/provision/lms_skin_status', methods=['GET'])
def provision_lms_skin_status():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    body, status = _proxy(SOURCES_BASE, '/api/lms_skin_status', method='GET')
    return jsonify(body), status


# Lyrion's own first-run setup (plugins + language + wizardDone) — the wizard's
# step-lms-plugins. Same home as the skin above: sources_server.py owns every
# Lyrion file/pref operation.
@app.route('/api/provision/lms_setup', methods=['GET', 'POST'])
def provision_lms_setup():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    if request.method == 'POST':
        body, status = _proxy(SOURCES_BASE, '/api/lms_setup', method='POST',
                              body=request.get_json(silent=True) or {}, timeout=20)
    else:
        body, status = _proxy(SOURCES_BASE, '/api/lms_setup', method='GET', timeout=20)
    return jsonify(body), status


@app.route('/api/provision/lms_setup_status', methods=['GET'])
def provision_lms_setup_status():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    body, status = _proxy(SOURCES_BASE, '/api/lms_setup_status', method='GET')
    return jsonify(body), status


@app.route('/api/provision/sources', methods=['GET'])
def provision_sources_list():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    body, status = _proxy(SOURCES_BASE, '/api/sources', method='GET')
    return jsonify(body), status


@app.route('/api/provision/sources/local', methods=['POST'])
def provision_sources_local():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    body, status = _proxy(SOURCES_BASE, '/api/sources/local', method='POST',
                          body=request.get_json(silent=True) or {})
    return jsonify(body), status


@app.route('/api/provision/sources/smb', methods=['POST'])
def provision_sources_smb():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    body, status = _proxy(SOURCES_BASE, '/api/sources/smb', method='POST',
                          body=request.get_json(silent=True) or {})
    return jsonify(body), status


@app.route('/api/provision/sources/<sid>', methods=['DELETE'])
def provision_sources_delete(sid):
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    body, status = _proxy(SOURCES_BASE, f'/api/sources/{urllib.parse.quote(sid)}', method='DELETE')
    return jsonify(body), status


@app.route('/api/provision/timezone', methods=['GET'])
def provision_timezone_get():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    tz, _ = _proxy(API_BASE, '/timezone', method='GET')
    tzs, _ = _proxy(API_BASE, '/timezones', method='GET')
    return jsonify({'timezone': (tz or {}).get('timezone'),
                    'timezones': (tzs or {}).get('timezones', [])})


@app.route('/api/provision/set_timezone', methods=['POST'])
def provision_set_timezone():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    data = request.get_json(silent=True) or {}
    body, status = _proxy(API_BASE, '/timezone', method='POST',
                          body={'timezone': data.get('timezone')}, timeout=20)
    return jsonify(body), status


@app.route('/api/provision/reboot', methods=['POST'])
def provision_reboot():
    # Used after a restore: the restored archive can include NetworkManager
    # profiles, timezone, DSP/audio config and Lyrion prefs written straight
    # to disk — a reboot is the simple, robust way to have every affected
    # service pick all of that up cleanly, instead of trying to hot-reload
    # each one individually here.
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    body, status = _proxy(API_BASE, '/reboot', method='POST', body={}, timeout=15)
    return jsonify(body), status


@app.route('/api/provision/restore', methods=['POST'])
def provision_restore():
    # Multipart (archive file + passphrase), relayed raw — same shape as the
    # authenticated Settings restore, just gated by provisioning instead of a
    # session. sources_server exempts our loopback origin from its own token
    # check exactly like every other loopback forward in this file.
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    return _forward_to_sources('/api/restore')


@app.route('/api/provision/restore/status', methods=['GET'])
def provision_restore_status():
    # /api/restore (above) is fire-and-forget: it returns as soon as the
    # restore job is *started*, not finished (sources_server runs it in a
    # background thread — see _run_restore_async). The wizard polls this to
    # find out when it has actually completed before finalizing/rebooting.
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    return _forward_to_sources('/api/restore/status')


# ── provisioning endpoints: installer branch (disk-imaging, no OS on disk
#    yet — booted with hifi.installer=1). Pre-auth for the same reason as
#    everything above: a fresh live session has no account/session concept. ──
@app.route('/api/provision/install_disks', methods=['GET'])
def provision_install_disks():
    if _boot_mode() != 'installer':
        return jsonify({'success': False, 'code': 'provision.notInstaller',
                        'message': _wt('provision.notInstaller', _lang())}), 409
    body, status = _proxy(API_BASE, '/install/disks', method='GET')
    return jsonify(body), status


@app.route('/api/provision/install_start', methods=['POST'])
def provision_install_start():
    if _boot_mode() != 'installer':
        return jsonify({'success': False, 'code': 'provision.notInstaller',
                        'message': _wt('provision.notInstaller', _lang())}), 409
    data = request.get_json(silent=True) or {}
    body, status = _proxy(API_BASE, '/install/start', method='POST',
                          body={'device': data.get('device')}, timeout=20)
    return jsonify(body), status


@app.route('/api/provision/install_status', methods=['GET'])
def provision_install_status():
    if _boot_mode() != 'installer':
        return jsonify({'success': False, 'code': 'provision.notInstaller',
                        'message': _wt('provision.notInstaller', _lang())}), 409
    body, status = _proxy(API_BASE, '/install/status', method='GET')
    return jsonify(body), status


# ── network-loss recovery endpoints (pre-auth: same RF/PSK trust as setup) ──
# Deliberately separate from /api/provision/*: this is for an ALREADY
# configured unit that lost connectivity, not first-boot setup — no account,
# mode or wizard concept exists here, only "get the network working again".
@app.route('/api/netrecovery/status', methods=['GET'])
def netrecovery_status():
    with _net_lock:
        return jsonify({
            'active': _net_recovery['active'],
            'ssid': _net_recovery['ssid'],
            'networks': _net_recovery['networks'],
            'networks_cached_at': _net_recovery['networks_cached_at'],
            'error': _net_recovery['error'],
        })


@app.route('/api/netrecovery/wifi_connect', methods=['POST'])
def netrecovery_wifi_connect():
    if not _net_recovery['active']:
        return jsonify({'success': False, 'message': 'Nessun recupero rete in corso'}), 409
    data = request.get_json(silent=True) or {}
    ssid = (data.get('ssid') or '').strip()
    password = data.get('password') or ''
    # Reply first (the AP is about to drop; the phone must know to expect it).
    threading.Thread(target=_bg_netrecovery_connect, args=(ssid, password), daemon=True).start()
    return jsonify({'success': True, 'dropping_ap': True})


def _bg_netrecovery_connect(ssid, password):
    ok, err, ap = _connect_wifi(ssid, password)
    with _net_lock:
        if ok:
            # Connected: _connect_wifi already tore the AP down; the network
            # monitor's next tick confirms connectivity and would reach the
            # same state, but clearing it here immediately is more responsive.
            _net_recovery.update({'active': False, 'ssid': None, 'psk': None, 'error': None})
        else:
            # _connect_wifi already tried to re-raise the AP on failure — reflect
            # what actually happened, not what was hoped for (the re-raise
            # itself can fail too).
            ap = ap or {'active': False, 'ssid': None, 'psk': None}
            _net_recovery.update({'error': err, **ap})


# ── generic system proxy (partitioned) ───────────────────────────────
def _handle_proxy(local_path, method):
    key = (local_path, method)
    if _provisioning() and not _logged_in():
        table = _PROVISION_ROUTES
    else:
        denied = _require_session() if not _provisioning() else None
        # In normal mode: must be logged in. In provisioning + logged in: full.
        if not _provisioning() and denied:
            return denied
        table = _AUTH_ROUTES
    api_path = table.get(key)
    if not api_path:
        return jsonify({'success': False, 'code': 'proxy.endpointNotAllowed',
                        'message': _wt('proxy.endpointNotAllowed', _lang())}), 403
    body = request.get_json(silent=True) if method != 'GET' else None
    data, status = _proxy(API_BASE, api_path, method=method, body=body,
                          timeout=220 if 'debug_kdump' in api_path  # may apt-get install kdump-tools
                          else 200 if 'tailscale_install' in api_path
                          else 90 if 'apply' in api_path or 'dsp' in api_path
                          or 'tailscale' in api_path or 'ssh' in api_path
                          or 'debug_plymouth' in api_path else 15)
    return jsonify(data), status


def _register_proxy_routes():
    seen = set()
    for (local_path, method) in list(_AUTH_ROUTES.keys()) + list(_PROVISION_ROUTES.keys()):
        if (local_path, method) in seen:
            continue
        seen.add((local_path, method))

        def _make(lp, m):
            def _view():
                return _handle_proxy(lp, m)
            return _view
        app.add_url_rule(local_path, endpoint=f'proxy_{method}_{local_path}',
                         view_func=_make(local_path, method), methods=[method])


_register_proxy_routes()


# ── destructive: factory reset (session + admin-password reauth) ─────
@app.route('/api/system/factory_reset', methods=['POST'])
def factory_reset():
    # NOT in the generic proxy table on purpose: a stolen session cookie alone
    # must not be able to wipe the box. Re-validate the admin password here
    # before proxying to api_server's loopback /factory_reset.
    denied = _require_session()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    if not _verify_password(data.get('password') or ''):
        return jsonify({'success': False, 'code': 'auth.wrongPassword',
                        'message': _wt('auth.wrongPassword', _lang())}), 403
    body, status = _proxy(API_BASE, '/factory_reset', method='POST', body={})
    return jsonify(body), status


# ── sources app (:8080 SPA) embedded via reverse proxy ────────────────
# Reverse-proxied through this daemon (same origin as the Settings page that
# embeds it, single session/pairing-token story) rather than pointed straight
# at :8080:
#   GET /sources-app            (session) → mint a pairing token, redirect with it
#   GET /sources-app?token=T    (token)   → proxied SPA HTML from loopback :8080
#   /api/<sources paths>        (token)   → transparently forwarded to :8080
#
# SECURITY: sources_server exempts 127.0.0.1 from its own token check, and our
# forwards originate from loopback — so WE must enforce the token here, exactly
# mirroring sources' own auth (bearer/?token=, constant-time compare). Token
# auth (not cookies) also means these routes are CSRF-immune by design.
_SOURCES_FWD_PREFIXES = ('/api/sources', '/api/usb', '/api/internal', '/api/apply',
                         '/api/backup', '/api/restore', '/api/cd', '/api/dsp', '/api/local',
                         '/api/playlistdir')
_PAIR_TOKENS_FILE = '/etc/hifi-pairing-tokens.json'


def _sources_token_ok():
    auth = request.headers.get('Authorization', '')
    token = auth[len('Bearer '):] if auth.startswith('Bearer ') else None
    if not token:
        token = request.args.get('token') or None
    if not token:
        return False
    try:
        with open(_PAIR_TOKENS_FILE) as f:
            tokens = json.load(f)
    except Exception:
        return False
    return any(secrets.compare_digest(t.get('token', ''), token) for t in tokens)


def _forward_to(base, path, timeout=120, service_label='servizio'):
    """Transparent forward (method, query, body, auth, content-type) to a
    loopback service (sources_server or api_server); streams the raw response
    back as-is (may be a file — Content-Disposition is preserved so a download
    keeps its filename)."""
    qs = request.query_string.decode('utf-8')
    url = f'{base}{path}' + (f'?{qs}' if qs else '')
    req = urllib.request.Request(url, method=request.method)
    for h in ('Authorization', 'Content-Type'):
        v = request.headers.get(h)
        if v:
            req.add_header(h, v)
    body = request.get_data() if request.method in ('POST', 'PUT', 'PATCH') else None
    try:
        with urllib.request.urlopen(req, data=body, timeout=timeout) as resp:
            out = Response(resp.read(), status=resp.status,
                           content_type=resp.headers.get('Content-Type', 'application/octet-stream'))
            disposition = resp.headers.get('Content-Disposition')
    except urllib.error.HTTPError as e:
        out = Response(e.read(), status=e.code,
                       content_type=e.headers.get('Content-Type', 'application/json'))
        disposition = None
    except Exception as e:
        print(f'[webui] {service_label} forward {path} failed: {e}')
        return jsonify({'success': False, 'message': _wt('proxy.serviceUnreachable', _lang())}), 502
    if disposition:
        out.headers['Content-Disposition'] = disposition
    # Framing policy (this response is embedded by our own Settings page, and
    # the whole admin may itself be embedded in Lyrion) is set centrally in
    # _set_csrf_cookie's after_request hook.
    return out


def _forward_to_sources(path):
    return _forward_to(SOURCES_BASE, path, timeout=120, service_label='sorgenti')


def _forward_to_api(path, timeout=60):
    return _forward_to(API_BASE, path, timeout=timeout, service_label='sistema')


@app.route('/sources-app', methods=['GET'])
def sources_app():
    # Entry point for the Settings iframe. With a valid token → serve the SPA
    # HTML; otherwise require the admin session, mint a fresh token via
    # loopback (minting is localhost-only in sources_server; the session is the
    # equivalent trust anchor), and redirect so the SPA finds ?token= in its URL.
    if _sources_token_ok():
        return _forward_to_sources('/')
    denied = _require_session()
    if denied:
        return denied
    body, status = _proxy(SOURCES_BASE, '/api/pair/token', method='POST', body={})
    token = (body or {}).get('token')
    if not token:
        return jsonify({'success': False, 'code': 'sources.pairUnavailable',
                        'message': 'Pairing is unavailable.'}), 502
    # Keep the caller's other params (lang= picks the page language, back= gives
    # it a way home) — dropping them here would send the user to an Italian
    # dead-end page. Only the params the page actually reads (QS.get() in
    # sources_server's INDEX_HTML, _req_lang()), each URL-encoded, and only
    # ever as the tail of our own fixed "/sources-app?token=..." prefix — so
    # no request value can pick the destination, just the query it carries.
    extra = ''.join('&' + key + '=' + urllib.parse.quote(request.args[key])
                    for key in ('lang', 'back', 'setup') if key in request.args)
    return redirect('/sources-app?token=' + token + extra, code=302)


@app.route('/api/<path:rest>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def sources_forward(rest):
    # Catch-all under /api/ — Werkzeug matches our explicit /api/system|auth|
    # provision|lyrion rules first, so only unclaimed paths land here. Forward
    # the known sources prefixes, token-gated; everything else is a 404.
    path = '/api/' + rest
    if not any(path == p or path.startswith(p + '/') for p in _SOURCES_FWD_PREFIXES):
        return jsonify({'success': False, 'code': 'proxy.unknownEndpoint',
                        'message': _wt('proxy.unknownEndpoint', _lang())}), 404
    if not _sources_token_ok():
        return jsonify({'success': False, 'code': 'pairing.tokenInvalid',
                        'message': _wt('pairing.tokenInvalid', _lang())}), 401
    return _forward_to_sources(path)


# ── DSP room-correction filter (FIR) — session-gated, forwarded raw ──
# The FIR file itself (status/upload/delete) lives on sources_server.py (:8080),
# not api_server, so it can't go through the ordinary /api/system JSON proxy.
# Unlike the embedded sources SPA (/sources-app, token-gated for a bare
# browser), this route is reached from OUR authenticated Settings page, so we
# gate it with the webui session instead: _forward_to_sources() then relays the
# raw request (incl. the multipart upload body) to loopback :8080, where
# sources_server's own pairing check is exempted for 127.0.0.1 exactly like our
# other loopback calls — no token needed for this one.
@app.route('/api/system/dsp_fir', methods=['GET', 'POST', 'DELETE'])
def dsp_fir_proxy():
    denied = _require_session()
    if denied:
        return denied
    return _forward_to_sources('/api/dsp/fir')


# ── LMS skin (Osmium / Material) — session-gated forward to sources_server ──
# Same story as the FIR filter above: the skin logic lives on sources_server
# (:8080, owns all Lyrion file ops), reached from OUR authenticated Settings
# page, so the webui session is the gate.
@app.route('/api/system/lms_skin', methods=['GET', 'POST'])
def lms_skin_proxy():
    denied = _require_session()
    if denied:
        return denied
    return _forward_to_sources('/api/lms_skin')


@app.route('/api/system/lms_skin_status', methods=['GET'])
def lms_skin_status_proxy():
    denied = _require_session()
    if denied:
        return denied
    return _forward_to_sources('/api/lms_skin_status')


# Playlist folder (Sources -> Advanced). Same story as lms_skin: it is a Lyrion
# pref, so it lives on sources_server.py, and this is the session-gated door
# the web admin's own Settings page comes through.
@app.route('/api/system/playlistdir', methods=['GET', 'POST'])
def playlistdir_proxy():
    denied = _require_session()
    if denied:
        return denied
    return _forward_to_sources('/api/playlistdir')


# ── Backup / restore — session-gated forward to sources_server ───────
# The archive lives on sources_server.py (:8080) — same story as the FIR
# filter above: this is OUR authenticated Settings page, so the webui session
# is the gate, and the raw request (including the multipart restore upload,
# and binary download responses) is relayed as-is via _forward_to_sources().
# /api/backup is already in _SOURCES_FWD_PREFIXES, but only reachable there
# under the pairing TOKEN (phone/QR flow) — these routes are the session-gated
# equivalent for the web-admin UI, which has no token to offer.
@app.route('/api/system/backup', methods=['GET'])
def backup_download_now_proxy():
    denied = _require_session()
    if denied:
        return denied
    return _forward_to_sources('/api/backup')


@app.route('/api/system/backup/<path:rest>', methods=['GET', 'POST', 'DELETE'])
def backup_proxy(rest):
    denied = _require_session()
    if denied:
        return denied
    return _forward_to_sources('/api/backup/' + rest)


@app.route('/api/system/restore', methods=['POST'])
def restore_proxy():
    denied = _require_session()
    if denied:
        return denied
    return _forward_to_sources('/api/restore')


@app.route('/api/system/restore/status', methods=['GET'])
def restore_status_proxy():
    denied = _require_session()
    if denied:
        return denied
    return _forward_to_sources('/api/restore/status')


# ── Sources (music library sources) — session-gated forward to sources_server
# Same story as backup/restore/DSP FIR above: sources_server.py's own
# `/api/sources`, `/api/usb`, `/api/internal/*`, `/api/apply` are otherwise
# only reachable through the pairing-TOKEN catch-all (sources_forward()
# below), which the web-admin's native Sources page (SourcesPanel.vue) has no
# token to offer — it has a webui session instead, so these are the
# session-gated equivalents, one per sources_server.py path family.
@app.route('/api/system/sources', methods=['GET'])
def sources_list_proxy():
    denied = _require_session()
    if denied:
        return denied
    return _forward_to_sources('/api/sources')


@app.route('/api/system/sources/<path:rest>', methods=['GET', 'POST', 'DELETE'])
def sources_item_proxy(rest):
    denied = _require_session()
    if denied:
        return denied
    return _forward_to_sources('/api/sources/' + rest)


@app.route('/api/system/usb', methods=['GET'])
def usb_list_proxy():
    denied = _require_session()
    if denied:
        return denied
    return _forward_to_sources('/api/usb')


@app.route('/api/system/usb/<path:rest>', methods=['POST'])
def usb_item_proxy(rest):
    denied = _require_session()
    if denied:
        return denied
    return _forward_to_sources('/api/usb/' + rest)


@app.route('/api/system/internal/<path:rest>', methods=['GET', 'POST'])
def internal_proxy(rest):
    denied = _require_session()
    if denied:
        return denied
    return _forward_to_sources('/api/internal/' + rest)


@app.route('/api/system/local/<path:rest>', methods=['GET', 'POST'])
def local_proxy(rest):
    denied = _require_session()
    if denied:
        return denied
    return _forward_to_sources('/api/local/' + rest)


@app.route('/api/system/apply', methods=['POST'])
def apply_proxy():
    denied = _require_session()
    if denied:
        return denied
    return _forward_to_sources('/api/apply')


# ── support bundle (zip) — session-gated, forwarded raw ──────────────
# Binary download, so it can't go through the generic JSON proxy table
# (_handle_proxy always wraps the response in jsonify()). Same trust level as
# every other read in Settings — the bundle is diagnostic-only and never
# changes device state, so no extra password reauth (unlike factory_reset).
@app.route('/api/system/support_bundle', methods=['GET'])
def support_bundle_proxy():
    denied = _require_session()
    if denied:
        return denied
    # The support bundle is a binary response, so use the same raw forwarder
    # that preserves download headers instead of the JSON-oriented proxy path.
    out = _forward_to(API_BASE, '/support_bundle', timeout=600, service_label='sistema')
    out.headers['Cache-Control'] = 'no-store'
    out.headers['X-Content-Type-Options'] = 'nosniff'
    return out


# ── companion pairing (mint via loopback :8080, session-gated) ───────
@app.route('/api/system/pair_token', methods=['POST'])
def pair_token():
    # sources_server only mints tokens from localhost (physical-trust). The
    # daemon IS localhost, so it can mint on behalf of an authenticated web
    # admin — the session is the equivalent trust anchor here.
    denied = _require_session()
    if denied:
        return denied
    body, status = _proxy(SOURCES_BASE, '/api/pair/token', method='POST', body={})
    return jsonify(body), status


@app.route('/api/system/pair_revoke_all', methods=['POST'])
def pair_revoke_all():
    denied = _require_session()
    if denied:
        return denied
    body, status = _proxy(SOURCES_BASE, '/api/pair/tokens/revoke_all', method='POST', body={})
    return jsonify(body), status


# ── Lyrion JSON-RPC proxy (avoids CORS for per-player prefs) ──────────
@app.route('/api/lyrion', methods=['POST'])
def lyrion_proxy():
    denied = _require_session()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    data, status = _proxy(LYRION_BASE, '/jsonrpc.js', method='POST', body=body, timeout=20)
    return jsonify(data), status


# ── captive portal minimal page + SPA serving ────────────────────────
def _captive_html():
    # Minimal, dependency-free, bilingual. This is the ONLY page the sandboxed
    # OS captive browsers ever see; the Vue app takes over once there's real
    # connectivity (redirect to '/'). Forks entirely on boot mode: a session
    # booted from the installer (no OS on disk yet) gets the disk-imaging
    # flow; everything else (an already-installed disk still in provisioning,
    # or a live "Try" session) gets the normal first-boot setup flow.
    return INSTALL_CAPTIVE_HTML if _boot_mode() == 'installer' else SETUP_CAPTIVE_HTML


@app.route('/', methods=['GET'])
def root():
    # Serve the minimal setup portal for the entire provisioning window, not
    # just while the AP is up. This matters for Wi-Fi specifically: a single
    # radio can't stay an AP and join the home network at the same time, so
    # once Wi-Fi connects the hotspot drops on purpose (_evaluate_provisioning
    # above) and the phone loses its link to this device's captive IP — the
    # remaining setup steps (mode, audio, Lyrion, sources, timezone) only
    # exist in this captive page, so the phone must be able to pick the exact
    # same flow back up once it rejoins the real LAN and browses to
    # http://hifiplayer.local or the device's new address. A wired
    # connection never has this problem — the AP stays up throughout (see
    # the "raised ALWAYS" policy above), so this branch is a no-op there.
    #
    # During a post-provisioning network-loss recovery, serve the equally
    # minimal network-only portal (no account/mode/wizard steps — this box
    # is already configured, it just needs its network back).
    if _provisioning():
        return Response(_captive_html(), mimetype='text/html')
    if _net_recovery['active']:
        # This box is already configured, so unlike the setup captive page
        # (whose deviceHost/hostMsg only exist because the name is being
        # picked live, mid-flow) there's no "which name" ambiguity here —
        # socket.gethostname() IS the answer, substituted server-side rather
        # than hardcoding the ISO's default 'hifiplayer' like this used to.
        html = NET_RECOVERY_HTML.replace('__DEVICE_HOST__', socket.gethostname())
        return Response(html, mimetype='text/html')
    return _serve_spa('index.html')


@app.route('/<path:subpath>', methods=['GET'])
def spa(subpath):
    return _serve_spa(subpath)


def _serve_spa(subpath):
    # send_from_directory() refuses traversal on its own; the isfile() probe
    # in front of it is confined the same way, so no "../" ever touches disk.
    root = os.path.normpath(DIST_DIR)
    full = os.path.normpath(os.path.join(root, subpath))
    if full.startswith(root + os.sep) and os.path.isfile(full):
        return send_from_directory(DIST_DIR, subpath)
    index = os.path.join(DIST_DIR, 'index.html')
    if os.path.isfile(index):
        return send_from_directory(DIST_DIR, 'index.html')
    # No Vue build present yet — serve a tiny built-in fallback so the daemon is
    # still useful (auth + provisioning APIs work regardless).
    return Response(FALLBACK_HTML, mimetype='text/html')


# Shared CSS for both captive templates below.
_CAPTIVE_CSS = """
 body{font-family:system-ui,sans-serif;background:#0f1115;color:#eee;margin:0;padding:24px;max-width:520px;margin:auto}
 h1{font-size:20px} .card{background:#1a1e26;border-radius:12px;padding:16px;margin:14px 0}
 label{display:block;font-size:13px;color:#aab;margin:8px 0 4px} input,select,button{width:100%;padding:12px;border-radius:8px;border:1px solid #333;background:#12151b;color:#eee;font-size:15px;box-sizing:border-box}
 button{background:#c8a24a;color:#111;font-weight:600;border:0;margin-top:12px} button.sec{background:#12151b;color:#eee;border:1px solid #333;font-weight:500}
 button:disabled{opacity:.5}
 /* Explicit chevron so a <select> reads as a dropdown even on browsers (e.g.
    iPadOS Safari) whose native affordance is too subtle against this dark
    theme to notice before tapping it. */
 select{-webkit-appearance:none;appearance:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20'%3E%3Cpath fill='%23aab' d='M5 7l5 6 5-6z'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 12px center;background-size:14px;padding-right:36px}
 .muted{color:#889;font-size:13px}
 .net{padding:10px;border-bottom:1px solid #262b35;cursor:pointer} .row{display:flex;justify-content:space-between}
 .langbar{text-align:right;margin-bottom:8px} .langbar a{color:#889;font-size:13px;text-decoration:none;margin-left:10px}
 .langbar a.active{color:#c8a24a;font-weight:600}
 .bar{height:8px;border-radius:4px;background:#12151b;overflow:hidden;margin:10px 0}
 .bar > div{height:100%;background:#c8a24a}
 .disk{padding:12px;border:1px solid #333;border-radius:8px;margin:8px 0;cursor:pointer}
 .disk.sel{border-color:#c8a24a;background:#1f1a10}
 .overlay{position:fixed;inset:0;background:rgba(10,11,14,.92);display:flex;align-items:center;justify-content:center;padding:24px;z-index:50}
 .overlay .card{max-width:340px;text-align:center}
 .spinner{width:32px;height:32px;margin:0 auto 14px;border-radius:50%;border:3px solid #333;border-top-color:#c8a24a;animation:spin 1s linear infinite}
 @keyframes spin{to{transform:rotate(360deg)}}
 .progress-wrap{margin:4px 0 0}
 .progress-label{color:#889;font-size:12px;margin-bottom:4px}
 .progress-bar{height:5px;border-radius:3px;background:#1a1e26;overflow:hidden}
 .progress-bar > div{height:100%;background:#c8a24a;transition:width .3s ease}
 @keyframes cardIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
 .card.step-in{animation:cardIn .3s ease}
 /* Checkbox rows (the music-services step): the blanket input{width:100%}
    above would stretch a checkbox across the card. */
 .chk{display:flex;align-items:flex-start;gap:10px;padding:10px 0;border-bottom:1px solid #262b35;cursor:pointer}
 .chk input{width:auto;flex:none;margin-top:3px}
 .chk .t{display:block;font-size:14px} .chk .d{display:block;color:#889;font-size:12px;margin-top:2px}
 .sep{border-top:1px solid #262b35;margin-top:14px;padding-top:4px}
"""

# ─────────────────────────────────────────────────────────────────────────
#  SETUP flow: language -> restore-or-fresh -> network -> mode (screen /
#  headless / off) -> audio -> lyrion (internal/external) -> sources (only
#  when internal) -> timezone -> finish. Reached on any boot that is NOT the
#  disk installer (an already-installed unit still in provisioning, or a live
#  "Try" session). Minimal, dependency-free, bilingual (EN default).
# ─────────────────────────────────────────────────────────────────────────
SETUP_CAPTIVE_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Osmium Sound — Setup</title>
<style>""" + _CAPTIVE_CSS + """</style></head><body>
<h1 id="h1title">Osmium Sound — Setup</h1>
<div class="progress-wrap" id="progress-wrap" style="display:none">
 <div class="progress-label" id="progress-label"></div>
 <div class="progress-bar"><div id="progress-fill" style="width:0%"></div></div>
</div>

<div class="card" id="step-lang">
 <p class="muted">Choose your language / Scegli la lingua</p>
 <button onclick="pickLang('en')" id="btn-lang-en">English</button>
 <button onclick="pickLang('it')" id="btn-lang-it">Italiano</button>
</div>

<div class="card" id="step-restore" style="display:none">
 <p class="muted" id="restore-intro">Setting up a new device? Restore a previous backup, or start fresh.</p>
 <button class="sec" onclick="startFresh()" id="btn-fresh">Start fresh</button>
 <label id="lbl-restorefile">Backup file</label>
 <input id="restorefile" type="file">
 <label id="lbl-restorepass">Passphrase (if the backup is encrypted)</label>
 <input id="restorepass" type="password">
 <button onclick="restore()" id="btn-restore">Restore from backup</button>
 <p class="muted" id="restoremsg"></p>
</div>

<div class="card" id="step-net" style="display:none">
 <p class="muted" id="net-intro">Connect this device to your home network so it can finish setting up and be reachable from your phone/PC afterwards.</p>
 <label id="lbl-wifi">Wi-Fi network</label>
 <div id="nets"></div>
 <label id="lbl-ssid">Or enter the network name (SSID)</label>
 <input id="ssid" placeholder="Network name">
 <label id="lbl-pass">Wi-Fi password</label>
 <input id="pass" type="password" placeholder="Password">
 <button onclick="connect()" id="btn-connect">Connect via Wi-Fi</button>
 <button class="sec" id="btn-wired" onclick="useWired()">I'm connected via cable (Ethernet)</button>
 <p class="muted" id="netmsg"></p>
</div>

<div class="card" id="step-update" style="display:none">
 <label id="lbl-update">Update required</label>
 <p class="muted" id="update-msg"></p>
 <button onclick="startMandatoryUpdate()" id="btn-update-confirm" style="display:none">Update now</button>
 <div class="bar" id="update-barwrap" style="display:none"><div id="update-bar" style="width:0%"></div></div>
</div>

<div class="card" id="step-name" style="display:none">
 <label id="lbl-devname">Name this player</label>
 <p class="muted" id="devname-help">Used as its network name (e.g. "livingroom" &#8594; livingroom.local) and its Bluetooth/multiroom name. Letters, numbers and dashes only &#8212; leave empty to keep the default.</p>
 <input id="devname" placeholder="e.g. livingroom">
 <button onclick="setDeviceName()" id="btn-devname">Continue</button>
 <p class="muted" id="devnamemsg"></p>
</div>

<div class="card" id="step-mode" style="display:none">
 <label id="lbl-mode">Device mode</label>
 <button onclick="claim('gui')" id="btn-mode-gui">With screen (touchscreen)</button>
 <button class="sec" onclick="claim('headless')" id="btn-mode-headless">Headless (no screen)</button>
 <button class="sec" onclick="claim('off')" id="btn-mode-off">Server only (player off)</button>
 <p class="muted" id="modehelp">In headless/server-only you manage everything from this web interface.</p>
</div>

<div class="card" id="step-pointer" style="display:none">
 <label id="lbl-pointer">Mouse pointer</label>
 <p class="muted" id="pointer-help">Show the mouse cursor on screen? Leave it off for a touchscreen — turn it on if you're driving this device with a mouse.</p>
 <button onclick="setPointer(false)" id="btn-pointer-hide">Touchscreen (hide pointer)</button>
 <button class="sec" onclick="setPointer(true)" id="btn-pointer-show">Mouse (show pointer)</button>
</div>

<div class="card" id="step-audio" style="display:none">
 <p class="muted" id="audio-intro">Pick the DAC / output device this player should send audio to. You can change this later from Settings.</p>
 <label id="lbl-audio">Audio output</label>
 <div id="audiodevs"></div>
 <p class="muted" id="audiomsg"></p>
 <button class="sec" onclick="skipAudio()" id="btn-audio-skip">Continue</button>
</div>

<div class="card" id="step-lyrion" style="display:none">
 <p class="muted" id="lyrion-intro">Choose where your music library lives: on this device, or on a Lyrion server you already run elsewhere on your network.</p>
 <label id="lbl-lyrion">Music server (Lyrion)</label>
 <button onclick="setLyrion('local')" id="btn-lyrion-local">Use this device as the server</button>
 <button class="sec" onclick="showLyrionFollow()" id="btn-lyrion-follow">Use a server already on my network</button>
 <div id="lyrionfollow" style="display:none">
   <div id="lyrionservers"></div>
   <label id="lbl-lyrionhost">Server address</label>
   <input id="lyrionhost" placeholder="192.168.1.50">
   <button onclick="setLyrion('follow')" id="btn-lyrion-follow-go">Use this server</button>
 </div>
 <p class="muted" id="lyrionmsg"></p>
</div>

<div class="card" id="step-lyrion-install" style="display:none">
 <label id="lbl-lyrion-install">Lyrion Music Server</label>
 <p class="muted" id="lyrion-install-msg"></p>
 <select id="lyrionchannel" style="display:none"></select>
 <button onclick="installLyrion()" id="btn-lyrion-install" style="display:none">Install Lyrion</button>
 <div class="bar" id="lyrion-install-barwrap" style="display:none"><div id="lyrion-install-bar" style="width:0%"></div></div>
 <button class="sec" onclick="skipLyrionInstall()" id="btn-lyrion-install-skip" style="display:none">Continue anyway</button>
</div>

<div class="card" id="step-lms-skin" style="display:none">
 <label id="lbl-lms-skin">Web player look</label>
 <p class="muted" id="lms-skin-help"></p>
 <button onclick="chooseSkin('osmium')" id="btn-skin-osmium">Osmium (recommended)</button>
 <button class="sec" onclick="chooseSkin('material')" id="btn-skin-material">Material</button>
 <div class="bar" id="skin-barwrap" style="display:none"><div id="skin-bar" style="width:0%"></div></div>
 <p class="muted" id="skinmsg"></p>
 <button class="sec" onclick="showPluginsStep()" id="btn-skin-skip" style="display:none">Continue anyway</button>
</div>

<div class="card" id="step-lms-plugins" style="display:none">
 <label id="lbl-lms-plugins">Music services</label>
 <p class="muted" id="lms-plugins-help"></p>
 <div id="plugin-list"></div>
 <div class="sep">
  <label class="chk" for="plg-analytics">
   <input type="checkbox" id="plg-analytics">
   <span><span class="t" id="lbl-analytics"></span><span class="d" id="analytics-help"></span></span>
  </label>
 </div>
 <button onclick="applyLmsSetup()" id="btn-plugins-go">Install and continue</button>
 <button class="sec" onclick="skipLmsSetup()" id="btn-plugins-skip">Skip</button>
 <button class="sec" onclick="checkAccountStep()" id="btn-plugins-continue" style="display:none">Continue anyway</button>
 <div class="bar" id="plugins-barwrap" style="display:none"><div id="plugins-bar" style="width:0%"></div></div>
 <p class="muted" id="pluginsmsg"></p>
</div>

<div class="card" id="step-account" style="display:none">
 <label id="lbl-account">Web admin account</label>
 <p class="muted" id="account-help">Used to log into this device's web interface (http://&#8230;) from now on.</p>
 <label id="lbl-acc-user">Username</label>
 <input id="acc-user" autocomplete="username">
 <label id="lbl-acc-pass">Password</label>
 <input id="acc-pass" type="password" autocomplete="new-password">
 <label id="lbl-acc-pass2">Confirm password</label>
 <input id="acc-pass2" type="password" autocomplete="new-password">
 <button onclick="createAccount()" id="btn-account">Create account</button>
 <p class="muted" id="accountmsg"></p>
</div>

<div class="card" id="step-timezone" style="display:none">
 <p class="muted" id="timezone-intro">Used for the clock, alarms and any scheduled tasks on this device.</p>
 <label id="lbl-timezone">Time zone</label>
 <select id="tzselect"></select>
 <button onclick="saveTimezone()" id="btn-tz-save">Save and continue</button>
 <p class="muted" id="tzmsg"></p>
</div>

<div class="card" id="step-sources-ask" style="display:none">
 <label id="lbl-sources">Music sources</label>
 <p class="muted" id="sources-ask-intro">Do you want to set up sources like a NAS or an internal hard disk? External devices (USB) already mount automatically — nothing to do for those.</p>
 <button onclick="sourcesAsk(true)" id="btn-sources-yes">Yes, set up sources</button>
 <button class="sec" onclick="sourcesAsk(false)" id="btn-sources-no">No, skip this</button>
</div>

<div class="card" id="step-sources-type" style="display:none">
 <label id="lbl-sources-type">Add a source</label>
 <p class="muted" id="sources-type-intro">Choose what to add. You can add more than one before continuing.</p>
 <button onclick="showSmbForm()" id="btn-sources-nas">Network drive (NAS)</button>
 <button class="sec" onclick="showInternalDisks()" id="btn-sources-internal-open">Internal disk</button>
 <button class="sec" onclick="continueFromSources()" id="btn-sources-done">Done, continue</button>
</div>

<div class="card" id="step-sources-smb" style="display:none">
 <label id="lbl-sources-smb">Network drive (NAS)</label>
 <p class="muted" id="smb-intro">Enter your NAS's address and the name of the shared folder with your music.</p>
 <label id="lbl-smb-server">Server address</label>
 <input id="smb-server" placeholder="192.168.1.50">
 <label id="lbl-smb-share">Share name</label>
 <input id="smb-share" placeholder="Music">
 <label id="lbl-smb-user">Username (if needed)</label>
 <input id="smb-user">
 <label id="lbl-smb-pass">Password (if needed)</label>
 <input id="smb-pass" type="password">
 <button onclick="submitSmb()" id="btn-smb-connect">Connect</button>
 <button class="sec" onclick="show('step-sources-type')" id="btn-smb-back">Back</button>
 <p class="muted" id="smb-msg"></p>
</div>

<div class="card" id="step-sources-smb-folder" style="display:none">
 <label id="lbl-smb-folder">Choose what to add</label>
 <p class="muted" id="smb-folder-intro">Use the whole share, or open a folder to use just part of it.</p>
 <p class="muted" id="smb-folder-path"></p>
 <div id="smb-folder-list"></div>
 <button onclick="smbFolderUp()" class="sec" id="btn-smb-folder-up">Up</button>
 <button onclick="smbFolderUseHere()" id="btn-smb-folder-use">Use this folder</button>
 <button class="sec" onclick="show('step-sources-type')" id="btn-smb-folder-back">Back</button>
 <p class="muted" id="smb-folder-msg"></p>
</div>

<div class="card" id="step-sources-internal" style="display:none">
 <div id="internal-list-wrap">
  <label id="lbl-sources-internal">Internal disks</label>
  <p class="muted" id="internal-intro">Pick a disk to use for your music library.</p>
  <div id="internal-list"></div>
  <button class="sec" onclick="show('step-sources-type')" id="btn-internal-back">Back</button>
 </div>
 <div id="internal-format-wrap" style="display:none">
  <div id="format-choose">
   <label id="lbl-format">Format disk</label>
   <p class="muted" id="format-warn"></p>
   <label id="lbl-format-fs">Filesystem</label>
   <select id="format-fs"><option value="ext4">ext4</option><option value="exfat">exFAT</option></select>
   <label id="lbl-format-label">Disk name</label>
   <input id="format-label" value="Musica">
   <button onclick="formatConfirmStep()" id="btn-format-next">Next</button>
   <button class="sec" onclick="cancelFormat()" id="btn-format-cancel1">Cancel</button>
  </div>
  <div id="format-confirm" style="display:none">
   <p class="muted" id="format-confirm-msg"></p>
   <input id="format-typed" oninput="updateFormatGoState()">
   <button onclick="startFormat()" id="btn-format-go" disabled>Format now</button>
   <button class="sec" onclick="cancelFormat()" id="btn-format-cancel2">Cancel</button>
  </div>
  <div id="format-progress" style="display:none">
   <p class="muted" id="format-progress-msg"></p>
   <div class="bar"><div id="format-bar" style="width:0%"></div></div>
  </div>
  <div id="format-done" style="display:none">
   <p class="muted" id="format-done-msg"></p>
   <button onclick="formatDone()" id="btn-format-done-continue">Continue</button>
  </div>
 </div>
</div>

<div class="card" id="step-finish" style="display:none">
 <p id="finishmsg" class="muted"></p>
 <button id="btn-finish" onclick="finish()" style="display:none">Complete setup</button>
</div>

<div class="overlay" id="reboot-overlay" style="display:none">
 <div class="card">
  <div class="spinner"></div>
  <h1 id="reboot-title" style="font-size:16px;margin:0 0 6px"></h1>
  <p class="muted" id="reboot-phase-msg"></p>
  <p class="muted" id="reboot-auto-msg"></p>
 </div>
</div>

<div class="overlay" id="restore-overlay" style="display:none">
 <div class="card">
  <div class="spinner"></div>
  <h1 id="restore-ov-title" style="font-size:16px;margin:0 0 6px"></h1>
  <p class="muted" id="restore-ov-msg"></p>
 </div>
</div>

<script>
var STRINGS={
 en:{restoreIntro:'Setting up a new device? Restore a previous backup, or start fresh.',fresh:'Start fresh',restoreFile:'Backup file',restorePass:'Passphrase (if the backup is encrypted)',restore:'Restore from backup',restoring:'Restoring…',restoreOverlayTitle:'Restoring from backup…',restoreDone:'Restore complete. Rebooting to apply it — reconnect in about a minute.',restoreFailed:'Restore failed.',restoreNoFile:'Choose a backup file first.',wifi:'Wi-Fi network',ssid:'Or enter the network name (SSID)',pass:'Wi-Fi password',connect:'Connect via Wi-Fi',wired:"I'm connected via cable (Ethernet)",connecting:'Connecting… the setup Wi-Fi will turn off. Reconnect your phone to your home network, then open http://hifiplayer.local to continue setup where you left off.',noCable:'No cable detected',netIntro:'Connect this device to your home network so it can finish setting up and be reachable from your phone/PC afterwards.',stepLabel:'Step {n} of {total}',audioIntro:'Pick the DAC / output device this player should send audio to. You can change this later from Settings.',lyrionIntro:'Choose where your music library lives: on this device, or on a Lyrion server you already run elsewhere on your network.',timezoneIntro:'Used for the clock, alarms and any scheduled tasks on this device.',updateRequired:'Update required',updateNow:'Update now',updateChecking:'Checking for updates…',updateAutoStarting:'An update is available and required — starting it now…',updateDevAvailable:'A preview (dev channel) update is available and required to continue setup.',updateApplying:'Updating — this can take a few minutes…',updateDoneRebooting:'Update complete. Rebooting…',updateFailed:'Update check/install failed. Retrying is required to continue setup.',devname:'Name this player',devnameHelp:'Used as its network name (e.g. "livingroom" → livingroom.local) and its Bluetooth/multiroom name. Letters, numbers and dashes only — leave empty to keep the default.',devnameSaving:'Saving…',mode:'Device mode',modeGui:'With screen (touchscreen)',modeHeadless:'Headless (no screen)',modeOff:'Server only (player off)',modeHelp:'In headless/server-only you manage everything from this web interface.',pointer:'Mouse pointer',pointerHelp:"Show the mouse cursor on screen? Leave it off for a touchscreen — turn it on if you're driving this device with a mouse.",pointerHide:'Touchscreen (hide pointer)',pointerShow:'Mouse (show pointer)',audio:'Audio output',audioContinue:'Continue',lyrion:'Music server (Lyrion)',lyrionLocal:'Use this device as the server',lyrionFollow:'Use a server already on my network',lyrionHost:'Server address',lyrionUse:'Use this server',lyrionInstall:'Install Lyrion',lyrionChecking:'Checking whether Lyrion Music Server is installed…',lyrionMissing:"Lyrion Music Server isn't installed yet.",lyrionInstalling:'Installing Lyrion Music Server…',lyrionDownloading:'Downloading Lyrion Music Server…',lyrionRestarting:'Restarting Lyrion Music Server…',lyrionInstallFailed:'Lyrion install failed.',continueAnyway:'Continue anyway',skinTitle:'Web player look',skinHelp:"Choose the look of Lyrion's web player (the page you open from a browser or phone). Osmium matches this device's interface.",skinOsmium:'Osmium (recommended)',skinMaterial:'Material',skinInstalling:'Installing the Material web interface…',skinApplying:'Applying the skin…',skinDone:'Skin applied.',skinFailed:"Couldn't apply the skin. Check the network connection and try again.",lmsPlugins:'Music services',lmsPluginsHelp:'Choose what to add to your music server. You can add or remove these later from Lyrion.',lmsPluginsGo:'Install and continue',lmsPluginsSkip:'Skip',lmsPluginsInstalling:'Installing the selected services…',lmsPluginsApplying:'Finishing the music server setup…',lmsPluginsDone:'Music server ready.',lmsPluginsFailed:"Couldn't finish the music server setup.",plg_MusicArtistInfo:'Artist and album info',plgd_MusicArtistInfo:'Biographies, album reviews and lyrics inside the player.',plg_Spotty:'Spotify',plgd_Spotty:'Play your Spotify Premium account through this player.',plg_TIDAL:'TIDAL',plgd_TIDAL:'Listen with your TIDAL subscription.',plg_Qobuz:'Qobuz',plgd_Qobuz:'Listen with your Qobuz subscription.',plg_Deezer:'Deezer',plgd_Deezer:'Listen with your Deezer subscription.',plg_RadioNowPlaying:'Radio track info',plgd_RadioNowPlaying:'Shows the track and cover art playing on internet radio.',plg_RadioNet:'Radio.net',plgd_RadioNet:'Browse the Radio.net internet radio directory.',analytics:'Help improve Lyrion (optional)',analyticsHelp:'Every couple of days, sends an anonymous ID, the version and operating system, the list of active plugins and how many tracks and players you have to the Lyrion community (stats.lms-community.org). No personal data, no track titles. You can change this later from Lyrion.',sources:'Music sources',sourcesAskIntro:'Do you want to set up sources like a NAS or an internal hard disk? External devices (USB) already mount automatically — nothing to do for those.',sourcesYes:'Yes, set up sources',sourcesNo:'No, skip this',sourcesTypeIntro:'Choose what to add. You can add more than one before continuing.',addNas:'Network drive (NAS)',addInternal:'Internal disk',sourcesDone:'Done, continue',backBtn:'Back',cancelBtn:'Cancel',smbIntro:"Enter your NAS's address and the name of the shared folder with your music.",smbServer:'Server address',smbShare:'Share name',smbUser:'Username (if needed)',smbPass:'Password (if needed)',smbConnect:'Connect',smbFieldsRequired:'Server address and share name are required.',smbConnecting:'Connecting…',smbConnected:'Connected!',smbFolderTitle:'Choose what to add',smbFolderIntro:'Use the whole share, or open a folder to use just part of it.',smbFolderUp:'Up',smbFolderUse:'Use this folder',smbFolderNoSubfolders:'No subfolders here.',smbFolderSaving:'Saving…',internalIntro:'Pick a disk to use for your music library.',internalLoading:'Loading…',internalNone:'No internal disks found.',internalAlreadyUsed:'Already in use',internalUseBtn:'Use this disk',internalFormatBtn:'Format this disk',internalAdopting:'Adding…',formatTitle:'Format disk',formatFs:'Filesystem',formatLabel:'Disk name',formatWarn:'This will ERASE ALL DATA on {disk}.',formatConfirmMsg:'Type {label} below to confirm.',formatGo:'Format now',formatting:'Formatting — this can take a while…',formatDoneMsg:'Done — the disk is ready to use.',continueBtn:'Continue',timezone:'Time zone',tzSave:'Save and continue',account:'Web admin account',accountHelp:"Used to log into this device's web interface (http://…) from now on.",username:'Username',password:'Password',confirmPassword:'Confirm password',createAccount:'Create account',creating:'Creating…',accountMismatch:'Passwords do not match.',accountTooShort:'Username needs at least 3 characters, password at least 8.',finishGui:'Screen mode set. Setup is complete — press "Complete setup" below: the hotspot will turn off, reconnect your phone to your network. The device will then start its normal on-screen interface.',finishHeadless:'Headless mode set. Press "Complete setup" below: the hotspot will turn off, reconnect your phone to your network and open http://hifiplayer.local',finishOff:'Server-only mode set — this device will not play audio locally. Press "Complete setup" below: the hotspot will turn off, reconnect your phone to your network and open http://hifiplayer.local',finishBtn:'Complete setup',finishDone:'Setup complete — hotspot off. Open http://hifiplayer.local from your network.',finishToLyrion:'Setup complete. Opening the web player…',rebootTitle:'Rebooting…',rebootGoingDown:'The device is restarting.',rebootComingBack:'Waiting for the device to come back online.',rebootAuto:'This page will reconnect automatically — no need to refresh.',error:'Error: '},
 it:{restoreIntro:'Stai configurando un nuovo dispositivo? Ripristina un backup precedente, oppure inizia da zero.',fresh:'Inizia da zero',restoreFile:'File di backup',restorePass:'Passphrase (se il backup è cifrato)',restore:'Ripristina da backup',restoring:'Ripristino in corso…',restoreOverlayTitle:'Ripristino da backup in corso…',restoreDone:'Ripristino completato. Riavvio in corso per applicarlo — riconnettiti tra circa un minuto.',restoreFailed:'Ripristino non riuscito.',restoreNoFile:'Scegli prima un file di backup.',wifi:'Rete Wi-Fi',ssid:'Oppure inserisci il nome (SSID)',pass:'Password Wi-Fi',connect:'Connetti via Wi-Fi',wired:'Sono connesso via cavo (Ethernet)',connecting:'Connessione in corso… il Wi-Fi di setup si spegnerà. Riconnetti il telefono alla tua rete di casa, poi apri http://hifiplayer.local per continuare la configurazione da dove l\\'hai lasciata.',noCable:'Nessun cavo rilevato',netIntro:'Collega questo dispositivo alla tua rete di casa così può completare la configurazione ed essere raggiungibile da telefono/PC in seguito.',stepLabel:'Passo {n} di {total}',audioIntro:'Scegli il DAC / dispositivo di uscita a cui questo player deve inviare l\\'audio. Puoi cambiarlo in seguito dalle Impostazioni.',lyrionIntro:'Scegli dove vive la tua libreria musicale: su questo dispositivo, oppure su un server Lyrion che hai già altrove sulla tua rete.',timezoneIntro:'Usato per l\\'orologio, le sveglie e qualsiasi attività pianificata su questo dispositivo.',updateRequired:'Aggiornamento richiesto',updateNow:'Aggiorna ora',updateChecking:'Controllo aggiornamenti…',updateAutoStarting:'È disponibile un aggiornamento obbligatorio — avvio in corso…',updateDevAvailable:'È disponibile un aggiornamento di anteprima (canale dev), obbligatorio per continuare il setup.',updateApplying:'Aggiornamento in corso — può richiedere qualche minuto…',updateDoneRebooting:'Aggiornamento completato. Riavvio in corso…',updateFailed:'Controllo/installazione aggiornamento fallito. È necessario riprovare per continuare il setup.',devname:'Dai un nome a questo player',devnameHelp:'Usato come nome di rete (es. "salotto" → salotto.local) e come nome Bluetooth/multiroom. Solo lettere, numeri e trattini — lascia vuoto per mantenere quello predefinito.',devnameSaving:'Salvataggio…',mode:'Modalità dispositivo',modeGui:'Con schermo (touchscreen)',modeHeadless:'Headless (senza schermo)',modeOff:'Solo server (player spento)',modeHelp:'In headless/solo server gestisci tutto da questa interfaccia web.',pointer:'Puntatore del mouse',pointerHelp:'Mostrare il cursore del mouse a schermo? Lascialo spento per un touchscreen — accendilo se usi il dispositivo con un mouse.',pointerHide:'Touchscreen (nascondi puntatore)',pointerShow:'Mouse (mostra puntatore)',audio:'Uscita audio',audioContinue:'Continua',lyrion:'Server musicale (Lyrion)',lyrionLocal:'Usa questo dispositivo come server',lyrionFollow:'Usa un server già presente sulla rete',lyrionHost:'Indirizzo del server',lyrionUse:'Usa questo server',lyrionInstall:'Installa Lyrion',lyrionChecking:'Verifica se Lyrion Music Server è installato…',lyrionMissing:'Lyrion Music Server non è ancora installato.',lyrionInstalling:'Installazione di Lyrion Music Server…',lyrionDownloading:'Scaricamento di Lyrion Music Server…',lyrionRestarting:'Riavvio di Lyrion Music Server…',lyrionInstallFailed:'Installazione di Lyrion non riuscita.',continueAnyway:'Continua comunque',skinTitle:'Aspetto del player web',skinHelp:"Scegli l'aspetto del player web di Lyrion (la pagina che apri da browser o telefono). Osmium è coerente con l'interfaccia di questo dispositivo.",skinOsmium:'Osmium (consigliata)',skinMaterial:'Material',skinInstalling:"Installazione dell'interfaccia web Material…",skinApplying:'Applicazione della skin…',skinDone:'Skin applicata.',skinFailed:'Impossibile applicare la skin. Controlla la rete e riprova.',lmsPlugins:'Servizi musicali',lmsPluginsHelp:'Scegli cosa aggiungere al tuo server musicale. Puoi aggiungerli o rimuoverli in seguito da Lyrion.',lmsPluginsGo:'Installa e continua',lmsPluginsSkip:'Salta',lmsPluginsInstalling:'Installazione dei servizi selezionati…',lmsPluginsApplying:'Completamento della configurazione del server musicale…',lmsPluginsDone:'Server musicale pronto.',lmsPluginsFailed:'Impossibile completare la configurazione del server musicale.',plg_MusicArtistInfo:'Info artisti e album',plgd_MusicArtistInfo:'Biografie, recensioni e testi dentro al player.',plg_Spotty:'Spotify',plgd_Spotty:'Riproduci il tuo account Spotify Premium su questo player.',plg_TIDAL:'TIDAL',plgd_TIDAL:'Ascolta con il tuo abbonamento TIDAL.',plg_Qobuz:'Qobuz',plgd_Qobuz:'Ascolta con il tuo abbonamento Qobuz.',plg_Deezer:'Deezer',plgd_Deezer:'Ascolta con il tuo abbonamento Deezer.',plg_RadioNowPlaying:'Info brani radio',plgd_RadioNowPlaying:'Mostra brano e copertina di quello che sta passando in radio.',plg_RadioNet:'Radio.net',plgd_RadioNet:'Sfoglia la directory di radio internet Radio.net.',analytics:'Aiuta a migliorare Lyrion (facoltativo)',analyticsHelp:"Ogni due giorni invia alla community di Lyrion (stats.lms-community.org) un identificativo anonimo, la versione e il sistema operativo, l'elenco dei plugin attivi e quanti brani e player hai. Nessun dato personale, nessun titolo dei brani. Puoi cambiare idea più avanti da Lyrion.",sources:'Sorgenti musicali',sourcesAskIntro:'Vuoi configurare sorgenti come un NAS o un disco rigido interno? I dispositivi esterni (USB) si montano già automaticamente — per quelli non serve fare nulla.',sourcesYes:'Sì, configura le sorgenti',sourcesNo:'No, salta questo passaggio',sourcesTypeIntro:'Scegli cosa aggiungere. Puoi aggiungerne più di una prima di continuare.',addNas:'Unità di rete (NAS)',addInternal:'Disco interno',sourcesDone:'Fatto, continua',backBtn:'Indietro',cancelBtn:'Annulla',smbIntro:"Inserisci l'indirizzo del tuo NAS e il nome della cartella condivisa con la musica.",smbServer:'Indirizzo del server',smbShare:'Nome della condivisione',smbUser:'Nome utente (se richiesto)',smbPass:'Password (se richiesta)',smbConnect:'Connetti',smbFieldsRequired:'Indirizzo del server e nome della condivisione sono obbligatori.',smbConnecting:'Connessione in corso…',smbConnected:'Connesso!',smbFolderTitle:'Scegli cosa aggiungere',smbFolderIntro:"Usa l'intera condivisione, oppure apri una cartella per usarne solo una parte.",smbFolderUp:'Su',smbFolderUse:'Usa questa cartella',smbFolderNoSubfolders:'Nessuna sottocartella qui.',smbFolderSaving:'Salvataggio…',internalIntro:'Scegli un disco da usare per la tua libreria musicale.',internalLoading:'Caricamento…',internalNone:'Nessun disco interno trovato.',internalAlreadyUsed:'Già in uso',internalUseBtn:'Usa questo disco',internalFormatBtn:'Formatta questo disco',internalAdopting:'Aggiunta in corso…',formatTitle:'Formatta disco',formatFs:'Filesystem',formatLabel:'Nome del disco',formatWarn:'Questo CANCELLERÀ TUTTI I DATI su {disk}.',formatConfirmMsg:'Digita {label} qui sotto per confermare.',formatGo:'Formatta ora',formatting:"Formattazione in corso — può richiedere un po' di tempo…",formatDoneMsg:'Fatto — il disco è pronto all\\'uso.',continueBtn:'Continua',timezone:'Fuso orario',tzSave:'Salva e continua',account:'Account amministratore web',accountHelp:"Usato per accedere all'interfaccia web di questo dispositivo (http://…) da ora in poi.",username:'Nome utente',password:'Password',confirmPassword:'Conferma password',createAccount:'Crea account',creating:'Creazione…',accountMismatch:'Le password non coincidono.',accountTooShort:'Nome utente di almeno 3 caratteri, password di almeno 8.',finishGui:'Modalità con schermo impostata. Il setup è completo — premi "Completa setup" qui sotto: l\\'hotspot si spegnerà, riconnetti il telefono alla tua rete. Il dispositivo avvierà poi la sua normale interfaccia a schermo.',finishHeadless:'Modalità headless impostata. Premi "Completa setup" qui sotto: l\\'hotspot si spegnerà, riconnetti il telefono alla tua rete e apri http://hifiplayer.local',finishOff:'Modalità solo server impostata — questo dispositivo non riprodurrà audio in locale. Premi "Completa setup" qui sotto: l\\'hotspot si spegnerà, riconnetti il telefono alla tua rete e apri http://hifiplayer.local',finishBtn:'Completa setup',finishDone:'Setup completato — hotspot spento. Apri http://hifiplayer.local dalla tua rete.',finishToLyrion:'Setup completato. Apro il player web…',rebootTitle:'Riavvio in corso…',rebootGoingDown:'Il dispositivo si sta riavviando.',rebootComingBack:'In attesa che il dispositivo torni online.',rebootAuto:'Questa pagina si ricollegherà automaticamente — non serve aggiornarla.',error:'Errore: '}
};
// Chosen once, up front, on step-lang -- persisted so it survives the
// network step's own reload (Wi-Fi hands off from the setup hotspot to the
// phone's home network, dropping this page entirely) and every other reload
// for the rest of this wizard run. No in-wizard way to change it afterwards,
// same as Android's own first-run language screen.
var LANG=localStorage.getItem('hifiSetupLang')||'';
var S=STRINGS[LANG]||STRINGS.en;
function applyStrings(){
document.getElementById('restore-intro').textContent=S.restoreIntro;
document.getElementById('btn-fresh').textContent=S.fresh;
document.getElementById('lbl-restorefile').textContent=S.restoreFile;
document.getElementById('lbl-restorepass').textContent=S.restorePass;
document.getElementById('btn-restore').textContent=S.restore;
document.getElementById('net-intro').textContent=S.netIntro;
document.getElementById('lbl-wifi').textContent=S.wifi;
document.getElementById('lbl-ssid').textContent=S.ssid;
document.getElementById('lbl-pass').textContent=S.pass;
document.getElementById('btn-connect').textContent=S.connect;
document.getElementById('btn-wired').textContent=S.wired;
document.getElementById('lbl-update').textContent=S.updateRequired;
document.getElementById('btn-update-confirm').textContent=S.updateNow;
document.getElementById('lbl-devname').textContent=S.devname;
document.getElementById('devname-help').textContent=S.devnameHelp;
document.getElementById('btn-devname').textContent=S.continueBtn;
document.getElementById('lbl-mode').textContent=S.mode;
document.getElementById('btn-mode-gui').textContent=S.modeGui;
document.getElementById('btn-mode-headless').textContent=S.modeHeadless;
document.getElementById('btn-mode-off').textContent=S.modeOff;
document.getElementById('modehelp').textContent=S.modeHelp;
document.getElementById('lbl-pointer').textContent=S.pointer;
document.getElementById('pointer-help').textContent=S.pointerHelp;
document.getElementById('btn-pointer-hide').textContent=S.pointerHide;
document.getElementById('btn-pointer-show').textContent=S.pointerShow;
document.getElementById('audio-intro').textContent=S.audioIntro;
document.getElementById('lbl-audio').textContent=S.audio;
document.getElementById('btn-audio-skip').textContent=S.audioContinue;
document.getElementById('lyrion-intro').textContent=S.lyrionIntro;
document.getElementById('lbl-lyrion').textContent=S.lyrion;
document.getElementById('btn-lyrion-local').textContent=S.lyrionLocal;
document.getElementById('btn-lyrion-follow').textContent=S.lyrionFollow;
document.getElementById('lbl-lyrionhost').textContent=S.lyrionHost;
document.getElementById('btn-lyrion-follow-go').textContent=S.lyrionUse;
document.getElementById('lbl-lyrion-install').textContent=S.lyrion;
document.getElementById('btn-lyrion-install').textContent=S.lyrionInstall;
document.getElementById('btn-lyrion-install-skip').textContent=S.continueAnyway;
document.getElementById('lbl-lms-skin').textContent=S.skinTitle;
document.getElementById('lms-skin-help').textContent=S.skinHelp;
document.getElementById('btn-skin-osmium').textContent=S.skinOsmium;
document.getElementById('btn-skin-material').textContent=S.skinMaterial;
document.getElementById('btn-skin-skip').textContent=S.continueAnyway;
document.getElementById('lbl-lms-plugins').textContent=S.lmsPlugins;
document.getElementById('lms-plugins-help').textContent=S.lmsPluginsHelp;
document.getElementById('btn-plugins-go').textContent=S.lmsPluginsGo;
document.getElementById('btn-plugins-skip').textContent=S.lmsPluginsSkip;
document.getElementById('btn-plugins-continue').textContent=S.continueAnyway;
document.getElementById('lbl-analytics').textContent=S.analytics;
document.getElementById('analytics-help').textContent=S.analyticsHelp;
document.getElementById('lbl-sources').textContent=S.sources;
document.getElementById('sources-ask-intro').textContent=S.sourcesAskIntro;
document.getElementById('btn-sources-yes').textContent=S.sourcesYes;
document.getElementById('btn-sources-no').textContent=S.sourcesNo;
document.getElementById('lbl-sources-type').textContent=S.sources;
document.getElementById('sources-type-intro').textContent=S.sourcesTypeIntro;
document.getElementById('btn-sources-nas').textContent=S.addNas;
document.getElementById('btn-sources-internal-open').textContent=S.addInternal;
document.getElementById('btn-sources-done').textContent=S.sourcesDone;
document.getElementById('lbl-sources-smb').textContent=S.addNas;
document.getElementById('smb-intro').textContent=S.smbIntro;
document.getElementById('lbl-smb-server').textContent=S.smbServer;
document.getElementById('lbl-smb-share').textContent=S.smbShare;
document.getElementById('lbl-smb-user').textContent=S.smbUser;
document.getElementById('lbl-smb-pass').textContent=S.smbPass;
document.getElementById('btn-smb-connect').textContent=S.smbConnect;
document.getElementById('btn-smb-back').textContent=S.backBtn;
document.getElementById('lbl-smb-folder').textContent=S.smbFolderTitle;
document.getElementById('smb-folder-intro').textContent=S.smbFolderIntro;
document.getElementById('btn-smb-folder-up').textContent=S.smbFolderUp;
document.getElementById('btn-smb-folder-use').textContent=S.smbFolderUse;
document.getElementById('btn-smb-folder-back').textContent=S.backBtn;
document.getElementById('lbl-sources-internal').textContent=S.addInternal;
document.getElementById('internal-intro').textContent=S.internalIntro;
document.getElementById('btn-internal-back').textContent=S.backBtn;
document.getElementById('lbl-format').textContent=S.formatTitle;
document.getElementById('lbl-format-fs').textContent=S.formatFs;
document.getElementById('lbl-format-label').textContent=S.formatLabel;
document.getElementById('btn-format-next').textContent=S.continueBtn;
document.getElementById('btn-format-cancel1').textContent=S.cancelBtn;
document.getElementById('btn-format-cancel2').textContent=S.cancelBtn;
document.getElementById('btn-format-go').textContent=S.formatGo;
document.getElementById('btn-format-done-continue').textContent=S.continueBtn;
document.getElementById('timezone-intro').textContent=S.timezoneIntro;
document.getElementById('lbl-timezone').textContent=S.timezone;
document.getElementById('btn-tz-save').textContent=S.tzSave;
document.getElementById('lbl-account').textContent=S.account;
document.getElementById('account-help').textContent=S.accountHelp;
document.getElementById('lbl-acc-user').textContent=S.username;
document.getElementById('lbl-acc-pass').textContent=S.password;
document.getElementById('lbl-acc-pass2').textContent=S.confirmPassword;
document.getElementById('btn-account').textContent=S.createAccount;
}

var STEPS=['step-lang','step-restore','step-net','step-update','step-name','step-mode','step-pointer','step-audio','step-lyrion','step-lyrion-install','step-lms-skin','step-lms-plugins','step-account','step-timezone','step-sources-ask','step-sources-type','step-sources-smb','step-sources-smb-folder','step-sources-internal','step-finish'];
var lyrionMode='local';
var netPhaseDone=false;
var restoringFromBackup=false;
var pendingRestoreFile=null;
var deviceHost='hifiplayer';
// The finish/connecting strings hardcode http://hifiplayer.local as the
// address to reconnect to — once the user picks a different name in
// step-name, that address changes, so route those strings through this.
function hostMsg(s){return s.replace(/hifiplayer\.local/g,deviceHost+'.local')}
function h(){return {'X-CSRF-Token':(document.cookie.match(/csrf=([^;]+)/)||[])[1]||'','X-UI-Lang':LANG}}
function show(id){
  STEPS.forEach(function(s){
    var el=document.getElementById(s);
    if(s===id){
      el.style.display='block';
      el.classList.remove('step-in');
      void el.offsetWidth; // reflow, so re-adding the class restarts the animation
      el.classList.add('step-in');
    }else{
      el.style.display='none';
    }
  });
  updateProgress(id);
}
// "Step N of total" orientation bar -- excludes step-lang (nothing to count
// yet) and step-finish (there's nothing after it) from the denominator, so it
// reads as progress through the actual configuration steps.
function updateProgress(id){
  var wrap=document.getElementById('progress-wrap');
  if(id==='step-lang'||id==='step-finish'){wrap.style.display='none';return}
  var pos=STEPS.indexOf(id);
  var total=STEPS.length-2;
  wrap.style.display='block';
  document.getElementById('progress-label').textContent=
    (S.stepLabel||'Step {n} of {total}').replace('{n}',pos).replace('{total}',total);
  document.getElementById('progress-fill').style.width=Math.round(pos/total*100)+'%';
}
function jpost(p,b){return fetch(p,{method:'POST',headers:Object.assign({'Content-Type':'application/json'},h()),body:JSON.stringify(b||{})}).then(function(r){return r.json()})}
function jget(p){return fetch(p,{headers:h()}).then(function(r){return r.json()})}

function pickLang(l){
  LANG=l;
  localStorage.setItem('hifiSetupLang',l);
  S=STRINGS[LANG];
  applyStrings();
  show('step-restore');
}
// Already chosen in an earlier visit this same wizard run (e.g. this is the
// reload right after the network step handed off from the setup hotspot to
// the phone's home network) -- skip straight past step-lang.
if(STRINGS[LANG]){applyStrings();show('step-restore')}

function load(){if(netPhaseDone)return;fetch('/api/provision/status').then(function(r){return r.json()}).then(function(s){
  if(!s.pending){return}
  var n=document.getElementById('nets');n.innerHTML='';
  (s.networks||[]).forEach(function(net){var d=document.createElement('div');d.className='net';
    d.innerHTML='<div class="row"><span>'+net.ssid+'</span><span class="muted">'+net.signal+'%</span></div>';
    d.onclick=function(){document.getElementById('ssid').value=net.ssid};n.appendChild(d)});
  if(s.error){document.getElementById('netmsg').textContent=S.error+s.error}
  if(s.stage==='network-ok'){netPhaseDone=true;checkMandatoryUpdate()}
})}

// Mandatory update gate, right after the network step (see the comment on
// the /api/provision/update_check route in this file for why it checks both
// prod and dev channels). A prod update starts on its own; a dev-only one
// waits for the operator to press the button below.
var pendingUpdateChannel=null;
var updateCheckAttempts=0;
function checkMandatoryUpdate(){
  show('step-update');
  document.getElementById('update-msg').textContent=S.updateChecking;
  document.getElementById('btn-update-confirm').style.display='none';
  document.getElementById('update-barwrap').style.display='none';
  jget('/api/provision/update_check').then(function(res){
    // The check itself failed on every component (network/DNS still warming
    // up right after the network step) -- that is NOT the same as "checked,
    // nothing to update". Retry for a bit before giving up, so a transient
    // blip can't make the wizard silently skip a real mandatory update.
    if(res.checkFailed){
      updateCheckAttempts++;
      if(updateCheckAttempts<8){setTimeout(checkMandatoryUpdate,2000);return}
      show('step-name');return
    }
    updateCheckAttempts=0;
    if(!res.available){show('step-name');return}
    pendingUpdateChannel=res.channel;
    if(res.auto){
      document.getElementById('update-msg').textContent=S.updateAutoStarting;
      startMandatoryUpdate();
    }else{
      document.getElementById('update-msg').textContent=S.updateDevAvailable;
      document.getElementById('btn-update-confirm').style.display='block';
    }
  }).catch(function(){setTimeout(checkMandatoryUpdate,1500)});
}
function startMandatoryUpdate(){
  document.getElementById('btn-update-confirm').style.display='none';
  document.getElementById('update-msg').textContent=S.updateApplying;
  document.getElementById('update-barwrap').style.display='block';
  jpost('/api/provision/update_apply',{channel:pendingUpdateChannel}).then(function(res){
    if(!res.started){
      document.getElementById('update-msg').textContent=res.message||S.updateFailed;
      document.getElementById('update-barwrap').style.display='none';
      document.getElementById('btn-update-confirm').style.display='block';
      return;
    }
    pollMandatoryUpdate();
  }).catch(function(){
    document.getElementById('update-msg').textContent=S.updateFailed;
    document.getElementById('update-barwrap').style.display='none';
    document.getElementById('btn-update-confirm').style.display='block';
  });
}
function pollMandatoryUpdate(){
  // A 'system' component update restarts hifi-webui itself -- a request
  // landing exactly then fails outright (connection refused for a second or
  // two), not with an error JSON. Without a catch that stops the whole poll
  // loop silently, stranding the operator on "Updating…" forever even though
  // the update finishes fine in the background. Just retry.
  jget('/api/provision/update_status').then(function(st){
    if(typeof st.overall_progress==='number')document.getElementById('update-bar').style.width=st.overall_progress+'%';
    if(st.message)document.getElementById('update-msg').textContent=st.message;
    if(st.state==='staged_pending_reboot'||st.state==='applying'){
      setTimeout(pollMandatoryUpdate,1500);
    }else if(st.state==='done'){
      // By the time this state is observable here, the appliance has already
      // rebooted on its own (twice: once to enter the isolated apply session,
      // once to leave it) -- webui_server.py could not have answered this
      // request otherwise, since it does not run during that window. No
      // reboot left to wait for; just reload into the now-current wizard state.
      document.getElementById('update-msg').textContent=S.updateDoneRebooting;
      location.reload();
    }else if(st.state==='error'||st.state==='apply_error'){
      document.getElementById('update-msg').textContent=S.updateFailed;
      document.getElementById('update-barwrap').style.display='none';
      document.getElementById('btn-update-confirm').style.display='block';
    }else{
      setTimeout(pollMandatoryUpdate,1500);
    }
  }).catch(function(){setTimeout(pollMandatoryUpdate,1500)});
}

function startFresh(){show('step-net')}

function restore(){
  var f=document.getElementById('restorefile').files[0];
  if(!f){document.getElementById('restoremsg').textContent=S.restoreNoFile;return}
  // Ask which Lyrion version to install (and install it) before touching the
  // backup — a restore only writes Lyrion's *prefs*, it never installs the
  // package. Going straight to finalize/reboot as before left devices with a
  // restored config but no Lyrion service to read it, relying on
  // hifi-firstboot's own flaky first-boot install timing to paper over it.
  pendingRestoreFile=f;
  restoringFromBackup=true;
  checkLyrionInstall();
}

function showRestoreOverlay(msg){
  document.getElementById('restore-ov-title').textContent=S.restoreOverlayTitle;
  document.getElementById('restore-ov-msg').textContent=msg||'';
  document.getElementById('restore-overlay').style.display='flex';
}
function hideRestoreOverlay(){
  document.getElementById('restore-overlay').style.display='none';
}
function doRestoreUpload(){
  var f=pendingRestoreFile;
  // step-lyrion-install is the card on screen right now (checkLyrionInstall
  // switched to it) — switch back so the overlay sits over the right card
  // once it's dismissed (error case falls back to this card, not a stale one).
  show('step-restore');
  document.getElementById('restoremsg').textContent='';
  var fd=new FormData();fd.append('file',f);fd.append('passphrase',document.getElementById('restorepass').value);
  showRestoreOverlay(S.restoring);
  fetch('/api/provision/restore',{method:'POST',headers:h(),body:fd}).then(function(r){return r.json()}).then(function(res){
    // /api/provision/restore only confirms the restore job STARTED (it runs
    // in a background thread on the box) — poll its status instead of
    // finalizing/rebooting on this same response, or a reboot could land
    // mid-restore.
    if(res.success&&res.started){pollRestoreStatus();return}
    hideRestoreOverlay();
    document.getElementById('restoremsg').textContent=res.message||S.restoreFailed;
  });
}
function pollRestoreStatus(){
  jget('/api/provision/restore/status').then(function(st){
    if(st.state==='done'){
      netPhaseDone=true;
      jpost('/api/provision/finalize',{reboot:true});
      hideRestoreOverlay();
      waitForReboot();
    }else if(st.state==='error'){
      hideRestoreOverlay();
      document.getElementById('restoremsg').textContent=st.message||S.restoreFailed;
    }else{
      showRestoreOverlay(st.message||S.restoring);
      setTimeout(pollRestoreStatus,1500);
    }
  }).catch(function(){
    // The restore's own "applying changes" phase can restart hifi-webui
    // itself (a restored admin-account DB does exactly that) -- this fetch
    // fails for the few seconds that takes. Without this, the poll loop died
    // silently right here and left the overlay stuck forever on whatever
    // message was last shown. Keep it up and keep retrying instead; once
    // hifi-webui is back this resumes exactly like any other poll tick.
    setTimeout(pollRestoreStatus,1500);
  });
}

// Same "waiting to reconnect" pattern as the authenticated admin webui's
// reboot overlay (Settings.vue) -- this captive page is a separate, plain
// JS codebase (no shared components possible), but restoring from backup
// here ends in a real reboot too, and left the phone with nothing but a
// static "reconnect in about a minute" message and no actual feedback.
function waitForReboot(){
  document.getElementById('reboot-title').textContent=S.rebootTitle;
  document.getElementById('reboot-auto-msg').textContent=S.rebootAuto;
  document.getElementById('reboot-phase-msg').textContent=S.rebootGoingDown;
  document.getElementById('reboot-overlay').style.display='flex';
  var deadline=Date.now()+6*60*1000;
  var tries=0;
  function ping(){return fetch('/api/auth/status').then(function(r){return r.ok}).catch(function(){return false})}
  function checkDown(){
    tries++;
    ping().then(function(ok){
      if(!ok||tries>=10||Date.now()>deadline){beginComingBack();return}
      setTimeout(checkDown,1500)
    })
  }
  function beginComingBack(){
    document.getElementById('reboot-phase-msg').textContent=S.rebootComingBack;
    setTimeout(pollBack,3000)
  }
  function pollBack(){
    if(Date.now()>deadline)return;
    ping().then(function(ok){
      if(ok){location.reload();return}
      setTimeout(pollBack,2500)
    })
  }
  checkDown();
}

function connect(){var b={ssid:document.getElementById('ssid').value,password:document.getElementById('pass').value};
  document.getElementById('netmsg').textContent=hostMsg(S.connecting);
  jpost('/api/provision/wifi_connect',b)}
function useWired(){jpost('/api/provision/use_wired',{}).then(function(res){
  if(res.success){netPhaseDone=true;checkMandatoryUpdate()}else{document.getElementById('netmsg').textContent=res.message||S.noCable}})}

function setDeviceName(){
  var v=document.getElementById('devname').value.trim();
  if(!v){show('step-mode');return}
  document.getElementById('devnamemsg').textContent=S.devnameSaving;
  jpost('/api/provision/set_name',{name:v}).then(function(res){
    if(res.success){deviceHost=v.toLowerCase();show('step-mode')}
    else{document.getElementById('devnamemsg').textContent=res.message||S.error}
  });
}

function claim(m){jpost('/api/provision/claim_mode',{mode:m,source:'web'}).then(function(res){
  if(!res.success){return}
  window._chosenMode=m;
  // Pointer visibility only means anything with an actual screen — headless
  // and server-only skip straight to audio.
  if(m==='gui'){show('step-pointer')}else{loadAudio();show('step-audio')}
})}
function setPointer(enable){
  jpost('/api/provision/pointer',{enable:enable}).then(function(){
    loadAudio();show('step-audio');
  });
}

function loadAudio(){
  jget('/api/provision/audio_devices').then(function(res){
    var box=document.getElementById('audiodevs');box.innerHTML='';
    ((res&&res.devices)||[]).forEach(function(d){var b=document.createElement('button');b.className='sec';b.textContent=d.name||d.id;
      b.onclick=function(){jpost('/api/provision/set_audio_device',{device:d.id}).then(function(){show('step-lyrion')})};
      box.appendChild(b)});
  });
}
function skipAudio(){show('step-lyrion')}

function showLyrionFollow(){
  document.getElementById('lyrionfollow').style.display='block';
  jget('/api/provision/discover_lms').then(function(res){
    var box=document.getElementById('lyrionservers');box.innerHTML='';
    ((res&&res.servers)||[]).forEach(function(s){var b=document.createElement('button');b.className='sec';b.textContent=(s.name||s.ip)+' — '+s.ip;
      b.onclick=function(){document.getElementById('lyrionhost').value=s.ip};box.appendChild(b)});
  });
}
function setLyrion(mode){
  var host=mode==='follow'?document.getElementById('lyrionhost').value.trim():null;
  jpost('/api/provision/lyrion_mode',{mode:mode,host:host}).then(function(res){
    if(!res.success){document.getElementById('lyrionmsg').textContent=res.message||S.error;return}
    lyrionMode=mode;
    if(mode==='local'){checkLyrionInstall()}else{show('step-timezone');loadTimezone()}
  });
}

// hifi-firstboot.service normally installs Lyrion on its own on first real
// boot, but it only retries "next boot" if it had no network yet — which can
// easily still be true by the time this wizard's network step finishes.
// Check and, if missing, install it here rather than silently leaving the
// unit with no Lyrion at all.
function checkLyrionInstall(){
  show('step-lyrion-install');
  document.getElementById('lyrion-install-msg').textContent=S.lyrionChecking;
  document.getElementById('lyrionchannel').style.display='none';
  document.getElementById('btn-lyrion-install').style.display='none';
  document.getElementById('btn-lyrion-install-skip').style.display='none';
  document.getElementById('lyrion-install-barwrap').style.display='none';
  jget('/api/provision/lyrion_check').then(function(res){
    var cur=res&&res.current;
    if(cur&&cur!=='unknown'){afterLyrionInstall(true);return}
    document.getElementById('lyrion-install-msg').textContent=S.lyrionMissing;
    var sel=document.getElementById('lyrionchannel');sel.innerHTML='';
    var channels=(res&&res.channels)||{};
    var channelKeys=Object.keys(channels);
    channelKeys.forEach(function(c){var o=document.createElement('option');o.value=c;
      o.textContent=c+(channels[c]&&channels[c].version?' ('+channels[c].version+')':'');sel.appendChild(o)});
    // Default to 'release' explicitly rather than relying on it happening to
    // be the first key the backend returned -- fall back to whatever key IS
    // first if 'release' isn't offered at all.
    if(channels.hasOwnProperty('release')){sel.value='release'}
    else if(channelKeys.length){sel.value=channelKeys[0]}
    sel.style.display=channelKeys.length?'block':'none';
    document.getElementById('btn-lyrion-install').style.display='block';
    document.getElementById('btn-lyrion-install-skip').style.display='block';
  });
}
function installLyrion(){
  var sel=document.getElementById('lyrionchannel');
  var channel=(sel.style.display!=='none'&&sel.value)?sel.value:undefined;
  sel.style.display='none';
  document.getElementById('btn-lyrion-install').style.display='none';
  document.getElementById('btn-lyrion-install-skip').style.display='none';
  document.getElementById('lyrion-install-msg').textContent=S.lyrionInstalling;
  document.getElementById('lyrion-install-barwrap').style.display='block';
  jpost('/api/provision/lyrion_install',{channel:channel}).then(function(res){
    if(!res.started){
      document.getElementById('lyrion-install-msg').textContent=res.message||S.error;
      document.getElementById('lyrion-install-barwrap').style.display='none';
      document.getElementById('btn-lyrion-install-skip').style.display='block';
      return;
    }
    pollLyrionInstall();
  });
}
// hifi-lyrion-update.sh (like the other hifi-*-update.sh scripts) writes its
// progress `message` in Italian only -- not locale-aware. `state` is the one
// locale-neutral field it emits, so that drives the displayed text; the raw
// message is kept only for 'error' (a diagnostic reason) and as a
// last-resort fallback for a state this map doesn't know about. Mirrors
// progressStateMessage() in src/pages/Settings.jsx.
function lyrionProgressMessage(state,rawMessage){
  if(state==='error')return rawMessage||S.lyrionInstallFailed;
  var known={downloading:S.lyrionDownloading,applying:S.lyrionInstalling,restarting:S.lyrionRestarting,done:S.lyrionInstalling};
  return (state in known)?known[state]:rawMessage;
}
function pollLyrionInstall(){
  jget('/api/provision/lyrion_status').then(function(st){
    if(typeof st.progress==='number'){document.getElementById('lyrion-install-bar').style.width=st.progress+'%'}
    document.getElementById('lyrion-install-msg').textContent=lyrionProgressMessage(st.state,st.message);
    if(st.state==='done'){afterLyrionInstall(true)}
    else if(st.state==='error'){
      document.getElementById('btn-lyrion-install-skip').style.display='block';
    }else{setTimeout(pollLyrionInstall,1500)}
  });
}
function skipLyrionInstall(){afterLyrionInstall(false)}
function afterLyrionInstall(hasLyrion){
  if(restoringFromBackup){restoringFromBackup=false;doRestoreUpload();return}
  // The skin step needs a local Lyrion to restyle; when the install was
  // skipped (or Lyrion is absent) it would only 409, so go straight on.
  if(hasLyrion){showSkinStep();return}
  checkAccountStep();
}
function showSkinStep(){
  show('step-lms-skin');
  document.getElementById('skinmsg').textContent='';
  document.getElementById('skin-barwrap').style.display='none';
  document.getElementById('btn-skin-osmium').style.display='block';
  document.getElementById('btn-skin-material').style.display='block';
  document.getElementById('btn-skin-skip').style.display='none';
}
function chooseSkin(v){
  document.getElementById('btn-skin-osmium').style.display='none';
  document.getElementById('btn-skin-material').style.display='none';
  document.getElementById('btn-skin-skip').style.display='none';
  document.getElementById('skinmsg').textContent=S.skinApplying;
  document.getElementById('skin-barwrap').style.display='block';
  jpost('/api/provision/lms_skin',{skin:v}).then(function(res){
    if(!res||!res.started){
      document.getElementById('skinmsg').textContent=(res&&res.message)||S.skinFailed;
      document.getElementById('skin-barwrap').style.display='none';
      document.getElementById('btn-skin-osmium').style.display='block';
      document.getElementById('btn-skin-material').style.display='block';
      document.getElementById('btn-skin-skip').style.display='block';
      return;
    }
    pollSkinStatus();
  });
}
// Same state→text convention as lyrionProgressMessage(): `state` is the
// locale-neutral field, the raw message is a fallback only.
function skinProgressMessage(state,rawMessage){
  if(state==='error')return rawMessage||S.skinFailed;
  var known={installing:S.skinInstalling,applying:S.skinApplying,done:S.skinDone};
  return (state in known)?known[state]:(rawMessage||S.skinApplying);
}
function pollSkinStatus(){
  jget('/api/provision/lms_skin_status').then(function(st){
    if(typeof st.progress==='number'){document.getElementById('skin-bar').style.width=st.progress+'%'}
    document.getElementById('skinmsg').textContent=skinProgressMessage(st.state,st.message);
    if(st.state==='done'){showPluginsStep()}
    else if(st.state==='error'){
      document.getElementById('skin-barwrap').style.display='none';
      document.getElementById('btn-skin-osmium').style.display='block';
      document.getElementById('btn-skin-material').style.display='block';
      document.getElementById('btn-skin-skip').style.display='block';
    }else{setTimeout(pollSkinStatus,1500)}
  });
}

// Lyrion ships its own setup wizard and used to run right after this one,
// asking the same four things again: language, which plugins to install, the
// music folder and the playlist folder. Three of those are already answered by
// the time we get here (Sources owns the music folder, the appliance
// provisions the playlist folder, the step above owns the skin), so this step
// asks the one that was left and then marks Lyrion's wizard as done — see
// _lms_setup_apply() in sources_server.py. Nothing here is a gate: any failure
// still lets the user reach the account step, and the plugins stay installable
// from Lyrion afterwards.
function showPluginsStep(){
  show('step-lms-plugins');
  document.getElementById('pluginsmsg').textContent='';
  document.getElementById('plugins-barwrap').style.display='none';
  document.getElementById('btn-plugins-go').style.display='block';
  document.getElementById('btn-plugins-skip').style.display='block';
  document.getElementById('btn-plugins-continue').style.display='none';
  var box=document.getElementById('plugin-list');box.innerHTML='';
  // The offered list comes from the backend (LMS_SETUP_PLUGINS), the wording
  // from our own dictionary -- the plugin repository's own descriptions are
  // English-only marketing copy.
  jget('/api/provision/lms_setup').then(function(res){
    ((res&&res.plugins)||[]).forEach(function(p){
      var lbl=document.createElement('label');lbl.className='chk';
      var cb=document.createElement('input');cb.type='checkbox';
      cb.id='plg-'+p.id;cb.checked=!!(p['default']||p.installed);
      var txt=document.createElement('span');
      var t=document.createElement('span');t.className='t';t.textContent=S['plg_'+p.id]||p.id;
      var d=document.createElement('span');d.className='d';d.textContent=S['plgd_'+p.id]||'';
      txt.appendChild(t);txt.appendChild(d);
      lbl.appendChild(cb);lbl.appendChild(txt);
      box.appendChild(lbl);
    });
    document.getElementById('plg-analytics').checked=!!(res&&res.analytics);
  }).catch(function(){});
}
function selectedPlugins(){
  var out=[];
  var boxes=document.getElementById('plugin-list').querySelectorAll('input[type=checkbox]');
  Array.prototype.forEach.call(boxes,function(cb){if(cb.checked)out.push(cb.id.slice(4))});
  return out;
}
function applyLmsSetup(){
  sendLmsSetup(selectedPlugins(),document.getElementById('plg-analytics').checked);
}
// "Skip" still POSTs: marking Lyrion's wizard done (and pinning the usage
// report to off) is the point of this step -- skipping only means "install
// nothing". Without the call, the user would land straight in Lyrion's own
// wizard at the end of setup, which is exactly what this replaces.
function skipLmsSetup(){sendLmsSetup([],false)}
function sendLmsSetup(plugins,analytics){
  document.getElementById('btn-plugins-go').style.display='none';
  document.getElementById('btn-plugins-skip').style.display='none';
  document.getElementById('btn-plugins-continue').style.display='none';
  document.getElementById('pluginsmsg').textContent=S.lmsPluginsInstalling;
  document.getElementById('plugins-barwrap').style.display='block';
  jpost('/api/provision/lms_setup',{plugins:plugins,analytics:analytics,language:LANG}).then(function(res){
    // No local Lyrion to configure (external server, or the install was
    // skipped) -- there is no wizard to suppress either, so just move on.
    if(!res||!res.started){checkAccountStep();return}
    pollLmsSetup();
  }).catch(function(){checkAccountStep()});
}
// Same state->text convention as lyrionProgressMessage()/skinProgressMessage():
// `state` is the locale-neutral field, the raw message is a fallback only.
function lmsSetupMessage(state,rawMessage){
  if(state==='error')return rawMessage||S.lmsPluginsFailed;
  var known={installing:S.lmsPluginsInstalling,applying:S.lmsPluginsApplying,done:S.lmsPluginsDone};
  return (state in known)?known[state]:(rawMessage||S.lmsPluginsInstalling);
}
function pollLmsSetup(){
  jget('/api/provision/lms_setup_status').then(function(st){
    if(typeof st.progress==='number'){document.getElementById('plugins-bar').style.width=st.progress+'%'}
    document.getElementById('pluginsmsg').textContent=lmsSetupMessage(st.state,st.message);
    if(st.state==='done'){checkAccountStep();return}
    if(st.state==='error'){
      // Offer a retry rather than silently carrying on: this is where
      // wizardDone gets written, and a device that skips it shows Lyrion's own
      // wizard at the end of setup.
      document.getElementById('plugins-barwrap').style.display='none';
      document.getElementById('btn-plugins-go').style.display='block';
      document.getElementById('btn-plugins-continue').style.display='block';
      return;
    }
    setTimeout(pollLmsSetup,1500);
  }).catch(function(){setTimeout(pollLmsSetup,1500)});
}

// The web-admin account used to only get asked for the first time you
// opened the web interface, which for a screenless/AP-hotspot setup meant
// AFTER finishing Lyrion's own wizard too — easy to forget, and it left the
// device reachable-but-unclaimed in the meantime. Create it here instead,
// unless one already exists (e.g. this wizard is being re-run, or the
// account was already created from the web interface directly). Also now
// the thing that unlocks the REAL Sources page below (session-gated) rather
// than a pre-auth workaround, so it has to happen before that step, not after.
function checkAccountStep(){
  show('step-account');
  jget('/api/auth/status').then(function(res){
    if(res&&res.has_account){show('step-timezone');loadTimezone();return}
  });
}
function createAccount(){
  var u=document.getElementById('acc-user').value.trim();
  var p=document.getElementById('acc-pass').value;
  var p2=document.getElementById('acc-pass2').value;
  if(u.length<3||p.length<8){document.getElementById('accountmsg').textContent=S.accountTooShort;return}
  if(p!==p2){document.getElementById('accountmsg').textContent=S.accountMismatch;return}
  document.getElementById('accountmsg').textContent=S.creating;
  jpost('/api/provision/create_account',{username:u,password:p}).then(function(res){
    if(res.success){show('step-timezone');loadTimezone()}
    else{document.getElementById('accountmsg').textContent=res.message||S.error}
  });
}

function loadTimezone(){
  jget('/api/provision/timezone').then(function(res){
    var sel=document.getElementById('tzselect');sel.innerHTML='';
    (res.timezones||[]).forEach(function(z){var o=document.createElement('option');o.value=z;o.textContent=z;
      if(z===res.timezone)o.selected=true;sel.appendChild(o)});
  });
}
function saveTimezone(){
  var tz=document.getElementById('tzselect').value;
  jpost('/api/provision/set_timezone',{timezone:tz}).then(function(){
    // Account + timezone are the last things that need the pre-auth
    // provisioning API -- finalize now (marker removed, AP torn down, mode
    // switched live) so the sources step below can open the REAL,
    // session-authenticated Vue Settings page instead of a pre-auth
    // workaround. finish()'s own finalize call later becomes a harmless
    // no-op (provision_finalize() early-returns once already finalized).
    jpost('/api/provision/finalize',{}).then(function(){showSourcesStep()});
  });
}

function showSourcesStep(){
  show('step-sources-ask');
}
// Most setups have nothing beyond a USB drive plugged into the device, which
// already automounts on its own -- forcing everyone through the sources page
// just to click past it added a step for no reason. "No" skips straight to
// finish (nothing was configured, nothing to apply); "Yes" opens a small
// native guided flow -- add a NAS share and/or an internal disk, as many as
// wanted, each one dropping back to "Add a source" until Done is pressed.
// Talks straight to the SAME session-gated endpoints the real Settings ->
// Sources page uses (/api/system/sources|internal/*), no separate page.
function sourcesAsk(yes){
  if(yes){show('step-sources-type')}else{showFinishScreen()}
}

// ── NAS / SMB share ────────────────────────────────────────────────
function showSmbForm(){
  document.getElementById('smb-server').value='';
  document.getElementById('smb-share').value='';
  document.getElementById('smb-user').value='';
  document.getElementById('smb-pass').value='';
  document.getElementById('smb-msg').textContent='';
  show('step-sources-smb');
}
function submitSmb(){
  var server=document.getElementById('smb-server').value.trim();
  var share=document.getElementById('smb-share').value.trim();
  if(!server||!share){document.getElementById('smb-msg').textContent=S.smbFieldsRequired;return}
  document.getElementById('smb-msg').textContent=S.smbConnecting;
  jpost('/api/system/sources/smb',{
    server:server,share:share,
    username:document.getElementById('smb-user').value.trim(),
    password:document.getElementById('smb-pass').value,
    // Mount only -- don't hand the share to Lyrion until the folder step
    // below confirms "whole share" or a subfolder (see api_add_smb()'s
    // defer_activation in sources_server.py).
    defer_activation:true
  }).then(function(res){
    if(res.success){
      document.getElementById('smb-msg').textContent=S.smbConnected;
      smbFolderSourceId=res.id;
      smbFolderPath='';
      smbFolderParent=null;
      setTimeout(function(){show('step-sources-smb-folder');loadSmbFolder()},800);
    }else{
      document.getElementById('smb-msg').textContent=res.message||S.error;
    }
  }).catch(function(){document.getElementById('smb-msg').textContent=S.error});
}

// ── NAS / SMB: whole-share vs. subfolder, after the mount above succeeds ──
// Reuses the same browse/subpath endpoints as Settings -> Sources' "Pick a
// subfolder" (sources_server.py's api_browse_subpath()/api_set_subpath()),
// just as a native step here instead of a modal, matching this page's style.
var smbFolderSourceId=null,smbFolderPath='',smbFolderParent=null;
function loadSmbFolder(){
  document.getElementById('smb-folder-msg').textContent='';
  document.getElementById('smb-folder-list').textContent=S.internalLoading;
  document.getElementById('btn-smb-folder-up').disabled=true;
  jget('/api/system/sources/'+encodeURIComponent(smbFolderSourceId)+'/browse?path='+encodeURIComponent(smbFolderPath))
  .then(function(res){
    document.getElementById('smb-folder-path').textContent='/'+(res.path||'');
    smbFolderParent=(res.parent===null||res.parent===undefined)?null:res.parent;
    document.getElementById('btn-smb-folder-up').disabled=(smbFolderParent===null);
    var box=document.getElementById('smb-folder-list');box.innerHTML='';
    var dirs=res.dirs||[];
    if(!dirs.length){box.textContent=S.smbFolderNoSubfolders;return}
    dirs.forEach(function(name){
      var row=document.createElement('div');row.className='net';row.style.cursor='pointer';
      row.textContent=name;
      row.onclick=function(){smbFolderPath=smbFolderPath?smbFolderPath+'/'+name:name;loadSmbFolder()};
      box.appendChild(row);
    });
  }).catch(function(){document.getElementById('smb-folder-msg').textContent=S.error});
}
function smbFolderUp(){
  if(smbFolderParent===null)return;
  smbFolderPath=smbFolderParent;
  loadSmbFolder();
}
function smbFolderUseHere(){
  document.getElementById('smb-folder-msg').textContent=S.smbFolderSaving;
  jpost('/api/system/sources/'+encodeURIComponent(smbFolderSourceId)+'/subpath',{subpath:smbFolderPath}).then(function(res){
    if(res.success){show('step-sources-type')}
    else{document.getElementById('smb-folder-msg').textContent=res.message||S.error}
  }).catch(function(){document.getElementById('smb-folder-msg').textContent=S.error});
}

// ── Internal disk (adopt existing filesystem, or format+adopt) ───────
function showInternalDisks(){
  document.getElementById('internal-list-wrap').style.display='block';
  document.getElementById('internal-format-wrap').style.display='none';
  show('step-sources-internal');
  loadInternalDisks();
}
function fmtDiskSize(bytes){
  var gb=(Number(bytes)||0)/1073741824;
  if(gb<=0)return'';
  return gb>=1000?(gb/1024).toFixed(1)+' TB':Math.round(gb)+' GB';
}
function loadInternalDisks(){
  var box=document.getElementById('internal-list');
  box.textContent=S.internalLoading;
  jget('/api/system/internal/disks').then(function(res){
    var disks=(res&&res.disks)||[];
    box.innerHTML='';
    if(!disks.length){box.textContent=S.internalNone;return}
    disks.forEach(function(d){
      var part=(d.partitions||[]).find(function(p){return p.fstype});
      var row=document.createElement('div');row.className='net';
      var title=(d.model||'Disk')+' · '+fmtDiskSize(d.size);
      var btn=document.createElement('button');btn.className='sec';btn.style.marginTop='6px';
      if(d.adopted){
        row.innerHTML='<div class="row"><span>'+title+'</span><span class="muted">'+S.internalAlreadyUsed+'</span></div>';
      }else if(part){
        row.innerHTML='<div>'+title+'</div>';
        btn.textContent=S.internalUseBtn;
        btn.onclick=function(){adoptInternal(part.path)};
        row.appendChild(btn);
      }else{
        row.innerHTML='<div>'+title+'</div>';
        btn.textContent=S.internalFormatBtn;
        btn.onclick=function(){openFormatWizard(d)};
        row.appendChild(btn);
      }
      box.appendChild(row);
    });
  });
}
function adoptInternal(device){
  var box=document.getElementById('internal-list');
  box.textContent=S.internalAdopting;
  jpost('/api/system/internal/adopt',{device:device}).then(function(res){
    if(res.success){setTimeout(function(){show('step-sources-type')},1200)}
    else{document.getElementById('internal-list').textContent=res.message||S.error;setTimeout(loadInternalDisks,1500)}
  }).catch(function(){loadInternalDisks()});
}

// Format sub-flow: choose fs+label -> type the label back to confirm (a
// destructive op, same "type it to prove you mean it" pattern as the real
// Settings page) -> progress (polled) -> done. One disk at a time.
var pendingFormatDisk=null;
function openFormatWizard(disk){
  pendingFormatDisk=disk;
  document.getElementById('format-warn').textContent=S.formatWarn.replace('{disk}',disk.model||disk.path);
  document.getElementById('format-fs').value='ext4';
  document.getElementById('format-label').value='Musica';
  document.getElementById('format-typed').value='';
  document.getElementById('internal-list-wrap').style.display='none';
  document.getElementById('internal-format-wrap').style.display='block';
  document.getElementById('format-choose').style.display='block';
  document.getElementById('format-confirm').style.display='none';
  document.getElementById('format-progress').style.display='none';
  document.getElementById('format-done').style.display='none';
}
function cancelFormat(){
  pendingFormatDisk=null;
  document.getElementById('internal-format-wrap').style.display='none';
  document.getElementById('internal-list-wrap').style.display='block';
}
function formatConfirmStep(){
  document.getElementById('format-confirm-msg').textContent=
    S.formatConfirmMsg.replace('{label}',document.getElementById('format-label').value.trim());
  document.getElementById('format-choose').style.display='none';
  document.getElementById('format-confirm').style.display='block';
  updateFormatGoState();
}
function updateFormatGoState(){
  var label=document.getElementById('format-label').value.trim();
  var typed=document.getElementById('format-typed').value.trim();
  document.getElementById('btn-format-go').disabled=!(label&&typed===label);
}
function startFormat(){
  document.getElementById('format-confirm').style.display='none';
  document.getElementById('format-progress').style.display='block';
  document.getElementById('format-progress-msg').textContent=S.formatting;
  jpost('/api/system/internal/format',{
    device:pendingFormatDisk.path,
    fs:document.getElementById('format-fs').value,
    label:document.getElementById('format-label').value.trim(),
    confirm:pendingFormatDisk.confirm
  }).then(function(res){
    if(!res.success){
      document.getElementById('format-progress-msg').textContent=res.message||S.error;
      return;
    }
    pollFormatStatus();
  }).catch(function(){document.getElementById('format-progress-msg').textContent=S.error});
}
function pollFormatStatus(){
  jget('/api/system/internal/format/status').then(function(st){
    if(typeof st.progress==='number')document.getElementById('format-bar').style.width=st.progress+'%';
    if(st.message)document.getElementById('format-progress-msg').textContent=st.message;
    if(st.state==='done'){
      document.getElementById('format-progress').style.display='none';
      document.getElementById('format-done-msg').textContent=S.formatDoneMsg;
      document.getElementById('format-done').style.display='block';
    }else if(st.state==='error'){
      document.getElementById('format-progress-msg').textContent=st.message||S.error;
    }else{
      setTimeout(pollFormatStatus,2000);
    }
  }).catch(function(){setTimeout(pollFormatStatus,2000)});
}
function formatDone(){
  pendingFormatDisk=null;
  document.getElementById('internal-format-wrap').style.display='none';
  show('step-sources-type');
}

// Safety-net apply: nothing else in this native flow pushes the final
// source list into Lyrion's prefs on its own (unlike the old iframe page's
// own Apply button) — do it once here, right before finishing. Session-
// gated, not the old pre-auth provisioning route (provisioning is already
// finalized by this point). Proceeds regardless of outcome: a wrong/missing
// source can be fixed later from Settings, it shouldn't block finishing.
function continueFromSources(){
  jpost('/api/system/apply',{}).then(showFinishScreen).catch(showFinishScreen);
}
function showFinishScreen(){
  show('step-finish');
  var m=window._chosenMode||'headless';
  document.getElementById('finishmsg').textContent=hostMsg(m==='gui'?S.finishGui:(m==='off'?S.finishOff:S.finishHeadless));
  document.getElementById('btn-finish').style.display='block';
}

function finish(){jpost('/api/provision/finalize',{}).then(function(){
  document.getElementById('btn-finish').style.display='none';
  if(lyrionMode==='local'){
    // Straight into the web player. This used to land on Lyrion's own setup
    // wizard, which showed itself on the first visit to its web UI and asked
    // the same questions over again; step-lms-plugins now answers the last of
    // them and sets wizardDone, so the same URL opens the player itself, with
    // the chosen skin and a library scan already running.
    document.getElementById('finishmsg').textContent=S.finishToLyrion;
    setTimeout(function(){location.href='http://'+location.hostname+':9000/'},1500);
  }else{
    document.getElementById('finishmsg').textContent=hostMsg(S.finishDone);
  }
})}
setInterval(load,3000);load();
</script></body></html>"""

# ─────────────────────────────────────────────────────────────────────────
#  INSTALLER flow: pick a target disk, confirm the erase, start the install,
#  mirror progress read-only, then auto-reboot. Reached only when this live
#  session was booted from the "Install Osmium Sound" menu entry
#  (hifi.installer=1) — no OS on disk yet, so no provisioning marker/account
#  concept applies; _boot_mode() alone gates these endpoints.
# ─────────────────────────────────────────────────────────────────────────
INSTALL_CAPTIVE_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Osmium Sound — Install</title>
<style>""" + _CAPTIVE_CSS + """</style></head><body>
<h1 id="h1title">Osmium Sound — Install</h1>

<div class="card" id="step-disks">
 <p class="muted" id="disks-intro">Choose the disk to install onto. Everything on it will be erased.</p>
 <div id="disklist"></div>
 <p class="muted" id="disksmsg"></p>
</div>

<div class="card" id="step-confirm" style="display:none">
 <p id="confirmtext" class="muted"></p>
 <button class="sec" onclick="show('step-disks')" id="btn-cancel">Cancel</button>
 <button onclick="startInstall()" id="btn-confirm">Erase and install</button>
</div>

<div class="card" id="step-progress" style="display:none">
 <p class="muted" id="progressmsg"></p>
 <div class="bar"><div id="progressbar" style="width:0%"></div></div>
</div>

<div class="card" id="step-done" style="display:none">
 <p class="muted" id="donemsg"></p>
</div>

<script>
// English only, on purpose: this runs before any language/account setup
// exists on the machine (replaces Debian Installer), so there's no
// language preference to read yet — see src/pages/InstallWizard.jsx.
var CONFIRM_TEXT='This will ERASE ALL DATA on {disk} and install Osmium Sound. This cannot be undone.';
var ERROR_PREFIX='Error: ';

function h(){return {'X-CSRF-Token':(document.cookie.match(/csrf=([^;]+)/)||[])[1]||''}}
function jpost(p,b){return fetch(p,{method:'POST',headers:Object.assign({'Content-Type':'application/json'},h()),body:JSON.stringify(b||{})}).then(function(r){return r.json()})}
function jget(p){return fetch(p,{headers:h()}).then(function(r){return r.json()})}
function show(id){['step-disks','step-confirm','step-progress','step-done'].forEach(function(s){document.getElementById(s).style.display=(s===id?'block':'none')})}

var selectedDisk=null;
function loadDisks(){
  jget('/api/provision/install_disks').then(function(res){
    var box=document.getElementById('disklist');box.innerHTML='';
    var disks=(res&&res.disks)||[];
    if(!disks.length){document.getElementById('disksmsg').textContent='No usable disks found.';return}
    disks.forEach(function(d){var el=document.createElement('div');el.className='disk';
      var gb=d.size?Math.round(d.size/1e9)+' GB':'';
      el.textContent=(d.model||d.path)+' — '+d.path+(gb?' ('+gb+')':'');
      el.onclick=function(){selectedDisk=d.path;
        document.querySelectorAll('.disk').forEach(function(x){x.className='disk'});el.className='disk sel';
        document.getElementById('confirmtext').textContent=CONFIRM_TEXT.replace('{disk}',d.path);
        show('step-confirm')};
      box.appendChild(el)});
  });
}
function startInstall(){
  if(!selectedDisk)return;
  show('step-progress');
  document.getElementById('progressmsg').textContent='Starting install…';
  jpost('/api/provision/install_start',{device:selectedDisk}).then(function(res){
    if(!res.success){document.getElementById('progressmsg').textContent=res.message||ERROR_PREFIX;return}
    pollStatus();
  });
}
function pollStatus(){
  jget('/api/provision/install_status').then(function(st){
    if(typeof st.progress==='number'){document.getElementById('progressbar').style.width=st.progress+'%'}
    if(st.message){document.getElementById('progressmsg').textContent=st.message}
    if(st.state==='done'){
      show('step-done');
      var n=5;
      var tick=function(){document.getElementById('donemsg').textContent='Install complete. Rebooting in '+n+'s…';
        if(n<=0){jpost('/api/provision/reboot',{});return}
        n--;setTimeout(tick,1000)};
      tick();
    }else if(st.state==='error'){
      document.getElementById('progressmsg').textContent=ERROR_PREFIX+(st.message||'');
    }else{
      setTimeout(pollStatus,1000);
    }
  });
}
loadDisks();
</script></body></html>"""

# Network-loss recovery portal: an already-configured unit that lost BOTH
# wired and Wi-Fi connectivity raises this same-styled but much smaller page —
# just re-enter Wi-Fi credentials, nothing else. It self-resolves: once the
# network monitor confirms connectivity again it tears the AP down on its own,
# no "finish" step needed here.
NET_RECOVERY_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Osmium Sound — Network</title>
<style>
 body{font-family:system-ui,sans-serif;background:#0f1115;color:#eee;margin:0;padding:24px;max-width:520px;margin:auto}
 h1{font-size:20px} .card{background:#1a1e26;border-radius:12px;padding:16px;margin:14px 0}
 label{display:block;font-size:13px;color:#aab;margin:8px 0 4px} input,button{width:100%;padding:12px;border-radius:8px;border:1px solid #333;background:#12151b;color:#eee;font-size:15px;box-sizing:border-box}
 button{background:#c8a24a;color:#111;font-weight:600;border:0;margin-top:12px} .muted{color:#889;font-size:13px}
 .net{padding:10px;border-bottom:1px solid #262b35;cursor:pointer} .row{display:flex;justify-content:space-between}
 .langbar{text-align:right;margin-bottom:8px} .langbar a{color:#889;font-size:13px;text-decoration:none;margin-left:10px}
 .langbar a.active{color:#c8a24a;font-weight:600}
</style></head><body>
<div class="langbar">
 <a href="?lang=en" id="lang-en">English</a><a href="?lang=it" id="lang-it">Italiano</a>
</div>
<h1 id="h1title">Osmium Sound — Network unreachable</h1>
<p class="muted" id="introtext">This device is already configured and lost its connection (neither cable nor Wi-Fi is working). Reconnect it by choosing a Wi-Fi network below — nothing else will be changed.</p>
<div class="card">
 <label id="lbl-wifi">Wi-Fi network</label>
 <div id="nets"></div>
 <label id="lbl-ssid">Or enter the network name (SSID)</label>
 <input id="ssid" placeholder="Network name">
 <label id="lbl-pass">Wi-Fi password</label>
 <input id="pass" type="password" placeholder="Password">
 <button onclick="connect()" id="btn-connect">Connect</button>
 <p class="muted" id="netmsg"></p>
</div>
<script>
var STRINGS={
 en:{intro:'This device is already configured and lost its connection (neither cable nor Wi-Fi is working). Reconnect it by choosing a Wi-Fi network below — nothing else will be changed.',wifi:'Wi-Fi network',ssid:'Or enter the network name (SSID)',pass:'Wi-Fi password',connect:'Connect',connecting:'Connecting… if you return to your network this page will no longer be reachable here — reopen http://__DEVICE_HOST__.local',error:'Error: '},
 it:{intro:'Il dispositivo è già configurato e ha perso la connessione (né cavo né Wi-Fi funzionanti). Ricollegalo scegliendo una rete Wi-Fi qui sotto — nessun\\'altra impostazione verrà modificata.',wifi:'Rete Wi-Fi',ssid:'Oppure inserisci il nome (SSID)',pass:'Password Wi-Fi',connect:'Connetti',connecting:'Connessione in corso… se torni sulla tua rete questa pagina non sarà più raggiungibile qui — riapri http://__DEVICE_HOST__.local',error:'Errore: '}
};
var LANG=(new URLSearchParams(location.search).get('lang')||'en');
if(STRINGS[LANG]===undefined)LANG='en';
var S=STRINGS[LANG];
document.getElementById('lang-'+LANG).className='active';
document.getElementById('introtext').textContent=S.intro;
document.getElementById('lbl-wifi').textContent=S.wifi;
document.getElementById('lbl-ssid').textContent=S.ssid;
document.getElementById('lbl-pass').textContent=S.pass;
document.getElementById('btn-connect').textContent=S.connect;

function h(){return {'X-CSRF-Token':(document.cookie.match(/csrf=([^;]+)/)||[])[1]||'','X-UI-Lang':LANG}}
function load(){fetch('/api/netrecovery/status',{headers:h()}).then(function(r){return r.json()}).then(function(s){
  if(!s.active){location.href='/';return}
  var n=document.getElementById('nets');n.innerHTML='';
  (s.networks||[]).forEach(function(net){var d=document.createElement('div');d.className='net';
    d.innerHTML='<div class="row"><span>'+net.ssid+'</span><span class="muted">'+net.signal+'%</span></div>';
    d.onclick=function(){document.getElementById('ssid').value=net.ssid};n.appendChild(d)});
  if(s.error){document.getElementById('netmsg').textContent=S.error+s.error}
})}
function connect(){var b={ssid:document.getElementById('ssid').value,password:document.getElementById('pass').value};
  document.getElementById('netmsg').textContent=S.connecting;
  fetch('/api/netrecovery/wifi_connect',{method:'POST',headers:Object.assign({'Content-Type':'application/json'},h()),body:JSON.stringify(b)})}
setInterval(load,3000);load();
</script></body></html>"""

FALLBACK_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Osmium Sound</title><style>body{font-family:system-ui;background:#0f1115;color:#eee;padding:40px;text-align:center}</style>
</head><body><h1>Osmium Sound — Web Admin</h1>
<p>The management interface has not been installed on this device yet.</p>
<p>The authentication and provisioning APIs are active.</p></body></html>"""


# ── startup ──────────────────────────────────────────────────────────
def _bootstrap():
    app.secret_key = _ensure_secret_key()
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Strict',
        # Not Secure: plain HTTP, no TLS -- see the module docstring's
        # security-model note. A Secure-flagged cookie would just get
        # silently dropped by the browser on every response.
        SESSION_COOKIE_SECURE=False,
        PERMANENT_SESSION_LIFETIME=7 * 24 * 3600,
    )
    _init_db()
    device = _eth_devices()[0] if _eth_devices() else _wifi_device()
    _ensure_networkmanager_state(device)


def _start_provisioning_loop():
    # Background thread: keeps the setup hotspot reconciled during provisioning.
    threading.Thread(target=_provisioning_loop, daemon=True).start()


def _start_network_monitor():
    # Background thread: wired self-heal + network-loss recovery AP. Runs
    # unconditionally (it skips its own work while provisioning is active).
    threading.Thread(target=_network_monitor_loop, daemon=True).start()


def main():
    _bootstrap()
    _start_provisioning_loop()
    _start_network_monitor()
    from werkzeug.serving import make_server
    print(f'[webui] serving HTTP on :{PORT}')
    make_server('0.0.0.0', PORT, app, threaded=True).serve_forever()


if __name__ == '__main__':
    main()
