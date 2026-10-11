#!/usr/bin/env python3
"""Lyrion's prefs: keep a last good copy, put it back when a file is broken.

Lyrion rewrites its .prefs files (YAML) in place. On a full disk the write
fails half way and leaves an empty or cut file; at the next start Lyrion
cannot read server.prefs ("Unable to read prefs … YAML::XS::LibYAML::Load")
and gives up — so freeing the space did not bring it back (field report,
2026-10). Run before every start of Lyrion (ExecStartPre):

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
GOOD = '.osmium-good'
USER = 'squeezeboxserver'

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
        saved, restored, moved = guard()
        log(f'{len(saved)} saved, {len(restored)} restored, {len(moved)} moved aside')
    except Exception as e:                 # never stop Lyrion from starting
        log(f'error: {e}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
