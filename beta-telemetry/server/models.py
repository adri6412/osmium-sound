"""SQLite schema + small data-access helpers for the beta-testing telemetry
server. One connection per request (Flask's g), WAL mode so the ingestion
endpoints and the dashboard reads don't block each other.
"""
import os
import sqlite3
import time

DB_PATH = os.environ.get('BETA_DB_PATH', '/data/beta.db')

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id TEXT UNIQUE NOT NULL,
    label TEXT NOT NULL,
    label_is_custom INTEGER NOT NULL DEFAULT 0,
    token_hash TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT
);

-- Single row (id=1): the dashboard's admin password, changeable from the
-- Account page (app.py's /account) without redeploying. Falls back to the
-- BETA_ADMIN_PASSWORD_HASH env var (see app.py's get_active_password_hash())
-- until the first change -- that env var stays useful as the value
-- reset_password.py restores with --clear, or as a fresh baseline if the
-- volume is ever wiped.
CREATE TABLE IF NOT EXISTS admin_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    password_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Single row (id=1): fleet-wide config, entirely dashboard-editable. Nothing
-- about cadence is ever hardcoded in the agent or in main.js -- this table is
-- the one source of truth (see GET /api/v1/config in app.py).
CREATE TABLE IF NOT EXISTS fleet_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    agent_interval_sec INTEGER NOT NULL DEFAULT 600,
    capture_enabled INTEGER NOT NULL DEFAULT 0,
    capture_interval_sec INTEGER NOT NULL DEFAULT 900,
    capture_duration_sec INTEGER NOT NULL DEFAULT 120,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    hostname TEXT,
    os_version TEXT,
    debian_version TEXT,
    cpu_model TEXT,
    cpu_cores INTEGER,
    gpu_model TEXT,
    ram_total_mb INTEGER,
    ram_used_mb INTEGER,
    disk_total_gb REAL,
    disk_used_gb REAL,
    cpu_percent REAL,
    disk_percent REAL,
    temp_c REAL,
    gpu_percent REAL,
    connection_type TEXT,
    local_ip TEXT
);
CREATE INDEX IF NOT EXISTS idx_snapshots_device_ts ON snapshots(device_id, ts);

CREATE TABLE IF NOT EXISTS har_captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    size_bytes INTEGER,
    requests_count INTEGER,
    errors_count INTEGER,
    by_status_json TEXT,
    top_domains_json TEXT,
    storage_path TEXT,
    UNIQUE(device_id, filename)
);

CREATE TABLE IF NOT EXISTS perf_captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_updated_at TEXT NOT NULL,
    sample_count INTEGER NOT NULL DEFAULT 0,
    cpu_avg REAL,
    cpu_max REAL,
    ram_avg_kb REAL,
    duration_sec REAL,
    by_tab_json TEXT,
    storage_path TEXT,
    UNIQUE(device_id, filename)
);
"""


def now_iso():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA journal_mode = WAL')
    return conn


def _ensure_column(conn, table, column, coltype):
    """CREATE TABLE IF NOT EXISTS is a no-op on a table that already exists,
    so a column added to SCHEMA after the first deploy never reaches an
    already-running server's DB file on its own -- this adds it once,
    idempotently, on every startup."""
    cols = {row['name'] for row in conn.execute(f'PRAGMA table_info({table})')}
    if column not in cols:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {coltype}')


def init_db():
    os.makedirs(os.path.dirname(DB_PATH) or '.', exist_ok=True)
    conn = get_db()
    try:
        conn.executescript(SCHEMA)
        _ensure_column(conn, 'snapshots', 'gpu_percent', 'REAL')
        _ensure_column(conn, 'snapshots', 'debian_version', 'TEXT')
        _ensure_column(conn, 'devices', 'label_is_custom', 'INTEGER NOT NULL DEFAULT 0')
        row = conn.execute('SELECT COUNT(*) c FROM fleet_config').fetchone()
        if row['c'] == 0:
            conn.execute(
                'INSERT INTO fleet_config '
                '(id, agent_interval_sec, capture_enabled, capture_interval_sec, capture_duration_sec, updated_at) '
                'VALUES (1, 600, 0, 900, 120, ?)', (now_iso(),))
        conn.commit()
    finally:
        conn.close()
