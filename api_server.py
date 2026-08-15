from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import subprocess
import os
import shutil
import signal
import sys
import socket
import platform
import re
import json
import logging
import urllib.request
import urllib.parse
import urllib.error
import time
import threading
import queue
import zipfile
import io
import glob
from hifi_logging import get_logger
from hifi_i18n import t as _t

app = Flask(__name__)
# This API is bound to 127.0.0.1 only (see the bottom of this file) and has no
# request-level authentication of its own — it relies entirely on that bind to
# keep it unreachable from the LAN. An unrestricted CORS(app) undermines that:
# it removes the browser's CORS preflight/response-blocking, so ANY web content
# the Electron kiosk's Chromium ever renders (now or in a future feature) could
# fetch() straight to reboot/shutdown/ssh_set/configure_network etc. Restrict
# to the origins the kiosk itself actually uses: the Vite dev server, and
# 'null' (the Origin Chromium sends for the packaged app's file:// renderer).
CORS(app, origins=["http://localhost:5173", "null"])

# Log full diagnostics server-side; never leak exception text / stack traces to
# HTTP clients (this API runs as root). Use `log.exception(...)` in handlers and
# return a generic message to the caller instead. get_logger() also persists this
# to a size-rotated file under /var/log/hifi/ (journald alone doesn't survive a
# reboot on this image) — see the support-bundle endpoint further down, which
# reads it back for remote diagnostics.
log = get_logger('api')

# Security headers middleware
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

def _lang():
    """Caller's UI language, sent as a header by both frontends (admin-webui's
    api.js, the kiosk's src/utils/api.js) on every request so responses built
    here — see hifi_i18n.py — come back in whichever language the owner
    picked, instead of always Italian.

    Some of the functions that call this are also invoked outside a Flask
    request (the update sequencer, unit tests calling handlers directly) —
    there's no caller language to read there, so fall back to the default
    rather than blow up with a "working outside of request context" error."""
    try:
        v = request.headers.get('X-UI-Lang')
    except RuntimeError:
        return 'en'
    return v if v in ('en', 'it') else 'en'

# ──────────────────────────────────────────────────────────────────
#  OTA update of the Electron UI (whole /opt/hifi-media-player dir).
#  The actual download/swap/restart is done as root by the helper
#  script; here we only check GitHub Releases and kick it off.
# ──────────────────────────────────────────────────────────────────
OTA_REPO = os.environ.get('HIFI_OTA_REPO', 'adri6412/hifi-media-player')
# Static release manifest published to a CDN (NOT subject to the
# api.github.com 60-req/hour rate limit). The release workflow writes
# `ota/latest-<channel>.json` mirroring the GitHub release object to the
# `gh-pages` branch. The device reads this first and only falls back to the
# REST API if it's unreachable, so normal update checks never touch the
# rate-limited API.
#
# Cloudflare Pages, watching that same `gh-pages` branch, NOT GitHub Pages:
# the custom domain (osmiumsound.qd.je) got stuck with GitHub Pages' ACME
# cert provisioning permanently wedged ("bad_authz", would not clear even
# after repeated re-adds) and the DNS host for that subdomain doesn't
# support the records needed to fix it any other way. Safe to change the
# default here with no fleet migration dance: every existing device already
# falls back to the GitHub REST API whenever this URL is unreachable (which
# it has been) -- they'll pick up whatever release carries this change via
# that fallback, then use the fast path again from then on.
OTA_MANIFEST_BASE = os.environ.get('HIFI_OTA_MANIFEST_BASE',
                                   'https://osmium-sound.pages.dev/ota')
# OTA release channel: 'prod' tracks GitHub's /releases/latest (stable releases
# only); 'dev' tracks the newest release including prereleases (vX.Y.Z-dev.N).
# 'alpha' tracks the newest release of ANY kind, including private test tags cut
# from the 'alpha' branch (vX.Y.Z-dev.N-alphaM) — those are excluded from what
# 'dev' sees, so they never reach a device that isn't specifically testing them.
# Persisted so the backend's GitHub check and the apply step stay consistent.
OTA_CHANNEL_FILE = '/etc/hifi-player/ota-channel'
OTA_CHANNELS = ('prod', 'dev', 'alpha')
# 'alpha' only appears as a selectable channel when this marker file has been
# placed by hand (root, out-of-band — see hifi-ota-alpha-toggle.sh). It is NOT
# a security boundary (the repo/releases are public) — it just keeps the option
# out of the UI/API for every device except the owner's own, on purpose.
OTA_ALPHA_MARKER_FILE = '/etc/hifi-player/ota-alpha-unlocked'
OTA_APPDIR = '/opt/hifi-media-player'
OTA_VERSION_FILE = os.path.join(OTA_APPDIR, 'UI_VERSION')
OTA_SCRIPT = '/usr/local/sbin/hifi-ota-update.sh'
OTA_STATUS_FILE = '/run/hifi-ota-status.json'
# The UI release carries several tarballs; pick ours by name prefix.
OTA_UI_PREFIX = 'hifi-ui-'

# ──────────────────────────────────────────────────────────────────
#  OTA update of the custom system components (Python API/daemons,
#  helper scripts and systemd units) shipped in the same GitHub
#  Release as a `hifi-system-<ver>.tar.gz` bundle. Installed as root
#  by a helper script which restarts the affected services.
# ──────────────────────────────────────────────────────────────────
SYS_VERSION_FILE = '/etc/hifi-player/SYSTEM_VERSION'
SYS_SCRIPT = '/usr/local/sbin/hifi-system-update.sh'
SYS_STATUS_FILE = '/run/hifi-system-status.json'
SYS_PREFIX = 'hifi-system-'

# ──────────────────────────────────────────────────────────────────
#  OTA update of the operating system itself, shipped as a *signed*
#  `hifi-os-<ver>.tar.gz` bundle carrying its own apply.sh. Because
#  apply.sh runs as root, the helper script refuses to apply it unless
#  a detached Ed25519 signature (asset `.tar.gz.sha256.sig`) verifies
#  against the public key baked into the image at ota-pubkey.pem.
# ──────────────────────────────────────────────────────────────────
OS_VERSION_FILE = '/etc/hifi-player/OS_VERSION'
OS_SCRIPT = '/usr/local/sbin/hifi-os-update.sh'
OS_STATUS_FILE = '/run/hifi-os-status.json'
OS_PREFIX = 'hifi-os-'

# ──────────────────────────────────────────────────────────────────
#  Installer (src/pages/InstallWizard.jsx): backend for the "Install
#  Osmium Sound" boot entry. Same systemd-run + /run status-file shape
#  as the OS/system/UI updates above. See hifi-disk-install.sh and
#  distro/README.md for the full flow — this replaces Debian Installer.
# ──────────────────────────────────────────────────────────────────
INSTALL_SCRIPT = '/usr/local/sbin/hifi-disk-install.sh'
INSTALL_STATUS_FILE = '/run/hifi-install-status.json'

# ──────────────────────────────────────────────────────────────────
#  Multi-component update sequencer.
#
#  Applying "everything" used to be sequenced by the client that started
#  it: apply one component, poll its /run status file, apply the next.
#  Anything that killed the client killed the rest of the sequence, and
#  the three most common events in an update are exactly that — the
#  system bundle restarts hifi-api and hifi-webui, the UI bundle
#  restarts lightdm, and an OS payload may reboot the box. The result
#  was a run that stopped half-way with some components still stale.
#
#  So the plan is now persisted here and executed to the end by
#  hifi-update-runner.sh under its own transient systemd unit. This
#  module only builds the plan, starts the runner, and reports progress
#  by merging the persisted plan with the running step's /run status
#  file. See hifi-update-runner.sh for the file format.
#
#  The per-component endpoints below stay: they are still the right
#  thing for updating a single component, and older clients use them.
# ──────────────────────────────────────────────────────────────────
UPDATE_PLAN_FILE = '/var/lib/hifi-player/update-plan'
UPDATE_RUNNER_SCRIPT = '/usr/local/sbin/hifi-update-runner.sh'
UPDATE_RUNNER_UNIT = 'hifi-update-runner'
# Canonical order. system first (it delivers the API, daemons, helper
# scripts and units everything else relies on), os second (it may reboot,
# and hifi-update-resume.service picks the plan back up), ui last (it
# restarts lightdm, tearing down the kiosk).
UPDATE_PLAN_ORDER = ('system', 'os', 'ui')
# How long a finished plan stays readable so clients can show the outcome
# — including a kiosk that was itself restarted by the UI step. After
# this it is cleared automatically, so a plan nobody dismissed cannot
# keep re-opening the "update complete" overlay forever.
UPDATE_PLAN_TTL = 900
# The plan file is whitespace-separated and parsed by /bin/sh, so every
# field must be whitespace-free. Versions also land in a file name.
_SAFE_VERSION_RE = re.compile(r'^[0-9A-Za-z._-]+$')
_SAFE_SHA_RE = re.compile(r'^[0-9a-fA-F]{64}$')

# ──────────────────────────────────────────────────────────────────
#  Install/update of Lyrion Music Server (.deb from the community
#  downloads server). The page publishes three streams and we let the
#  owner pick: the release, the bugfix nightly for that release, and
#  the development branch. Managed from Settings → Lyrion Music Server
#  (NOT from the appliance's own update page — this is third-party
#  software with its own release cadence).
#
#  downloads.lms-community.org/ now 301s here; the .deb files still
#  live on the old host, which is what the parser matches.
# ──────────────────────────────────────────────────────────────────
LYRION_DOWNLOADS_PAGE = os.environ.get('HIFI_LYRION_PAGE', 'https://lyrion.org/downloads')
LYRION_PKG = 'lyrionmusicserver'
LYRION_SCRIPT = '/usr/local/sbin/hifi-lyrion-update.sh'
LYRION_STATUS_FILE = '/run/hifi-lyrion-status.json'
LYRION_CHANNEL_FILE = '/etc/hifi-player/lyrion-channel'
# Separate from LYRION_CHANNEL_FILE on purpose: the Settings UI persists the
# *picked* channel the moment the owner taps it (so the choice survives a page
# reload before they hit Install), well before apply_lyrion_update() runs. If
# "switching" were detected by diffing against that same file, it would always
# read as "no change" by the time apply runs and a same-version channel swap
# (e.g. nightly -> release when release is not newer than what's installed)
# would be refused as "already up to date" instead of reinstalling. This file
# is only written once a build actually starts installing, so it always
# reflects what's actually running (or about to run).
LYRION_INSTALLED_CHANNEL_FILE = '/etc/hifi-player/lyrion-installed-channel'
LYRION_CHANNELS = ('release', 'nightly', 'dev')
LYRION_DEFAULT_CHANNEL = 'release'

# Mitigation for a kernel panic seen in the DesignWare DMA driver
# (dw_dmac_core: dw_shutdown -> do_dw_dma_disable) during device_shutdown()
# when reboot()/shutdown() runs while a DMA channel is actively streaming
# audio — reliably reproduced with the DSP engine on (continuous stream
# through that path), never with it off. This isn't a fix for the kernel bug
# itself (that needs an upstream/kernel fix), just a best-effort way to avoid
# the race: stop the audio path and give the hardware a moment to go idle
# before actually asking the kernel to restart/power off. DSP_UNIT is defined
# further down in this file; that's fine, it's resolved at call time.
def _quiesce_audio_before_power_action():
    try:
        ac = subprocess.run(['systemctl', 'is-active', DSP_UNIT],
                            capture_output=True, text=True, timeout=10)
        if ac.stdout.strip() != 'active':
            return
        subprocess.run(['sudo', 'systemctl', 'stop', DSP_UNIT],
                       capture_output=True, text=True, timeout=15)
        subprocess.run(['sudo', 'systemctl', 'stop', 'squeezelite'],
                       capture_output=True, text=True, timeout=15)
        time.sleep(2)
    except Exception:
        log.exception('_quiesce_audio_before_power_action failed')

# Funzione per riavviare il dispositivo
def reboot_device():
    try:
        _quiesce_audio_before_power_action()
        subprocess.Popen("sudo reboot", shell=True)
        return "Device rebooting"
    except Exception:
        log.exception("reboot_device failed")
        return "Failed to reboot device"

# Funzione per spegnere il dispositivo
def shutdown_device():
    try:
        _quiesce_audio_before_power_action()
        subprocess.Popen("sudo shutdown now", shell=True)
        return "Device shutting down"
    except Exception:
        log.exception("shutdown_device failed")
        return "Failed to shutdown device"

# Funzione per chiudere tutti i processi di Chromium e rilanciare /app/app_launcher.py
def close_all_apps_and_restart():
    try:
        os.system("pkill chromium")
        current_pid = os.getpid()
        #for proc in subprocess.check_output(["ps", "aux"]).decode("utf-8").split("\n"):
         #   if "/app/app_launcher.py" in proc and "python3" in proc:
         #       pid = int(proc.split()[1])
         #       if pid != current_pid:
         #           os.kill(pid, signal.SIGKILL)

        app_launcher_script = "/app/new/main.py"
        subprocess.Popen(f"python3 {app_launcher_script}", shell=True)
        return "All Chromium processes and app_launcher.py closed and restarted"
    except Exception:
        log.exception("close_all_apps_and_restart failed")
        return "Failed to close all apps and restart"

# Funzione per ottenere le informazioni di sistema
def get_system_info():
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        
        # Ottieni tutte le interfacce di rete
        import psutil
        network_interfaces = []
        
        for interface_name, interface_addresses in psutil.net_if_addrs().items():
            if interface_name == 'lo':  # Skip loopback
                continue
                
            for address in interface_addresses:
                if address.family == socket.AF_INET:  # IPv4
                    interface_type = 'unknown'
                    if interface_name.startswith('eth') or interface_name.startswith('en'):
                        interface_type = 'wired'
                    elif interface_name.startswith('wlan') or interface_name.startswith('wl'):
                        interface_type = 'wireless'
                    elif interface_name.startswith('usb'):
                        interface_type = 'usb'
                    
                    network_interfaces.append({
                        'name': interface_name,
                        'address': address.address,
                        'netmask': address.netmask,
                        'type': interface_type,
                        'active': True
                    })
        
        return {
            'hostname': hostname,
            'platform': platform.platform(),
            'arch': platform.machine(),
            'version': _installed_ui_version(),
            'local_ip': local_ip,
            'network_interfaces': network_interfaces
        }
    except Exception:
        log.exception("get_system_info failed")
        return {
            'hostname': 'Unknown',
            'platform': platform.platform(),
            'arch': platform.machine(),
            'version': _installed_ui_version(),
            'local_ip': 'Unknown',
            'network_interfaces': [],
            'error': _t('system.infoFetchFailed', _lang())
        }

def _cpu_temp_c():
    """Highest reading across /sys/class/thermal/thermal_zone* (usually the
    CPU package sensor), in whole °C. None if no thermal zone is exposed."""
    best = None
    try:
        for zone in glob.glob('/sys/class/thermal/thermal_zone*/temp'):
            try:
                with open(zone) as f:
                    millideg = int(f.read().strip())
            except Exception:
                continue
            c = millideg / 1000.0
            if best is None or c > best:
                best = c
    except Exception:
        pass
    return round(best, 1) if best is not None else None

def _gpu_busy_pct():
    """Intel iGPU busy % via intel_gpu_top, if installed (not shipped on the
    image by default -- see intel-gpu-tools). `-J` streams a JSON array that
    only gets its closing `]` once the process exits, and it never exits on
    its own -- a plain `subprocess.run(..., timeout=N)` would always hit the
    timeout and lose the output. Let it sample for one interval, then ask it
    to exit cleanly (SIGINT, same as Ctrl-C) so it flushes valid JSON."""
    if not shutil.which('intel_gpu_top'):
        return None
    proc = None
    try:
        proc = subprocess.Popen(
            ['intel_gpu_top', '-J', '-s', '500', '-o', '-'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        time.sleep(1.0)
        proc.send_signal(signal.SIGINT)
        try:
            out, _ = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
        text = out.strip()
        if not text.startswith('['):
            text = '[' + text.lstrip(',')
        if not text.rstrip().endswith(']'):
            text = text.rstrip().rstrip(',') + ']'
        samples = json.loads(text)
        if not samples:
            return None
        engines = samples[-1].get('engines') or {}
        render = engines.get('Render/3D') or engines.get('Render/3D/0') or {}
        busy = render.get('busy')
        return round(float(busy), 1) if busy is not None else None
    except Exception:
        return None
    finally:
        if proc and proc.poll() is None:
            proc.kill()

def get_system_stats():
    """CPU/RAM/disk/temperature/GPU snapshot for the admin dashboard. All
    fields are best-effort and independently None-able -- one missing sensor
    (e.g. no GPU tool installed) must never take the whole tile down."""
    try:
        import psutil
        # psutil.cpu_percent(percpu=False) is already the system-wide average
        # across all cores (not a single core), matching `top`'s %Cpu(s) line.
        # A 0.2s sample window was too short and jittery on a bursty system
        # (Electron/vu_meter/Lyrion background load), making single reads
        # swing widely and look like they disagreed with a manual `top`
        # check -- 1s brings it in line with typical manual observation and
        # the dashboard already polls this endpoint only every 5s.
        cpu_pct = psutil.cpu_percent(interval=1.0)
        vm = psutil.virtual_memory()
        du = shutil.disk_usage('/')
        return {
            'cpu_percent': cpu_pct,
            'ram_percent': vm.percent,
            'ram_used_mb': round(vm.used / 1024 / 1024),
            'ram_total_mb': round(vm.total / 1024 / 1024),
            'disk_percent': round(du.used / du.total * 100, 1) if du.total else None,
            'disk_used_gb': round(du.used / 1024 / 1024 / 1024, 1),
            'disk_total_gb': round(du.total / 1024 / 1024 / 1024, 1),
            'temp_c': _cpu_temp_c(),
            'gpu_percent': _gpu_busy_pct(),
        }
    except Exception:
        log.exception("get_system_stats failed")
        return {'cpu_percent': None, 'ram_percent': None, 'ram_used_mb': None,
                'ram_total_mb': None, 'disk_percent': None, 'disk_used_gb': None,
                'disk_total_gb': None, 'temp_c': None, 'gpu_percent': None}

_IFACE_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')

def _valid_iface_name(name):
    """True only for a plausible network interface name passed as a single argv
    token to a root-privileged dhclient/ip call (no shell involved, so no
    metacharacter injection risk) — but a value starting with '-' would still
    be parsed as a FLAG by dhclient/ip instead of an interface name (e.g.
    '-x'/'-nw'/'-sf <script>'), so the leading character must be alphanumeric,
    not just drawn from the same allowed character set as the rest."""
    return bool(isinstance(name, str) and name and _IFACE_RE.match(name))

def _valid_ipv4(addr):
    """True only for a well-formed dotted-quad IPv4 address (no shell metachars)."""
    if not isinstance(addr, str):
        return False
    parts = addr.split('.')
    if len(parts) != 4:
        return False
    return all(p.isdigit() and 0 <= int(p) <= 255 and (p == '0' or not p.startswith('0'))
               for p in parts)

# Funzione per configurare la rete
def configure_network(config):
    try:
        interface_name = config.get('interface', 'eth0')
        mode = config.get('mode', 'dhcp')
        
        if mode == 'dhcp':
            if not _valid_iface_name(interface_name):
                return f"Invalid interface: {interface_name}"
            # Configura DHCP
            result = subprocess.run(['sudo', 'dhclient', interface_name],
                                  capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return f"Interface {interface_name} configured for DHCP"
            else:
                return f"Failed to configure DHCP: {result.stderr}"
                
        elif mode == 'static':
            # Configura IP statico
            ip = config.get('ip', '192.168.1.100')
            gateway = config.get('gateway', '192.168.1.1')
            dns = config.get('dns', '8.8.8.8')

            # Validate every value before it reaches a shell/privileged command.
            # `dns` in particular is interpolated into `sh -c` below; without this
            # a value like '8.8.8.8"; reboot #' would be a root command injection.
            if not _valid_ipv4(ip):
                return f"Invalid IP address: {ip}"
            if not _valid_ipv4(gateway):
                return f"Invalid gateway: {gateway}"
            if not _valid_ipv4(dns):
                return f"Invalid DNS address: {dns}"
            if not _valid_iface_name(interface_name):
                return f"Invalid interface: {interface_name}"

            # Rimuovi l'IP esistente
            subprocess.run(['sudo', 'ip', 'addr', 'flush', 'dev', interface_name], 
                         capture_output=True, text=True)
            
            # Aggiungi il nuovo IP
            result1 = subprocess.run(['sudo', 'ip', 'addr', 'add', f'{ip}/24', 'dev', interface_name], 
                                   capture_output=True, text=True, timeout=10)
            
            # Aggiungi il gateway
            result2 = subprocess.run(['sudo', 'ip', 'route', 'add', 'default', 'via', gateway], 
                                   capture_output=True, text=True, timeout=10)
            
            # Configura DNS
            result3 = subprocess.run(['sudo', 'sh', '-c', f'echo "nameserver {dns}" > /etc/resolv.conf'], 
                                   capture_output=True, text=True, timeout=10)
            
            if result1.returncode == 0 and result2.returncode == 0 and result3.returncode == 0:
                return f"Interface {interface_name} configured with static IP {ip}"
            else:
                return f"Failed to configure static IP: {result1.stderr} {result2.stderr} {result3.stderr}"
        else:
            return "Invalid network mode. Use 'dhcp' or 'static'"
            
    except subprocess.TimeoutExpired:
        return "Network configuration timed out"
    except Exception:
        log.exception("configure_network failed")
        return "Network configuration failed"

# ──────────────────────────────────────────────────────────────────
#  WiFi / network helpers (NetworkManager / nmcli) — used by the
#  first-setup wizard. DHCP is always used (no static IP).
# ──────────────────────────────────────────────────────────────────

def _run(cmd, timeout=20):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

def _terse_split(line):
    """Split an `nmcli -t` line on unescaped ':' and unescape the fields."""
    fields = re.split(r'(?<!\\):', line)
    return [f.replace('\\:', ':').replace('\\\\', '\\') for f in fields]

def _device_ip(device):
    if not device:
        return None
    try:
        r = _run(['nmcli', '-t', '-f', 'IP4.ADDRESS', 'device', 'show', device])
        for line in r.stdout.strip().split('\n'):
            if ':' in line:
                val = line.split(':', 1)[1].strip()
                if val:
                    return val.split('/')[0]
    except Exception:
        pass
    return None

def _active_connection_name(device):
    try:
        r = _run(['nmcli', '-t', '-f', 'NAME,DEVICE', 'connection', 'show', '--active'])
        for line in r.stdout.strip().split('\n'):
            parts = _terse_split(line)
            if len(parts) >= 2 and parts[1] == device:
                return parts[0]
    except Exception:
        pass
    return None

def _active_device():
    """Return (device, type) of the connected uplink to report as "the" network
    status. Ethernet is preferred over Wi-Fi, and the box's own setup/recovery
    hotspot (connection 'hifi-setup', see webui_server.py's AP_CON_NAME) is
    skipped — it's an active 'wifi' device too, and if picked here it would
    report its own AP address (10.42.0.1) instead of the real LAN IP whenever
    a cable is plugged in while the hotspot is still up (e.g. during
    provisioning, which raises it unconditionally)."""
    try:
        r = _run(['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE', 'device', 'status'])
        rows = []
        for line in r.stdout.strip().split('\n'):
            parts = _terse_split(line)
            if len(parts) >= 3 and parts[2] == 'connected' and parts[1] in ('wifi', 'ethernet'):
                rows.append((parts[0], parts[1]))
        for device, dtype in rows:
            if dtype == 'ethernet':
                return device, dtype
        for device, dtype in rows:
            if dtype == 'wifi' and _active_connection_name(device) != 'hifi-setup':
                return device, dtype
    except Exception:
        pass
    return None, None

def _first_device_of_type(dtype):
    try:
        r = _run(['nmcli', '-t', '-f', 'DEVICE,TYPE', 'device', 'status'])
        for line in r.stdout.strip().split('\n'):
            parts = _terse_split(line)
            if len(parts) >= 2 and parts[1] == dtype:
                return parts[0]
    except Exception:
        pass
    return None

def _active_ssid():
    try:
        r = _run(['nmcli', '-t', '-f', 'IN-USE,SSID', 'device', 'wifi', 'list'])
        for line in r.stdout.strip().split('\n'):
            parts = _terse_split(line)
            if len(parts) >= 2 and parts[0] == '*':
                return parts[1]
    except Exception:
        pass
    return None


def _ensure_networkmanager_state(device=None):
    """Recover from NetworkManager states where the interface is unmanaged or networking is globally off."""
    try:
        _run(['nmcli', 'networking', 'on'], timeout=15)
    except Exception:
        pass
    if device:
        try:
            _run(['nmcli', 'device', 'set', device, 'managed', 'yes'], timeout=15)
        except Exception:
            pass


def _startup_network_recovery():
    device = _first_device_of_type('ethernet') or _first_device_of_type('wifi')
    _ensure_networkmanager_state(device)


def _ensure_dhcp_ip(device, timeout=15):
    """Wait briefly for a DHCP lease to appear after enabling the device."""
    _ensure_networkmanager_state(device)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ip = _device_ip(device)
        if ip:
            return ip
        time.sleep(1)
    return _device_ip(device)


def _connection_ids_for_device_type(dtype):
    """NM connection profile names bound to this device type ('wifi' or
    'ethernet'), active or not — includes profiles NM auto-created for past
    manual connects, not just the currently active one."""
    ids = set()
    nm_type = '802-11-wireless' if dtype == 'wifi' else '802-3-ethernet'
    try:
        r = _run(['nmcli', '-t', '-f', 'NAME,TYPE', 'connection', 'show'])
        for line in r.stdout.strip().split('\n'):
            parts = _terse_split(line)
            if len(parts) >= 2 and parts[1] == nm_type:
                ids.add(parts[0])
    except Exception:
        pass
    return ids

def _set_interface_enabled(dtype, enabled):
    """Turn an interface type on (eligible to auto-reconnect, e.g. after a
    reboot) or off (disconnected right now, and kept from silently coming
    back on its own). Wired and Wi-Fi profiles both default to NM's own
    autoconnect=yes with no priority between them, so previously the two
    could — and did — silently fight over which one actually carried
    traffic. Picking one here (wifi_connect/wired_dhcp below) now means the
    other one actually stops competing, not just "also got a route"."""
    for conn in _connection_ids_for_device_type(dtype):
        try:
            _run(['nmcli', 'connection', 'modify', conn,
                  'connection.autoconnect', 'yes' if enabled else 'no'])
        except Exception:
            pass
    if not enabled:
        dev = _first_device_of_type(dtype)
        if dev:
            try:
                _run(['nmcli', 'device', 'disconnect', dev])
            except Exception:
                pass

def get_network_status():
    device, dtype = _active_device()
    ip = _device_ip(device) if device else None
    ssid = _active_ssid() if dtype == 'wifi' else None
    typ = 'wireless' if dtype == 'wifi' else ('wired' if dtype == 'ethernet' else 'none')
    return {'type': typ, 'ip': ip, 'ssid': ssid, 'connected': bool(ip), 'device': device}

def wifi_scan():
    try:
        _run(['nmcli', 'device', 'wifi', 'rescan'], timeout=12)
    except Exception:
        pass
    networks = []
    try:
        # `rescan` only requests a scan and returns immediately; results land
        # a few seconds later. An immediate `list` usually looks fine because
        # NetworkManager already has a scan cache from its own periodic
        # background scans to fall back on -- but that cache doesn't exist
        # yet right after boot, so don't trust the first read blindly.
        for attempt in range(6):
            r = _run(['nmcli', '-t', '-f', 'IN-USE,SSID,SIGNAL,SECURITY', 'device', 'wifi', 'list'])
            networks = []
            for line in r.stdout.strip().split('\n'):
                if not line:
                    continue
                parts = _terse_split(line)
                if len(parts) < 4:
                    continue
                in_use, ssid, signal_, security = parts[0], parts[1], parts[2], parts[3]
                if not ssid:
                    continue
                networks.append({
                    'ssid': ssid,
                    'signal': signal_,
                    'security': security,
                    'in_use': in_use == '*',
                })
            if networks or attempt == 5:
                break
            time.sleep(1)
    except Exception:
        log.exception("wifi_scan failed")
        return {'networks': [], 'error': _t('network.scanFailed', _lang())}
    return {'networks': networks}

def wifi_connect(ssid, password):
    if not ssid:
        return {'success': False, 'code': 'network.ssidMissing', 'message': _t('network.ssidMissing', _lang())}
    # ssid/password are passed as argv to nmcli (no shell), but a value that
    # starts with '-' or carries control characters could still be parsed as a
    # flag or break the command line. Validate with an anchored regexp (no
    # control chars, no leading dash) before building argv.
    safe_arg = re.compile(r'(?!-)[^\x00-\x1f]+')
    for label, value in (('SSID', ssid), ('password', password or '')):
        if value and not safe_arg.fullmatch(value):
            return {'success': False, 'code': 'network.invalidField',
                    'message': _t('network.invalidField', _lang(), label=label)}
    cmd = ['nmcli', 'device', 'wifi', 'connect', ssid]
    if password:
        cmd += ['password', password]
    try:
        r = _run(cmd, timeout=45)
    except subprocess.TimeoutExpired:
        return {'success': False, 'code': 'network.connectTimeout',
                'message': _t('network.connectTimeout', _lang())}
    except Exception:
        log.exception("wifi_connect failed")
        return {'success': False, 'code': 'network.connectFailed',
                'message': _t('network.connectFailed', _lang())}
    if r.returncode == 0:
        device, _ = _active_device() or (None, None)
        msg = _t('network.connected', _lang(), ssid=ssid)
        ip = _ensure_dhcp_ip(device) if device else None
        # Only make Wi-Fi exclusive once it actually has a working IP — never
        # turn Ethernet off on the strength of an nmcli command that merely
        # returned success, which would risk stranding the box with neither
        # interface reachable.
        if ip:
            _set_interface_enabled('wifi', True)
            _set_interface_enabled('ethernet', False)
        return {'success': True, 'message': msg, 'ip': ip}
    return {'success': False, 'code': 'network.connectFailed',
            'message': (r.stderr or r.stdout).strip() or _t('network.connectFailed', _lang())}

def wired_dhcp():
    eth = _first_device_of_type('ethernet')
    if not eth:
        return {'success': False, 'code': 'network.noEthernet', 'message': _t('network.noEthernet', _lang())}
    try:
        r = _run(['nmcli', 'device', 'connect', eth], timeout=45)
    except Exception:
        log.exception("wired_dhcp failed")
        return {'success': False, 'code': 'network.wiredFailed', 'message': _t('network.wiredFailed', _lang())}
    ip = _ensure_dhcp_ip(eth)
    if ip:
        # Symmetric with wifi_connect above: only flip exclusivity once wired
        # actually has a working IP.
        _set_interface_enabled('ethernet', True)
        _set_interface_enabled('wifi', False)
        return {'success': True, 'code': 'network.wiredConnected',
                'message': _t('network.wiredConnected', _lang()), 'ip': ip}
    return {'success': False, 'code': 'network.cableNotConnected',
            'message': (r.stderr or r.stdout).strip() or _t('network.cableNotConnected', _lang()), 'ip': ip}

# ──────────────────────────────────────────────────────────────────
#  Audio output (DAC) selection for squeezelite — used by the wizard.
# ──────────────────────────────────────────────────────────────────

SQUEEZELITE_DEFAULT = '/etc/default/squeezelite'

def list_audio_devices():
    """List ALSA playback devices (cards) usable as squeezelite output.

    Devices are addressed by their stable ALSA card *name* (hw:CARD=<id>,DEV=<n>)
    rather than the card *number* (hw:<n>,<d>): card numbers are assigned at boot
    in probe order, so a USB DAC that enumerates after the onboard card can swap
    numbers across reboots and the saved "-o hw:1,0" would then point at the PC's
    sound card. The CARD= name is stable, so the selection survives reboots.
    """
    devices = [{'id': 'default', 'name': _t('audio.defaultDeviceName', _lang()), 'card': None, 'device': None}]
    try:
        r = _run(['aplay', '-l'])
        for line in r.stdout.split('\n'):
            # e.g. "card 0: D50s [Topping D50s], device 0: USB Audio [USB Audio]"
            m = re.match(r'card (\d+): (\S+) \[([^\]]+)\], device (\d+): [^\[]*\[([^\]]+)\]', line)
            if m:
                card, cid, cname, dev, dname = (
                    int(m.group(1)), m.group(2), m.group(3), int(m.group(4)), m.group(5))
                # Hide the snd-aloop Loopback card: it's the internal bridge to the
                # DSP engine, not a real output the user should pick directly.
                if cid == 'Loopback':
                    continue
                devices.append({
                    'id': f'hw:CARD={cid},DEV={dev}',
                    'name': f'{cname} — {dname}',
                    'card': card,
                    'device': dev,
                })
    except Exception:
        log.exception("list_audio_devices failed")
        return {'devices': devices, 'current': _current_real_dac(),
                'error': _t('audio.listDevicesFailed', _lang())}
    return {'devices': devices, 'current': _current_real_dac()}

def _current_audio_device():
    """Return the -o output device currently configured in /etc/default/squeezelite."""
    try:
        with open(SQUEEZELITE_DEFAULT) as f:
            content = f.read()
        m = re.search(r"ARGS=(['\"])(.*?)\1", content)
        if m:
            o = re.search(r'-o\s+(\S+)', m.group(2))
            if o:
                return o.group(1)
    except Exception:
        pass
    return 'default'

def set_audio_device(device):
    """Rewrite the -o option in /etc/default/squeezelite and restart it."""
    if not device:
        return {'success': False, 'code': 'audio.deviceMissing', 'message': _t('audio.deviceMissing', _lang())}

    # Validate device is one of the valid audio device IDs from list_audio_devices()
    valid_devices = [d['id'] for d in list_audio_devices()['devices']]
    if device not in valid_devices:
        return {'success': False, 'code': 'audio.invalidDevice',
                'message': _t('audio.invalidDevice', _lang(), device=device)}

    # When the DSP engine is ON, the chosen DAC is CamillaDSP's *playback*
    # device — squeezelite stays pointed at the Loopback. Re-apply the DSP
    # path with the new DAC instead of rewriting squeezelite's -o.
    if _read_dsp_state().get('enabled'):
        st = _read_dsp_state()
        try:
            with _dsp_apply_lock:
                _apply_dsp_on(device, st['bands'], st['crossfeed'], st['room_correction'], st['balance'])
        except Exception:
            log.exception("set_audio_device (DSP) failed")
            return {'success': False, 'code': 'audio.dspOutputFailed',
                    'message': _t('audio.dspOutputFailed', _lang())}
        return {'success': True, 'message': _t('audio.dspOutputSet', _lang(), device=device)}

    try:
        with open(SQUEEZELITE_DEFAULT) as f:
            content = f.read()
    except Exception:
        content = "ARGS='-o default -D -v -C 5 -s 127.0.0.1 -n HiFiPlayer'\n"

    m = re.search(r"ARGS=(['\"])(.*?)\1", content)
    if m:
        args = m.group(2)
        if re.search(r'-o\s+\S+', args):
            args = re.sub(r'-o\s+\S+', f'-o {device}', args)
        else:
            args = f'-o {device} ' + args
        # Ensure DSD-over-PCM (bit-perfect DSD) is enabled. Without -D squeezelite
        # downconverts DSD to PCM; -D passes DSD verbatim to a DSD-capable DAC (DoP).
        if not re.search(r'(^|\s)-D(\s|$)', args):
            args = re.sub(r'(-o\s+\S+)', r'\1 -D', args, count=1)
        content = content[:m.start()] + f"ARGS='{args}'" + content[m.end():]
    else:
        content += f"\nARGS='-o {device} -D -v -C 5 -s 127.0.0.1 -n HiFiPlayer'\n"

    try:
        with open(SQUEEZELITE_DEFAULT, 'w') as f:
            f.write(content)
    except Exception:
        log.exception("set_audio_device: write config failed")
        return {'success': False, 'code': 'audio.writeConfigFailed',
                'message': _t('audio.writeConfigFailed', _lang())}

    try:
        r = _restart_squeezelite_if_enabled()
        if r.returncode != 0:
            return {'success': True, 'message': _t('audio.deviceSetRestartWarn', _lang(),
                    device=device, err=(r.stderr or '').strip())}
    except Exception:
        log.exception("set_audio_device: squeezelite restart failed")
        return {'success': True, 'message': _t('audio.deviceSetRestartFailed', _lang(), device=device)}
    return {'success': True, 'message': _t('audio.outputSet', _lang(), device=device)}

# ── Multiroom: which Lyrion server this device's squeezelite follows ──
# Standalone (default) is squeezelite's own local LMS (-s 127.0.0.1). "Follow"
# points -s at another Osmium device's LMS on the LAN, so this device's player
# shows up there and can be grouped via that server's native sync (see
# lyrionApi.syncPlayer/unsyncPlayer) — LMS instances don't discover each other,
# so both devices must point at the same one for multiroom to work between them.
def _current_lms_host():
    _, args = _read_sq_args()
    if args:
        m = re.search(r'-s\s+(\S+)', args)
        if m:
            return m.group(1)
    return '127.0.0.1'

def get_lms_role():
    host = _current_lms_host()
    if host == '127.0.0.1':
        return {'mode': 'local', 'host': None}
    return {'mode': 'follow', 'host': host}

def set_lms_role(mode, host):
    if mode == 'local':
        target = '127.0.0.1'
    elif mode == 'follow':
        if not _valid_ipv4(host):
            return {'success': False, 'code': 'lms.invalidIp',
                    'message': _t('lms.invalidIp', _lang(), host=host)}
        if host == '127.0.0.1':
            return {'success': False, 'code': 'lms.useLocalMode',
                    'message': _t('lms.useLocalMode', _lang())}
        target = host
    else:
        return {'success': False, 'code': 'lms.invalidMode',
                'message': _t('lms.invalidMode', _lang(), mode=mode)}

    _, args = _read_sq_args()
    if args is None:
        return {'success': False, 'code': 'lms.sqConfigMissing',
                'message': _t('lms.sqConfigMissing', _lang())}
    _write_sq_args(_sq_set_s(args, target))

    try:
        r = _restart_squeezelite_if_enabled()
        if r.returncode != 0:
            return {'success': True, 'host': target if mode == 'follow' else None,
                    'message': _t('lms.serverSetRestartWarn', _lang(),
                                  target=target, err=(r.stderr or '').strip())}
    except Exception:
        log.exception("set_lms_role: squeezelite restart failed")
        return {'success': True, 'host': target if mode == 'follow' else None,
                'message': _t('lms.serverSetRestartFailed', _lang(), target=target)}
    msg = (_t('lms.localRestored', _lang()) if mode == 'local'
           else _t('lms.serverSet', _lang(), target=target))
    return {'success': True, 'host': target if mode == 'follow' else None, 'message': msg}

# ── Player name (-n) — every device ships as "OsmiumSound" by default, which
# makes them indistinguishable once two are grouped for multiroom. Letting an
# owner rename this is the fix. No spaces: systemd's `ExecStart=... $ARGS`
# splits on whitespace with no shell-style quoting, so a space would be seen
# by squeezelite as the start of a new argument instead of part of -n's value.
_PLAYER_NAME_RE = re.compile(r'^[A-Za-z0-9_.\-]{1,24}$')

def _valid_player_name(name):
    return bool(isinstance(name, str) and _PLAYER_NAME_RE.match(name))

def _current_player_name():
    _, args = _read_sq_args()
    if args:
        m = re.search(r'-n\s+(\S+)', args)
        if m:
            return m.group(1)
    return 'OsmiumSound'

def get_player_name():
    return {'name': _current_player_name()}

def set_player_name(name):
    if not _valid_player_name(name):
        return {'success': False, 'code': 'player.invalidName',
                'message': _t('player.invalidName', _lang())}
    _, args = _read_sq_args()
    if args is None:
        return {'success': False, 'code': 'lms.sqConfigMissing',
                'message': _t('lms.sqConfigMissing', _lang())}
    if re.search(r'-n\s+\S+', args):
        args = re.sub(r'-n\s+\S+', f'-n {name}', args)
    else:
        args = (args + f' -n {name}').strip()
    _write_sq_args(args)

    try:
        r = _restart_squeezelite_if_enabled()
        if r.returncode != 0:
            return {'success': True, 'name': name,
                    'message': _t('player.nameSetRestartWarn', _lang(),
                                  name=name, err=(r.stderr or '').strip())}
    except Exception:
        log.exception("set_player_name: squeezelite restart failed")
        return {'success': True, 'name': name,
                'message': _t('player.nameSetRestartFailed', _lang(), name=name)}
    if _read_bt_state():
        # Best-effort: keep the Bluetooth alias in sync so a renamed player
        # doesn't leave phones seeing the old "OsmiumSound" in their picker.
        # hifi-bt-watcher.py sets this too on its own startup; this just
        # applies it live without waiting for a watcher restart.
        try:
            subprocess.run(['bluetoothctl', 'system-alias', name], capture_output=True, timeout=10)
        except Exception:
            pass
    return {'success': True, 'name': name, 'message': _t('player.nameSet', _lang(), name=name)}

# ── Device name — Linux hostname + player name, set together ──────────
# Every appliance ships from the ISO with the same hardcoded hostname
# ("hifiplayer", baked into /etc/hostname at build time by
# 0100-system-setup.hook.chroot) and the same default player name
# ("OsmiumSound"), so two units on one LAN collide on both hifiplayer.local
# (avahi falls back to hifiplayer-2.local, silently confusing) and the
# multiroom picker. Letting the owner pick one name in the setup wizard and
# applying it to both fixes both at once. Stricter charset than
# _PLAYER_NAME_RE on purpose — this becomes a DNS/mDNS label, which
# _PLAYER_NAME_RE's dot/underscore aren't safe for.
_HOSTNAME_RE = re.compile(r'^[A-Za-z0-9]([A-Za-z0-9-]{0,30}[A-Za-z0-9])?$')

def _valid_device_name(name):
    return bool(isinstance(name, str) and _HOSTNAME_RE.match(name))

def _set_etc_hosts_hostname(name):
    """Replace (or insert) the 127.0.1.1 line in /etc/hosts to match `name`.
    Best-effort: a failure here only means `sudo` prints a cosmetic "unable
    to resolve host" warning, not worth failing the whole rename over."""
    try:
        try:
            with open('/etc/hosts') as f:
                lines = f.readlines()
        except FileNotFoundError:
            lines = []
        out, seen = [], False
        for line in lines:
            if re.match(r'^\s*127\.0\.1\.1\s', line):
                out.append(f'127.0.1.1\t{name}\n')
                seen = True
            else:
                out.append(line)
        if not seen:
            out.append(f'127.0.1.1\t{name}\n')
        with open('/etc/hosts', 'w') as f:
            f.writelines(out)
    except Exception:
        log.exception("_set_etc_hosts_hostname failed")

def get_device_name():
    return {'name': socket.gethostname()}

def set_device_name(name):
    if not _valid_device_name(name):
        return {'success': False, 'code': 'device.invalidName',
                'message': _t('device.invalidName', _lang())}
    try:
        r = _run(['hostnamectl', 'set-hostname', name], timeout=10)
        if r.returncode != 0:
            return {'success': False, 'code': 'device.hostnameSetFailed',
                    'message': _t('device.hostnameSetFailed', _lang())}
    except Exception:
        log.exception("set_device_name: hostnamectl failed")
        return {'success': False, 'code': 'device.hostnameSetFailed',
                'message': _t('device.hostnameSetFailed', _lang())}
    _set_etc_hosts_hostname(name)
    try:
        # So the new <name>.local is announced immediately, without waiting
        # for a reboot — avahi-daemon doesn't watch /etc/hostname on its own.
        _run(['systemctl', 'restart', 'avahi-daemon'], timeout=15)
    except Exception:
        log.exception("set_device_name: avahi restart failed")
    try:
        # Lyrion Music Server bundles its OWN mDNS/Bonjour responder and reads
        # the hostname once at startup — restarting avahi-daemon above does
        # NOT make it re-announce, so without this it keeps advertising (and
        # answering for) the OLD <name>.local indefinitely, right alongside
        # the new one now served by avahi. Only bounce it if it's already
        # running: never turn on a local Lyrion instance the user has off
        # (e.g. this box follows an external server elsewhere on the LAN).
        if _run(['systemctl', 'is-active', '--quiet', 'lyrionmusicserver'], timeout=10).returncode == 0:
            _run(['systemctl', 'restart', 'lyrionmusicserver'], timeout=30)
    except Exception:
        log.exception("set_device_name: lyrionmusicserver restart failed")
    # Keep the LMS/Bluetooth-facing name in sync too. _HOSTNAME_RE's charset
    # is a subset of _PLAYER_NAME_RE's, so this always validates.
    set_player_name(name)
    return {'success': True, 'name': name, 'message': _t('device.nameSet', _lang(), name=name)}

# ── LAN discovery of other Lyrion/LMS servers ──────────────────────
# Native Slim/Squeezebox discovery protocol (UDP 3483): broadcast a single
# 'e' probe, any Lyrion/LMS instance on the same broadcast domain answers
# with an 'E'-prefixed TLV packet (NAME/JSON tags = server name / web+API
# port). This is the exact zero-config mechanism official Squeezebox
# controllers use to find servers, so no IP has to be typed in by hand.
def discover_lms_servers(timeout=1.5):
    found = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(0.3)
    try:
        sock.sendto(b'e', ('255.255.255.255', 3483))
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, addr = sock.recvfrom(1024)
            except socket.timeout:
                continue
            if not data or data[:1] != b'E':
                continue
            name, port = None, '9000'
            body, i = data[1:], 0
            while i + 5 <= len(body):
                tag = body[i:i + 4]
                ln = body[i + 4]
                val = body[i + 5:i + 5 + ln]
                if tag == b'NAME':
                    name = val.decode('utf-8', 'replace')
                elif tag == b'JSON':
                    port = val.decode('ascii', 'replace') or '9000'
                i += 5 + ln
            found[addr[0]] = {'ip': addr[0], 'name': name or addr[0], 'port': port}
    except Exception:
        log.exception("discover_lms_servers failed")
    finally:
        sock.close()
    return sorted(found.values(), key=lambda s: s['ip'])

# ──────────────────────────────────────────────────────────────────
#  SSH service control — the appliance ships with SSH disabled; this lets
#  the user turn it on/off from Settings. The unit name is resolved from a
#  fixed allow-list (never user input), so there is no injection surface.
# ──────────────────────────────────────────────────────────────────
def _ssh_unit():
    """Return the systemd unit that provides sshd ('ssh.service' on Debian/
    DietPi, 'sshd.service' elsewhere). Falls back to 'ssh.service'."""
    for unit in ('ssh.service', 'sshd.service'):
        try:
            r = subprocess.run(['systemctl', 'list-unit-files', unit],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and unit in (r.stdout or ''):
                return unit
        except Exception:
            pass
    return 'ssh.service'

def _ssh_available():
    unit = _ssh_unit()
    try:
        r = subprocess.run(['systemctl', 'list-unit-files', unit],
                           capture_output=True, text=True, timeout=10)
        return unit in (r.stdout or '')
    except Exception:
        return False

def _install_openssh():
    """Install the openssh-server package (the appliance image may not ship it).
    Returns (available, detail) — detail is stderr from whichever apt-get step
    failed, or '' on success, so the caller can surface something more useful
    than a flat "failed" to the UI."""
    try:
        # Refresh the index first; a long-running appliance may have a stale one.
        r_update = subprocess.run(['sudo', 'apt-get', 'update'],
                      capture_output=True, text=True, timeout=120)
        if r_update.returncode != 0:
            log.error("apt-get update failed (rc=%s): %s", r_update.returncode,
                      (r_update.stderr or '').strip())
        r_install = subprocess.run(['sudo', 'apt-get', 'install', '-y', 'openssh-server'],
                      capture_output=True, text=True, timeout=180)
        if r_install.returncode != 0:
            log.error("apt-get install openssh-server failed (rc=%s): %s",
                      r_install.returncode, (r_install.stderr or '').strip())
            if not _ssh_available():
                return False, (r_install.stderr or '').strip()
    except Exception:
        log.exception("openssh-server install failed")
        return False, ''
    return _ssh_available(), ''

SSH_NO_ROOT_LOGIN_DROPIN = '/etc/ssh/sshd_config.d/99-hifi-no-root-login.conf'
SSH_NO_ROOT_LOGIN_CONTENT = ("# Managed by HiFi Player — do not edit by hand (overwritten on update).\n"
                              "PermitRootLogin no\n")

def _harden_ssh_no_root_login():
    """Make sure root can never log in over the SSH server this endpoint just
    enabled — the kiosk account has a well-known default password, so an
    attacker who guesses/leaks it must land as the unprivileged 'hifi' user,
    never root. Baked into the image and carried by the OS-update channel
    (distro/os-update/apply.d/0017-ssh-no-root-login.sh) too; this call makes
    it take effect immediately instead of waiting for the next OTA/reboot."""
    try:
        os.makedirs(os.path.dirname(SSH_NO_ROOT_LOGIN_DROPIN), exist_ok=True)
        existing = None
        if os.path.isfile(SSH_NO_ROOT_LOGIN_DROPIN):
            with open(SSH_NO_ROOT_LOGIN_DROPIN) as f:
                existing = f.read()
        if existing != SSH_NO_ROOT_LOGIN_CONTENT:
            tmp = SSH_NO_ROOT_LOGIN_DROPIN + '.tmp'
            with open(tmp, 'w') as f:
                f.write(SSH_NO_ROOT_LOGIN_CONTENT)
            os.chmod(tmp, 0o644)
            os.replace(tmp, SSH_NO_ROOT_LOGIN_DROPIN)
    except Exception:
        log.exception("failed to write sshd no-root-login drop-in")

def get_ssh_status():
    unit = _ssh_unit()
    try:
        avail = subprocess.run(['systemctl', 'list-unit-files', unit],
                              capture_output=True, text=True, timeout=10)
        en = subprocess.run(['systemctl', 'is-enabled', unit],
                           capture_output=True, text=True, timeout=10)
        ac = subprocess.run(['systemctl', 'is-active', unit],
                           capture_output=True, text=True, timeout=10)
        return {
            'available': unit in (avail.stdout or ''),
            'enabled': en.stdout.strip() == 'enabled',
            'active': ac.stdout.strip() == 'active',
        }
    except Exception:
        log.exception("get_ssh_status failed")
        return {'available': False, 'enabled': False, 'active': False,
                'code': 'ssh.statusUnavailable', 'error': 'SSH status unavailable.'}

def set_ssh(enable):
    """Enable+start or disable+stop the SSH server (persists across reboots).
    When enabling on an image that doesn't ship openssh-server, install it
    first so the toggle works out of the box."""
    if enable and not _ssh_available():
        installed, detail = _install_openssh()
        if not installed:
            msg = _t('ssh.installFailed', _lang())
            return {'success': False, 'available': False, 'enabled': False,
                    'active': False, 'code': 'ssh.installFailed',
                    'message': f'{msg}: {detail}' if detail else msg}
    if enable:
        # Written before the unit (re)starts, so root-login is blocked from
        # sshd's very first start.
        _harden_ssh_no_root_login()
        # Guarantee host keys exist before the first start. openssh-server
        # ships in the base image (disabled, not absent — see
        # 0400-enable-services.hook.chroot), but that install happens inside
        # the live-build chroot under policy-rc.d, which can leave host-key
        # generation incomplete depending on exactly when/how the postinst
        # ran at build time. `ssh-keygen -A` only fills in whatever's
        # missing and is a no-op if every key type is already present — the
        # single most common cause of systemd reporting "control process
        # exited with error code" for sshd is starting with no host keys at
        # all, so this is cheap insurance regardless of the exact reason.
        try:
            subprocess.run(['sudo', 'ssh-keygen', '-A'], capture_output=True, text=True, timeout=15)
        except Exception:
            log.exception("ssh-keygen -A failed")
    unit = _ssh_unit()
    action = 'enable' if enable else 'disable'
    try:
        r = subprocess.run(['sudo', 'systemctl', action, '--now', unit],
                          capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            detail = (r.stderr or '').strip()
            log.error("set_ssh %s failed: %s", action, detail)
            status = get_ssh_status()
            status['success'] = False
            status['code'] = 'ssh.toggleFailed'
            msg = _t('ssh.toggleFailed', _lang())
            status['message'] = f'{msg}: {detail}' if detail else msg
            return status
    except Exception:
        log.exception("set_ssh failed")
        return {'success': False, 'code': 'ssh.toggleFailed',
                'message': _t('ssh.toggleFailed', _lang())}
    if enable:
        # If sshd was already active (e.g. re-toggling on without an
        # intervening stop), `enable --now` above doesn't restart it — reload
        # so the drop-in written above takes effect on this run too, not just
        # on the next fresh start.
        try:
            subprocess.run(['sudo', 'systemctl', 'reload', unit],
                          capture_output=True, text=True, timeout=15)
        except Exception:
            log.exception("sshd reload after hardening failed")
    status = get_ssh_status()
    status['success'] = True
    # The UI translates by `code`; `message` is a language-appropriate fallback
    # for older clients (it used to be hardcoded Italian regardless of locale).
    status['code'] = 'ssh.enabled' if enable else 'ssh.disabled'
    status['message'] = _t(status['code'], _lang())
    # Tell the caller whether a login even exists, so the panel can prompt for
    # one instead of repeating the old "change the default hifi password" advice.
    status['account'] = get_shell_account()
    return status

# ──────────────────────────────────────────────────────────────────
#  Shell (SSH/console) account.
#
#  The appliance used to ship a single kiosk user with the documented
#  default password 'hifi' and no sudo, which made SSH both insecure and
#  useless (you had to `su root`, whose password was also documented).
#  Instead, the admin account the owner creates in the provisioning
#  wizard is mirrored into a real Linux user with full sudo — a
#  per-device credential, nothing known shipped in the image.
#
#  The plaintext password only exists at account creation and password
#  change, so webui_server.py calls in at exactly those two moments;
#  nothing extra is persisted here beyond the account *name*, which the
#  factory reset needs in order to remove it again.
# ──────────────────────────────────────────────────────────────────
SHELL_ACCOUNT_FILE = '/etc/hifi-player/shell-account'
SHELL_ACCOUNT_RE = re.compile(r'^[a-z_][a-z0-9_-]{2,31}$')
# Never let the web admin take over an account that already means something.
SHELL_ACCOUNT_RESERVED = {
    'root', 'hifi', 'support', 'hifimusic', 'daemon', 'bin', 'sys', 'sync',
    'games', 'man', 'lp', 'mail', 'news', 'uucp', 'proxy', 'www-data',
    'backup', 'list', 'irc', 'nobody', 'systemd-network', 'messagebus',
    'sshd', 'lightdm', 'squeezelite', 'admin',
}
KIOSK_USER = 'hifi'

def _user_exists(name):
    try:
        subprocess.run(['id', '-u', name], capture_output=True, timeout=10, check=True)
        return True
    except Exception:
        return False

def _user_in_group(name, group):
    try:
        r = subprocess.run(['id', '-nG', name], capture_output=True, text=True, timeout=10)
        return group in (r.stdout or '').split()
    except Exception:
        return False

def _kiosk_password_disabled():
    """True when the kiosk user has no usable password (`passwd -S` reports L
    for locked or NP for none). Best-effort: unknown ⇒ report False."""
    try:
        r = subprocess.run(['passwd', '-S', KIOSK_USER],
                           capture_output=True, text=True, timeout=10)
        parts = (r.stdout or '').split()
        return len(parts) > 1 and parts[1] in ('L', 'NP')
    except Exception:
        return False

def get_shell_account():
    """Report the shell login, if any. Falls back to scanning for a non-system
    sudo user so a device stays correct even if the marker file is lost (e.g.
    a system-channel rollback)."""
    name = ''
    try:
        with open(SHELL_ACCOUNT_FILE) as f:
            name = f.read().strip()
    except Exception:
        pass
    if name and _user_exists(name):
        return {'exists': True, 'username': name,
                'kiosk_password_disabled': _kiosk_password_disabled()}
    # No marker (or it points at a deleted user) — look for one ourselves.
    try:
        r = subprocess.run(['getent', 'group', 'sudo'],
                           capture_output=True, text=True, timeout=10)
        members = (r.stdout or '').strip().split(':')[-1]
        for m in [x.strip() for x in members.split(',') if x.strip()]:
            if m not in SHELL_ACCOUNT_RESERVED:
                return {'exists': True, 'username': m,
                        'kiosk_password_disabled': _kiosk_password_disabled()}
    except Exception:
        log.exception("shell account lookup failed")
    return {'exists': False, 'username': '',
            'kiosk_password_disabled': _kiosk_password_disabled()}

def _disable_kiosk_password():
    """Retire the documented 'hifi'/'hifi' default once a real login exists.
    `usermod -p '*'` leaves no hash at all, unlike `passwd -l`, which only
    prefixes '!' to the (trivially guessed) original. The kiosk is unaffected:
    LightDM autologin authenticates via the autologin/nopasswdlogin groups, and
    every privileged call goes through the NOPASSWD rules in sudoers.d/hifi."""
    if not _user_exists(KIOSK_USER) or _kiosk_password_disabled():
        return
    try:
        subprocess.run(['usermod', '-p', '*', KIOSK_USER],
                       capture_output=True, text=True, timeout=15, check=True)
        log.info("kiosk user password disabled (shell account present)")
    except Exception:
        log.exception("could not disable kiosk user password")

def set_shell_account(username, password):
    """Create (or update the password of) the Linux login used for SSH and the
    console. Full sudo, via 'sudo' group membership — sudoers.d/hifi stays as
    tight as it is, because it serves the kiosk user, not this one."""
    username = (username or '').strip().lower()
    password = password or ''
    if not SHELL_ACCOUNT_RE.match(username):
        return {'success': False, 'code': 'shell.badUsername',
                'message': _t('shell.badUsername', _lang())}
    if username in SHELL_ACCOUNT_RESERVED:
        return {'success': False, 'code': 'shell.reservedUsername',
                'message': _t('shell.reservedUsername', _lang(), username=username)}
    if len(password) < 8:
        return {'success': False, 'code': 'shell.shortPassword',
                'message': _t('shell.shortPassword', _lang())}
    # chpasswd reads "user:password" lines, so either character would let a
    # crafted password rewrite a different account's entry.
    if '\n' in password or ':' in password:
        return {'success': False, 'code': 'shell.badPassword',
                'message': _t('shell.badPassword', _lang())}

    existed = _user_exists(username)
    try:
        if not existed:
            subprocess.run(['useradd', '-m', '-s', '/bin/bash', '-G', 'sudo', username],
                           capture_output=True, text=True, timeout=30, check=True)
        elif not _user_in_group(username, 'sudo'):
            subprocess.run(['usermod', '-aG', 'sudo', username],
                           capture_output=True, text=True, timeout=20, check=True)
        # Read the journal without needing sudo for it.
        subprocess.run(['usermod', '-aG', 'adm,systemd-journal', username],
                       capture_output=True, text=True, timeout=20)
        # Password on stdin — never on the command line, where it would be
        # visible in /proc to every local process.
        subprocess.run(['chpasswd'], input=f'{username}:{password}\n', text=True,
                       capture_output=True, timeout=30, check=True)
    except subprocess.CalledProcessError as e:
        log.error("shell account provisioning failed: %s", (e.stderr or '').strip())
        return {'success': False, 'code': 'shell.createFailed',
                'message': _t('shell.createFailed', _lang())}
    except Exception:
        log.exception("shell account provisioning failed")
        return {'success': False, 'code': 'shell.createFailed',
                'message': _t('shell.createFailed', _lang())}

    # Only now, with a verified working login in place, retire the old default.
    if _user_exists(username) and _user_in_group(username, 'sudo'):
        try:
            os.makedirs(os.path.dirname(SHELL_ACCOUNT_FILE), exist_ok=True)
            tmp = SHELL_ACCOUNT_FILE + '.tmp'
            with open(tmp, 'w') as f:
                f.write(username + '\n')
            os.chmod(tmp, 0o644)
            os.replace(tmp, SHELL_ACCOUNT_FILE)
        except Exception:
            log.exception("could not record shell account name")
        _disable_kiosk_password()

    out = get_shell_account()
    out['success'] = True
    out['code'] = 'shell.updated' if existed else 'shell.created'
    out['message'] = 'SSH login updated.' if existed else 'SSH login created.'
    return out

# ──────────────────────────────────────────────────────────────────
#  Support bundle — a downloadable zip with logs + system diagnostics, so a
#  remote issue can be triaged without asking the user for SSH access (which
#  ships OFF by default, see the SSH section above). Read-only: never touches
#  system state. Loopback-only like every other route here; webui_server.py
#  gates it behind an authenticated admin session before proxying.
# ──────────────────────────────────────────────────────────────────
SUPPORT_LOG_DIR = '/var/log/hifi'
SUPPORT_JOURNAL_UNITS = [
    'hifi-api', 'hifi-webui', 'hifi-sources', 'hifi-vumeter', 'hifi-firstboot',
    'hifi-quiesce-audio-shutdown', 'squeezelite', 'lyrionmusicserver',
    'bluetooth', 'NetworkManager',
]
# Config worth including — never secrets/keys. Mirrors the allow-list spirit of
# sources_server.py's BACKUP_FILES, but deliberately excludes everything under
# /etc/hifi-player (webui.db, TLS key, OTA pubkey/signing material) and
# /etc/NetworkManager/system-connections (plaintext Wi-Fi PSKs).
SUPPORT_CONFIG_FILES = [
    '/etc/hifi-sources.json',
    '/etc/hifi-player/display-mode',
    '/etc/hifi-player/ui-resolution',
    '/etc/hifi-player/ota-channel',
    '/etc/hifi-player/SYSTEM_VERSION',
    '/etc/hifi-player/OS_VERSION',
]


def _support_journal_dump(unit, since='7 days ago'):
    """Bounded window + line cap per unit — a device with months of uptime (or
    a degraded journald) must never make the whole bundle stall: with only
    --since, journalctl has to scan the entire matching range before
    returning; -n also lets it seek from the end and stop early once it has
    enough lines, which is what actually keeps this fast in practice."""
    try:
        r = subprocess.run(['journalctl', '-u', unit, '--since', since,
                            '-n', '2000', '-o', 'short-iso', '--no-pager'],
                           capture_output=True, text=True, timeout=12)
        return r.stdout or ''
    except Exception as e:
        return f'(journalctl fallito: {e})\n'


def _support_services_snapshot():
    lines = ['== systemctl list-units --failed ==']
    try:
        r = subprocess.run(['systemctl', 'list-units', '--failed', '--no-pager'],
                           capture_output=True, text=True, timeout=15)
        lines.append(r.stdout or '')
    except Exception as e:
        lines.append(f'(list-units --failed fallito: {e})')
    lines.append('== stato unit hifi ==')
    for unit in SUPPORT_JOURNAL_UNITS:
        try:
            en = subprocess.run(['systemctl', 'is-enabled', unit],
                                capture_output=True, text=True, timeout=10)
            ac = subprocess.run(['systemctl', 'is-active', unit],
                                capture_output=True, text=True, timeout=10)
            lines.append(f'{unit}: enabled={en.stdout.strip() or "?"} active={ac.stdout.strip() or "?"}')
        except Exception as e:
            lines.append(f'{unit}: errore ({e})')
    return '\n'.join(lines) + '\n'


def _support_bundle_build():
    """Build the support zip in memory. Every section is best-effort: one
    failing piece (e.g. journalctl unavailable) must never abort the rest."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        # logs/ — the rotated files every daemon now writes (see hifi_logging.py)
        try:
            if os.path.isdir(SUPPORT_LOG_DIR):
                for fname in sorted(os.listdir(SUPPORT_LOG_DIR)):
                    fpath = os.path.join(SUPPORT_LOG_DIR, fname)
                    if os.path.isfile(fpath):
                        z.write(fpath, arcname=f'logs/{fname}')
        except Exception:
            log.exception("support bundle: logs/ collection failed")

        for unit in SUPPORT_JOURNAL_UNITS:
            z.writestr(f'journal/{unit}.log', _support_journal_dump(unit))

        z.writestr('system_info.json', json.dumps(get_system_info(), indent=2))
        z.writestr('services.txt', _support_services_snapshot())

        for fpath in SUPPORT_CONFIG_FILES:
            try:
                if os.path.isfile(fpath):
                    z.write(fpath, arcname='config' + fpath)
            except Exception:
                log.exception("support bundle: config file %s failed", fpath)

        try:
            r = subprocess.run(['dmesg', '--ctime'], capture_output=True, text=True, timeout=15)
            tail = '\n'.join((r.stdout or '').splitlines()[-500:])
            z.writestr('dmesg_tail.txt', tail)
        except Exception as e:
            z.writestr('dmesg_tail.txt', f'(dmesg fallito: {e})\n')

    return buf.getvalue()

# ──────────────────────────────────────────────────────────────────
#  HAR network capture (Debug section, Settings.jsx) — captured by the
#  Electron main process over Chrome DevTools Protocol (main/main.js's
#  har-capture-start/stop IPC handlers, kiosk-only: only the on-device app
#  can drive its own webContents.debugger). This file's job is just to list/
#  serve/delete whatever .har files already landed on disk, for the web
#  admin to download — same loopback-only trust model as /support_bundle.
# ──────────────────────────────────────────────────────────────────
# Must match main/main.js's HAR_CAPTURE_DIR exactly (app.getPath('logs') +
# '/har-captures', which resolves to this on the appliance's --user-data-dir).
HAR_CAPTURE_DIR = '/home/hifi/.config/hifi-media-player/logs/har-captures'
# Matches exactly what main.js generates (`capture-` + toISOString() with
# ':'/'.' replaced by '-', which leaves the trailing 'Z' + '.har') -- anchored
# both ends, so this also doubles as the path-traversal guard for the
# download/delete routes below (no '/', no '..').
_HAR_FILENAME_RE = re.compile(r'^capture-[0-9TZ-]+\.har$')

def _har_captures_list():
    out = []
    try:
        fnames = os.listdir(HAR_CAPTURE_DIR)
    except OSError:
        return out
    for fname in sorted(fnames, reverse=True):
        if not _HAR_FILENAME_RE.match(fname):
            continue
        try:
            st = os.stat(os.path.join(HAR_CAPTURE_DIR, fname))
        except OSError:
            continue
        out.append({'name': fname, 'size': st.st_size, 'mtime': int(st.st_mtime)})
    return out

# ──────────────────────────────────────────────────────────────────
#  Tailscale — join the OWNER's OWN existing tailnet (their own Tailscale
#  account), so the appliance and all of its ports (web UI, Lyrion, SMB,
#  etc.) become reachable from anywhere that tailnet reaches — e.g. to get
#  at the music library while away from home — without opening anything to
#  the public internet. This talks only to Tailscale's own service. Login
#  uses plain `tailscale up` (interactive): it prints a one-time
#  https://login.tailscale.com/... URL that the owner opens on ANY device
#  (phone, laptop...) to approve this node from their own account — no auth
#  key to generate/paste, no vendor infrastructure or approval step.
# ──────────────────────────────────────────────────────────────────
def _tailscale_available():
    return bool(shutil.which('tailscale'))


def install_tailscale():
    """Runtime fallback for devices that missed the build-time hook / OTA
    migration that normally installs Tailscale (0410-tailscale.hook.chroot,
    distro/os-update/apply.d/0029-remote-support.sh) — same official
    installer both of those use, which sets up Tailscale's own apt repo +
    signing key before installing the package via apt (a plain
    `apt-get install tailscale` fails on a stock Debian repo list)."""
    if _tailscale_available():
        return {'success': True, 'available': True, 'code': 'tailscale.alreadyInstalled',
                'message': _t('tailscale.alreadyInstalled', _lang())}
    try:
        r = subprocess.run(
            ['sh', '-c', 'curl -fsSL https://tailscale.com/install.sh | sh'],
            capture_output=True, text=True, timeout=180)
        if r.returncode != 0 or not _tailscale_available():
            log.error("tailscale install failed: %s", (r.stderr or '').strip())
            return {'success': False, 'available': False, 'code': 'tailscale.installFailedNetwork',
                    'message': _t('tailscale.installFailedNetwork', _lang())}
    except Exception:
        log.exception("tailscale install failed")
        return {'success': False, 'available': False, 'code': 'tailscale.installFailed',
                'message': _t('tailscale.installFailed', _lang())}
    return {'success': True, 'available': True, 'code': 'tailscale.installed',
            'message': _t('tailscale.installed', _lang())}


def _device_label():
    """Human-recognizable, per-device Tailscale hostname: every appliance
    ships with the SAME hostname (preseed.cfg fixes it to 'hifiplayer'), so
    socket.gethostname() alone would collide across a tailnet with more than
    one unit. Combine the customer-chosen player name (may also collide — it
    defaults to 'OsmiumSound') with a short, genuinely unique-per-install
    suffix from /etc/machine-id."""
    try:
        with open('/etc/machine-id') as f:
            machine_id = f.read().strip()
    except Exception:
        machine_id = ''
    suffix = machine_id[-6:] if machine_id else socket.gethostname()
    name = re.sub(r'[^a-z0-9-]+', '-', _current_player_name().lower()).strip('-') or 'device'
    return f'{name}-{suffix}'


_DERP_NEAREST_RE = re.compile(r'Nearest DERP:\s*(.+)')
_DERP_LATENCY_LINE_RE = re.compile(r'-\s*(\w+):\s*([\d.]+)ms\s*\(([^)]+)\)')


def _tailscale_netcheck():
    """Best-effort nearest-DERP name + latency from `tailscale netcheck`'s
    plain-text report -- there's no stable structured output for this
    subcommand across tailscale versions, so this is a defensive text scrape:
    any format mismatch just yields empty fields rather than failing, since
    it's purely informational (Tailscale status card)."""
    try:
        r = subprocess.run(['tailscale', 'netcheck'], capture_output=True, text=True, timeout=10)
        out = (r.stdout or '') + (r.stderr or '')
        m = _DERP_NEAREST_RE.search(out)
        nearest = m.group(1).strip() if m else ''
        latency_ms = None
        if nearest:
            for line in out.splitlines():
                lm = _DERP_LATENCY_LINE_RE.search(line)
                if lm and lm.group(3).strip().lower() == nearest.lower():
                    latency_ms = float(lm.group(2))
                    break
        return nearest, latency_ms
    except Exception:
        return '', None


def get_tailscale_status():
    if not _tailscale_available():
        return {'available': False, 'connected': False}
    try:
        r = subprocess.run(['tailscale', 'status', '--json'],
                           capture_output=True, text=True, timeout=10)
        st = json.loads(r.stdout or '{}')
        backend = st.get('BackendState', '')
        connected = backend == 'Running'
        self_node = st.get('Self') or {}
        ips = self_node.get('TailscaleIPs') or []
    except Exception:
        log.exception("get_tailscale_status failed")
        return {'available': True, 'connected': False, 'error': _t('tailscale.statusUnavailable', _lang())}
    derp_region, derp_latency_ms = _tailscale_netcheck() if connected else ('', None)
    return {'available': True, 'connected': connected, 'backend_state': backend,
            'ip': ips[0] if ips else '', 'hostname': self_node.get('HostName') or '',
            'derp_relay': self_node.get('Relay') or '', 'derp_region': derp_region,
            'derp_latency_ms': derp_latency_ms}


_TAILSCALE_URL_RE = re.compile(r'https://\S+')


def set_tailscale(enable):
    """Join (or leave) the owner's own tailnet. Joining runs plain
    `tailscale up`, which — the first time, or after a full logout — prints a
    one-time login URL and then blocks until the node is approved from that
    URL (opened on any device, not necessarily this one) or a session-scoped
    timeout tailscaled applies on its own; once authenticated, Tailscale
    remembers it across reboots, so re-enabling later reconnects instantly
    with no URL. We don't wait for that: read `up`'s output just long enough
    to grab the URL (or notice it connected immediately with no URL needed)
    and hand it back to the caller, leaving the process running in the
    background — the frontend polls get_tailscale_status() to notice when
    the owner finishes approving it elsewhere.
    Leaving uses 'down' (disconnect, keep the node's identity) rather than
    'logout' (which would deregister it), so a later toggle-on reconnects
    without a fresh login."""
    if not _tailscale_available():
        return {'success': False, 'available': False, 'connected': False,
                'code': 'tailscale.notInstalled', 'message': _t('tailscale.notInstalled', _lang())}
    if enable:
        cmd = ['sudo', 'tailscale', 'up', f'--hostname={_device_label()}']
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        except Exception:
            log.exception("tailscale up failed to start")
            return {'success': False, 'available': True, 'connected': False,
                    'code': 'tailscale.enableFailed', 'message': _t('tailscale.enableFailed', _lang())}

        lines = queue.Queue()

        def _pump():
            try:
                for line in proc.stdout:
                    lines.put(line)
            except Exception:
                pass

        threading.Thread(target=_pump, daemon=True).start()

        login_url = None
        output = []
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                line = lines.get(timeout=max(0.1, deadline - time.monotonic()))
            except queue.Empty:
                break
            output.append(line)
            m = _TAILSCALE_URL_RE.search(line)
            if m:
                login_url = m.group(0).strip()
                break
            if proc.poll() is not None:
                break

        if login_url:
            status = get_tailscale_status()
            status['success'] = True
            status['login_url'] = login_url
            status['message'] = _t('tailscale.openLink', _lang())
            return status

        exit_code = proc.poll()
        if exit_code == 0:
            # Already authenticated (e.g. re-enabling after 'down') — no URL needed.
            status = get_tailscale_status()
            status['success'] = True
            status['message'] = _t('tailscale.enabled', _lang())
            return status
        if exit_code not in (None, 0):
            err = ''.join(output).strip()
            log.error("tailscale up failed: %s", err)
            return {'success': False, 'available': True, 'connected': False,
                    'code': 'tailscale.enableFailed', 'message': _t('tailscale.enableFailed', _lang())}

        # Still running with no URL yet (slow network) — leave it in the
        # background, the frontend will keep polling status.
        status = get_tailscale_status()
        status['success'] = True
        status['message'] = _t('tailscale.enabling', _lang())
        return status

    try:
        subprocess.run(['sudo', 'tailscale', 'down'], capture_output=True, text=True, timeout=30)
    except Exception:
        log.exception("set_tailscale(disable) failed")
        return {'success': False, 'code': 'tailscale.disableFailed',
                'message': _t('tailscale.disableFailed', _lang())}
    status = get_tailscale_status()
    status['success'] = True
    status['message'] = _t('tailscale.disabled', _lang())
    return status

# ──────────────────────────────────────────────────────────────────
#  Mouse pointer (cursor) control — the appliance is built for a
#  touchscreen, so the X cursor is auto-hidden by unclutter. This lets a
#  user WITHOUT a touchscreen turn the on-screen pointer on from Settings.
#  The choice is persisted and re-applied at login by ~/.xsession; here we
#  also apply it live so it takes effect without a reboot.
#  NOTE: the cursor only ever appears once the X server is no longer started
#  with `-nocursor` (removed at build time + by OS-OTA migration); on an
#  un-migrated device a reboot is needed after that update for it to show.
# ──────────────────────────────────────────────────────────────────
POINTER_FILE = '/etc/hifi-player/pointer-enabled'

def _has_unclutter():
    return bool(shutil.which('unclutter'))

def get_pointer_status():
    """Return { available, enabled }. 'enabled' = pointer shown (cursor not
    auto-hidden). Defaults to disabled (hidden) — the touchscreen default."""
    enabled = False
    try:
        with open(POINTER_FILE) as f:
            enabled = f.read().strip() == '1'
    except Exception:
        pass
    return {'available': _has_unclutter(), 'enabled': enabled}

def _kiosk_x_env():
    """Environment for talking to the kiosk X server (hifi autologin = :0)."""
    env = dict(os.environ)
    env['DISPLAY'] = env.get('DISPLAY', ':0')
    env.setdefault('XAUTHORITY', '/home/hifi/.Xauthority')
    return env

def set_pointer(enable):
    """Show (enable) or hide (disable) the mouse pointer — live + persisted.
    Showing kills the cursor-hider (unclutter); hiding (re)starts it. The
    persisted flag is read by ~/.xsession so the choice survives a reboot."""
    try:
        os.makedirs(os.path.dirname(POINTER_FILE), exist_ok=True)
        tmp = POINTER_FILE + '.tmp'
        with open(tmp, 'w') as f:
            f.write(('1' if enable else '0') + '\n')
        os.replace(tmp, POINTER_FILE)
    except Exception:
        log.exception("set_pointer: persist failed")
        return {'success': False, 'available': _has_unclutter(),
                'enabled': get_pointer_status()['enabled'],
                'code': 'prefs.saveFailed', 'message': _t('prefs.saveFailed', _lang())}

    # Apply live to the running session (best-effort; the persisted flag covers
    # the next login regardless of whether this succeeds).
    try:
        # Either way, stop any running cursor-hider first.
        subprocess.run(['pkill', '-x', 'unclutter'], capture_output=True, timeout=10)
        if not enable and _has_unclutter():
            # Re-hide: relaunch unclutter in the kiosk X session, detached.
            subprocess.Popen(['unclutter', '-idle', '1', '-root'],
                             env=_kiosk_x_env(),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
    except Exception:
        log.exception("set_pointer: live apply failed")

    return {'success': True, 'available': _has_unclutter(), 'enabled': bool(enable),
            'message': _t('pointer.shown' if enable else 'pointer.hidden', _lang())}

# ──────────────────────────────────────────────────────────────────
#  Display mode — GUI touchscreen kiosk vs headless. The appliance ships
#  GUI-first (graphical.target -> LightDM -> Electron kiosk). Headless is a
#  real persisted mode: multi-user.target, no X, controlled remotely
#  (companion app / Lyrion :9000 / sources :8080). All hifi-* daemons +
#  squeezelite + Lyrion run in BOTH modes, so switching only adds/removes the
#  on-screen GUI stack — nothing about playback or control changes.
#
#  The actual switch is done by /usr/local/sbin/hifi-display-mode.sh (flips the
#  default systemd target; --live also isolates the target now, after a short
#  delay so this HTTP response is flushed before the GUI that issued it dies).
#  api_server runs as root, so no sudoers entry is needed.
#
#  Persisted state ABSENT means gui — the fleet-safety default (an existing
#  configured unit must never drift into headless on an OS update).
# ──────────────────────────────────────────────────────────────────
DISPLAY_MODE_FILE = '/etc/hifi-player/display-mode'
DISPLAY_MODE_SCRIPT = '/usr/local/sbin/hifi-display-mode.sh'
DISPLAY_MODES = ('gui', 'headless')
# Update states that mean "an OTA is actively working"; switching the systemd
# target mid-update could interrupt it or collide with an update reboot, so we
# refuse the switch while any of these is in progress.
_UPDATE_BUSY_STATES = ('downloading', 'verifying', 'applying', 'installing', 'running', 'rebooting')

def _update_in_progress():
    # A sequenced plan is authoritative: it is persistent, so unlike the /run
    # status files it still reads "running" across the reboot an OS payload
    # asked for — which is exactly when a display-mode switch or a factory
    # reset would do the most damage.
    try:
        if update_plan_status().get('state') == 'running':
            return True
    except Exception:
        pass
    for status_fn in (os_update_status, system_update_status):
        try:
            if (status_fn() or {}).get('state') in _UPDATE_BUSY_STATES:
                return True
        except Exception:
            pass
    return False

def get_display_mode():
    """Return { mode }. 'gui' (default when the file is absent) or 'headless'."""
    mode = 'gui'
    try:
        with open(DISPLAY_MODE_FILE) as f:
            if f.read().strip() == 'headless':
                mode = 'headless'
    except Exception:
        pass
    return {'mode': mode}

def set_display_mode(mode):
    """Switch GUI <-> headless, live + persisted. Refused while an OTA is
    applying (a target switch mid-update could interrupt it)."""
    if mode not in DISPLAY_MODES:
        return {'success': False, 'mode': get_display_mode()['mode'],
                'code': 'displayMode.invalid', 'message': _t('displayMode.invalid', _lang())}
    if _update_in_progress():
        return {'success': False, 'mode': get_display_mode()['mode'],
                'code': 'update.inProgressRetry', 'message': _t('update.inProgressRetry', _lang())}
    try:
        r = subprocess.run([DISPLAY_MODE_SCRIPT, 'set', mode, '--live'],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            log.error("set_display_mode failed: %s", (r.stderr or '').strip())
            return {'success': False, 'mode': get_display_mode()['mode'],
                    'code': 'displayMode.changeFailed', 'message': _t('displayMode.changeFailed', _lang())}
    except Exception:
        log.exception("set_display_mode failed")
        return {'success': False, 'mode': get_display_mode()['mode'],
                'code': 'displayMode.changeFailed', 'message': _t('displayMode.changeFailed', _lang())}
    # In gui mode the switch is instant (LightDM already up); in headless the X
    # session is torn down a moment after this response is sent.
    msg = _t('displayMode.guiEnabled' if mode == 'gui' else 'displayMode.headlessEnabled', _lang())
    return {'success': True, 'mode': mode, 'message': msg}

# ──────────────────────────────────────────────────────────────────
#  Player enabled/disabled — whether this device plays audio at all
#  (squeezelite), orthogonal to display mode above (which only controls the
#  on-screen kiosk). A "server only" unit keeps Lyrion + every hifi-* daemon
#  running but never launches squeezelite here — e.g. a box in a closet whose
#  only job is serving satellite players elsewhere.
#
#  Persisted state ABSENT means enabled — same fleet-safety default as
#  display mode (an existing configured unit must never drift into "no
#  player" on an OS update).
# ──────────────────────────────────────────────────────────────────
PLAYER_ENABLED_FILE = '/etc/hifi-player/player-enabled'

def get_player_enabled():
    """Return { enabled }. True (default when the file is absent) or False."""
    enabled = True
    try:
        with open(PLAYER_ENABLED_FILE) as f:
            if f.read().strip() == '0':
                enabled = False
    except Exception:
        pass
    return {'enabled': enabled}

def set_player_enabled(enabled):
    """Enable/disable squeezelite, live + persisted. Refused while an OTA is
    applying, same guard as display mode (set_display_mode above)."""
    if _update_in_progress():
        return {'success': False, 'enabled': get_player_enabled()['enabled'],
                'code': 'update.inProgressRetry', 'message': _t('update.inProgressRetry', _lang())}
    action = 'enable' if enabled else 'disable'
    try:
        r = subprocess.run(['systemctl', action, '--now', 'squeezelite'],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            log.error("set_player_enabled %s failed: %s", action, (r.stderr or '').strip())
            return {'success': False, 'enabled': get_player_enabled()['enabled'],
                    'code': 'player.toggleFailed', 'message': _t('player.toggleFailed', _lang())}
    except Exception:
        log.exception("set_player_enabled failed")
        return {'success': False, 'enabled': get_player_enabled()['enabled'],
                'code': 'player.toggleFailed', 'message': _t('player.toggleFailed', _lang())}
    try:
        os.makedirs(os.path.dirname(PLAYER_ENABLED_FILE), exist_ok=True)
        with open(PLAYER_ENABLED_FILE, 'w') as f:
            f.write('1' if enabled else '0')
    except Exception:
        log.exception("set_player_enabled: failed to persist state")
    msg = _t('player.enabled' if enabled else 'player.disabled', _lang())
    return {'success': True, 'enabled': enabled, 'message': msg}

def _restart_squeezelite_if_enabled(timeout=30):
    """`systemctl restart` starts a unit regardless of its enablement, so a
    plain restart after an audio/DSP config change would silently bring
    squeezelite back up even while the user has it off (server-only mode).
    Skip the restart entirely while disabled; the config change is still
    persisted to disk and takes effect next time the player is re-enabled."""
    if not get_player_enabled()['enabled']:
        return subprocess.CompletedProcess(args=['systemctl', 'restart', 'squeezelite'], returncode=0)
    return _run(['systemctl', 'restart', 'squeezelite'], timeout=timeout)

# ──────────────────────────────────────────────────────────────────
#  UI render resolution. The interface is a fixed 1024x600 canvas CSS-zoomed
#  to the panel, and the Electron window is created as large as the panel —
#  so on a 1080p/4K screen Chromium really rasterizes 2..8 Mpixel per repaint
#  (every blur radius scales with the zoom too), pinning weak kiosk iGPUs near
#  100%. Nothing inside Chromium reduces that pixel count; the only real lever
#  is below it, in the X framebuffer.
#
#  /usr/local/sbin/hifi-ui-resolution.sh shrinks the framebuffer area mapped to
#  the output (xrandr --scale-from), keeping the native video mode, and the GPU
#  upscales it during scanout. api_server runs as root, so no sudoers entry is
#  needed.
#
#  Persisted state ABSENT means "auto" — unlike display-mode, the default here
#  is deliberately meant to reach the already-installed fleet: a unit that has
#  never written the file is exactly the one suffering from this, and it will
#  never open Settings.
# ──────────────────────────────────────────────────────────────────
UI_RESOLUTION_FILE = '/etc/hifi-player/ui-resolution'
UI_RESOLUTION_SCRIPT = '/usr/local/sbin/hifi-ui-resolution.sh'
UI_RESOLUTIONS = ('auto', '720', '1080', 'native')

def get_ui_resolution():
    """Return { mode }. One of UI_RESOLUTIONS; 'auto' when the file is absent
    or holds anything unrecognised."""
    mode = 'auto'
    try:
        with open(UI_RESOLUTION_FILE) as f:
            val = f.read().strip()
        if val in UI_RESOLUTIONS:
            mode = val
    except Exception:
        pass
    return {'mode': mode}

def set_ui_resolution(mode):
    """Persist the render resolution and restart the graphical session so it
    takes effect. Refused while an OTA is applying — this tears the kiosk down
    and back up, which must not race an update reboot."""
    if mode not in UI_RESOLUTIONS:
        return {'success': False, 'mode': get_ui_resolution()['mode'],
                'code': 'uiResolution.invalid', 'message': _t('uiResolution.invalid', _lang())}
    if _update_in_progress():
        return {'success': False, 'mode': get_ui_resolution()['mode'],
                'code': 'update.inProgressRetry', 'message': _t('update.inProgressRetry', _lang())}
    if not os.path.exists(UI_RESOLUTION_SCRIPT):
        return {'success': False, 'mode': get_ui_resolution()['mode'],
                'code': 'uiResolution.unavailable', 'message': _t('uiResolution.unavailable', _lang())}
    try:
        r = subprocess.run([UI_RESOLUTION_SCRIPT, 'set', mode, '--live'],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            log.error("set_ui_resolution failed: %s", (r.stderr or '').strip())
            return {'success': False, 'mode': get_ui_resolution()['mode'],
                    'code': 'uiResolution.changeFailed', 'message': _t('uiResolution.changeFailed', _lang())}
    except Exception:
        log.exception("set_ui_resolution failed")
        return {'success': False, 'mode': get_ui_resolution()['mode'],
                'code': 'uiResolution.changeFailed', 'message': _t('uiResolution.changeFailed', _lang())}
    # The X session is restarted a moment after this response is flushed, so
    # the kiosk UI issuing the request is about to disappear and come back.
    return {'success': True, 'mode': mode,
            'message': _t('uiResolution.updated', _lang())}

# ──────────────────────────────────────────────────────────────────
#  Timezone. The installer asks nothing about it (see distro/README.md) and
#  the build defaults every fresh image to UTC (0400-enable-services.hook.chroot)
#  — deterministic, but wrong for anyone who isn't in it, and units built from
#  old/refurbished hardware can drift further still without a working RTC
#  battery (systemd-timesyncd is now enabled by default to correct for that,
#  but it can't fix which zone the clock is displayed in). `timedatectl
#  set-timezone` is the whole mechanism: it updates /etc/localtime and
#  /etc/timezone itself and both survive a reboot on their own, so there is no
#  separate /etc/hifi-player/* marker file to keep in sync here.
# ──────────────────────────────────────────────────────────────────
ZONEINFO_DIR = '/usr/share/zoneinfo'

def get_timezone():
    """Return { timezone }. 'UTC' if it can't be determined."""
    try:
        with open('/etc/timezone') as f:
            tz = f.read().strip()
            if tz:
                return {'timezone': tz}
    except Exception:
        pass
    return {'timezone': 'UTC'}

def list_timezones():
    """All IANA zone names the installed tzdata knows about, e.g. 'Europe/Rome'."""
    names = []
    for dirpath, _dirnames, filenames in os.walk(ZONEINFO_DIR):
        for name in filenames:
            real = os.path.join(dirpath, name)
            rel = os.path.relpath(real, ZONEINFO_DIR)
            # tzdata ships a few non-zone files (posixrules, localtime itself if
            # present, leap seconds tables, the iso3166 country table, etc.) —
            # this is the same "does it look like Area/Location" heuristic
            # `timedatectl list-timezones` effectively applies.
            if rel.startswith('.') or rel in ('posixrules',) or '.' in name:
                continue
            names.append(rel.replace(os.sep, '/'))
    return sorted(names)

def set_timezone(tz):
    """Switch the system timezone, live + persisted, via timedatectl."""
    tz = (tz or '').strip()
    # timedatectl itself would refuse a bad name, but validate against
    # zoneinfo directly first: tz flows into a filesystem path below and this
    # is the chokepoint that keeps a "../../etc/passwd"-shaped value from ever
    # reaching a shell-adjacent API.
    real = os.path.normpath(os.path.join(ZONEINFO_DIR, tz))
    if not tz or not real.startswith(ZONEINFO_DIR + os.sep) or not os.path.isfile(real):
        return {'success': False, 'timezone': get_timezone()['timezone'],
                'code': 'timezone.invalid', 'message': _t('timezone.invalid', _lang())}
    try:
        r = subprocess.run(['timedatectl', 'set-timezone', tz],
                           capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            log.error("set_timezone failed: %s", (r.stderr or '').strip())
            return {'success': False, 'timezone': get_timezone()['timezone'],
                    'code': 'timezone.changeFailed', 'message': _t('timezone.changeFailed', _lang())}
    except Exception:
        log.exception("set_timezone failed")
        return {'success': False, 'timezone': get_timezone()['timezone'],
                'code': 'timezone.changeFailed', 'message': _t('timezone.changeFailed', _lang())}
    # timedatectl updates /etc/localtime live, but the kiosk's Electron/Chromium
    # process resolves its timezone (ICU) once at startup and never re-reads
    # it -- the on-screen clock would otherwise keep showing the old offset
    # until the next reboot. Kill it; the xsession restart loop (distro/os-update/
    # files/xsession) relaunches it within ~3s with the new zone applied. A
    # headless unit has no such process, so this is a harmless no-op there.
    try:
        subprocess.run(['pkill', '-x', 'hifi-media-player'], capture_output=True, timeout=10)
    except Exception:
        log.exception("set_timezone: kiosk restart failed")
    return {'success': True, 'timezone': tz,
            'message': _t('timezone.updated', _lang(), tz=tz)}

# ──────────────────────────────────────────────────────────────────
#  Animated VU meter (expanded now-playing view). Pure rendering choice, no OS
#  action — but it needs to live here (not just localStorage in the Electron
#  renderer) so it's reachable from the companion app / web admin on a
#  headless unit, where nobody can ever open the on-screen Settings to flip
#  it. Persisted state ABSENT means enabled (the shipped default).
# ──────────────────────────────────────────────────────────────────
VU_METER_FILE = '/etc/hifi-player/vu-meter-enabled'

def get_vu_meter():
    """Return { enabled }. Defaults to True (file absent or unreadable)."""
    enabled = True
    try:
        with open(VU_METER_FILE) as f:
            enabled = f.read().strip() != '0'
    except Exception:
        pass
    return {'enabled': enabled}

def set_vu_meter(enable):
    """Persist the VU meter preference. No live session action needed — the
    kiosk UI reads this on load and reacts immediately within its own tab."""
    try:
        os.makedirs(os.path.dirname(VU_METER_FILE), exist_ok=True)
        tmp = VU_METER_FILE + '.tmp'
        with open(tmp, 'w') as f:
            f.write(('1' if enable else '0') + '\n')
        os.replace(tmp, VU_METER_FILE)
    except Exception:
        log.exception("set_vu_meter: persist failed")
        return {'success': False, 'enabled': get_vu_meter()['enabled'],
                'code': 'prefs.saveFailed', 'message': _t('prefs.saveFailed', _lang())}
    return {'success': True, 'enabled': enable}

# ──────────────────────────────────────────────────────────────────
#  Now-playing auto-expand (kiosk-only UI behaviour, like the VU meter
#  above): how long after a song starts playing the kiosk should
#  automatically open the fullscreen now-playing view on its own, if the
#  user hasn't already navigated there. 0 = disabled (never auto-opens).
#  Persisted here (not just localStorage) for the same reason as
#  vu-meter-enabled: reachable from the companion app / web admin on a
#  headless unit.
# ──────────────────────────────────────────────────────────────────
NOWPLAYING_AUTOEXPAND_FILE = '/etc/hifi-player/nowplaying-autoexpand-seconds'
NOWPLAYING_AUTOEXPAND_CHOICES = (0, 3, 5, 10, 15)

def get_nowplaying_autoexpand():
    """Return { seconds }. Defaults to 0 (disabled; file absent/unreadable/invalid)."""
    seconds = 0
    try:
        with open(NOWPLAYING_AUTOEXPAND_FILE) as f:
            seconds = int(f.read().strip())
    except Exception:
        pass
    return {'seconds': seconds if seconds in NOWPLAYING_AUTOEXPAND_CHOICES else 0}

def set_nowplaying_autoexpand(seconds):
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        seconds = 0
    if seconds not in NOWPLAYING_AUTOEXPAND_CHOICES:
        seconds = 0
    try:
        os.makedirs(os.path.dirname(NOWPLAYING_AUTOEXPAND_FILE), exist_ok=True)
        tmp = NOWPLAYING_AUTOEXPAND_FILE + '.tmp'
        with open(tmp, 'w') as f:
            f.write(str(seconds) + '\n')
        os.replace(tmp, NOWPLAYING_AUTOEXPAND_FILE)
    except Exception:
        log.exception("set_nowplaying_autoexpand: persist failed")
        return {'success': False, 'seconds': get_nowplaying_autoexpand()['seconds'],
                'code': 'prefs.saveFailed', 'message': _t('prefs.saveFailed', _lang())}
    return {'success': True, 'seconds': seconds}

# ──────────────────────────────────────────────────────────────────
#  Boot debug flags (Settings → Debug, admin webui only). For diagnosing a box
#  that hangs at boot/shutdown behind the Plymouth splash instead of actually
#  crashing cleanly, or that needs a captured vmcore off a real kernel panic.
#  Both edit only GRUB_CMDLINE_LINUX_DEFAULT in /etc/default/grub, via the
#  same read-modify-write + `update-grub` pattern as the 0005-silent-grub OS
#  migration -- never grub-install/shim/Secure Boot (that's the one thing that
#  can brick a headless unit; regenerating grub.cfg from the already-installed
#  bootloader cannot). Both require an actual reboot to take effect, since a
#  running kernel's own cmdline can't be changed retroactively.
# ──────────────────────────────────────────────────────────────────
GRUB_DEFAULTS_FILE = '/etc/default/grub'
KDUMP_DEFAULTS_FILE = '/etc/default/kdump-tools'
# Reserved for the crash kernel once kdump is on -- taken out of normal use
# permanently after the next boot, so kept modest; standard x86_64 default.
KDUMP_CRASHKERNEL = 'crashkernel=256M'
# Stripped when disabling Plymouth so panic/boot text is actually visible
# (loglevel=0 silences the console same as the splash does); restored as a
# group when re-enabling.
_PLYMOUTH_QUIET_TOKENS = ('quiet', 'splash', 'loglevel=0')

def _read_kv_file(path, key):
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith(f'{key}='):
                    return line.split('=', 1)[1].strip().strip('"')
    except Exception:
        pass
    return None

def _write_kv_file(path, key, value):
    """In-place set/replace of KEY=value in a shell-sourced defaults file
    (/etc/default/*) -- read-modify-write, touches only this one key, leaves
    everything else in the file untouched."""
    try:
        with open(path) as f:
            lines = f.readlines()
    except Exception:
        lines = []
    new_line = f'{key}={value}\n'
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f'{key}='):
            lines[i] = new_line
            found = True
            break
    if not found:
        lines.append(new_line)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w') as f:
            f.writelines(lines)
        os.replace(tmp, path)
        return True
    except Exception:
        log.exception("_write_kv_file(%s) failed", path)
        return False

def _grub_cmdline_default():
    return (_read_kv_file(GRUB_DEFAULTS_FILE, 'GRUB_CMDLINE_LINUX_DEFAULT') or '').strip()

def _set_grub_cmdline_default(tokens):
    ok = _write_kv_file(GRUB_DEFAULTS_FILE, 'GRUB_CMDLINE_LINUX_DEFAULT', '"' + ' '.join(tokens) + '"')
    if not ok:
        return False
    r = _run(['update-grub'], timeout=60)
    if r.returncode != 0:
        r = _run(['update-grub2'], timeout=60)
    return r.returncode == 0

def get_plymouth_disabled():
    return {'disabled': 'plymouth.enable=0' in _grub_cmdline_default().split()}

def set_plymouth_disabled(disable):
    tokens = [t for t in _grub_cmdline_default().split()
              if t not in _PLYMOUTH_QUIET_TOKENS and t != 'plymouth.enable=0']
    if disable:
        tokens.append('plymouth.enable=0')
    else:
        tokens = list(_PLYMOUTH_QUIET_TOKENS) + tokens
    if not _set_grub_cmdline_default(tokens):
        return {'success': False, 'disabled': get_plymouth_disabled()['disabled'],
                'code': 'debug.updateGrubFailed', 'message': _t('debug.updateGrubFailed', _lang())}
    return {'success': True, 'disabled': disable, 'code': 'debug.rebootRequired',
            'message': _t('debug.rebootRequired', _lang())}

def _kdump_tools_installed():
    return subprocess.run(['dpkg', '-s', 'kdump-tools'], capture_output=True, timeout=10).returncode == 0

def get_kdump_enabled():
    return {'enabled': KDUMP_CRASHKERNEL in _grub_cmdline_default().split(),
            'installed': _kdump_tools_installed()}

def set_kdump_enabled(enable):
    if enable and not _kdump_tools_installed():
        try:
            r = subprocess.run(['apt-get', 'install', '-y', 'kdump-tools', 'linux-crashdump'],
                               capture_output=True, text=True, timeout=180,
                               env=dict(os.environ, DEBIAN_FRONTEND='noninteractive'))
        except Exception:
            r = None
        if r is None or r.returncode != 0 or not _kdump_tools_installed():
            log.error("kdump-tools install failed: %s", (r.stderr if r else '').strip())
            return {'success': False, 'enabled': get_kdump_enabled()['enabled'],
                    'code': 'debug.kdumpInstallFailed', 'message': _t('debug.kdumpInstallFailed', _lang())}
    tokens = [t for t in _grub_cmdline_default().split() if not t.startswith('crashkernel=')]
    if enable:
        tokens.append(KDUMP_CRASHKERNEL)
    if not _set_grub_cmdline_default(tokens):
        return {'success': False, 'enabled': get_kdump_enabled()['enabled'],
                'code': 'debug.updateGrubFailed', 'message': _t('debug.updateGrubFailed', _lang())}
    _write_kv_file(KDUMP_DEFAULTS_FILE, 'KDUMP_ENABLED', 'true' if enable else 'false')
    try:
        subprocess.run(['systemctl', 'enable' if enable else 'disable', '--now', 'kdump-tools'],
                       capture_output=True, timeout=30)
    except Exception:
        pass
    return {'success': True, 'enabled': enable, 'code': 'debug.rebootRequired',
            'message': _t('debug.rebootRequired', _lang())}

# ──────────────────────────────────────────────────────────────────
#  Provisioning + factory reset. The first-boot hotspot/captive flow and
#  the web-admin account live in webui_server.py (bound 0.0.0.0:443/:80).
#  api_server stays loopback-only; these endpoints are thin bridges the
#  Electron kiosk uses locally:
#   - /provision_status / /provision_mode proxy to webui on 127.0.0.1:80
#     (the provisioning API is always served there, even in LAN-only mode).
#   - /factory_reset runs the reset script detached (callers are the kiosk
#     [physical access] or webui [after its own admin-password check]).
#   - /webui_reset_credentials wipes the web-admin account from the kiosk
#     (physical-access recovery when the web password is forgotten).
# ──────────────────────────────────────────────────────────────────
WEBUI_BASE = 'http://127.0.0.1:80'
WEBUI_DB = '/etc/hifi-player/webui.db'
FACTORY_RESET_SCRIPT = '/usr/local/sbin/hifi-factory-reset.sh'

def _proxy_webui(path, method='GET', body=None, timeout=10):
    req = urllib.request.Request(f'{WEBUI_BASE}{path}', method=method)
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
            return {'success': False}, e.code
    except Exception:
        # webui not running / not in provisioning — treat as "nothing pending".
        return None, 0

def get_provision_status():
    body, _ = _proxy_webui('/api/provision/status')
    if body is None:
        return {'pending': False}
    return body

def set_provision_mode(mode, source='screen'):
    body, status = _proxy_webui('/api/provision/claim_mode', method='POST',
                                body={'mode': mode, 'source': source})
    if body is None:
        return {'success': False, 'code': 'provisioning.notActive',
                'message': _t('provisioning.notActive', _lang())}
    return body

def provision_wifi_connect(ssid, password):
    """Kick off the same Wi-Fi join webui_server's captive portal uses, from
    the on-screen manual network-setup panel. The AP drops immediately on
    webui's side; the kiosk keeps polling /provision_status to see it
    through 'connecting' -> 'network-ok'/'failed'."""
    body, status = _proxy_webui('/api/provision/wifi_connect', method='POST',
                                body={'ssid': ssid, 'password': password})
    if body is None:
        return {'success': False, 'code': 'provisioning.notActive',
                'message': _t('provisioning.notActive', _lang())}
    return body

def provision_wifi_rescan():
    """Live Wi-Fi rescan for the on-screen manual panel: briefly drops and
    re-raises the setup hotspot around the scan (see webui_server.py's
    _live_wifi_rescan()) so the list isn't stuck with whatever the single
    early-boot scan found. Generous timeout: AP down + scan + AP back up."""
    body, status = _proxy_webui('/api/provision/wifi_rescan', method='POST', timeout=30)
    if body is None:
        return {'success': False, 'code': 'provisioning.notActive',
                'message': _t('provisioning.notActive', _lang())}
    return body

def factory_reset():
    if _update_in_progress():
        return {'success': False, 'code': 'update.inProgressRetry',
                'message': _t('update.inProgressRetry', _lang())}
    if not os.path.exists(FACTORY_RESET_SCRIPT):
        return {'success': False, 'code': 'factoryReset.scriptMissing',
                'message': _t('factoryReset.scriptMissing', _lang())}
    try:
        # Detached transient unit so the reboot at the end doesn't kill us mid
        # HTTP response.
        subprocess.Popen(['systemd-run', '--collect', '--',
                          '/bin/sh', FACTORY_RESET_SCRIPT],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {'success': True, 'message': _t('factoryReset.started', _lang())}
    except Exception:
        log.exception("factory_reset failed")
        return {'success': False, 'code': 'factoryReset.startFailed',
                'message': _t('factoryReset.startFailed', _lang())}

def webui_reset_credentials():
    """Wipe the web-admin account (kiosk-only recovery). Direct sqlite so it
    works even if webui_server isn't running."""
    try:
        import sqlite3
        if os.path.exists(WEBUI_DB):
            conn = sqlite3.connect(WEBUI_DB)
            conn.execute('DELETE FROM admin_user')
            # Invalidate any open web sessions too.
            conn.execute("UPDATE meta SET value = CAST(CAST(value AS INTEGER)+1 AS TEXT) "
                         "WHERE key = 'session_version'")
            conn.commit()
            conn.close()
        return {'success': True, 'message': _t('webui.credsReset', _lang())}
    except Exception:
        log.exception("webui_reset_credentials failed")
        return {'success': False, 'code': 'webui.credsResetFailed',
                'message': _t('webui.credsResetFailed', _lang())}

# ──────────────────────────────────────────────────────────────────
#  Tidal Connect — optional. Lets the appliance appear as a Tidal Connect
#  target so the Tidal app can stream directly to it (via mDNS/avahi). The
#  daemon is an unofficial, reverse-engineered binary that is NOT bundled
#  (no trusted x86 build ships with the image); the OS-OTA migration only
#  sets up the prerequisites (avahi) and the systemd unit. The toggle is
#  therefore only "available" once a tidal-connect binary is actually present.
#  Unit name comes from a fixed constant (never user input) — no injection.
# ──────────────────────────────────────────────────────────────────
TIDAL_UNIT = 'tidal-connect.service'
TIDAL_BINARY = '/usr/local/bin/tidal_connect'

def _unit_exists(unit):
    try:
        r = subprocess.run(['systemctl', 'list-unit-files', unit],
                           capture_output=True, text=True, timeout=10)
        return r.returncode == 0 and unit in (r.stdout or '')
    except Exception:
        return False

def _tidal_available():
    # Both the unit AND the (unbundled) binary must be present for the toggle
    # to do anything useful.
    return _unit_exists(TIDAL_UNIT) and os.path.exists(TIDAL_BINARY)

def get_tidal_status():
    try:
        en = subprocess.run(['systemctl', 'is-enabled', TIDAL_UNIT],
                           capture_output=True, text=True, timeout=10)
        ac = subprocess.run(['systemctl', 'is-active', TIDAL_UNIT],
                           capture_output=True, text=True, timeout=10)
        return {
            'available': _tidal_available(),
            'enabled': en.stdout.strip() == 'enabled',
            'active': ac.stdout.strip() == 'active',
        }
    except Exception:
        log.exception("get_tidal_status failed")
        return {'available': False, 'enabled': False, 'active': False,
                'error': _t('tidal.statusUnavailable', _lang())}

def set_tidal(enable):
    """Enable+start or disable+stop the Tidal Connect daemon (persists)."""
    if enable and not _tidal_available():
        return {'success': False, 'available': False, 'enabled': False,
                'active': False, 'code': 'tidal.notInstalled',
                'message': _t('tidal.notInstalled', _lang())}
    action = 'enable' if enable else 'disable'
    try:
        r = subprocess.run(['sudo', 'systemctl', action, '--now', TIDAL_UNIT],
                          capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            log.error("set_tidal %s failed: %s", action, (r.stderr or '').strip())
            status = get_tidal_status()
            status['success'] = False
            status['code'] = 'tidal.opFailed'
            status['message'] = _t('tidal.opFailed', _lang())
            return status
    except Exception:
        log.exception("set_tidal failed")
        return {'success': False, 'code': 'tidal.opFailed', 'message': _t('tidal.opFailed', _lang())}
    status = get_tidal_status()
    status['success'] = True
    status['message'] = _t('tidal.enabled' if enable else 'tidal.disabled', _lang())
    return status

# ──────────────────────────────────────────────────────────────────
#  DSP / CamillaDSP engine — OPTIONAL parametric EQ + crossfeed.
#
#  Default OFF: squeezelite plays straight to the DAC (bit-perfect, DoP/DSD).
#  When ON, squeezelite is redirected to an snd-aloop Loopback; CamillaDSP
#  captures the loopback, applies the EQ/crossfeed, and outputs to the real
#  DAC. The DSP path resamples to a fixed rate and is therefore NOT bit-perfect
#  (DoP/DSD pass-through is disabled) — that's why it's an opt-in toggle.
#  Turning DSP OFF restores the exact previous bit-perfect squeezelite args.
# ──────────────────────────────────────────────────────────────────
CAMILLA_BIN = '/usr/local/bin/camilladsp'
CAMILLA_CONFIG = '/etc/camilladsp/config.yml'
CAMILLA_CONFIG_TMP = '/etc/camilladsp/config.yml.check'
DSP_UNIT = 'camilladsp.service'
# Flask runs threaded (see app.run below), so rapid-fire requests (e.g.
# switching EQ presets a few times in a row while a track is playing) can
# reach set_dsp()/set_audio_device() concurrently in separate threads.
# _apply_dsp_on/_off each do a restart of squeezelite AND camilladsp — two of
# those interleaving is the same DAC-contention race fixed for the on/off
# ordering earlier, just self-inflicted between two overlapping requests
# instead of a single misordered one. Serialize the whole apply so requests
# queue instead of racing each other for the ALSA device.
_dsp_apply_lock = threading.Lock()
DSP_STATE_FILE = '/etc/hifi-player/dsp.json'
DSP_PRESETS_FILE = '/etc/hifi-player/dsp-presets.json'
DSP_TARGET_FILE = '/var/lib/hifi-player/dsp-target'
DSP_RATE = 48000
LOOPBACK_PLAYBACK = 'hw:CARD=Loopback,DEV=0'   # squeezelite writes here
LOOPBACK_CAPTURE = 'hw:CARD=Loopback,DEV=1'    # CamillaDSP reads here

# Biquad filter types a band may take. Highpass/Lowpass have no gain
# parameter in CamillaDSP — emitting one is a config validation error.
DSP_BAND_TYPES = {'Peaking', 'Lowshelf', 'Highshelf', 'Highpass', 'Lowpass'}
DSP_BAND_TYPES_NO_GAIN = {'Highpass', 'Lowpass'}
DSP_BALANCE_MAX = 12.0

# Built-in read-only presets. Never persisted; 'balance'/'crossfeed'/
# 'room_correction' stay neutral so loading one only touches tone.
DSP_BUILTIN_PRESETS = {
    'Flat': {'bands': [], 'crossfeed': False, 'room_correction': False, 'balance': 0.0},
    'Warm': {'bands': [
        {'type': 'Lowshelf', 'freq': 150, 'gain': 2.0, 'q': 0.707},
        {'type': 'Highshelf', 'freq': 7500, 'gain': -1.5, 'q': 0.707},
    ], 'crossfeed': False, 'room_correction': False, 'balance': 0.0},
    'Bright': {'bands': [
        {'type': 'Highshelf', 'freq': 6000, 'gain': 2.5, 'q': 0.707},
    ], 'crossfeed': False, 'room_correction': False, 'balance': 0.0},
    'Loudness (low volume)': {'bands': [
        {'type': 'Lowshelf', 'freq': 120, 'gain': 4.0, 'q': 0.707},
        {'type': 'Highshelf', 'freq': 8000, 'gain': 2.0, 'q': 0.707},
    ], 'crossfeed': False, 'room_correction': False, 'balance': 0.0},
}
DSP_MAX_USER_PRESETS = 24

# Room-correction FIR filter — uploaded via the sources web service (:8080,
# see sources_server.py's /api/dsp/fir) and picked up here. Fixed dir/name
# (never a user-supplied filename), one filter at a time.
FIR_DIR = '/etc/camilladsp/filters'
FIR_KINDS = {'.wav': 'Wav', '.txt': 'Raw'}  # ext -> CamillaDSP Conv "type"

def _fir_current():
    """Return (path, camilla_type) of the stored FIR filter, or (None, None)."""
    for ext, kind in FIR_KINDS.items():
        p = os.path.join(FIR_DIR, 'room' + ext)
        if os.path.isfile(p):
            return p, kind
    return None, None

def _loopback_present():
    try:
        with open('/proc/asound/cards') as f:
            return 'Loopback' in f.read()
    except Exception:
        return False

def _dsp_available():
    return os.path.exists(CAMILLA_BIN) and _unit_exists(DSP_UNIT) and _loopback_present()

def _clean_band(b):
    """Validate/normalize one EQ band. Raises on a bad freq/gain/q (caller
    skips it), same as the pre-existing inline validation in set_dsp."""
    btype = b.get('type', 'Peaking')
    if btype not in DSP_BAND_TYPES:
        btype = 'Peaking'
    out = {
        'type': btype,
        'freq': max(20.0, min(20000.0, float(b.get('freq')))),
        'q': max(0.1, min(10.0, float(b.get('q', 1.0)) or 1.0)),
    }
    if btype not in DSP_BAND_TYPES_NO_GAIN:
        out['gain'] = max(-24.0, min(24.0, float(b.get('gain', 0))))
    return out

def _clean_bands(bands):
    clean = []
    for b in (bands or [])[:20]:
        try:
            clean.append(_clean_band(b))
        except Exception:
            continue
    return clean

def _clean_balance(v):
    try:
        return max(-DSP_BALANCE_MAX, min(DSP_BALANCE_MAX, float(v)))
    except Exception:
        return 0.0

def _read_dsp_state():
    try:
        with open(DSP_STATE_FILE) as f:
            d = json.load(f)
    except Exception:
        d = {}
    return {'enabled': bool(d.get('enabled')),
            'bands': _clean_bands(d.get('bands')),
            'crossfeed': bool(d.get('crossfeed')),
            'room_correction': bool(d.get('room_correction')),
            'balance': _clean_balance(d.get('balance') or 0.0),
            'preset': d.get('preset') or None}

def _write_dsp_state(state):
    os.makedirs(os.path.dirname(DSP_STATE_FILE), exist_ok=True)
    tmp = DSP_STATE_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f)
    os.replace(tmp, DSP_STATE_FILE)

def _read_dsp_target():
    try:
        with open(DSP_TARGET_FILE) as f:
            return f.read().strip() or 'default'
    except Exception:
        return 'default'

def _write_dsp_target(dev):
    os.makedirs(os.path.dirname(DSP_TARGET_FILE), exist_ok=True)
    tmp = DSP_TARGET_FILE + '.tmp'
    with open(tmp, 'w') as f:
        f.write((dev or 'default') + '\n')
    os.replace(tmp, DSP_TARGET_FILE)

# ── squeezelite ARGS string editing (shared with set_audio_device) ──
def _read_sq_args():
    """Return (full_file_content, args_string) or (content, None) if no ARGS=."""
    try:
        with open(SQUEEZELITE_DEFAULT) as f:
            content = f.read()
    except Exception:
        return None, None
    m = re.search(r"ARGS=(['\"])(.*?)\1", content)
    return content, (m.group(2) if m else None)

def _write_sq_args(new_args):
    content, _ = _read_sq_args()
    if content is None:
        content = ''
    m = re.search(r"ARGS=(['\"])(.*?)\1", content)
    if m:
        content = content[:m.start()] + f"ARGS='{new_args}'" + content[m.end():]
    else:
        content += f"\nARGS='{new_args}'\n"
    with open(SQUEEZELITE_DEFAULT, 'w') as f:
        f.write(content)

def _sq_set_o(args, dev):
    if re.search(r'-o\s+\S+', args):
        return re.sub(r'-o\s+\S+', f'-o {dev}', args)
    return f'-o {dev} ' + args

def _sq_set_s(args, host):
    if re.search(r'-s\s+\S+', args):
        return re.sub(r'-s\s+\S+', f'-s {host}', args)
    return (args + f' -s {host}').strip()

def _sq_remove_flag(args, flag):
    return re.sub(rf'(^|\s){re.escape(flag)}(?=\s|$)', ' ', args).strip()

def _sq_ensure_D(args):
    if not re.search(r'(^|\s)-D(\s|$)', args):
        args = re.sub(r'(-o\s+\S+)', r'\1 -D', args, count=1)
    return args

def _sq_set_rate(args, rate):
    if re.search(r'-r\s+\S+', args):
        return re.sub(r'-r\s+\S+', f'-r {rate}', args)
    return re.sub(r'(-o\s+\S+)', rf'\1 -r {rate}', args, count=1)

def _sq_ensure_R(args):
    if not re.search(r'(^|\s)-R(\s|$)', args):
        args = (args + ' -R').strip()
    return args

def _camilla_config_dict(playback_dev, bands, crossfeed, room_correction=False, balance=0.0):
    """Build a CamillaDSP config (returned as a dict; JSON is valid YAML)."""
    filters, eq_names = {}, []
    for i, b in enumerate(bands):
        nm = f'band_{i}'
        btype = b.get('type', 'Peaking')
        if btype not in DSP_BAND_TYPES:
            btype = 'Peaking'
        params = {
            'type': btype,
            'freq': float(b.get('freq', 1000)),
            'q': float(b.get('q', 1.0)) or 1.0,
        }
        if btype not in DSP_BAND_TYPES_NO_GAIN:
            params['gain'] = float(b.get('gain', 0))
        filters[nm] = {'type': 'Biquad', 'parameters': params}
        eq_names.append(nm)
    conv_names = []
    if room_correction:
        fir_path, fir_kind = _fir_current()
        if fir_path:
            filters['room_correction'] = {'type': 'Conv', 'parameters': {
                'type': fir_kind, 'filename': fir_path,
                **({'format': 'TEXT'} if fir_kind == 'Raw' else {}),
            }}
            conv_names.append('room_correction')
    mixers, pipeline = {}, []
    if crossfeed:
        # Basic headphone crossfeed: blend an attenuated copy of the opposite
        # channel into each ear (no delay — a simple, valid first version).
        mixers['crossfeed'] = {'channels': {'in': 2, 'out': 2}, 'mapping': [
            {'dest': 0, 'sources': [
                {'channel': 0, 'gain': -1.0, 'inverted': False},
                {'channel': 1, 'gain': -9.0, 'inverted': False}]},
            {'dest': 1, 'sources': [
                {'channel': 1, 'gain': -1.0, 'inverted': False},
                {'channel': 0, 'gain': -9.0, 'inverted': False}]},
        ]}
        pipeline.append({'type': 'Mixer', 'name': 'crossfeed'})
    # Room correction (convolution) runs before the parametric EQ, so manual EQ
    # tweaks are applied on top of the already-corrected response.
    if conv_names:
        pipeline.append({'type': 'Filter', 'channels': [0, 1], 'names': conv_names})
    if eq_names:
        pipeline.append({'type': 'Filter', 'channels': [0, 1], 'names': eq_names})
    # Balance: attenuate-only (never boost, so no clipping risk). Positive
    # balance shifts toward the right ear by attenuating the left channel,
    # and vice-versa. Applied last, after tone shaping.
    bal = max(-DSP_BALANCE_MAX, min(DSP_BALANCE_MAX, float(balance or 0.0)))
    if abs(bal) >= 0.05:
        gain_l = -max(0.0, bal)
        gain_r = min(0.0, bal)
        if gain_l:
            filters['balance_l'] = {'type': 'Gain', 'parameters': {'gain': gain_l}}
            pipeline.append({'type': 'Filter', 'channels': [0], 'names': ['balance_l']})
        if gain_r:
            filters['balance_r'] = {'type': 'Gain', 'parameters': {'gain': gain_r}}
            pipeline.append({'type': 'Filter', 'channels': [1], 'names': ['balance_r']})
    return {
        'devices': {
            'samplerate': DSP_RATE, 'chunksize': 1024,
            'enable_rate_adjust': True, 'target_level': 512,
            'capture': {'type': 'Alsa', 'channels': 2, 'device': LOOPBACK_CAPTURE, 'format': 'S32_LE'},
            'playback': {'type': 'Alsa', 'channels': 2, 'device': playback_dev, 'format': 'S32_LE'},
        },
        'filters': filters, 'mixers': mixers, 'pipeline': pipeline,
    }

def _current_real_dac():
    """The DAC squeezelite outputs to when DSP is OFF. When DSP is ON the
    squeezelite -o is the Loopback, so fall back to the stored target."""
    o = _current_audio_device()
    return _read_dsp_target() if 'Loopback' in o else o

# ── Pause playback around a DSP apply ───────────────────────────────
# Applying a DSP change restarts squeezelite and/or CamillaDSP, which means
# closing and reopening an ALSA device — abandoning a LIVE, actively-streaming
# transfer mid-flight is a much rougher transition than restarting an idle
# device (more in-flight state to unwind), and is suspected to be behind
# sporadic silence/lockups after a DSP toggle during playback (same class of
# problem as the DMA kernel panic mitigated for reboot/shutdown). Minimal
# local LMS JSON-RPC client so the backend can pause the local player itself
# before applying, and resume it after, regardless of which client (kiosk,
# companion app) triggered the change.
LMS_RPC_URL = 'http://127.0.0.1:9000/jsonrpc.js'

def _lms_request(playerid, command, timeout=5):
    payload = json.dumps({'id': 1, 'method': 'slim.request', 'params': [playerid, command]}).encode()
    req = urllib.request.Request(LMS_RPC_URL, data=payload, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read()).get('result')

def _local_playing_player():
    """(playerid, elapsed_seconds) of THIS device's own squeezelite instance
    if it's currently playing, else (None, 0.0) — only its stream is affected
    by a DSP apply (other multiroom members elsewhere are untouched). The
    elapsed position is captured here, BEFORE the pause/restart, so the
    resume can seek back to it — LMS does not reliably keep the position
    across the player's disconnect, so a bare `play` sometimes restarted the
    track from 0:00. Best-effort: any failure (LMS not reachable, unexpected
    shape) just means we don't pause, not a reason to fail the DSP apply."""
    try:
        result = _lms_request('-', ['serverstatus', 0, 999]) or {}
        for p in result.get('players_loop', []):
            if str(p.get('ip', '')).startswith('127.0.0.1:'):
                playerid = p.get('playerid')
                st = _lms_request(playerid, ['status', '-', 1]) or {}
                if st.get('mode') == 'play':
                    try:
                        elapsed = float(st.get('time') or 0.0)
                    except (TypeError, ValueError):
                        elapsed = 0.0
                    return playerid, elapsed
    except Exception:
        log.exception('_local_playing_player failed')
    return None, 0.0

def _lms_pause(playerid):
    try:
        _lms_request(playerid, ['pause', '1'])
    except Exception:
        log.exception('_lms_pause failed')

def _lms_resume(playerid, resume_at=0.0):
    """Restart playback after a DSP apply. Not `pause 0`: the apply killed
    and restarted squeezelite (and/or CamillaDSP), so there is no live paused
    stream on the player to simply unpause -- the new squeezelite process has
    nothing buffered. Wait until the player has actually re-registered with
    Lyrion (a fixed sleep proved too short: the slimproto handshake after a
    restart can take several seconds, and a `play` sent to a not-yet-connected
    player is silently dropped), start playback, then seek back to where the
    track was — `play` alone starts the current queue item from 0:00 whenever
    LMS lost the position across the disconnect."""
    try:
        for _ in range(20):  # up to ~10s
            try:
                st = _lms_request(playerid, ['status', '-', 1]) or {}
                if st.get('player_connected'):
                    break
            except Exception:
                pass
            time.sleep(0.5)
        _lms_request(playerid, ['play'])
        if resume_at and resume_at > 1.0:
            # Give the fresh stream a beat to actually start before seeking;
            # an unseekable source (radio stream) just ignores/fails this,
            # which is fine — it has no meaningful position to restore.
            time.sleep(0.5)
            try:
                _lms_request(playerid, ['time', round(resume_at, 1)])
            except Exception:
                pass
    except Exception:
        log.exception('_lms_resume failed')

# ──────────────────────────────────────────────────────────────────
#  Resume playback across a reboot. hifi-quiesce-audio-shutdown.sh runs
#  hifi-capture-playback-state.py before every shutdown/reboot (while LMS/
#  squeezelite are still up) and writes PLAYBACK_STATE_FILE; this reads it
#  back once at this process's own next startup. Not relying on LMS's native
#  playingAtPowerOff/positionAtDisconnect prefs for the same reason
#  _local_playing_player() above doesn't trust bare position-across-
#  disconnect: found unreliable in practice, plus those prefs are only
#  flushed to disk on a 10s debounced autosave that a fast power-off can miss
#  entirely — this file is written synchronously, right before shutdown.
# ──────────────────────────────────────────────────────────────────
PLAYBACK_STATE_FILE = '/var/lib/hifi-player/playback-state.json'

def _resume_playback_after_boot():
    """Was playing -> jump to that track/position and resume playing. Was
    paused -> load the same track at that position but leave it paused (the
    kiosk shows the right "now playing" info without audio starting on its
    own). Was stopped, or no state file (fresh install, or a normal restart
    that never captured one) -> do nothing. Runs in a background thread from
    __main__ so it never delays this API's own readiness; the kiosk UI works
    normally regardless of how long squeezelite takes to reconnect.

    LMS has its OWN native power-on-resume (playingAtPowerOff/
    positionAtDisconnect, applied the moment squeezelite's slimproto socket
    reconnects — before this function ever gets to run) — that's exactly the
    unreliable mechanism this whole feature avoids relying on (see the module
    comment above), and hifi-capture-playback-state.py already asks LMS to
    clear it at capture time. But that clear is itself just a best-effort pref
    write (same debounced-autosave risk), so it can't be trusted to have
    stuck: if it didn't, native resume fires on reconnect with whatever STALE
    track/position it last managed to persist (symptom seen in practice:
    some unrelated older track starts playing). An explicit `stop` here,
    before applying our own captured state, guarantees a clean slate either
    way regardless of what native resume already did."""
    log.info('resume-after-boot: state file %s', 'found' if os.path.exists(PLAYBACK_STATE_FILE) else 'absent')
    try:
        with open(PLAYBACK_STATE_FILE) as f:
            state = json.load(f)
    except Exception:
        return
    # Consume once: a later ordinary process restart (crash, manual restart)
    # must not re-apply a now-stale capture.
    try:
        os.remove(PLAYBACK_STATE_FILE)
    except OSError:
        pass
    mode = state.get('mode')
    if mode not in ('play', 'pause'):
        log.info('resume-after-boot: captured mode=%r, nothing to restore', mode)
        return
    try:
        index = int(state.get('playlist_cur_index') or 0)
        elapsed = float(state.get('time') or 0.0)
    except (TypeError, ValueError):
        return
    playerid = None
    try:
        for _ in range(90):  # up to ~90s: LMS's own startup/library scan can
                              # take a while, well past squeezelite's own
                              # 5s systemd RestartSec reconnect attempts.
            try:
                result = _lms_request('-', ['serverstatus', 0, 999]) or {}
                for p in result.get('players_loop', []):
                    if str(p.get('ip', '')).startswith('127.0.0.1:'):
                        candidate = p.get('playerid')
                        # A candidate can appear in players_loop just from
                        # LMS's own bookkeeping before slimproto has actually
                        # re-registered it — confirm it's really connected
                        # (same check _lms_resume makes) before trusting it.
                        st = _lms_request(candidate, ['status', '-', 1]) or {}
                        if st.get('player_connected'):
                            playerid = candidate
                        break
            except Exception:
                pass
            if playerid:
                break
            time.sleep(1.0)
        if not playerid:
            log.warning('resume-after-boot: local player never reconnected, giving up')
            return
        log.info('resume-after-boot: restoring mode=%s index=%s time=%.1f on %s', mode, index, elapsed, playerid)
        # Clean slate first: whatever LMS's own native power-on-resume already
        # did on reconnect (see docstring) gets wiped out here, so what
        # follows is the only thing that decides the end state.
        _lms_request(playerid, ['stop'])
        time.sleep(0.3)
        # `playlist index` both jumps to and starts that queue position —
        # there's no "load without playing" command — so a captured 'pause'
        # still starts it here and gets paused right back below, just long
        # enough to land on the right track/position first.
        _lms_request(playerid, ['playlist', 'index', index])
        if elapsed > 1.0:
            time.sleep(0.5)
            try:
                _lms_request(playerid, ['time', round(elapsed, 1)])
            except Exception:
                pass
        if mode == 'pause':
            _lms_request(playerid, ['pause', '1'])
        log.info('resume-after-boot: done')
    except Exception:
        log.exception('_resume_playback_after_boot failed')

def _camilla_config_valid(cfg):
    """Write cfg to a scratch file and ask CamillaDSP itself to validate it,
    so a bad EQ/balance/FIR combination can never leave squeezelite pointed
    at a Loopback with a dead (or silently-rejecting) CamillaDSP behind it."""
    try:
        with open(CAMILLA_CONFIG_TMP, 'w') as f:
            json.dump(cfg, f, indent=2)
        r = subprocess.run([CAMILLA_BIN, '--check', CAMILLA_CONFIG_TMP],
                           capture_output=True, text=True, timeout=15)
        return r.returncode == 0
    except Exception:
        log.exception('camilladsp --check failed')
        return False
    finally:
        try:
            os.remove(CAMILLA_CONFIG_TMP)
        except OSError:
            pass

def _apply_dsp_on(playback_dev, bands, crossfeed, room_correction=False, balance=0.0):
    cfg = _camilla_config_dict(playback_dev, bands, crossfeed, room_correction, balance)
    if not _camilla_config_valid(cfg):
        raise ValueError('Configurazione DSP non valida')
    # Pause first: about to restart squeezelite and/or CamillaDSP, i.e. close
    # and reopen an ALSA device — doing that while it's actively mid-stream
    # is what was leaving things silent/stuck after a DSP toggle during
    # playback. Always resume afterward, success or failure.
    playing_player, elapsed = _local_playing_player()
    if playing_player:
        _lms_pause(playing_player)
    try:
        _apply_dsp_on_locked(playback_dev, bands, crossfeed, room_correction, balance, cfg)
    finally:
        if playing_player:
            _lms_resume(playing_player, elapsed)

def _apply_dsp_on_locked(playback_dev, bands, crossfeed, room_correction, balance, cfg):
    os.makedirs(os.path.dirname(CAMILLA_CONFIG), exist_ok=True)
    with open(CAMILLA_CONFIG, 'w') as f:
        json.dump(cfg, f, indent=2)
    _write_dsp_target(playback_dev)
    _, args = _read_sq_args()
    if args is not None:
        new_args = _sq_set_o(args, LOOPBACK_PLAYBACK)
        new_args = _sq_remove_flag(new_args, '-D')   # no DoP/DSD through the DSP path
        new_args = _sq_set_rate(new_args, DSP_RATE)  # fixed rate into the loopback
        new_args = _sq_ensure_R(new_args)            # soxr resample to that rate
        # Collapse whitespace left behind by flag removal/insertion — belt and
        # braces against a messy starting string (e.g. an external migration
        # like 0003-audio-dsd-device.sh touching the same line) leaving runs
        # of spaces that would otherwise just accumulate on every apply.
        new_args = re.sub(r'\s+', ' ', new_args).strip()
        # squeezelite only needs restarting when its own args actually change
        # (DSP was off, or a preset/balance apply just merged in from an older
        # client that still sent 'enabled' — see set_dsp). A plain EQ/preset
        # switch while already on leaves squeezelite's args identical, so
        # skip the restart: it would otherwise drop squeezelite's connection
        # to Lyrion and interrupt whatever's currently playing for no reason
        # — only CamillaDSP needs to reload to pick up the new EQ.
        if new_args != re.sub(r'\s+', ' ', args).strip():
            _write_sq_args(new_args)
            # squeezelite must release the real DAC (by restarting onto the
            # loopback) BEFORE CamillaDSP tries to open that same hw: device —
            # otherwise the two processes fight over an exclusive-access
            # device and CamillaDSP's open can fail or wedge the DAC until a
            # reboot. Same reasoning as _apply_dsp_off(), just mirrored:
            # release the old holder before starting the new one.
            _restart_squeezelite_if_enabled()
    # `enable --now` is a no-op on an already-running unit — it would NOT pick
    # up the config.yml we just wrote (CamillaDSP only reads it at startup, no
    # hot reload). Enable separately for boot persistence, then always
    # restart so a preset/EQ change while DSP is already on actually takes
    # effect instead of silently no-op'ing.
    subprocess.run(['sudo', 'systemctl', 'enable', DSP_UNIT],
                   capture_output=True, text=True, timeout=30)
    _run(['systemctl', 'restart', DSP_UNIT], timeout=30)

def _apply_dsp_off():
    # See _apply_dsp_on's matching comment: pause around the restart so an
    # actively-streaming device is never yanked out from under a live
    # transfer.
    playing_player, elapsed = _local_playing_player()
    if playing_player:
        _lms_pause(playing_player)
    try:
        dac = _read_dsp_target()
        _, args = _read_sq_args()
        if args is not None:
            args = _sq_set_o(args, dac or 'default')
            args = _sq_ensure_D(args)                 # restore DoP/DSD
            args = re.sub(r'\s*-r\s+\S+', '', args)    # drop the forced rate
            args = _sq_remove_flag(args, '-R')         # drop resampling
            _write_sq_args(re.sub(r'\s+', ' ', args).strip())
        subprocess.run(['sudo', 'systemctl', 'disable', '--now', DSP_UNIT],
                       capture_output=True, text=True, timeout=30)
        _restart_squeezelite_if_enabled()
    finally:
        if playing_player:
            _lms_resume(playing_player, elapsed)

def get_dsp_status():
    st = _read_dsp_state()
    active = False
    try:
        ac = subprocess.run(['systemctl', 'is-active', DSP_UNIT],
                           capture_output=True, text=True, timeout=10)
        active = ac.stdout.strip() == 'active'
    except Exception:
        pass
    fir_path, _ = _fir_current()
    return {'available': _dsp_available(), 'enabled': st['enabled'], 'active': active,
            'bands': st['bands'], 'crossfeed': st['crossfeed'], 'rate': DSP_RATE,
            'room_correction': st['room_correction'], 'fir_present': bool(fir_path),
            'balance': st['balance'], 'preset': st['preset']}

def set_dsp(config):
    """Apply/persist DSP settings. Any key ABSENT from `config` keeps its
    previously stored value (merge semantics) — this protects fields an
    older UI/companion build never sends (e.g. 'balance') from being wiped
    by a client that only knows about the older keys."""
    if not _dsp_available():
        return {'success': False, 'available': False,
                'code': 'dsp.unavailable', 'message': _t('dsp.unavailable', _lang())}
    st = _read_dsp_state()
    enabled = bool(config['enabled']) if 'enabled' in config else st['enabled']
    crossfeed = bool(config['crossfeed']) if 'crossfeed' in config else st['crossfeed']
    room_correction = bool(config['room_correction']) if 'room_correction' in config else st['room_correction']
    bands = _clean_bands(config['bands']) if 'bands' in config else st['bands']
    balance = _clean_balance(config['balance']) if 'balance' in config else st['balance']
    # Any explicit tone/level edit (vs. e.g. just an enabled toggle) clears
    # the active-preset name unless the caller names one itself (preset
    # load/save pass 'preset' explicitly).
    preset = st['preset']
    if 'preset' in config:
        preset = config.get('preset') or None
    elif any(k in config for k in ('bands', 'crossfeed', 'room_correction', 'balance')):
        preset = None
    try:
        with _dsp_apply_lock:
            if enabled:
                dac = _current_real_dac()
                if not dac or 'Loopback' in dac:
                    dac = 'default'
                _apply_dsp_on(dac, bands, crossfeed, room_correction, balance)
            else:
                _apply_dsp_off()
            _write_dsp_state({'enabled': enabled, 'bands': bands, 'crossfeed': crossfeed,
                              'room_correction': room_correction, 'balance': balance,
                              'preset': preset})
    except Exception:
        log.exception('set_dsp failed')
        return {'success': False, 'code': 'dsp.opFailed', 'message': _t('dsp.opFailed', _lang())}
    return {'success': True, 'enabled': enabled, 'bands': bands, 'crossfeed': crossfeed,
            'room_correction': room_correction, 'balance': balance, 'preset': preset,
            'message': _t('dsp.enabled' if enabled else 'dsp.disabled', _lang())}

# ── DSP presets (named snapshots of bands/crossfeed/room_correction/balance) ──

def _read_dsp_presets():
    try:
        with open(DSP_PRESETS_FILE) as f:
            d = json.load(f)
        presets = d.get('presets') or {}
        return presets if isinstance(presets, dict) else {}
    except Exception:
        return {}

def _write_dsp_presets(presets):
    os.makedirs(os.path.dirname(DSP_PRESETS_FILE), exist_ok=True)
    tmp = DSP_PRESETS_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump({'version': 1, 'presets': presets}, f, indent=2)
    os.replace(tmp, DSP_PRESETS_FILE)

def _dsp_preset_public(name, p, builtin, active_name):
    return {'name': name, 'builtin': builtin, 'active': name == active_name,
            'bands': p.get('bands') or [], 'crossfeed': bool(p.get('crossfeed')),
            'room_correction': bool(p.get('room_correction')),
            'balance': _clean_balance(p.get('balance') or 0.0)}

def _valid_preset_name(name):
    name = (name or '').strip()
    if not name or len(name) > 40:
        return None
    if name.lower() in (k.lower() for k in DSP_BUILTIN_PRESETS):
        return None
    return name

def get_dsp_presets():
    st = _read_dsp_state()
    user = _read_dsp_presets()
    out = [_dsp_preset_public(n, p, True, st['preset']) for n, p in DSP_BUILTIN_PRESETS.items()]
    out += [_dsp_preset_public(n, p, False, st['preset']) for n, p in sorted(user.items())]
    return {'presets': out, 'active': st['preset']}

def save_dsp_preset(name):
    clean_name = _valid_preset_name(name)
    if not clean_name:
        return {'success': False, 'code': 'dspPreset.invalidName',
                'message': _t('dspPreset.invalidName', _lang())}
    user = _read_dsp_presets()
    if clean_name not in user and len(user) >= DSP_MAX_USER_PRESETS:
        return {'success': False, 'code': 'dspPreset.maxReached',
                'message': _t('dspPreset.maxReached', _lang())}
    st = _read_dsp_state()
    user[clean_name] = {'bands': st['bands'], 'crossfeed': st['crossfeed'],
                        'room_correction': st['room_correction'], 'balance': st['balance']}
    try:
        _write_dsp_presets(user)
        _write_dsp_state({**st, 'preset': clean_name})
    except Exception:
        log.exception('save_dsp_preset failed')
        return {'success': False, 'code': 'dspPreset.saveFailed',
                'message': _t('dspPreset.saveFailed', _lang())}
    return {'success': True, **get_dsp_presets(), 'message': _t('dspPreset.saved', _lang())}

def load_dsp_preset(name):
    name = (name or '').strip()
    p = DSP_BUILTIN_PRESETS.get(name) or _read_dsp_presets().get(name)
    if not p:
        return {'success': False, 'code': 'dspPreset.notFound',
                'message': _t('dspPreset.notFound', _lang())}
    # Bands + balance + crossfeed only — 'room_correction' and 'enabled' are
    # deliberately preserved (they depend on a physically-uploaded FIR filter
    # and on the bit-perfect on/off choice, not on the tonal preset).
    result = set_dsp({'bands': p.get('bands') or [], 'balance': p.get('balance') or 0.0,
                      'crossfeed': bool(p.get('crossfeed')), 'preset': name})
    if result.get('success'):
        result['message'] = _t('dspPreset.loaded', _lang())
    return result

def rename_dsp_preset(name, new_name):
    user = _read_dsp_presets()
    if name not in user:
        return {'success': False, 'code': 'dspPreset.notFound',
                'message': _t('dspPreset.notFound', _lang())}
    clean_new = _valid_preset_name(new_name)
    if not clean_new:
        return {'success': False, 'code': 'dspPreset.invalidName',
                'message': _t('dspPreset.invalidName', _lang())}
    if clean_new in user and clean_new != name:
        return {'success': False, 'code': 'dspPreset.nameExists',
                'message': _t('dspPreset.nameExists', _lang())}
    user[clean_new] = user.pop(name)
    try:
        _write_dsp_presets(user)
        st = _read_dsp_state()
        if st['preset'] == name:
            _write_dsp_state({**st, 'preset': clean_new})
    except Exception:
        log.exception('rename_dsp_preset failed')
        return {'success': False, 'code': 'dspPreset.renameFailed',
                'message': _t('dspPreset.renameFailed', _lang())}
    return {'success': True, **get_dsp_presets(), 'message': _t('dspPreset.renamed', _lang())}

def delete_dsp_preset(name):
    user = _read_dsp_presets()
    if name not in user:
        return {'success': False, 'code': 'dspPreset.notFound',
                'message': _t('dspPreset.notFound', _lang())}
    del user[name]
    try:
        _write_dsp_presets(user)
        st = _read_dsp_state()
        if st['preset'] == name:
            _write_dsp_state({**st, 'preset': None})
    except Exception:
        log.exception('delete_dsp_preset failed')
        return {'success': False, 'code': 'dspPreset.deleteFailed',
                'message': _t('dspPreset.deleteFailed', _lang())}
    return {'success': True, **get_dsp_presets(), 'message': _t('dspPreset.deleted', _lang())}

# ──────────────────────────────────────────────────────────────────
#  Bluetooth audio (A2DP sink) — OPTIONAL, OFF by default. Lets the
#  appliance appear as a Bluetooth speaker: a phone connects and streams
#  straight to the DAC, no app/account needed (guest-friendly input, the
#  same idea as Volumio/WiiM/Bluesound/Eversolo). See OS migration
#  0024-bluetooth.sh for the systemd units/prerequisites, and
#  distro/config/includes.chroot/usr/local/sbin/hifi-bt-{aplay-run,
#  watcher.py} (delivered by the system OTA channel) for the runtime DAC
#  handover + Now Playing metadata.
#
#  Concurrency with squeezelite/CamillaDSP: Bluetooth "wins". When a phone
#  starts actively streaming, hifi-bt-watcher.py pauses the local Lyrion
#  player (and stops CamillaDSP if it was running, same release-before-open
#  ordering as the DSP toggle above) so the real DAC is free, then restarts
#  hifi-bt-aplay.service to open it. That handover reacts to live BlueZ
#  D-Bus signals from the watcher daemon; this section only turns the whole
#  subsystem on/off, reports status, and — since Bluetooth carries no cover
#  art worth trusting (BlueZ's AVRCP art support is unreliable) — resolves
#  one from an online lookup for the UI's Now Playing overlay.
# ──────────────────────────────────────────────────────────────────
BT_UNITS = ('bluetooth.service', 'hifi-bluealsa.service', 'hifi-bt-agent.service',
            'hifi-bt-aplay.service', 'hifi-bt-watcher.service')
BT_STATE_FILE = '/etc/hifi-player/bluetooth.json'
BT_NOW_PLAYING_FILE = '/run/hifi-bt/now-playing.json'
BT_CAMILLA_STOPPED_FLAG = '/run/hifi-bt/camilla-stopped'
BT_APLAY_SCRIPT = '/usr/local/sbin/hifi-bt-aplay-run'
_BT_MAC_RE = re.compile(r'^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$')
_bt_apply_lock = threading.Lock()

def _bt_available():
    return (_unit_exists('hifi-bluealsa.service')
            and shutil.which('bluetoothctl') is not None
            and os.path.exists(BT_APLAY_SCRIPT))

def _read_bt_state():
    try:
        with open(BT_STATE_FILE) as f:
            return bool(json.load(f).get('enabled'))
    except Exception:
        return False

def _write_bt_state(enabled):
    os.makedirs(os.path.dirname(BT_STATE_FILE), exist_ok=True)
    tmp = BT_STATE_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump({'enabled': bool(enabled)}, f)
    os.replace(tmp, BT_STATE_FILE)

def _bt_paired_devices():
    """[{mac, name, connected}], best-effort — empty on any failure so a
    flaky bluetoothctl call never breaks the whole status response."""
    devices = []
    try:
        r = subprocess.run(['bluetoothctl', 'devices', 'Paired'],
                           capture_output=True, text=True, timeout=10)
        lines = (r.stdout or '').splitlines()
        if r.returncode != 0 or not lines:
            # Older bluez CLIs don't support the "Paired" filter argument.
            r = subprocess.run(['bluetoothctl', 'paired-devices'],
                               capture_output=True, text=True, timeout=10)
            lines = (r.stdout or '').splitlines()
        for line in lines:
            m = re.match(r'Device\s+([0-9A-Fa-f:]{17})\s+(.*)', line.strip())
            if not m:
                continue
            mac, name = m.group(1), m.group(2)
            info = subprocess.run(['bluetoothctl', 'info', mac],
                                  capture_output=True, text=True, timeout=10)
            devices.append({'mac': mac, 'name': name,
                            'connected': 'Connected: yes' in (info.stdout or '')})
    except Exception:
        log.exception("_bt_paired_devices failed")
    return devices

def get_bluetooth_status():
    try:
        ac = subprocess.run(['systemctl', 'is-active', 'bluetooth.service'],
                           capture_output=True, text=True, timeout=10)
        active = ac.stdout.strip() == 'active'
        discoverable = False
        if active:
            show = subprocess.run(['bluetoothctl', 'show'],
                                  capture_output=True, text=True, timeout=10)
            discoverable = 'Discoverable: yes' in (show.stdout or '')
        return {'available': _bt_available(), 'enabled': _read_bt_state(), 'active': active,
                'discoverable': discoverable, 'devices': _bt_paired_devices() if active else []}
    except Exception:
        log.exception("get_bluetooth_status failed")
        return {'available': False, 'enabled': False, 'active': False, 'discoverable': False,
                'devices': [], 'error': _t('bluetooth.statusUnavailable', _lang())}

def set_bluetooth(enable):
    """Enable or disable the whole Bluetooth subsystem (persists). Serialized
    so an enable/disable double-click can't interleave with itself."""
    if enable and not _bt_available():
        return {'success': False, 'available': False, 'enabled': False, 'active': False,
                'discoverable': False, 'devices': [],
                'code': 'bluetooth.unavailableUpdate', 'message': _t('bluetooth.unavailableUpdate', _lang())}
    with _bt_apply_lock:
        _write_bt_state(enable)
        try:
            if enable:
                subprocess.run(['modprobe', 'btusb'], capture_output=True, timeout=15)
                subprocess.run(['modprobe', 'bluetooth'], capture_output=True, timeout=15)
                subprocess.run(['sudo', 'systemctl', 'unmask', 'bluetooth.service'],
                               capture_output=True, text=True, timeout=15)
                for unit in BT_UNITS:
                    r = subprocess.run(['sudo', 'systemctl', 'enable', '--now', unit],
                                       capture_output=True, text=True, timeout=30)
                    if r.returncode != 0:
                        log.error("set_bluetooth enable %s failed: %s", unit, (r.stderr or '').strip())
                # hifi-bt-watcher.py sets power/pairable/alias once the adapter
                # comes up — give it a moment before the UI's first status poll.
                for _ in range(10):
                    r = subprocess.run(['bluetoothctl', 'list'],
                                       capture_output=True, text=True, timeout=5)
                    if (r.stdout or '').strip():
                        break
                    time.sleep(1)
            else:
                for unit in reversed(BT_UNITS):
                    subprocess.run(['sudo', 'systemctl', 'disable', '--now', unit],
                                   capture_output=True, text=True, timeout=30)
                subprocess.run(['sudo', 'systemctl', 'mask', 'bluetooth.service'],
                               capture_output=True, text=True, timeout=15)
                # Never leave DSP off just because Bluetooth is being turned off.
                if os.path.exists(BT_CAMILLA_STOPPED_FLAG):
                    _run(['systemctl', 'start', DSP_UNIT], timeout=30)
                    try:
                        os.remove(BT_CAMILLA_STOPPED_FLAG)
                    except OSError:
                        pass
                subprocess.run(['modprobe', '-r', 'btusb'], capture_output=True, timeout=15)
        except Exception:
            log.exception("set_bluetooth failed")
            status = get_bluetooth_status()
            status['success'] = False
            status['code'] = 'bluetooth.opFailed'
            status['message'] = _t('bluetooth.opFailed', _lang())
            return status
    status = get_bluetooth_status()
    status['success'] = True
    status['message'] = _t('bluetooth.enabled' if enable else 'bluetooth.disabled', _lang())
    return status

def set_bt_discoverable():
    if not _bt_available():
        return {'success': False, 'code': 'bluetooth.unavailable',
                'message': _t('bluetooth.unavailable', _lang())}
    try:
        subprocess.run(['bluetoothctl', 'discoverable-timeout', '120'],
                       capture_output=True, text=True, timeout=10)
        r = subprocess.run(['bluetoothctl', 'discoverable', 'on'],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return {'success': False, 'code': 'bluetooth.cannotMakeVisible',
                    'message': _t('bluetooth.cannotMakeVisible', _lang())}
    except Exception:
        log.exception("set_bt_discoverable failed")
        return {'success': False, 'code': 'bluetooth.cannotMakeVisible',
                'message': _t('bluetooth.cannotMakeVisible', _lang())}
    return {'success': True, 'seconds': 120, 'message': _t('bluetooth.visibleFor2Min', _lang())}

def bt_forget(mac):
    """Unpair/remove a device. MAC comes straight from a network request, so
    it's validated against a strict address pattern before ever reaching a
    shell-adjacent subprocess argument."""
    if not mac or not _BT_MAC_RE.match(mac):
        return {'success': False, 'code': 'bluetooth.invalidAddress',
                'message': _t('bluetooth.invalidAddress', _lang())}
    try:
        r = subprocess.run(['bluetoothctl', 'remove', mac],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return {'success': False, 'code': 'bluetooth.deviceNotFound',
                    'message': _t('bluetooth.deviceNotFound', _lang())}
    except Exception:
        log.exception("bt_forget failed")
        return {'success': False, 'code': 'bluetooth.forgetFailed',
                'message': _t('bluetooth.forgetFailed', _lang())}
    return {'success': True, 'devices': _bt_paired_devices(), 'message': _t('bluetooth.forgotten', _lang())}

# Cover art never arrives over Bluetooth (AVRCP art support in BlueZ is
# experimental/unreliable, and cars/phones mostly rely on their own
# proprietary stacks for it) — best-effort online lookup by title+artist
# instead. Tiny in-memory cache so repeated Now Playing polls during the
# same track don't refetch; capped so a long BT listening session (many
# different tracks) can't grow it unbounded.
_bt_cover_cache = {}
_BT_COVER_CACHE_MAX = 200

def _bt_cover_lookup(title, artist, album):
    key = (title or '', artist or '', album or '')
    if key == ('', '', ''):
        return None
    if key in _bt_cover_cache:
        return _bt_cover_cache[key]
    cover = None
    try:
        term = urllib.parse.quote(f'{artist} {title}'.strip())
        url = f'https://itunes.apple.com/search?term={term}&media=music&entity=song&limit=1'
        req = urllib.request.Request(url, headers={'User-Agent': 'OsmiumSound/1.0'})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        results = data.get('results') or []
        if results:
            # ...100x100bb.jpg -> a larger cover; still tiny/fast over LAN.
            art = results[0].get('artworkUrl100')
            if art:
                cover = art.replace('100x100bb', '600x600bb')
    except Exception:
        cover = None  # offline / no match / rate-limited — fine, just no art
    if len(_bt_cover_cache) >= _BT_COVER_CACHE_MAX:
        _bt_cover_cache.clear()
    _bt_cover_cache[key] = cover
    return cover

def get_bluetooth_now_playing():
    try:
        with open(BT_NOW_PLAYING_FILE) as f:
            np = json.load(f)
    except Exception:
        np = {}
    if not np.get('active'):
        return {'active': False}
    np['cover_url'] = _bt_cover_lookup(np.get('title'), np.get('artist'), np.get('album'))
    return np

# ──────────────────────────────────────────────────────────────────
#  OTA update helpers
# ──────────────────────────────────────────────────────────────────

def _installed_ui_version():
    try:
        with open(OTA_VERSION_FILE) as f:
            return f.read().strip() or 'unknown'
    except Exception:
        return 'unknown'

def _version_tuple(v):
    """Best-effort numeric tuple from a version like 'v1.2.0' → (1, 2, 0)."""
    nums = re.findall(r'\d+', v or '')
    return tuple(int(n) for n in nums) if nums else None

_ALPHA_TAG_RE = re.compile(r'-alpha\d+$')

def _semver_key(v):
    """Sort key honouring prereleases: '2.5.7-dev.1' ranks BELOW '2.5.7' but
    above '2.5.6', so switching dev→prod still upgrades to the stable build.

    A trailing '-alphaN' (e.g. '2.5.21-dev.52-alpha3') ranks BELOW the plain
    'dev.52' it's nested on, same idea one level down: naively including the
    alpha digits in the prerelease tuple made '(52, 3) > (52,)', so a device
    already on an alpha build considered the promoted plain dev.N *older* and
    never offered it. alpha1 < alpha2 < ... < dev.N (plain).

    Debian's '~' separator means the same thing and is what the Lyrion nightly
    builds use ('9.1.2~1781881406' precedes the 9.1.2 release), so treat the two
    separators alike — whichever comes first wins."""
    raw = (v or '').lstrip('vV')
    alpha_match = _ALPHA_TAG_RE.search(raw)
    if alpha_match:
        alpha_rank = (0, int(re.search(r'\d+', alpha_match.group()).group()))
        raw = raw[:alpha_match.start()]
    else:
        alpha_rank = (1,)  # not an alpha build: ranks above any alpha of the same base
    sep = min((raw.index(c) for c in '-~' if c in raw), default=-1)
    base, pre = (raw, '') if sep < 0 else (raw[:sep], raw[sep + 1:])
    base_nums = tuple(int(n) for n in re.findall(r'\d+', base)) or (0,)
    if pre:  # prerelease: lower than the release with the same base
        return (base_nums, 0, tuple(int(n) for n in re.findall(r'\d+', pre)) or (0,), alpha_rank)
    return (base_nums, 1, (), alpha_rank)  # final release: above any prerelease of same base

def _is_newer(latest, current):
    """True if `latest` should be offered over `current`."""
    if not latest:
        return False
    if current in (None, '', 'unknown'):
        return True
    return _semver_key(latest) > _semver_key(current)

def _read_version_file(path):
    try:
        with open(path) as f:
            return f.read().strip() or 'unknown'
    except Exception:
        return 'unknown'

def _alpha_unlocked():
    return os.path.exists(OTA_ALPHA_MARKER_FILE)

def get_ota_channel():
    """Return the persisted OTA channel ('prod', 'dev' or 'alpha'). Defaults to
    the HIFI_OTA_CHANNEL env var, else 'prod'. Falls back to 'prod' if the
    resolved channel is 'alpha' but the marker file has since been removed, so
    a device doesn't keep chasing alpha releases after being locked back out."""
    try:
        with open(OTA_CHANNEL_FILE) as f:
            ch = f.read().strip()
        if ch in OTA_CHANNELS and (ch != 'alpha' or _alpha_unlocked()):
            return ch
    except Exception:
        pass
    env = os.environ.get('HIFI_OTA_CHANNEL', 'prod')
    if env in OTA_CHANNELS and (env != 'alpha' or _alpha_unlocked()):
        return env
    return 'prod'

def set_ota_channel(channel):
    if channel not in OTA_CHANNELS or (channel == 'alpha' and not _alpha_unlocked()):
        return {'success': False, 'code': 'ota.invalidChannel',
                'message': _t('ota.invalidChannel', _lang()), 'channel': get_ota_channel()}
    try:
        os.makedirs(os.path.dirname(OTA_CHANNEL_FILE), exist_ok=True)
        tmp = OTA_CHANNEL_FILE + '.tmp'
        with open(tmp, 'w') as f:
            f.write(channel + '\n')
        os.replace(tmp, OTA_CHANNEL_FILE)
    except Exception:
        log.exception("set_ota_channel failed")
        return {'success': False, 'code': 'ota.channelSaveFailed',
                'message': _t('ota.channelSaveFailed', _lang()), 'channel': get_ota_channel()}
    return {'success': True, 'channel': channel}

# Short-lived cache of the GitHub Release per channel. A single "check updates"
# resolves three asset prefixes (UI + System + OS), each of which used to make
# its own GitHub API request for the *same* release — 3x the calls against the
# unauthenticated 60-req/hour limit, which is why checks intermittently failed
# and the version display fell back to "n/a". Caching collapses those into one
# request and lets repeated checks reuse the result.
_RELEASE_CACHE = {}        # channel -> (fetched_at, release_dict)
_RELEASE_CACHE_TTL = 60    # seconds
# The server now runs threaded (app.run(threaded=True)), so a single "check
# updates" — which calls _fetch_release 3× concurrently for UI/system/OS — can
# race on this dict. Serialise access; the cache makes all but the first call
# cheap anyway.
_RELEASE_CACHE_LOCK = threading.Lock()

def _fetch_pages_manifest(channel):
    """Read the channel's static manifest from GitHub Pages. Returns a release-
    shaped dict ({tag_name, assets:[…]}) or None if unavailable/empty."""
    url = f'{OTA_MANIFEST_BASE}/latest-{channel}.json'
    req = urllib.request.Request(url, headers={'User-Agent': 'hifi-player-ota'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        release = json.load(resp)
    return release if release.get('tag_name') else None

def _fetch_github_api_release(channel):
    """Fallback: query the (rate-limited) GitHub REST API.
    prod → newest stable; dev → newest release incl. prereleases, EXCLUDING
    alpha-tagged ones; alpha → newest release of any kind (incl. alpha tags).

    The repo also hosts the Android companion app's releases (tags
    "companion-v*", APK-only assets) — those must never be offered to the
    appliance, so both channels list releases and filter them out. That's
    also why prod can't just use /releases/latest: a stable companion
    release can claim "latest" (belt-and-braces with the workflow-side
    make_latest: false) and it can't be filtered from that endpoint."""
    url = f'https://api.github.com/repos/{OTA_REPO}/releases?per_page=30'
    req = urllib.request.Request(url, headers={
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'hifi-player-ota',
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.load(resp)
    # GitHub lists releases newest-first; skip drafts and companion releases.
    rels = [rel for rel in data if not rel.get('draft')
            and not str(rel.get('tag_name', '')).startswith('companion-')]
    if channel == 'alpha':
        return next(iter(rels), {})
    if channel == 'dev':
        return next((rel for rel in rels
                      if not _ALPHA_TAG_RE.search(str(rel.get('tag_name', '')))), {})
    return next((rel for rel in rels if not rel.get('prerelease')), {})

def _fetch_release(channel):
    """Fetch the release to offer for the given channel.

    Source order: the static GitHub Pages manifest (a CDN, not rate-limited) is
    tried first; only if it's unreachable do we fall back to the GitHub REST API
    (60 req/hour/IP unauthenticated). Result is cached briefly, and on a total
    fetch failure the last good release is reused so a momentary blip doesn't
    surface as an error."""
    with _RELEASE_CACHE_LOCK:
        now = time.time()
        cached = _RELEASE_CACHE.get(channel)
        if cached and now - cached[0] < _RELEASE_CACHE_TTL:
            return cached[1]

        # 1. Preferred: static manifest on Pages.
        try:
            release = _fetch_pages_manifest(channel)
            if release:
                _RELEASE_CACHE[channel] = (now, release)
                return release
            log.warning("Pages manifest for channel %s empty; falling back to API", channel)
        except Exception:
            log.warning("Pages manifest fetch failed for channel %s; falling back to API", channel)

        # 2. Fallback: the rate-limited GitHub REST API.
        try:
            release = _fetch_github_api_release(channel)
        except Exception:
            # Reuse the last good release (even if past the TTL) rather than failing
            # the whole check on a transient blip / exhausted rate limit.
            if cached:
                log.warning("release fetch failed; serving cached release for channel %s", channel)
                return cached[1]
            raise

        _RELEASE_CACHE[channel] = (now, release)
        return release

def _check_release_update(current, prefix):
    """Look at the relevant GitHub Release and return update info for the asset
    whose name starts with `prefix` (e.g. 'hifi-ui-' or 'hifi-system-')."""
    channel = get_ota_channel()
    try:
        release = _fetch_release(channel)
    except Exception:
        log.exception("update check failed")
        return {'error': _t('update.checkFailed', _lang()), 'current': current, 'channel': channel}

    latest = release.get('tag_name') or release.get('name') or ''
    assets = release.get('assets', [])

    def _named(suffix):
        return next((a for a in assets
                     if a.get('name', '').startswith(prefix)
                     and a.get('name', '').endswith(suffix)), None)

    tarball = _named('.tar.gz')
    sha_asset = _named('.tar.gz.sha256')
    sig_asset = _named('.tar.gz.sha256.sig')

    return {
        'current': current,
        'latest': latest,
        'channel': channel,
        'update_available': _is_newer(latest, current) and tarball is not None,
        'notes': release.get('body', ''),
        'asset_url': tarball.get('browser_download_url') if tarball else None,
        'asset_size': tarball.get('size') if tarball else None,
        'sha_url': sha_asset.get('browser_download_url') if sha_asset else None,
        'sig_url': sig_asset.get('browser_download_url') if sig_asset else None,
    }

def check_app_update():
    return _check_release_update(_installed_ui_version(), OTA_UI_PREFIX)

def _fetch_sha256(sha_url):
    """Download the .sha256 sidecar and return just the hex digest.

    GitHub's release-download host resets the connection outright on a
    noticeable fraction of requests from some networks (observed ~20-25%,
    independent of curl vs urllib and of IPv4/IPv6) — a plain timeout/DNS
    problem it is not. Every curl-based download elsewhere in the OTA scripts
    already rides through that with `--retry 3`; this one-shot fetch had no
    such retry, so with 3 components to check, "Aggiorna tutto" had a good
    chance of tripping over it on at least one of them."""
    req = urllib.request.Request(sha_url, headers={'User-Agent': 'hifi-player-ota'})
    last_exc = None
    for attempt in range(3):
        if attempt:
            time.sleep(1)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                text = resp.read().decode('utf-8', 'replace').strip()
            # format is "<sha>  <filename>"; take the first whitespace-delimited token
            return text.split()[0] if text else ''
        except Exception as e:
            last_exc = e
    raise last_exc

def apply_app_update():
    info = check_app_update()
    if info.get('error'):
        return {'started': False, 'message': info['error']}
    if not info.get('update_available'):
        return {'started': False, 'code': 'update.noneAvailable',
                'message': _t('update.noneAvailable', _lang())}
    if not info.get('sha_url'):
        return {'started': False, 'code': 'update.checksumMissing',
                'message': _t('update.checksumMissing', _lang())}

    try:
        sha = _fetch_sha256(info['sha_url'])
    except Exception:
        log.exception("update: checksum fetch failed")
        return {'started': False, 'code': 'update.checksumReadFailed',
                'message': _t('update.checksumReadFailed', _lang())}
    if not sha:
        return {'started': False, 'code': 'update.checksumEmpty',
                'message': _t('update.checksumEmpty', _lang())}

    cmd = [
        'systemd-run', '--no-block', '--collect', '--unit=hifi-ota',
        OTA_SCRIPT, info['asset_url'], sha, info['latest'],
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=True)
    except FileNotFoundError:
        # systemd-run unavailable → fall back to a detached subprocess
        subprocess.Popen([OTA_SCRIPT, info['asset_url'], sha, info['latest']],
                         start_new_session=True)
    except subprocess.CalledProcessError:
        log.exception("update: apply command failed")
        return {'started': False, 'code': 'update.startFailed',
                'message': _t('update.startFailed', _lang())}
    except Exception:
        log.exception("update: apply failed")
        return {'started': False, 'code': 'update.startFailed',
                'message': _t('update.startFailed', _lang())}
    return {'started': True, 'version': info['latest']}

def app_update_status():
    try:
        with open(OTA_STATUS_FILE) as f:
            return json.load(f)
    except Exception:
        return {'state': 'idle'}

# ──────────────────────────────────────────────────────────────────
#  OTA update of the custom system components
# ──────────────────────────────────────────────────────────────────
def _installed_system_version():
    return _read_version_file(SYS_VERSION_FILE)

def check_system_update():
    return _check_release_update(_installed_system_version(), SYS_PREFIX)

def apply_system_update():
    info = check_system_update()
    if info.get('error'):
        return {'started': False, 'message': info['error']}
    if not info.get('update_available'):
        return {'started': False, 'code': 'update.noneAvailable',
                'message': _t('update.noneAvailable', _lang())}
    if not info.get('sha_url'):
        return {'started': False, 'code': 'update.checksumMissing',
                'message': _t('update.checksumMissing', _lang())}

    try:
        sha = _fetch_sha256(info['sha_url'])
    except Exception:
        log.exception("update: checksum fetch failed")
        return {'started': False, 'code': 'update.checksumReadFailed',
                'message': _t('update.checksumReadFailed', _lang())}
    if not sha:
        return {'started': False, 'code': 'update.checksumEmpty',
                'message': _t('update.checksumEmpty', _lang())}

    cmd = [
        'systemd-run', '--no-block', '--collect', '--unit=hifi-system-update',
        SYS_SCRIPT, info['asset_url'], sha, info['latest'],
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=True)
    except FileNotFoundError:
        # systemd-run unavailable → fall back to a detached subprocess
        subprocess.Popen([SYS_SCRIPT, info['asset_url'], sha, info['latest']],
                         start_new_session=True)
    except subprocess.CalledProcessError:
        log.exception("update: apply command failed")
        return {'started': False, 'code': 'update.startFailed',
                'message': _t('update.startFailed', _lang())}
    except Exception:
        log.exception("update: apply failed")
        return {'started': False, 'code': 'update.startFailed',
                'message': _t('update.startFailed', _lang())}
    return {'started': True, 'version': info['latest']}

def system_update_status():
    try:
        with open(SYS_STATUS_FILE) as f:
            return json.load(f)
    except Exception:
        return {'state': 'idle'}

# ──────────────────────────────────────────────────────────────────
#  OTA update of the operating system (signed bundle + apply.sh)
# ──────────────────────────────────────────────────────────────────
def _installed_os_version():
    return _read_version_file(OS_VERSION_FILE)

def check_os_update():
    return _check_release_update(_installed_os_version(), OS_PREFIX)

def apply_os_update():
    info = check_os_update()
    if info.get('error'):
        return {'started': False, 'message': info['error']}
    if not info.get('update_available'):
        return {'started': False, 'code': 'update.noneAvailableOs',
                'message': _t('update.noneAvailableOs', _lang())}
    if not info.get('sha_url'):
        return {'started': False, 'code': 'update.checksumMissing',
                'message': _t('update.checksumMissing', _lang())}
    # The OS bundle runs root scripts, so a valid signature is mandatory.
    if not info.get('sig_url'):
        return {'started': False, 'code': 'update.sigMissing',
                'message': _t('update.sigMissing', _lang())}

    try:
        sha = _fetch_sha256(info['sha_url'])
    except Exception:
        log.exception("update: checksum fetch failed")
        return {'started': False, 'code': 'update.checksumReadFailed',
                'message': _t('update.checksumReadFailed', _lang())}
    if not sha:
        return {'started': False, 'code': 'update.checksumEmpty',
                'message': _t('update.checksumEmpty', _lang())}

    cmd = [
        'systemd-run', '--no-block', '--collect', '--unit=hifi-os-update',
        OS_SCRIPT, info['asset_url'], sha, info['sig_url'], info['latest'],
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=True)
    except FileNotFoundError:
        # systemd-run unavailable → fall back to a detached subprocess
        subprocess.Popen([OS_SCRIPT, info['asset_url'], sha, info['sig_url'], info['latest']],
                         start_new_session=True)
    except subprocess.CalledProcessError:
        log.exception("update: apply command failed")
        return {'started': False, 'code': 'update.startFailed',
                'message': _t('update.startFailed', _lang())}
    except Exception:
        log.exception("update: apply failed")
        return {'started': False, 'code': 'update.startFailed',
                'message': _t('update.startFailed', _lang())}
    return {'started': True, 'version': info['latest']}

def os_update_status():
    try:
        with open(OS_STATUS_FILE) as f:
            return json.load(f)
    except Exception:
        return {'state': 'idle'}

# ──────────────────────────────────────────────────────────────────
#  Installer: boot-mode detection + disk-to-disk installation
# ──────────────────────────────────────────────────────────────────
def get_boot_mode():
    """Read from /proc/cmdline whether this live session was booted from the
    'Install Osmium Sound' menu entry (hifi.installer=1) or the plain 'Try'
    entry. The Electron app (src/App.jsx) uses this to decide whether to show
    InstallWizard or the normal kiosk UI."""
    try:
        with open('/proc/cmdline') as f:
            cmdline = f.read()
    except Exception:
        cmdline = ''
    mode = 'installer' if 'hifi.installer=1' in cmdline.split() else 'live'
    return {'mode': mode}

def _boot_medium_disk():
    """Resolve the physical disk backing the live boot medium itself, so it
    can be excluded from the installer's disk picker (hifi-disk-install.sh
    refuses it independently too, as a second line of defense)."""
    for mp in ('/run/live/medium', '/lib/live/mount/medium'):
        try:
            r = _run(['findmnt', '-no', 'SOURCE', mp], timeout=5)
        except Exception:
            continue
        src = (r.stdout or '').strip()
        if not src:
            continue
        try:
            pr = _run(['lsblk', '-no', 'PKNAME', src], timeout=5)
            pk = (pr.stdout or '').strip().split()
            if pk:
                return '/dev/' + pk[0]
        except Exception:
            pass
    return None

def list_install_disks():
    medium_disk = _boot_medium_disk()
    try:
        r = _run(['lsblk', '-J', '-b', '-o', 'PATH,TYPE,SIZE,MODEL,TRAN,ROTA'], timeout=10)
        data = json.loads(r.stdout or '{}')
    except Exception:
        log.exception("install: disk enumeration failed")
        return {'success': False, 'code': 'install.enumFailed',
                'message': _t('install.enumFailed', _lang()), 'disks': []}
    disks = []
    for dev in data.get('blockdevices', []):
        if dev.get('type') != 'disk':
            continue
        path = dev.get('path')
        if not path or path == medium_disk:
            continue
        disks.append({
            'path': path,
            'size': dev.get('size'),
            'model': (dev.get('model') or '').strip(),
            'transport': dev.get('tran'),
            'rotational': bool(dev.get('rota')),
        })
    return {'success': True, 'disks': disks}

def start_disk_install(device):
    if not device or not isinstance(device, str) or not re.match(r'^/dev/[A-Za-z0-9/_]+$', device):
        return {'success': False, 'code': 'install.invalidDisk',
                'message': _t('install.invalidDisk', _lang())}
    medium_disk = _boot_medium_disk()
    if medium_disk and device == medium_disk:
        return {'success': False, 'code': 'install.cannotInstallOnBootMedia',
                'message': _t('install.cannotInstallOnBootMedia', _lang())}

    with open(INSTALL_STATUS_FILE, 'w') as f:
        json.dump({'state': 'running', 'progress': 0, 'message': _t('common.starting', _lang())}, f)

    cmd = ['systemd-run', '--no-block', '--collect', '--unit=hifi-disk-install',
           INSTALL_SCRIPT, device]
    try:
        r = _run(cmd, timeout=15)
        launch_err = None if r.returncode == 0 else (r.stderr or r.stdout or '').strip()
    except Exception:
        log.exception("install: failed to launch")
        launch_err = _t('install.systemdRunNoResponse', _lang())
    if launch_err:
        with open(INSTALL_STATUS_FILE, 'w') as f:
            json.dump({'state': 'error', 'progress': 0, 'message': launch_err}, f)
        return {'success': False, 'message': launch_err}
    return {'success': True}

def disk_install_status():
    try:
        with open(INSTALL_STATUS_FILE) as f:
            return json.load(f)
    except Exception:
        return {'state': 'idle', 'progress': 0, 'message': ''}

# ──────────────────────────────────────────────────────────────────
#  Multi-component update sequencer (see the constants block above)
# ──────────────────────────────────────────────────────────────────
_UPDATE_PLAN_LOCK = threading.Lock()

# Per-kind wiring: how to check it, where its live status is written, and how
# to read the version actually installed right now.
_PLAN_KINDS = {
    'system': (lambda: check_system_update(), SYS_STATUS_FILE, lambda: _installed_system_version()),
    'os':     (lambda: check_os_update(),     OS_STATUS_FILE,  lambda: _installed_os_version()),
    'ui':     (lambda: check_app_update(),    OTA_STATUS_FILE, lambda: _installed_ui_version()),
}

def _read_update_plan():
    """Parse the persisted plan, or None when there isn't one."""
    try:
        with open(UPDATE_PLAN_FILE) as f:
            lines = f.read().splitlines()
    except Exception:
        return None

    plan = {'plan_id': '', 'channel': '', 'created': 0, 'steps': [],
            'finished': None, 'overall': None}
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        if parts[0] == 'plan' and len(parts) >= 4:
            plan['plan_id'] = parts[1]
            plan['channel'] = parts[2]
            try:
                plan['created'] = int(parts[3])
            except ValueError:
                pass
        elif parts[0] == 'step' and len(parts) >= 8:
            try:
                attempts = int(parts[3])
            except ValueError:
                attempts = 0
            plan['steps'].append({
                'kind': parts[1], 'state': parts[2], 'attempts': attempts,
                'version': parts[4], 'url': parts[5], 'sha': parts[6],
                'sig': None if parts[7] == '-' else parts[7],
            })
        elif parts[0] == 'finished' and len(parts) >= 3:
            try:
                plan['finished'] = int(parts[1])
            except ValueError:
                plan['finished'] = 0
            plan['overall'] = parts[2]
    return plan if plan['steps'] else None

def _write_update_plan(plan):
    """Serialise the plan atomically (tmp + os.replace) — it is the only record
    of what is still pending, and it has to survive a power cut mid-write."""
    lines = ['v 1',
             'plan %s %s %d' % (plan['plan_id'], plan['channel'], plan['created'])]
    for s in plan['steps']:
        lines.append('step %s %s %d %s %s %s %s' % (
            s['kind'], s['state'], s.get('attempts', 0), s['version'],
            s['url'], s['sha'], s['sig'] or '-'))
    os.makedirs(os.path.dirname(UPDATE_PLAN_FILE), exist_ok=True)
    tmp = UPDATE_PLAN_FILE + '.tmp'
    with open(tmp, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    os.chmod(tmp, 0o644)
    os.replace(tmp, UPDATE_PLAN_FILE)

def _clear_update_plan():
    try:
        os.remove(UPDATE_PLAN_FILE)
    except FileNotFoundError:
        pass
    except Exception:
        log.exception("could not remove the update plan")

# Sentinel returned by _plan_step_from_info() to mean "an update IS available
# but the step couldn't be safely built" — distinct from plain None ("nothing
# to do"), so build_update_plan() can surface it as a real error instead of
# silently treating it as if there was no update at all.
_STEP_INVALID = object()

def _plan_step_from_info(kind, info):
    """Turn a check result into a plan step. Returns None when there's nothing
    to do, or _STEP_INVALID when an update exists but the step failed validation.

    Every field is validated here rather than in the runner: the plan file is
    parsed by /bin/sh on whitespace, and the OS step's arguments end up as
    arguments to a root script."""
    if not info or info.get('error') or not info.get('update_available'):
        return None
    version = (info.get('latest') or '').strip()
    url = (info.get('asset_url') or '').strip()
    sha = (info.get('sha_url') or '').strip()
    sig = (info.get('sig_url') or '').strip()
    if not _SAFE_VERSION_RE.match(version):
        log.warning("update plan: refusing %s, unsafe version %r", kind, version)
        return _STEP_INVALID
    if not url.startswith('https://') or not sha.startswith('https://'):
        log.warning("update plan: refusing %s, non-TLS asset URL", kind)
        return _STEP_INVALID
    # The OS bundle runs root code from its payload, so its signature is not
    # optional — mirrors apply_os_update().
    if kind == 'os' and not sig.startswith('https://'):
        log.warning("update plan: refusing os step, missing signature")
        return _STEP_INVALID
    try:
        digest = _fetch_sha256(sha)
    except Exception:
        log.exception("update plan: checksum fetch failed for %s", kind)
        return _STEP_INVALID
    if not _SAFE_SHA_RE.match(digest or ''):
        log.warning("update plan: refusing %s, malformed checksum", kind)
        return _STEP_INVALID
    if any(c.isspace() for c in url + sig):
        return _STEP_INVALID
    return {'kind': kind, 'state': 'pending', 'attempts': 0, 'version': version,
            'url': url, 'sha': digest, 'sig': sig or None}

def build_update_plan():
    """Check all three components and return the steps that need applying, in
    canonical order. One release fetch serves all three (60s cache)."""
    steps = []
    errors = []
    for kind in UPDATE_PLAN_ORDER:
        check_fn = _PLAN_KINDS[kind][0]
        try:
            info = check_fn()
        except Exception:
            log.exception("update plan: check failed for %s", kind)
            errors.append(kind)
            continue
        if info.get('error'):
            errors.append(kind)
            continue
        step = _plan_step_from_info(kind, info)
        if step is _STEP_INVALID:
            errors.append(kind)
            continue
        if step:
            steps.append(step)
    return steps, errors

def _runner_active():
    """True while the sequencer is running (either the transient unit started by
    apply_all_updates, or the boot-time resume unit)."""
    for unit in (UPDATE_RUNNER_UNIT + '.service', 'hifi-update-resume.service'):
        try:
            r = _run(['systemctl', 'is-active', unit])
            if (r.stdout or '').strip() in ('active', 'activating', 'reloading'):
                return True
        except Exception:
            pass
    return False

def _plan_overall_state(plan):
    """Derive the plan-level state from its steps."""
    if plan.get('finished'):
        return 'error' if plan.get('overall') == 'error' else 'finished'
    states = [s['state'] for s in plan['steps']]
    if 'error' in states:
        return 'error'
    if 'running' in states:
        # A step marked running with no live runner means we were killed between
        # steps (power cut, or a reboot on a box where the resume unit isn't
        # enabled yet). Say so rather than spinning forever on a dead plan.
        return 'running' if _runner_active() else 'interrupted'
    if 'pending' in states:
        return 'running' if _runner_active() else 'interrupted'
    return 'finished'

def apply_all_updates():
    """Build a plan for every component that has an update and hand it to the
    sequencer. Returns immediately; poll update_plan_status()."""
    with _UPDATE_PLAN_LOCK:
        existing = _read_update_plan()
        if existing and _plan_overall_state(existing) == 'running':
            return {'started': False, 'code': 'update.alreadyInProgress',
                    'message': _t('update.alreadyInProgress', _lang())}

        steps, errors = build_update_plan()
        if not steps:
            if errors:
                return {'started': False, 'code': 'update.checkFailed',
                        'message': _t('update.checkFailed', _lang())}
            return {'started': False, 'code': 'update.noneAvailable',
                    'message': _t('update.noneAvailable', _lang())}

        plan = {
            'plan_id': '%d-%d' % (int(time.time()), os.getpid()),
            'channel': get_ota_channel(),
            'created': int(time.time()),
            'steps': steps,
            'finished': None, 'overall': None,
        }
        try:
            _write_update_plan(plan)
        except Exception:
            log.exception("update plan: could not write %s", UPDATE_PLAN_FILE)
            return {'started': False, 'code': 'update.planSaveFailed',
                    'message': _t('update.planSaveFailed', _lang())}

        # Belt and braces: a device imaged before hifi-update-runner.sh was
        # added to the ISO's chmod-list (0300-app-install.hook.chroot) ships it
        # non-executable. `systemd-run --no-block` below still returns success
        # in that case — it only queues the transient unit, it doesn't wait for
        # the exec to actually happen — so the permission error is invisible
        # here and only shows up later as a plan stuck forever in 'pending'
        # (nothing ever marks it 'running'). Fix it unconditionally so this
        # class of bug can't silently strand a plan again.
        try:
            os.chmod(UPDATE_RUNNER_SCRIPT, 0o755)
        except OSError:
            log.exception("update plan: could not chmod +x %s", UPDATE_RUNNER_SCRIPT)

        cmd = ['systemd-run', '--no-block', '--collect',
               '--unit=' + UPDATE_RUNNER_UNIT, UPDATE_RUNNER_SCRIPT]
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=True)
        except FileNotFoundError:
            # systemd-run unavailable → detached subprocess. It no longer
            # survives a reboot, but the plan on disk does, so the resume unit
            # (or the next apply) finishes the job.
            subprocess.Popen([UPDATE_RUNNER_SCRIPT], start_new_session=True)
        except Exception:
            log.exception("update plan: could not start the runner")
            _clear_update_plan()
            return {'started': False, 'code': 'update.startFailed',
                    'message': _t('update.startFailed', _lang())}

        return {'started': True, 'plan_id': plan['plan_id'],
                'steps': [{'kind': s['kind'], 'version': s['version']} for s in steps]}

def update_plan_status():
    """Progress of the current plan: the persisted step list plus the live
    progress of whichever step is running."""
    plan = _read_update_plan()
    if not plan:
        return {'state': 'idle'}

    state = _plan_overall_state(plan)

    # Retire a finished plan once everyone has had a chance to see the outcome,
    # so it stops re-opening the completion overlay on every client start.
    if plan.get('finished') and time.time() - plan['finished'] > UPDATE_PLAN_TTL:
        _clear_update_plan()
        return {'state': 'idle'}

    # 'error' ranks above 'pending': the runner (hifi-update-runner.sh) always
    # stops at the first failed step, so any steps still 'pending' after that
    # were simply never reached — picking one of those as `current` would
    # attribute the failure to the wrong component and its version wouldn't
    # match the (unwritten) live status file below, silently losing the message.
    current = (next((s for s in plan['steps'] if s['state'] == 'running'), None)
               or next((s for s in plan['steps'] if s['state'] == 'error'), None)
               or next((s for s in plan['steps'] if s['state'] == 'pending'), None)
               or (plan['steps'][-1] if plan['steps'] else None))

    step_state, progress, message = '', None, ''
    # 'error' must be included here too — otherwise a failed step's real
    # failure reason (written by the updater script's fail() into
    # /run/hifi-*-status.json, e.g. "Download fallito da ...") is never read,
    # and the client falls back to showing just the generic component name.
    if current and state in ('running', 'interrupted', 'error'):
        try:
            with open(_PLAN_KINDS[current['kind']][1]) as f:
                live = json.load(f)
        except Exception:
            live = {}
        # Only trust the /run status file when it is talking about *this* step.
        # It is not reset between runs, so it can still hold the previous
        # update's `done` — which is precisely what used to make a client skip
        # ahead and start the next component on top of a running one.
        if live.get('version') == current['version']:
            step_state = live.get('state') or ''
            progress = live.get('progress') if isinstance(live.get('progress'), (int, float)) else None
            message = live.get('message') or ''
        else:
            step_state = 'starting'

    done = sum(1 for s in plan['steps'] if s['state'] == 'done')
    total = len(plan['steps']) or 1
    overall_progress = int(100.0 * (done + (progress or 0) / 100.0) / total)

    return {
        'state': state,
        'plan_id': plan['plan_id'],
        'channel': plan['channel'],
        'kind': current['kind'] if current else '',
        'version': current['version'] if current else '',
        'step_state': step_state,
        'progress': progress,
        'message': message,
        'overall_progress': min(overall_progress, 100),
        'finished': plan.get('finished'),
        'steps': [{'kind': s['kind'], 'version': s['version'], 'state': s['state'],
                   'installed': _PLAN_KINDS[s['kind']][2]()} for s in plan['steps']],
    }

def dismiss_update_plan():
    """Drop a plan that is no longer running (the client has shown the outcome).
    Refuses while the sequencer is still working."""
    with _UPDATE_PLAN_LOCK:
        plan = _read_update_plan()
        if plan and _plan_overall_state(plan) == 'running':
            return {'success': False, 'code': 'update.inProgress',
                    'message': _t('update.inProgress', _lang())}
        _clear_update_plan()
        return {'success': True}

# ──────────────────────────────────────────────────────────────────
#  Lyrion Music Server update helpers
# ──────────────────────────────────────────────────────────────────

def _lyrion_installed_version():
    try:
        r = _run(['dpkg-query', '-W', '-f=${Version}', LYRION_PKG])
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return 'unknown'

def get_lyrion_channel():
    """Return the persisted Lyrion channel. Mirrors get_ota_channel(), but this
    is a *separate* setting: the appliance's own dev channel says nothing about
    which music-server build the owner wants."""
    try:
        with open(LYRION_CHANNEL_FILE) as f:
            ch = f.read().strip()
        if ch in LYRION_CHANNELS:
            return ch
    except Exception:
        pass
    return LYRION_DEFAULT_CHANNEL

def set_lyrion_channel(channel):
    if channel not in LYRION_CHANNELS:
        return {'success': False, 'code': 'lyrion.badChannel',
                'message': _t('lyrion.badChannel', _lang()), 'channel': get_lyrion_channel()}
    try:
        os.makedirs(os.path.dirname(LYRION_CHANNEL_FILE), exist_ok=True)
        tmp = LYRION_CHANNEL_FILE + '.tmp'
        with open(tmp, 'w') as f:
            f.write(channel + '\n')
        os.replace(tmp, LYRION_CHANNEL_FILE)
    except Exception:
        log.exception("set_lyrion_channel failed")
        return {'success': False, 'code': 'lyrion.channelSaveFailed',
                'message': _t('lyrion.channelSaveFailed', _lang()), 'channel': get_lyrion_channel()}
    return {'success': True, 'channel': channel}

def get_lyrion_installed_channel():
    """Which channel actually produced the build currently installed (or
    being installed). None if never tracked yet — every device is in this
    state the first time it runs code that knows about this file, since it
    didn't exist before. Deliberately does NOT fall back to the preference
    file (get_lyrion_channel()): that file is what the Settings UI already
    overwrites the instant the owner picks a channel, before Install is even
    pressed, which is the exact bug this split was meant to fix — falling
    back to it here would silently reintroduce it on every device's first
    switch after upgrading. None compares unequal to any real channel, so
    apply_lyrion_update() treats an untracked device as "always switching",
    which is the safe default (worst case: one redundant reinstall)."""
    try:
        with open(LYRION_INSTALLED_CHANNEL_FILE) as f:
            ch = f.read().strip()
        if ch in LYRION_CHANNELS:
            return ch
    except Exception:
        pass
    return None

def _set_lyrion_installed_channel(channel):
    try:
        os.makedirs(os.path.dirname(LYRION_INSTALLED_CHANNEL_FILE), exist_ok=True)
        tmp = LYRION_INSTALLED_CHANNEL_FILE + '.tmp'
        with open(tmp, 'w') as f:
            f.write(channel + '\n')
        os.replace(tmp, LYRION_INSTALLED_CHANNEL_FILE)
    except Exception:
        log.exception("set_lyrion_installed_channel failed")

def _parse_lyrion_channels(html):
    """Pull one .deb per channel out of the downloads page.

    Release builds live under /LyrionMusicServer_v<X.Y.Z>/, both the stable
    nightly and the development build under /nightly/ with a '~<timestamp>'
    suffix. The two nightly streams are told apart by version: the higher
    minor is the development branch, the lower one the bugfix stream for the
    current release. We keep the '_all.deb' flavour, which is what the image
    installs today — switching to _amd64 would be an arch change, not an
    update."""
    out = {}
    releases = re.findall(
        r'https://downloads\.lms-community\.org/LyrionMusicServer_v(\d+\.\d+\.\d+)/'
        r'lyrionmusicserver_\1_all\.deb', html)
    if releases:
        latest = max(set(releases), key=_semver_key)
        out['release'] = {
            'version': latest,
            'url': (f'https://downloads.lms-community.org/LyrionMusicServer_v{latest}/'
                    f'lyrionmusicserver_{latest}_all.deb'),
        }

    nightlies = sorted(
        set(re.findall(
            r'https://downloads\.lms-community\.org/nightly/'
            r'lyrionmusicserver_(\d+\.\d+\.\d+~\d+)_all\.deb', html)),
        key=_semver_key)
    if nightlies:
        # Highest = development branch; the next one down = stable nightly.
        # With only one nightly published, treat it as the development build.
        out['dev'] = {
            'version': nightlies[-1],
            'url': ('https://downloads.lms-community.org/nightly/'
                    f'lyrionmusicserver_{nightlies[-1]}_all.deb'),
        }
        if len(nightlies) > 1:
            out['nightly'] = {
                'version': nightlies[-2],
                'url': ('https://downloads.lms-community.org/nightly/'
                        f'lyrionmusicserver_{nightlies[-2]}_all.deb'),
            }
    return out

def check_lyrion_update(channel=None):
    current = _lyrion_installed_version()
    channel = channel if channel in LYRION_CHANNELS else get_lyrion_channel()
    req = urllib.request.Request(LYRION_DOWNLOADS_PAGE,
                                 headers={'User-Agent': 'hifi-player-ota'})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', 'replace')
    except Exception:
        log.exception("lyrion update check failed")
        return {'code': 'lyrion.checkFailed',
                'error': _t('lyrion.checkFailed', _lang()),
                'current': current, 'channel': channel, 'channels': {}}

    channels = _parse_lyrion_channels(html)
    if not channels:
        return {'code': 'lyrion.noBuildFound',
                'error': _t('lyrion.noBuildFound', _lang()),
                'current': current, 'channel': channel, 'channels': {}}

    # An unavailable channel falls back to the release build rather than
    # reporting nothing — the page is the only source we have.
    sel = channels.get(channel) or channels.get('release') or next(iter(channels.values()))
    return {
        'current': current,
        'channel': channel,
        'channels': channels,
        'latest': sel['version'],
        'update_available': _is_newer(sel['version'], current),
        'asset_url': sel['url'],
    }

def apply_lyrion_update(channel=None):
    """Install the selected channel's build.

    A channel *switch* is applied even when it is a downgrade (moving from the
    development build back to the release is exactly that); only a no-op within
    the same channel is refused. hifi-lyrion-update.sh already passes
    --allow-downgrades to apt.

    "Switch" is detected against the *installed* channel, not the preference
    file the Settings UI writes the instant the owner taps a channel option
    (well before Install is pressed) — otherwise this always sees "no change"
    and a same-or-older-version channel swap gets wrongly refused as up to
    date. See LYRION_INSTALLED_CHANNEL_FILE."""
    switching = channel in LYRION_CHANNELS and channel != get_lyrion_installed_channel()
    info = check_lyrion_update(channel)
    if info.get('error'):
        return {'started': False, 'code': info.get('code'), 'message': info['error']}
    if not info.get('update_available') and not switching:
        return {'started': False, 'code': 'lyrion.upToDate',
                'message': _t('lyrion.upToDate', _lang())}
    if switching:
        set_lyrion_channel(channel)

    cmd = [
        'systemd-run', '--no-block', '--collect', '--unit=hifi-lyrion-update',
        LYRION_SCRIPT, info['asset_url'], info['latest'],
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=True)
    except FileNotFoundError:
        subprocess.Popen([LYRION_SCRIPT, info['asset_url'], info['latest']],
                         start_new_session=True)
    except subprocess.CalledProcessError:
        log.exception("update: apply command failed")
        return {'started': False, 'code': 'lyrion.startFailed',
                'message': _t('lyrion.startFailed', _lang())}
    except Exception:
        log.exception("update: apply failed")
        return {'started': False, 'code': 'lyrion.startFailed',
                'message': _t('lyrion.startFailed', _lang())}
    _set_lyrion_installed_channel(channel)
    return {'started': True, 'version': info['latest'], 'channel': info['channel']}

def lyrion_update_status():
    try:
        with open(LYRION_STATUS_FILE) as f:
            return json.load(f)
    except Exception:
        return {'state': 'idle'}

# Funzione per mostrare la tastiera virtuale globale
def show_global_keyboard():
    try:
        # Try different virtual keyboard solutions
        commands = [
            'onboard',  # Onboard virtual keyboard
            'florence',  # Florence virtual keyboard  
            'xvkbd',  # X virtual keyboard
            'matchbox-keyboard'  # Matchbox keyboard
        ]
        
        for cmd in commands:
            try:
                # Check if command exists
                subprocess.run(f"which {cmd}", shell=True, check=True, capture_output=True)
                print(f"Found {cmd}, launching...")
                # Launch in background
                subprocess.Popen(f"{cmd} &", shell=True)
                return _t('keyboard.started', _lang(), cmd=cmd)
            except subprocess.CalledProcessError:
                print(f"{cmd} not found, trying next...")
                continue

        return _t('keyboard.noneFound', _lang())
    except Exception:
        log.exception("show_global_keyboard failed")
        return _t('keyboard.startFailed', _lang())

# Funzione per nascondere la tastiera virtuale globale
def hide_global_keyboard():
    try:
        # Kill virtual keyboard processes
        subprocess.run("pkill -f onboard", shell=True, capture_output=True)
        subprocess.run("pkill -f florence", shell=True, capture_output=True)
        subprocess.run("pkill -f xvkbd", shell=True, capture_output=True)
        subprocess.run("pkill -f matchbox-keyboard", shell=True, capture_output=True)
        return _t('keyboard.closed', _lang())
    except Exception:
        log.exception("hide_global_keyboard failed")
        return _t('keyboard.closeFailed', _lang())

# ──────────────────────────────────────────────────────────────────
#  Guided room correction — measure the room with a USB mic and generate
#  the CamillaDSP FIR automatically (no external REW workflow needed).
#  Async job, same systemd-run + /run status-file shape as the OTA/format
#  jobs; the worker writes the same /etc/camilladsp/filters/room.wav the
#  manual upload flow uses, so the existing room_correction toggle applies it.
# ──────────────────────────────────────────────────────────────────
ROOMCORR_STATUS = '/run/hifi-roomcorr-status.json'
ROOMCORR_CFG = '/run/hifi-roomcorr-config.json'
ROOMCORR_RESULT = '/var/lib/hifi-player/roomcorr-result.json'
ROOMCORR_UNIT = 'hifi-room-measure'
ROOMCORR_SCRIPT = '/usr/local/sbin/hifi-room-measure.py'

def get_roomcorr_mics():
    """Capture devices from `arecord -l` (the measurement mic candidates).
    Loopback is the DSP plumbing, never a mic."""
    mics = []
    try:
        r = _run(['arecord', '-l'], timeout=10)
        for m in re.finditer(r'card (\d+): (\S+) \[(.*?)\], device (\d+): (.*?) \[',
                             r.stdout or ''):
            card, cid, cname, dev, dname = m.groups()
            if 'Loopback' in cid or 'Loopback' in cname:
                continue
            mics.append({
                'device': f'plughw:{card},{dev}',
                'name': (cname or cid).strip() or f'Card {card}',
                'detail': dname.strip(),
            })
    except Exception:
        log.exception('get_roomcorr_mics failed')
    return {'mics': mics, 'available': os.path.exists(ROOMCORR_SCRIPT)}

def _roomcorr_state():
    try:
        with open(ROOMCORR_STATUS) as f:
            return json.load(f)
    except Exception:
        return {'state': 'idle'}

def start_roomcorr_measure(data):
    if not os.path.exists(ROOMCORR_SCRIPT):
        return {'success': False, 'code': 'roomcorr.updateRequired',
                'message': _t('roomcorr.updateRequired', _lang())}, 424
    mic = str(data.get('mic_device') or '').strip()
    known = [m['device'] for m in get_roomcorr_mics()['mics']]
    if mic not in known:
        return {'success': False, 'code': 'roomcorr.micNotFound',
                'message': _t('roomcorr.micNotFound', _lang())}, 400
    try:
        level = float(data.get('level_db') or -12.0)
    except (TypeError, ValueError):
        level = -12.0
    level = max(-30.0, min(-6.0, level))
    if _roomcorr_state().get('state') in ('preparing', 'sweep', 'analyzing'):
        return {'success': False, 'code': 'roomcorr.alreadyMeasuring',
                'message': _t('roomcorr.alreadyMeasuring', _lang())}, 409

    cfg = {'mic_device': mic, 'out_device': _current_real_dac(), 'level_db': level}
    with open(ROOMCORR_CFG, 'w') as f:
        json.dump(cfg, f)
    os.chmod(ROOMCORR_CFG, 0o600)
    with open(ROOMCORR_STATUS, 'w') as f:
        json.dump({'state': 'preparing', 'progress': 0, 'message': _t('common.starting', _lang())}, f)
    subprocess.run(['systemd-run', '--no-block', '--collect',
                    '--unit=' + ROOMCORR_UNIT, ROOMCORR_SCRIPT, ROOMCORR_CFG],
                   capture_output=True, text=True, timeout=10)
    return {'success': True}, 202

def get_roomcorr_status():
    st = _roomcorr_state()
    if st.get('state') == 'done':
        try:
            with open(ROOMCORR_RESULT) as f:
                st['result'] = json.load(f)
        except Exception:
            pass
        fir_path, _ = _fir_current()
        dsp = _read_dsp_state()
        st['fir_present'] = bool(fir_path)
        st['applied'] = bool(dsp['enabled'] and dsp['room_correction'])
    return st

def roomcorr_apply():
    """Turn the freshly measured filter on via the normal DSP apply path."""
    fir_path, _ = _fir_current()
    if not fir_path:
        return {'success': False, 'code': 'roomcorr.noFilter',
                'message': _t('roomcorr.noFilter', _lang())}
    return set_dsp({'enabled': True, 'room_correction': True})

def roomcorr_discard():
    """Delete the generated filter (and switch the room-correction flag off
    if it was using it)."""
    removed = False
    for ext in FIR_KINDS:
        p = os.path.join(FIR_DIR, 'room' + ext)
        try:
            os.remove(p)
            removed = True
        except OSError:
            pass
    try:
        os.remove(ROOMCORR_RESULT)
    except OSError:
        pass
    st = _read_dsp_state()
    if st['room_correction']:
        set_dsp({'room_correction': False})
    return {'success': True, 'removed': removed}


@app.route('/check', methods=['GET'])
def api_check():
    return jsonify({"message": "ok"})

@app.route('/app_update/check', methods=['GET'])
def api_app_update_check():
    return jsonify(check_app_update())

@app.route('/app_update/apply', methods=['POST'])
def api_app_update_apply():
    return jsonify(apply_app_update())

@app.route('/app_update/status', methods=['GET'])
def api_app_update_status():
    return jsonify(app_update_status())

@app.route('/system_update/check', methods=['GET'])
def api_system_update_check():
    return jsonify(check_system_update())

@app.route('/system_update/apply', methods=['POST'])
def api_system_update_apply():
    return jsonify(apply_system_update())

@app.route('/system_update/status', methods=['GET'])
def api_system_update_status():
    return jsonify(system_update_status())

@app.route('/os_update/check', methods=['GET'])
def api_os_update_check():
    return jsonify(check_os_update())

@app.route('/os_update/apply', methods=['POST'])
def api_os_update_apply():
    return jsonify(apply_os_update())

@app.route('/os_update/status', methods=['GET'])
def api_os_update_status():
    return jsonify(os_update_status())

@app.route('/boot_mode', methods=['GET'])
def api_boot_mode():
    return jsonify(get_boot_mode())

@app.route('/install/disks', methods=['GET'])
def api_install_disks():
    return jsonify(list_install_disks())

@app.route('/install/start', methods=['POST'])
def api_install_start():
    data = request.get_json(silent=True) or {}
    return jsonify(start_disk_install((data.get('device') or '').strip()))

@app.route('/install/status', methods=['GET'])
def api_install_status():
    return jsonify(disk_install_status())

# Sequenced multi-component update. Preferred over calling the three
# */apply endpoints in turn: the whole plan is persisted and driven to the
# end server-side, so a service restart, a kiosk teardown or the reboot an
# OS payload asks for can no longer leave components half-updated.
@app.route('/update/apply_all', methods=['POST'])
def api_update_apply_all():
    return jsonify(apply_all_updates())

@app.route('/update/status', methods=['GET'])
def api_update_status():
    return jsonify(update_plan_status())

@app.route('/update/dismiss', methods=['POST'])
def api_update_dismiss():
    return jsonify(dismiss_update_plan())

@app.route('/lyrion_update/check', methods=['GET'])
def api_lyrion_update_check():
    return jsonify(check_lyrion_update(request.args.get('channel')))

@app.route('/lyrion_update/apply', methods=['POST'])
def api_lyrion_update_apply():
    data = request.get_json(silent=True) or {}
    return jsonify(apply_lyrion_update(data.get('channel')))

@app.route('/lyrion_channel', methods=['GET'])
def api_lyrion_channel():
    return jsonify({'channel': get_lyrion_channel(), 'channels': list(LYRION_CHANNELS)})

@app.route('/lyrion_channel', methods=['POST'])
def api_set_lyrion_channel():
    data = request.get_json(silent=True) or {}
    return jsonify(set_lyrion_channel((data.get('channel') or '').strip()))

@app.route('/lyrion_update/status', methods=['GET'])
def api_lyrion_update_status():
    return jsonify(lyrion_update_status())

@app.route('/reboot', methods=['POST'])
def api_reboot():
    result = reboot_device()
    return jsonify({"message": result})

@app.route('/shutdown', methods=['POST'])
def api_shutdown():
    result = shutdown_device()
    return jsonify({"message": result})

@app.route('/close_and_restart', methods=['POST'])
def api_close_and_restart():
    result = close_all_apps_and_restart()
    return jsonify({"message": result})

@app.route('/system_info', methods=['GET'])
def api_system_info():
    result = get_system_info()
    return jsonify(result)

@app.route('/system_stats', methods=['GET'])
def api_system_stats():
    result = get_system_stats()
    return jsonify(result)

@app.route('/network_info', methods=['GET'])
def api_network_info():
    result = get_system_info()
    return jsonify(result['network_interfaces'])

@app.route('/configure_network', methods=['POST'])
def api_configure_network():
    config = request.get_json()
    if not config:
        return jsonify({"error": "No configuration provided"}), 400
    
    result = configure_network(config)
    return jsonify({"message": result})

@app.route('/network_status', methods=['GET'])
def api_network_status():
    return jsonify(get_network_status())

@app.route('/wifi_scan', methods=['GET'])
def api_wifi_scan():
    return jsonify(wifi_scan())

@app.route('/wifi_connect', methods=['POST'])
def api_wifi_connect():
    data = request.get_json(silent=True) or {}
    return jsonify(wifi_connect(data.get('ssid'), data.get('password', '')))

@app.route('/wired_dhcp', methods=['POST'])
def api_wired_dhcp():
    return jsonify(wired_dhcp())

@app.route('/ssh_status', methods=['GET'])
def api_ssh_status():
    return jsonify(get_ssh_status())

@app.route('/ssh_set', methods=['POST'])
def api_ssh_set():
    data = request.get_json(silent=True) or {}
    return jsonify(set_ssh(bool(data.get('enable'))))

@app.route('/shell_account', methods=['GET'])
def api_shell_account():
    return jsonify(get_shell_account())

@app.route('/shell_account', methods=['POST'])
def api_set_shell_account():
    data = request.get_json(silent=True) or {}
    return jsonify(set_shell_account(data.get('username'), data.get('password')))

@app.route('/support_bundle', methods=['GET'])
def api_support_bundle():
    data = _support_bundle_build()
    stamp = time.strftime('%Y%m%d-%H%M')
    resp = Response(data, mimetype='application/zip')
    resp.headers['Content-Disposition'] = \
        f'attachment; filename="hifi-support-{socket.gethostname()}-{stamp}.zip"'
    return resp

@app.route('/har_captures', methods=['GET'])
def api_har_captures():
    return jsonify({'captures': _har_captures_list()})

@app.route('/har_captures/<filename>', methods=['GET'])
def api_har_capture_download(filename):
    if not _HAR_FILENAME_RE.match(filename or ''):
        return jsonify({'error': 'invalid filename'}), 400
    fpath = os.path.join(HAR_CAPTURE_DIR, filename)
    if not os.path.isfile(fpath):
        return jsonify({'error': 'not found'}), 404
    try:
        with open(fpath, 'rb') as f:
            data = f.read()
    except Exception:
        log.exception("har capture download failed for %s", filename)
        return jsonify({'error': 'read failed'}), 500
    resp = Response(data, mimetype='application/json')
    resp.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp

@app.route('/har_captures/<filename>', methods=['DELETE'])
def api_har_capture_delete(filename):
    if not _HAR_FILENAME_RE.match(filename or ''):
        return jsonify({'success': False, 'error': 'invalid filename'}), 400
    try:
        os.remove(os.path.join(HAR_CAPTURE_DIR, filename))
    except FileNotFoundError:
        pass
    except Exception:
        log.exception("har capture delete failed for %s", filename)
        return jsonify({'success': False}), 500
    return jsonify({'success': True})

@app.route('/tailscale_status', methods=['GET'])
def api_tailscale_status():
    return jsonify(get_tailscale_status())

@app.route('/tailscale_install', methods=['POST'])
def api_tailscale_install():
    return jsonify(install_tailscale())

@app.route('/tailscale_set', methods=['POST'])
def api_tailscale_set():
    data = request.get_json(silent=True) or {}
    return jsonify(set_tailscale(bool(data.get('enable'))))

@app.route('/debug_plymouth', methods=['GET'])
def api_debug_plymouth_get():
    return jsonify(get_plymouth_disabled())

@app.route('/debug_plymouth', methods=['POST'])
def api_debug_plymouth_set():
    data = request.get_json(silent=True) or {}
    return jsonify(set_plymouth_disabled(bool(data.get('disable'))))

@app.route('/debug_kdump', methods=['GET'])
def api_debug_kdump_get():
    return jsonify(get_kdump_enabled())

@app.route('/debug_kdump', methods=['POST'])
def api_debug_kdump_set():
    data = request.get_json(silent=True) or {}
    return jsonify(set_kdump_enabled(bool(data.get('enable'))))

@app.route('/pointer_status', methods=['GET'])
def api_pointer_status():
    return jsonify(get_pointer_status())

@app.route('/pointer_set', methods=['POST'])
def api_pointer_set():
    data = request.get_json(silent=True) or {}
    return jsonify(set_pointer(bool(data.get('enable'))))

@app.route('/display_mode', methods=['GET'])
def api_display_mode():
    return jsonify(get_display_mode())

@app.route('/display_mode', methods=['POST'])
def api_set_display_mode():
    data = request.get_json(silent=True) or {}
    return jsonify(set_display_mode((data.get('mode') or '').strip()))

@app.route('/player_enabled', methods=['GET'])
def api_player_enabled():
    return jsonify(get_player_enabled())

@app.route('/player_enabled', methods=['POST'])
def api_set_player_enabled():
    data = request.get_json(silent=True) or {}
    return jsonify(set_player_enabled(bool(data.get('enabled'))))

@app.route('/ui_resolution', methods=['GET'])
def api_ui_resolution():
    return jsonify(get_ui_resolution())

@app.route('/ui_resolution', methods=['POST'])
def api_set_ui_resolution():
    data = request.get_json(silent=True) or {}
    return jsonify(set_ui_resolution((data.get('mode') or '').strip()))

@app.route('/timezone', methods=['GET'])
def api_timezone():
    return jsonify(get_timezone())

@app.route('/timezone', methods=['POST'])
def api_set_timezone():
    data = request.get_json(silent=True) or {}
    return jsonify(set_timezone(data.get('timezone') or ''))

@app.route('/timezones', methods=['GET'])
def api_list_timezones():
    return jsonify({'timezones': list_timezones()})

@app.route('/vu_meter', methods=['GET'])
def api_vu_meter():
    return jsonify(get_vu_meter())

@app.route('/vu_meter', methods=['POST'])
def api_set_vu_meter():
    data = request.get_json(silent=True) or {}
    return jsonify(set_vu_meter(bool(data.get('enable'))))

@app.route('/nowplaying_autoexpand', methods=['GET'])
def api_nowplaying_autoexpand():
    return jsonify(get_nowplaying_autoexpand())

@app.route('/nowplaying_autoexpand', methods=['POST'])
def api_set_nowplaying_autoexpand():
    data = request.get_json(silent=True) or {}
    return jsonify(set_nowplaying_autoexpand(data.get('seconds')))

@app.route('/provision_status', methods=['GET'])
def api_provision_status():
    return jsonify(get_provision_status())

@app.route('/provision_mode', methods=['POST'])
def api_provision_mode():
    data = request.get_json(silent=True) or {}
    return jsonify(set_provision_mode((data.get('mode') or '').strip(),
                                      (data.get('source') or 'screen').strip()))

@app.route('/provision_wifi_connect', methods=['POST'])
def api_provision_wifi_connect():
    data = request.get_json(silent=True) or {}
    return jsonify(provision_wifi_connect((data.get('ssid') or '').strip(),
                                          data.get('password') or ''))

@app.route('/provision_wifi_rescan', methods=['POST'])
def api_provision_wifi_rescan():
    return jsonify(provision_wifi_rescan())

@app.route('/factory_reset', methods=['POST'])
def api_factory_reset():
    return jsonify(factory_reset())

@app.route('/webui_reset_credentials', methods=['POST'])
def api_webui_reset_credentials():
    return jsonify(webui_reset_credentials())

@app.route('/ota_channel', methods=['GET'])
def api_ota_channel():
    channels = [c for c in OTA_CHANNELS if c != 'alpha' or _alpha_unlocked()]
    return jsonify({'channel': get_ota_channel(), 'channels': channels})

@app.route('/ota_channel', methods=['POST'])
def api_set_ota_channel():
    data = request.get_json(silent=True) or {}
    return jsonify(set_ota_channel(data.get('channel')))

@app.route('/audio_devices', methods=['GET'])
def api_audio_devices():
    return jsonify(list_audio_devices())

@app.route('/set_audio_device', methods=['POST'])
def api_set_audio_device():
    data = request.get_json(silent=True) or {}
    return jsonify(set_audio_device(data.get('device')))

@app.route('/lms_role', methods=['GET'])
def api_lms_role():
    return jsonify(get_lms_role())

@app.route('/lms_role', methods=['POST'])
def api_set_lms_role():
    data = request.get_json(silent=True) or {}
    return jsonify(set_lms_role(data.get('mode'), data.get('host')))

@app.route('/player_name', methods=['GET'])
def api_player_name():
    return jsonify(get_player_name())

@app.route('/player_name', methods=['POST'])
def api_set_player_name():
    data = request.get_json(silent=True) or {}
    return jsonify(set_player_name(data.get('name')))

@app.route('/device_name', methods=['GET'])
def api_device_name():
    return jsonify(get_device_name())

@app.route('/device_name', methods=['POST'])
def api_set_device_name():
    data = request.get_json(silent=True) or {}
    return jsonify(set_device_name((data.get('name') or '').strip()))

@app.route('/discover_lms', methods=['GET'])
def api_discover_lms():
    return jsonify({'servers': discover_lms_servers()})

@app.route('/roomcorr/mics', methods=['GET'])
def api_roomcorr_mics():
    return jsonify(get_roomcorr_mics())

@app.route('/roomcorr/measure', methods=['POST'])
def api_roomcorr_measure():
    data = request.get_json(silent=True) or {}
    body, status = start_roomcorr_measure(data)
    return jsonify(body), status

@app.route('/roomcorr/status', methods=['GET'])
def api_roomcorr_status():
    return jsonify(get_roomcorr_status())

@app.route('/roomcorr/apply', methods=['POST'])
def api_roomcorr_apply():
    return jsonify(roomcorr_apply())

@app.route('/roomcorr/discard', methods=['POST'])
def api_roomcorr_discard():
    return jsonify(roomcorr_discard())

@app.route('/dsp_status', methods=['GET'])
def api_dsp_status():
    return jsonify(get_dsp_status())

@app.route('/dsp_set', methods=['POST'])
def api_dsp_set():
    data = request.get_json(silent=True) or {}
    return jsonify(set_dsp(data))

@app.route('/dsp_presets', methods=['GET'])
def api_dsp_presets():
    return jsonify(get_dsp_presets())

@app.route('/dsp_preset_save', methods=['POST'])
def api_dsp_preset_save():
    data = request.get_json(silent=True) or {}
    return jsonify(save_dsp_preset(data.get('name')))

@app.route('/dsp_preset_load', methods=['POST'])
def api_dsp_preset_load():
    data = request.get_json(silent=True) or {}
    return jsonify(load_dsp_preset(data.get('name')))

@app.route('/dsp_preset_rename', methods=['POST'])
def api_dsp_preset_rename():
    data = request.get_json(silent=True) or {}
    return jsonify(rename_dsp_preset(data.get('name'), data.get('new_name')))

@app.route('/dsp_preset_delete', methods=['POST'])
def api_dsp_preset_delete():
    data = request.get_json(silent=True) or {}
    return jsonify(delete_dsp_preset(data.get('name')))

@app.route('/tidal_status', methods=['GET'])
def api_tidal_status():
    return jsonify(get_tidal_status())

@app.route('/tidal_set', methods=['POST'])
def api_tidal_set():
    data = request.get_json(silent=True) or {}
    return jsonify(set_tidal(bool(data.get('enable'))))

@app.route('/bluetooth_status', methods=['GET'])
def api_bluetooth_status():
    return jsonify(get_bluetooth_status())

@app.route('/bluetooth_set', methods=['POST'])
def api_bluetooth_set():
    data = request.get_json(silent=True) or {}
    return jsonify(set_bluetooth(bool(data.get('enable'))))

@app.route('/bluetooth_discoverable', methods=['POST'])
def api_bluetooth_discoverable():
    return jsonify(set_bt_discoverable())

@app.route('/bluetooth_forget', methods=['POST'])
def api_bluetooth_forget():
    data = request.get_json(silent=True) or {}
    return jsonify(bt_forget(data.get('mac')))

@app.route('/bluetooth_now_playing', methods=['GET'])
def api_bluetooth_now_playing():
    return jsonify(get_bluetooth_now_playing())

@app.route('/show_global_keyboard', methods=['POST'])
def api_show_global_keyboard():
    result = show_global_keyboard()
    return jsonify({"message": result})

@app.route('/hide_global_keyboard', methods=['POST'])
def api_hide_global_keyboard():
    result = hide_global_keyboard()
    return jsonify({"message": result})

if __name__ == '__main__':
    # Bind to loopback only. This API runs as root and exposes reboot/shutdown,
    # OS/system updates and network reconfiguration with NO authentication; it is
    # consumed solely by the local kiosk UI (src/utils/api.js → http://localhost:8000).
    # Listening on 0.0.0.0 would hand every device on the LAN root-equivalent
    # control of the appliance.
    # threaded=True so a slow handler (apt/systemctl/network reconfig, or a
    # 15s OTA fetch) doesn't block the kiosk UI's other requests behind it.
    _startup_network_recovery()
    threading.Thread(target=_resume_playback_after_boot, daemon=True).start()
    app.run(host='127.0.0.1', port=8000, threaded=True)