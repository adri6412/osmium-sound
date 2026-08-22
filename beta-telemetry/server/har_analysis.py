"""HAR summary rollup, ported from tools/har-viewer/har_cli.py's
normalize()/cmd_summary()/cmd_domains() so an uploaded .har gets a compact
summary computed once at ingestion time instead of being re-parsed on every
dashboard view.
"""
import json
from urllib.parse import urlsplit


def _status_class(status):
    return 'err' if not status else f'{status // 100}xx'


def _normalize(entries):
    out = []
    for e in entries:
        req = e.get('request') or {}
        res = e.get('response') or {}
        url = req.get('url', '')
        parts = urlsplit(url)
        status = res.get('status') or 0
        failed = not status
        content = res.get('content') or {}
        size = content.get('size') or 0
        if size <= 0:
            size = res.get('bodySize') or 0
            if size < 0:
                size = 0
        out.append({
            'domain': parts.netloc or '(relative)',
            'status': status,
            'failed': failed,
            'size': size,
        })
    return out


def analyze_har(raw_bytes, top_domains_n=10):
    """Parse HAR JSON bytes and return a compact summary dict, or None if the
    bytes don't look like a HAR file. Never raises -- a malformed capture must
    not take the whole upload down."""
    try:
        data = json.loads(raw_bytes)
        entries = (data.get('log') or {}).get('entries')
        if not isinstance(entries, list):
            return None
    except Exception:
        return None

    normalized = _normalize(entries)
    by_status = {}
    errors = 0
    domains = {}
    for e in normalized:
        cls = _status_class(e['status'])
        by_status[cls] = by_status.get(cls, 0) + 1
        if e['failed'] or e['status'] >= 400:
            errors += 1
        d = domains.setdefault(e['domain'], {'count': 0, 'size': 0, 'errors': 0})
        d['count'] += 1
        d['size'] += e['size']
        if e['failed'] or e['status'] >= 400:
            d['errors'] += 1

    top_domains = dict(sorted(domains.items(), key=lambda kv: kv[1]['size'], reverse=True)[:top_domains_n])

    return {
        'requests_count': len(normalized),
        'errors_count': errors,
        'by_status': by_status,
        'top_domains': top_domains,
    }
