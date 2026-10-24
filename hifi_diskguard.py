#!/usr/bin/env python3
"""The system disk's reserve: room nobody but the system may take.

On the system disk one partition (/data) holds everything — music, /home,
/var (Lyrion's prefs, cache and database, the logs) and the /etc overlay. A
user who fills it with music breaks Lyrion: it runs as its own user, the
first to hit "No space left on device", and it rewrites server.prefs half
way, so it does not come back even after the space is freed (seen in the
field, 2026-10).

Two layers keep the reserve free: 5 % of the partition, never less than
512 MiB nor more than 2 GiB. On a 16 GB disk the data partition is about
5 GB (the rest is the boot partition and the two system slots), and a 2 GiB
floor took 40 % of it; 512 MiB is plenty for Lyrion's prefs, cache and
database to keep writing, and 2 GiB is plenty on any disk:

  * this module, for everything our services write there. They run as root,
    and root ignores the ext4 reserve: every writer of user-sized data
    (file manager, uploads, CD ripping, downloads) asks check() before it
    starts and, when it copies in chunks, a Budget while it goes;
  * the kernel, for what does not go through us (a Samba copy, as
    hifimusic): hifi-disk-reserve.sh gives the partition an ext4 reserve of
    the same size, usable only by root and the RESERVE_GROUP (Lyrion, the
    kiosk). Samba stops at the line, Lyrion keeps writing below it.

Paths on other disks (USB, internal music disks) have no reserve: Lyrion
does not live there.

`python3 hifi_diskguard.py status` prints the state as JSON; `reserve-bytes
<path>` prints the reserve the shell script applies.
"""
import json
import os
import sys

# What the reserve protects; its filesystem is "the system disk".
SYSTEM_MARK = '/var/lib/squeezeboxserver'
SYSTEM_FALLBACK = '/var'
MIN_RESERVE = 512 * 1024 ** 2
MAX_RESERVE = 2 * 1024 ** 3
RESERVE_FRACTION = 0.05
# Above this share of the disk used, the screens warn.
WARN_FRACTION = 0.90
# A chunked copy asks the filesystem again after this many bytes.
RECHECK_BYTES = 64 * 1024 ** 2
RESERVE_GROUP = 'hifi-reserve'
UI_LANGUAGE_FILE = '/etc/hifi-player/ui-language'


class NoRoom(OSError):
    """Writing `need` bytes there would eat into the system's reserve.
    `room` is what may still be written (never negative)."""

    def __init__(self, path, need, room, reserve):
        super().__init__(28, 'system disk reserve reached', path)   # 28 = ENOSPC
        self.need, self.room, self.reserve = need, max(0, room), reserve


def _existing(path):
    """`path`, or its nearest existing parent (a destination may not exist yet)."""
    path = os.path.abspath(path or '/')
    while not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path


def system_dev():
    for p in (SYSTEM_MARK, SYSTEM_FALLBACK):
        try:
            return os.stat(p).st_dev
        except OSError:
            continue
    return None


def on_system_disk(path, sys_dev=None):
    """True when `path` (or where it would be created) is on the system
    disk's data partition."""
    sys_dev = system_dev() if sys_dev is None else sys_dev
    if sys_dev is None:
        return False
    try:
        return os.stat(_existing(path)).st_dev == sys_dev
    except OSError:
        return False


def reserve_for(total_bytes):
    return int(min(MAX_RESERVE, max(MIN_RESERVE, total_bytes * RESERVE_FRACTION)))


def _vfs(path):
    st = os.statvfs(_existing(path))
    total = st.f_blocks * st.f_frsize
    free = st.f_bfree * st.f_frsize          # what root sees: the reserve is ours to keep
    return total, free


def room(path):
    """Bytes that may still be written at `path` before the reserve; None
    when `path` is not on the system disk (no limit of ours)."""
    if not on_system_disk(path):
        return None
    try:
        total, free = _vfs(path)
    except OSError:
        return None
    return free - reserve_for(total)


def check(path, need):
    """Raise NoRoom when `need` bytes at `path` would go below the reserve."""
    r = room(path)
    if r is not None and need > r:
        raise NoRoom(path, need, r, reserve_for(_vfs(path)[0]))


def check_any(path, need):
    """Like check() on the system disk, but also guards disks with no reserve
    of ours (the second internal disk, a USB stick): there `need` must simply
    fit in the free space. NoRoom.reserve is 0 for those, which the reader's
    message turns into the plain 'this disk is full' wording."""
    r = room(path)
    if r is not None:                       # system disk: keep the reserve free
        if need > r:
            raise NoRoom(path, need, r, reserve_for(_vfs(path)[0]))
        return
    try:                                    # any other disk: plain free space
        _total, free = _vfs(path)
    except OSError:
        return                              # can't measure it -- let the write try
    if need > free:
        raise NoRoom(path, need, free, 0)


class Budget:
    """For a copy that goes chunk by chunk: `add(n)` after every chunk asks
    the filesystem again every RECHECK_BYTES and raises NoRoom as soon as the
    reserve is reached — also when someone else is filling the disk at the
    same time. Free when `path` is not on the system disk."""

    def __init__(self, path):
        self.path = path
        self.active = on_system_disk(path)
        self._since = 0

    def add(self, n):
        if not self.active:
            return
        self._since += n
        if self._since >= RECHECK_BYTES:
            self._since = 0
            check(self.path, 0)


def status():
    """The system disk for the screens: sizes, the reserve, and a level —
    ok, warn (more than 90 % used) or full (at the reserve)."""
    path = SYSTEM_MARK if os.path.exists(SYSTEM_MARK) else SYSTEM_FALLBACK
    try:
        total, free = _vfs(path)
    except OSError:
        return {'available': False}
    reserve = reserve_for(total)
    used = total - free
    level = 'full' if free <= reserve else ('warn' if used >= total * WARN_FRACTION else 'ok')
    return {'available': True, 'total': total, 'free': free, 'used': used,
            'reserve': reserve, 'room': max(0, free - reserve),
            'percent': round(used * 100.0 / total, 1) if total else 0, 'level': level}


def gb(n, lang='en'):
    """Bytes → '1.5' (GB, one decimal; '1,5' in Italian), for the messages."""
    s = f'{max(0, n) / 1000 ** 3:.1f}'
    return s.replace('.', ',') if lang == 'it' else s


def message(err, lang, stopped=False):
    """The reader's sentence for a NoRoom: 'disk.noRoom' before anything was
    written, 'disk.noRoomStopped' when a copy had to stop half way. A disk with
    no reserve of ours (reserve == 0: the second disk, a USB stick) gets the
    plainer wording, with no mention of the reserve kept for Lyrion."""
    from hifi_i18n import t
    plain = not err.reserve
    if stopped:
        if plain:
            return t('disk.noRoomStoppedPlain', lang)
        return t('disk.noRoomStopped', lang, reserve=gb(err.reserve, lang))
    if plain:
        return t('disk.noRoomPlain', lang, need=gb(err.need, lang), room=gb(err.room, lang))
    return t('disk.noRoom', lang, need=gb(err.need, lang), room=gb(err.room, lang),
             reserve=gb(err.reserve, lang))


def main(argv):
    if len(argv) >= 2 and argv[1] == 'status':
        print(json.dumps(status()))
        return 0
    if len(argv) >= 3 and argv[1] == 'reserve-bytes':
        print(reserve_for(_vfs(argv[2])[0]))
        return 0
    if len(argv) >= 4 and argv[1] == 'need-free':
        # For the system's own installs (Lyrion), which may use the reserve:
        # is there `bytes` free at all? Prints why not, in the device's language.
        need = int(argv[3])
        free = _vfs(argv[2])[1]
        if free >= need:
            return 0
        lang = 'en'
        try:
            with open(UI_LANGUAGE_FILE, encoding='utf-8') as f:
                lang = 'it' if f.read().strip().startswith('it') else 'en'
        except OSError:
            pass
        from hifi_i18n import t
        print(t('disk.noRoomInstall', lang, need=gb(need, lang), free=gb(free, lang)))
        return 1
    print(__doc__.strip().splitlines()[0], file=sys.stderr)
    print('usage: hifi_diskguard.py status | reserve-bytes <path> | need-free <path> <bytes>', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
