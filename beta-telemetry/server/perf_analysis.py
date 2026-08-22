"""Incremental rollup for perf-capture .jsonl batches (see main.js's
samplePerfCapture — each line is {ts, appMetrics[], domMetrics, uiState}).
Perf captures are shipped incrementally (the agent ships new lines as they're
appended), so this folds a new batch into the previous rollup rather than
re-reading the whole file every time.
"""
import json
from datetime import datetime


def _parse_ts(s):
    try:
        return datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    except Exception:
        return None


def _line_totals(sample):
    app_metrics = sample.get('appMetrics') or []
    if isinstance(app_metrics, dict):  # error shape from perfMetricsFromAppMetrics()
        return 0.0, 0.0
    cpu = sum((m.get('cpuPct') or 0) for m in app_metrics if isinstance(m, dict))
    ram_kb = sum((m.get('workingSetKb') or 0) for m in app_metrics if isinstance(m, dict))
    return cpu, ram_kb


def fold_batch(existing, raw_ndjson_bytes):
    """existing: dict with sample_count/cpu_avg/cpu_max/ram_avg_kb/duration_sec/
    by_tab_json/first_seen_at/last_updated_at (or None for a brand-new capture).
    Returns the updated dict, or None if the batch had no parseable samples."""
    count = existing['sample_count'] if existing else 0
    cpu_avg = existing['cpu_avg'] if existing else 0.0
    cpu_max = existing['cpu_max'] if existing else 0.0
    ram_avg_kb = existing['ram_avg_kb'] if existing else 0.0
    by_tab = json.loads(existing['by_tab_json']) if (existing and existing.get('by_tab_json')) else {}
    first_seen = existing['first_seen_at'] if existing else None
    last_updated = existing['last_updated_at'] if existing else None

    new_lines = 0
    for line in raw_ndjson_bytes.decode('utf-8', errors='replace').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            sample = json.loads(line)
        except Exception:
            continue
        cpu, ram_kb = _line_totals(sample)
        count += 1
        new_lines += 1
        cpu_avg += (cpu - cpu_avg) / count
        ram_avg_kb += (ram_kb - ram_avg_kb) / count
        cpu_max = max(cpu_max, cpu)

        ui_state = sample.get('uiState') or {}
        tab = ui_state.get('activeTab') if isinstance(ui_state, dict) else None
        if tab:
            by_tab[tab] = by_tab.get(tab, 0) + 1

        ts = sample.get('ts')
        if ts:
            if first_seen is None:
                first_seen = ts
            last_updated = ts

    if new_lines == 0:
        return None

    duration_sec = None
    dt_first, dt_last = _parse_ts(first_seen), _parse_ts(last_updated)
    if dt_first and dt_last:
        duration_sec = max(0.0, (dt_last - dt_first).total_seconds())

    return {
        'sample_count': count,
        'cpu_avg': round(cpu_avg, 2),
        'cpu_max': round(cpu_max, 2),
        'ram_avg_kb': round(ram_avg_kb, 1),
        'duration_sec': duration_sec,
        'by_tab_json': json.dumps(by_tab),
        'first_seen_at': first_seen,
        'last_updated_at': last_updated,
    }
