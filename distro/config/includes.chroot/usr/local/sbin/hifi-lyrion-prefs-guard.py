#!/usr/bin/env python3
"""Lyrion's state: fix stray ownership, and keep a last good copy of each prefs
file to put back when one is broken.

Run before every start of Lyrion (ExecStartPre, as root), it does two things.

Ownership. Lyrion runs as the squeezeboxserver user (uid fixed at 900 by
sysusers.d) and can only read, not create, inside a directory owned by root.
A root-level operation can leave its cache or state tree owned by root — e.g.
the /var graft at an image's first boot (initramfs cp -a from the image), or a
backup restore — and then the first NEW plugin Lyrion is asked to install dies
on `mkdir .../cache/InstalledPlugins/Plugins/<name>: Permission denied`, a fatal
croak that keeps the service down for good (field report, 2026-10-23: Spotty on
a device born as an image, where hifi-ab-firstboot's one-off chown never ran).
So every start we chown back to squeezeboxserver:nogroup anything under its
cache, prefs and log trees that is owned by someone else. The playlist folder is
left alone on purpose (hifimusic:hifishare, setgid — see _make_playlist_folder
in sources_server.py, which re-asserts it on every start).

Prefs. Lyrion rewrites its .prefs files (YAML) in place. On a full disk the
write fails half way and leaves an empty or cut file; at the next start Lyrion
cannot read server.prefs ("Unable to read prefs … YAML::XS::LibYAML::Load") and
gives up — so freeing the space did not bring it back (field report, 2026-10):

  * every prefs file that reads well is copied to prefs/.osmium-good/;
  * every one that is empty or does not parse is replaced by its good copy,
    if there is one (otherwise it is moved aside, so Lyrion starts with that
    part at its defaults instead of not starting at all).

Never blocks the start: any error is logged and Lyrion starts anyway.
"""
import os
import pwd
import shutil
import sys

PREFS = os.environ.get('PREFSDIR', '/var/lib/squeezeboxserver/prefs')
CACHE = os.environ.get('CACHEDIR', '/var/lib/squeezeboxserver/cache')
GOOD = '.osmium-good'
USER = 'squeezeboxserver'
# The state trees to re-own on every start. BASE covers prefs and the usual
# cache (and the rest of /var/lib/squeezeboxserver); the log dir lives apart,
# and CACHE is added only when it has been pointed somewhere outside BASE.
BASE = os.path.dirname(PREFS)
_cache = os.path.normpath(CACHE)
_under_base = _cache == BASE or _cache.startswith(BASE.rstrip('/') + '/')
OWN_TREES = (BASE, '/var/log/squeezeboxserver') + (() if _under_base else (_cache,))
# Never re-owned: the playlist folder belongs to the share user with the shared
# group and the setgid bit, so Lyrion and Samba can both write in it.
OWN_SKIP = (os.path.join(BASE, 'playlists'),)

try:
    import yaml
except ImportError:                     # the image has python3-yaml; never fail over it
    yaml = None


def log(msg):
    print(f'hifi-lyrion-prefs-guard: {msg}', flush=True)


def readable(path):
    """True when `path` is a prefs file Lyrion can load: not empty, and YAML
    (a mapping) when the parser is there. None when it cannot be read at all
    (an I/O error): then it is left alone, not judged."""
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except OSError:
        return None
    if not data.strip():
        return False
    if yaml is None:
        return data.lstrip().startswith(b'---')
    try:
        # the syntax only: Lyrion's own tags (!!perl/…) need not be known
        node = yaml.compose(data)
    except Exception:
        return False
    return isinstance(node, yaml.MappingNode)


def prefs_files(root):
    """server.prefs and the plugins' prefs, relative to `root`."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != GOOD]
        for name in filenames:
            if name.endswith('.prefs'):
                out.append(os.path.relpath(os.path.join(dirpath, name), root))
    return sorted(out)


def _owner():
    try:
        pw = pwd.getpwnam(USER)
        return pw.pw_uid, pw.pw_gid
    except KeyError:
        return None


def own_tree(trees, owner, skip=(), lstat=os.lstat, chown=os.lchown):
    """chown back to `owner` every entry under `trees` that belongs to someone
    else, skipping the subtrees in `skip`. Conditional, so once a tree is right
    the next start touches nothing (cheap even on a large cache). Symlinks are
    chowned as themselves, not followed. Returns how many entries were fixed;
    a per-entry error is logged, never raised — the start must not depend on it."""
    if not owner:
        return 0
    uid, gid = owner
    skip = tuple(os.path.normpath(s) for s in skip)
    fixed = 0

    def fix(path):
        nonlocal fixed
        try:
            st = lstat(path)
        except OSError:
            return
        if st.st_uid == uid and st.st_gid == gid:
            return
        try:
            chown(path, uid, gid)
            fixed += 1
        except OSError as e:
            log(f'cannot set owner of {path}: {e}')

    for tree in trees:
        if os.path.normpath(tree) in skip or not os.path.lexists(tree):
            continue
        fix(tree)
        for dirpath, dirnames, filenames in os.walk(tree):
            dirnames[:] = [d for d in dirnames
                           if os.path.normpath(os.path.join(dirpath, d)) not in skip]
            for name in dirnames + filenames:
                fix(os.path.join(dirpath, name))
    return fixed


def _copy(src, dst, owner):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + '.tmp'
    shutil.copy2(src, tmp)
    if owner:
        os.chown(tmp, *owner)
    os.replace(tmp, dst)


def guard(root=PREFS):
    """Save the good, restore the broken. Returns (saved, restored, moved)."""
    saved, restored, moved = [], [], []
    if not os.path.isdir(root):
        return saved, restored, moved
    owner = _owner()
    good_root = os.path.join(root, GOOD)
    for rel in prefs_files(root):
        path, good = os.path.join(root, rel), os.path.join(good_root, rel)
        state = readable(path)
        if state is None:
            log(f'cannot read {rel}: left as it is')
            continue
        if state:
            try:
                _copy(path, good, owner)
                saved.append(rel)
            except OSError as e:          # a full disk, most likely: the old good copy stays
                log(f'cannot save {rel}: {e}')
            continue
        if readable(good):
            try:
                _copy(good, path, owner)
                restored.append(rel)
                log(f'{rel} was empty or broken: last good copy put back')
            except OSError as e:
                log(f'cannot restore {rel}: {e}')
        else:
            try:
                os.replace(path, path + '.broken')
                moved.append(rel)
                log(f'{rel} was empty or broken and has no good copy: moved aside, Lyrion starts with its defaults')
            except OSError as e:
                log(f'cannot move {rel} aside: {e}')
    if owner:
        try:
            os.chown(good_root, *owner)
        except OSError:
            pass
    return saved, restored, moved


def main():
    try:
        owned = own_tree(OWN_TREES, _owner(), OWN_SKIP)
        saved, restored, moved = guard()
        log(f'{len(saved)} saved, {len(restored)} restored, '
            f'{len(moved)} moved aside, {owned} owner fixed')
    except Exception as e:                 # never stop Lyrion from starting
        log(f'error: {e}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
