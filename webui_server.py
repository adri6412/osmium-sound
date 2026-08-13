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
# WPA2 PSK for the setup hotspot. Fixed + documented (see SECURITY.md): the
# residual risk (an RF-range attacker who knows it can reach the pre-auth set on
# an unconfigured unit) is accepted; WPA2 still encrypts the home Wi-Fi password
# in transit and the pre-auth set carries no destructive endpoint.
AP_PSK = 'osmiumsetup'

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
    return nets


def _raise_ap(dev):
    ssid = _ap_ssid(dev)
    _nmcli(['connection', 'delete', AP_CON_NAME])  # clear any stale profile
    rc, _, err = _nmcli([
        'connection', 'add', 'type', 'wifi', 'ifname', dev, 'con-name', AP_CON_NAME,
        'autoconnect', 'no', 'ssid', ssid,
        '802-11-wireless.mode', 'ap', '802-11-wireless.band', 'bg',
        'wifi-sec.key-mgmt', 'wpa-psk', 'wifi-sec.psk', AP_PSK,
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


def _connect_wifi(ssid, password):
    """Drop the AP, try to join, and on failure delete the stale profile and
    re-raise the AP so the phone (which auto-rejoins) sees the error."""
    if not _SSID_RE.match(ssid or ''):
        return False, _wt('network.ssidInvalidChars', _lang())
    _teardown_ap()
    args = ['device', 'wifi', 'connect', ssid]
    if password:
        args += ['password', password]
    rc, _, err = _nmcli(args, timeout=45)
    if rc == 0:
        return True, ''
    # 'wifi connect' persists a bad autoconnect profile even on auth failure —
    # delete it so NM doesn't fight the AP we are about to re-raise.
    _nmcli(['connection', 'delete', 'id', ssid])
    dev = _wifi_device()
    if dev:
        _raise_ap(dev)
    return False, (err.strip() or _wt('network.connectFailed', _lang()))


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
        _net_recovery.update({'active': True, 'ssid': ssid, 'psk': AP_PSK, 'error': None})
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
    """Called at startup and on demand. Decides AP vs LAN-only vs finalize."""
    """Bring the setup hotspot up (or reconcile it) during the provisioning
    window. Called repeatedly by _provisioning_loop, so it must be idempotent
    and cheap when there is nothing to do.

    Policy: the hotspot is raised at first setup ALWAYS (Volumio-style) — even
    when Ethernet is connected — so a phone can always discover the box during
    setup. It is only skipped while a Wi-Fi connect is mid-flight, after the
    network step succeeded, or once the AP is already up."""
    if not _provisioning():
        return
    with _prov_lock:
        state = _load_prov_state()
        if state.get('finalized'):
            _do_finalize()
            return
        stage = state.get('stage')
        ap = state.get('ap') or {}
        # Leave the AP alone mid-connect, after a successful network step, or
        # when it's already up (incl. the 'failed' state, where _connect_wifi
        # already re-raised it so the phone can see the error).
        if stage in ('connecting', 'network-ok') or ap.get('active'):
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
        dnsmasq_ok = _ensure_dnsmasq()
        # Cache a scan BEFORE raising the AP (single radio can't scan while AP).
        state['networks'] = _scan_wifi()
        state['networks_cached_at'] = time.time()
        ok, ssid = _raise_ap(dev)
        if ok:
            err = None
        elif not dnsmasq_ok:
            err = _wt('network.dnsmasqMissing', _lang())
        else:
            err = _wt('network.hotspotActivateFailed', _lang())
        state['ap'] = {'active': ok, 'supported': True, 'ssid': ssid,
                       'psk': AP_PSK if ok else None, 'error': err}
        state['stage'] = 'waiting-ap' if ok else 'waiting-lan'
        _save_prov_state(state)


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
    ('/api/system/timezone', 'GET'): '/timezone',
    ('/api/system/timezone', 'POST'): '/timezone',
    ('/api/system/timezones', 'GET'): '/timezones',
    ('/api/system/vu_meter', 'GET'): '/vu_meter',
    ('/api/system/vu_meter', 'POST'): '/vu_meter',
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


@app.after_request
def _set_csrf_cookie(resp):
    # Ensure a CSRF cookie exists so the SPA can read + echo it. Not HttpOnly by
    # design (double-submit needs JS to read it). Not Secure either: plain
    # HTTP, no TLS (see the module docstring's security-model note).
    if not request.cookies.get('csrf'):
        resp.set_cookie('csrf', secrets.token_urlsafe(24), samesite='Strict',
                        secure=False, httponly=False)
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
    # Reply first (the AP is about to drop; the phone must know to expect it).
    threading.Thread(target=_bg_connect, args=(ssid, password), daemon=True).start()
    return jsonify({'success': True, 'dropping_ap': True})


def _bg_connect(ssid, password):
    with _prov_lock:
        state = _load_prov_state()
        state['stage'] = 'connecting'
        state['ssid_attempt'] = ssid
        state['error'] = None
        _save_prov_state(state)
        ok, err = _connect_wifi(ssid, password)
        state = _load_prov_state()
        if ok:
            state['stage'] = 'network-ok'
            state['ap'] = {'active': False, 'supported': True}
            state['error'] = None
        else:
            dev = _wifi_device()
            ssid_ap = _ap_ssid(dev) if dev else None
            state['stage'] = 'failed'
            state['ap'] = {'active': bool(dev), 'supported': True, 'ssid': ssid_ap, 'psk': AP_PSK}
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


@app.route('/api/provision/apply_sources', methods=['POST'])
def provision_apply_sources():
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    body, status = _proxy(SOURCES_BASE, '/api/apply', method='POST', body={}, timeout=90)
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


@app.route('/api/provision/sources_app', methods=['GET'])
def provision_sources_app():
    # The captive setup page links here instead of reimplementing source
    # management itself — mints a pairing token via the same localhost-only
    # loopback call sources_app() (above) uses for the authenticated case,
    # gated by _provisioning() instead of a session since no account exists
    # yet at this point, then redirects into the real, full-featured sources
    # SPA (local/SMB/USB/internal disk, not just SMB). ?setup=1 tells that
    # page to swap its "Apply & rescan library" copy for setup-appropriate
    # wording (see sources_server.py's index()) — Lyrion's own setup wizard
    # does the real first scan right after this step, so "rescan" here would
    # be misleading and redundant.
    if not _provisioning():
        return jsonify({'success': False, 'code': 'provision.notInProgress',
                        'message': _wt('provision.notInProgress', _lang())}), 409
    body, status = _proxy(SOURCES_BASE, '/api/pair/token', method='POST', body={})
    token = (body or {}).get('token')
    if not token:
        return jsonify({'success': False, 'code': 'sources.pairUnavailable',
                        'message': 'Pairing is unavailable.'}), 502
    lang = request.args.get('lang') or _lang()
    return redirect(f'/sources-app?token={token}&setup=1&lang={urllib.parse.quote(lang)}', code=302)


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
    ok, err = _connect_wifi(ssid, password)
    with _net_lock:
        if ok:
            # Connected: _connect_wifi already tore the AP down; the network
            # monitor's next tick confirms connectivity and would reach the
            # same state, but clearing it here immediately is more responsive.
            _net_recovery.update({'active': False, 'ssid': None, 'psk': None, 'error': None})
        else:
            # _connect_wifi already re-raised the AP itself on failure — reflect
            # that (SSID is deterministic from the MAC, so it hasn't changed).
            _net_recovery['error'] = err
            _net_recovery['active'] = True


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
                          timeout=200 if 'tailscale_install' in api_path
                          else 90 if 'apply' in api_path or 'dsp' in api_path
                          or 'tailscale' in api_path or 'ssh' in api_path else 15)
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
                         '/api/backup', '/api/restore', '/api/cd', '/api/dsp')
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
    # Explicitly allow embedding by our own Settings page (some browsers — Brave
    # in particular — are aggressive about frames that don't declare a policy).
    out.headers['Content-Security-Policy'] = "frame-ancestors 'self'"
    out.headers['X-Frame-Options'] = 'SAMEORIGIN'
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
    # dead-end page.
    extra = ''.join(f'&{k}={urllib.parse.quote(v)}'
                    for k, v in request.args.items() if k != 'token')
    return redirect(f'/sources-app?token={token}{extra}', code=302)


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
        return Response(NET_RECOVERY_HTML, mimetype='text/html')
    return _serve_spa('index.html')


@app.route('/<path:subpath>', methods=['GET'])
def spa(subpath):
    return _serve_spa(subpath)


def _serve_spa(subpath):
    full = os.path.join(DIST_DIR, subpath)
    if os.path.isfile(full):
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
 .muted{color:#889;font-size:13px}
 .net{padding:10px;border-bottom:1px solid #262b35;cursor:pointer} .row{display:flex;justify-content:space-between}
 .langbar{text-align:right;margin-bottom:8px} .langbar a{color:#889;font-size:13px;text-decoration:none;margin-left:10px}
 .langbar a.active{color:#c8a24a;font-weight:600}
 .bar{height:8px;border-radius:4px;background:#12151b;overflow:hidden;margin:10px 0}
 .bar > div{height:100%;background:#c8a24a}
 .disk{padding:12px;border:1px solid #333;border-radius:8px;margin:8px 0;cursor:pointer}
 .disk.sel{border-color:#c8a24a;background:#1f1a10}
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
<div class="langbar">
 <a href="?lang=en" id="lang-en">English</a><a href="?lang=it" id="lang-it">Italiano</a>
</div>
<h1 id="h1title">Osmium Sound — Setup</h1>

<div class="card" id="step-restore">
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
 <label id="lbl-audio">Audio output</label>
 <div id="audiodevs"></div>
 <p class="muted" id="audiomsg"></p>
 <button class="sec" onclick="skipAudio()" id="btn-audio-skip">Continue</button>
</div>

<div class="card" id="step-lyrion" style="display:none">
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

<div class="card" id="step-sources" style="display:none">
 <label id="lbl-sources">Music sources</label>
 <p class="muted" id="sources-intro">Manage local, network (SMB) and USB sources below. Optional: you can also do this later from Settings. Lyrion's own setup wizard scans the library once you finish here.</p>
 <iframe id="sources-iframe" style="width:100%;height:60vh;min-height:380px;border:0;border-radius:10px;background:#1a1e26"></iframe>
 <button class="sec" onclick="continueFromSources()" id="btn-sources-continue">Continue</button>
</div>

<div class="card" id="step-timezone" style="display:none">
 <label id="lbl-timezone">Time zone</label>
 <select id="tzselect"></select>
 <button onclick="saveTimezone()" id="btn-tz-save">Save and continue</button>
 <p class="muted" id="tzmsg"></p>
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

<div class="card" id="step-finish" style="display:none">
 <p id="finishmsg" class="muted"></p>
 <button id="btn-finish" onclick="finish()" style="display:none">Complete setup</button>
</div>

<script>
var STRINGS={
 en:{restoreIntro:'Setting up a new device? Restore a previous backup, or start fresh.',fresh:'Start fresh',restoreFile:'Backup file',restorePass:'Passphrase (if the backup is encrypted)',restore:'Restore from backup',restoring:'Restoring…',restoreDone:'Restore complete. Rebooting to apply it — reconnect in about a minute.',restoreFailed:'Restore failed.',restoreNoFile:'Choose a backup file first.',wifi:'Wi-Fi network',ssid:'Or enter the network name (SSID)',pass:'Wi-Fi password',connect:'Connect via Wi-Fi',wired:"I'm connected via cable (Ethernet)",connecting:'Connecting… the setup Wi-Fi will turn off. Reconnect your phone to your home network, then open http://hifiplayer.local to continue setup where you left off.',noCable:'No cable detected',devname:'Name this player',devnameHelp:'Used as its network name (e.g. "livingroom" → livingroom.local) and its Bluetooth/multiroom name. Letters, numbers and dashes only — leave empty to keep the default.',devnameSaving:'Saving…',mode:'Device mode',modeGui:'With screen (touchscreen)',modeHeadless:'Headless (no screen)',modeOff:'Server only (player off)',modeHelp:'In headless/server-only you manage everything from this web interface.',pointer:'Mouse pointer',pointerHelp:"Show the mouse cursor on screen? Leave it off for a touchscreen — turn it on if you're driving this device with a mouse.",pointerHide:'Touchscreen (hide pointer)',pointerShow:'Mouse (show pointer)',audio:'Audio output',audioContinue:'Continue',lyrion:'Music server (Lyrion)',lyrionLocal:'Use this device as the server',lyrionFollow:'Use a server already on my network',lyrionHost:'Server address',lyrionUse:'Use this server',lyrionInstall:'Install Lyrion',lyrionChecking:'Checking whether Lyrion Music Server is installed…',lyrionMissing:"Lyrion Music Server isn't installed yet.",lyrionInstalling:'Installing Lyrion Music Server…',continueAnyway:'Continue anyway',sources:'Music sources',sourcesIntro:"Manage local, network (SMB) and USB sources below. Optional: you can also do this later from Settings. Lyrion's own setup wizard scans the library once you finish here.",continueBtn:'Continue',timezone:'Time zone',tzSave:'Save and continue',account:'Web admin account',accountHelp:"Used to log into this device's web interface (http://…) from now on.",username:'Username',password:'Password',confirmPassword:'Confirm password',createAccount:'Create account',creating:'Creating…',accountMismatch:'Passwords do not match.',accountTooShort:'Username needs at least 3 characters, password at least 8.',finishGui:'Screen mode set. Setup is complete — press "Complete setup" below: the hotspot will turn off, reconnect your phone to your network. The device will then start its normal on-screen interface.',finishHeadless:'Headless mode set. Press "Complete setup" below: the hotspot will turn off, reconnect your phone to your network and open http://hifiplayer.local',finishOff:'Server-only mode set — this device will not play audio locally. Press "Complete setup" below: the hotspot will turn off, reconnect your phone to your network and open http://hifiplayer.local',finishBtn:'Complete setup',finishDone:'Setup complete — hotspot off. Open http://hifiplayer.local from your network.',finishToLyrion:"Setup complete. Taking you to Lyrion's own setup wizard to finish scanning your library…",error:'Error: '},
 it:{restoreIntro:'Stai configurando un nuovo dispositivo? Ripristina un backup precedente, oppure inizia da zero.',fresh:'Inizia da zero',restoreFile:'File di backup',restorePass:'Passphrase (se il backup è cifrato)',restore:'Ripristina da backup',restoring:'Ripristino in corso…',restoreDone:'Ripristino completato. Riavvio in corso per applicarlo — riconnettiti tra circa un minuto.',restoreFailed:'Ripristino non riuscito.',restoreNoFile:'Scegli prima un file di backup.',wifi:'Rete Wi-Fi',ssid:'Oppure inserisci il nome (SSID)',pass:'Password Wi-Fi',connect:'Connetti via Wi-Fi',wired:'Sono connesso via cavo (Ethernet)',connecting:'Connessione in corso… il Wi-Fi di setup si spegnerà. Riconnetti il telefono alla tua rete di casa, poi apri http://hifiplayer.local per continuare la configurazione da dove l\\'hai lasciata.',noCable:'Nessun cavo rilevato',devname:'Dai un nome a questo player',devnameHelp:'Usato come nome di rete (es. "salotto" → salotto.local) e come nome Bluetooth/multiroom. Solo lettere, numeri e trattini — lascia vuoto per mantenere quello predefinito.',devnameSaving:'Salvataggio…',mode:'Modalità dispositivo',modeGui:'Con schermo (touchscreen)',modeHeadless:'Headless (senza schermo)',modeOff:'Solo server (player spento)',modeHelp:'In headless/solo server gestisci tutto da questa interfaccia web.',pointer:'Puntatore del mouse',pointerHelp:'Mostrare il cursore del mouse a schermo? Lascialo spento per un touchscreen — accendilo se usi il dispositivo con un mouse.',pointerHide:'Touchscreen (nascondi puntatore)',pointerShow:'Mouse (mostra puntatore)',audio:'Uscita audio',audioContinue:'Continua',lyrion:'Server musicale (Lyrion)',lyrionLocal:'Usa questo dispositivo come server',lyrionFollow:'Usa un server già presente sulla rete',lyrionHost:'Indirizzo del server',lyrionUse:'Usa questo server',lyrionInstall:'Installa Lyrion',lyrionChecking:'Verifica se Lyrion Music Server è installato…',lyrionMissing:'Lyrion Music Server non è ancora installato.',lyrionInstalling:'Installazione di Lyrion Music Server…',continueAnyway:'Continua comunque',sources:'Sorgenti musicali',sourcesIntro:'Gestisci sorgenti locali, di rete (SMB) e USB qui sotto. Facoltativo: puoi farlo anche più tardi dalle Impostazioni. La scansione della libreria la fa il setup wizard di Lyrion una volta terminato qui.',continueBtn:'Continua',timezone:'Fuso orario',tzSave:'Salva e continua',account:'Account amministratore web',accountHelp:"Usato per accedere all'interfaccia web di questo dispositivo (http://…) da ora in poi.",username:'Nome utente',password:'Password',confirmPassword:'Conferma password',createAccount:'Crea account',creating:'Creazione…',accountMismatch:'Le password non coincidono.',accountTooShort:'Nome utente di almeno 3 caratteri, password di almeno 8.',finishGui:'Modalità con schermo impostata. Il setup è completo — premi "Completa setup" qui sotto: l\\'hotspot si spegnerà, riconnetti il telefono alla tua rete. Il dispositivo avvierà poi la sua normale interfaccia a schermo.',finishHeadless:'Modalità headless impostata. Premi "Completa setup" qui sotto: l\\'hotspot si spegnerà, riconnetti il telefono alla tua rete e apri http://hifiplayer.local',finishOff:'Modalità solo server impostata — questo dispositivo non riprodurrà audio in locale. Premi "Completa setup" qui sotto: l\\'hotspot si spegnerà, riconnetti il telefono alla tua rete e apri http://hifiplayer.local',finishBtn:'Completa setup',finishDone:'Setup completato — hotspot spento. Apri http://hifiplayer.local dalla tua rete.',finishToLyrion:'Setup completato. Ti porto al setup wizard di Lyrion per finire la scansione della libreria…',error:'Errore: '}
};
var LANG=(new URLSearchParams(location.search).get('lang')||'en');
if(STRINGS[LANG]===undefined)LANG='en';
var S=STRINGS[LANG];
document.getElementById('lang-'+LANG).className='active';
document.getElementById('restore-intro').textContent=S.restoreIntro;
document.getElementById('btn-fresh').textContent=S.fresh;
document.getElementById('lbl-restorefile').textContent=S.restoreFile;
document.getElementById('lbl-restorepass').textContent=S.restorePass;
document.getElementById('btn-restore').textContent=S.restore;
document.getElementById('lbl-wifi').textContent=S.wifi;
document.getElementById('lbl-ssid').textContent=S.ssid;
document.getElementById('lbl-pass').textContent=S.pass;
document.getElementById('btn-connect').textContent=S.connect;
document.getElementById('btn-wired').textContent=S.wired;
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
document.getElementById('lbl-audio').textContent=S.audio;
document.getElementById('btn-audio-skip').textContent=S.audioContinue;
document.getElementById('lbl-lyrion').textContent=S.lyrion;
document.getElementById('btn-lyrion-local').textContent=S.lyrionLocal;
document.getElementById('btn-lyrion-follow').textContent=S.lyrionFollow;
document.getElementById('lbl-lyrionhost').textContent=S.lyrionHost;
document.getElementById('btn-lyrion-follow-go').textContent=S.lyrionUse;
document.getElementById('lbl-lyrion-install').textContent=S.lyrion;
document.getElementById('btn-lyrion-install').textContent=S.lyrionInstall;
document.getElementById('btn-lyrion-install-skip').textContent=S.continueAnyway;
document.getElementById('lbl-sources').textContent=S.sources;
document.getElementById('sources-intro').textContent=S.sourcesIntro;
document.getElementById('btn-sources-continue').textContent=S.continueBtn;
document.getElementById('lbl-timezone').textContent=S.timezone;
document.getElementById('btn-tz-save').textContent=S.tzSave;
document.getElementById('lbl-account').textContent=S.account;
document.getElementById('account-help').textContent=S.accountHelp;
document.getElementById('lbl-acc-user').textContent=S.username;
document.getElementById('lbl-acc-pass').textContent=S.password;
document.getElementById('lbl-acc-pass2').textContent=S.confirmPassword;
document.getElementById('btn-account').textContent=S.createAccount;

var STEPS=['step-restore','step-net','step-name','step-mode','step-pointer','step-audio','step-lyrion','step-lyrion-install','step-sources','step-timezone','step-account','step-finish'];
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
function show(id){STEPS.forEach(function(s){document.getElementById(s).style.display=(s===id?'block':'none')})}
function jpost(p,b){return fetch(p,{method:'POST',headers:Object.assign({'Content-Type':'application/json'},h()),body:JSON.stringify(b||{})}).then(function(r){return r.json()})}
function jget(p){return fetch(p,{headers:h()}).then(function(r){return r.json()})}

function load(){if(netPhaseDone)return;fetch('/api/provision/status').then(function(r){return r.json()}).then(function(s){
  if(!s.pending){return}
  var n=document.getElementById('nets');n.innerHTML='';
  (s.networks||[]).forEach(function(net){var d=document.createElement('div');d.className='net';
    d.innerHTML='<div class="row"><span>'+net.ssid+'</span><span class="muted">'+net.signal+'%</span></div>';
    d.onclick=function(){document.getElementById('ssid').value=net.ssid};n.appendChild(d)});
  if(s.error){document.getElementById('netmsg').textContent=S.error+s.error}
  if(s.stage==='network-ok'){netPhaseDone=true;show('step-name')}
})}

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

function doRestoreUpload(){
  var f=pendingRestoreFile;
  // step-lyrion-install is the card on screen right now (checkLyrionInstall
  // switched to it) — switch back so #restoremsg is actually visible.
  show('step-restore');
  var fd=new FormData();fd.append('file',f);fd.append('passphrase',document.getElementById('restorepass').value);
  document.getElementById('restoremsg').textContent=S.restoring;
  fetch('/api/provision/restore',{method:'POST',headers:h(),body:fd}).then(function(r){return r.json()}).then(function(res){
    if(res.success){
      netPhaseDone=true;
      document.getElementById('restoremsg').textContent=S.restoreDone;
      jpost('/api/provision/finalize',{}).then(function(){jpost('/api/provision/reboot',{})});
    }else{
      document.getElementById('restoremsg').textContent=res.message||S.restoreFailed;
    }
  });
}

function connect(){var b={ssid:document.getElementById('ssid').value,password:document.getElementById('pass').value};
  document.getElementById('netmsg').textContent=hostMsg(S.connecting);
  jpost('/api/provision/wifi_connect',b)}
function useWired(){jpost('/api/provision/use_wired',{}).then(function(res){
  if(res.success){netPhaseDone=true;show('step-name')}else{document.getElementById('netmsg').textContent=res.message||S.noCable}})}

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
    if(cur&&cur!=='unknown'){afterLyrionInstall();return}
    document.getElementById('lyrion-install-msg').textContent=S.lyrionMissing;
    var sel=document.getElementById('lyrionchannel');sel.innerHTML='';
    var channels=(res&&res.channels)||{};
    Object.keys(channels).forEach(function(c){var o=document.createElement('option');o.value=c;
      o.textContent=c+(channels[c]&&channels[c].version?' ('+channels[c].version+')':'');sel.appendChild(o)});
    sel.style.display=Object.keys(channels).length?'block':'none';
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
function pollLyrionInstall(){
  jget('/api/provision/lyrion_status').then(function(st){
    if(typeof st.progress==='number'){document.getElementById('lyrion-install-bar').style.width=st.progress+'%'}
    if(st.message){document.getElementById('lyrion-install-msg').textContent=st.message}
    if(st.state==='done'){afterLyrionInstall()}
    else if(st.state==='error'){
      document.getElementById('lyrion-install-msg').textContent=st.message||S.error;
      document.getElementById('btn-lyrion-install-skip').style.display='block';
    }else{setTimeout(pollLyrionInstall,1500)}
  });
}
function skipLyrionInstall(){afterLyrionInstall()}
function afterLyrionInstall(){
  if(restoringFromBackup){restoringFromBackup=false;doRestoreUpload();return}
  showSourcesStep();
}

function showSourcesStep(){
  var f=document.getElementById('sources-iframe');
  if(!f.src){f.src='/api/provision/sources_app?lang='+encodeURIComponent(LANG)}
  show('step-sources');
}

// Pushes the final source list into Lyrion's prefs and restarts it (the
// embedded sources page's own Apply button is a no-op restart-wise during
// setup — see ?setup=1 handling in sources_server.py) — done exactly once,
// here, right before handing off to Lyrion's own setup wizard at finish().
// Proceeds regardless of success: a wrong/missing source can be fixed later
// from Settings, it shouldn't block finishing the device setup.
function continueFromSources(){
  jpost('/api/provision/apply_sources',{}).then(function(){show('step-timezone');loadTimezone()});
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
    checkAccountStep();
  });
}

// The web-admin account used to only get asked for the first time you
// opened the web interface, which for a screenless/AP-hotspot setup meant
// AFTER finishing Lyrion's own wizard too — easy to forget, and it left the
// device reachable-but-unclaimed in the meantime. Create it here instead,
// unless one already exists (e.g. this wizard is being re-run, or the
// account was already created from the web interface directly).
function checkAccountStep(){
  show('step-account');
  jget('/api/auth/status').then(function(res){
    if(res&&res.has_account){showFinishScreen();return}
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
    if(res.success){showFinishScreen()}
    else{document.getElementById('accountmsg').textContent=res.message||S.error}
  });
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
    // Hand off to Lyrion's own setup wizard — it shows itself automatically
    // on first visit to its web UI, and it's the one that actually knows
    // when the library scan (kicked off above, once, by apply_sources) is
    // done, unlike anything we could show here.
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
 en:{intro:'This device is already configured and lost its connection (neither cable nor Wi-Fi is working). Reconnect it by choosing a Wi-Fi network below — nothing else will be changed.',wifi:'Wi-Fi network',ssid:'Or enter the network name (SSID)',pass:'Wi-Fi password',connect:'Connect',connecting:'Connecting… if you return to your network this page will no longer be reachable here — reopen http://hifiplayer.local',error:'Error: '},
 it:{intro:'Il dispositivo è già configurato e ha perso la connessione (né cavo né Wi-Fi funzionanti). Ricollegalo scegliendo una rete Wi-Fi qui sotto — nessun\\'altra impostazione verrà modificata.',wifi:'Rete Wi-Fi',ssid:'Oppure inserisci il nome (SSID)',pass:'Password Wi-Fi',connect:'Connetti',connecting:'Connessione in corso… se torni sulla tua rete questa pagina non sarà più raggiungibile qui — riapri http://hifiplayer.local',error:'Errore: '}
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
