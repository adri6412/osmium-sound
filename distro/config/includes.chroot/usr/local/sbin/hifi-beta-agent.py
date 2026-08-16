#!/usr/bin/env python3
"""HiFi Player — private beta-testing telemetry agent.

Persistent daemon (systemd Type=simple, Restart=always — see
hifi-beta-agent.service) that runs on every beta-tester appliance. Deliberately
"dumb": it never decides anything on its own cadence. Every cycle it first
asks the cloud server (GET /api/v1/config) how often to run and whether the
on-device HAR/perf captures (main.js's Settings -> Debug feature, see
HAR_CAPTURE_DIR/PERF_CAPTURE_DIR below) should be running right now, writes
that schedule to a file main.js polls, then uploads whatever new
snapshot/capture data there is. Captures (HAR + perf) are deleted from disk
once fully uploaded, so beta devices don't accumulate them indefinitely. All
cadence lives in the dashboard on the server, not here — see
beta-telemetry/server/.

State (device token, per-file upload offsets) persists to STATE_FILE so a
restart never re-registers or re-uploads already-shipped data.
"""
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, '/usr/local/bin')
try:
    from hifi_logging import tee_stdio_to_file
    tee_stdio_to_file('beta-agent')
except Exception:
    pass

try:
    import psutil
except Exception:
    psutil = None

# ── fixed configuration (the only things that cannot, by nature, come from
#    the server: how to reach it in the first place) ───────────────────────
SERVER_URL = os.environ.get('HIFI_BETA_SERVER_URL', 'https://telemetry.osmiumsound.it')
# Deliberately NOT a real secret in source -- this repo is public. The build
# workflow substitutes the real value in at release-build time from a GitHub
# Actions secret (same pattern as the OTA_SIGNING_KEY used to sign OS
# updates), so it never touches git history. See build-ui-ota.yml.
BOOTSTRAP_SECRET = os.environ.get('HIFI_BETA_BOOTSTRAP_SECRET', 'REPLACE_ME_BOOTSTRAP_SECRET')

STATE_DIR = os.environ.get('HIFI_BETA_STATE_DIR', '/var/lib/hifi-beta-agent')
STATE_FILE = os.path.join(STATE_DIR, 'state.json')

HOME_DIR = os.path.expanduser('~')
HAR_CAPTURE_DIR = os.path.join(HOME_DIR, '.config', 'hifi-media-player', 'logs', 'har-captures')
PERF_CAPTURE_DIR = os.path.join(HOME_DIR, '.config', 'hifi-media-player', 'logs', 'perf-captures')
CAPTURE_SCHEDULE_FILE = os.path.join(HOME_DIR, '.config', 'hifi-media-player', 'beta-capture-schedule.json')
UI_VERSION_FILE = '/opt/hifi-media-player/UI_VERSION'

DEFAULT_INTERVAL_SEC = 600  # only used before the server has ever been reached
HTTP_TIMEOUT_SEC = 30

_HAR_RE = re.compile(r'^capture-[0-9TZ-]+\.har$')
_PERF_RE = re.compile(r'^perf-[0-9TZ-]+\.jsonl$')

# Set (not time.sleep()) so shutdown is prompt: a signal handler that doesn't
# raise just lets time.sleep() silently resume for its full remaining
# duration (PEP 475 auto-retries interrupted syscalls) -- with the default
# 600s interval that meant systemd waiting the better part of 10 minutes (or
# hitting its own stop-timeout and SIGKILLing) on every shutdown/reboot.
# Event.wait() re-checks the flag before re-blocking, so .set() from the
# handler wakes it immediately.
_stop_event = threading.Event()


def _log(msg):
    print(f'{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())} [beta-agent] {msg}', flush=True)


def _handle_term(signum, _frame):
    _stop_event.set()


signal.signal(signal.SIGTERM, _handle_term)
signal.signal(signal.SIGINT, _handle_term)


# ── state persistence ────────────────────────────────────────────────────
def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = STATE_FILE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(state, f)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        _log(f'failed to persist state: {e}')


# ── HTTP helper (stdlib only, no third-party deps) ──────────────────────
def http_request(method, path, token=None, json_body=None, raw_body=None,
                  content_type='application/json'):
    url = SERVER_URL.rstrip('/') + path
    headers = {'User-Agent': 'hifi-beta-agent'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    elif raw_body is not None:
        data = raw_body
        headers['Content-Type'] = content_type
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
            body = resp.read()
            parsed = json.loads(body) if body else None
            return resp.status, parsed
    except urllib.error.HTTPError as e:
        _log(f'{method} {path} -> HTTP {e.code}')
        return e.code, None
    except Exception as e:
        _log(f'{method} {path} failed: {e}')
        return None, None


def device_request(state, method, path, **kwargs):
    """http_request using state's device_token, with one added behaviour: a
    401 means the server-side token was revoked (e.g. the dashboard's
    "Revoca token" button) -- it will never start working again on its own,
    so keep retrying it is pointless. Clearing it here makes the *next*
    cycle's ensure_registered() see no token and register fresh, instead of
    the agent being stuck presenting a dead token forever."""
    status, body = http_request(method, path, token=state.get('device_token'), **kwargs)
    if status == 401 and state.get('device_token'):
        _log('device token rejected (401), likely revoked -- clearing so the agent re-registers next cycle')
        state.pop('device_token', None)
        save_state(state)
    return status, body


# ── device identity ──────────────────────────────────────────────────────
def machine_id():
    try:
        with open('/etc/machine-id') as f:
            return f.read().strip()
    except Exception:
        return socket.gethostname()


def default_label():
    mid = machine_id()
    suffix = mid[-6:] if mid else socket.gethostname()
    return f'{socket.gethostname()}-{suffix}'


def ensure_registered(state):
    if state.get('device_token'):
        return True
    device_id = machine_id()
    label = state.get('label') or default_label()
    status, body = http_request('POST', '/api/v1/register', token=BOOTSTRAP_SECRET,
                                 json_body={'device_id': device_id, 'label': label})
    if status == 200 and body and body.get('token'):
        state['device_token'] = body['token']
        state['device_id'] = device_id
        state['label'] = label
        save_state(state)
        _log(f'registered as {device_id}')
        return True
    _log('registration failed, will retry next cycle')
    return False


# ── remote config: agent cadence + capture scheduling ────────────────────
def write_capture_schedule_file(schedule):
    try:
        try:
            with open(CAPTURE_SCHEDULE_FILE) as f:
                existing = json.load(f)
            if (existing.get('enabled') == schedule.get('enabled')
                    and existing.get('intervalSec') == schedule.get('intervalSec')
                    and existing.get('durationSec') == schedule.get('durationSec')):
                return  # unchanged -- don't bump mtime for no reason
        except Exception:
            pass
        payload = dict(schedule)
        payload['updatedAt'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        os.makedirs(os.path.dirname(CAPTURE_SCHEDULE_FILE), exist_ok=True)
        tmp = CAPTURE_SCHEDULE_FILE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(payload, f)
        os.replace(tmp, CAPTURE_SCHEDULE_FILE)
    except Exception as e:
        _log(f'failed to write capture schedule file: {e}')


def fetch_config(state):
    status, body = device_request(state, 'GET', '/api/v1/config')
    if status != 200 or not body:
        return
    interval = body.get('agentIntervalSec')
    if isinstance(interval, (int, float)) and interval > 0:
        state['agent_interval_sec'] = int(interval)
        save_state(state)
    write_capture_schedule_file({
        'enabled': bool(body.get('captureEnabled')),
        'intervalSec': body.get('captureIntervalSec'),
        'durationSec': body.get('captureDurationSec'),
    })


# ── system snapshot ──────────────────────────────────────────────────────
def cpu_model():
    try:
        with open('/proc/cpuinfo') as f:
            for line in f:
                if line.lower().startswith('model name'):
                    return line.split(':', 1)[1].strip()
    except Exception:
        pass
    return None


def gpu_model():
    try:
        out = subprocess.run(['lspci'], capture_output=True, text=True, timeout=5).stdout
        for line in out.splitlines():
            if 'VGA compatible controller' in line or '3D controller' in line:
                return line.split(':', 2)[-1].strip()
    except Exception:
        pass
    return None


def cpu_temp_c():
    best = None
    try:
        import glob
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


def gpu_busy_pct():
    """Intel iGPU busy % via intel_gpu_top, same approach as api_server.py's
    _gpu_busy_pct() -- not shipped on the image by default (see
    intel-gpu-tools), so this is a no-op (None) wherever it's missing."""
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


def network_info():
    if psutil is None:
        return 'unknown', None
    try:
        conn_type, local_ip = 'unknown', None
        stats = psutil.net_if_stats()
        for name, addrs in psutil.net_if_addrs().items():
            if name == 'lo' or name not in stats or not stats[name].isup:
                continue
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    local_ip = addr.address
                    if name.startswith('eth') or name.startswith('en'):
                        conn_type = 'wired'
                    elif name.startswith('wlan') or name.startswith('wl'):
                        conn_type = 'wireless'
                    elif name.startswith('usb'):
                        conn_type = 'usb'
                    break
            if local_ip:
                break
        return conn_type, local_ip
    except Exception:
        return 'unknown', None


def read_os_version():
    try:
        with open(UI_VERSION_FILE) as f:
            return f.read().strip() or None
    except Exception:
        return None


def system_snapshot():
    vm = psutil.virtual_memory() if psutil else None
    du = shutil.disk_usage('/')
    cpu_pct = psutil.cpu_percent(interval=1.0) if psutil else None
    conn_type, local_ip = network_info()
    return {
        'hostname': socket.gethostname(),
        'os_version': read_os_version(),
        'cpu_model': cpu_model(),
        'cpu_cores': os.cpu_count(),
        'gpu_model': gpu_model(),
        'ram_total_mb': round(vm.total / 1024 / 1024) if vm else None,
        'ram_used_mb': round(vm.used / 1024 / 1024) if vm else None,
        'disk_total_gb': round(du.total / 1024 ** 3, 1) if du.total else None,
        'disk_used_gb': round(du.used / 1024 ** 3, 1) if du.total else None,
        'cpu_percent': cpu_pct,
        'disk_percent': round(du.used / du.total * 100, 1) if du.total else None,
        'temp_c': cpu_temp_c(),
        'gpu_percent': gpu_busy_pct(),
        'connection_type': conn_type,
        'local_ip': local_ip,
    }


def send_snapshot(state):
    status, _ = device_request(state, 'POST', '/api/v1/snapshot', json_body=system_snapshot())
    if status != 200:
        _log(f'snapshot upload failed (status={status})')


# ── HAR captures: whole file, uploaded once it looks finished ───────────
# Deleted from disk right after a successful upload -- the server is now the
# copy of record, and beta devices are disk-constrained. har_uploaded still
# exists as a fallback: if the delete itself fails (e.g. permissions), we
# remember the filename so we don't re-upload it forever.
def upload_har_captures(state):
    uploaded = set(state.setdefault('har_uploaded', []))
    try:
        names = os.listdir(HAR_CAPTURE_DIR)
    except FileNotFoundError:
        return
    except Exception as e:
        _log(f'cannot list {HAR_CAPTURE_DIR}: {e}')
        return

    for filename in sorted(names):
        if filename in uploaded or not _HAR_RE.match(filename):
            continue
        path = os.path.join(HAR_CAPTURE_DIR, filename)
        try:
            if time.time() - os.path.getmtime(path) < 30:
                continue  # still might be mid-write, try again next cycle
            with open(path, 'rb') as f:
                data = f.read()
        except Exception as e:
            _log(f'cannot read {filename}: {e}')
            continue

        status, _ = device_request(
            state, 'POST', f'/api/v1/har?filename={urllib.parse.quote(filename)}',
            raw_body=data, content_type='application/json')
        if status == 200:
            try:
                os.remove(path)
            except Exception as e:
                _log(f'uploaded {filename} but failed to remove it from disk: {e}')
                uploaded.add(filename)
                state['har_uploaded'] = sorted(uploaded)
                save_state(state)
        else:
            _log(f'HAR upload failed for {filename} (status={status}), will retry next cycle')


# ── perf captures: append-only, shipped incrementally by byte offset ────
# Once a file has no more unshipped bytes and hasn't grown in a while (the
# capture has clearly ended, not just paused between writes), it's deleted
# from disk the same way HAR captures are -- nothing left on the device that
# hasn't already reached the server.
_PERF_QUIET_SEC = 30


def upload_perf_captures(state):
    offsets = state.setdefault('perf_offsets', {})
    try:
        names = os.listdir(PERF_CAPTURE_DIR)
    except FileNotFoundError:
        return
    except Exception as e:
        _log(f'cannot list {PERF_CAPTURE_DIR}: {e}')
        return

    for filename in sorted(names):
        if not _PERF_RE.match(filename):
            continue
        path = os.path.join(PERF_CAPTURE_DIR, filename)
        offset = offsets.get(filename, 0)
        try:
            stat = os.stat(path)
            size = stat.st_size
        except Exception as e:
            _log(f'cannot stat {filename}: {e}')
            continue

        if size > offset:
            try:
                with open(path, 'rb') as f:
                    f.seek(offset)
                    chunk = f.read()
            except Exception as e:
                _log(f'cannot read {filename}: {e}')
                continue

            last_nl = chunk.rfind(b'\n')
            if last_nl == -1:
                continue  # no complete line yet -- wait for the next cycle
            complete = chunk[:last_nl + 1]

            status, _ = device_request(
                state, 'POST', f'/api/v1/perf?filename={urllib.parse.quote(filename)}',
                raw_body=complete, content_type='application/x-ndjson')
            if status != 200:
                _log(f'perf upload failed for {filename} (status={status}), will retry next cycle')
                continue
            offset += len(complete)
            offsets[filename] = offset
            state['perf_offsets'] = offsets
            save_state(state)

        if offset >= size and time.time() - stat.st_mtime > _PERF_QUIET_SEC:
            try:
                os.remove(path)
                offsets.pop(filename, None)
                state['perf_offsets'] = offsets
                save_state(state)
            except Exception as e:
                _log(f'uploaded {filename} but failed to remove it from disk: {e}')


# ── main loop ─────────────────────────────────────────────────────────────
def run_cycle(state):
    if not ensure_registered(state):
        return
    fetch_config(state)
    send_snapshot(state)
    upload_har_captures(state)
    upload_perf_captures(state)


def main():
    once = '--once' in sys.argv
    state = load_state()
    state.setdefault('agent_interval_sec', DEFAULT_INTERVAL_SEC)

    while not _stop_event.is_set():
        try:
            run_cycle(state)
        except Exception:
            _log('cycle failed:\n' + traceback.format_exc())
        if once:
            break
        _stop_event.wait(max(30, state.get('agent_interval_sec', DEFAULT_INTERVAL_SEC)))


if __name__ == '__main__':
    main()
