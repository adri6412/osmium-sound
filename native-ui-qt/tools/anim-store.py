#!/usr/bin/env python3
"""Pack the Now Playing animations of the store (anim-store/<id>/) and write
their catalogue, for file.osmiumsound.it/anim/ (api_server.py's animation
store downloads and checks them).

    anim-store.py pack anim-store/<id> --out OUT
    anim-store.py index OUT

A folder holds anim.json, the scene's QML files, its images and preview.jpg
(a still of the scene, shown on the store's card: a scene cannot be drawn
outside the kiosk, so its author provides it). pack checks everything the
device will check, then writes <id>-<version>.animpak and <id>-<version>.jpg;
index lists every package in OUT (the highest version per id) in index.json.

Packages are reproducible: fixed timestamps, sorted names, the same bytes for
the same folder. A published <id>-<version>.animpak is cached for good, so a
changed scene needs a higher version anyway, but publishing the same one
again must not produce a different file under the same name.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import zipfile

# mirrored in api_server.py (the animation store)
SCENE_FORMAT = 1
ID_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{0,40}$')
FILE_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.(png|jpg|json|qml)$')
FILES_MAX = 64
PACK_MAX = 40 * 1024 * 1024
UNPACKED_MAX = 80 * 1024 * 1024
PREVIEW_MAX = 1024 * 1024
QML_MAX = 512 * 1024
BUILTIN = ('none', 'cd', 'cdfront', 'vinyl', 'cassette')
EPOCH = (1980, 1, 1, 0, 0, 0)


def fail(msg):
    sys.exit(f'anim-store: {msg}')


def load_meta(folder):
    try:
        with open(os.path.join(folder, 'anim.json'), encoding='utf-8') as f:
            meta = json.load(f)
    except (OSError, ValueError) as e:
        fail(f'{folder}/anim.json: {e}')
    if not isinstance(meta, dict):
        fail(f'{folder}/anim.json is not an object')
    aid, ver, fmt = meta.get('id'), meta.get('version'), meta.get('format', 1)
    if not (isinstance(aid, str) and ID_RE.match(aid)) or aid in BUILTIN:
        fail(f'{folder}: bad or built-in id {aid!r}')
    if os.path.basename(os.path.normpath(folder)) != aid:
        fail(f'{folder}: the folder must be named after the id ({aid})')
    if not (isinstance(ver, int) and not isinstance(ver, bool) and ver >= 1):
        fail(f'{folder}: version must be an integer >= 1')
    if not (isinstance(fmt, int) and 1 <= fmt <= SCENE_FORMAT):
        fail(f'{folder}: format {fmt!r} (this tool knows up to {SCENE_FORMAT})')
    name = meta.get('name')
    if not (isinstance(name, dict) and isinstance(name.get('en'), str) and name['en'] and isinstance(name.get('it'), str)):
        fail(f'{folder}: name needs "en" and "it"')
    scene = meta.get('scene')
    if not (isinstance(scene, str) and scene.endswith('.qml') and FILE_RE.match(scene)
            and os.path.isfile(os.path.join(folder, scene))):
        fail(f'{folder}: scene {scene!r} is not a .qml file of the folder')
    return meta


def package_files(folder):
    """The files that go in the package: everything but the preview."""
    names = sorted(n for n in os.listdir(folder) if n != 'preview.jpg' and not n.startswith('.'))
    if len(names) > FILES_MAX:
        fail(f'{folder}: more than {FILES_MAX} files')
    total = 0
    for n in names:
        path = os.path.join(folder, n)
        if not os.path.isfile(path) or not FILE_RE.match(n):
            fail(f'{folder}/{n}: only flat .qml, .png, .jpg and .json files')
        data = open(path, 'rb').read()
        total += len(data)
        if n.endswith('.png') and not data.startswith(b'\x89PNG\r\n\x1a\n'):
            fail(f'{folder}/{n} is not a PNG')
        if n.endswith('.jpg') and not data.startswith(b'\xff\xd8\xff'):
            fail(f'{folder}/{n} is not a JPEG')
        if n.endswith('.qml'):
            if len(data) > QML_MAX:
                fail(f'{folder}/{n} is larger than {QML_MAX} bytes')
            try:
                if '\x00' in data.decode('utf-8'):
                    raise UnicodeDecodeError('utf-8', b'', 0, 1, 'NUL')
            except UnicodeDecodeError:
                fail(f'{folder}/{n} is not UTF-8 text')
    if total > UNPACKED_MAX:
        fail(f'{folder}: {total} bytes unpacked, the limit is {UNPACKED_MAX}')
    return names


def pack(args):
    folder = args.folder
    meta = load_meta(folder)
    names = package_files(folder)
    preview = os.path.join(folder, 'preview.jpg')
    if not os.path.isfile(preview):
        fail(f'{folder}/preview.jpg is missing (a still of the scene for the store card)')
    pv = open(preview, 'rb').read()
    if not pv.startswith(b'\xff\xd8\xff') or len(pv) > PREVIEW_MAX:
        fail(f'{folder}/preview.jpg must be a JPEG under {PREVIEW_MAX} bytes')
    base = f"{meta['id']}-{meta['version']}"
    os.makedirs(args.out, exist_ok=True)
    out = os.path.join(args.out, base + '.animpak')
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zf:
        for n in names:
            info = zipfile.ZipInfo(n, date_time=EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            zf.writestr(info, open(os.path.join(folder, n), 'rb').read())
    if os.path.getsize(out) > PACK_MAX:
        fail(f'{out} is larger than {PACK_MAX} bytes')
    with open(os.path.join(args.out, base + '.jpg'), 'wb') as f:
        f.write(pv)
    for n in (base + '.animpak', base + '.jpg'):
        print(f'{n}  {os.path.getsize(os.path.join(args.out, n)) // 1024} KiB')


def index(args):
    best = {}
    for fn in sorted(os.listdir(args.dir)):
        if not fn.endswith('.animpak'):
            continue
        path = os.path.join(args.dir, fn)
        with zipfile.ZipFile(path) as zf:
            meta = json.loads(zf.read('anim.json'))
        data = open(path, 'rb').read()
        entry = {'id': meta['id'], 'version': meta['version'], 'format': meta.get('format', 1),
                 'name': meta['name'], 'author': meta.get('author', ''), 'license': meta.get('license', ''),
                 'file': fn, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        preview = os.path.join(args.dir, fn[:-len('.animpak')] + '.jpg')
        if os.path.isfile(preview):
            pv = open(preview, 'rb').read()
            entry.update({'preview': os.path.basename(preview), 'previewSize': len(pv),
                          'previewSha256': hashlib.sha256(pv).hexdigest()})
        if meta['id'] not in best or best[meta['id']]['version'] < meta['version']:
            best[meta['id']] = entry
    doc = {'format': 1, 'animations': [best[k] for k in sorted(best)]}
    with open(os.path.join(args.dir, 'index.json'), 'w', encoding='utf-8') as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
        f.write('\n')
    print(f"index.json: {len(doc['animations'])} animation(s)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    pk = sub.add_parser('pack', help='pack one folder of anim-store/')
    pk.add_argument('folder')
    pk.add_argument('--out', required=True)
    ix = sub.add_parser('index', help='write index.json for the packages in a folder')
    ix.add_argument('dir')
    args = ap.parse_args()
    {'pack': pack, 'index': index}[args.cmd](args)


if __name__ == '__main__':
    main()
