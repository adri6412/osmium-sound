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
     credentials, NOT the companion pairing-token), cookie session, CSRF,
     Host-header allowlist, TLS.

  3. WEB ADMIN + PROXY: serves the separate Vue admin app (built to
     /opt/hifi-webui/dist) and relays a whitelisted set of api_server.py:8000
     calls behind the session — api_server itself stays loopback-only and
     untrusted-network-free, exactly as today.

Security model (see the plan's "Analisi di sicurezza"):
  * api_server is NEVER exposed directly; the proxy runs here, behind the
    session, and calls 127.0.0.1:8000.
  * TLS self-signed cert + cookie signing key are generated PER-DEVICE on first
    start and never shipped in the image (shared keys => forgeable sessions).
  * Every mutating request needs a double-submit CSRF token; every request's
    Host header must be in the allowlist (anti DNS-rebinding).
  * The proxy whitelist is PARTITIONED: a small pre-auth set is reachable during
    the captive window (wifi/dac/lyrion-install/claim/create-account); the full
    admin set (reboot/shutdown/ssh/ota/dsp/...) needs a live session.
  * factory_reset / password reset re-validate the admin password in the body.

Dev/local flags:
  HIFI_WEBUI_STATE_DIR   override /etc/hifi-player (default) for state files
  HIFI_WEBUI_DIST        override /opt/hifi-webui/dist (the Vue build)
  HIFI_WEBUI_HTTP_ONLY=1 skip TLS, serve plain HTTP on HIFI_WEBUI_PORT (dev)
  HIFI_WEBUI_PORT        HTTP-only dev port (default 8081)
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
import urllib.request

from flask import Flask, jsonify, request, session, redirect, send_from_directory, Response
from werkzeug.security import generate_password_hash, check_password_hash

# ── paths / config ───────────────────────────────────────────────────
STATE_DIR = os.environ.get('HIFI_WEBUI_STATE_DIR', '/etc/hifi-player')
DIST_DIR = os.environ.get('HIFI_WEBUI_DIST', '/opt/hifi-webui/dist')
MARKER = os.path.join(STATE_DIR, 'provisioning-pending')
PROVISION_STATE = os.path.join(STATE_DIR, 'provisioning-state.json')
DB_PATH = os.path.join(STATE_DIR, 'webui.db')
SECRET_KEY_FILE = os.path.join(STATE_DIR, 'webui-secret.key')
TLS_CERT = os.path.join(STATE_DIR, 'webui-cert.pem')
TLS_KEY = os.path.join(STATE_DIR, 'webui-key.pem')
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
HTTP_ONLY = os.environ.get('HIFI_WEBUI_HTTP_ONLY') == '1'

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


# ── local IP discovery (for Host allowlist + cert SAN) ───────────────
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


# ── one-time per-device secrets: cookie key + TLS cert ───────────────
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


def _ensure_tls():
    """Generate a per-device self-signed cert on first start (via openssl, which
    is in the image). Returns (cert, key) paths or None if generation failed."""
    if os.path.isfile(TLS_CERT) and os.path.isfile(TLS_KEY):
        return TLS_CERT, TLS_KEY
    sans = ['DNS:hifiplayer.local', 'DNS:localhost']
    for ip in sorted(_local_ips()):
        sans.append(f'IP:{ip}')
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        subprocess.run(
            ['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
             '-keyout', TLS_KEY, '-out', TLS_CERT, '-days', '3650',
             '-subj', '/CN=hifiplayer.local',
             '-addext', 'subjectAltName=' + ','.join(sans)],
            check=True, capture_output=True, timeout=60)
        os.chmod(TLS_KEY, 0o600)
        os.chmod(TLS_CERT, 0o644)
        return TLS_CERT, TLS_KEY
    except Exception as e:
        print(f'[webui] TLS cert generation failed: {e}')
        return None


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
    """True if a non-AP connection is active with a device (ethernet uplink).
    Used to let the user skip the Wi-Fi step when they're on a cable."""
    if FAKE:
        return False
    rc, out, _ = _nmcli(['-t', '-f', 'NAME,DEVICE,STATE,TYPE', 'connection', 'show', '--active'])
    if rc != 0:
        return False
    for line in out.splitlines():
        parts = line.split(':')
        if len(parts) >= 4 and parts[0] != AP_CON_NAME and parts[2] == 'activated' \
                and parts[1] and parts[3] == '802-3-ethernet':
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
        return False, 'SSID non valido'
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
    return False, (err.strip() or 'Connessione Wi-Fi fallita')


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
                           'error': 'La scheda Wi-Fi non supporta la modalità hotspot'}
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
            err = 'dnsmasq-base mancante — hotspot non disponibile'
        else:
            err = 'Attivazione hotspot fallita'
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
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8')), resp.status
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode('utf-8')), e.code
        except Exception:
            return {'success': False, 'message': 'Servizio non disponibile'}, e.code
    except Exception as e:
        print(f'[webui] proxy {path} unreachable: {e}')
        return {'success': False, 'message': 'Servizio non raggiungibile'}, 502


# Full admin whitelist (session required). (local_path, method) -> api path.
_AUTH_ROUTES = {
    ('/api/system/info', 'GET'): '/system_info',
    ('/api/system/network_status', 'GET'): '/network_status',
    ('/api/system/network_info', 'GET'): '/network_info',
    ('/api/system/wifi_scan', 'GET'): '/wifi_scan',
    ('/api/system/wifi_connect', 'POST'): '/wifi_connect',
    ('/api/system/wired_dhcp', 'POST'): '/wired_dhcp',
    ('/api/system/ssh', 'GET'): '/ssh_status',
    ('/api/system/ssh', 'POST'): '/ssh_set',
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
    ('/api/system/bluetooth', 'GET'): '/bluetooth_status',
    ('/api/system/bluetooth', 'POST'): '/bluetooth_set',
    ('/api/system/bluetooth_discoverable', 'POST'): '/bluetooth_discoverable',
    ('/api/system/bluetooth_forget', 'POST'): '/bluetooth_forget',
    ('/api/system/dsp', 'GET'): '/dsp_status',
    ('/api/system/dsp', 'POST'): '/dsp_set',
    ('/api/system/dsp_presets', 'GET'): '/dsp_presets',
    ('/api/system/dsp_preset_save', 'POST'): '/dsp_preset_save',
    ('/api/system/dsp_preset_load', 'POST'): '/dsp_preset_load',
    ('/api/system/dsp_preset_delete', 'POST'): '/dsp_preset_delete',
    ('/api/system/display_mode', 'GET'): '/display_mode',
    ('/api/system/display_mode', 'POST'): '/display_mode',
    ('/api/system/updates/app/check', 'GET'): '/app_update/check',
    ('/api/system/updates/app/apply', 'POST'): '/app_update/apply',
    ('/api/system/updates/app/status', 'GET'): '/app_update/status',
    ('/api/system/updates/system/check', 'GET'): '/system_update/check',
    ('/api/system/updates/system/apply', 'POST'): '/system_update/apply',
    ('/api/system/updates/system/status', 'GET'): '/system_update/status',
    ('/api/system/updates/os/check', 'GET'): '/os_update/check',
    ('/api/system/updates/os/apply', 'POST'): '/os_update/apply',
    ('/api/system/updates/os/status', 'GET'): '/os_update/status',
    ('/api/system/updates/lyrion/check', 'GET'): '/lyrion_update/check',
    ('/api/system/updates/lyrion/apply', 'POST'): '/lyrion_update/apply',
    ('/api/system/updates/lyrion/status', 'GET'): '/lyrion_update/status',
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
}

# CAPTIVE probe endpoints answered with a redirect to the portal while the AP
# is up (this is what makes the phone auto-pop the setup page).
_CAPTIVE_PROBES = (
    '/generate_204', '/gen_204', '/hotspot-detect.html', '/library/test/success.html',
    '/connecttest.txt', '/ncsi.txt', '/redirect', '/success.txt', '/canonical.html',
)


# ── request guards: Host allowlist + captive redirect + CSRF ─────────
def _allowed_hosts():
    hosts = {'hifiplayer.local', 'localhost', AP_ADDR}
    for ip in _local_ips():
        hosts.add(ip)
    return hosts


@app.before_request
def _guard():
    # 1) Host allowlist (anti DNS-rebinding). Host header minus any :port.
    host = (request.host or '').split(':')[0]
    ap_up = _load_prov_state().get('ap', {}).get('active') if _provisioning() else False
    if host not in _allowed_hosts():
        # During the captive window an unknown Host is a probe/redirect target,
        # not an attack — send it to the portal. Otherwise reject outright.
        if _provisioning() and ap_up:
            return redirect(f'http://{AP_ADDR}/', code=302)
        return Response('Forbidden host', status=403)

    # 2) Captive probes → portal (only while the AP is actually up).
    if _provisioning() and ap_up and request.path in _CAPTIVE_PROBES:
        return redirect(f'http://{AP_ADDR}/', code=302)

    # 3) CSRF: double-submit token on every mutation. The token lives in a
    # non-HttpOnly cookie the SPA echoes back in X-CSRF-Token; a cross-site page
    # can send the cookie but cannot read it to set the header.
    # Exempt:
    #   * localhost — api_server.py makes server-to-server provisioning calls
    #     from 127.0.0.1 (no browser, no cookie), same loopback-trust as
    #     elsewhere.
    #   * /api/provision/* — the first-boot captive flow runs over PLAIN HTTP
    #     (:80 / http://10.42.0.1), where the Secure CSRF cookie is unavailable
    #     by design. These endpoints are pre-auth and gated by physical/RF
    #     proximity + the provisioning marker; CSRF protects the authenticated
    #     HTTPS admin session, which is a separate surface.
    if request.method in ('POST', 'PUT', 'DELETE', 'PATCH') \
            and request.remote_addr not in ('127.0.0.1', '::1') \
            and not request.path.startswith('/api/provision/'):
        cookie = request.cookies.get('csrf')
        header = request.headers.get('X-CSRF-Token')
        if not cookie or not header or not secrets.compare_digest(cookie, header):
            return jsonify({'success': False, 'message': 'CSRF token mancante o non valido'}), 403


@app.after_request
def _set_csrf_cookie(resp):
    # Ensure a CSRF cookie exists so the SPA can read + echo it. Not HttpOnly by
    # design (double-submit needs JS to read it); Secure under TLS.
    if not request.cookies.get('csrf'):
        resp.set_cookie('csrf', secrets.token_urlsafe(24), samesite='Strict',
                        secure=not HTTP_ONLY, httponly=False)
    return resp


def _require_session():
    if not _logged_in():
        return jsonify({'success': False, 'message': 'Autenticazione richiesta'}), 401
    return None


# ── auth endpoints ───────────────────────────────────────────────────
@app.route('/api/auth/status', methods=['GET'])
def auth_status():
    return jsonify({
        'has_account': _get_user() is not None,
        'logged_in': _logged_in(),
        'provisioning': _provisioning(),
    })


@app.route('/api/auth/setup', methods=['POST'])
def auth_setup():
    # Create the admin account — allowed ONLY when none exists yet (first setup).
    if _get_user() is not None:
        return jsonify({'success': False, 'message': 'Account già esistente'}), 409
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if len(username) < 3 or len(password) < 8:
        return jsonify({'success': False, 'message': 'Utente ≥3 e password ≥8 caratteri'}), 400
    _create_user(username, password)
    session.clear()
    session['auth'] = True
    session['sv'] = _session_version()
    session.permanent = True
    return jsonify({'success': True})


@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    ip = request.remote_addr
    if _rate_limited(ip):
        return jsonify({'success': False, 'message': 'Troppi tentativi, riprova più tardi'}), 429
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    row = _get_user()
    if not row or row['username'] != username or not check_password_hash(row['password_hash'], password):
        _record_fail(ip)
        return jsonify({'success': False, 'message': 'Credenziali non valide'}), 401
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
        return jsonify({'success': False, 'message': 'Password attuale errata'}), 403
    if len(username) < 3 or len(new) < 8:
        return jsonify({'success': False, 'message': 'Utente ≥3 e password ≥8 caratteri'}), 400
    _create_user(username, new)
    _bump_session_version()  # log every other session out
    session['sv'] = _session_version()  # keep THIS session valid
    return jsonify({'success': True})


# ── provisioning endpoints (pre-auth: physical/RF proximity is the trust) ──
@app.route('/api/provision/status', methods=['GET'])
def provision_status():
    if not _provisioning():
        return jsonify({'pending': False})
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
    """Skip the Wi-Fi step: the box is on Ethernet. Verified server-side so we
    never mark the network done when there's actually no uplink (which would
    leave the box unreachable after the hotspot drops)."""
    if not _provisioning():
        return jsonify({'success': False, 'message': 'Non in provisioning'}), 409
    if not _wired_connected():
        return jsonify({'success': False, 'message': 'Nessuna connessione via cavo rilevata'}), 409
    with _prov_lock:
        state = _load_prov_state()
        state['stage'] = 'network-ok'
        state['error'] = None
        _save_prov_state(state)
    return jsonify({'success': True})


@app.route('/api/provision/wifi_connect', methods=['POST'])
def provision_wifi_connect():
    if not _provisioning():
        return jsonify({'success': False, 'message': 'Non in provisioning'}), 409
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
        return jsonify({'success': False, 'message': 'Non in provisioning'}), 409
    data = request.get_json(silent=True) or {}
    mode = (data.get('mode') or '').strip()
    source = (data.get('source') or 'web').strip()
    if mode not in ('gui', 'headless'):
        return jsonify({'success': False, 'message': 'Modalità non valida'}), 400
    with _prov_lock:
        state = _load_prov_state()
        if state.get('mode') and state.get('claimed_by') and state.get('claimed_by') != source:
            # Someone already claimed (first wins).
            return jsonify({'success': False, 'message': 'Modalità già scelta',
                            'mode': state.get('mode'), 'claimed_by': state.get('claimed_by')}), 409
        state['mode'] = mode
        state['claimed_by'] = source
        _save_prov_state(state)
    if mode == 'gui':
        # GUI = the on-screen path is chosen, so the setup hotspot is no longer
        # needed: finalize (drop the AP + remove the marker). This is what stops
        # the hotspot the moment the user picks "with a screen". Deferred a beat
        # so THIS response flushes to a phone that's on the hotspot before the AP
        # disappears under it; harmless for the kiosk (not on the AP).
        _set_display_mode('gui', live=False)

        def _deferred_finalize():
            time.sleep(1.5)
            with _prov_lock:
                _do_finalize()
        threading.Thread(target=_deferred_finalize, daemon=True).start()
    else:
        # Headless: switch the running session off-screen (live only from the
        # web/phone, where the user continues) but KEEP the hotspot up until the
        # web setup calls finalize.
        _set_display_mode('headless', live=(source == 'web'))
    return jsonify({'success': True, 'mode': mode})


@app.route('/api/provision/finalize', methods=['POST'])
def provision_finalize():
    if not _provisioning():
        return jsonify({'success': True})  # already done
    with _prov_lock:
        state = _load_prov_state()
        mode = state.get('mode', 'gui')
        _set_display_mode(mode, live=False)
        _do_finalize()
    return jsonify({'success': True})


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
        return jsonify({'success': False, 'message': 'Endpoint non consentito'}), 403
    body = request.get_json(silent=True) if method != 'GET' else None
    data, status = _proxy(API_BASE, api_path, method=method, body=body,
                          timeout=90 if 'apply' in api_path or 'dsp' in api_path else 15)
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
        return jsonify({'success': False, 'message': 'Password non valida'}), 403
    body, status = _proxy(API_BASE, '/factory_reset', method='POST', body={})
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
    # connectivity (redirect to '/').
    return CAPTIVE_HTML


@app.route('/', methods=['GET'])
def root():
    # During the captive window with the AP up, serve the minimal portal.
    if _provisioning() and _load_prov_state().get('ap', {}).get('active'):
        return Response(_captive_html(), mimetype='text/html')
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


CAPTIVE_HTML = """<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Osmium Sound — Setup</title>
<style>
 body{font-family:system-ui,sans-serif;background:#0f1115;color:#eee;margin:0;padding:24px;max-width:520px;margin:auto}
 h1{font-size:20px} .card{background:#1a1e26;border-radius:12px;padding:16px;margin:14px 0}
 label{display:block;font-size:13px;color:#aab;margin:8px 0 4px} input,select,button{width:100%;padding:12px;border-radius:8px;border:1px solid #333;background:#12151b;color:#eee;font-size:15px;box-sizing:border-box}
 button{background:#c8a24a;color:#111;font-weight:600;border:0;margin-top:12px} button.sec{background:#12151b;color:#eee;border:1px solid #333;font-weight:500}
 .muted{color:#889;font-size:13px}
 .net{padding:10px;border-bottom:1px solid #262b35;cursor:pointer} .row{display:flex;justify-content:space-between}
</style></head><body>
<h1>Osmium Sound — Configurazione</h1>
<p class="muted" id="lead">Collega il dispositivo a internet e scegli la modalità.</p>
<div class="card" id="step-net">
 <label>Rete Wi-Fi</label>
 <div id="nets"></div>
 <label>Oppure inserisci il nome (SSID)</label>
 <input id="ssid" placeholder="Nome rete">
 <label>Password Wi-Fi</label>
 <input id="pass" type="password" placeholder="Password">
 <button onclick="connect()">Connetti via Wi-Fi</button>
 <button class="sec" id="btn-wired" onclick="useWired()">Sono connesso via cavo (Ethernet)</button>
 <p class="muted" id="netmsg"></p>
</div>
<div class="card" id="step-mode" style="display:none">
 <label>Modalità dispositivo</label>
 <button onclick="claim('gui')">Con schermo (touchscreen)</button>
 <button class="sec" onclick="claim('headless')">Headless (senza schermo)</button>
 <p class="muted">In headless gestisci tutto da questa interfaccia web dopo il setup.</p>
</div>
<div class="card" id="step-finish" style="display:none">
 <p id="finishmsg" class="muted"></p>
 <button id="btn-finish" onclick="finish()" style="display:none">Completa setup</button>
</div>
<script>
var done=false;
function h(){return {'X-CSRF-Token':(document.cookie.match(/csrf=([^;]+)/)||[])[1]||''}}
function show(id){['step-net','step-mode','step-finish'].forEach(function(s){document.getElementById(s).style.display=(s===id?'block':'none')})}
function jpost(p,b){return fetch(p,{method:'POST',headers:Object.assign({'Content-Type':'application/json'},h()),body:JSON.stringify(b||{})}).then(function(r){return r.json()})}
function load(){if(done)return;fetch('/api/provision/status').then(function(r){return r.json()}).then(function(s){
  if(!s.pending){return}
  var n=document.getElementById('nets');n.innerHTML='';
  (s.networks||[]).forEach(function(net){var d=document.createElement('div');d.className='net';
    d.innerHTML='<div class="row"><span>'+net.ssid+'</span><span class="muted">'+net.signal+'%</span></div>';
    d.onclick=function(){document.getElementById('ssid').value=net.ssid};n.appendChild(d)});
  document.getElementById('btn-wired').style.display=(s.wired?'block':'block');
  if(s.error){document.getElementById('netmsg').textContent='Errore: '+s.error}
  if(s.stage==='network-ok'){show('step-mode')}
})}
function connect(){var b={ssid:document.getElementById('ssid').value,password:document.getElementById('pass').value};
  document.getElementById('netmsg').textContent='Connessione in corso… il Wi-Fi di setup si disconnetterà, riconnettiti alla tua rete e ricarica la pagina.';
  jpost('/api/provision/wifi_connect',b)}
function useWired(){jpost('/api/provision/use_wired',{}).then(function(res){
  if(res.success){show('step-mode')}else{document.getElementById('netmsg').textContent=res.message||'Nessun cavo rilevato'}})}
function claim(m){jpost('/api/provision/claim_mode',{mode:m,source:'web'}).then(function(){
  done=true;
  if(m==='gui'){
    show('step-finish');
    document.getElementById('finishmsg').textContent='Modalità con schermo attivata. Continua la configurazione sullo schermo del dispositivo. Puoi chiudere questa pagina.';
  }else{
    show('step-finish');
    document.getElementById('finishmsg').textContent='Modalità headless attivata. Premi "Completa setup" per terminare: l\\'hotspot si spegnerà, riconnetti il telefono alla tua rete e apri https://hifiplayer.local';
    document.getElementById('btn-finish').style.display='block';
  }
})}
function finish(){jpost('/api/provision/finalize',{}).then(function(){
  document.getElementById('finishmsg').textContent='Setup completato. Hotspot spento — apri https://hifiplayer.local dalla tua rete.';
  document.getElementById('btn-finish').style.display='none';
})}
setInterval(load,3000);load();
</script></body></html>"""

FALLBACK_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>Osmium Sound</title><style>body{font-family:system-ui;background:#0f1115;color:#eee;padding:40px;text-align:center}</style>
</head><body><h1>Osmium Sound — Web Admin</h1>
<p>L'interfaccia di gestione non è ancora stata installata su questo dispositivo.</p>
<p>Le API di autenticazione e provisioning sono attive.</p></body></html>"""


# ── startup ──────────────────────────────────────────────────────────
def _bootstrap():
    app.secret_key = _ensure_secret_key()
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Strict',
        SESSION_COOKIE_SECURE=not HTTP_ONLY,
        PERMANENT_SESSION_LIFETIME=7 * 24 * 3600,
    )
    _init_db()


def _start_provisioning_loop():
    # Background thread: keeps the setup hotspot reconciled during provisioning.
    threading.Thread(target=_provisioning_loop, daemon=True).start()


def main():
    _bootstrap()
    _start_provisioning_loop()
    from werkzeug.serving import make_server

    if HTTP_ONLY:
        port = int(os.environ.get('HIFI_WEBUI_PORT', '8081'))
        print(f'[webui] HTTP-only dev mode on :{port}')
        make_server('0.0.0.0', port, app, threaded=True).serve_forever()
        return

    tls = _ensure_tls()
    if not tls:
        print('[webui] no TLS — falling back to plain HTTP on :80')
        make_server('0.0.0.0', 80, app, threaded=True).serve_forever()
        return

    # :80 in a background thread (captive probes + redirect to :443), :443 main.
    def _http80():
        make_server('0.0.0.0', 80, _redirect_app, threaded=True).serve_forever()
    threading.Thread(target=_http80, daemon=True).start()

    import ssl
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(tls[0], tls[1])
    print('[webui] serving HTTPS on :443 (+ :80 redirect/captive)')
    make_server('0.0.0.0', 443, app, threaded=True, ssl_context=ctx).serve_forever()


def _redirect_app(environ, start_response):
    """Tiny WSGI app for :80. Delegates to the Flask app for the provisioning
    API (so api_server.py's loopback proxy + the phone reach it on plain HTTP
    regardless of AP state) and for captive traffic while the AP is up;
    everything else 301s to HTTPS so admin traffic is always encrypted."""
    path = environ.get('PATH_INFO', '/')
    ap_up = _provisioning() and _load_prov_state().get('ap', {}).get('active')
    if path.startswith('/api/provision/') or ap_up:
        return app(environ, start_response)
    host = environ.get('HTTP_HOST', 'hifiplayer.local').split(':')[0]
    start_response('301 Moved Permanently', [('Location', f'https://{host}{path}')])
    return [b'']


if __name__ == '__main__':
    main()
