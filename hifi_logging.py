"""Shared logging helpers for the HiFi Player appliance's Python daemons.

Every custom daemon historically only wrote to stdout/stderr, captured by
journald — which on this image is itself volatile (no /var/log/journal until
the support-logging OS migration creates it). get_logger()/tee_stdio_to_file()
add a size-rotated file under /var/log/hifi/ so this history survives a
reboot and can be picked up by the support-bundle endpoint, without requiring
every print() call site across the daemons to change.
"""
import io
import logging
import logging.handlers
import os
import sys

LOG_DIR = os.environ.get('HIFI_LOG_DIR', '/var/log/hifi')
MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 5


def get_logger(name, echo=True, level=logging.INFO):
    """Logger for `name` with a rotating file handler under LOG_DIR. If
    `echo`, also attaches a stream handler so console/journald output is
    unchanged from today."""
    logger = logging.getLogger(f'hifi.{name}')
    if logger.handlers:
        return logger
    logger.setLevel(level)
    fmt = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')

    if echo:
        stream = logging.StreamHandler()
        stream.setFormatter(fmt)
        logger.addHandler(stream)

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            os.path.join(LOG_DIR, f'{name}.log'),
            maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError:
        pass  # e.g. local dev without root / without the dir — console still works

    logger.propagate = False
    return logger


class _StreamToLogger(io.TextIOBase):
    """File-like shim: each line written is echoed to the real stream (so
    journald/console output stays exactly as before) and forwarded to a
    logger, which persists it to the rotated file."""

    def __init__(self, logger, level, echo_stream):
        self._logger = logger
        self._level = level
        self._echo = echo_stream
        self._buf = ''

    def write(self, data):
        if self._echo is not None:
            self._echo.write(data)
        self._buf += data
        while '\n' in self._buf:
            line, self._buf = self._buf.split('\n', 1)
            if line:
                self._logger.log(self._level, line)
        return len(data)

    def flush(self):
        if self._echo is not None:
            self._echo.flush()


def tee_stdio_to_file(name):
    """Redirect this process's stdout/stderr so every existing print() call
    keeps reaching the console/journald AND also lands in a size-rotated file
    at /var/log/hifi/<name>.log — no call sites need to change."""
    logger = get_logger(name, echo=False)
    sys.stdout = _StreamToLogger(logger, logging.INFO, sys.__stdout__)
    sys.stderr = _StreamToLogger(logger, logging.ERROR, sys.__stderr__)
