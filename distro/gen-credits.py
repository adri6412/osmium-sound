#!/usr/bin/env python3
"""The Debian packages of an image, with their licenses — written at build time.

build-image.sh runs this on the finished chroot, before the cleanup that
strips /usr/share/doc down to the copyright files:

    gen-credits.py <chroot> <chroot>/usr/lib/osmium/credits.json

For every installed package it takes name, version, homepage and source
package from <chroot>/var/lib/dpkg/status, and the license from
/usr/share/doc/<pkg>/copyright: the `License:` fields of a machine-readable
(DEP-5) file, or a handful of well-known phrases in an old free-form one.
api_server.py's /credits serves the result to Settings → Licenses & credits
(web admin, full list) and the on-screen Third-Party Notices (count), next to
the hand-kept THIRD-PARTY-NOTICES.md.

Runs on the build host: nothing is executed inside the chroot.
"""
import datetime
import json
import os
import re
import sys

# Free-form copyright files: the phrase that identifies a license, in the
# order they are checked. Only the first hit per phrase counts.
_PHRASES = (
    (re.compile(r'GNU Affero General Public License', re.I), 'AGPL'),
    (re.compile(r'GNU (Lesser|Library) General Public License', re.I), 'LGPL'),
    (re.compile(r'GNU General Public License', re.I), 'GPL'),
    (re.compile(r'Apache License', re.I), 'Apache'),
    (re.compile(r'Mozilla Public License', re.I), 'MPL'),
    (re.compile(r'Permission is hereby granted, free of charge', re.I), 'MIT/Expat'),
    (re.compile(r'Redistribution and use in source and binary forms', re.I), 'BSD'),
    (re.compile(r'Boost Software License', re.I), 'BSL-1.0'),
    (re.compile(r'public domain', re.I), 'public-domain'),
)
UNKNOWN = 'see copyright file'


def parse_status(text):
    """Installed packages from a dpkg status file: list of dicts with the
    fields that matter (Package, Version, Homepage, Source)."""
    pkgs = []
    for stanza in re.split(r'\n\s*\n', text):
        fields = {}
        for line in stanza.splitlines():
            if line[:1].isspace() or ':' not in line:
                continue
            k, _, v = line.partition(':')
            fields[k.strip()] = v.strip()
        if not fields.get('Package'):
            continue
        if not fields.get('Status', '').endswith(' installed'):
            continue
        source = fields.get('Source', '')
        source = source.split(' (', 1)[0].strip()
        pkgs.append({
            'name': fields['Package'],
            'version': fields.get('Version', ''),
            'homepage': fields.get('Homepage', ''),
            'source': source,
        })
    return pkgs


def licenses_from_copyright(text):
    """A short license summary for one copyright file."""
    if not text:
        return UNKNOWN
    names = []
    if re.search(r'^Format:\s*\S+copyright-format', text, re.M | re.I):
        for m in re.finditer(r'^License:[ \t]*([^\n]+)', text, re.M):
            name = m.group(1).strip()
            if name and len(name) <= 80 and name not in names:
                names.append(name)
    if not names:
        for rx, name in _PHRASES:
            if rx.search(text) and name not in names:
                names.append(name)
    return ', '.join(names) if names else UNKNOWN


def _doc_dir(chroot, pkg):
    """<chroot>/usr/share/doc/<pkg>, following a symlink to another package's
    folder (Debian does that for packages built from one source) without ever
    leaving the chroot."""
    d = os.path.join(chroot, 'usr', 'share', 'doc', pkg)
    if os.path.islink(d):
        target = os.readlink(d)
        d = os.path.join(chroot, target.lstrip('/')) if target.startswith('/') else os.path.join(os.path.dirname(d), target)
    return d


def copyright_text(chroot, pkg, source=''):
    for name in (pkg, source):
        if not name:
            continue
        path = os.path.join(_doc_dir(chroot, name), 'copyright')
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                return f.read()
        except OSError:
            continue
    return ''


def suite_of(chroot):
    try:
        with open(os.path.join(chroot, 'etc', 'os-release'), encoding='utf-8') as f:
            for line in f:
                if line.startswith('VERSION_CODENAME='):
                    return line.split('=', 1)[1].strip().strip('"')
    except OSError:
        pass
    return ''


def build(chroot):
    with open(os.path.join(chroot, 'var', 'lib', 'dpkg', 'status'), encoding='utf-8', errors='replace') as f:
        pkgs = parse_status(f.read())
    for p in pkgs:
        p['license'] = licenses_from_copyright(copyright_text(chroot, p['name'], p['source']))
    pkgs.sort(key=lambda p: p['name'])
    return {
        'generated': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d'),
        'suite': suite_of(chroot),
        'count': len(pkgs),
        'packages': pkgs,
    }


def main(argv):
    if len(argv) != 3:
        print('usage: gen-credits.py <chroot> <out.json>', file=sys.stderr)
        return 2
    chroot, out = argv[1], argv[2]
    data = build(chroot)
    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    tmp = out + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1, sort_keys=True)
        f.write('\n')
    os.replace(tmp, out)
    unknown = sum(1 for p in data['packages'] if p['license'] == UNKNOWN)
    print(f"gen-credits: {data['count']} packages ({unknown} without a recognisable license) -> {out}")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
