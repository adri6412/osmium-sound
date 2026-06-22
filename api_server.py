from flask import Flask, jsonify, request
from flask_cors import CORS
import subprocess
import os
import signal
import sys
import socket
import platform
import re
import json
import logging
import urllib.request

app = Flask(__name__)
CORS(app)  # Abilita CORS per tutte le route

# Log full diagnostics server-side; never leak exception text / stack traces to
# HTTP clients (this API runs as root). Use `log.exception(...)` in handlers and
# return a generic message to the caller instead.
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s')
log = logging.getLogger('hifi.api')

# Security headers middleware
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

# ──────────────────────────────────────────────────────────────────
#  OTA update of the Electron UI (whole /opt/hifi-media-player dir).
#  The actual download/swap/restart is done as root by the helper
#  script; here we only check GitHub Releases and kick it off.
# ──────────────────────────────────────────────────────────────────
OTA_REPO = os.environ.get('HIFI_OTA_REPO', 'adri6412/hifi-media-player')
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
#  OTA update of Lyrion Music Server (stable .deb from the community
#  downloads server). We parse the downloads page for the latest
#  stable release and install it as root.
# ──────────────────────────────────────────────────────────────────
LYRION_DOWNLOADS_PAGE = os.environ.get('HIFI_LYRION_PAGE', 'https://downloads.lms-community.org/')
LYRION_PKG = 'lyrionmusicserver'
LYRION_SCRIPT = '/usr/local/sbin/hifi-lyrion-update.sh'
LYRION_STATUS_FILE = '/run/hifi-lyrion-status.json'

# Funzione per aggiornare il sistema
def update_system():
    try:
        process = subprocess.Popen("sudo apt-get update && sudo apt-get upgrade -y", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process.wait()
        return "System updated successfully"
    except Exception:
        log.exception("update_system failed")
        return "Failed to update system"

# Funzione per riavviare il dispositivo
def reboot_device():
    try:
        subprocess.Popen("sudo reboot", shell=True)
        return "Device rebooting"
    except Exception:
        log.exception("reboot_device failed")
        return "Failed to reboot device"

# Funzione per spegnere il dispositivo
def shutdown_device():
    try:
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
            'error': 'Errore nel recupero delle informazioni di sistema'
        }

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
            if not re.match(r'^[A-Za-z0-9._-]+$', interface_name or ''):
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

def _active_device():
    """Return (device, type) of the first connected wifi/ethernet device."""
    try:
        r = _run(['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE', 'device', 'status'])
        for line in r.stdout.strip().split('\n'):
            parts = _terse_split(line)
            if len(parts) >= 3 and parts[2] == 'connected' and parts[1] in ('wifi', 'ethernet'):
                return parts[0], parts[1]
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
        r = _run(['nmcli', '-t', '-f', 'IN-USE,SSID,SIGNAL,SECURITY', 'device', 'wifi', 'list'])
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
    except Exception:
        log.exception("wifi_scan failed")
        return {'networks': [], 'error': 'Scansione WiFi fallita'}
    return {'networks': networks}

def wifi_connect(ssid, password):
    if not ssid:
        return {'success': False, 'message': 'SSID mancante'}
    # ssid/password are passed as argv to nmcli (no shell), but a value that
    # starts with '-' or carries control characters could still be parsed as a
    # flag or break the command line. Validate with an anchored regexp (no
    # control chars, no leading dash) before building argv.
    safe_arg = re.compile(r'(?!-)[^\x00-\x1f]+')
    for label, value in (('SSID', ssid), ('password', password or '')):
        if value and not safe_arg.fullmatch(value):
            return {'success': False, 'message': f'{label} non valido'}
    cmd = ['nmcli', 'device', 'wifi', 'connect', ssid]
    if password:
        cmd += ['password', password]
    try:
        r = _run(cmd, timeout=45)
    except subprocess.TimeoutExpired:
        return {'success': False, 'message': 'Timeout durante la connessione'}
    except Exception:
        log.exception("wifi_connect failed")
        return {'success': False, 'message': 'Connessione fallita'}
    if r.returncode == 0:
        device, _ = _active_device()
        return {'success': True, 'message': f'Connesso a {ssid}', 'ip': _device_ip(device)}
    return {'success': False, 'message': (r.stderr or r.stdout).strip() or 'Connessione fallita'}

def wired_dhcp():
    eth = _first_device_of_type('ethernet')
    if not eth:
        return {'success': False, 'message': 'Nessuna interfaccia Ethernet trovata'}
    try:
        r = _run(['nmcli', 'device', 'connect', eth], timeout=45)
    except Exception:
        log.exception("wired_dhcp failed")
        return {'success': False, 'message': 'Connessione via cavo fallita'}
    ip = _device_ip(eth)
    if ip:
        return {'success': True, 'message': 'Connesso via cavo', 'ip': ip}
    return {'success': r.returncode == 0, 'message': (r.stderr or r.stdout).strip() or 'Cavo non connesso', 'ip': ip}

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
    devices = [{'id': 'default', 'name': 'Predefinito di sistema', 'card': None, 'device': None}]
    try:
        r = _run(['aplay', '-l'])
        for line in r.stdout.split('\n'):
            # e.g. "card 0: D50s [Topping D50s], device 0: USB Audio [USB Audio]"
            m = re.match(r'card (\d+): (\S+) \[([^\]]+)\], device (\d+): [^\[]*\[([^\]]+)\]', line)
            if m:
                card, cid, cname, dev, dname = (
                    int(m.group(1)), m.group(2), m.group(3), int(m.group(4)), m.group(5))
                devices.append({
                    'id': f'hw:CARD={cid},DEV={dev}',
                    'name': f'{cname} — {dname}',
                    'card': card,
                    'device': dev,
                })
    except Exception:
        log.exception("list_audio_devices failed")
        return {'devices': devices, 'current': _current_audio_device(),
                'error': 'Lettura dispositivi audio fallita'}
    return {'devices': devices, 'current': _current_audio_device()}

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
        return {'success': False, 'message': 'Device mancante'}

    # Validate device is one of the valid audio device IDs from list_audio_devices()
    valid_devices = [d['id'] for d in list_audio_devices()['devices']]
    if device not in valid_devices:
        return {'success': False, 'message': f'Dispositivo audio non valido: {device}'}

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
        return {'success': False, 'message': 'Scrittura configurazione fallita'}

    try:
        r = _run(['systemctl', 'restart', 'squeezelite'], timeout=30)
        if r.returncode != 0:
            return {'success': True, 'message': f'Device impostato ({device}); riavvio squeezelite: {(r.stderr or "").strip()}'}
    except Exception:
        log.exception("set_audio_device: squeezelite restart failed")
        return {'success': True, 'message': f'Device impostato ({device}); riavvio non riuscito'}
    return {'success': True, 'message': f'Uscita audio impostata su {device}'}

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
    Returns True if the SSH unit is present afterwards."""
    try:
        # Refresh the index first; a long-running appliance may have a stale one.
        subprocess.run(['sudo', 'apt-get', 'update'],
                      capture_output=True, text=True, timeout=120)
        subprocess.run(['sudo', 'apt-get', 'install', '-y', 'openssh-server'],
                      capture_output=True, text=True, timeout=180)
    except Exception:
        log.exception("openssh-server install failed")
        return False
    return _ssh_available()

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
                'error': 'Stato SSH non disponibile'}

def set_ssh(enable):
    """Enable+start or disable+stop the SSH server (persists across reboots).
    When enabling on an image that doesn't ship openssh-server, install it
    first so the toggle works out of the box."""
    if enable and not _ssh_available():
        if not _install_openssh():
            return {'success': False, 'available': False, 'enabled': False,
                    'active': False, 'message': 'Installazione di openssh-server fallita'}
    unit = _ssh_unit()
    action = 'enable' if enable else 'disable'
    try:
        r = subprocess.run(['sudo', 'systemctl', action, '--now', unit],
                          capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            log.error("set_ssh %s failed: %s", action, (r.stderr or '').strip())
            status = get_ssh_status()
            status['success'] = False
            status['message'] = 'Operazione SSH fallita'
            return status
    except Exception:
        log.exception("set_ssh failed")
        return {'success': False, 'message': 'Operazione SSH fallita'}
    status = get_ssh_status()
    status['success'] = True
    status['message'] = 'SSH abilitato' if enable else 'SSH disabilitato'
    return status

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

def _is_newer(latest, current):
    """True if `latest` should be offered over `current`."""
    if not latest:
        return False
    if current in (None, '', 'unknown'):
        return True
    lt, ct = _version_tuple(latest), _version_tuple(current)
    if lt and ct:
        return lt > ct
    return latest != current  # fallback: any difference is an update

def _read_version_file(path):
    try:
        with open(path) as f:
            return f.read().strip() or 'unknown'
    except Exception:
        return 'unknown'

def _check_release_update(current, prefix):
    """Look at the latest GitHub Release and return update info for the asset
    whose name starts with `prefix` (e.g. 'hifi-ui-' or 'hifi-system-')."""
    url = f'https://api.github.com/repos/{OTA_REPO}/releases/latest'
    req = urllib.request.Request(url, headers={
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'hifi-player-ota',
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            release = json.load(resp)
    except Exception:
        log.exception("update check failed")
        return {'error': 'Controllo aggiornamenti fallito', 'current': current}

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
    """Download the .sha256 sidecar and return just the hex digest."""
    req = urllib.request.Request(sha_url, headers={'User-Agent': 'hifi-player-ota'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        text = resp.read().decode('utf-8', 'replace').strip()
    # format is "<sha>  <filename>"; take the first whitespace-delimited token
    return text.split()[0] if text else ''

def apply_app_update():
    info = check_app_update()
    if info.get('error'):
        return {'started': False, 'message': info['error']}
    if not info.get('update_available'):
        return {'started': False, 'message': 'Nessun aggiornamento disponibile'}
    if not info.get('sha_url'):
        return {'started': False, 'message': 'Checksum (.sha256) mancante nella release'}

    try:
        sha = _fetch_sha256(info['sha_url'])
    except Exception:
        log.exception("update: checksum fetch failed")
        return {'started': False, 'message': 'Lettura checksum fallita'}
    if not sha:
        return {'started': False, 'message': 'Checksum vuoto'}

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
        return {'started': False, 'message': 'Avvio aggiornamento fallito'}
    except Exception:
        log.exception("update: apply failed")
        return {'started': False, 'message': 'Avvio aggiornamento fallito'}
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
        return {'started': False, 'message': 'Nessun aggiornamento disponibile'}
    if not info.get('sha_url'):
        return {'started': False, 'message': 'Checksum (.sha256) mancante nella release'}

    try:
        sha = _fetch_sha256(info['sha_url'])
    except Exception:
        log.exception("update: checksum fetch failed")
        return {'started': False, 'message': 'Lettura checksum fallita'}
    if not sha:
        return {'started': False, 'message': 'Checksum vuoto'}

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
        return {'started': False, 'message': 'Avvio aggiornamento fallito'}
    except Exception:
        log.exception("update: apply failed")
        return {'started': False, 'message': 'Avvio aggiornamento fallito'}
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
        return {'started': False, 'message': 'Nessun aggiornamento OS disponibile'}
    if not info.get('sha_url'):
        return {'started': False, 'message': 'Checksum (.sha256) mancante nella release'}
    # The OS bundle runs root scripts, so a valid signature is mandatory.
    if not info.get('sig_url'):
        return {'started': False,
                'message': 'Firma (.sha256.sig) mancante: aggiornamento OS rifiutato'}

    try:
        sha = _fetch_sha256(info['sha_url'])
    except Exception:
        log.exception("update: checksum fetch failed")
        return {'started': False, 'message': 'Lettura checksum fallita'}
    if not sha:
        return {'started': False, 'message': 'Checksum vuoto'}

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
        return {'started': False, 'message': 'Avvio aggiornamento fallito'}
    except Exception:
        log.exception("update: apply failed")
        return {'started': False, 'message': 'Avvio aggiornamento fallito'}
    return {'started': True, 'version': info['latest']}

def os_update_status():
    try:
        with open(OS_STATUS_FILE) as f:
            return json.load(f)
    except Exception:
        return {'state': 'idle'}

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

def check_lyrion_update():
    current = _lyrion_installed_version()
    req = urllib.request.Request(LYRION_DOWNLOADS_PAGE,
                                 headers={'User-Agent': 'hifi-player-ota'})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', 'replace')
    except Exception:
        log.exception("lyrion update check failed")
        return {'error': 'Controllo aggiornamenti Lyrion fallito', 'current': current}

    # Stable releases live under LyrionMusicServer_v<X.Y.Z>/lyrionmusicserver_<X.Y.Z>_all.deb
    # (nightlies are under /nightly/ and do not match this pattern → excluded).
    matches = re.findall(
        r'https://downloads\.lms-community\.org/LyrionMusicServer_v(\d+\.\d+\.\d+)/'
        r'lyrionmusicserver_\1_all\.deb', html)
    if not matches:
        return {'error': 'Nessuna release stabile trovata sul server download', 'current': current}

    latest = max(set(matches), key=_version_tuple)
    asset_url = (f'https://downloads.lms-community.org/LyrionMusicServer_v{latest}/'
                 f'lyrionmusicserver_{latest}_all.deb')
    return {
        'current': current,
        'latest': latest,
        'update_available': _is_newer(latest, current),
        'asset_url': asset_url,
    }

def apply_lyrion_update():
    info = check_lyrion_update()
    if info.get('error'):
        return {'started': False, 'message': info['error']}
    if not info.get('update_available'):
        return {'started': False, 'message': 'Nessun aggiornamento Lyrion disponibile'}

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
        return {'started': False, 'message': 'Avvio aggiornamento fallito'}
    except Exception:
        log.exception("update: apply failed")
        return {'started': False, 'message': 'Avvio aggiornamento fallito'}
    return {'started': True, 'version': info['latest']}

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
                return f"Tastiera virtuale {cmd} avviata"
            except subprocess.CalledProcessError:
                print(f"{cmd} not found, trying next...")
                continue
        
        return "Nessuna tastiera virtuale di sistema trovata. Installa onboard, florence, xvkbd o matchbox-keyboard"
    except Exception:
        log.exception("show_global_keyboard failed")
        return "Errore nell'avvio della tastiera virtuale"

# Funzione per nascondere la tastiera virtuale globale
def hide_global_keyboard():
    try:
        # Kill virtual keyboard processes
        subprocess.run("pkill -f onboard", shell=True, capture_output=True)
        subprocess.run("pkill -f florence", shell=True, capture_output=True)
        subprocess.run("pkill -f xvkbd", shell=True, capture_output=True)
        subprocess.run("pkill -f matchbox-keyboard", shell=True, capture_output=True)
        return "Tastiera virtuale chiusa"
    except Exception:
        log.exception("hide_global_keyboard failed")
        return "Errore nella chiusura della tastiera virtuale"

@app.route('/check', methods=['GET'])
def api_check():
    return jsonify({"message": "ok"})

@app.route('/update_system', methods=['POST'])
def api_update_system():
    result = update_system()
    return jsonify({"message": result})

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

@app.route('/lyrion_update/check', methods=['GET'])
def api_lyrion_update_check():
    return jsonify(check_lyrion_update())

@app.route('/lyrion_update/apply', methods=['POST'])
def api_lyrion_update_apply():
    return jsonify(apply_lyrion_update())

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

@app.route('/audio_devices', methods=['GET'])
def api_audio_devices():
    return jsonify(list_audio_devices())

@app.route('/set_audio_device', methods=['POST'])
def api_set_audio_device():
    data = request.get_json(silent=True) or {}
    return jsonify(set_audio_device(data.get('device')))

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
    app.run(host='127.0.0.1', port=8000)