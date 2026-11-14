#!/usr/bin/env python3
"""Compute the Recommended list (hifi_recommend.run) once and exit.

Started by hifi-recommend.timer with --scheduled, at the time the owner chose
in the settings, or by the API's "compute now" without it. Only a scheduled
run stands back: it does nothing when the feature or its schedule is off,
waits out the first minutes after boot (a missed run is caught up at power-on,
and the device should finish starting first) and comes back in half an hour
if music is playing. A run the owner asked for goes ahead at once; both run at
the lowest priority (see the unit).
"""
import fcntl
import glob
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, '/usr/local/bin')

BOOT_GRACE = 300          # seconds of uptime before a scheduled run starts
RETRY_AFTER = 1800        # seconds; "music is playing, come back later"
RETRY_UNIT = 'hifi-recommend-retry'


def get_log():
    try:
        from hifi_logging import get_logger
        return get_logger('recommend')
    except Exception:
        import logging
        logging.basicConfig(level=logging.INFO, format='%(message)s')
        return logging.getLogger('recommend')


def uptime():
    try:
        with open('/proc/uptime') as f:
            return float(f.read().split()[0])
    except (OSError, ValueError):
        return BOOT_GRACE


def audio_running():
    """True while any ALSA playback stream of this box is running: whatever
    feeds it (Lyrion, Bluetooth, AirPlay), someone is listening."""
    for path in glob.glob('/proc/asound/card*/pcm*p/sub*/status'):
        try:
            with open(path) as f:
                if 'state: RUNNING' in f.read():
                    return True
        except OSError:
            pass
    return False


def retry_later(log):
    r = subprocess.run(
        ['systemd-run', '--quiet', '--collect', '--unit', RETRY_UNIT,
         '--on-active=%d' % RETRY_AFTER,
         '/usr/bin/systemctl', 'start', '--no-block', 'hifi-recommend.service'],
        capture_output=True, text=True)
    log.info('recommend: music is playing, trying again in %d min%s',
             RETRY_AFTER // 60, '' if r.returncode == 0 else ' (retry already pending)')


def lyrion_rpc(base):
    def rpc(player, command):
        req = urllib.request.Request(
            base + '/jsonrpc.js',
            json.dumps({'id': 1, 'method': 'slim.request',
                        'params': [player or '', command]}).encode('utf-8'),
            {'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode('utf-8')).get('result') or {}
    return rpc


def online_allowed():
    """The owner's "fetch information from the Internet" switch
    (hifi_metadata's meta-online flag): missing means allowed."""
    try:
        with open('/etc/hifi-player/meta-online') as f:
            return f.read().strip() != '0'
    except OSError:
        return True


def main(argv):
    scheduled = '--scheduled' in argv
    log = get_log()
    import hifi_recommend as rec
    settings = rec.load_settings()
    if scheduled:
        if not settings['enabled'] or not rec.schedule_oncalendar(settings):
            return 0
        wait = BOOT_GRACE - uptime()
        if wait > 0:
            time.sleep(wait)
        if audio_running():
            retry_later(log)
            return 0

    os.makedirs(rec.DB_DIR, exist_ok=True)
    lock = open(os.path.join(rec.DB_DIR, 'run.lock'), 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log.info('recommend: a run is already going, leaving it to it')
        return 0

    import hifi_metadata
    db = rec.open_db()
    run_id = rec.start_run(db)
    summary = {'outcome': 'error'}
    started = time.time()
    try:
        embedder = rec.Embedder.load(rec.MODEL_DIR, threads=2)
        http = hifi_metadata.CLIENT if online_allowed() else None
        rpc = lyrion_rpc(hifi_metadata.Lyrion().base_url())
        summary = rec.run(db, rpc, http=http, settings=settings,
                          embedder=embedder, log=log)
    except Exception as e:
        summary = {'outcome': 'error', 'error': type(e).__name__}
        log.exception('recommend: run failed')
    finally:
        rec.finish_run(db, run_id, summary)
    log.info('recommend: %s in %.0f s: %s', summary.get('outcome'),
             time.time() - started,
             ', '.join('%s=%s' % kv for kv in sorted(summary.items())
                       if kv[0] != 'outcome'))
    return 0 if summary.get('outcome') != 'error' else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
