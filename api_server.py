from flask import Flask, jsonify, request
from flask_cors import CORS
import subprocess
import os
import signal
import sys
import socket
import platform
import threading

app = Flask(__name__)

# Start the VU meter daemon as a background process when the API server starts
def start_vu_meter_daemon():
    try:
        # Check if it's already running
        subprocess.run(["pkill", "-f", "vu_meter_daemon.py"], capture_output=True)
        # Launch it
        daemon_path = os.path.join(os.path.dirname(__file__), "vu_meter_daemon.py")
        print(f"Starting VU meter daemon from: {daemon_path}")
        subprocess.Popen([sys.executable, daemon_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"Error starting VU meter daemon: {e}")

# Run daemon initialization in background to not block Flask startup
threading.Thread(target=start_vu_meter_daemon, daemon=True).start()
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