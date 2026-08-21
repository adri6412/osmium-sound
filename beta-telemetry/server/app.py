"""HiFi Player — private beta-testing telemetry server.

Receives system snapshots + HAR/perf captures from hifi-beta-agent.py
(running on each beta-tester appliance), stores them in SQLite, and serves a
small dashboard to watch fleet health during the beta and to change the
fleet-wide capture schedule in real time (see fleet_config in models.py --
that table is the only source of truth for cadence, nothing is hardcoded on
the device side).

Runs behind a reverse proxy (Apache, managed by the operator) that terminates
TLS -- this process only ever speaks plain HTTP on BETA_LISTEN_PORT.
"""
import hashlib
import hmac
import json
import os
import secrets
import shutil
import sqlite3
import time
from functools import wraps

from flask import Flask, g, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import har_analysis
import perf_analysis
from models import get_db, init_db, now_iso

BOOTSTRAP_SECRET = os.environ.get('BETA_BOOTSTRAP_SECRET', '')
ADMIN_PASSWORD_HASH = os.environ.get('BETA_ADMIN_PASSWORD_HASH', '')  # generate_password_hash('...')
CAPTURES_DIR = os.environ.get('BETA_CAPTURES_DIR', '/data/captures')
SECRET_KEY_FILE = os.environ.get('BETA_SECRET_KEY_FILE', '/data/flask-secret.key')

app = Flask(__name__)


def _ensure_secret_key():
    try:
        with open(SECRET_KEY_FILE, 'rb') as f:
            data = f.read().strip()
            if data:
                return data
    except Exception:
        pass
    key = secrets.token_bytes(32)
    try:
        os.makedirs(os.path.dirname(SECRET_KEY_FILE) or '.', exist_ok=True)
        tmp = SECRET_KEY_FILE + '.tmp'
        with open(tmp, 'wb') as f:
            f.write(key)
        os.chmod(tmp, 0o600)
        os.replace(tmp, SECRET_KEY_FILE)
    except Exception:
        pass
    return key


app.secret_key = _ensure_secret_key()


@app.template_filter('fromjson')
def _fromjson(value):
    try:
        return json.loads(value) if value else {}
    except Exception:
        return {}

if not BOOTSTRAP_SECRET:
    raise RuntimeError('BETA_BOOTSTRAP_SECRET must be set (shared secret baked into hifi-beta-agent.py)')
if not ADMIN_PASSWORD_HASH:
    raise RuntimeError('BETA_ADMIN_PASSWORD_HASH must be set (generate_password_hash("...") of the dashboard password)')

init_db()


# ── auth helpers ──────────────────────────────────────────────────────────
def _bearer_token():
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    return auth[len('Bearer '):].strip()


def require_bootstrap(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = _bearer_token() or ''
        if not hmac.compare_digest(token, BOOTSTRAP_SECRET):
            return jsonify({'error': 'unauthorized'}), 401
        return fn(*args, **kwargs)
    return wrapper


def require_device(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = _bearer_token()
        if not token:
            return jsonify({'error': 'unauthorized'}), 401
        token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
        db = get_db()
        row = db.execute('SELECT * FROM devices WHERE token_hash = ?', (token_hash,)).fetchone()
        if not row:
            db.close()
            return jsonify({'error': 'unauthorized'}), 401
        db.execute('UPDATE devices SET last_seen_at = ? WHERE id = ?', (now_iso(), row['id']))
        db.commit()
        g.device = row
        g.db = db
        try:
            return fn(*args, **kwargs)
        finally:
            g.db.close()
    return wrapper


def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('admin'):
            return redirect(url_for('login', next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def _device_capture_dir(device_id):
    path = os.path.join(CAPTURES_DIR, str(device_id))
    os.makedirs(path, exist_ok=True)
    return path


MAX_CAPTURES_PER_DEVICE = 10


def _prune_old_captures(db, table, order_col, device_id):
    """Keep only the MAX_CAPTURES_PER_DEVICE most recent rows of `table` for
    this device, deleting the rest (DB row + the file on disk it points at).
    Runs on every upload so storage stays bounded without a separate cron job
    -- each appliance uploads then deletes its local copy (see
    hifi-beta-agent.py), so the server is the only place these accumulate."""
    rows = db.execute(
        f'SELECT id, storage_path FROM {table} WHERE device_id = ? ORDER BY {order_col} DESC',
        (device_id,)).fetchall()
    for row in rows[MAX_CAPTURES_PER_DEVICE:]:
        if row['storage_path']:
            try:
                os.remove(row['storage_path'])
            except OSError:
                pass
        db.execute(f'DELETE FROM {table} WHERE id = ?', (row['id'],))


def _delete_device(db, device_id):
    """Remove a device and everything hanging off it: the snapshots/HAR/perf
    rows go with it via ON DELETE CASCADE (foreign_keys is ON, see get_db()),
    and its capture directory is removed here since nothing else on disk
    tracks it. Used to clear out appliances that registered once and were
    then uninstalled -- they'd otherwise sit in the list forever as 'offline'.
    """
    row = db.execute('SELECT id FROM devices WHERE id = ?', (device_id,)).fetchone()
    if not row:
        return False
    db.execute('DELETE FROM devices WHERE id = ?', (device_id,))
    try:
        shutil.rmtree(os.path.join(CAPTURES_DIR, str(device_id)))
    except OSError:
        pass
    return True


# ── admin password: DB override, falling back to the env var ────────────
# Lets the password be changed from /account without redeploying, while
# BETA_ADMIN_PASSWORD_HASH stays as the value reset_password.py --clear
# restores when the admin is locked out (see that script's docstring).
def get_active_password_hash():
    db = get_db()
    try:
        row = db.execute('SELECT password_hash FROM admin_config WHERE id = 1').fetchone()
    finally:
        db.close()
    return row['password_hash'] if row else ADMIN_PASSWORD_HASH


def set_active_password_hash(new_hash):
    db = get_db()
    try:
        db.execute(
            'INSERT INTO admin_config (id, password_hash, updated_at) VALUES (1, ?, ?) '
            'ON CONFLICT(id) DO UPDATE SET password_hash = excluded.password_hash, '
            'updated_at = excluded.updated_at',
            (new_hash, now_iso()))
        db.commit()
    finally:
        db.close()


# ── ingestion API ─────────────────────────────────────────────────────────
@app.route('/api/v1/register', methods=['POST'])
@require_bootstrap
def api_register():
    body = request.get_json(silent=True) or {}
    machine_id = (body.get('device_id') or '').strip()
    label = (body.get('label') or '').strip() or machine_id
    if not machine_id:
        return jsonify({'error': 'device_id required'}), 400

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()

    db = get_db()
    try:
        existing = db.execute('SELECT id, label_is_custom FROM devices WHERE machine_id = ?', (machine_id,)).fetchone()
        if existing:
            if existing['label_is_custom']:
                # Admin gave this device its own name -- don't clobber it with
                # whatever hostname-derived label the agent computed locally
                # just because it happened to re-register (e.g. after a
                # revoked token).
                db.execute('UPDATE devices SET token_hash = ?, last_seen_at = ? WHERE id = ?',
                           (token_hash, now_iso(), existing['id']))
            else:
                db.execute('UPDATE devices SET token_hash = ?, label = ?, last_seen_at = ? WHERE id = ?',
                           (token_hash, label, now_iso(), existing['id']))
        else:
            db.execute(
                'INSERT INTO devices (machine_id, label, token_hash, created_at, last_seen_at) '
                'VALUES (?, ?, ?, ?, ?)', (machine_id, label, token_hash, now_iso(), now_iso()))
        db.commit()
    finally:
        db.close()
    return jsonify({'token': token})


@app.route('/api/v1/config', methods=['GET'])
@require_device
def api_config():
    row = g.db.execute('SELECT * FROM fleet_config WHERE id = 1').fetchone()
    return jsonify({
        'agentIntervalSec': row['agent_interval_sec'],
        'captureEnabled': bool(row['capture_enabled']),
        'captureIntervalSec': row['capture_interval_sec'],
        'captureDurationSec': row['capture_duration_sec'],
    })


def _client_ts_or_now(value):
    """hifi-beta-agent.py stamps each snapshot with its own capture time and
    replays queued ones after a cloud outage -- honor that so a snapshot sent
    hours late still lands at its real capture time instead of the upload
    time (device_detail.html's chart is ordered/labeled by this column)."""
    if isinstance(value, str):
        try:
            time.strptime(value, '%Y-%m-%dT%H:%M:%SZ')
            return value
        except ValueError:
            pass
    return now_iso()


@app.route('/api/v1/snapshot', methods=['POST'])
@require_device
def api_snapshot():
    body = request.get_json(silent=True) or {}
    g.db.execute(
        'INSERT INTO snapshots (device_id, ts, hostname, os_version, debian_version, cpu_model, cpu_cores, gpu_model, '
        'ram_total_mb, ram_used_mb, disk_total_gb, disk_used_gb, cpu_percent, disk_percent, temp_c, '
        'gpu_percent, connection_type, local_ip) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (g.device['id'], _client_ts_or_now(body.get('ts')), body.get('hostname'), body.get('os_version'),
         body.get('debian_version'), body.get('cpu_model'),
         body.get('cpu_cores'), body.get('gpu_model'), body.get('ram_total_mb'), body.get('ram_used_mb'),
         body.get('disk_total_gb'), body.get('disk_used_gb'), body.get('cpu_percent'),
         body.get('disk_percent'), body.get('temp_c'), body.get('gpu_percent'),
         body.get('connection_type'), body.get('local_ip')))
    # Keep the display label following the appliance's actual hostname (same
    # "<hostname>-<machine_id suffix>" shape the agent computes for its own
    # initial registration) as long as nobody has given it a custom name via
    # the dashboard -- otherwise a hostname change (e.g. renaming the box)
    # never shows up here until/unless the device token gets revoked and it
    # happens to re-register.
    hostname = (body.get('hostname') or '').strip()
    if hostname and not g.device['label_is_custom']:
        mid = g.device['machine_id'] or ''
        new_label = f'{hostname}-{mid[-6:]}' if mid else hostname
        if new_label != g.device['label']:
            g.db.execute('UPDATE devices SET label = ? WHERE id = ?', (new_label, g.device['id']))
    g.db.commit()
    return jsonify({'ok': True})


@app.route('/api/v1/har', methods=['POST'])
@require_device
def api_har():
    filename = (request.args.get('filename') or '').strip()
    if not filename or '/' in filename or '\\' in filename:
        return jsonify({'error': 'invalid filename'}), 400
    raw = request.get_data()
    summary = har_analysis.analyze_har(raw) or {}

    storage_path = os.path.join(_device_capture_dir(g.device['id']), filename)
    with open(storage_path, 'wb') as f:
        f.write(raw)

    g.db.execute(
        'INSERT INTO har_captures (device_id, filename, uploaded_at, size_bytes, requests_count, '
        'errors_count, by_status_json, top_domains_json, storage_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) '
        'ON CONFLICT(device_id, filename) DO UPDATE SET uploaded_at = excluded.uploaded_at, '
        'size_bytes = excluded.size_bytes, requests_count = excluded.requests_count, '
        'errors_count = excluded.errors_count, by_status_json = excluded.by_status_json, '
        'top_domains_json = excluded.top_domains_json',
        (g.device['id'], filename, now_iso(), len(raw), summary.get('requests_count'),
         summary.get('errors_count'), json.dumps(summary.get('by_status') or {}),
         json.dumps(summary.get('top_domains') or {}), storage_path))
    _prune_old_captures(g.db, 'har_captures', 'uploaded_at', g.device['id'])
    g.db.commit()
    return jsonify({'ok': True})


@app.route('/api/v1/perf', methods=['POST'])
@require_device
def api_perf():
    filename = (request.args.get('filename') or '').strip()
    if not filename or '/' in filename or '\\' in filename:
        return jsonify({'error': 'invalid filename'}), 400
    raw = request.get_data()

    existing_row = g.db.execute(
        'SELECT * FROM perf_captures WHERE device_id = ? AND filename = ?',
        (g.device['id'], filename)).fetchone()
    existing = dict(existing_row) if existing_row else None
    rollup = perf_analysis.fold_batch(existing, raw)
    if rollup is None:
        return jsonify({'ok': True, 'skipped': 'no complete samples in batch'})

    storage_path = os.path.join(_device_capture_dir(g.device['id']), filename)
    with open(storage_path, 'ab') as f:
        f.write(raw)

    if existing:
        g.db.execute(
            'UPDATE perf_captures SET last_updated_at = ?, sample_count = ?, cpu_avg = ?, cpu_max = ?, '
            'ram_avg_kb = ?, duration_sec = ?, by_tab_json = ? WHERE id = ?',
            (rollup['last_updated_at'], rollup['sample_count'], rollup['cpu_avg'], rollup['cpu_max'],
             rollup['ram_avg_kb'], rollup['duration_sec'], rollup['by_tab_json'], existing['id']))
    else:
        g.db.execute(
            'INSERT INTO perf_captures (device_id, filename, first_seen_at, last_updated_at, sample_count, '
            'cpu_avg, cpu_max, ram_avg_kb, duration_sec, by_tab_json, storage_path) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (g.device['id'], filename, rollup['first_seen_at'], rollup['last_updated_at'],
             rollup['sample_count'], rollup['cpu_avg'], rollup['cpu_max'], rollup['ram_avg_kb'],
             rollup['duration_sec'], rollup['by_tab_json'], storage_path))
    _prune_old_captures(g.db, 'perf_captures', 'last_updated_at', g.device['id'])
    g.db.commit()
    return jsonify({'ok': True})


# ── dashboard: auth ───────────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password', '')
        if check_password_hash(get_active_password_hash(), password):
            session['admin'] = True
            return redirect(request.args.get('next') or url_for('devices'))
        return render_template('login.html', error='Password errata')
    return render_template('login.html', error=None)


@app.route('/logout')
def logout():
    session.pop('admin', None)
    return redirect(url_for('login'))


# ── dashboard: devices ────────────────────────────────────────────────────
@app.route('/')
@require_admin
def devices():
    db = get_db()
    rows = db.execute('''
        SELECT d.*, s.hostname, s.os_version, s.debian_version, s.cpu_model, s.gpu_model, s.ram_total_mb, s.disk_total_gb,
               s.cpu_percent, s.disk_percent, s.connection_type
        FROM devices d
        LEFT JOIN snapshots s ON s.id = (
            SELECT id FROM snapshots WHERE device_id = d.id ORDER BY ts DESC LIMIT 1
        )
        ORDER BY d.last_seen_at DESC
    ''').fetchall()
    db.close()
    # ISO8601 'Z' timestamps sort lexicographically, so the template can just
    # string-compare against this cutoff instead of parsing dates itself.
    online_cutoff = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - 20 * 60))
    return render_template('devices.html', devices=rows, online_cutoff=online_cutoff)


@app.route('/devices/<int:device_id>')
@require_admin
def device_detail(device_id):
    db = get_db()
    device = db.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
    if not device:
        db.close()
        return 'Device not found', 404
    snapshots = [dict(r) for r in db.execute(
        'SELECT * FROM snapshots WHERE device_id = ? ORDER BY ts DESC LIMIT 200', (device_id,)).fetchall()]
    har_captures = db.execute(
        'SELECT * FROM har_captures WHERE device_id = ? ORDER BY uploaded_at DESC', (device_id,)).fetchall()
    perf_captures = db.execute(
        'SELECT * FROM perf_captures WHERE device_id = ? ORDER BY last_updated_at DESC', (device_id,)).fetchall()
    db.close()
    online_cutoff = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - 20 * 60))
    return render_template('device_detail.html', device=device,
                            snapshots=list(reversed(snapshots)),
                            har_captures=har_captures, perf_captures=perf_captures,
                            online_cutoff=online_cutoff)


@app.route('/devices/<int:device_id>/label', methods=['POST'])
@require_admin
def device_rename(device_id):
    label = (request.form.get('label') or '').strip()
    if label:
        db = get_db()
        # label_is_custom=1 opts this device out of api_snapshot's automatic
        # hostname-follow -- an explicit admin rename should stick even if
        # the appliance's hostname later changes again.
        db.execute('UPDATE devices SET label = ?, label_is_custom = 1 WHERE id = ?', (label, device_id))
        db.commit()
        db.close()
    return redirect(url_for('device_detail', device_id=device_id))


@app.route('/devices/<int:device_id>/revoke', methods=['POST'])
@require_admin
def device_revoke(device_id):
    # Invalidate the current token (random hash nothing will ever match) --
    # the agent re-registers with the bootstrap secret on its next cycle and
    # gets a fresh one automatically.
    db = get_db()
    db.execute('UPDATE devices SET token_hash = ? WHERE id = ?',
               (hashlib.sha256(secrets.token_bytes(32)).hexdigest(), device_id))
    db.commit()
    db.close()
    return redirect(url_for('device_detail', device_id=device_id))


@app.route('/devices/<int:device_id>/delete', methods=['POST'])
@require_admin
def device_delete(device_id):
    db = get_db()
    try:
        _delete_device(db, device_id)
        db.commit()
    finally:
        db.close()
    return redirect(url_for('devices'))


# Bulk version of the above: one button to clear out every appliance that
# hasn't checked in for `days` days (never-seen ones included). An agent that
# is merely switched off for a while re-appears on its own next check-in --
# only the DB history is lost -- so the cutoff can be reasonably aggressive.
@app.route('/devices/purge', methods=['POST'])
@require_admin
def devices_purge():
    try:
        days = max(1, int(request.form.get('days', 30)))
    except (TypeError, ValueError):
        days = 30
    cutoff = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - days * 86400))
    db = get_db()
    try:
        rows = db.execute(
            'SELECT id FROM devices WHERE last_seen_at IS NULL OR last_seen_at < ?', (cutoff,)).fetchall()
        for row in rows:
            _delete_device(db, row['id'])
        db.commit()
    finally:
        db.close()
    return redirect(url_for('devices', purged=len(rows), days=days))


@app.route('/devices/<int:device_id>/har/<path:filename>')
@require_admin
def download_har(device_id, filename):
    db = get_db()
    row = db.execute('SELECT storage_path FROM har_captures WHERE device_id = ? AND filename = ?',
                      (device_id, filename)).fetchone()
    db.close()
    if not row or not os.path.isfile(row['storage_path']):
        return 'Not found', 404
    return send_file(row['storage_path'], as_attachment=True, download_name=filename)


@app.route('/devices/<int:device_id>/perf/<path:filename>')
@require_admin
def download_perf(device_id, filename):
    db = get_db()
    row = db.execute('SELECT storage_path FROM perf_captures WHERE device_id = ? AND filename = ?',
                      (device_id, filename)).fetchone()
    db.close()
    if not row or not os.path.isfile(row['storage_path']):
        return 'Not found', 404
    return send_file(row['storage_path'], as_attachment=True, download_name=filename)


# ── dashboard: account ────────────────────────────────────────────────────
@app.route('/account', methods=['GET', 'POST'])
@require_admin
def account():
    error = None
    saved = False
    if request.method == 'POST':
        current = request.form.get('current_password', '')
        new = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')
        if not check_password_hash(get_active_password_hash(), current):
            error = 'Password attuale errata.'
        elif len(new) < 8:
            error = 'La nuova password deve avere almeno 8 caratteri.'
        elif new != confirm:
            error = 'Le due password non coincidono.'
        else:
            set_active_password_hash(generate_password_hash(new))
            saved = True
    return render_template('account.html', error=error, saved=saved)


# ── dashboard: fleet config ──────────────────────────────────────────────
@app.route('/config', methods=['GET', 'POST'])
@require_admin
def fleet_config():
    db = get_db()
    if request.method == 'POST':
        def _int(name, default):
            try:
                return max(1, int(request.form.get(name, default)))
            except (TypeError, ValueError):
                return default

        agent_interval_sec = _int('agent_interval_sec', 600)
        capture_enabled = 1 if request.form.get('capture_enabled') == 'on' else 0
        capture_interval_sec = _int('capture_interval_sec', 900)
        capture_duration_sec = _int('capture_duration_sec', 120)
        db.execute(
            'UPDATE fleet_config SET agent_interval_sec = ?, capture_enabled = ?, capture_interval_sec = ?, '
            'capture_duration_sec = ?, updated_at = ? WHERE id = 1',
            (agent_interval_sec, capture_enabled, capture_interval_sec, capture_duration_sec, now_iso()))
        db.commit()

    row = db.execute('SELECT * FROM fleet_config WHERE id = 1').fetchone()
    db.close()
    return render_template('fleet_config.html', config=row)


if __name__ == '__main__':
    port = int(os.environ.get('BETA_LISTEN_PORT', '8090'))
    app.run(host='127.0.0.1', port=port)
