from flask import Flask, jsonify, request
from flask_cors import CORS
import subprocess
import os
import signal
import sys
import socket
import platform
import re

app = Flask(__name__)
CORS(app)  # Abilita CORS per tutte le route

# Funzione per aggiornare il sistema
def update_system():
    try:
        process = subprocess.Popen("sudo apt-get update && sudo apt-get upgrade -y", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process.wait()
        return "System updated successfully"
    except Exception as e:
        return f"Failed to update system: {e}"

# Funzione per riavviare il dispositivo
def reboot_device():
    try:
        subprocess.Popen("sudo reboot", shell=True)
        return "Device rebooting"
    except Exception as e:
        return f"Failed to reboot device: {e}"

# Funzione per spegnere il dispositivo
def shutdown_device():
    try:
        subprocess.Popen("sudo shutdown now", shell=True)
        return "Device shutting down"
    except Exception as e:
        return f"Failed to shutdown device: {e}"

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
    except Exception as e:
        return f"Failed to close all apps and restart: {e}"

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
            'version': '1.0.0',
            'local_ip': local_ip,
            'network_interfaces': network_interfaces
        }
    except Exception as e:
        return {
            'hostname': 'Unknown',
            'platform': platform.platform(),
            'arch': platform.machine(),
            'version': '1.0.0',
            'local_ip': 'Unknown',
            'network_interfaces': [],
            'error': str(e)
        }

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
    except Exception as e:
        return f"Network configuration failed: {str(e)}"

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
    except Exception as e:
        return {'networks': [], 'error': str(e)}
    return {'networks': networks}

def wifi_connect(ssid, password):
    if not ssid:
        return {'success': False, 'message': 'SSID mancante'}
    cmd = ['nmcli', 'device', 'wifi', 'connect', ssid]
    if password:
        cmd += ['password', password]
    try:
        r = _run(cmd, timeout=45)
    except subprocess.TimeoutExpired:
        return {'success': False, 'message': 'Timeout durante la connessione'}
    except Exception as e:
        return {'success': False, 'message': str(e)}
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
    except Exception as e:
        return {'success': False, 'message': str(e)}
    ip = _device_ip(eth)
    if ip:
        return {'success': True, 'message': 'Connesso via cavo', 'ip': ip}
    return {'success': r.returncode == 0, 'message': (r.stderr or r.stdout).strip() or 'Cavo non connesso', 'ip': ip}

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
    except Exception as e:
        return f"Errore nell'avvio della tastiera virtuale: {str(e)}"

# Funzione per nascondere la tastiera virtuale globale
def hide_global_keyboard():
    try:
        # Kill virtual keyboard processes
        subprocess.run("pkill -f onboard", shell=True, capture_output=True)
        subprocess.run("pkill -f florence", shell=True, capture_output=True)
        subprocess.run("pkill -f xvkbd", shell=True, capture_output=True)
        subprocess.run("pkill -f matchbox-keyboard", shell=True, capture_output=True)
        return "Tastiera virtuale chiusa"
    except Exception as e:
        return f"Errore nella chiusura della tastiera virtuale: {str(e)}"

@app.route('/check', methods=['GET'])
def api_check():
    return jsonify({"message": "ok"})

@app.route('/update_system', methods=['POST'])
def api_update_system():
    result = update_system()
    return jsonify({"message": result})

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

@app.route('/show_global_keyboard', methods=['POST'])
def api_show_global_keyboard():
    result = show_global_keyboard()
    return jsonify({"message": result})

@app.route('/hide_global_keyboard', methods=['POST'])
def api_hide_global_keyboard():
    result = hide_global_keyboard()
    return jsonify({"message": result})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)