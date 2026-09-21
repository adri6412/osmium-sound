from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import subprocess
import os
import shutil
import signal
import sys
import socket
import ssl
import errno
import email.utils
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
from hifi_i18n import MESSAGES as _I18N_MESSAGES

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
# Releases are served from file.osmiumsound.it (Cloudflare R2, the host the
# ISO and the flasher come from) and the release workflow drops a copy of each
# channel's manifest next to the payloads (ota/latest-<channel>.json). Read
# that copy when Pages is unreachable, before resorting to the rate-limited
# GitHub API. Stable releases since 2.5.24, every channel since 2.5.25; the
# name stays for the HIFI_OTA_PROD_MIRROR_BASE override.
OTA_PROD_MIRROR_BASE = os.environ.get('HIFI_OTA_PROD_MIRROR_BASE',
                                      'https://file.osmiumsound.it/ota')
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
# 🚨 Da 2.5.24 il canale "ui" porta l'interfaccia Qt (/opt/hifi-qt), non piu'
# l'app Electron: la versione installata sta in un file suo, fuori dalle due
# cartelle. Il vecchio percorso resta come ripiego per gli apparecchi che non
# hanno ancora ricevuto questo aggiornamento.
OTA_VERSION_FILE = '/etc/hifi-player/UI_VERSION'
OTA_VERSION_FILE_LEGACY = os.path.join(OTA_APPDIR, 'UI_VERSION')
OTA_SCRIPT = '/usr/local/sbin/hifi-ota-update.sh'
OTA_STATUS_FILE = '/run/hifi-ota-status.json'
# The UI release carries several tarballs; pick ours by name prefix.
# 🚨 Da 2.5.24 il pacchetto dell'interfaccia contiene Qt e si chiama
# `hifi-qtui-`: il nome e' NUOVO di proposito, perche' l'aggiornatore
# installato sugli apparecchi vecchi rifiuta un pacchetto senza Electron e
# bloccherebbe l'intero aggiornamento. Non trovando `hifi-ui-` quegli
# apparecchi considerano l'interfaccia aggiornata, applicano sistema e
# sistema operativo, e al giro dopo — con l'aggiornatore nuovo — prendono
# anche Qt. Il nome vecchio resta come ripiego per tornare indietro.
OTA_UI_PREFIX = ('hifi-qtui-', 'hifi-ui-')

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
# Immagine RAUC (schema A/B): un solo bundle che porta UI + componenti di
# sistema + OS; hifi-image-update.sh lo scarica intero su /data e lo fa
# installare a RAUC nello slot inattivo, oppure lo fa leggere a RAUC in
# streaming dall'asset della Release quando su /data non c'è posto.
IMAGE_PREFIX = 'hifi-image-'
IMAGE_STATUS_FILE = '/run/hifi-image-status.json'
IMAGE_SCRIPT = '/usr/local/sbin/hifi-image-update.sh'

# ──────────────────────────────────────────────────────────────────
#  Installer (src/pages/InstallWizard.jsx): backend for the "Install
#  Osmium Sound" boot entry. Same systemd-run + /run status-file shape
#  as the OS/system/UI updates above. See hifi-disk-install.sh and
#  distro/README.md for the full flow — this replaces Debian Installer.
# ──────────────────────────────────────────────────────────────────
INSTALL_SCRIPT = '/usr/local/sbin/hifi-disk-install.sh'
INSTALL_STATUS_FILE = '/run/hifi-install-status.json'

# ──────────────────────────────────────────────────────────────────
#  Multi-component update sequencer — two-phase, isolated apply.
#
#  Applying "everything" used to be sequenced by the client that started
#  it: apply one component, poll its /run status file, apply the next.
#  Anything that killed the client killed the rest of the sequence, and
#  the three most common events in an update are exactly that — the
#  system bundle restarts hifi-api and hifi-webui, the UI bundle
#  restarts lightdm, and an OS payload may reboot the box. A later
#  redesign moved that sequencing server-side (hifi-update-runner.sh, one
#  transient unit), which fixed "killed the client" but not "applying
#  while the very things being replaced are still running" — a service
#  restart or a lightdm teardown mid-install could still leave a
#  component half-applied.
#
#  So the flow is now split in two phases, each with its own runner:
#    1. hifi-update-stage-runner.sh downloads and verifies every
#       component (nothing applied yet, the box stays fully live) and,
#       once everything has staged, creates /system-update and reboots.
#    2. systemd-system-update-generator(8) redirects that one boot into
#       system-update.target instead of the normal graphical session —
#       nothing from the app stack starts at all — where
#       hifi-update-apply-runner.sh (hifi-update-apply.service) applies
#       every staged, already-verified payload with nothing else running
#       to race against, then clears /system-update and reboots back to
#       normal.
#
#  This module builds the plan, starts the stage runner, and reports
#  progress by merging the persisted plan with the running step's /run
#  status file during staging, then — once the box comes back from its
#  two reboots — the durable post-apply outcome recorded in
#  UPDATE_STATE_FILE. See hifi-update-stage-runner.sh /
#  hifi-update-apply-runner.sh for the on-disk formats.
#
#  The per-component endpoints below stay: they are still the right
#  thing for updating a single component, and older clients use them.
# ──────────────────────────────────────────────────────────────────
UPDATE_DIR = '/var/lib/hifi-player/update'
UPDATE_PLAN_FILE = UPDATE_DIR + '/plan'
# Written by the stage/apply runners; read (never written) here. Key=value
# lines: phase (staged|applying|done|error), ts (epoch), message.
UPDATE_STATE_FILE = UPDATE_DIR + '/state'
# Detail for the terminal apply_error state — channel + free-text message.
UPDATE_ERROR_FILE = UPDATE_DIR + '/error.json'
UPDATE_STAGE_RUNNER_SCRIPT = '/usr/local/sbin/hifi-update-stage-runner.sh'
UPDATE_STAGE_RUNNER_UNIT = 'hifi-update-stage'
# systemd-system-update-generator(8)'s own trigger: its mere existence at
# early boot is what redirects default.target to system-update.target for
# that one boot. Created by the stage runner, removed by the apply runner.
SYSTEM_UPDATE_LINK = '/system-update'
# Canonical order. system first (it delivers the API, daemons, helper
# scripts and units everything else relies on), os second, ui last.
# 'image' per ultimo: sugli apparecchi non ancora convertiti non è mai offerto
# (check_image_update), su quelli convertiti o già immagine è l'unico passo
# che conta e supera gli altri (il riavvio va direttamente sul nuovo slot).
UPDATE_PLAN_ORDER = ('system', 'os', 'ui', 'image')
# How long a finished/failed outcome stays readable so clients can show it
# — including a kiosk that only comes back up after both update-mode
# reboots. After this it is cleared automatically, so a plan/outcome
# nobody dismissed cannot keep re-opening the overlay forever.
UPDATE_PLAN_TTL = 900
# A 'phase=applying' left behind across the conversion-chain reboots (armed
# on purpose by the apply runner so the kiosk shows one continuous update)
# must still expire if the chain dies, or the overlay would spin forever.
UPDATE_APPLYING_TTL = 2 * 3600
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
LYRION_UNIT = 'lyrionmusicserver'
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
        # The host name is normally in /etc/hosts; when it is not, this goes
        # out to DNS, which hangs or fails without a network — and the
        # interface list, the one thing the network page needs while the
        # box is offline, must not go down with it.
        try:
            local_ip = socket.gethostbyname(hostname)
        except Exception:
            local_ip = 'Unknown'

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

def _sysfs(path):
    """First line of a sysfs attribute, stripped. None when unreadable."""
    try:
        with open(path) as f:
            return f.readline().strip()
    except Exception:
        return None


def _sysfs_temp_c(path):
    """A sysfs millidegree attribute as °C, None when unreadable or outside
    the range a real silicon sensor can report. The bounds are not cosmetic:
    an ACPI zone with nothing behind it happily reads back 0 or 216.8 °C
    (0xFFFF millidegrees), and the old "hottest zone wins" pick would put
    exactly that on the dashboard."""
    raw = _sysfs(path)
    if raw is None:
        return None
    try:
        c = int(raw) / 1000.0
    except ValueError:
        return None
    return c if 5.0 <= c <= 125.0 else None


THERMAL_ZONE_GLOB = '/sys/class/thermal/thermal_zone*'
HWMON_GLOB = '/sys/class/hwmon/hwmon*'
DRM_HWMON_TEMP_GLOB = '/sys/class/drm/card[0-9]/device/hwmon/hwmon*/temp*_input'

# Zone types that really are the CPU die/package, in order of preference (not
# of expected value).
_CPU_ZONE_TYPES = ('x86_pkg_temp', 'coretemp', 'k10temp', 'zenpower',
                   'cpu_thermal', 'cpu-thermal', 'soc_thermal', 'tcpu')

# Zones that certainly do NOT measure the CPU. A mini PC lists half a dozen of
# them (chipset, Wi-Fi card, NVMe, iGPU) and any one can be the hottest thing
# in the box, so a plain max() over every zone reports some other component's
# temperature under the "Temperature" label.
_NON_CPU_ZONE_HINTS = ('pch', 'nvme', 'iwlwifi', 'wifi', 'wlan', 'gpu',
                       'int3400', 'battery', 'charger', 'ambient', 'skin')

# The same die sensors read straight from hwmon, for kernels that expose them
# there without registering a thermal zone.
_CPU_HWMON_NAMES = ('coretemp', 'k10temp', 'zenpower')


def _cpu_temp_c():
    """CPU temperature in °C (one decimal), None when the box exposes no CPU
    sensor at all.

    Chosen BY SENSOR NAME. This used to be the highest reading across every
    thermal zone, which is only the CPU by luck: on a machine whose chipset,
    Wi-Fi card or iGPU runs hotter than the die, that maximum silently became
    some other chip's temperature."""
    zones = []
    for zone in glob.glob(THERMAL_ZONE_GLOB):
        ztype = (_sysfs(os.path.join(zone, 'type')) or '').lower()
        c = _sysfs_temp_c(os.path.join(zone, 'temp'))
        if c is not None:
            zones.append((ztype, c))

    for name in _CPU_ZONE_TYPES:
        # Several packages/cores can expose the same sensor type; the hottest
        # of them is the one that matters.
        matches = [c for ztype, c in zones if ztype.startswith(name)]
        if matches:
            return round(max(matches), 1)

    # Before acpitz, not after: acpitz is an ACPI zone that on most boards
    # tracks the board, while a coretemp hwmon is the die itself.
    hwmon = _cpu_hwmon_temp_c()
    if hwmon is not None:
        return hwmon

    fallback = [c for ztype, c in zones if ztype.startswith('acpitz')]
    if not fallback:
        # Bare ACPI names ('tz00' and friends): the hottest zone that is at
        # least not a component we can name, rather than no reading at all.
        fallback = [c for ztype, c in zones
                    if not any(h in ztype for h in _NON_CPU_ZONE_HINTS)]
    return round(max(fallback), 1) if fallback else None


def _cpu_hwmon_temp_c():
    """coretemp/k10temp read straight from hwmon: 'Package id 0' (Intel) or
    'Tdie'/'Tctl' (AMD) when labelled, else the hottest core."""
    for hwmon in sorted(glob.glob(HWMON_GLOB)):
        if (_sysfs(os.path.join(hwmon, 'name')) or '').lower() not in _CPU_HWMON_NAMES:
            continue
        package = core = None
        for entry in sorted(glob.glob(os.path.join(hwmon, 'temp*_input'))):
            c = _sysfs_temp_c(entry)
            if c is None:
                continue
            label = (_sysfs(entry.replace('_input', '_label')) or '').lower()
            if label.startswith('package') or label in ('tdie', 'tctl'):
                package = c if package is None else max(package, c)
            core = c if core is None else max(core, c)
        if package is not None:
            return round(package, 1)
        if core is not None:
            return round(core, 1)
    return None


def _gpu_temp_c():
    """GPU temperature in whole °C, None when the GPU has no sensor of its
    own — which is the normal case for an Intel iGPU: it shares the CPU die,
    so the package sensor already covers it and only discrete cards (and
    amdgpu) publish a hwmon of their own under the DRM device."""
    for entry in sorted(glob.glob(DRM_HWMON_TEMP_GLOB)):
        label = (_sysfs(entry.replace('_input', '_label')) or '').lower()
        if label in ('junction', 'mem', 'vrm', 'vram'):
            continue  # hotspot/memory sensors, not the GPU core
        c = _sysfs_temp_c(entry)
        if c is not None:
            return round(c, 1)
    for zone in glob.glob(THERMAL_ZONE_GLOB):
        if 'gpu' in (_sysfs(os.path.join(zone, 'type')) or '').lower():
            c = _sysfs_temp_c(os.path.join(zone, 'temp'))
            if c is not None:
                return round(c, 1)
    return None

_gpu_warned = False  # log the first failure only -- this polls every 5s forever


def _gpu_busy_pct():
    """GPU busy % -- Intel iGPU via intel_gpu_top, AMD/ATI via radeontop.
    Neither tool ships on the image by default (see intel-gpu-tools /
    radeontop apply.d steps), so this is a no-op (None) wherever neither is
    installed."""
    if shutil.which('intel_gpu_top'):
        return _intel_gpu_busy_pct()
    if shutil.which('radeontop'):
        return _amd_gpu_busy_pct()
    return None


def _intel_gpu_busy_pct():
    """`-J` streams a JSON array that only gets its closing `]` once the
    process exits, and it never exits on its own -- a plain
    `subprocess.run(..., timeout=N)` would always hit the timeout and lose
    the output. Let it sample for one interval, then ask it to exit cleanly
    (SIGINT, same as Ctrl-C) so it flushes valid JSON. Failures are logged
    once (not every poll): this used to fail completely silently, which is
    exactly how a real bug (Debian's stricter default perf_event_paranoid
    rejecting CAP_PERFMON -- see distro/os-update/apply.d/0046-perfmon-sysctl.sh)
    went unnoticed for a long time."""
    global _gpu_warned
    proc = None
    err = ''
    try:
        proc = subprocess.Popen(
            ['intel_gpu_top', '-J', '-s', '500', '-o', '-'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(1.0)
        proc.send_signal(signal.SIGINT)
        try:
            out, err = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
        text = out.strip()
        if not text.startswith('['):
            text = '[' + text.lstrip(',')
        if not text.rstrip().endswith(']'):
            text = text.rstrip().rstrip(',') + ']'
        samples = json.loads(text)
        if not samples:
            if not _gpu_warned:
                _gpu_warned = True
                log.warning('gpu_busy_pct: no samples captured, stderr: %s', (err or '').strip()[:200])
            return None
        engines = samples[-1].get('engines') or {}
        render = engines.get('Render/3D') or engines.get('Render/3D/0') or {}
        busy = render.get('busy')
        if busy is None and not _gpu_warned:
            _gpu_warned = True
            log.warning('gpu_busy_pct: no \'busy\' field in engines=%s', list(engines))
        return round(float(busy), 1) if busy is not None else None
    except Exception as e:
        if not _gpu_warned:
            _gpu_warned = True
            log.warning('gpu_busy_pct: %s, stderr: %s', e, (err or '').strip()[:200])
        return None
    finally:
        if proc and proc.poll() is None:
            proc.kill()


def _amd_gpu_busy_pct():
    """AMD/ATI GPU busy % via radeontop. Works across both the legacy
    `radeon` and current `amdgpu` kernel drivers (unlike reading
    gpu_busy_percent from sysfs, which only amdgpu exposes -- it would miss
    older cards). `-l 1` takes exactly one sample and exits on its own, no
    SIGINT dance needed like intel_gpu_top's endless JSON stream."""
    global _gpu_warned
    try:
        out = subprocess.run(
            ['radeontop', '-d', '-', '-l', '1'],
            capture_output=True, text=True, timeout=5).stdout
        m = re.search(r'\bgpu\s+([\d.]+)%', out)
        if not m:
            if not _gpu_warned:
                _gpu_warned = True
                log.warning('gpu_busy_pct: no gpu field in radeontop output: %s', out.strip()[:200])
            return None
        return round(float(m.group(1)), 1)
    except Exception as e:
        if not _gpu_warned:
            _gpu_warned = True
            log.warning('gpu_busy_pct: %s', e)
        return None


DATA_MOUNT = '/data'


def _disk_path():
    """The filesystem whose fill level actually means something to the owner.

    On an image system / IS the squashfs slot: read-only, packed full at build
    time, so it reports 100% forever and says nothing about the box. Everything
    that grows -- music, Lyrion, /var, /home, the whole writable layer -- lives
    on the data partition, so that is the disk to report. A legacy install has
    no separate /data and keeps answering for /."""
    try:
        if os.path.ismount(DATA_MOUNT):
            return DATA_MOUNT
    except Exception:
        pass
    return '/'


def _whole_disk_bytes(path):
    """Size of the physical disk the given filesystem sits on, in bytes.

    The owner thinks in terms of the disk they bought, not of partitions:
    to answer "how much did the system take and how much is left for my
    music" we need the whole device, not just the mounted filesystem. Read
    it from sysfs (the mount's device -> the partition's parent disk -> its
    size in 512-byte sectors), so no external tool has to be installed.
    None when it can't be resolved (a network mount, a container, an
    unusual device-mapper setup): the caller then omits the breakdown
    rather than inventing numbers."""
    try:
        st = os.stat(path)
        node = os.path.realpath('/sys/dev/block/%d:%d' % (os.major(st.st_dev), os.minor(st.st_dev)))
        # a partition carries this file and hangs under its disk; a mount
        # straight on a whole device (or on an LVM/loop node) does not
        if os.path.exists(os.path.join(node, 'partition')):
            node = os.path.dirname(node)
        with open(os.path.join(node, 'size'), encoding='utf-8') as f:
            size = int(f.read().strip()) * 512
        return size if size > 0 else None
    except Exception:
        return None


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
        path = _disk_path()
        du = shutil.disk_usage(path)
        # How the disk is split, in the terms the owner cares about: the
        # image slots and the boot partition are gone for good (the system
        # keeps two full copies of itself so an update can fail safely), the
        # data partition is theirs. Everything on the device that is not the
        # reported filesystem counts as the system's share; on a legacy
        # install, where / holds both the system and the music, the split
        # cannot be drawn and stays None instead of being guessed.
        whole = _whole_disk_bytes(path)
        system = whole - du.total if whole and whole > du.total else None
        if path == '/' and system is not None and not os.path.ismount(DATA_MOUNT):
            system = None
        return {
            'cpu_percent': cpu_pct,
            'ram_percent': vm.percent,
            'ram_used_mb': round(vm.used / 1024 / 1024),
            'ram_total_mb': round(vm.total / 1024 / 1024),
            'disk_path': path,
            'disk_percent': round(du.used / du.total * 100, 1) if du.total else None,
            'disk_used_gb': round(du.used / 1024 / 1024 / 1024, 1),
            'disk_total_gb': round(du.total / 1024 / 1024 / 1024, 1),
            # what is still writable by the owner (statvfs' available, so the
            # filesystem's root reserve is not promised to them)
            'disk_free_gb': round(du.free / 1024 / 1024 / 1024, 1),
            'disk_system_gb': round(system / 1024 / 1024 / 1024, 1) if system is not None else None,
            'disk_device_gb': round(whole / 1024 / 1024 / 1024, 1) if whole else None,
            'temp_c': _cpu_temp_c(),
            'gpu_percent': _gpu_busy_pct(),
            'gpu_temp_c': _gpu_temp_c(),
        }
    except Exception:
        log.exception("get_system_stats failed")
        return {'cpu_percent': None, 'ram_percent': None, 'ram_used_mb': None,
                'ram_total_mb': None, 'disk_path': None, 'disk_percent': None,
                'disk_used_gb': None, 'disk_total_gb': None, 'disk_free_gb': None,
                'disk_system_gb': None, 'disk_device_gb': None, 'temp_c': None,
                'gpu_percent': None, 'gpu_temp_c': None}

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

# ──────────────────────────────────────────────────────────────────
#  Network check ("network doctor"): walks the same path an update
#  check takes — the box's own link, the router, the internet, name
#  lookup, the clock (TLS needs it), the update server and the host
#  the download comes from — and says at which hop it breaks, so the
#  owner can tell "my Wi-Fi" from "my router" from "Osmium's server".
#  Settings → System info / Updates, on the kiosk and in the web admin.
#
#  Every result is language-neutral (ids, codes, addresses, numbers):
#  the UIs turn them into sentences.
# ──────────────────────────────────────────────────────────────────
NETCHECK_STEPS = ('link', 'router', 'internet', 'dns', 'clock', 'ota', 'download')
# Raw IPs on purpose: this step must not depend on name lookup, which has
# a step of its own. 443 rather than ICMP, since that is what the update
# check needs and plenty of networks drop ping to the outside.
_NETCHECK_IP_TARGETS = (('1.1.1.1', 443), ('8.8.8.8', 443), ('9.9.9.9', 443))
_NETCHECK_LOCK = threading.Lock()
_NETCHECK_UA = 'hifi-player-ota'

def _netcheck_error(exc):
    """(reason code, HTTP status or None) for a failed probe."""
    if isinstance(exc, urllib.error.HTTPError):
        return 'http', exc.code
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, socket.gaierror):
        return 'dns', None
    if isinstance(reason, ssl.SSLCertVerificationError):
        return 'tlsCert', None
    if isinstance(reason, ssl.SSLError):
        return 'tls', None
    if isinstance(reason, TimeoutError) or 'timed out' in str(reason):
        return 'timeout', None
    if isinstance(reason, ConnectionRefusedError):
        return 'refused', None
    if isinstance(reason, ConnectionResetError):
        return 'reset', None
    if isinstance(reason, OSError) and reason.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH):
        return 'unreachable', None
    return 'other', None

def _netcheck_parallel(tasks, timeout):
    """Run {key: fn} side by side and wait at most `timeout` seconds overall.
    Daemon threads, so a probe stuck in a call without its own timeout
    (getaddrinfo) can't hold the answer back: it is reported as timed out."""
    results = {}
    def run(key, fn):
        try:
            results[key] = fn()
        except Exception as e:
            results[key] = e
    threads = [threading.Thread(target=run, args=(k, fn), daemon=True) for k, fn in tasks.items()]
    for th in threads:
        th.start()
    deadline = time.monotonic() + timeout
    for th in threads:
        th.join(max(0.0, deadline - time.monotonic()))
    return {k: results.get(k, TimeoutError('timed out')) for k in tasks}

def _netcheck_link():
    device, dtype = _active_device()
    if not device:
        return {'status': 'fail', 'error': 'noLink'}
    out = {'device': device, 'type': 'wireless' if dtype == 'wifi' else 'wired',
           'ip': _device_ip(device), 'status': 'ok'}
    parts = [device]
    if dtype == 'wifi':
        out['ssid'] = _active_ssid()
        try:
            r = _run(['nmcli', '-t', '-f', 'IN-USE,SIGNAL', 'device', 'wifi', 'list',
                      'ifname', device, '--rescan', 'no'], timeout=5)
            for line in r.stdout.strip().split('\n'):
                f = _terse_split(line)
                if len(f) >= 2 and f[0] == '*' and f[1].isdigit():
                    out['signal'] = int(f[1])
        except Exception:
            pass
        if out.get('ssid'):
            parts.append(out['ssid'])
        if out.get('signal') is not None:
            parts.append(f"{out['signal']}%")
            if out['signal'] < 35:
                out.update(status='warn', error='weakSignal')
    if not out['ip']:
        out.update(status='fail', error='noAddress')
    elif out['ip'].startswith('169.254.'):
        # link-local: the cable/Wi-Fi is up but nobody handed out an address
        out.update(status='fail', error='noDhcp')
    if out['ip']:
        parts.append(out['ip'])
    out['detail'] = ' · '.join(parts)
    return out

def _default_gateway():
    r = _run(['ip', '-4', 'route', 'show', 'default'], timeout=5)
    for line in r.stdout.splitlines():
        m = re.search(r'\bvia (\S+)', line)
        if m:
            return m.group(1)
    return None

def _netcheck_router():
    gw = _default_gateway()
    if not gw:
        return {'status': 'fail', 'error': 'noGateway'}
    out = {'gateway': gw, 'detail': gw}
    r = _run(['ping', '-n', '-q', '-c', '3', '-i', '0.2', '-W', '1', gw], timeout=8)
    m = re.search(r'(\d+) packets transmitted, (\d+) received', r.stdout)
    sent, got = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    if got:
        rtt = re.search(r'= [\d.]+/([\d.]+)/', r.stdout)
        if rtt:
            out['ms'] = round(float(rtt.group(1)), 1)
            out['detail'] = f"{gw} · {out['ms']} ms"
        out['loss'] = round(100 * (sent - got) / sent) if sent else 0
        out['status'] = 'warn' if got < sent else 'ok'
        if got < sent:
            out['error'] = 'packetLoss'
        return out
    # Some routers ignore ping. If it answered ARP it is there all the same.
    n = _run(['ip', 'neigh', 'show', gw], timeout=5).stdout
    if 'lladdr' in n and not re.search(r'\b(FAILED|INCOMPLETE)\b', n):
        out.update(status='ok', error='noPing')
        return out
    out.update(status='fail', error='noAnswer')
    return out

def _netcheck_tcp(host, port, timeout=4):
    t0 = time.monotonic()
    with socket.create_connection((host, port), timeout=timeout):
        pass
    return round((time.monotonic() - t0) * 1000)

def _netcheck_internet():
    res = _netcheck_parallel({f'{h}:{p}': (lambda h=h, p=p: _netcheck_tcp(h, p))
                              for h, p in _NETCHECK_IP_TARGETS}, 6)
    ok = [(k, v) for k, v in res.items() if isinstance(v, int)]
    if ok:
        k, ms = min(ok, key=lambda kv: kv[1])
        return {'status': 'ok', 'ms': ms, 'detail': f"{k.split(':')[0]} · {ms} ms"}
    code, _ = _netcheck_error(next(iter(res.values())))
    return {'status': 'fail', 'error': code,
            'detail': ' · '.join(h for h, _ in _NETCHECK_IP_TARGETS)}

def _netcheck_hosts():
    """The hosts an update check and its download talk to."""
    hosts = [urllib.parse.urlparse(OTA_MANIFEST_BASE).hostname,
             urllib.parse.urlparse(OTA_PROD_MIRROR_BASE).hostname,
             'api.github.com', 'github.com']
    return [h for i, h in enumerate(hosts) if h and h not in hosts[:i]]

def _netcheck_dns():
    device, _ = _active_device()
    servers = _device_ipv4_runtime(device)['dns'] if device else []
    hosts = _netcheck_hosts()
    res = _netcheck_parallel({h: (lambda h=h: socket.getaddrinfo(h, 443, proto=socket.IPPROTO_TCP))
                              for h in hosts}, 6)
    failed = [h for h, v in res.items() if isinstance(v, Exception)]
    out = {'servers': servers, 'failed': failed, 'detail': ', '.join(servers) if servers else ''}
    if len(failed) == len(hosts):
        code, _ = _netcheck_error(res[hosts[0]])
        out.update(status='fail', error='dns' if code == 'dns' else code)
    elif failed:
        out.update(status='warn', error='dnsPartial')
    else:
        out['status'] = 'ok'
    return out

def _netcheck_ntp():
    try:
        v = _run(['timedatectl', 'show', '-p', 'NTPSynchronized', '--value'], timeout=5).stdout.strip()
        return v == 'yes'
    except Exception:
        return None

def _netcheck_fetch(url, headers=None, limit=1 << 20, timeout=8):
    """GET `url`; returns (info dict, body bytes or None). Never raises."""
    host = urllib.parse.urlparse(url).hostname
    info = {'host': host, 'url': url}
    req = urllib.request.Request(url, headers={'User-Agent': _NETCHECK_UA, **(headers or {})})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(limit)
            info['http'] = resp.status
            info['date'] = resp.headers.get('Date')
            final = urllib.parse.urlparse(resp.geturl()).hostname
            if final and final != host:
                info['via'] = final
        info['ms'] = round((time.monotonic() - t0) * 1000)
        info['bytes'] = len(body)
        info['status'] = 'ok'
        return info, body
    except Exception as e:
        code, http = _netcheck_error(e)
        info.update(status='fail', error=code, ms=round((time.monotonic() - t0) * 1000))
        if http:
            info['http'] = http
        return info, None

def _netcheck_ota(channel):
    """The update check's own sources, in the order the device tries them
    (see _fetch_release()). Returns (step, first manifest that answered,
    the Date headers seen — for the clock step)."""
    sources = {'pages': f'{OTA_MANIFEST_BASE}/latest-{channel}.json',
               'mirror': f'{OTA_PROD_MIRROR_BASE}/latest-{channel}.json'}
    # /rate_limit tells whether the last-resort fallback would work, and
    # doesn't count against the 60 requests an hour itself
    sources['github'] = 'https://api.github.com/rate_limit'
    res = _netcheck_parallel({k: (lambda u=u: _netcheck_fetch(u)) for k, u in sources.items()}, 12)
    rows, manifest, dates = [], None, []
    for key in sources:
        r = res[key]
        if isinstance(r, Exception):
            code, _ = _netcheck_error(r)
            info, body = {'host': urllib.parse.urlparse(sources[key]).hostname,
                          'status': 'fail', 'error': code}, None
        else:
            info, body = r
        info['id'] = key
        if info.get('date'):
            dates.append(info['date'])
        if body is not None:
            try:
                data = json.loads(body)
            except Exception:
                data = None
            if key == 'github':
                core = ((data or {}).get('resources') or {}).get('core') or {}
                info['remaining'] = core.get('remaining')
                if core.get('remaining') == 0:
                    info.update(status='warn', error='rateLimited')
            elif not (isinstance(data, dict) and data.get('tag_name')):
                info.update(status='fail', error='badManifest')
            else:
                info['tag'] = data['tag_name']
                manifest = manifest or data
        info.pop('date', None)
        rows.append(info)
    by_id = {r['id']: r for r in rows}
    if by_id['pages']['status'] == 'ok':
        status, error = 'ok', None
    elif manifest is not None or by_id['github']['status'] == 'ok':
        # the device gets there through a fallback: updates still work
        status, error = 'warn', 'fallback'
    else:
        status, error = 'fail', 'otaDown'
    step = {'status': status, 'channel': channel, 'sources': rows,
            'detail': by_id['pages'].get('tag') or ''}
    if error:
        step['error'] = error
    return step, manifest, dates

def _netcheck_download(manifest):
    """First MiB of the payload this device would download: the same host,
    redirects and speed the real update gets."""
    if not manifest:
        return {'status': 'skip'}
    image = _image_mode() or _ab_ready()
    wanted = [(IMAGE_PREFIX, '.raucb')] if image else [(p, '.tar.gz') for p in OTA_UI_PREFIX] + [(SYS_PREFIX, '.tar.gz')]
    assets = manifest.get('assets') or []
    asset = next((a for pfx, sfx in wanted for a in assets
                  if str(a.get('name', '')).startswith(pfx) and str(a.get('name', '')).endswith(sfx)
                  and a.get('browser_download_url')), None)
    if not asset:
        return {'status': 'skip'}
    info, body = _netcheck_fetch(asset['browser_download_url'], headers={'Range': 'bytes=0-1048575'},
                                 timeout=15)
    out = {'status': info['status'], 'host': info['host'], 'asset': asset.get('name')}
    for k in ('via', 'http', 'ms', 'error'):
        if info.get(k) is not None:
            out[k] = info[k]
    if body is not None and info.get('ms'):
        out['kbps'] = round(len(body) / 1024 / (info['ms'] / 1000))
    out['detail'] = info.get('via') or info['host']
    return out

def _netcheck_clock(ntp, dates):
    """The clock against the Date header of the servers that answered: TLS
    certificates are refused by a box whose clock is far off. What counts is
    that measured offset, not the NTP flag: the image may run no NTP client
    at all and keep good time from the RTC (`ntp` is reported, not judged)."""
    out = {'ntp': ntp, 'detail': time.strftime('%Y-%m-%d %H:%M'), 'status': 'ok'}
    skews = []
    for d in dates:
        try:
            skews.append(time.time() - email.utils.parsedate_to_datetime(d).timestamp())
        except Exception:
            pass
    if skews:
        skew = round(min(skews, key=abs))
        out['skew'] = skew
        out['detail'] += f' · {skew:+d} s'
        if abs(skew) > 3600:
            out.update(status='fail', error='clockOff')
        elif abs(skew) > 120:
            out.update(status='warn', error='clockOff')
    elif time.gmtime().tm_year < 2025:
        out.update(status='fail', error='clockOff')
    return out

def network_check():
    with _NETCHECK_LOCK:
        channel = get_ota_channel()
        steps = {'link': _netcheck_link()}
        if steps['link']['status'] == 'fail':
            # no address, nothing further can work: don't list seven failures
            for k in NETCHECK_STEPS[1:]:
                steps[k] = {'status': 'skip'}
        else:
            res = _netcheck_parallel({'router': _netcheck_router, 'internet': _netcheck_internet,
                                      'dns': _netcheck_dns, 'ntp': _netcheck_ntp,
                                      'ota': lambda: _netcheck_ota(channel)}, 20)
            for k in ('router', 'internet', 'dns'):
                v = res[k]
                steps[k] = v if isinstance(v, dict) else {'status': 'fail', 'error': _netcheck_error(v)[0]}
            ota = res['ota']
            manifest, dates = None, []
            if isinstance(ota, tuple):
                steps['ota'], manifest, dates = ota
            else:
                steps['ota'] = {'status': 'fail', 'error': _netcheck_error(ota)[0], 'channel': channel}
            ntp = res['ntp'] if isinstance(res['ntp'], bool) else None
            steps['clock'] = _netcheck_clock(ntp, dates)
            try:
                steps['download'] = _netcheck_download(manifest)
            except Exception as e:
                steps['download'] = {'status': 'fail', 'error': _netcheck_error(e)[0]}
            # A later hop that works proves the earlier one does too: a router
            # that ignores ping, or a network that blocks the raw-IP probes
            # but lets the update server through, is not where the fault is.
            ota_ok = steps['ota']['status'] != 'fail'
            if steps['router']['status'] == 'fail' and steps['router'].get('gateway') \
                    and (steps['internet']['status'] == 'ok' or ota_ok):
                steps['router'].update(status='ok', error='noPing')
            if steps['internet']['status'] == 'fail' and ota_ok:
                steps['internet'].update(status='warn', error='blockedIps')
        out = [dict(steps[k], id=k) for k in NETCHECK_STEPS]
        verdict = next((s['id'] for s in out if s['status'] == 'fail'), None)
        warn = next((s['id'] for s in out if s['status'] == 'warn'), None)
        return {'success': True, 'channel': channel, 'at': int(time.time()),
                'verdict': verdict or 'ok', 'warn': warn, 'steps': out}

# ──────────────────────────────────────────────────────────────────
#  Connectivity at a glance: the three states an OS's tray icon shows
#  ("internet", "lan" = only the local network, "offline"), for the
#  kiosk's top bar. Cheap on purpose (one ping, one TCP connect, a
#  couple of seconds at worst) and cached, since the UI asks every
#  few seconds; the full story is the network check above.
# ──────────────────────────────────────────────────────────────────
CONNECTIVITY_TTL = 10        # seconds a result is served from the cache
_CONNECTIVITY_LOCK = threading.Lock()
_connectivity_cache = {'at': 0.0, 'result': None}

def _conn_router_ok(gw):
    """Whether the gateway answers: one ping, or, failing that, a live ARP
    entry (plenty of routers ignore ping)."""
    try:
        r = _run(['ping', '-n', '-q', '-c', '1', '-W', '1', gw], timeout=4)
        if re.search(r'packets transmitted, [1-9]\d* received', r.stdout):
            return True
        n = _run(['ip', 'neigh', 'show', gw], timeout=3).stdout
        return 'lladdr' in n and not re.search(r'\b(FAILED|INCOMPLETE)\b', n)
    except Exception:
        return False

def _conn_internet_ok():
    """Whether at least one of the raw-IP HTTPS targets answers a TCP connect."""
    res = _netcheck_parallel({f'{h}:{p}': (lambda h=h, p=p: _netcheck_tcp(h, p, timeout=2))
                              for h, p in _NETCHECK_IP_TARGETS}, 2.5)
    return any(isinstance(v, int) for v in res.values())

def _connectivity_probe():
    device, dtype = _active_device()
    ip = _device_ip(device) if device else None
    typ = 'wireless' if dtype == 'wifi' else ('wired' if dtype == 'ethernet' else 'none')
    out = {'state': 'offline', 'type': typ, 'device': device, 'ip': ip,
           'ssid': _active_ssid() if dtype == 'wifi' else None, 'gateway': None, 'router': False}
    if not ip:
        return out
    try:
        gw = _default_gateway()
    except Exception:
        gw = None
    out['gateway'] = gw
    res = _netcheck_parallel({'router': (lambda: _conn_router_ok(gw)) if gw else (lambda: False),
                              'internet': _conn_internet_ok}, 4)
    out['router'] = res['router'] is True
    if res['internet'] is True:
        # a reply from the outside proves the router works, ping or not
        out.update(state='internet', router=True)
    elif out['router']:
        out['state'] = 'lan'
    # an address but a router that neither answers nor shows in ARP: the
    # link is up but leads nowhere, which for the owner is "offline"
    return out

def get_connectivity(force=False):
    now = time.monotonic()
    with _CONNECTIVITY_LOCK:
        c = _connectivity_cache
        if not force and c['result'] is not None and now - c['at'] < CONNECTIVITY_TTL:
            return dict(c['result'])
        try:
            res = _connectivity_probe()
        except Exception as e:
            logging.warning('connectivity probe failed: %s', e)
            res = {'state': 'offline', 'type': 'none', 'device': None, 'ip': None,
                   'ssid': None, 'gateway': None, 'router': False}
        res['at'] = int(time.time())
        c['result'] = res
        c['at'] = time.monotonic()
        return dict(res)

def _wifi_band(freq):
    """'2.4', '5' or '6' from the frequency nmcli prints ('2462 MHz'), '' when
    it makes no sense.

    A home router almost always broadcasts the same SSID on 2.4 and 5 GHz, and
    a scan list that shows that name twice with nothing to tell the two rows
    apart is unusable — hence the band on every network, and the band the
    owner picked carried all the way down to the profile (see
    _wifi_band_args)."""
    try:
        mhz = int(str(freq).strip().split()[0])
    except (TypeError, ValueError, IndexError):
        return ''
    if 2400 <= mhz < 2500:
        return '2.4'
    if 4900 <= mhz < 5925:
        return '5'
    if 5925 <= mhz <= 7125:
        return '6'
    return ''


def _signal_int(value):
    """The SIGNAL column as a number; nmcli prints it as text and can leave it
    empty."""
    try:
        return int(str(value).strip() or 0)
    except ValueError:
        return 0


def _wifi_band_args(band):
    """`802-11-wireless.band` for a band the owner picked from the scan list.

    Only set when the UI says the choice was a real one (an SSID that appears
    on more than one band): pinning a profile that has nowhere else to go
    would only give NetworkManager one more way to fail."""
    if band == '2.4':
        return ['802-11-wireless.band', 'bg']
    if band in ('5', '6'):
        return ['802-11-wireless.band', 'a']
    return []


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
            r = _run(['nmcli', '-t', '-f', 'IN-USE,SSID,SIGNAL,SECURITY,FREQ', 'device', 'wifi', 'list'])
            # One row per band, not per access point: a mesh or a repeater puts
            # the same SSID on the same band several times over, and those are
            # the rows nobody can choose between. Strongest signal wins.
            by_band = {}
            order = []
            for line in r.stdout.strip().split('\n'):
                if not line:
                    continue
                parts = _terse_split(line)
                if len(parts) < 5:
                    continue
                in_use, ssid, signal_, security, freq = parts[0], parts[1], parts[2], parts[3], parts[4]
                if not ssid:
                    continue
                net = {
                    'ssid': ssid,
                    'signal': signal_,
                    'security': security,
                    'in_use': in_use == '*',
                    'band': _wifi_band(freq),
                }
                key = (ssid, net['band'])
                prev = by_band.get(key)
                if prev is None:
                    by_band[key] = net
                    order.append(key)
                else:
                    if _signal_int(net['signal']) > _signal_int(prev['signal']):
                        prev.update(signal=net['signal'], security=net['security'])
                    prev['in_use'] = prev['in_use'] or net['in_use']
            networks = [by_band[k] for k in order]
            if networks or attempt == 5:
                break
            time.sleep(1)
    except Exception:
        log.exception("wifi_scan failed")
        return {'networks': [], 'error': _t('network.scanFailed', _lang())}
    # "Saved", as a phone shows it: NetworkManager still has a profile (and
    # so the key) for these, and the UI joins them without asking for it.
    try:
        saved = set(_connection_ids_for_device_type('wifi'))
    except Exception:
        saved = set()
    for net in networks:
        net['saved'] = net['ssid'] in saved
    return {'networks': networks}

def _scan_security(ssid):
    """The SECURITY column NetworkManager reports for this SSID, or None when
    the SSID isn't in its scan list at all. '' is a meaningful answer — an
    open network — so "never seen" has to stay distinguishable from it."""
    try:
        r = _run(['nmcli', '-t', '-f', 'SSID,SECURITY', 'device', 'wifi', 'list'])
        for line in r.stdout.strip().split('\n'):
            parts = _terse_split(line)
            if len(parts) >= 2 and parts[0] == ssid:
                return parts[1].strip()
    except Exception:
        pass
    return None


def _wifi_security_args(ssid, password):
    """`nmcli connection add` arguments for this network's security.

    `nmcli device wifi connect` takes these from the access point itself, so
    building the profile by hand (see _wifi_join) means working out the key
    management here: a WPA3-only AP needs `sae`, WEP needs a key or a
    passphrase rather than a PSK, and a network that really is open must carry
    no security setting at all. Anything else — including an SSID missing from
    the scan list — falls back to WPA-PSK, which is what home networks use."""
    if not password:
        return []
    sec = _scan_security(ssid)
    if sec == '':          # seen in the scan, and reported as open
        return []
    sec = (sec or '').upper()
    if 'WEP' in sec:
        # Same rule nmcli uses: a value of exactly key length is a raw key,
        # anything else is a passphrase (1 = key, 2 = passphrase).
        is_key = re.fullmatch(r'[0-9a-fA-F]{10}|[0-9a-fA-F]{26}|.{5}|.{13}', password)
        return ['802-11-wireless-security.key-mgmt', 'none',
                '802-11-wireless-security.wep-key0', password,
                '802-11-wireless-security.wep-key-type', '1' if is_key else '2']
    # A WPA2/WPA3 transition AP advertises both and still takes wpa-psk; only
    # a WPA3-only one has to be joined with SAE.
    if 'WPA3' in sec and 'WPA2' not in sec and 'WPA1' not in sec:
        return ['802-11-wireless-security.key-mgmt', 'sae',
                '802-11-wireless-security.psk', password]
    return ['802-11-wireless-security.key-mgmt', 'wpa-psk',
            '802-11-wireless-security.psk', password]


def _wifi_profile_exists(ssid):
    """True when NetworkManager already has a Wi-Fi profile under this name —
    which is what both nmcli and we name a profile after its SSID."""
    return ssid in _connection_ids_for_device_type('wifi')


def _preserved_ipv4_args(conn):
    """`connection add` arguments that carry a profile's fixed address over to
    the profile that replaces it.

    Rebuilding the profile is what makes the join work at all (see _wifi_join),
    but on its own it would quietly drop a fixed address the owner had set on
    that same Wi-Fi network: the box would come back over DHCP at a different
    address, which on a headless unit is indistinguishable from it having
    disappeared. Only a 'manual' profile has anything worth carrying — a DHCP
    one is already what a fresh profile does."""
    cfg = _nm_connection_ipv4(conn)
    if cfg.get('method') != 'manual' or not cfg.get('address'):
        return []
    args = ['ipv4.method', 'manual',
            'ipv4.addresses', f"{cfg['address']}/{cfg.get('prefix') or 24}"]
    if cfg.get('gateway'):
        args += ['ipv4.gateway', cfg['gateway']]
    if cfg.get('dns'):
        args += ['ipv4.dns', ' '.join(cfg['dns'][:3]), 'ipv4.ignore-auto-dns', 'yes']
    return args


def _wifi_join(ssid, password, dev, band=''):
    """Join `ssid`, returning the CompletedProcess of the step that decided it.

    When a password is given the connection profile is built here
    (`connection add` + `connection up`) rather than through the
    `nmcli device wifi connect` shorthand. The shorthand only works the first
    time a network is used: once a profile for that SSID exists it pushes the
    new password into that profile as a bare `psk` with no `key-mgmt`, and
    NetworkManager rejects the whole update with
    "802-11-wireless-security.key-mgmt: property is missing" (issue #98).
    Re-joining a network the box had already been on — exactly what someone
    does after a spell on the cable — therefore always failed, and no amount
    of retyping the password could help. Dropping the stale profile first and
    spelling out key-mgmt ourselves removes both halves of that.

    With no password there is nothing to write, so a saved profile is
    activated as it stands (its stored secret is still good) and only a
    network we have no profile for goes through the shorthand.

    `band` is the band the owner picked from a dual-band SSID: without it
    NetworkManager joins whichever of the two it likes, which would make the
    two rows in the list the same row."""
    band_args = _wifi_band_args(band)
    if not password:
        if _wifi_profile_exists(ssid):
            # The stored secret is still good — only the chosen band has to be
            # written onto the profile before it comes up.
            if band_args:
                _run(['nmcli', 'connection', 'modify', 'id', ssid] + band_args)
            return _run(['nmcli', 'connection', 'up', 'id', ssid], timeout=45)
        if not band_args:
            return _run(['nmcli', 'device', 'wifi', 'connect', ssid], timeout=45)
        # An open network on a chosen band: the shorthand can't pin one, so
        # build the profile here too (_wifi_security_args gives nothing back
        # for an empty password, which is exactly what an open AP wants).

    sec_args = _wifi_security_args(ssid, password)
    # Read before the delete, write back into the replacement: the admin web UI
    # can put a fixed address on a Wi-Fi profile too, and it lives on the very
    # profile being rebuilt here.
    ip_args = _preserved_ipv4_args(ssid) if _wifi_profile_exists(ssid) else []
    _run(['nmcli', 'connection', 'delete', 'id', ssid])   # clear any stale profile
    add = ['nmcli', 'connection', 'add', 'type', 'wifi', 'con-name', ssid, 'ssid', ssid]
    if dev:
        add += ['ifname', dev]
    r = _run(add + sec_args + band_args + ip_args)
    if r.returncode != 0:
        return r
    # Association can still fail transiently on marginal signal, so one retry
    # before calling it a failure (same reasoning as webui_server.py's
    # _connect_wifi). Kept to two attempts on purpose: the admin web UI proxies
    # this call and gives up on the whole request after 90s.
    for attempt in range(2):
        r = _run(['nmcli', 'connection', 'up', 'id', ssid], timeout=30)
        if r.returncode == 0:
            return r
        if attempt == 0:
            time.sleep(2)
    # Don't leave a profile that can't associate lying around: it would be the
    # stale profile the next attempt trips over, and until then NetworkManager
    # keeps retrying it with a password we already know doesn't work.
    _run(['nmcli', 'connection', 'delete', 'id', ssid])
    return r


def wifi_connect(ssid, password, band=''):
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
    if band not in ('', '2.4', '5', '6'):
        band = ''
    dev = _first_device_of_type('wifi')
    _ensure_networkmanager_state(dev)
    try:
        r = _wifi_join(ssid, password, dev, band)
    except subprocess.TimeoutExpired:
        return {'success': False, 'code': 'network.connectTimeout',
                'message': _t('network.connectTimeout', _lang())}
    except Exception:
        log.exception("wifi_connect failed")
        return {'success': False, 'code': 'network.connectFailed',
                'message': _t('network.connectFailed', _lang())}
    if r.returncode == 0:
        msg = _t('network.connected', _lang(), ssid=ssid)
        # The Wi-Fi interface by name, not _active_device(): that one prefers
        # Ethernet, so on a box joining Wi-Fi while still cabled it handed back
        # the *wired* address — and the exclusivity flip below then unplugged
        # the cable on the strength of the cable's own IP.
        ip = _ensure_dhcp_ip(dev) if dev else None
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
#  Static IPv4 (NetworkManager) — admin-webui only.
#
#  The kiosk Settings screen deliberately has no equivalent: mistyping an
#  address there strands a headless box, and the remote admin at least
#  reaches the owner's browser where the "you must reconnect at the new
#  address" warning can be shown.
#
#  Everything goes through the *connection profile* (nmcli connection
#  modify), never `ip addr add` like the legacy /configure_network route
#  below — a runtime-only address is gone at the next reboot or NM restart,
#  and writing /etc/resolv.conf by hand is undone by NetworkManager anyway.
# ──────────────────────────────────────────────────────────────────

def _valid_prefix(prefix):
    """True for a usable IPv4 CIDR prefix. /31 and /32 leave no room for a
    host+gateway pair on a LAN, so they're rejected rather than silently
    producing an unreachable box."""
    try:
        return 1 <= int(prefix) <= 30
    except (TypeError, ValueError):
        return False

def _ipv4_to_int(addr):
    a, b, c, d = (int(p) for p in addr.split('.'))
    return (a << 24) | (b << 16) | (c << 8) | d

def _same_subnet(a, b, prefix):
    mask = (0xFFFFFFFF << (32 - int(prefix))) & 0xFFFFFFFF
    return (_ipv4_to_int(a) & mask) == (_ipv4_to_int(b) & mask)

def _assignable_host(addr, prefix):
    """Reject addresses that are valid dotted-quads but can't be a host on a
    LAN: loopback/multicast/reserved ranges, and the subnet's own network and
    broadcast addresses."""
    first = int(addr.split('.')[0])
    if first == 0 or first == 127 or first >= 224:
        return False
    host_bits = 32 - int(prefix)
    val = _ipv4_to_int(addr)
    mask = (0xFFFFFFFF << host_bits) & 0xFFFFFFFF
    if val == (val & mask):            # network address
        return False
    if val == ((val & mask) | ((1 << host_bits) - 1)):   # broadcast address
        return False
    return True

def _parse_dns(dns):
    """Accept a list, or a string with comma/space/semicolon separators."""
    if dns is None:
        return []
    if isinstance(dns, str):
        parts = re.split(r'[,;\s]+', dns.strip())
    elif isinstance(dns, (list, tuple)):
        parts = [str(p).strip() for p in dns]
    else:
        return None
    return [p for p in parts if p]

def _nm_connection_ipv4(conn):
    """ipv4.* settings as stored in the connection profile (what survives a
    reboot), as opposed to whatever the interface happens to carry now."""
    out = {'method': None, 'address': None, 'prefix': None, 'gateway': None, 'dns': []}
    if not conn:
        return out
    try:
        r = _run(['nmcli', '-t', '-f', 'ipv4.method,ipv4.addresses,ipv4.gateway,ipv4.dns',
                  'connection', 'show', conn])
    except Exception:
        return out
    for line in r.stdout.strip().split('\n'):
        parts = _terse_split(line)
        if len(parts) < 2:
            continue
        key, val = parts[0].strip(), parts[1].strip()
        if val in ('', '--'):
            continue
        if key == 'ipv4.method':
            out['method'] = val
        elif key == 'ipv4.addresses':
            first = val.split(',')[0].strip()
            if '/' in first:
                addr, _, prefix = first.partition('/')
                out['address'] = addr.strip()
                try:
                    out['prefix'] = int(prefix)
                except ValueError:
                    pass
            else:
                out['address'] = first
        elif key == 'ipv4.gateway':
            out['gateway'] = val
        elif key == 'ipv4.dns':
            out['dns'] = [d.strip() for d in val.split(',') if d.strip()]
    return out

def _device_ipv4_runtime(device):
    """Address/prefix/gateway/DNS the interface is actually using right now —
    used to pre-fill the static form with the working DHCP values, so
    "keep this address, just make it permanent" needs no typing."""
    out = {'address': None, 'prefix': None, 'gateway': None, 'dns': []}
    if not device:
        return out
    try:
        r = _run(['nmcli', '-t', '-f', 'IP4.ADDRESS,IP4.GATEWAY,IP4.DNS', 'device', 'show', device])
    except Exception:
        return out
    for line in r.stdout.strip().split('\n'):
        parts = _terse_split(line)
        if len(parts) < 2:
            continue
        key, val = parts[0].strip(), parts[1].strip()
        if not val or val == '--':
            continue
        if key.startswith('IP4.ADDRESS') and out['address'] is None:
            addr, _, prefix = val.partition('/')
            out['address'] = addr.strip()
            try:
                out['prefix'] = int(prefix)
            except ValueError:
                pass
        elif key.startswith('IP4.GATEWAY'):
            out['gateway'] = val
        elif key.startswith('IP4.DNS'):
            out['dns'].append(val)
    return out

def get_ipv4_config():
    """Current addressing of the uplink the admin is talking to us over."""
    device, dtype = _active_device()
    if not device:
        return {'success': False, 'code': 'network.noActiveConnection',
                'message': _t('network.noActiveConnection', _lang())}
    conn = _active_connection_name(device)
    profile = _nm_connection_ipv4(conn)
    runtime = _device_ipv4_runtime(device)
    mode = 'manual' if profile.get('method') == 'manual' else 'auto'
    return {
        'success': True,
        'device': device,
        'type': 'wireless' if dtype == 'wifi' else 'wired',
        'connection': conn,
        'mode': mode,
        # For a manual profile these are what was configured; for DHCP they're
        # the live lease, so switching to static starts from a working setup.
        'address': profile['address'] if mode == 'manual' else runtime['address'],
        'prefix': (profile['prefix'] if mode == 'manual' else runtime['prefix']) or 24,
        'gateway': profile['gateway'] if mode == 'manual' else runtime['gateway'],
        'dns': profile['dns'] if mode == 'manual' else runtime['dns'],
        'current_ip': runtime['address'],
    }

def _bg_apply_ipv4(conn, device, expect_ip):
    """Re-activate the profile after the HTTP reply has been flushed.

    `nmcli connection up` tears the address down and back up, which kills the
    very TCP connection carrying this request when the admin is on the LAN —
    so the route answers first and the activation happens here.

    If the interface never comes back with the requested address the profile
    is put back on DHCP: a box that silently keeps a broken static address is
    unreachable with no way in short of a keyboard and monitor. A *reachable*
    address that simply routes badly (wrong gateway for the LAN) is left
    alone — that's the owner's explicit choice, and the up-front subnet check
    already rejects the common typo.
    """
    time.sleep(1.5)
    try:
        _run(['nmcli', 'connection', 'up', conn], timeout=60)
    except Exception:
        log.exception('ipv4 apply: bringing %s up failed', conn)
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        ip = _device_ip(device)
        if ip and (expect_ip is None or ip == expect_ip):
            log.info('ipv4 apply: %s is up on %s', device, ip)
            return
        time.sleep(1)
    log.error('ipv4 apply: %s never reached %s — reverting to DHCP',
              device, expect_ip or 'a lease')
    try:
        _run(['nmcli', 'connection', 'modify', conn,
              'ipv4.addresses', '', 'ipv4.gateway', '', 'ipv4.dns', '',
              'ipv4.ignore-auto-dns', 'no', 'ipv4.method', 'auto'], timeout=20)
        _run(['nmcli', 'connection', 'up', conn], timeout=60)
    except Exception:
        log.exception('ipv4 apply: DHCP rollback failed for %s', conn)

def set_ipv4_config(cfg):
    cfg = cfg or {}
    mode = str(cfg.get('mode') or '').strip().lower()
    # 'dhcp'/'static' are what the legacy /configure_network body called them;
    # accepted here too so either vocabulary works.
    mode = {'dhcp': 'auto', 'static': 'manual'}.get(mode, mode)
    if mode not in ('auto', 'manual'):
        return {'success': False, 'code': 'network.invalidMode',
                'message': _t('network.invalidMode', _lang(), mode=cfg.get('mode'))}

    device, dtype = _active_device()
    if not device:
        return {'success': False, 'code': 'network.noActiveConnection',
                'message': _t('network.noActiveConnection', _lang())}
    conn = _active_connection_name(device)
    if not conn:
        return {'success': False, 'code': 'network.noProfile',
                'message': _t('network.noProfile', _lang(), device=device)}

    if mode == 'auto':
        args = ['ipv4.addresses', '', 'ipv4.gateway', '', 'ipv4.dns', '',
                'ipv4.ignore-auto-dns', 'no', 'ipv4.method', 'auto']
        expect_ip = None
        new_ip = None
    else:
        address = str(cfg.get('address') or cfg.get('ip') or '').strip()
        gateway = str(cfg.get('gateway') or '').strip()
        prefix = cfg.get('prefix', 24)
        if not _valid_ipv4(address):
            return {'success': False, 'code': 'network.invalidAddress',
                    'message': _t('network.invalidAddress', _lang(), address=address)}
        if not _valid_prefix(prefix):
            return {'success': False, 'code': 'network.invalidPrefix',
                    'message': _t('network.invalidPrefix', _lang(), prefix=prefix)}
        prefix = int(prefix)
        if not _assignable_host(address, prefix):
            return {'success': False, 'code': 'network.unusableAddress',
                    'message': _t('network.unusableAddress', _lang(), address=address)}
        # The gateway has to be a real host too: the subnet's network or
        # broadcast address passes _same_subnet but can never answer ARP, and
        # pointing it at our own address is a silent no-route-out.
        if not _valid_ipv4(gateway) or not _assignable_host(gateway, prefix) or gateway == address:
            return {'success': False, 'code': 'network.invalidGateway',
                    'message': _t('network.invalidGateway', _lang(), gateway=gateway)}
        if not _same_subnet(address, gateway, prefix):
            # NM would accept the profile and then fail to install a default
            # route, leaving a box with an address but no way off the LAN.
            return {'success': False, 'code': 'network.gatewayOutsideSubnet',
                    'message': _t('network.gatewayOutsideSubnet', _lang(),
                                  gateway=gateway, address=address, prefix=prefix)}
        dns = _parse_dns(cfg.get('dns'))
        if dns is None:
            return {'success': False, 'code': 'network.invalidDns',
                    'message': _t('network.invalidDns', _lang(), dns=cfg.get('dns'))}
        for d in dns:
            if not _valid_ipv4(d):
                return {'success': False, 'code': 'network.invalidDns',
                        'message': _t('network.invalidDns', _lang(), dns=d)}
        # Without a resolver a static box can still be reached by IP but
        # nothing it does (streaming services, updates) resolves — fall back
        # to the router, which is the resolver on virtually every home LAN.
        if not dns:
            dns = [gateway]
        args = ['ipv4.addresses', f'{address}/{prefix}',
                'ipv4.gateway', gateway,
                'ipv4.dns', ' '.join(dns[:3]),
                'ipv4.ignore-auto-dns', 'yes',
                'ipv4.method', 'manual']
        expect_ip = address
        new_ip = address

    try:
        r = _run(['nmcli', 'connection', 'modify', conn] + args, timeout=25)
    except Exception:
        log.exception('set_ipv4_config: nmcli modify failed')
        return {'success': False, 'code': 'network.ipv4ApplyFailed',
                'message': _t('network.ipv4ApplyFailed', _lang())}
    if r.returncode != 0:
        return {'success': False, 'code': 'network.ipv4ApplyFailed',
                'message': (r.stderr or r.stdout).strip() or _t('network.ipv4ApplyFailed', _lang())}

    # A profile that doesn't auto-connect would come back on a *different*
    # (or no) address after a reboot, defeating the point of a fixed address.
    try:
        _run(['nmcli', 'connection', 'modify', conn, 'connection.autoconnect', 'yes'], timeout=15)
    except Exception:
        pass

    threading.Thread(target=_bg_apply_ipv4, args=(conn, device, expect_ip), daemon=True).start()

    code = 'network.staticApplying' if mode == 'manual' else 'network.dhcpApplying'
    return {'success': True, 'code': code,
            'message': _t(code, _lang(), address=new_ip or ''),
            'mode': mode, 'device': device, 'address': new_ip}

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
        content = "ARGS='-o default -D -v -C 5 -s 127.0.0.1 -n OsmiumSound -M Osmium'\n"

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
        content += f"\nARGS='-o {device} -D -v -C 5 -s 127.0.0.1 -n OsmiumSound -M Osmium'\n"

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

# A DNS name for an external Lyrion server (nas.lan, lms.example.com,
# osmium.local). Letters, digits and hyphens per label only: the name ends up
# inside squeezelite's ARGS='...' line, so no quote, space or shell character
# may get through.
_HOSTNAME_LABEL_RE = re.compile(r'^(?!-)[a-z0-9-]{1,63}(?<!-)$')

def _valid_hostname(name):
    if not isinstance(name, str) or not name or len(name) > 253:
        return False
    labels = name.split('.')
    # All-numeric names are malformed IPv4 addresses, not host names.
    if all(l.isdigit() for l in labels):
        return False
    return all(_HOSTNAME_LABEL_RE.match(l) for l in labels)

def _resolves(name, timeout=5):
    """True if the name resolves to an address, giving up after `timeout` s
    (getaddrinfo has no timeout of its own and a dead DNS can hang for 30 s)."""
    result = []
    def lookup():
        try:
            result.append(bool(socket.getaddrinfo(name, 9000, proto=socket.IPPROTO_TCP)))
        except OSError:
            result.append(False)
    th = threading.Thread(target=lookup, daemon=True)
    th.start()
    th.join(timeout)
    return bool(result and result[0])

def get_lms_role():
    host = _current_lms_host()
    if host == '127.0.0.1':
        return {'mode': 'local', 'host': None}
    return {'mode': 'follow', 'host': host}

def _set_local_lyrion_enabled(enable):
    """Start+enable, or stop+disable, this device's OWN Lyrion Music Server.

    Following another server does not merely make the local one redundant: as
    long as it keeps running it still answers on 127.0.0.1:9000, and anything
    that reaches loopback before it has read this role talks to that empty
    local server instead of the one being followed. The kiosk resolves the
    server address asynchronously at startup (Api::refreshLmsHost), so on a
    boot where the answer is late it latches onto the local one — which is the
    "sometimes it connects to the local server anyway" owners report. Stopping
    it is not enough on its own: without `disable` the unit comes straight back
    at the next boot, so the choice would only hold until the next restart.

    Best effort: the role itself is already persisted in
    /etc/default/squeezelite by the time this runs, and a device that never
    installed Lyrion has a unit that cannot start (ConditionPathExists on
    /data/lyrion/current) or no unit at all — neither is a reason to report the
    role change as failed.
    """
    action = ['enable', '--now'] if enable else ['disable', '--now']
    try:
        if enable:
            # A deliberate start must not be vetoed by the unit's crash-loop
            # limit (five starts in five minutes), which counts every stop and
            # start the setup does too — see sources_server._systemctl_lyrion.
            _run(['systemctl', 'reset-failed', LYRION_UNIT], timeout=15)
        r = _run(['systemctl'] + action + [LYRION_UNIT], timeout=60)
        if r.returncode != 0:
            log.warning("set_lms_role: systemctl %s %s failed: %s",
                        action[0], LYRION_UNIT, (r.stderr or '').strip())
        return r.returncode == 0
    except Exception:
        log.exception("set_lms_role: systemctl %s %s failed", action[0], LYRION_UNIT)
        return False

def set_lms_role(mode, host):
    if mode == 'local':
        target = '127.0.0.1'
    elif mode == 'follow':
        host = host.strip().rstrip('.').lower() if isinstance(host, str) else host
        if not (_valid_ipv4(host) or _valid_hostname(host)):
            return {'success': False, 'code': 'lms.invalidHost',
                    'message': _t('lms.invalidHost', _lang(), host=host)}
        if host in ('127.0.0.1', 'localhost'):
            return {'success': False, 'code': 'lms.useLocalMode',
                    'message': _t('lms.useLocalMode', _lang())}
        # squeezelite resolves the name once when it starts; a typo would only
        # show after the reboot the owner is asked for next, as a player that
        # never connects. Check it here while there is still a form to fix it.
        if not _valid_ipv4(host) and not _resolves(host):
            return {'success': False, 'code': 'lms.hostNotFound',
                    'message': _t('lms.hostNotFound', _lang(), host=host)}
        target = host
    else:
        return {'success': False, 'code': 'lms.invalidMode',
                'message': _t('lms.invalidMode', _lang(), mode=mode)}

    _, args = _read_sq_args()
    if args is None:
        return {'success': False, 'code': 'lms.sqConfigMissing',
                'message': _t('lms.sqConfigMissing', _lang())}
    _write_sq_args(_sq_set_s(args, target))
    # Before the player restart below, so squeezelite comes back up with the
    # local server already stopped (following) or already running (standalone)
    # and can only land on the one that was just chosen.
    _set_local_lyrion_enabled(mode == 'local')

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
    # A boot that came up without its data partition writes to a tmpfs /etc:
    # the change applies right now and is gone at the next restart, with the
    # previous choice back — which is exactly how "I set it back and at
    # startup it is on the other server again" happens. Say so instead of
    # reporting a clean success.
    if _data_partition_mounted() is False:
        msg = msg + ' — ' + _t('lms.volatileBoot', _lang())
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

def _apply_hostname(name):
    """The OS-level half of a rename: hostnamectl + /etc/hosts + avahi/Lyrion
    re-announce. Split out of set_device_name so a backup restore (which
    restores /etc/hostname itself as plain "core" state — see hifi_backup.py)
    can re-apply just this half through /hostname_apply, without also forcing
    the Bluetooth/squeezelite player name to follow — set_player_name() below
    does that, and a restore already re-applies the player name independently
    from the restored /etc/default/squeezelite."""
    try:
        r = _run(['hostnamectl', 'set-hostname', name], timeout=10)
        if r.returncode != 0:
            return {'success': False, 'code': 'device.hostnameSetFailed',
                    'message': _t('device.hostnameSetFailed', _lang())}
    except Exception:
        log.exception("_apply_hostname: hostnamectl failed")
        return {'success': False, 'code': 'device.hostnameSetFailed',
                'message': _t('device.hostnameSetFailed', _lang())}
    _set_etc_hosts_hostname(name)
    try:
        # So the new <name>.local is announced immediately, without waiting
        # for a reboot — avahi-daemon doesn't watch /etc/hostname on its own.
        _run(['systemctl', 'restart', 'avahi-daemon'], timeout=15)
    except Exception:
        log.exception("_apply_hostname: avahi restart failed")
    try:
        # Lyrion Music Server bundles its OWN mDNS/Bonjour responder and reads
        # the hostname once at startup — restarting avahi-daemon above does
        # NOT make it re-announce, so without this it keeps advertising (and
        # answering for) the OLD <name>.local indefinitely, right alongside
        # the new one now served by avahi. Only bounce it if it's already
        # running: never turn on a local Lyrion instance the user has off
        # (e.g. this box follows an external server elsewhere on the LAN).
        if _run(['systemctl', 'is-active', '--quiet', 'lyrionmusicserver'], timeout=10).returncode == 0:
            _run(['systemctl', 'reset-failed', 'lyrionmusicserver'], timeout=15)
            _run(['systemctl', 'restart', 'lyrionmusicserver'], timeout=30)
    except Exception:
        log.exception("_apply_hostname: lyrionmusicserver restart failed")
    return {'success': True, 'name': name}


def set_device_name(name):
    if not _valid_device_name(name):
        return {'success': False, 'code': 'device.invalidName',
                'message': _t('device.invalidName', _lang())}
    result = _apply_hostname(name)
    if not result.get('success'):
        return result
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
    # Says whether this boot came up with its data partition — a boot that
    # fell back to a tmpfs /data runs on the image's factory settings and
    # silently drops everything written during it, which from the outside
    # looks like settings reverting on their own.
    'hifi-boot-health',
    # The A/B chain. Without these a device that did not convert looks exactly
    # like one that did nothing: the units enabled by the 0061 migration are
    # where the conversion is armed and carried out, and a bundle that does not
    # name them leaves "why is it still on the old layout" unanswerable.
    'hifi-rauc-config', 'hifi-ab-finish', 'hifi-ab-image', 'hifi-ab-firstboot',
    # Bluetooth speakers: the supervisor's journal is where a speaker that
    # never reconnects leaves its trail (bluetoothd's own log alone does not
    # say which player unit was started or why one wasn't).
    'hifi-bt-out',
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
    '/etc/hifi-player/ui-refresh',
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


def _support_ab_snapshot():
    """The A/B picture: image mode, booted slot, conversion state, and the
    pre-check verdict.

    🚨 The pre-check is RUN when its JSON is not there. That file lives in
    /run, so it is gone after every reboot, and it is the only thing that says
    why a device stayed on the old layout — a bundle collected the morning
    after an update would otherwise carry no answer at all. Running it is safe:
    it reports and changes nothing (see hifi-ab-precheck.sh)."""
    out = {}
    try:
        out = ab_status()
    except Exception as e:
        return {'error': f'ab_status failed: {e}'}
    if not out.get('precheck') and not out.get('image_mode'):
        try:
            r = subprocess.run([AB_PRECHECK_SCRIPT], capture_output=True, text=True, timeout=180)
            out['precheck_run'] = {'exit': r.returncode,
                                   'verdict': (r.stdout or r.stderr or '').strip()[:600]}
            with open(AB_PRECHECK_FILE) as f:
                out['precheck'] = json.load(f)
        except Exception as e:
            out['precheck_run'] = {'error': str(e)}
    return out


def _support_disks_snapshot():
    """Partition table, mounts and free space.

    The A/B conversion is a question about the disk — how many partitions,
    which one is the root, is there an ESP, how much room is left — and none of
    it was in the bundle, so every answer had to be asked of the owner by hand."""
    out = []
    for label, cmd in (
            ('lsblk', ['lsblk', '-o', 'NAME,MAJ:MIN,RM,SIZE,RO,TYPE,FSTYPE,PARTLABEL,MOUNTPOINT']),
            ('df', ['df', '-hT']),
            ('findmnt', ['findmnt', '--real', '-o', 'TARGET,SOURCE,FSTYPE,OPTIONS']),
            ('partitions', ['sfdisk', '-l']),
            ('efi', ['test', '-d', '/sys/firmware/efi'])):
        out.append(f'== {label} ==')
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            out.append((r.stdout or '').rstrip() or f'(exit {r.returncode}) {(r.stderr or "").strip()[:200]}')
        except Exception as e:
            out.append(f'({label} failed: {e})')
        out.append('')
    return '\n'.join(out) + '\n'


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

        try:
            z.writestr('ab_status.json', json.dumps(_support_ab_snapshot(), indent=2))
        except Exception as e:
            z.writestr('ab_status.json', json.dumps({'error': str(e)}))
        try:
            z.writestr('disks.txt', _support_disks_snapshot())
        except Exception as e:
            z.writestr('disks.txt', f'(disks snapshot failed: {e})\n')

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
#  Mouse pointer (cursor) control — shown by default (the on-device
#  first-boot QR/Wi-Fi setup wizard has a touch/mouse-driven manual-network
#  fallback that needs a visible cursor). A touchscreen-only owner can turn
#  it off from Settings, which starts unclutter to auto-hide it.
#  The choice is persisted and re-applied at login by ~/.xsession; here we
#  also apply it live so it takes effect without a reboot.
#  On the Wayland kiosk session (labwc) unclutter is inert — it is an X11
#  client and never sees the kiosk window. There the flag is read at login by
#  /usr/local/bin/hifi-kiosk-wayland, which hides the compositor's own pointer
#  with a transparent cursor theme; inside the window it is the UI's
#  `hifi-hide-cursor` class that applies live, so this toggle still takes
#  effect immediately where the pointer is actually visible.
#  NOTE: the cursor only ever appears once the X server is no longer started
#  with `-nocursor` (removed at build time + by OS-OTA migration); on an
#  un-migrated device a reboot is needed after that update for it to show.
# ──────────────────────────────────────────────────────────────────
POINTER_FILE = '/etc/hifi-player/pointer-enabled'

def _has_unclutter():
    return bool(shutil.which('unclutter'))

def get_pointer_status():
    """Return { available, enabled }. 'enabled' = pointer shown (cursor not
    auto-hidden). Defaults to enabled (shown) on a unit that has never set a
    preference — the on-device first-boot QR/Wi-Fi setup wizard needs the
    pointer visible to be usable; a touchscreen owner can still switch it off
    from Settings."""
    enabled = True
    try:
        with open(POINTER_FILE) as f:
            enabled = f.read().strip() != '0'
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
    # status files it still reads "running"/'staged_pending_reboot'/'applying'
    # across both reboots of the isolated update flow — which is exactly when
    # a display-mode switch or a factory reset would do the most damage (the
    # latter two states can only ever be observed in the brief window right
    # before/after the update-mode reboots, since hifi-api itself isn't
    # running while the apply half is actually working).
    try:
        if update_plan_status().get('state') in ('running', 'staged_pending_reboot', 'applying'):
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
#  Which on-screen interface runs: the Electron kiosk (historic) or the Qt
#  one (draws straight on DRM/KMS, no X and no compositor). They are mutually
#  exclusive — lightdm vs hifi-qt.service — and the switch is the same script
#  that handles gui/headless, so the two settings can't fight each other.
#
#  ABSENT state means 'electron', the same fleet-safety default as display
#  mode: a device that never chose must never change interface on its own
#  because of an update.
# ──────────────────────────────────────────────────────────────────
UI_ENGINE_FILE = '/etc/hifi-player/ui-engine'
UI_ENGINES = ('electron', 'qt')
QT_UI_BIN = '/opt/hifi-qt/hifi-qt'
ELECTRON_UI_DIR = '/opt/hifi-media-player'

def _electron_ui_installed():
    """The image ships the Qt interface only — Electron was 354 MiB of the
    2715 and went out to make room for /data. So Electron is no longer a given:
    it must be probed exactly like Qt, or a converted device whose /etc still
    says "electron" (the overlay carries the legacy setting over) would be
    offered an interface that isn't there and would come back to a black
    screen."""
    return os.path.isdir(ELECTRON_UI_DIR)

def _qt_ui_installed():
    """Vero solo se la seconda interfaccia puo' DAVVERO partire su questo
    apparecchio: il programma (dal pacchetto di sistema) e le librerie Qt che
    gli servono (dal pacchetto OS, l'unico che puo' installare pacchetti). Le
    due meta' viaggiano su canali diversi e possono arrivare separate: offrire
    la scelta con una meta' sola lascerebbe lo schermo nero al riavvio.
    Il modulo grafico che disegna su DRM/KMS e il modulo QML di base non sono
    librerie collegate al programma, quindi vanno cercati a parte."""
    if not (os.path.isfile(QT_UI_BIN) and os.access(QT_UI_BIN, os.X_OK)):
        return False
    return bool(glob.glob('/usr/lib/*/qt6/plugins/platforms/libqeglfs.so')
                and glob.glob('/usr/lib/*/qt6/qml/QtQuick/libqtquick2plugin.so'))

def get_ui_engine():
    """Return { engine, engines }. `engines` is what this device can actually
    run right now — the Qt option only appears once its files are installed,
    so an older unit that hasn't received them yet shows a single choice
    instead of a switch that would leave it with a black screen."""
    engine = 'electron'
    try:
        with open(UI_ENGINE_FILE) as f:
            if f.read().strip() == 'qt':
                engine = 'qt'
    except Exception:
        pass
    engines = (['electron'] if _electron_ui_installed() else []) \
        + (['qt'] if _qt_ui_installed() else [])
    # the chosen interface is gone (package removed, or an image that only
    # ships one of the two): say what is actually there
    if engine not in engines:
        engine = engines[0] if engines else 'electron'
    return {'engine': engine, 'engines': engines}

def set_ui_engine(engine):
    """Switch Electron <-> Qt, live + persisted. Same update guard as the
    display mode: swapping the on-screen interface mid-update would tear down
    the session that is applying it."""
    if engine not in UI_ENGINES:
        return {'success': False, 'engine': get_ui_engine()['engine'],
                'code': 'uiEngine.invalid', 'message': _t('uiEngine.invalid', _lang())}
    if (engine == 'qt' and not _qt_ui_installed()) \
       or (engine == 'electron' and not _electron_ui_installed()):
        return {'success': False, 'engine': get_ui_engine()['engine'],
                'code': 'uiEngine.notInstalled', 'message': _t('uiEngine.notInstalled', _lang())}
    if _update_in_progress():
        return {'success': False, 'engine': get_ui_engine()['engine'],
                'code': 'update.inProgressRetry', 'message': _t('update.inProgressRetry', _lang())}
    try:
        r = subprocess.run([DISPLAY_MODE_SCRIPT, 'engine', 'set', engine, '--live'],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            log.error("set_ui_engine failed: %s", (r.stderr or '').strip())
            return {'success': False, 'engine': get_ui_engine()['engine'],
                    'code': 'uiEngine.changeFailed', 'message': _t('uiEngine.changeFailed', _lang())}
    except Exception:
        log.exception("set_ui_engine failed")
        return {'success': False, 'engine': get_ui_engine()['engine'],
                'code': 'uiEngine.changeFailed', 'message': _t('uiEngine.changeFailed', _lang())}
    msg = _t('uiEngine.qtEnabled' if engine == 'qt' else 'uiEngine.electronEnabled', _lang())
    return {'success': True, 'engine': engine, 'message': msg}

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
#  /usr/local/sbin/hifi-ui-resolution.sh shrinks that pixel count. It prefers a
#  real smaller video mode with the panel's own aspect ratio (xrandr --mode), so
#  the panel/TV scaler does the upscale and the GPU does nothing; only when the
#  panel exposes no such mode under the cap (21:9, 16:10, and every 16:9 panel
#  without a 1280x720 mode — 720p is a CEA mode, so TVs have it and PC monitors
#  mostly don't) does it need a fallback, and the fallback differs per backend:
#  on X11 it shrinks the framebuffer area with xrandr --scale-from, which costs
#  a full-screen GPU rescale per frame inside Xorg (measured on Gemini Lake:
#  1.80 W GPU with --scale-from vs 0.89 W on a real mode, same scene); on
#  Wayland, where that transform does not exist, it takes the smallest real
#  mode ABOVE the cap instead (1920x1200 -> 1280x800) — still free, still the
#  panel's own scaler. api_server runs as root, so no sudoers entry is needed.
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
#  Panel refresh rate. Both X's own scale-blit (when ui-resolution is active)
#  and Chromium's on-screen compositor are vblank-paced, so their GPU cost
#  scales with refresh: halving it roughly halves both — measured on Gemini
#  Lake, same content, ~79% -> ~49% render-engine busy going 49.98Hz ->
#  29.99Hz. Unlike ui-resolution this never touches the framebuffer area
#  (only the CRTC timing), so the Electron window — sized once at launch — is
#  untouched and the switch applies live with no session restart.
#
#  Not every panel exposes a low-refresh alternative for its native mode
#  (fixed-frequency embedded panels often have just one); 'supported'
#  reflects that per-unit so the UI can hide the control instead of offering
#  a toggle that would silently do nothing.
#
#  Persisted state ABSENT means "native" — opt-in, unlike ui-resolution: an
#  existing unit must not change behaviour until someone explicitly picks
#  "low" from Settings.
# ──────────────────────────────────────────────────────────────────
UI_REFRESH_FILE = '/etc/hifi-player/ui-refresh'
UI_REFRESH_SCRIPT = '/usr/local/sbin/hifi-ui-refresh.sh'
UI_REFRESHES = ('native', 'low')

def get_ui_refresh():
    """Return { mode, supported }. mode is one of UI_REFRESHES; 'native' when
    the file is absent or holds anything unrecognised. supported reflects
    whether the current panel/mode actually has a distinct low-refresh
    alternative at all (probed live via the script; False if the script is
    missing)."""
    mode = 'native'
    try:
        with open(UI_REFRESH_FILE) as f:
            val = f.read().strip()
        if val in UI_REFRESHES:
            mode = val
    except Exception:
        pass
    supported = False
    if os.path.exists(UI_REFRESH_SCRIPT):
        try:
            r = subprocess.run([UI_REFRESH_SCRIPT, 'supported'],
                               capture_output=True, text=True, timeout=10)
            supported = r.returncode == 0 and r.stdout.strip() == '1'
        except Exception:
            pass
    return {'mode': mode, 'supported': supported}

def set_ui_refresh(mode):
    """Persist the refresh-rate preference and apply it live — no session
    restart needed, see module comment above. Refused while an OTA is
    applying, same guard as ui-resolution."""
    if mode not in UI_REFRESHES:
        return {'success': False, 'mode': get_ui_refresh()['mode'],
                'code': 'uiRefresh.invalid', 'message': _t('uiRefresh.invalid', _lang())}
    if _update_in_progress():
        return {'success': False, 'mode': get_ui_refresh()['mode'],
                'code': 'update.inProgressRetry', 'message': _t('update.inProgressRetry', _lang())}
    if not os.path.exists(UI_REFRESH_SCRIPT):
        return {'success': False, 'mode': get_ui_refresh()['mode'],
                'code': 'uiRefresh.unavailable', 'message': _t('uiRefresh.unavailable', _lang())}
    try:
        r = subprocess.run([UI_REFRESH_SCRIPT, 'set', mode, '--live'],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            log.error("set_ui_refresh failed: %s", (r.stderr or '').strip())
            return {'success': False, 'mode': get_ui_refresh()['mode'],
                    'code': 'uiRefresh.changeFailed', 'message': _t('uiRefresh.changeFailed', _lang())}
    except Exception:
        log.exception("set_ui_refresh failed")
        return {'success': False, 'mode': get_ui_refresh()['mode'],
                'code': 'uiRefresh.changeFailed', 'message': _t('uiRefresh.changeFailed', _lang())}
    return {'success': True, 'mode': mode,
            'message': _t('uiRefresh.updated', _lang())}

# ──────────────────────────────────────────────────────────────────
#  Kiosk restart. Both session launchers (distro/os-update/files/xsession on
#  X11, kiosk-wayland-launch on Wayland) run Electron inside a `while true`
#  loop, so killing the process is all it takes: it comes back ~3s later with
#  whatever OS state changed underneath it. A headless unit has no such
#  process and this is a harmless no-op there.
#
#  🚨 Da 2.5.24 le interfacce su schermo sono due e si riavviano in modi
#  diversi: la Qt non gira dentro nessuna sessione con ciclo di rilancio, e'
#  un'unita' systemd tutta sua (hifi-qt.service), quindi un pkill sul processo
#  Electron su quegli apparecchi non fa assolutamente niente.
# ──────────────────────────────────────────────────────────────────
# `pkill -x` matches the kernel's `comm`, which is capped at 15 characters:
# "hifi-media-player" is 17, so the obvious pattern matches NOTHING (procps
# even warns about it) and every caller that used it was silently doing
# nothing at all. Match the truncated name instead — `-f` is not an option
# here, it would also match any shell or script with the app name on its
# command line, including the OTA updater.
KIOSK_COMM = 'hifi-media-play'  # 'hifi-media-player' truncated to comm's 15 chars
QT_UI_UNIT = 'hifi-qt.service'

def restart_kiosk_ui(delay=1.5):
    """Restart whichever on-screen interface this device runs (Electron kiosk
    or Qt), so it picks up the OS state that just changed underneath it.

    Deferred onto a timer because the caller is usually serving a request that
    the kiosk itself made (on-device Settings): killing it inline would tear
    the browser down before Flask ever flushed the response, and the page would
    come back up reporting the change as failed. Same reason
    hifi-ui-resolution.sh delays its lightdm restart.
    """
    def _restart_qt():
        # try-restart e non restart: in modalita' headless non gira nessuna
        # interfaccia, e un restart la avvierebbe — riaccendendo uno schermo
        # che l'utente ha spento di proposito. Stessa scelta di
        # hifi-ui-resolution.sh. Il codice d'uscita si ignora: sugli
        # apparecchi Electron l'unita' non esiste nemmeno.
        _run(['systemctl', 'try-restart', QT_UI_UNIT], timeout=30)

    def _kill_electron():
        subprocess.run(['pkill', '-x', KIOSK_COMM], capture_output=True, timeout=10)

    def _restart():
        try:
            engine = get_ui_engine()['engine']
        except Exception:
            log.exception("restart_kiosk_ui: interfaccia in uso non determinabile")
            engine = None
        # Motore ignoto: si tentano tutte e due le strade. Ognuna e' innocua
        # quando tocca all'altra (unita' assente / processo assente), mentre
        # non riavviare l'interfaccia lascerebbe a schermo lo stato vecchio.
        steps = []
        if engine in (None, 'qt'):
            steps.append(_restart_qt)
        if engine in (None, 'electron'):
            steps.append(_kill_electron)
        for step in steps:
            try:
                step()
            except Exception:
                log.exception("restart_kiosk_ui failed")
    t = threading.Timer(delay, _restart)
    t.daemon = True
    t.start()

# ──────────────────────────────────────────────────────────────────
#  Timezone. The installer asks nothing about it (see distro/README.md) and
#  the build defaults every fresh image to UTC (0400-enable-services.hook.chroot)
#  — deterministic, but wrong for anyone who isn't in it, and units built from
#  old/refurbished hardware can drift further still without a working RTC
#  battery (systemd-timesyncd is now enabled by default to correct for that,
#  but it can't fix which zone the clock is displayed in).
#
#  Two files carry the zone and they are NOT equivalent:
#
#    /etc/localtime  — the symlink into the zoneinfo tree that glibc, Chromium
#                      and timedatectl itself actually resolve wall-clock time
#                      against. This one is the truth.
#    /etc/timezone   — a Debian-ism holding just the IANA name. systemd's
#                      timedated does not maintain it upstream, so on a trixie
#                      unit `timedatectl set-timezone` leaves it on whatever
#                      the image shipped ("Etc/UTC"). It still matters here
#                      because the backup profile captures it (hifi_backup.py).
#
#  Reading the name back from /etc/timezone was therefore how a zone that HAD
#  been applied kept reporting UTC to every Settings page on the box. Read the
#  symlink instead, and write both files on the way in so the two never drift.
# ──────────────────────────────────────────────────────────────────
ZONEINFO_DIR = '/usr/share/zoneinfo'
LOCALTIME_LINK = '/etc/localtime'
TIMEZONE_FILE = '/etc/timezone'

def _zone_from_localtime():
    """IANA name behind the /etc/localtime symlink, or None.

    Read with readlink and normalised by hand rather than realpath()'d: the
    zoneinfo tree is full of symlinks between equivalent zones (Etc/UTC → UTC,
    Europe/Vatican → Europe/Rome), and following them would hand back a name
    other than the one the user picked — which the Settings <select> would then
    fail to match against its own option list.
    """
    try:
        link = os.readlink(LOCALTIME_LINK)
    except OSError:
        return None  # missing, or a plain copy of the zone file
    target = link if os.path.isabs(link) else os.path.join(os.path.dirname(LOCALTIME_LINK), link)
    target = os.path.normpath(target)
    prefix = ZONEINFO_DIR + os.sep
    if not target.startswith(prefix):
        return None
    name = target[len(prefix):]
    # /usr/share/zoneinfo/posix/<zone> is a second copy of the same tree; strip
    # the prefix so the value matches what list_timezones() offers.
    if name.startswith('posix/'):
        name = name[len('posix/'):]
    return name or None

def get_timezone():
    """Return { timezone }. 'UTC' if it can't be determined."""
    tz = _zone_from_localtime()
    if tz:
        return {'timezone': tz}
    # No usable symlink (an image that copied the zone file in place, say).
    # The Debian name file is the only thing left to go on.
    try:
        with open(TIMEZONE_FILE) as f:
            tz = f.read().strip()
            if tz:
                return {'timezone': tz}
    except Exception:
        pass
    return {'timezone': 'UTC'}

def list_timezones():
    """All IANA zone names the installed tzdata knows about, e.g. 'Europe/Rome'."""
    names = []
    for dirpath, dirnames, filenames in os.walk(ZONEINFO_DIR):
        if os.path.relpath(dirpath, ZONEINFO_DIR) == '.':
            # posix/ is a second, identical copy of the entire tree, and right/
            # is the leap-second variant — correct only for a clock counting
            # TAI, so a box set from one displays ~37s off. Neither belongs in
            # a "pick your city" list (they'd also treble its length);
            # `timedatectl list-timezones` doesn't offer them either.
            dirnames[:] = [d for d in dirnames if d not in ('posix', 'right')]
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

def _link_localtime(tz):
    """Point /etc/localtime at `tz` ourselves. True on success.

    Same relative form timedated writes ('../usr/share/zoneinfo/<zone>'), and
    swapped in with rename(2) so a reader never catches the link missing.
    """
    tmp = LOCALTIME_LINK + '.hifi-tmp'
    try:
        if os.path.lexists(tmp):
            os.unlink(tmp)
        os.symlink(os.path.join('../usr/share/zoneinfo', tz), tmp)
        os.replace(tmp, LOCALTIME_LINK)
        return True
    except Exception:
        log.exception("set_timezone: could not link %s to %s", LOCALTIME_LINK, tz)
        try:
            if os.path.lexists(tmp):
                os.unlink(tmp)
        except Exception:
            pass
        return False

def _write_etc_timezone(tz):
    """Keep the Debian name file in step with the symlink (best effort)."""
    try:
        current = ''
        try:
            with open(TIMEZONE_FILE) as f:
                current = f.read().strip()
        except Exception:
            pass
        if current == tz:
            return
        tmp = TIMEZONE_FILE + '.hifi-tmp'
        with open(tmp, 'w') as f:
            f.write(tz + '\n')
        os.chmod(tmp, 0o644)
        os.replace(tmp, TIMEZONE_FILE)
    except Exception:
        log.exception("set_timezone: could not update %s", TIMEZONE_FILE)

def set_timezone(tz):
    """Switch the system timezone, live + persisted."""
    tz = (tz or '').strip()
    # A client holding a name from the posix/ mirror of the tree (it used to
    # be offered in /timezones) means the plain zone: normalise it, or the
    # read-back check below would compare 'Europe/Rome' against
    # 'posix/Europe/Rome' and report a change that did in fact happen as failed.
    if tz.startswith('posix/'):
        tz = tz[len('posix/'):]
    # timedatectl itself would refuse a bad name, but validate against
    # zoneinfo directly first: tz flows into a filesystem path below and this
    # is the chokepoint that keeps a "../../etc/passwd"-shaped value from ever
    # reaching a shell-adjacent API.
    real = os.path.normpath(os.path.join(ZONEINFO_DIR, tz))
    if not tz or not real.startswith(ZONEINFO_DIR + os.sep) or not os.path.isfile(real):
        return {'success': False, 'timezone': get_timezone()['timezone'],
                'code': 'timezone.invalid', 'message': _t('timezone.invalid', _lang())}
    # From here on the zone name is the one read back off the validated path,
    # not the request's own string: it is what the /etc/localtime link below
    # gets built from.
    tz = os.path.relpath(real, ZONEINFO_DIR)
    try:
        r = subprocess.run(['timedatectl', 'set-timezone', tz],
                           capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            log.error("timedatectl set-timezone %s failed: %s", tz, (r.stderr or '').strip())
    except Exception:
        log.exception("timedatectl set-timezone failed")
    # Never take timedatectl's word for it. It is the preferred path (it also
    # tells timedated, so a later `timedatectl status` agrees with us), but it
    # needs a live systemd-timedated on the bus to do anything at all, and a
    # unit where that call fails must still end up in the right zone rather
    # than silently sitting in UTC. Verify against the symlink, then finish
    # the job by hand if it didn't happen.
    if _zone_from_localtime() != tz and not _link_localtime(tz):
        return {'success': False, 'timezone': get_timezone()['timezone'],
                'code': 'timezone.changeFailed', 'message': _t('timezone.changeFailed', _lang())}
    _write_etc_timezone(tz)
    if get_timezone()['timezone'] != tz:
        return {'success': False, 'timezone': get_timezone()['timezone'],
                'code': 'timezone.changeFailed', 'message': _t('timezone.changeFailed', _lang())}
    # This process cached the old zone the first time it formatted a local
    # time; without tzset() every timestamp the API renders (log views, backup
    # generation names) would stay on the old offset until hifi-api restarts.
    try:
        time.tzset()
    except Exception:
        pass
    # And the on-screen interface resolves its timezone once at startup and
    # never re-reads it (Chromium through ICU, Qt through its own cache), so
    # the clock would keep showing the old offset until the next reboot.
    restart_kiosk_ui()
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
#  VU meter skin: which look the kiosk's analog meters wear. Each skin is
#  a folder the on-screen interface ships in its assets (skin.json plus
#  images, built with native-ui-qt/tools/vu-skin-build.py), so adding one
#  is dropping a folder in: the list below is read from disk, never kept
#  by hand. Persisted like the on/off switch above, so the web admin can
#  change it too; ABSENT (or a skin no longer installed) means "classic".
# ──────────────────────────────────────────────────────────────────
VU_STYLE_FILE = '/etc/hifi-player/vu-style'
VU_SKINS_DIR = os.environ.get('HIFI_VU_SKINS_DIR', '/opt/hifi-qt/assets/vu')
VU_STYLE_DEFAULT = 'classic'
# Skins downloaded from the VU meter store: on the data partition, so they
# survive the A/B image updates (the root file system is read-only).
VU_STORE_DIR = os.environ.get('HIFI_VU_STORE_DIR', '/var/lib/hifi-player/vu-skins')
_VU_STYLE_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{0,40}$')

def list_vu_styles():
    """The installed skins, [{id, name:{en,it}}], in their declared order
    (classic first): the ones the interface ships, then the ones downloaded
    from the VU meter store (a shipped skin wins an id both have). A folder
    whose skin.json does not parse is skipped: offering a look the kiosk
    would then refuse to draw helps no one."""
    styles = []
    seen = set()
    for base, source in ((VU_SKINS_DIR, 'builtin'), (VU_STORE_DIR, 'store')):
        try:
            names = sorted(os.listdir(base))
        except OSError:
            names = []
        for sid in names:
            if not _VU_STYLE_RE.match(sid) or sid in seen:
                continue
            try:
                with open(os.path.join(base, sid, 'skin.json'), encoding='utf-8') as f:
                    meta = json.load(f)
            except (OSError, ValueError):
                continue
            if not isinstance(meta, dict):
                continue
            seen.add(sid)
            name = meta.get('name')
            if not isinstance(name, dict):
                name = {'en': sid, 'it': sid}
            styles.append({'id': sid, 'name': {'en': str(name.get('en') or sid), 'it': str(name.get('it') or name.get('en') or sid)},
                           'order': meta.get('order', 50) if isinstance(meta.get('order', 50), int) else 50,
                           'source': source})
    if not any(st['id'] == VU_STYLE_DEFAULT for st in styles):
        # the interface draws the classic look even without its folder
        styles.append({'id': VU_STYLE_DEFAULT, 'name': {'en': 'Classic', 'it': 'Classico'}, 'order': 0, 'source': 'builtin'})
    styles.sort(key=lambda st: (st['order'], st['id']))
    return [{'id': st['id'], 'name': st['name'], 'source': st['source']} for st in styles]

def get_vu_style():
    """Return { style, styles }."""
    styles = list_vu_styles()
    style = VU_STYLE_DEFAULT
    try:
        with open(VU_STYLE_FILE) as f:
            style = f.read().strip() or VU_STYLE_DEFAULT
    except Exception:
        pass
    if not any(st['id'] == style for st in styles):
        style = VU_STYLE_DEFAULT
    return {'style': style, 'styles': styles}

def set_vu_style(style):
    """Persist the skin choice. Only an installed skin is accepted."""
    style = str(style or '').strip()
    if not _VU_STYLE_RE.match(style) or not any(st['id'] == style for st in list_vu_styles()):
        return {'success': False, 'style': get_vu_style()['style'],
                'code': 'prefs.vuStyleUnknown', 'message': _t('prefs.vuStyleUnknown', _lang())}
    try:
        os.makedirs(os.path.dirname(VU_STYLE_FILE), exist_ok=True)
        tmp = VU_STYLE_FILE + '.tmp'
        with open(tmp, 'w') as f:
            f.write(style + '\n')
        os.replace(tmp, VU_STYLE_FILE)
    except Exception:
        log.exception("set_vu_style: persist failed")
        return {'success': False, 'style': get_vu_style()['style'],
                'code': 'prefs.saveFailed', 'message': _t('prefs.saveFailed', _lang())}
    return {'success': True, 'style': style}

# ──────────────────────────────────────────────────────────────────
#  Now-playing animation: a turning CD (top-loading, or the 90s front-loading
#  player 'cdfront'), vinyl record or cassette the kiosk draws where the VU
#  meters would be. The interface shows it only while the
#  VU meters are switched off; the two settings stay independent here, so
#  turning the meters back on and off again brings the chosen animation back.
#  Persisted like the VU choices above (reachable from the web admin on a
#  headless unit); ABSENT, unreadable or unknown content means "none".
# ──────────────────────────────────────────────────────────────────
NOWPLAYING_ANIMATION_FILE = '/etc/hifi-player/nowplaying-animation'
# the scenes the interface ships; the animation store adds more (below)
NOWPLAYING_ANIMATION_BUILTIN = ('none', 'cd', 'cdfront', 'vinyl', 'cassette')
NOWPLAYING_ANIMATION_CHOICES = NOWPLAYING_ANIMATION_BUILTIN
NOWPLAYING_ANIMATION_DEFAULT = 'none'


def nowplaying_animation_choices():
    """Built-in ids, then those installed from the animation store."""
    return list(NOWPLAYING_ANIMATION_BUILTIN) + [a['id'] for a in list_store_animations()]

# Error text for a refused id, added to the shared catalogue (hifi_i18n.py)
# unless it already carries one, so _t() below answers in both languages.
_I18N_MESSAGES.setdefault('prefs.animationUnknown',
                          {'en': 'That animation is not available', 'it': 'Questa animazione non è disponibile'})

def get_nowplaying_animation():
    """Return { animation, choices, store }: store lists the installed store
    animations with their names and scene file, for the settings screens."""
    animation = NOWPLAYING_ANIMATION_DEFAULT
    try:
        with open(NOWPLAYING_ANIMATION_FILE) as f:
            animation = f.read(64).strip()
    except Exception:
        pass
    store = list_store_animations()
    choices = list(NOWPLAYING_ANIMATION_BUILTIN) + [a['id'] for a in store]
    if animation not in choices:
        animation = NOWPLAYING_ANIMATION_DEFAULT
    return {'animation': animation, 'choices': choices, 'store': store}

def set_nowplaying_animation(animation):
    """Persist the animation choice. A built-in id or an installed store one;
    'none' is stored like any other, the way the switches above store "off".
    Leaves the VU meter switch alone: the interface does the gating."""
    if not isinstance(animation, str) or animation.strip() not in nowplaying_animation_choices():
        return {'success': False, 'animation': get_nowplaying_animation()['animation'],
                'code': 'prefs.animationUnknown', 'message': _t('prefs.animationUnknown', _lang())}
    animation = animation.strip()
    try:
        os.makedirs(os.path.dirname(NOWPLAYING_ANIMATION_FILE), exist_ok=True)
        tmp = NOWPLAYING_ANIMATION_FILE + '.tmp'
        with open(tmp, 'w') as f:
            f.write(animation + '\n')
        os.replace(tmp, NOWPLAYING_ANIMATION_FILE)
    except Exception:
        log.exception("set_nowplaying_animation: persist failed")
        return {'success': False, 'animation': get_nowplaying_animation()['animation'],
                'code': 'prefs.saveFailed', 'message': _t('prefs.saveFailed', _lang())}
    return {'success': True, 'animation': animation}

# ──────────────────────────────────────────────────────────────────
#  VU meter store: more skins, downloaded on demand from
#  file.osmiumsound.it/vu/. The catalogue (index.json) carries a detached
#  Ed25519 signature made with the same key as the OS updates and checked
#  against the same public key (ota-pubkey.pem); every package (.vupak, a
#  zip holding skin.json and its images) and every preview is then checked
#  against the sha256 the signed catalogue names. Only what passes all of
#  that is unpacked, into VU_STORE_DIR, file by file: flat names, image and
#  JSON files only, size limits, and a skin.json that describes a skin the
#  interface can draw.
#
#  Nothing here runs code from a package: effects (needle ballistics, peak
#  lamp, backlight, peak needle) are parameters of skin.json that the
#  interface interprets. VU_SKIN_FORMAT is the highest skin.json format the
#  interface shipped next to this API understands; newer entries are listed
#  as needing an update and never installed.
#
#  The catalogue is refreshed in the background (at start, then every
#  VU_STORE_REFRESH, and on a GET when older than VU_STORE_STALE), and a
#  refresh also brings skins already installed from the store up to the
#  version it lists. New skins are only offered: installing one is the
#  owner's choice.
# ──────────────────────────────────────────────────────────────────
import base64 as _base64
import hashlib as _hashlib
import tempfile as _tempfile

VU_STORE_URL = os.environ.get('HIFI_VU_STORE_URL', 'https://file.osmiumsound.it/vu/')
VU_STORE_STATE_DIR = os.environ.get('HIFI_VU_STORE_STATE_DIR', '/var/lib/hifi-player/vu-store')
VU_STORE_PUBKEY = os.environ.get('HIFI_VU_STORE_PUBKEY', '/etc/hifi-player/ota-pubkey.pem')
VU_SKIN_FORMAT = 2
VU_STORE_REFRESH = 12 * 3600
VU_STORE_STALE = 600
VU_STORE_FIRST_CHECK = 120
VU_STORE_SIG_RETRY = 5
VU_INDEX_MAX = 1024 * 1024
VU_PACK_MAX = 40 * 1024 * 1024
VU_PACK_UNPACKED_MAX = 80 * 1024 * 1024
VU_PACK_FILES_MAX = 24
VU_PREVIEW_MAX = 1024 * 1024
_VU_FILE_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{0,80}\.(png|jpg|json)$')
_VU_PACK_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{0,80}\.vupak$')
_VU_PREVIEW_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{0,80}\.jpg$')
_VU_SHA_RE = re.compile(r'^[0-9a-f]{64}$')

_vu_store_lock = threading.Lock()
_vu_store = {'catalog': None, 'checked': 0, 'error': None, 'checking': False, 'loaded': False, 'jobs': {}}


class _VuStoreError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _vu_msg(code):
    return {'code': code, 'message': _t(code, _lang())}


def _vu_http_get(url, limit, timeout=30, agent='OsmiumSound-VU/1.0'):
    # an explicit User-Agent: some static hosts refuse urllib's default one
    req = urllib.request.Request(url, headers={'User-Agent': agent})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(limit + 1)
    except (urllib.error.URLError, OSError, ValueError) as e:
        log.info("store: GET %s failed: %s", url, e)
        raise _VuStoreError('vuStore.downloadFailed')
    if len(data) > limit:
        raise _VuStoreError('vuStore.verifyFailed')
    return data


def _vu_verify_signature(data, sig, pubkey=None):
    """Ed25519 over the exact catalogue bytes, like hifi-os-update.sh does for
    the OS bundles. No key, no openssl or a bad signature all mean no. The
    animation store checks its own catalogue with the same function."""
    pubkey = pubkey or VU_STORE_PUBKEY
    if not os.path.isfile(pubkey):
        log.warning("store: no public key at %s, catalogue refused", pubkey)
        return False
    with _tempfile.TemporaryDirectory(prefix='hifi-vu-sig-') as d:
        fdata, fsig = os.path.join(d, 'index.json'), os.path.join(d, 'index.json.sig')
        with open(fdata, 'wb') as f:
            f.write(data)
        with open(fsig, 'wb') as f:
            f.write(sig)
        try:
            r = subprocess.run(['openssl', 'pkeyutl', '-verify', '-pubin', '-inkey', pubkey,
                                '-rawin', '-in', fdata, '-sigfile', fsig],
                               capture_output=True, timeout=20)
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("vu store: openssl not usable: %s", e)
            return False
    return r.returncode == 0


def _vu_is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _vu_parse_index(raw):
    """The catalogue's entries, validated, highest version per id."""
    try:
        doc = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        raise _VuStoreError('vuStore.catalogInvalid')
    skins = doc.get('skins') if isinstance(doc, dict) else None
    if not isinstance(skins, list):
        raise _VuStoreError('vuStore.catalogInvalid')
    out = {}
    for e in skins:
        if not isinstance(e, dict):
            continue
        sid, ver, fmt = e.get('id'), e.get('version'), e.get('format', 1)
        name = e.get('name')
        if not (isinstance(sid, str) and _VU_STYLE_RE.match(sid) and isinstance(ver, int) and not isinstance(ver, bool)
                and ver >= 1 and isinstance(fmt, int) and fmt >= 1 and isinstance(name, dict)
                and isinstance(name.get('en'), str) and name.get('en')):
            continue
        pack, size, sha = e.get('file'), e.get('size'), str(e.get('sha256') or '').lower()
        if not (isinstance(pack, str) and _VU_PACK_RE.match(pack) and isinstance(size, int)
                and 0 < size <= VU_PACK_MAX and _VU_SHA_RE.match(sha)):
            continue
        entry = {'id': sid, 'version': ver, 'format': fmt,
                 'name': {'en': name['en'][:60], 'it': str(name.get('it') or name['en'])[:60]},
                 'author': str(e.get('author') or '')[:80], 'license': str(e.get('license') or '')[:80],
                 'file': pack, 'size': size, 'sha256': sha, 'preview': None}
        pv, pvs, pvsize = e.get('preview'), str(e.get('previewSha256') or '').lower(), e.get('previewSize')
        if (isinstance(pv, str) and _VU_PREVIEW_RE.match(pv) and _VU_SHA_RE.match(pvs)
                and isinstance(pvsize, int) and 0 < pvsize <= VU_PREVIEW_MAX):
            entry['preview'] = {'file': pv, 'sha256': pvs, 'size': pvsize}
        if sid not in out or out[sid]['version'] < ver:
            out[sid] = entry
    return sorted(out.values(), key=lambda x: x['id'])


def _vu_preview_path(entry):
    return os.path.join(VU_STORE_STATE_DIR, 'previews', entry['preview']['sha256'] + '.jpg')


def _vu_write_atomic(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)


def _vu_store_load_cached():
    """The last verified catalogue from disk, re-verified: a kiosk that
    starts offline still shows what was there."""
    with _vu_store_lock:
        if _vu_store['loaded']:
            return
        _vu_store['loaded'] = True
    try:
        with open(os.path.join(VU_STORE_STATE_DIR, 'index.json'), 'rb') as f:
            raw = f.read(VU_INDEX_MAX + 1)
        with open(os.path.join(VU_STORE_STATE_DIR, 'index.json.sig'), 'rb') as f:
            sig = f.read(4096)
        mtime = os.path.getmtime(os.path.join(VU_STORE_STATE_DIR, 'index.json'))
    except OSError:
        return
    if len(raw) > VU_INDEX_MAX or not _vu_verify_signature(raw, sig):
        return
    try:
        catalog = _vu_parse_index(raw)
    except _VuStoreError:
        return
    with _vu_store_lock:
        if _vu_store['catalog'] is None:
            _vu_store['catalog'] = catalog
            # stale on purpose: the first GET still checks the network
            _vu_store['checked'] = min(mtime, time.time() - VU_STORE_STALE - 1)


def _vu_builtin_ids():
    ids = {VU_STYLE_DEFAULT}
    try:
        ids.update(n for n in os.listdir(VU_SKINS_DIR) if _VU_STYLE_RE.match(n))
    except OSError:
        pass
    return ids


def _vu_installed_store():
    """{id: version} of the skins unpacked from the store."""
    out = {}
    try:
        names = os.listdir(VU_STORE_DIR)
    except OSError:
        return out
    for sid in names:
        if not _VU_STYLE_RE.match(sid):
            continue
        try:
            with open(os.path.join(VU_STORE_DIR, sid, 'skin.json'), encoding='utf-8') as f:
                v = json.load(f).get('version', 0)
        except (OSError, ValueError, AttributeError):
            continue
        out[sid] = v if isinstance(v, int) and not isinstance(v, bool) else 0
    return out


def _vu_seen_ids():
    try:
        with open(os.path.join(VU_STORE_STATE_DIR, 'seen.json'), encoding='utf-8') as f:
            v = json.load(f)
        return set(x for x in v if isinstance(x, str)) if isinstance(v, list) else set()
    except (OSError, ValueError):
        return set()


def _vu_check_skin(skin, entry, names):
    """skin.json of a package: the id/version the catalogue promised and the
    geometry VuPanel.qml needs, every file it names inside the package."""
    def ok_file(n):
        return isinstance(n, str) and _VU_FILE_RE.match(n) and n in names and not n.endswith('.json')

    def ok_pair(p):
        return isinstance(p, list) and len(p) == 2 and all(_vu_is_num(v) for v in p)

    if not isinstance(skin, dict) or skin.get('id') != entry['id'] or skin.get('version') != entry['version']:
        return False
    fmt = skin.get('format', 1)
    if not isinstance(fmt, int) or fmt > VU_SKIN_FORMAT:
        return False
    size = skin.get('size')
    if not (ok_pair(size) and size[0] > 0 and size[1] > 0):
        return False
    meters = skin.get('meters')
    if not (isinstance(meters, list) and len(meters) >= 2 and all(ok_pair(m) for m in meters[:2])):
        return False
    if not ok_pair(skin.get('angles')):
        return False
    if not ok_file(skin.get('under')) or not ok_file(skin.get('over')):
        return False
    needle = skin.get('needle')
    if not isinstance(needle, dict) or ('image' in needle and not ok_file(needle['image'])):
        return False
    effects = skin.get('effects', {})
    if not isinstance(effects, dict):
        return False
    for key in ('backlight', 'peakLamp', 'peakNeedle'):
        eff = effects.get(key)
        if eff is None:
            continue
        if not isinstance(eff, dict) or ('image' in eff and not ok_file(eff['image'])):
            return False
    return True


def _vu_unpack(data, entry):
    """Unpack a verified .vupak into VU_STORE_DIR/<id>, replacing an older
    copy only once the new one is complete."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except (zipfile.BadZipFile, ValueError):
        raise _VuStoreError('vuStore.invalidPackage')
    if not infos or len(infos) > VU_PACK_FILES_MAX:
        raise _VuStoreError('vuStore.invalidPackage')
    names, total = set(), 0
    for info in infos:
        mode = (info.external_attr >> 16) & 0o170000
        if (info.is_dir() or not _VU_FILE_RE.match(info.filename) or info.filename in names
                or mode not in (0, 0o100000)):
            raise _VuStoreError('vuStore.invalidPackage')
        names.add(info.filename)
        total += info.file_size
    if total > VU_PACK_UNPACKED_MAX or 'skin.json' not in names:
        raise _VuStoreError('vuStore.invalidPackage')
    try:
        files = {n: zf.read(n) for n in names}
        skin = json.loads(files['skin.json'].decode('utf-8'))
    except (zipfile.BadZipFile, UnicodeDecodeError, ValueError, OSError, RuntimeError):
        raise _VuStoreError('vuStore.invalidPackage')
    if not _vu_check_skin(skin, entry, names):
        raise _VuStoreError('vuStore.invalidPackage')
    for n, blob in files.items():
        if n.endswith('.png') and not blob.startswith(b'\x89PNG\r\n\x1a\n'):
            raise _VuStoreError('vuStore.invalidPackage')
        if n.endswith('.jpg') and not blob.startswith(b'\xff\xd8\xff'):
            raise _VuStoreError('vuStore.invalidPackage')
    sid = entry['id']
    dest = os.path.join(VU_STORE_DIR, sid)
    tmp = os.path.join(VU_STORE_DIR, '.tmp-' + sid)
    old = os.path.join(VU_STORE_DIR, '.old-' + sid)
    try:
        os.makedirs(VU_STORE_DIR, exist_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(old, ignore_errors=True)
        os.makedirs(tmp)
        for n, blob in files.items():
            with open(os.path.join(tmp, n), 'wb') as f:
                f.write(blob)
        if os.path.isdir(dest):
            os.rename(dest, old)
        os.rename(tmp, dest)
        shutil.rmtree(old, ignore_errors=True)
    except OSError:
        log.exception("vu store: unpacking %s failed", sid)
        shutil.rmtree(tmp, ignore_errors=True)
        if not os.path.isdir(dest) and os.path.isdir(old):
            os.rename(old, dest)
        raise _VuStoreError('vuStore.installFailed')


def _vu_install_entry(entry):
    """Download, verify and unpack one catalogue entry (job state in
    _vu_store['jobs']). True when installed."""
    sid = entry['id']
    try:
        data = _vu_http_get(urllib.parse.urljoin(VU_STORE_URL, entry['file']), entry['size'])
        if len(data) != entry['size'] or _hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise _VuStoreError('vuStore.verifyFailed')
        with _vu_store_lock:
            _vu_store['jobs'][sid] = {'state': 'installing'}
        _vu_unpack(data, entry)
    except _VuStoreError as e:
        log.warning("vu store: %s v%s not installed: %s", sid, entry['version'], e.code)
        with _vu_store_lock:
            _vu_store['jobs'][sid] = {'state': 'error', 'code': e.code}
        return False
    with _vu_store_lock:
        _vu_store['jobs'].pop(sid, None)
    log.info("vu store: %s v%s installed", sid, entry['version'])
    return True


def _vu_store_refresh():
    """Fetch and verify the catalogue and its previews, then bring the skins
    installed from the store up to date. One at a time."""
    with _vu_store_lock:
        if _vu_store['checking']:
            return
        _vu_store['checking'] = True
    error = None
    catalog = None
    try:
        raw = _vu_http_get(urllib.parse.urljoin(VU_STORE_URL, 'index.json'), VU_INDEX_MAX)
        sig = _vu_http_get(urllib.parse.urljoin(VU_STORE_URL, 'index.json.sig'), 4096)
        if not _vu_verify_signature(raw, sig):
            # a publish uploads the list and its signature one after the other:
            # read both again once before calling it a failure
            time.sleep(VU_STORE_SIG_RETRY)
            raw = _vu_http_get(urllib.parse.urljoin(VU_STORE_URL, 'index.json'), VU_INDEX_MAX)
            sig = _vu_http_get(urllib.parse.urljoin(VU_STORE_URL, 'index.json.sig'), 4096)
            if not _vu_verify_signature(raw, sig):
                raise _VuStoreError('vuStore.signatureInvalid')
        catalog = _vu_parse_index(raw)
        for entry in catalog:
            if not entry['preview'] or os.path.isfile(_vu_preview_path(entry)):
                continue
            try:
                blob = _vu_http_get(urllib.parse.urljoin(VU_STORE_URL, entry['preview']['file']), entry['preview']['size'])
            except _VuStoreError:
                continue
            if _hashlib.sha256(blob).hexdigest() == entry['preview']['sha256'] and blob.startswith(b'\xff\xd8\xff'):
                _vu_write_atomic(_vu_preview_path(entry), blob)
        try:
            _vu_write_atomic(os.path.join(VU_STORE_STATE_DIR, 'index.json'), raw)
            _vu_write_atomic(os.path.join(VU_STORE_STATE_DIR, 'index.json.sig'), sig)
        except OSError:
            log.exception("vu store: could not keep the catalogue on disk")
    except _VuStoreError as e:
        error = 'vuStore.catalogUnavailable' if e.code == 'vuStore.downloadFailed' else e.code
    except Exception:
        log.exception("vu store: refresh failed")
        error = 'vuStore.catalogUnavailable'
    with _vu_store_lock:
        if catalog is not None:
            _vu_store['catalog'] = catalog
        _vu_store['error'] = error
        _vu_store['checked'] = time.time()
        _vu_store['loaded'] = True
    try:
        if catalog is not None:
            installed, builtin = _vu_installed_store(), _vu_builtin_ids()
            for entry in catalog:
                if (entry['id'] in installed and entry['id'] not in builtin
                        and entry['version'] > installed[entry['id']] and entry['format'] <= VU_SKIN_FORMAT):
                    with _vu_store_lock:
                        if entry['id'] in _vu_store['jobs'] and _vu_store['jobs'][entry['id']].get('state') != 'error':
                            continue
                        _vu_store['jobs'][entry['id']] = {'state': 'downloading'}
                    _vu_install_entry(entry)
    finally:
        with _vu_store_lock:
            _vu_store['checking'] = False


def _vu_store_refresh_async():
    threading.Thread(target=_vu_store_refresh, daemon=True, name='vu-store-refresh').start()


def _vu_store_background():
    time.sleep(VU_STORE_FIRST_CHECK)
    while True:
        try:
            _vu_store_refresh()
        except Exception:
            log.exception("vu store: periodic check failed")
        time.sleep(VU_STORE_REFRESH)


def _vu_find_entry(sid):
    with _vu_store_lock:
        for entry in _vu_store['catalog'] or []:
            if entry['id'] == sid:
                return entry
    return None


def get_vu_store(summary=False):
    """The store as the settings screens show it. summary=True only counts
    what is new (for a badge) and never carries the previews."""
    _vu_store_load_cached()
    with _vu_store_lock:
        stale = not _vu_store['checking'] and time.time() - _vu_store['checked'] > VU_STORE_STALE
        catalog = list(_vu_store['catalog'] or [])
        jobs = {k: dict(v) for k, v in _vu_store['jobs'].items()}
        error, checked = _vu_store['error'], _vu_store['checked']
    if stale:
        _vu_store_refresh_async()
    installed, builtin, seen = _vu_installed_store(), _vu_builtin_ids(), _vu_seen_ids()
    items = []
    for entry in catalog:
        sid = entry['id']
        if sid in builtin:
            continue
        have = installed.get(sid)
        supported = entry['format'] <= VU_SKIN_FORMAT
        item = {'id': sid, 'version': entry['version'], 'name': entry['name'], 'author': entry['author'],
                'license': entry['license'], 'size': entry['size'], 'supported': supported,
                'installed': have is not None, 'installedVersion': have,
                'update': have is not None and supported and entry['version'] > have,
                'new': have is None and supported and sid not in seen}
        job = jobs.get(sid)
        if job:
            item['job'] = job['state']
            if job.get('code'):
                item['jobError'] = _vu_msg(job['code'])
        if not summary:
            item['preview'] = None
            if entry['preview']:
                try:
                    with open(_vu_preview_path(entry), 'rb') as f:
                        item['preview'] = 'data:image/jpeg;base64,' + _base64.b64encode(f.read()).decode('ascii')
                except OSError:
                    pass
        items.append(item)
    if summary:
        return {'new': sum(1 for i in items if i['new']), 'updates': sum(1 for i in items if i['update'])}
    with _vu_store_lock:
        checking = _vu_store['checking']
    return {'skins': items, 'checking': checking or stale, 'checked': int(checked),
            'error': _vu_msg(error) if error else None,
            'busy': any(i.get('job') in ('downloading', 'installing') for i in items)}


def vu_store_check():
    _vu_store_refresh_async()
    return {'success': True, 'checking': True}


def vu_store_install(sid):
    sid = str(sid or '').strip()
    _vu_store_load_cached()
    entry = _vu_find_entry(sid) if _VU_STYLE_RE.match(sid) else None
    if entry is None:
        return {'success': False, **_vu_msg('vuStore.unknown')}
    if sid in _vu_builtin_ids():
        return {'success': False, **_vu_msg('vuStore.builtin')}
    if entry['format'] > VU_SKIN_FORMAT:
        return {'success': False, **_vu_msg('vuStore.unsupported')}
    if _vu_installed_store().get(sid) == entry['version']:
        return {'success': True, 'installed': True}
    with _vu_store_lock:
        if _vu_store['jobs'].get(sid, {}).get('state') in ('downloading', 'installing'):
            return {'success': False, **_vu_msg('vuStore.busy')}
        _vu_store['jobs'][sid] = {'state': 'downloading'}
    threading.Thread(target=_vu_install_entry, args=(entry,), daemon=True, name='vu-store-install').start()
    return {'success': True, 'started': True}


def vu_store_remove(sid):
    sid = str(sid or '').strip()
    if not _VU_STYLE_RE.match(sid) or sid not in _vu_installed_store():
        return {'success': False, **_vu_msg('vuStore.notInstalled')}
    with _vu_store_lock:
        if _vu_store['jobs'].get(sid, {}).get('state') in ('downloading', 'installing'):
            return {'success': False, **_vu_msg('vuStore.busy')}
        _vu_store['jobs'].pop(sid, None)
    try:
        shutil.rmtree(os.path.join(VU_STORE_DIR, sid))
    except OSError:
        log.exception("vu store: removing %s failed", sid)
        return {'success': False, **_vu_msg('vuStore.removeFailed')}
    # the look in use is gone: back to the default rather than a stale choice
    try:
        with open(VU_STYLE_FILE) as f:
            if f.read().strip() == sid:
                os.remove(VU_STYLE_FILE)
    except OSError:
        pass
    return {'success': True}


def vu_store_mark_seen():
    _vu_store_load_cached()
    with _vu_store_lock:
        ids = [e['id'] for e in _vu_store['catalog'] or []]
    seen = _vu_seen_ids() | set(ids)
    try:
        _vu_write_atomic(os.path.join(VU_STORE_STATE_DIR, 'seen.json'), json.dumps(sorted(seen)).encode('utf-8'))
    except OSError:
        return {'success': False, **_vu_msg('prefs.saveFailed')}
    return {'success': True}

# ──────────────────────────────────────────────────────────────────
#  Now-playing animation store: more animations, downloaded on demand from
#  file.osmiumsound.it/anim/, the same way as the VU meter skins above: a
#  catalogue (index.json) with a detached Ed25519 signature made with the OS
#  update key and checked against ota-pubkey.pem, then every package
#  (.animpak) and preview checked against the sha256 the catalogue names.
#
#  Unlike a skin, an animation is a scene: QML the kiosk loads and runs, with
#  its images. That is accepted because it arrives exactly like an update of
#  the interface does - signed with the same key, so it carries the same trust
#  and nothing else is ever loaded (no manual upload, no other source). A
#  package holds anim.json (id, version, format, name, the scene's file) and
#  flat .qml / .png / .jpg / .json files; ANIM_SCENE_FORMAT is the scene
#  contract of the interface shipped next to this API (the inputs NpAnimation
#  gives a scene), newer entries are listed as needing an update.
#
#  Installed animations live on the data partition, next to the store skins,
#  and are refreshed like them: at start, every ANIM_STORE_REFRESH, and on a
#  GET older than ANIM_STORE_STALE; a refresh brings the installed ones up to
#  the listed version. The four animations the interface ships stay built in.
# ──────────────────────────────────────────────────────────────────
ANIM_STORE_URL = os.environ.get('HIFI_ANIM_STORE_URL', 'https://file.osmiumsound.it/anim/')
ANIM_STORE_DIR = os.environ.get('HIFI_ANIM_STORE_DIR', '/var/lib/hifi-player/anim-scenes')
ANIM_STORE_STATE_DIR = os.environ.get('HIFI_ANIM_STORE_STATE_DIR', '/var/lib/hifi-player/anim-store')
ANIM_STORE_PUBKEY = os.environ.get('HIFI_ANIM_STORE_PUBKEY', '/etc/hifi-player/ota-pubkey.pem')
ANIM_SCENE_FORMAT = 1
ANIM_STORE_REFRESH = 12 * 3600
ANIM_STORE_STALE = 600
ANIM_STORE_FIRST_CHECK = 150
ANIM_STORE_SIG_RETRY = 5
ANIM_INDEX_MAX = 1024 * 1024
ANIM_PACK_MAX = 40 * 1024 * 1024
ANIM_PACK_UNPACKED_MAX = 80 * 1024 * 1024
ANIM_PACK_FILES_MAX = 64
ANIM_PREVIEW_MAX = 1024 * 1024
ANIM_QML_MAX = 512 * 1024
# QML files may start with a capital: a scene's own components are types
_ANIM_FILE_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.(png|jpg|json|qml)$')
_ANIM_PACK_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{0,80}\.animpak$')
_ANIM_ID_RE = _VU_STYLE_RE
_ANIM_AGENT = 'OsmiumSound-Anim/1.0'

_anim_store_lock = threading.Lock()
_anim_store = {'catalog': None, 'checked': 0, 'error': None, 'checking': False, 'loaded': False, 'jobs': {}}


class _AnimStoreError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _anim_msg(code):
    return {'code': code, 'message': _t(code, _lang())}


def _anim_get(url, limit):
    """_vu_http_get with this store's error codes."""
    try:
        return _vu_http_get(url, limit, agent=_ANIM_AGENT)
    except _VuStoreError as e:
        raise _AnimStoreError(e.code.replace('vuStore.', 'animStore.'))


def _anim_parse_index(raw):
    """The catalogue's entries, validated, highest version per id."""
    try:
        doc = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        raise _AnimStoreError('animStore.catalogInvalid')
    anims = doc.get('animations') if isinstance(doc, dict) else None
    if not isinstance(anims, list):
        raise _AnimStoreError('animStore.catalogInvalid')
    out = {}
    for e in anims:
        if not isinstance(e, dict):
            continue
        aid, ver, fmt = e.get('id'), e.get('version'), e.get('format', 1)
        name = e.get('name')
        if not (isinstance(aid, str) and _ANIM_ID_RE.match(aid) and isinstance(ver, int) and not isinstance(ver, bool)
                and ver >= 1 and isinstance(fmt, int) and fmt >= 1 and isinstance(name, dict)
                and isinstance(name.get('en'), str) and name.get('en')):
            continue
        pack, size, sha = e.get('file'), e.get('size'), str(e.get('sha256') or '').lower()
        if not (isinstance(pack, str) and _ANIM_PACK_RE.match(pack) and isinstance(size, int)
                and 0 < size <= ANIM_PACK_MAX and _VU_SHA_RE.match(sha)):
            continue
        entry = {'id': aid, 'version': ver, 'format': fmt,
                 'name': {'en': name['en'][:60], 'it': str(name.get('it') or name['en'])[:60]},
                 'author': str(e.get('author') or '')[:80], 'license': str(e.get('license') or '')[:80],
                 'file': pack, 'size': size, 'sha256': sha, 'preview': None}
        pv, pvs, pvsize = e.get('preview'), str(e.get('previewSha256') or '').lower(), e.get('previewSize')
        if (isinstance(pv, str) and _VU_PREVIEW_RE.match(pv) and _VU_SHA_RE.match(pvs)
                and isinstance(pvsize, int) and 0 < pvsize <= ANIM_PREVIEW_MAX):
            entry['preview'] = {'file': pv, 'sha256': pvs, 'size': pvsize}
        if aid not in out or out[aid]['version'] < ver:
            out[aid] = entry
    return sorted(out.values(), key=lambda x: x['id'])


def _anim_preview_path(entry):
    return os.path.join(ANIM_STORE_STATE_DIR, 'previews', entry['preview']['sha256'] + '.jpg')


def _anim_read_meta(aid):
    """anim.json of an installed animation, or None."""
    try:
        with open(os.path.join(ANIM_STORE_DIR, aid, 'anim.json'), encoding='utf-8') as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(meta, dict) or not isinstance(meta.get('scene'), str) \
            or not os.path.isfile(os.path.join(ANIM_STORE_DIR, aid, meta['scene'])):
        return None
    return meta


def _anim_installed_store():
    """{id: version} of the animations unpacked from the store."""
    out = {}
    try:
        names = os.listdir(ANIM_STORE_DIR)
    except OSError:
        return out
    for aid in names:
        if not _ANIM_ID_RE.match(aid) or aid in NOWPLAYING_ANIMATION_BUILTIN:
            continue
        meta = _anim_read_meta(aid)
        if meta is None:
            continue
        v = meta.get('version', 0)
        out[aid] = v if isinstance(v, int) and not isinstance(v, bool) else 0
    return out


def list_store_animations():
    """The installed store animations, [{id, name:{en,it}, scene}], in their
    declared order: what the kiosk offers next to the built-in ones and
    loads from ANIM_STORE_DIR/<id>/<scene>."""
    out = []
    for aid in _anim_installed_store():
        meta = _anim_read_meta(aid) or {}
        name = meta.get('name') if isinstance(meta.get('name'), dict) else {}
        order = meta.get('order', 50)
        out.append({'id': aid, 'name': {'en': str(name.get('en') or aid), 'it': str(name.get('it') or name.get('en') or aid)},
                    'scene': meta.get('scene'), 'order': order if isinstance(order, int) and not isinstance(order, bool) else 50})
    out.sort(key=lambda a: (a['order'], a['id']))
    return [{'id': a['id'], 'name': a['name'], 'scene': a['scene']} for a in out]


def _anim_seen_ids():
    try:
        with open(os.path.join(ANIM_STORE_STATE_DIR, 'seen.json'), encoding='utf-8') as f:
            v = json.load(f)
        return set(x for x in v if isinstance(x, str)) if isinstance(v, list) else set()
    except (OSError, ValueError):
        return set()


def _anim_check_meta(meta, entry, names):
    """anim.json of a package: the id/version the catalogue promised, a
    format this interface runs and a scene file inside the package."""
    if not isinstance(meta, dict) or meta.get('id') != entry['id'] or meta.get('version') != entry['version']:
        return False
    fmt = meta.get('format', 1)
    if not isinstance(fmt, int) or isinstance(fmt, bool) or fmt > ANIM_SCENE_FORMAT:
        return False
    scene = meta.get('scene')
    if not (isinstance(scene, str) and scene.endswith('.qml') and scene in names):
        return False
    name = meta.get('name')
    return isinstance(name, dict) and isinstance(name.get('en'), str) and bool(name.get('en'))


def _anim_unpack(data, entry):
    """Unpack a verified .animpak into ANIM_STORE_DIR/<id>, replacing an older
    copy only once the new one is complete."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except (zipfile.BadZipFile, ValueError):
        raise _AnimStoreError('animStore.invalidPackage')
    if not infos or len(infos) > ANIM_PACK_FILES_MAX:
        raise _AnimStoreError('animStore.invalidPackage')
    names, total = set(), 0
    for info in infos:
        mode = (info.external_attr >> 16) & 0o170000
        if (info.is_dir() or not _ANIM_FILE_RE.match(info.filename) or info.filename in names
                or mode not in (0, 0o100000)):
            raise _AnimStoreError('animStore.invalidPackage')
        names.add(info.filename)
        total += info.file_size
    if total > ANIM_PACK_UNPACKED_MAX or 'anim.json' not in names:
        raise _AnimStoreError('animStore.invalidPackage')
    try:
        files = {n: zf.read(n) for n in names}
        meta = json.loads(files['anim.json'].decode('utf-8'))
    except (zipfile.BadZipFile, UnicodeDecodeError, ValueError, OSError, RuntimeError):
        raise _AnimStoreError('animStore.invalidPackage')
    if not _anim_check_meta(meta, entry, names):
        raise _AnimStoreError('animStore.invalidPackage')
    for n, blob in files.items():
        if n.endswith('.png') and not blob.startswith(b'\x89PNG\r\n\x1a\n'):
            raise _AnimStoreError('animStore.invalidPackage')
        if n.endswith('.jpg') and not blob.startswith(b'\xff\xd8\xff'):
            raise _AnimStoreError('animStore.invalidPackage')
        if n.endswith('.qml'):
            try:
                if len(blob) > ANIM_QML_MAX or '\x00' in blob.decode('utf-8'):
                    raise _AnimStoreError('animStore.invalidPackage')
            except UnicodeDecodeError:
                raise _AnimStoreError('animStore.invalidPackage')
    aid = entry['id']
    dest = os.path.join(ANIM_STORE_DIR, aid)
    tmp = os.path.join(ANIM_STORE_DIR, '.tmp-' + aid)
    old = os.path.join(ANIM_STORE_DIR, '.old-' + aid)
    try:
        os.makedirs(ANIM_STORE_DIR, exist_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(old, ignore_errors=True)
        os.makedirs(tmp)
        for n, blob in files.items():
            with open(os.path.join(tmp, n), 'wb') as f:
                f.write(blob)
        if os.path.isdir(dest):
            os.rename(dest, old)
        os.rename(tmp, dest)
        shutil.rmtree(old, ignore_errors=True)
    except OSError:
        log.exception("anim store: unpacking %s failed", aid)
        shutil.rmtree(tmp, ignore_errors=True)
        if not os.path.isdir(dest) and os.path.isdir(old):
            os.rename(old, dest)
        raise _AnimStoreError('animStore.installFailed')


def _anim_install_entry(entry):
    """Download, verify and unpack one catalogue entry (job state in
    _anim_store['jobs']). True when installed."""
    aid = entry['id']
    try:
        data = _anim_get(urllib.parse.urljoin(ANIM_STORE_URL, entry['file']), entry['size'])
        if len(data) != entry['size'] or _hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise _AnimStoreError('animStore.verifyFailed')
        with _anim_store_lock:
            _anim_store['jobs'][aid] = {'state': 'installing'}
        _anim_unpack(data, entry)
    except _AnimStoreError as e:
        log.warning("anim store: %s v%s not installed: %s", aid, entry['version'], e.code)
        with _anim_store_lock:
            _anim_store['jobs'][aid] = {'state': 'error', 'code': e.code}
        return False
    with _anim_store_lock:
        _anim_store['jobs'].pop(aid, None)
    log.info("anim store: %s v%s installed", aid, entry['version'])
    return True


def _anim_store_load_cached():
    """The last verified catalogue from disk, re-verified."""
    with _anim_store_lock:
        if _anim_store['loaded']:
            return
        _anim_store['loaded'] = True
    try:
        with open(os.path.join(ANIM_STORE_STATE_DIR, 'index.json'), 'rb') as f:
            raw = f.read(ANIM_INDEX_MAX + 1)
        with open(os.path.join(ANIM_STORE_STATE_DIR, 'index.json.sig'), 'rb') as f:
            sig = f.read(4096)
        mtime = os.path.getmtime(os.path.join(ANIM_STORE_STATE_DIR, 'index.json'))
    except OSError:
        return
    if len(raw) > ANIM_INDEX_MAX or not _vu_verify_signature(raw, sig, ANIM_STORE_PUBKEY):
        return
    try:
        catalog = _anim_parse_index(raw)
    except _AnimStoreError:
        return
    with _anim_store_lock:
        if _anim_store['catalog'] is None:
            _anim_store['catalog'] = catalog
            _anim_store['checked'] = min(mtime, time.time() - ANIM_STORE_STALE - 1)


def _anim_store_refresh():
    """Fetch and verify the catalogue and its previews, then bring the
    animations installed from the store up to date. One at a time."""
    with _anim_store_lock:
        if _anim_store['checking']:
            return
        _anim_store['checking'] = True
    error = None
    catalog = None
    try:
        raw = _anim_get(urllib.parse.urljoin(ANIM_STORE_URL, 'index.json'), ANIM_INDEX_MAX)
        sig = _anim_get(urllib.parse.urljoin(ANIM_STORE_URL, 'index.json.sig'), 4096)
        if not _vu_verify_signature(raw, sig, ANIM_STORE_PUBKEY):
            # the list and its signature are uploaded one after the other
            time.sleep(ANIM_STORE_SIG_RETRY)
            raw = _anim_get(urllib.parse.urljoin(ANIM_STORE_URL, 'index.json'), ANIM_INDEX_MAX)
            sig = _anim_get(urllib.parse.urljoin(ANIM_STORE_URL, 'index.json.sig'), 4096)
            if not _vu_verify_signature(raw, sig, ANIM_STORE_PUBKEY):
                raise _AnimStoreError('animStore.signatureInvalid')
        catalog = _anim_parse_index(raw)
        for entry in catalog:
            if not entry['preview'] or os.path.isfile(_anim_preview_path(entry)):
                continue
            try:
                blob = _anim_get(urllib.parse.urljoin(ANIM_STORE_URL, entry['preview']['file']), entry['preview']['size'])
            except _AnimStoreError:
                continue
            if _hashlib.sha256(blob).hexdigest() == entry['preview']['sha256'] and blob.startswith(b'\xff\xd8\xff'):
                _vu_write_atomic(_anim_preview_path(entry), blob)
        try:
            _vu_write_atomic(os.path.join(ANIM_STORE_STATE_DIR, 'index.json'), raw)
            _vu_write_atomic(os.path.join(ANIM_STORE_STATE_DIR, 'index.json.sig'), sig)
        except OSError:
            log.exception("anim store: could not keep the catalogue on disk")
    except _AnimStoreError as e:
        error = 'animStore.catalogUnavailable' if e.code == 'animStore.downloadFailed' else e.code
    except Exception:
        log.exception("anim store: refresh failed")
        error = 'animStore.catalogUnavailable'
    with _anim_store_lock:
        if catalog is not None:
            _anim_store['catalog'] = catalog
        _anim_store['error'] = error
        _anim_store['checked'] = time.time()
        _anim_store['loaded'] = True
    try:
        if catalog is not None:
            installed = _anim_installed_store()
            for entry in catalog:
                if (entry['id'] in installed and entry['id'] not in NOWPLAYING_ANIMATION_BUILTIN
                        and entry['version'] > installed[entry['id']] and entry['format'] <= ANIM_SCENE_FORMAT):
                    with _anim_store_lock:
                        if entry['id'] in _anim_store['jobs'] and _anim_store['jobs'][entry['id']].get('state') != 'error':
                            continue
                        _anim_store['jobs'][entry['id']] = {'state': 'downloading'}
                    _anim_install_entry(entry)
    finally:
        with _anim_store_lock:
            _anim_store['checking'] = False


def _anim_store_refresh_async():
    threading.Thread(target=_anim_store_refresh, daemon=True, name='anim-store-refresh').start()


def _anim_store_background():
    time.sleep(ANIM_STORE_FIRST_CHECK)
    while True:
        try:
            _anim_store_refresh()
        except Exception:
            log.exception("anim store: periodic check failed")
        time.sleep(ANIM_STORE_REFRESH)


def _anim_find_entry(aid):
    with _anim_store_lock:
        for entry in _anim_store['catalog'] or []:
            if entry['id'] == aid:
                return entry
    return None


def get_anim_store(summary=False):
    """The store as the settings screens show it. summary=True only counts
    what is new (for a badge) and never carries the previews."""
    _anim_store_load_cached()
    with _anim_store_lock:
        stale = not _anim_store['checking'] and time.time() - _anim_store['checked'] > ANIM_STORE_STALE
        catalog = list(_anim_store['catalog'] or [])
        jobs = {k: dict(v) for k, v in _anim_store['jobs'].items()}
        error, checked = _anim_store['error'], _anim_store['checked']
    if stale:
        _anim_store_refresh_async()
    installed, seen = _anim_installed_store(), _anim_seen_ids()
    items = []
    for entry in catalog:
        aid = entry['id']
        if aid in NOWPLAYING_ANIMATION_BUILTIN:
            continue
        have = installed.get(aid)
        supported = entry['format'] <= ANIM_SCENE_FORMAT
        item = {'id': aid, 'version': entry['version'], 'name': entry['name'], 'author': entry['author'],
                'license': entry['license'], 'size': entry['size'], 'supported': supported,
                'installed': have is not None, 'installedVersion': have,
                'update': have is not None and supported and entry['version'] > have,
                'new': have is None and supported and aid not in seen}
        job = jobs.get(aid)
        if job:
            item['job'] = job['state']
            if job.get('code'):
                item['jobError'] = _anim_msg(job['code'])
        if not summary:
            item['preview'] = None
            if entry['preview']:
                try:
                    with open(_anim_preview_path(entry), 'rb') as f:
                        item['preview'] = 'data:image/jpeg;base64,' + _base64.b64encode(f.read()).decode('ascii')
                except OSError:
                    pass
        items.append(item)
    if summary:
        return {'new': sum(1 for i in items if i['new']), 'updates': sum(1 for i in items if i['update'])}
    with _anim_store_lock:
        checking = _anim_store['checking']
    return {'animations': items, 'checking': checking or stale, 'checked': int(checked),
            'error': _anim_msg(error) if error else None,
            'busy': any(i.get('job') in ('downloading', 'installing') for i in items)}


def anim_store_check():
    _anim_store_refresh_async()
    return {'success': True, 'checking': True}


def anim_store_install(aid):
    aid = str(aid or '').strip()
    _anim_store_load_cached()
    entry = _anim_find_entry(aid) if _ANIM_ID_RE.match(aid) else None
    if entry is None:
        return {'success': False, **_anim_msg('animStore.unknown')}
    if aid in NOWPLAYING_ANIMATION_BUILTIN:
        return {'success': False, **_anim_msg('animStore.builtin')}
    if entry['format'] > ANIM_SCENE_FORMAT:
        return {'success': False, **_anim_msg('animStore.unsupported')}
    if _anim_installed_store().get(aid) == entry['version']:
        return {'success': True, 'installed': True}
    with _anim_store_lock:
        if _anim_store['jobs'].get(aid, {}).get('state') in ('downloading', 'installing'):
            return {'success': False, **_anim_msg('animStore.busy')}
        _anim_store['jobs'][aid] = {'state': 'downloading'}
    threading.Thread(target=_anim_install_entry, args=(entry,), daemon=True, name='anim-store-install').start()
    return {'success': True, 'started': True}


def anim_store_remove(aid):
    aid = str(aid or '').strip()
    if not _ANIM_ID_RE.match(aid) or aid not in _anim_installed_store():
        return {'success': False, **_anim_msg('animStore.notInstalled')}
    with _anim_store_lock:
        if _anim_store['jobs'].get(aid, {}).get('state') in ('downloading', 'installing'):
            return {'success': False, **_anim_msg('animStore.busy')}
        _anim_store['jobs'].pop(aid, None)
    try:
        shutil.rmtree(os.path.join(ANIM_STORE_DIR, aid))
    except OSError:
        log.exception("anim store: removing %s failed", aid)
        return {'success': False, **_anim_msg('animStore.removeFailed')}
    # the animation in use is gone: back to none rather than a stale choice
    try:
        with open(NOWPLAYING_ANIMATION_FILE) as f:
            if f.read().strip() == aid:
                os.remove(NOWPLAYING_ANIMATION_FILE)
    except OSError:
        pass
    return {'success': True}


def anim_store_mark_seen():
    _anim_store_load_cached()
    with _anim_store_lock:
        ids = [e['id'] for e in _anim_store['catalog'] or []]
    seen = _anim_seen_ids() | set(ids)
    try:
        _vu_write_atomic(os.path.join(ANIM_STORE_STATE_DIR, 'seen.json'), json.dumps(sorted(seen)).encode('utf-8'))
    except OSError:
        return {'success': False, **_anim_msg('prefs.saveFailed')}
    return {'success': True}

# ──────────────────────────────────────────────────────────────────
#  Now-playing auto-expand (kiosk-only UI behaviour, like the VU meter
#  above): how long after a song starts playing the kiosk should
#  automatically open the fullscreen now-playing view on its own, if the
#  user hasn't already navigated there. 0 = disabled (never auto-opens).
#  Persisted here (not just localStorage) for the same reason as
#  vu-meter-enabled: reachable from the companion app / web admin on a
#  headless unit.
# ──────────────────────────────────────────────────────────────────
UI_LANGUAGE_FILE = '/etc/hifi-player/ui-language'
UI_LANGUAGE_CHOICES = ('en', 'it')

def get_ui_language():
    """Return { language }. The on-device UI (both the Electron kiosk and the
    native one) reads this file, so the language follows the device rather
    than whichever UI happened to set it."""
    lang = ''
    try:
        with open(UI_LANGUAGE_FILE) as f:
            lang = f.read().strip().lower()
    except Exception:
        pass
    return {'language': lang if lang in UI_LANGUAGE_CHOICES else ''}

def set_ui_language(lang):
    lang = (lang or '').strip().lower()
    if lang not in UI_LANGUAGE_CHOICES:
        return {'success': False, 'language': get_ui_language()['language'],
                'code': 'prefs.saveFailed', 'message': _t('prefs.saveFailed', _lang())}
    try:
        os.makedirs(os.path.dirname(UI_LANGUAGE_FILE), exist_ok=True)
        tmp = UI_LANGUAGE_FILE + '.tmp'
        with open(tmp, 'w') as f:
            f.write(lang + '\n')
        os.replace(tmp, UI_LANGUAGE_FILE)
    except Exception:
        log.exception("set_ui_language: persist failed")
        return {'success': False, 'language': get_ui_language()['language'],
                'code': 'prefs.saveFailed', 'message': _t('prefs.saveFailed', _lang())}
    return {'success': True, 'language': lang}

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
            # kdump-tools alone is enough on Debian: it depends on makedumpfile
            # and kexec-tools itself, and this appliance's own kernel already
            # supports kexec. linux-crashdump is an Ubuntu-only meta-package
            # that doesn't exist here -- installing it unconditionally failed
            # the whole command every time (apt-get install fails atomically
            # on an unresolvable package name), which is why this always
            # errored regardless of actual Internet connectivity.
            r = subprocess.run(['apt-get', 'install', '-y', 'kdump-tools'],
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

def provision_wifi_connect(ssid, password, band=''):
    """Kick off the same Wi-Fi join webui_server's captive portal uses, from
    the on-screen manual network-setup panel. The AP drops immediately on
    webui's side; the kiosk keeps polling /provision_status to see it
    through 'connecting' -> 'network-ok'/'failed'."""
    body, status = _proxy_webui('/api/provision/wifi_connect', method='POST',
                                body={'ssid': ssid, 'password': password, 'band': band})
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
#  Bluetooth speakers (A2DP source) — OPTIONAL, OFF by default. Lets
#  the appliance play OUT to a Bluetooth speaker or a pair of
#  headphones. Each paired speaker gets a squeezelite instance of its
#  own (hifi-bt-player@<mac>.service), so it shows up in Lyrion as a
#  player in its own right, with its own name and its own queue,
#  alongside this device's built-in player — the same arrangement
#  piCorePlayer offers, and it is what makes a Bluetooth speaker
#  groupable with the main player for multiroom.
#
#  Nothing here touches the DAC: the built-in player keeps playing
#  through it while a Bluetooth speaker plays something else. The two
#  are separate Lyrion players, not two outputs fighting over one card.
#
#  🚨 This section does NOT start or stop anything. It writes the
#  owner's choice to /etc/hifi-player/bluetooth.json and signals
#  hifi-bt-out.service, which owns the whole runtime: bluetoothd,
#  BlueALSA (in a2dp-source role), the pairing agent, reconnecting a
#  speaker that was switched off, and one player unit per connected
#  speaker. The reason the choice cannot simply be `systemctl enable`
#  is the A/B image scheme — unit enablement does not survive an image
#  swap, the state file does (it is seeded by hifi-ab-seed.sh and it is
#  in the backup). See that unit and hifi-bt-out.py.
#
#  What this section does do synchronously is the parts that are a
#  conversation with the hardware and that the user is waiting on:
#  scanning, pairing and an explicit connect/disconnect.
# ──────────────────────────────────────────────────────────────────
BT_STATE_FILE = '/etc/hifi-player/bluetooth.json'
BT_STATUS_FILE = '/run/hifi-bt/output.json'
BT_SUPERVISOR = 'hifi-bt-out.service'
BT_PLAYER_UNIT = 'hifi-bt-player@{}.service'
BT_BLUEALSA_UNIT = 'hifi-bluealsa.service'
# The ALSA plugin squeezelite opens as bluealsa:DEV=<MAC>. The daemon alone is
# not enough — see the system-bundle/OS-migration split in 0024-bluetooth.sh,
# where the two halves of this feature can legitimately arrive one update
# apart, and a half-installed feature must report itself unavailable.
BT_ALSA_PLUGIN_GLOB = '/usr/lib/*/alsa-lib/libasound_module_pcm_bluealsa.so'
_BT_MAC_RE = re.compile(r'^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$')
# The A2DP sink service a speaker or a pair of headphones advertises. Anything
# without it (a keyboard, a phone, a fitness band) can be paired but will
# never play, so the UI is told which is which.
_BT_SINK_UUID = '0000110b'
# What a remote control advertises: HID over Bluetooth classic (0x1124) or
# over BLE (0x1812, "HID over GATT"). A remote is the opposite case to a
# speaker — it is an input device, and it plays nothing.
_BT_HID_UUIDS = ('00001124', '00001812')
_bt_apply_lock = threading.Lock()


def _bt_available():
    return (shutil.which('bluetoothctl') is not None
            and _unit_exists(BT_SUPERVISOR)
            and _unit_exists(BT_BLUEALSA_UNIT)
            and bool(glob.glob(BT_ALSA_PLUGIN_GLOB)))


def _bt_read_doc():
    """The whole state document. Kept in the file the sink design already
    used, so backup/restore ("bluetooth" category, which also carries
    /var/lib/bluetooth and therefore the pairing keys) keeps working
    unchanged, and so does a restore made before this feature existed."""
    try:
        with open(BT_STATE_FILE) as f:
            doc = json.load(f)
        if not isinstance(doc, dict):
            return {'enabled': False, 'speakers': []}
        doc.setdefault('enabled', False)
        if not isinstance(doc.get('speakers'), list):
            doc['speakers'] = []
        # Bluetooth remotes live in the same document as the speakers: they
        # share the radio, the pairing keys and the backup category, and a
        # restore made before remotes existed must still parse.
        if not isinstance(doc.get('remotes'), list):
            doc['remotes'] = []
        return doc
    except Exception:
        return {'enabled': False, 'speakers': [], 'remotes': []}


def _bt_write_doc(doc):
    os.makedirs(os.path.dirname(BT_STATE_FILE), exist_ok=True)
    tmp = BT_STATE_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(doc, f, indent=1)
    os.replace(tmp, BT_STATE_FILE)


def _read_bt_state():
    """Just the master switch. Kept as its own function because
    set_device_name() (which renames the adapter along with the player) calls
    it, and because that is all most callers want."""
    return bool(_bt_read_doc().get('enabled'))


def _bt_kick():
    """Tell the supervisor to re-read the state file now rather than at its
    next poll, so the UI's follow-up status request isn't answered from a
    snapshot taken before the change."""
    try:
        subprocess.run(['systemctl', 'kill', '-s', 'HUP', BT_SUPERVISOR],
                       capture_output=True, timeout=10)
    except Exception:
        pass


def _bt_snapshot():
    """What the supervisor last saw. Reading a small file beats running
    bluetoothctl on every status poll from three UIs at once."""
    try:
        with open(BT_STATUS_FILE) as f:
            snap = json.load(f)
        return snap if isinstance(snap, dict) else {}
    except Exception:
        return {}


def _bt_player_mac(mac):
    """A stable, unique player id for the speaker's squeezelite.

    Lyrion keys a player (its name, its volume, which group it is in) on this
    id, so it has to survive reboots and updates — and it must not collide
    with another Osmium paired to the same speaker, which is why this device's
    machine-id goes into the hash and not just the speaker's address. The
    first byte is forced to locally-administered/unicast so the result can
    never look like a real manufacturer's address."""
    try:
        with open('/etc/machine-id') as f:
            seed = f.read().strip()
    except Exception:
        seed = socket.gethostname()
    digest = _hashlib.sha256((seed + '|' + mac.upper()).encode()).digest()
    b = bytearray(digest[:6])
    b[0] = (b[0] & 0xFE) | 0x02
    return ':'.join('%02X' % x for x in b)


def _bt_clean_name(name, fallback='Bluetooth'):
    """A player name safe to hand to squeezelite and to show in Lyrion.
    Spaces are fine (it reaches squeezelite through execv, one argv entry),
    control characters are not."""
    name = re.sub(r'[\x00-\x1f\x7f]', '', str(name or '')).strip()
    return (name[:40] or fallback)


def _bt_instance(mac):
    """'F4:2B:7D:63:98:D7' -> 'f4-2b-7d-63-98-d7', the systemd instance name."""
    return mac.replace(':', '-').lower()


def _bt_device_info(mac):
    """{name, paired, trusted, connected, audio} for one device, from BlueZ."""
    info = {'mac': mac, 'name': '', 'paired': False, 'trusted': False,
            'connected': False, 'audio': False}
    try:
        r = subprocess.run(['bluetoothctl', 'info', mac],
                           capture_output=True, text=True, timeout=10)
        text = r.stdout or ''
    except Exception:
        return info
    m = re.search(r'^\s*(?:Alias|Name):\s*(.+)$', text, re.M)
    if m:
        info['name'] = m.group(1).strip()
    info['paired'] = 'Paired: yes' in text
    info['trusted'] = 'Trusted: yes' in text
    info['connected'] = 'Connected: yes' in text
    info['audio'] = _BT_SINK_UUID in text.lower()
    info['input'] = any(u in text.lower() for u in _BT_HID_UUIDS)
    return info


def _bt_known_devices():
    """Everything BlueZ currently knows about: paired devices plus whatever
    the last scan turned up. Best-effort — an empty list on failure is a UI
    that says "nothing found", not a broken page."""
    devices = []
    try:
        r = subprocess.run(['bluetoothctl', 'devices'],
                           capture_output=True, text=True, timeout=10)
        for line in (r.stdout or '').splitlines():
            m = re.match(r'Device\s+([0-9A-Fa-f:]{17})\s*(.*)', line.strip())
            if not m:
                continue
            mac = m.group(1).upper()
            info = _bt_device_info(mac)
            if not info['name']:
                info['name'] = m.group(2).strip() or mac
            devices.append(info)
    except Exception:
        log.exception("_bt_known_devices failed")
    return devices


def get_bt_speakers():
    """Status for the Bluetooth speakers screen: the master switch, the
    configured speakers with their live state, and whatever else is in range
    from the last scan."""
    try:
        doc = _bt_read_doc()
        enabled = bool(doc.get('enabled'))
        snap = _bt_snapshot()
        live = {str(s.get('mac', '')).upper(): s for s in (snap.get('speakers') or [])}

        speakers = []
        for sp in doc.get('speakers') or []:
            mac = str(sp.get('mac', '')).upper()
            if not _BT_MAC_RE.match(mac):
                continue
            state = live.get(mac, {})
            speakers.append({
                'mac': mac,
                'name': sp.get('name') or mac,
                'player': sp.get('player') or sp.get('name') or mac,
                'enabled': bool(sp.get('enabled', True)),
                'autoconnect': bool(sp.get('autoconnect', True)),
                'codec': sp.get('codec') or '',
                'connected': bool(state.get('connected')),
                'playing': bool(state.get('playing')),
            })

        # In range but not set up yet. Only meaningful while the adapter is
        # up; with Bluetooth off BlueZ has nothing to tell us.
        configured = {s['mac'] for s in speakers}
        found = []
        if enabled:
            for dev in _bt_known_devices():
                if dev['mac'] not in configured:
                    found.append(dev)

        return {'available': _bt_available(), 'enabled': enabled,
                'adapter': bool(snap.get('adapter')) if enabled else False,
                'speakers': speakers, 'found': found}
    except Exception:
        log.exception("get_bt_speakers failed")
        return {'available': False, 'enabled': False, 'adapter': False,
                'speakers': [], 'found': [],
                'error': _t('bluetooth.statusUnavailable', _lang())}


def _bt_fail(code, **extra):
    out = {'success': False, 'code': code, 'message': _t(code, _lang())}
    out.update(extra)
    return out


def _bt_ok(code, **extra):
    out = {'success': True, 'code': code, 'message': _t(code, _lang())}
    out.update(extra)
    out.update(get_bt_speakers())
    return out


def set_bt_enabled(enable):
    """Turn the whole Bluetooth side on or off. Serialized so a double-tap
    can't interleave with itself."""
    if enable and not _bt_available():
        return _bt_fail('bluetooth.unavailableUpdate', **get_bt_speakers())
    with _bt_apply_lock:
        doc = _bt_read_doc()
        doc['enabled'] = bool(enable)
        try:
            _bt_write_doc(doc)
        except Exception:
            log.exception("set_bt_enabled: could not persist the choice")
            return _bt_fail('bluetooth.opFailed', **get_bt_speakers())
        _bt_kick()
        if enable:
            # The supervisor has to start bluetoothd and power the adapter up
            # before the screen's first status poll means anything.
            for _ in range(15):
                time.sleep(1)
                if _bt_snapshot().get('adapter'):
                    break
    return _bt_ok('bluetooth.enabled' if enable else 'bluetooth.disabled')


def bt_scan(seconds=10):
    """Look for speakers in range. Blocking on purpose: the screen shows a
    spinner and the answer is the list, which is easier to get right than a
    progress endpoint for something that takes ten seconds."""
    if not _bt_available():
        return _bt_fail('bluetooth.unavailable')
    if not _read_bt_state():
        return _bt_fail('bluetooth.turnOnFirst')
    try:
        seconds = max(3, min(int(seconds or 10), 30))
    except (TypeError, ValueError):
        seconds = 10
    if not _bt_snapshot().get('adapter'):
        return _bt_fail('bluetooth.noAdapter', **get_bt_speakers())
    try:
        # --timeout makes bluetoothctl run discovery for that long and then
        # stop it, which matters: discovery left running eats airtime and is
        # audible as stutter on a speaker that is already playing.
        subprocess.run(['bluetoothctl', '--timeout', str(seconds), 'scan', 'on'],
                       capture_output=True, text=True, timeout=seconds + 15)
    except Exception:
        log.exception("bt_scan failed")
        return _bt_fail('bluetooth.scanFailed', **get_bt_speakers())
    return _bt_ok('bluetooth.scanDone')


def bt_add_speaker(mac, player=None):
    """Pair, trust and set a speaker up as a player, in one step.

    Trusting matters as much as pairing here: a trusted speaker may reconnect
    by itself when it is switched on, and BlueZ accepts it without asking
    anyone. The MAC comes straight off a network request, so it is checked
    against a strict address pattern before it reaches a subprocess argument."""
    if not _bt_available():
        return _bt_fail('bluetooth.unavailable')
    if not mac or not _BT_MAC_RE.match(mac):
        return _bt_fail('bluetooth.invalidAddress')
    if not _read_bt_state():
        return _bt_fail('bluetooth.turnOnFirst')
    mac = mac.upper()

    with _bt_apply_lock:
        doc = _bt_read_doc()
        if any(str(s.get('mac', '')).upper() == mac for s in doc['speakers']):
            return _bt_fail('bluetooth.alreadyAdded', **get_bt_speakers())

        info = _bt_device_info(mac)
        if not info['paired']:
            try:
                # Discovery must stop before pairing: BlueZ will not pair while
                # the adapter is still hopping around looking for devices.
                subprocess.run(['bluetoothctl', 'scan', 'off'],
                               capture_output=True, text=True, timeout=10)
                r = subprocess.run(['bluetoothctl', 'pair', mac],
                                   capture_output=True, text=True, timeout=60)
            except Exception:
                log.exception("bt_add_speaker: pair failed")
                return _bt_fail('bluetooth.pairFailed', **get_bt_speakers())
            info = _bt_device_info(mac)
            if not info['paired']:
                log.error("bt pair %s failed: %s", mac, (r.stdout or r.stderr or '').strip()[-200:])
                return _bt_fail('bluetooth.pairFailed', **get_bt_speakers())

        subprocess.run(['bluetoothctl', 'trust', mac], capture_output=True, timeout=15)

        name = _bt_clean_name(info['name'] or player or mac, mac)
        doc['speakers'].append({
            'mac': mac,
            'name': name,
            'player': _bt_clean_name(player or name, name),
            'player_mac': _bt_player_mac(mac),
            'enabled': True,
            'autoconnect': True,
            'codec': '',
        })
        try:
            _bt_write_doc(doc)
        except Exception:
            log.exception("bt_add_speaker: could not persist the speaker")
            return _bt_fail('bluetooth.opFailed', **get_bt_speakers())
    _bt_kick()
    # The supervisor connects it and starts its player; give it one cycle so
    # the reply already shows the speaker as connected.
    time.sleep(3)
    return _bt_ok('bluetooth.speakerAdded')


def bt_remove_speaker(mac):
    """Forget a speaker: its player goes away and BlueZ drops the pairing."""
    if not mac or not _BT_MAC_RE.match(mac):
        return _bt_fail('bluetooth.invalidAddress')
    mac = mac.upper()
    with _bt_apply_lock:
        doc = _bt_read_doc()
        before = len(doc['speakers'])
        doc['speakers'] = [s for s in doc['speakers']
                           if str(s.get('mac', '')).upper() != mac]
        if len(doc['speakers']) == before:
            return _bt_fail('bluetooth.deviceNotFound', **get_bt_speakers())
        try:
            _bt_write_doc(doc)
        except Exception:
            log.exception("bt_remove_speaker: could not persist")
            return _bt_fail('bluetooth.opFailed', **get_bt_speakers())
    # Stop the player first, then unpair: removing a device out from under a
    # squeezelite that still has its PCM open is how you get a hung ALSA
    # handle instead of a clean exit.
    _bt_kick()
    time.sleep(1)
    try:
        subprocess.run(['systemctl', 'stop', BT_PLAYER_UNIT.format(_bt_instance(mac))],
                       capture_output=True, timeout=30)
        subprocess.run(['bluetoothctl', 'remove', mac], capture_output=True, timeout=20)
    except Exception:
        log.exception("bt_remove_speaker: unpair failed")
    _bt_kick()
    return _bt_ok('bluetooth.forgotten')


def bt_update_speaker(mac, fields):
    """Rename a speaker's player, or switch it off without forgetting it."""
    if not mac or not _BT_MAC_RE.match(mac):
        return _bt_fail('bluetooth.invalidAddress')
    mac = mac.upper()
    with _bt_apply_lock:
        doc = _bt_read_doc()
        target = None
        for s in doc['speakers']:
            if str(s.get('mac', '')).upper() == mac:
                target = s
                break
        if target is None:
            return _bt_fail('bluetooth.deviceNotFound', **get_bt_speakers())
        if 'player' in fields:
            target['player'] = _bt_clean_name(fields['player'], target.get('name') or mac)
        if 'enabled' in fields:
            target['enabled'] = bool(fields['enabled'])
        if 'autoconnect' in fields:
            target['autoconnect'] = bool(fields['autoconnect'])
        if 'codec' in fields:
            codec = re.sub(r'[^A-Za-z0-9_-]', '', str(fields.get('codec') or ''))[:16]
            target['codec'] = codec
        target.setdefault('player_mac', _bt_player_mac(mac))
        try:
            _bt_write_doc(doc)
        except Exception:
            log.exception("bt_update_speaker: could not persist")
            return _bt_fail('bluetooth.opFailed', **get_bt_speakers())
    # A rename or a codec change only reaches Lyrion when squeezelite restarts
    # with the new arguments; the supervisor does that on its next pass, but
    # restarting it here means the new name is already there when the screen
    # refreshes.
    unit = BT_PLAYER_UNIT.format(_bt_instance(mac))
    try:
        if subprocess.run(['systemctl', 'is-active', unit],
                          capture_output=True, text=True, timeout=10).stdout.strip() == 'active':
            subprocess.run(['systemctl', 'restart', unit], capture_output=True, timeout=30)
    except Exception:
        log.exception("bt_update_speaker: player restart failed")
    _bt_kick()
    return _bt_ok('bluetooth.saved')


def bt_connect(mac, connect=True):
    """Connect or disconnect a speaker by hand. Disconnecting also parks the
    automatic retry (autoconnect off), because a speaker the owner just
    disconnected reconnecting fifteen seconds later is not a feature."""
    if not mac or not _BT_MAC_RE.match(mac):
        return _bt_fail('bluetooth.invalidAddress')
    if not _read_bt_state():
        return _bt_fail('bluetooth.turnOnFirst')
    mac = mac.upper()
    try:
        r = subprocess.run(['bluetoothctl', 'connect' if connect else 'disconnect', mac],
                           capture_output=True, text=True, timeout=40)
    except Exception:
        log.exception("bt_connect failed")
        return _bt_fail('bluetooth.connectFailed' if connect else 'bluetooth.opFailed',
                        **get_bt_speakers())
    ok = _bt_device_info(mac)['connected'] == bool(connect)
    if not ok and connect:
        log.error("bt connect %s failed: %s", mac, (r.stdout or r.stderr or '').strip()[-200:])
        return _bt_fail('bluetooth.connectFailed', **get_bt_speakers())
    with _bt_apply_lock:
        doc = _bt_read_doc()
        for s in doc['speakers']:
            if str(s.get('mac', '')).upper() == mac:
                s['autoconnect'] = bool(connect)
                break
        try:
            _bt_write_doc(doc)
        except Exception:
            log.exception("bt_connect: could not persist autoconnect")
    _bt_kick()
    time.sleep(2)
    return _bt_ok('bluetooth.connected' if connect else 'bluetooth.disconnected')

# ──────────────────────────────────────────────────────────────────
#  Bluetooth remotes
#
#  A remote control is an input device, not an output: once paired and
#  trusted it talks straight to the kernel's HID layer and shows up as
#  a /dev/input node, which the on-screen interface reads by itself
#  (native-ui-qt/src/remote.cpp). Nothing here has to run while it is
#  being used — this is only the pairing, and forgetting.
#
#  🚨 Two things make this different from the speakers:
#
#  1. The radio. Bluetooth is off on a device whose owner never asked
#     for it (the boot is quicker that way), and the supervisor is the
#     one that turns it on. A remote has to be paired BEFORE there is
#     a remote to keep the radio on for, so a scan opens a pairing
#     window in the state file (`remote_pairing_until`) which the
#     supervisor honours like any other reason to be up. Once one
#     remote is saved, the radio stays up for it.
#
#  2. Never paging them. A speaker that is off gets connection
#     attempts; a remote does NOT. It reconnects by itself the moment
#     a key is pressed, and paging one that is asleep would take the
#     radio away from a speaker that is playing (see hifi-bt-out.py).
# ──────────────────────────────────────────────────────────────────
BT_PAIRING_WINDOW = 180          # seconds the radio stays up for pairing


def _bt_remotes_available():
    """Pairing a remote needs BlueZ and the supervisor — and nothing else.
    The speakers' extra requirements (BlueALSA, the ALSA plugin) are about
    playing audio, which a remote never does."""
    return shutil.which('bluetoothctl') is not None and _unit_exists(BT_SUPERVISOR)


def _bt_remotes_supported():
    """True when the supervisor on this device knows about remotes.

    The api_server half of this feature travels in an app update, the
    supervisor half in the image: on a device where the image is older, a
    pairing window would be ignored and the radio torn down mid-pairing. The
    new supervisor always writes a `remotes` key in its snapshot, so its
    presence is the honest answer to "can this device do it yet"."""
    return 'remotes' in _bt_snapshot()


def _bt_open_pairing_window(seconds=BT_PAIRING_WINDOW):
    """Ask the supervisor for the radio, and wait until it is actually up."""
    with _bt_apply_lock:
        doc = _bt_read_doc()
        doc['remote_pairing_until'] = int(time.time()) + int(seconds)
        try:
            _bt_write_doc(doc)
        except Exception:
            log.exception("bt remotes: could not persist the pairing window")
            return False
    _bt_kick()
    for _ in range(20):
        if _bt_snapshot().get('adapter'):
            return True
        time.sleep(1)
    return False


def get_bt_remotes():
    """Status for the remote control screen: the remotes this device is
    paired with, and whatever else the last scan saw."""
    try:
        doc = _bt_read_doc()
        snap = _bt_snapshot()
        live = {str(r.get('mac', '')).upper(): r for r in (snap.get('remotes') or [])}
        remotes = []
        for rm in doc.get('remotes') or []:
            mac = str(rm.get('mac', '')).upper()
            if not _BT_MAC_RE.match(mac):
                continue
            remotes.append({
                'mac': mac,
                'name': rm.get('name') or mac,
                'connected': bool(live.get(mac, {}).get('connected')),
            })

        # In range but not paired yet. Speakers are left out: they have a
        # screen of their own, and pairing one here would set up nothing.
        known = {r['mac'] for r in remotes}
        known |= {str(s.get('mac', '')).upper() for s in (doc.get('speakers') or [])}
        found = []
        if snap.get('adapter'):
            for dev in _bt_known_devices():
                if dev['mac'] not in known and not dev.get('audio'):
                    found.append(dev)

        return {'available': _bt_remotes_available(),
                'supported': _bt_remotes_supported(),
                'adapter': bool(snap.get('adapter')),
                'remotes': remotes, 'found': found}
    except Exception:
        log.exception("get_bt_remotes failed")
        return {'available': False, 'supported': False, 'adapter': False,
                'remotes': [], 'found': [],
                'error': _t('bluetooth.statusUnavailable', _lang())}


def _bt_remote_ok(code, **extra):
    out = {'success': True, 'code': code, 'message': _t(code, _lang())}
    out.update(extra)
    out.update(get_bt_remotes())
    return out


def _bt_remote_fail(code, **extra):
    out = {'success': False, 'code': code, 'message': _t(code, _lang())}
    out.update(extra)
    out.update(get_bt_remotes())
    return out


def bt_remotes_scan(seconds=12):
    """Look for a remote in pairing mode. Blocking, like the speakers' scan:
    the screen shows a spinner and the answer is the list."""
    if not _bt_remotes_available():
        return _bt_remote_fail('bluetooth.unavailable')
    if not _bt_remotes_supported():
        return _bt_remote_fail('bluetooth.remoteNeedsUpdate')
    try:
        seconds = max(3, min(int(seconds or 12), 30))
    except (TypeError, ValueError):
        seconds = 12
    if not _bt_open_pairing_window():
        return _bt_remote_fail('bluetooth.noAdapter')
    try:
        subprocess.run(['bluetoothctl', '--timeout', str(seconds), 'scan', 'on'],
                       capture_output=True, text=True, timeout=seconds + 15)
    except Exception:
        log.exception("bt_remotes_scan failed")
        return _bt_remote_fail('bluetooth.scanFailed')
    return _bt_remote_ok('bluetooth.scanDone')


def bt_remote_add(mac):
    """Pair and trust a remote, and remember it.

    Trusting is what makes it work afterwards: BlueZ lets a trusted device
    reconnect by itself, without anyone to approve it — which is exactly what
    a remote does when a key is pressed after a night in a drawer."""
    if not _bt_remotes_available():
        return _bt_remote_fail('bluetooth.unavailable')
    if not _bt_remotes_supported():
        return _bt_remote_fail('bluetooth.remoteNeedsUpdate')
    if not mac or not _BT_MAC_RE.match(mac):
        return _bt_remote_fail('bluetooth.invalidAddress')
    mac = mac.upper()
    if not _bt_open_pairing_window():
        return _bt_remote_fail('bluetooth.noAdapter')

    with _bt_apply_lock:
        doc = _bt_read_doc()
        if any(str(r.get('mac', '')).upper() == mac for r in doc['remotes']):
            return _bt_remote_fail('bluetooth.remoteAlreadyAdded')

        info = _bt_device_info(mac)
        if not info['paired']:
            try:
                # Discovery has to stop before pairing: BlueZ will not pair
                # while the adapter is still hopping around looking.
                subprocess.run(['bluetoothctl', 'scan', 'off'],
                               capture_output=True, text=True, timeout=10)
                r = subprocess.run(['bluetoothctl', 'pair', mac],
                                   capture_output=True, text=True, timeout=60)
            except Exception:
                log.exception("bt_remote_add: pair failed")
                return _bt_remote_fail('bluetooth.remotePairFailed')
            info = _bt_device_info(mac)
            if not info['paired']:
                log.error("bt remote pair %s failed: %s", mac,
                          (r.stdout or r.stderr or '').strip()[-200:])
                return _bt_remote_fail('bluetooth.remotePairFailed')

        subprocess.run(['bluetoothctl', 'trust', mac], capture_output=True, timeout=15)
        # A remote does connect on request the first time: it is awake right
        # now, and connecting is what makes the kernel create its input node
        # without waiting for the first key press.
        try:
            subprocess.run(['bluetoothctl', 'connect', mac], capture_output=True, timeout=30)
        except Exception:
            log.exception("bt_remote_add: first connect failed")

        doc['remotes'].append({'mac': mac, 'name': _bt_clean_name(info['name'] or mac, mac)})
        try:
            _bt_write_doc(doc)
        except Exception:
            log.exception("bt_remote_add: could not persist the remote")
            return _bt_remote_fail('bluetooth.opFailed')
    _bt_kick()
    time.sleep(2)
    return _bt_remote_ok('bluetooth.remoteAdded')


def bt_remote_remove(mac):
    """Forget a remote: BlueZ drops the pairing and the radio is free to go
    back down if nothing else needs it."""
    if not mac or not _BT_MAC_RE.match(mac):
        return _bt_remote_fail('bluetooth.invalidAddress')
    mac = mac.upper()
    with _bt_apply_lock:
        doc = _bt_read_doc()
        before = len(doc['remotes'])
        doc['remotes'] = [r for r in doc['remotes']
                          if str(r.get('mac', '')).upper() != mac]
        if len(doc['remotes']) == before:
            return _bt_remote_fail('bluetooth.remoteNotFound')
        try:
            _bt_write_doc(doc)
        except Exception:
            log.exception("bt_remote_remove: could not persist")
            return _bt_remote_fail('bluetooth.opFailed')
    try:
        subprocess.run(['bluetoothctl', 'remove', mac], capture_output=True, timeout=20)
    except Exception:
        log.exception("bt_remote_remove: unpair failed")
    _bt_kick()
    return _bt_remote_ok('bluetooth.remoteForgotten')


# ──────────────────────────────────────────────────────────────────
#  Remote controls, seen from the web admin
#
#  I tasti li legge l'interfaccia sullo schermo, che possiede /dev/input
#  (native-ui-qt/src/remote.cpp): qui non si legge nessun dispositivo. Al web
#  admin serve la stessa fotografia — quali telecomandi ci sono, cosa fa ogni
#  tasto, qual e' "il mio telecomando" — e per averla le due parti si passano
#  quattro file:
#
#    /etc/hifi-player/remote-keys.json   cosa fa ogni tasto (per dispositivo)
#    /etc/hifi-player/remote-device      il telecomando dichiarato dall'utente
#    /run/hifi-remote/last.json          l'ultimo tasto premuto (lo scrive lei)
#    /run/hifi-remote/learn              "sto provando i tasti": scadenza epoch
#
#  🚨 L'elenco dei dispositivi si ricava da sysfs con le stesse regole di
#  remote.cpp, non chiedendolo all'interfaccia: cosi' la pagina funziona anche
#  mentre il kiosk si riavvia per un aggiornamento.
# ──────────────────────────────────────────────────────────────────
REMOTE_KEYS_FILE = '/etc/hifi-player/remote-keys.json'
REMOTE_DEVICE_FILE = '/etc/hifi-player/remote-device'
REMOTE_RUN_DIR = '/run/hifi-remote'
REMOTE_LAST_FILE = REMOTE_RUN_DIR + '/last.json'
REMOTE_LEARN_FILE = REMOTE_RUN_DIR + '/learn'
REMOTE_LEARN_SECONDS = 180
# Le azioni assegnabili: 🚨 stesso elenco e stesso ordine di kActions in
# native-ui-qt/src/remote.cpp. Se cambia li', cambia anche qui.
REMOTE_ACTIONS = [
    'playPause', 'play', 'pause', 'stop', 'next', 'prev', 'forward', 'rewind',
    'volumeUp', 'volumeDown', 'mute',
    'up', 'down', 'left', 'right', 'ok', 'back', 'home', 'menu', 'pageUp', 'pageDown',
    'nowPlaying', 'fullScreen', 'nextVu', 'nextAnimation', 'queue', 'search',
    'favorite', 'shuffle', 'standby', 'eject',
]
# i codici evdev che bastano a riconoscere un telecomando (linux/input-event-codes.h)
_KEY_PLAYPAUSE, _KEY_NEXTSONG, _KEY_PREVIOUSSONG = 164, 163, 165
_KEY_PLAYCD, _KEY_STOPCD, _KEY_PLAY = 200, 166, 207
_KEY_UP, _KEY_DOWN, _KEY_LEFT, _KEY_RIGHT = 103, 108, 105, 106
_KEY_ENTER, _KEY_OK, _KEY_SELECT = 28, 0x160, 0x161
_REL_X, _REL_Y, _ABS_X, _ABS_MT_X = 0, 1, 0, 53


def _sysfs_bit(bitmap, bit):
    """Un bit di un bitmap di /sys/class/input: parole esadecimali, la piu'
    significativa per prima."""
    words = (bitmap or '').split()
    if not words:
        return False
    idx = len(words) - 1 - bit // 64
    if idx < 0 or idx >= len(words):
        return False
    try:
        return bool((int(words[idx], 16) >> (bit % 64)) & 1)
    except ValueError:
        return False


def _remote_devices():
    """I telecomandi collegati adesso, con le regole di remote.cpp: tasti
    multimediali oppure frecce+conferma, e niente tastiere complete fra i
    "telecomandi veri"."""
    out = []
    chosen = _remote_chosen()
    root = os.environ.get('HIFI_SYSFS_INPUT', '/sys/class/input')
    for d in sorted(glob.glob(os.path.join(root, 'input*'))):
        def rd(name):
            try:
                with open(os.path.join(d, name)) as f:
                    return f.read().strip()
            except Exception:
                return ''
        key = rd('capabilities/key')
        if not key:
            continue
        full_keyboard = all(_sysfs_bit(key, b) for b in range(1, 32))
        media = any(_sysfs_bit(key, c) for c in
                    (_KEY_PLAYPAUSE, _KEY_NEXTSONG, _KEY_PREVIOUSSONG, _KEY_PLAYCD, _KEY_STOPCD, _KEY_PLAY))
        nav = (all(_sysfs_bit(key, c) for c in (_KEY_UP, _KEY_DOWN, _KEY_LEFT, _KEY_RIGHT))
               and any(_sysfs_bit(key, c) for c in (_KEY_ENTER, _KEY_OK, _KEY_SELECT)))
        if not media and not (nav and not full_keyboard):
            continue
        rel, abs_ = rd('capabilities/rel'), rd('capabilities/abs')
        pointer = _sysfs_bit(rel, _REL_X) and _sysfs_bit(rel, _REL_Y)
        tablet = _sysfs_bit(abs_, _ABS_X) or _sysfs_bit(abs_, _ABS_MT_X)
        name = rd('name') or os.path.basename(d)
        try:
            bus = int(rd('id/bustype') or '0', 16)
        except ValueError:
            bus = 0
        out.append({
            'name': name,
            'bus': 'bluetooth' if bus == 5 else 'usb' if bus == 3 else 'other',
            'kind': 'remote' if (not full_keyboard and not pointer and not tablet) else 'keyboard',
            'chosen': bool(chosen) and name == chosen,
            'address': rd('uniq').upper(),
        })
    return out


def _remote_chosen():
    try:
        with open(REMOTE_DEVICE_FILE) as f:
            return f.readline().strip()
    except Exception:
        return ''


def _remote_keys_doc():
    """remote-keys.json, sempre nella forma nuova {all, devices}. Un file del
    primo giorno era una mappa piatta codice -> azione: vale per tutti."""
    try:
        with open(REMOTE_KEYS_FILE) as f:
            doc = json.load(f)
        if not isinstance(doc, dict):
            return {'all': {}, 'devices': {}}
        if 'all' in doc or 'devices' in doc:
            return {'all': dict(doc.get('all') or {}), 'devices': dict(doc.get('devices') or {})}
        return {'all': dict(doc), 'devices': {}}
    except Exception:
        return {'all': {}, 'devices': {}}


def _remote_last_key():
    try:
        with open(REMOTE_LAST_FILE) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _remote_learning():
    try:
        with open(REMOTE_LEARN_FILE) as f:
            return float(f.read().strip() or 0) > time.time()
    except Exception:
        return False


def get_remote():
    """Quello che serve alla pagina Telecomando del web admin."""
    # 🚨 Non basta chiedere a systemd se l'unita' e' attiva: in collaudo (e su
    # un apparecchio dove qualcuno l'ha avviata a mano) l'interfaccia gira lo
    # stesso, e la pagina direbbe il falso. Conta che ci sia il processo.
    running = False
    try:
        running = subprocess.run(['systemctl', 'is-active', 'hifi-qt.service'],
                                 capture_output=True, text=True, timeout=10).stdout.strip() == 'active'
        if not running:
            running = subprocess.run(['pgrep', '-f', 'hifi-qt --assets'],
                                     capture_output=True, timeout=10).returncode == 0
    except Exception:
        pass
    doc = _remote_keys_doc()
    return {
        'devices': _remote_devices(),
        'chosen': _remote_chosen(),
        'keys': doc,
        'actions': REMOTE_ACTIONS,
        'lastKey': _remote_last_key(),
        'learning': _remote_learning(),
        # 🚨 I tasti li legge l'interfaccia sullo schermo: senza quella, la
        # prova dei tasti non puo' funzionare e la pagina deve dirlo.
        'interfaceRunning': running,
    }


def set_remote_device(device):
    """"Questo e' il mio telecomando" (nome vuoto = nessuno)."""
    device = re.sub(r'[\x00-\x1f\x7f]', '', str(device or '')).strip()[:80]
    try:
        os.makedirs(os.path.dirname(REMOTE_DEVICE_FILE), exist_ok=True)
        tmp = REMOTE_DEVICE_FILE + '.tmp'
        with open(tmp, 'w') as f:
            f.write(device + '\n')
        os.replace(tmp, REMOTE_DEVICE_FILE)
    except Exception:
        log.exception("set_remote_device failed")
        return {'success': False, 'message': _t('remote.saveFailed', _lang()), **get_remote()}
    return {'success': True, 'message': _t('remote.saved', _lang()), **get_remote()}


def set_remote_key(code, action, device=''):
    """Cosa fa un tasto, per QUEL dispositivo (vuoto = per tutti). `action`
    None toglie l'assegnazione, "" vuol dire "questo tasto non fa niente"."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return {'success': False, 'message': _t('remote.badKey', _lang()), **get_remote()}
    if code <= 0:
        return {'success': False, 'message': _t('remote.badKey', _lang()), **get_remote()}
    if action is not None:
        action = str(action)
        if action and action not in REMOTE_ACTIONS:
            return {'success': False, 'message': _t('remote.badAction', _lang()), **get_remote()}
    device = re.sub(r'[\x00-\x1f\x7f]', '', str(device or '')).strip()[:80]

    doc = _remote_keys_doc()
    where = doc['devices'].setdefault(device, {}) if device else doc['all']
    if action is None:
        where.pop(str(code), None)
        if device and not doc['devices'][device]:
            doc['devices'].pop(device, None)
    else:
        where[str(code)] = action
    try:
        os.makedirs(os.path.dirname(REMOTE_KEYS_FILE), exist_ok=True)
        tmp = REMOTE_KEYS_FILE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(doc, f, indent=1)
        os.replace(tmp, REMOTE_KEYS_FILE)
    except Exception:
        log.exception("set_remote_key failed")
        return {'success': False, 'message': _t('remote.saveFailed', _lang()), **get_remote()}
    return {'success': True, 'message': _t('remote.saved', _lang()), **get_remote()}


def set_remote_learning(enable):
    """La finestra "sto provando i tasti": l'interfaccia la guarda e smette di
    agire sui tasti finche' dura. 🚨 Con una scadenza, non un interruttore: un
    browser chiuso a meta' prova non deve lasciare un apparecchio in cui il
    telecomando non comanda piu' niente."""
    try:
        os.makedirs(REMOTE_RUN_DIR, exist_ok=True)
        # 🚨 Scritto e poi rinominato: l'interfaccia sorveglia la cartella, e
        # una riscrittura sul posto non e' un cambiamento di cartella.
        tmp = REMOTE_LEARN_FILE + '.tmp'
        with open(tmp, 'w') as f:
            f.write(str(int(time.time()) + REMOTE_LEARN_SECONDS) if enable else '0')
        os.replace(tmp, REMOTE_LEARN_FILE)
    except Exception:
        log.exception("set_remote_learning failed")
        return {'success': False, 'message': _t('remote.saveFailed', _lang()), **get_remote()}
    return {'success': True, **get_remote()}


# ──────────────────────────────────────────────────────────────────
#  OTA update helpers
# ──────────────────────────────────────────────────────────────────

# ── modalità immagine (schema A/B con RAUC) ───────────────────────────
# Su uno slot immagine (root in sola lettura, costruita da distro/build-image.sh)
# UI, componenti di sistema e OS viaggiano tutti nel bundle RAUC: i tre
# canali legacy non hanno più senso e la versione "installata" è una sola.
# Il marcatore sta fuori da /etc di proposito (l'upper dell'overlay potrebbe
# ombreggiare qualunque cosa sotto /etc).
IMAGE_VERSION_FILE = '/usr/lib/osmium/IMAGE_VERSION'
LYRION_DATA_VERSION_FILE = '/data/lyrion/current/VERSION'
AB_STATE_FILE = '/boot/efi/EFI/debian/abconvert.state'
AB_PRECHECK_FILE = '/run/hifi-ab-precheck.json'
AB_PRECHECK_SCRIPT = '/usr/local/sbin/hifi-ab-precheck.sh'
RAUC_SYSTEM_CONF = '/etc/rauc/system.conf'

def _image_mode():
    """True on a device whose root IS a slot image.

    🚨 A live session is never one, even when it boots from the very same
    squashfs: the ISO is about to carry the image itself as its live
    filesystem, so the marker file is present there too. Without this a live
    session would block its own update channels and answer questions about
    slots it does not have."""
    if not os.path.exists(IMAGE_VERSION_FILE):
        return False
    try:
        return not _is_live_boot()
    except Exception:
        return True

def _ab_ready():
    """Converted to the A/B layout (RAUC configured) but possibly still
    running the legacy root: from here on the image channel is the only
    one that makes sense — legacy bundles would patch a root the next
    image install overwrites."""
    return os.path.exists(RAUC_SYSTEM_CONF)

def _image_version():
    return _read_version_file(IMAGE_VERSION_FILE)

def _booted_slot():
    try:
        with open(PROC_CMDLINE) as f:
            for tok in f.read().split():
                if tok.startswith('rauc.slot='):
                    return tok.split('=', 1)[1]
    except Exception:
        pass
    return None

def _data_partition_mounted():
    """True/False from the initramfs state file, None when it says nothing."""
    try:
        with open('/run/hifi-state/data-mounted') as f:
            flag = f.read().strip()
    except Exception:
        return None
    return flag == '1' if flag in ('0', '1') else None

def ab_status():
    """Stato dello schema A/B per l'interfaccia e per la prova sul campo:
    modalità immagine, slot avviato, stato della conversione (ESP), esito
    delle pre-verifiche e `rauc status` in JSON quando RAUC è configurato."""
    out = {'image_mode': _image_mode(), 'image_version': _image_version() if _image_mode() else None,
           'booted_slot': _booted_slot(), 'rauc_configured': os.path.exists(RAUC_SYSTEM_CONF),
           'state': None, 'precheck': None, 'rauc': None,
           # False = the initramfs fell back to a tmpfs /data (see the
           # local-bottom hifi-state hook): this boot is running on the
           # image's factory /etc and nothing written now survives a reboot.
           # None on a device that predates the flag, or a legacy layout.
           'data_mounted': _data_partition_mounted()}
    try:
        with open(AB_STATE_FILE) as f:
            out['state'] = f.read().strip() or None
    except Exception:
        pass
    try:
        with open(AB_PRECHECK_FILE) as f:
            out['precheck'] = json.load(f)
    except Exception:
        pass
    if out['rauc_configured']:
        try:
            r = _run(['rauc', 'status', '--output-format=json'], timeout=20)
            if r.returncode == 0 and r.stdout.strip():
                out['rauc'] = json.loads(r.stdout)
        except Exception:
            log.exception("ab_status: rauc status failed")
    return out

def _installed_ui_version():
    if _image_mode():
        return _image_version()
    # il file nuovo prima, quello vecchio come ripiego (apparecchi non ancora aggiornati)
    for path in (OTA_VERSION_FILE, OTA_VERSION_FILE_LEGACY):
        try:
            with open(path) as f:
                v = f.read().strip()
            if v:
                return v
        except Exception:
            pass
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

def _fetch_pages_manifest(channel, base=None):
    """Read the channel's static manifest from GitHub Pages (or from `base`,
    its file.osmiumsound.it mirror). Returns a release-
    shaped dict ({tag_name, assets:[…]}) or None if unavailable/empty."""
    url = f'{base or OTA_MANIFEST_BASE}/latest-{channel}.json'
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

        # 2. The copy of the manifest next to the payloads on
        #    file.osmiumsound.it (same host the download comes from anyway).
        try:
            release = _fetch_pages_manifest(channel, OTA_PROD_MIRROR_BASE)
            if release:
                _RELEASE_CACHE[channel] = (now, release)
                return release
        except Exception:
            log.warning("mirror manifest fetch failed for channel %s; falling back to API", channel)

        # 3. Fallback: the rate-limited GitHub REST API.
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

def _debian_codename():
    """VERSION_CODENAME from /etc/os-release ('bookworm', 'trixie', ...), or
    '' if it can't be determined. Python-side counterpart of os-update/
    lib.sh's hifi_suite() -- kept separate rather than shared since this
    module has no shell/subprocess dependency on that file."""
    try:
        return platform.freedesktop_os_release().get('VERSION_CODENAME', '')
    except Exception:
        return ''

# Debian 12 (bookworm) devices can't take an OS update built for a release
# that assumes Debian 13 (trixie) -- see distro/build-distro.sh's labwc/
# wlr-randr/xwayland requirement, packages that only exist from trixie
# onward now that the kiosk session moved to Wayland. Rather than let such a
# device fetch and apply a bundle it can't actually use (and land in some
# half-upgraded state), every update channel is blocked outright once this
# ships to it, and Settings shows a banner telling the owner to reinstall
# from the new (Debian 13) ISO instead of trying to update in place.
_OTA_BLOCKED_CODENAMES = ('bookworm',)

def _check_release_update(current, prefix, channel=None, suffix='.tar.gz', image=False):
    """Look at the relevant GitHub Release and return update info for the asset
    whose name starts with `prefix` (e.g. 'hifi-ui-' or 'hifi-system-').

    channel defaults to the persisted OTA channel; the setup wizard's
    mandatory update gate (wizard_update_check() below) passes an explicit
    one to check prod/dev independently of whatever the device's own channel
    setting happens to be, without touching it."""
    channel = channel or get_ota_channel()
    if (_image_mode() or _ab_ready()) and not image:
        # Slot immagine — o legacy già convertito allo schema A/B (system.conf
        # presente): i canali legacy (ui/system/os) non esistono più, si
        # aggiorna solo l'immagine intera (bundle RAUC). Senza questo blocco il
        # piano post-conversione si portava dietro uno step `ui` inutile (la UI
        # arriva con l'immagine) e Impostazioni mostrava aggiornamenti fantasma.
        return {'current': current, 'latest': None, 'channel': channel,
                'update_available': False, 'blocked': 'image'}
    if _debian_codename() in _OTA_BLOCKED_CODENAMES:
        # Deliberately not `error`: build_update_plan()/_plan_step_from_info()
        # treat that as a failed check and report it; this is a clean,
        # permanent "nothing to do here", with `blocked` as the extra signal
        # the update.jsx/.vue banners key off.
        return {'current': current, 'latest': None, 'channel': channel,
                'update_available': False, 'blocked': 'debian12'}
    try:
        release = _fetch_release(channel)
    except Exception:
        log.exception("update check failed")
        return {'error': _t('update.checkFailed', _lang()), 'current': current, 'channel': channel}

    latest = release.get('tag_name') or release.get('name') or ''
    assets = release.get('assets', [])

    def _named(suffix):
        # `prefix` puo' essere una tupla: si prova nell'ordine dato, cosi' il
        # nome nuovo vince su quello vecchio quando ci sono entrambi
        for pfx in ((prefix,) if isinstance(prefix, str) else prefix):
            a = next((a for a in assets
                      if a.get('name', '').startswith(pfx)
                      and a.get('name', '').endswith(suffix)), None)
            if a:
                return a
        return None

    tarball = _named(suffix)
    sha_asset = _named(suffix + '.sha256')
    sig_asset = _named(suffix + '.sha256.sig')

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

def _installed_image_version():
    """Versione dell'immagine in uso; su una root legacy già convertita (RAUC
    configurato ma nessuna immagine ancora installata) è 'unknown', così la
    prima immagine risulta sempre "più nuova"."""
    if _image_mode():
        return _image_version()
    return 'unknown'

def check_image_update(channel=None):
    """Bundle immagine RAUC: offerto solo dove RAUC è configurato (apparecchio
    convertito allo schema A/B, oppure già in modalità immagine). Un legacy non
    convertito non lo vede: prima passa dal pacchetto 1 (system+OS) che, se le
    pre-verifiche lo permettono, converte le partizioni."""
    channel = channel or get_ota_channel()
    if not os.path.exists(RAUC_SYSTEM_CONF):
        return {'current': 'unknown', 'latest': None, 'channel': channel,
                'update_available': False}
    return _check_release_update(_installed_image_version(), IMAGE_PREFIX, channel,
                                 suffix='.raucb', image=True)

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
        OTA_SCRIPT, 'full', info['asset_url'], sha, info['latest'],
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=True)
    except FileNotFoundError:
        # systemd-run unavailable → fall back to a detached subprocess
        subprocess.Popen([OTA_SCRIPT, 'full', info['asset_url'], sha, info['latest']],
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
    if _image_mode():
        return _image_version()
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
        SYS_SCRIPT, 'full', info['asset_url'], sha, info['latest'],
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=True)
    except FileNotFoundError:
        # systemd-run unavailable → fall back to a detached subprocess
        subprocess.Popen([SYS_SCRIPT, 'full', info['asset_url'], sha, info['latest']],
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
    if _image_mode():
        return _image_version()
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
        OS_SCRIPT, 'full', info['asset_url'], sha, info['sig_url'], info['latest'],
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=True)
    except FileNotFoundError:
        # systemd-run unavailable → fall back to a detached subprocess
        subprocess.Popen([OS_SCRIPT, 'full', info['asset_url'], sha, info['sig_url'], info['latest']],
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
        # 🚨 Nothing you can install onto has zero bytes. Loading the nbd
        # module — which RAUC needs to stream an image — makes the kernel
        # create sixteen empty /dev/nbdN devices, and lsblk reports every one
        # of them as a disk: the installer's picker filled up with
        # "/dev/nbd2 · 0.0 GB" entries and the real disk was lost among them.
        # Same for zram, loop and ram devices, which are memory, not storage.
        try:
            _size = int(dev.get('size') or 0)
        except (TypeError, ValueError):
            _size = 0
        if _size <= 0:
            continue
        _name = path.rsplit('/', 1)[-1]
        if _name.startswith(('nbd', 'zram', 'ram', 'loop', 'dm-')):
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
    'image':  (lambda: check_image_update(),  IMAGE_STATUS_FILE, lambda: _installed_image_version()),
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
    lines = ['v 2',
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

def _read_update_state():
    """Parse UPDATE_STATE_FILE (written by the stage/apply runners), or None
    when there isn't one. Never written from here — this module only reads
    the outcome the shell side recorded."""
    try:
        with open(UPDATE_STATE_FILE) as f:
            lines = f.read().splitlines()
    except Exception:
        return None
    info = {}
    for line in lines:
        k, sep, v = line.partition('=')
        if sep:
            info[k] = v
    if not info:
        return None
    try:
        info['ts'] = int(info.get('ts', 0))
    except ValueError:
        info['ts'] = 0
    return info

def _runner_message(info, fallback=''):
    """User-facing text for a record the shell side wrote (the k=v state file,
    error.json, or a /run/hifi-*-status.json): the runners put a translation
    `key` plus `params` (a JSON object, or a string holding one) next to their
    plain-English `message`. A known key wins — translated into the caller's
    language — so the kiosk in Italian and the web admin in English read the
    same step in their own words; anything else falls back to the raw text."""
    if not isinstance(info, dict):
        return fallback
    key = info.get('key')
    if key and key in _I18N_MESSAGES:
        params = info.get('params') or {}
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except ValueError:
                params = {}
        if not isinstance(params, dict):
            params = {}
        return _t(key, _lang(), **params)
    return info.get('message') or fallback

def _clear_update_state():
    for f in (UPDATE_STATE_FILE, UPDATE_ERROR_FILE):
        try:
            os.remove(f)
        except FileNotFoundError:
            pass
        except Exception:
            log.exception("could not remove %s", f)

def _read_update_error():
    """Detail for a failed apply (channel + message), or None."""
    try:
        with open(UPDATE_ERROR_FILE) as f:
            return json.load(f)
    except Exception:
        return None

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
        if kind not in _PLAN_KINDS:
            continue
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
    """True while the STAGE sequencer is running (either the transient unit
    started by apply_all_updates, or the boot-time stage-resume unit). The
    apply half never runs while this module can observe it — it only ever
    runs isolated under system-update.target, where hifi-api itself is not
    scheduled to start."""
    for unit in (UPDATE_STAGE_RUNNER_UNIT + '.service', 'hifi-update-stage-resume.service'):
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
    stage sequencer. Returns immediately; poll update_plan_status()."""
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

        # A leftover outcome from a previous cycle (done/error banner) would
        # otherwise take priority over this brand-new plan's own progress —
        # see update_plan_status(), which checks the state file first.
        _clear_update_state()

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

        # Belt and braces: a device imaged before hifi-update-stage-runner.sh
        # was added to the ISO's chmod-list (0300-app-install.hook.chroot)
        # ships it non-executable. `systemd-run --no-block` below still
        # returns success in that case — it only queues the transient unit, it
        # doesn't wait for the exec to actually happen — so the permission
        # error is invisible here and only shows up later as a plan stuck
        # forever in 'pending' (nothing ever marks it 'running'). Fix it
        # unconditionally so this class of bug can't silently strand a plan
        # again.
        try:
            os.chmod(UPDATE_STAGE_RUNNER_SCRIPT, 0o755)
        except OSError:
            log.exception("update plan: could not chmod +x %s", UPDATE_STAGE_RUNNER_SCRIPT)

        cmd = ['systemd-run', '--no-block', '--collect',
               '--unit=' + UPDATE_STAGE_RUNNER_UNIT, UPDATE_STAGE_RUNNER_SCRIPT]
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=True)
        except FileNotFoundError:
            # systemd-run unavailable → detached subprocess. It no longer
            # survives a reboot, but the plan on disk does, so the stage-resume
            # unit (or the next apply) finishes the job.
            subprocess.Popen([UPDATE_STAGE_RUNNER_SCRIPT], start_new_session=True)
        except Exception:
            log.exception("update plan: could not start the stage runner")
            _clear_update_plan()
            return {'started': False, 'code': 'update.startFailed',
                    'message': _t('update.startFailed', _lang())}

        return {'started': True, 'plan_id': plan['plan_id'],
                'steps': [{'kind': s['kind'], 'version': s['version']} for s in steps]}

def update_plan_status():
    """Progress of the current update, across BOTH phases and the two reboots
    between them:

    - while staging: the persisted plan's step list plus the live progress of
      whichever step is downloading/verifying (unchanged from before the
      two-phase split);
    - once staging finishes: 'staged_pending_reboot' — the box is about to
      reboot into the isolated apply session on its own, nothing more to poll
      until it comes back;
    - after the box returns (successfully or not): the durable outcome
      hifi-update-apply-runner.sh recorded in UPDATE_STATE_FILE, since by then
      the plan file itself is gone (removed on success) or stale (left behind
      on failure, superseded by the state file — see below).

    The state file is checked FIRST and wins whenever it holds a terminal
    result: hifi-api does not run at all while the apply runner works, so the
    only time this function can ever observe 'applying' is a leftover from a
    run that crashed before finishing — still worth surfacing rather than
    silently falling through to a stale plan."""
    state_info = _read_update_state()
    if state_info and state_info.get('phase') in ('applying', 'done', 'error'):
        phase = state_info['phase']
        ts = state_info.get('ts', 0)
        if phase in ('done', 'error') and time.time() - ts > UPDATE_PLAN_TTL:
            _clear_update_state()
            _clear_update_plan()
        elif phase == 'applying' and time.time() - ts > UPDATE_APPLYING_TTL:
            # Stale: the isolated session (or the A/B conversion chain that
            # deliberately leaves 'applying' across its reboots) never came
            # back to finish. Clear it instead of spinning forever.
            _clear_update_state()
        elif phase == 'applying':
            return {'state': 'applying',
                    'message': _runner_message(state_info, _t('update.applying', _lang())),
                    'finished': None}
        elif phase == 'done':
            return {'state': 'done',
                    'message': _runner_message(state_info, _t('update.applyDone', _lang())),
                    'finished': ts}
        else:
            err = _read_update_error() or {}
            return {'state': 'apply_error', 'kind': err.get('channel', ''),
                    'message': (_runner_message(err) or _runner_message(state_info)
                                or _t('update.applyError', _lang())),
                    'finished': ts}

    plan = _read_update_plan()
    if not plan:
        return {'state': 'idle'}

    state = _plan_overall_state(plan)

    # Retire a finished-but-never-staged (i.e. purely stage-side error) plan
    # once everyone has had a chance to see the outcome, so it stops
    # re-opening the overlay on every client start. A plan that DID finish
    # staging is retired via the state file above instead (it is superseded
    # by 'staged'/'applying'/'done'/'error' the moment the box reboots).
    if plan.get('finished') and time.time() - plan['finished'] > UPDATE_PLAN_TTL:
        _clear_update_plan()
        return {'state': 'idle'}

    # An image step has no apply phase: the reboot IS the apply, so nobody
    # ever rewrites the state file afterwards the way the apply runner does
    # for the legacy channels. Once the image now running is the one this plan
    # staged, the update is over — without this the screen sits on "the device
    # will restart to apply it" for good, on a device that already restarted
    # and is running exactly what was asked for (seen on the Dell going to
    # alpha3). Retiring the plan here is also what stops it from re-opening
    # the overlay at every boot.
    if state == 'finished' and _image_mode():
        _img_step = next((st for st in plan['steps'] if st['kind'] == 'image'), None)
        if _img_step and _img_step.get('version') == _image_version():
            _clear_update_plan()
            return {'state': 'done',
                    'message': _t('update.applyDone', _lang()),
                    'finished': plan.get('finished')}

    # Every step has staged; the stage runner is about to (or already did)
    # create /system-update and reboot into the isolated apply session. There
    # is nothing left to poll here until the box comes back — the state-file
    # branch above takes over from that point on.
    if state == 'finished':
        return {'state': 'staged_pending_reboot',
                'message': _t('update.stagedPendingReboot', _lang()),
                'finished': plan.get('finished')}

    # 'error' ranks above 'pending': the stage runner always stops at the
    # first failed step, so any steps still 'pending' after that were simply
    # never reached — picking one of those as `current` would attribute the
    # failure to the wrong component and its version wouldn't match the
    # (unwritten) live status file below, silently losing the message.
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
            message = _runner_message(live)
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
    """Drop a plan/outcome that is no longer running (the client has shown the
    result). Refuses while either phase is still actually working."""
    with _UPDATE_PLAN_LOCK:
        state = update_plan_status().get('state')
        if state in ('running', 'staged_pending_reboot', 'applying'):
            return {'success': False, 'code': 'update.inProgress',
                    'message': _t('update.inProgress', _lang())}
        _clear_update_state()
        _clear_update_plan()
        return {'success': True}

# ──────────────────────────────────────────────────────────────────
#  Setup wizard: mandatory update gate, right after the network step.
#  Checks the PROD channel only, regardless of the device's own OTA channel
#  setting (always 'prod' this early): a fresh install must be on the current
#  stable release before setup goes on. (Until 2026-08-28 this also checked
#  dev, as a temporary measure from when the wizard only existed on dev
#  builds -- a dev-only release then blocked setup on a stable install, and
#  on a live boot of the very ISO we ship, which can't update at all.)
#
#  Skipped outright on a live session (boot=live): a "Try Osmium Sound" boot
#  runs from the read-only squashfs with a RAM overlay, so nothing an update
#  installs survives a reboot -- and the OS component even stages a reboot
#  to apply itself (hifi-update-stage-resume.service, which deliberately
#  doesn't run under boot=live). Demanding an update there only strands the
#  operator on a step that can never complete.
# ──────────────────────────────────────────────────────────────────
PROC_CMDLINE = '/proc/cmdline'

def _is_live_boot():
    """True when this session booted from the live medium: the ISO's
    bootloader always appends `boot=live` (distro/build-distro.sh), the same
    token the systemd units gate on with ConditionKernelCommandLine=!boot=live.
    Not the same thing as get_boot_mode() above -- that only tells the two
    live menu entries apart ('installer' vs 'live') and answers 'live' on an
    installed system as well."""
    try:
        with open(PROC_CMDLINE) as f:
            return 'boot=live' in f.read().split()
    except Exception:
        return False

def _channel_has_update(channel):
    """Returns (has_update, checked_ok). checked_ok is False only when EVERY
    component's check failed outright (network/API blip) -- distinct from a
    check that actually ran and simply found nothing newer. Right after the
    network step, DNS/routing can still be warming up, so a failed check here
    must not read the same as a confirmed "nothing to update" (see
    wizard_update_check() below)."""
    any_ok = False
    for current, prefix in ((_installed_ui_version(), OTA_UI_PREFIX),
                            (_installed_system_version(), SYS_PREFIX),
                            (_installed_os_version(), OS_PREFIX)):
        try:
            info = _check_release_update(current, prefix, channel)
        except Exception:
            continue
        if info.get('error'):
            continue
        any_ok = True
        if info.get('update_available'):
            return True, True
    return False, any_ok

def wizard_update_check():
    if _is_live_boot():
        # Nothing to check: no network call, no retry loop in the wizard.
        return {'available': False, 'live': True}
    prod_avail, prod_ok = _channel_has_update('prod')
    if prod_avail:
        return {'available': True, 'channel': 'prod', 'auto': True}
    if not prod_ok:
        # The check couldn't run at all -- report it distinctly so the wizard
        # retries instead of treating "couldn't check" the same as "checked,
        # nothing to update".
        return {'available': False, 'checkFailed': True}
    return {'available': False}

def wizard_update_apply(channel):
    if channel != 'prod':
        return {'started': False, 'code': 'update.checkFailed',
                'message': _t('update.checkFailed', _lang())}
    if _is_live_boot():
        return {'started': False, 'code': 'update.liveSession',
                'message': _t('update.liveSession', _lang())}
    # Not a side-channel hack: this is a real, deliberate channel switch (the
    # same one Settings -> Updates would make), so the device legitimately
    # tracks whichever channel it was just updated from, same as if the
    # operator had picked it there.
    set_ota_channel(channel)
    return apply_all_updates()

# ──────────────────────────────────────────────────────────────────
#  Lyrion Music Server update helpers
# ──────────────────────────────────────────────────────────────────

def _lyrion_installed_version():
    if _image_mode():
        # su /data, scompattato da hifi-lyrion-update.sh: niente dpkg
        return _read_version_file(LYRION_DATA_VERSION_FILE)
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

def _ui_update_check(check_fn):
    """What the three update cards on screen should show.

    On an image system the interface, the system components and the OS are no
    longer three things that update on their own: they are one image. The
    legacy checks correctly answer "blocked" there, but the three frontends
    only ever ask those three, so a perfectly available image update showed up
    as "everything up to date" — the appliance knew, the screen did not (seen
    on the Dell with alpha3 already published). So in image mode all three
    answer with the image check. It is the same version in all three rows
    because it is the same image, and the changelog rides along on the first.

    The same holds for a device that has been converted but is still booting
    its old root while it waits for the first image (system.conf present,
    IMAGE_VERSION not yet): its legacy channels are blocked too, so without
    this it would show nothing at all in the very window where the image is
    what it needs.

    The plan builder keeps calling check_app/system/os_update directly, so it
    still sees "blocked" and does not try to stage a .raucb as a tarball.
    """
    if _image_mode() or _ab_ready():
        info = dict(check_image_update())
        info['kind'] = 'image'
        return info
    return check_fn()

@app.route('/app_update/check', methods=['GET'])
def api_app_update_check():
    return jsonify(_ui_update_check(check_app_update))

@app.route('/app_update/apply', methods=['POST'])
def api_app_update_apply():
    return jsonify(apply_app_update())

@app.route('/app_update/status', methods=['GET'])
def api_app_update_status():
    return jsonify(app_update_status())

@app.route('/system_update/check', methods=['GET'])
def api_system_update_check():
    return jsonify(_ui_update_check(check_system_update))

@app.route('/system_update/apply', methods=['POST'])
def api_system_update_apply():
    return jsonify(apply_system_update())

@app.route('/system_update/status', methods=['GET'])
def api_system_update_status():
    return jsonify(system_update_status())

@app.route('/os_update/check', methods=['GET'])
def api_os_update_check():
    return jsonify(_ui_update_check(check_os_update))

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

@app.route('/wizard_update_check', methods=['GET'])
def api_wizard_update_check():
    return jsonify(wizard_update_check())

@app.route('/wizard_update_apply', methods=['POST'])
def api_wizard_update_apply():
    data = request.get_json(silent=True) or {}
    return jsonify(wizard_update_apply(data.get('channel')))

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

@app.route('/network_check', methods=['GET'])
def api_network_check():
    return jsonify(network_check())

@app.route('/connectivity', methods=['GET'])
def api_connectivity():
    return jsonify(get_connectivity(force=request.args.get('force') == '1'))

@app.route('/wifi_scan', methods=['GET'])
def api_wifi_scan():
    return jsonify(wifi_scan())

@app.route('/wifi_connect', methods=['POST'])
def api_wifi_connect():
    data = request.get_json(silent=True) or {}
    return jsonify(wifi_connect(data.get('ssid'), data.get('password', ''),
                                (data.get('band') or '').strip()))

@app.route('/wired_dhcp', methods=['POST'])
def api_wired_dhcp():
    return jsonify(wired_dhcp())

# Fixed (static) address for the active uplink — driven by the admin-webui
# Network page. Unlike /configure_network above this edits the NetworkManager
# profile, so the address survives a reboot.
@app.route('/ipv4_config', methods=['GET'])
def api_ipv4_config_get():
    return jsonify(get_ipv4_config())

@app.route('/ipv4_config', methods=['POST'])
def api_ipv4_config_set():
    data = request.get_json(silent=True) or {}
    result = set_ipv4_config(data)
    return jsonify(result), (200 if result.get('success') else 400)

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

@app.route('/ui_engine', methods=['GET'])
def api_ui_engine():
    return jsonify(get_ui_engine())

@app.route('/ui_engine', methods=['POST'])
def api_set_ui_engine():
    data = request.get_json(silent=True) or {}
    return jsonify(set_ui_engine((data.get('engine') or '').strip()))

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

@app.route('/ui_refresh', methods=['GET'])
def api_ui_refresh():
    return jsonify(get_ui_refresh())

@app.route('/ui_refresh', methods=['POST'])
def api_set_ui_refresh():
    data = request.get_json(silent=True) or {}
    return jsonify(set_ui_refresh((data.get('mode') or '').strip()))

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

@app.route('/vu_style', methods=['GET'])
def api_vu_style():
    return jsonify(get_vu_style())

# One file of an installed skin (its skin.json or an image), so the web admin
# can draw the same still preview of every style the kiosk shows in Settings →
# VU meter. Names are flat, like the store unpacks them; a skin shipped with
# the interface wins over a downloaded one with the same id, as in
# list_vu_styles().
_VU_SKIN_FILE_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{0,80}\.(png|jpg|json)$')
_VU_SKIN_MIME = {'png': 'image/png', 'jpg': 'image/jpeg', 'json': 'application/json'}

@app.route('/vu_skin/<sid>/<name>', methods=['GET'])
def api_vu_skin_file(sid, name):
    if not _VU_STYLE_RE.match(sid) or not _VU_SKIN_FILE_RE.match(name):
        return jsonify({'success': False}), 404
    for base in (VU_SKINS_DIR, VU_STORE_DIR):
        if not os.path.isfile(os.path.join(base, sid, 'skin.json')):
            continue
        try:
            with open(os.path.join(base, sid, name), 'rb') as f:
                data = f.read()
        except OSError:
            break
        resp = Response(data, mimetype=_VU_SKIN_MIME[name.rsplit('.', 1)[1]])
        resp.headers['Cache-Control'] = 'private, max-age=300'
        return resp
    return jsonify({'success': False}), 404

@app.route('/vu_style', methods=['POST'])
def api_set_vu_style():
    data = request.get_json(silent=True) or {}
    return jsonify(set_vu_style(data.get('style')))

@app.route('/nowplaying_animation', methods=['GET'])
def api_nowplaying_animation():
    return jsonify(get_nowplaying_animation())

@app.route('/nowplaying_animation', methods=['POST'])
def api_set_nowplaying_animation():
    data = request.get_json(silent=True)
    result = set_nowplaying_animation(data.get('animation') if isinstance(data, dict) else None)
    if result['success']:
        return jsonify(result)
    return jsonify(result), (400 if result.get('code') == 'prefs.animationUnknown' else 500)

@app.route('/vu_store', methods=['GET'])
def api_vu_store():
    return jsonify(get_vu_store(summary=request.args.get('summary') == '1'))

@app.route('/vu_store/check', methods=['POST'])
def api_vu_store_check():
    return jsonify(vu_store_check())

@app.route('/vu_store/install', methods=['POST'])
def api_vu_store_install():
    data = request.get_json(silent=True) or {}
    return jsonify(vu_store_install(data.get('id')))

@app.route('/vu_store/remove', methods=['POST'])
def api_vu_store_remove():
    data = request.get_json(silent=True) or {}
    return jsonify(vu_store_remove(data.get('id')))

@app.route('/vu_store/seen', methods=['POST'])
def api_vu_store_seen():
    return jsonify(vu_store_mark_seen())

@app.route('/anim_store', methods=['GET'])
def api_anim_store():
    return jsonify(get_anim_store(summary=request.args.get('summary') == '1'))

@app.route('/anim_store/check', methods=['POST'])
def api_anim_store_check():
    return jsonify(anim_store_check())

@app.route('/anim_store/install', methods=['POST'])
def api_anim_store_install():
    data = request.get_json(silent=True) or {}
    return jsonify(anim_store_install(data.get('id')))

@app.route('/anim_store/remove', methods=['POST'])
def api_anim_store_remove():
    data = request.get_json(silent=True) or {}
    return jsonify(anim_store_remove(data.get('id')))

@app.route('/anim_store/seen', methods=['POST'])
def api_anim_store_seen():
    return jsonify(anim_store_mark_seen())

@app.route('/vu_meter', methods=['POST'])
def api_set_vu_meter():
    data = request.get_json(silent=True) or {}
    return jsonify(set_vu_meter(bool(data.get('enable'))))

@app.route('/ui_language', methods=['GET'])
def api_ui_language():
    return jsonify(get_ui_language())

@app.route('/ui_language', methods=['POST'])
def api_set_ui_language():
    data = request.get_json(silent=True) or {}
    return jsonify(set_ui_language(data.get('language')))

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
                                          data.get('password') or '',
                                          (data.get('band') or '').strip()))

@app.route('/provision_wifi_rescan', methods=['POST'])
def api_provision_wifi_rescan():
    return jsonify(provision_wifi_rescan())

@app.route('/factory_reset', methods=['POST'])
def api_factory_reset():
    return jsonify(factory_reset())

@app.route('/webui_reset_credentials', methods=['POST'])
def api_webui_reset_credentials():
    return jsonify(webui_reset_credentials())

@app.route('/image_update/check', methods=['GET'])
def api_image_update_check():
    return jsonify(check_image_update())

@app.route('/ab_status', methods=['GET'])
def api_ab_status():
    return jsonify(ab_status())

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

@app.route('/hostname_apply', methods=['POST'])
def api_apply_hostname():
    # Internal-only (this API is bound to 127.0.0.1, see the bottom of this
    # file): re-applies an already-restored /etc/hostname at the OS level,
    # for sources_server.py's backup-restore path. Deliberately a separate
    # route from /device_name above — see _apply_hostname's docstring for why
    # it must not also touch the player name.
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not _valid_device_name(name):
        return jsonify({'success': False, 'code': 'device.invalidName',
                        'message': _t('device.invalidName', _lang())})
    return jsonify(_apply_hostname(name))

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

# ── Bluetooth speakers (A2DP source) ──────────────────────────────
# /bluetooth_status keeps its old path: it is the one Bluetooth route that
# ever had callers outside this file, and answering it with the new shape
# costs nothing. The sink-era routes (/bluetooth_discoverable,
# /bluetooth_now_playing) are gone with the sink role itself.
@app.route('/bluetooth_status', methods=['GET'])
@app.route('/bt_speakers', methods=['GET'])
def api_bt_speakers():
    return jsonify(get_bt_speakers())

@app.route('/bluetooth_set', methods=['POST'])
@app.route('/bt_speakers/enable', methods=['POST'])
def api_bt_enable():
    data = request.get_json(silent=True) or {}
    return jsonify(set_bt_enabled(bool(data.get('enable'))))

@app.route('/bt_speakers/scan', methods=['POST'])
def api_bt_scan():
    data = request.get_json(silent=True) or {}
    return jsonify(bt_scan(data.get('seconds', 10)))

@app.route('/bt_speakers/add', methods=['POST'])
def api_bt_add():
    data = request.get_json(silent=True) or {}
    return jsonify(bt_add_speaker(data.get('mac'), data.get('player')))

@app.route('/bluetooth_forget', methods=['POST'])
@app.route('/bt_speakers/remove', methods=['POST'])
def api_bt_remove():
    data = request.get_json(silent=True) or {}
    return jsonify(bt_remove_speaker(data.get('mac')))

@app.route('/bt_speakers/update', methods=['POST'])
def api_bt_update():
    data = request.get_json(silent=True) or {}
    fields = {k: data[k] for k in ('player', 'enabled', 'autoconnect', 'codec')
              if k in data}
    return jsonify(bt_update_speaker(data.get('mac'), fields))

@app.route('/bt_speakers/connect', methods=['POST'])
def api_bt_connect():
    data = request.get_json(silent=True) or {}
    return jsonify(bt_connect(data.get('mac'), bool(data.get('connect', True))))

# ── telecomandi Bluetooth ────────────────────────────────────────────
# Solo accoppiare e dimenticare: quando il telecomando e' accoppiato, i
# tasti li legge da se' l'interfaccia dallo /dev/input che il nucleo
# crea (native-ui-qt/src/remote.cpp), senza passare da qui.
@app.route('/bt_remotes', methods=['GET'])
def api_bt_remotes():
    return jsonify(get_bt_remotes())

@app.route('/bt_remotes/scan', methods=['POST'])
def api_bt_remotes_scan():
    data = request.get_json(silent=True) or {}
    return jsonify(bt_remotes_scan(data.get('seconds', 12)))

@app.route('/bt_remotes/add', methods=['POST'])
def api_bt_remotes_add():
    data = request.get_json(silent=True) or {}
    return jsonify(bt_remote_add(data.get('mac')))

@app.route('/bt_remotes/remove', methods=['POST'])
def api_bt_remotes_remove():
    data = request.get_json(silent=True) or {}
    return jsonify(bt_remote_remove(data.get('mac')))

# ── telecomandi, dal web admin ───────────────────────────────────────
@app.route('/remote', methods=['GET'])
def api_remote():
    return jsonify(get_remote())

@app.route('/remote/device', methods=['POST'])
def api_remote_device():
    data = request.get_json(silent=True) or {}
    return jsonify(set_remote_device(data.get('device')))

@app.route('/remote/keys', methods=['POST'])
def api_remote_keys():
    data = request.get_json(silent=True) or {}
    # 'action' assente = togli l'assegnazione; "" = questo tasto non fa niente
    action = data.get('action', None) if 'action' in data else None
    return jsonify(set_remote_key(data.get('code'), action, data.get('device', '')))

@app.route('/remote/learn', methods=['POST'])
def api_remote_learn():
    data = request.get_json(silent=True) or {}
    return jsonify(set_remote_learning(bool(data.get('enable'))))

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
    threading.Thread(target=_vu_store_background, daemon=True, name='vu-store').start()
    threading.Thread(target=_anim_store_background, daemon=True, name='anim-store').start()
    app.run(host='127.0.0.1', port=8000, threaded=True)