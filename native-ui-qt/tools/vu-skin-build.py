#!/usr/bin/env python3
"""Build a VU meter skin for the Qt kiosk out of a designer's layered PNGs.

A skin is a folder under native-ui-qt/assets/vu/<id>/ holding:
  skin.json   geometry and display name (read by VuPanel.qml and api_server)
  under.png   everything below the needles (panel + dials), flattened
  over.png    everything above the needles (bezel / frame)
  needle.png  one needle, pointing straight up, drawn at its native size

The layers are flattened so the Now Playing screen draws two panel images
and two needles, exactly like the original skin: the kiosk runs on weak Intel
iGPUs and every full-panel layer is overdraw on every frame of the needles.

All positions are given in SOURCE-artwork pixels; the tool scales them to the
output width and writes them into skin.json.

  build   vu-skin-build.py build OUT_DIR --name-en .. --name-it .. \\
            --under back.png --under dials.png --over coil.png --over frame.png \\
            --needle needle.png --needle-pivot X,Y \\
            --meter X,Y --meter X,Y --angles=MIN,MAX [--width 2048] [--order N]
          (write --angles with "=": a leading minus is otherwise read as an option)
          Effects (skin.json format 2, see VuPanel.qml), all optional:
            --ballistics STIFFNESS,DAMPING,MASS   the needle spring (default 150,15,0.5)
            --backlight lit.png [--backlight-off 0.3] [--backlight-fade 600]
                     a full-canvas layer drawn over the dials, fully lit while
                     playing and at the --backlight-off opacity otherwise
            --peak-lamp lamp.png --peak-lamp-at X,Y --peak-lamp-at X,Y
                     [--peak-lamp-threshold 90] [--peak-lamp-hold 800] [--peak-lamp-over]
                     a lamp (drawn at its native size, centred on each X,Y)
                     lit while the level is over the threshold (0..100)
            --peak-needle [--peak-needle-color '#d32f2f'] [--peak-needle-width 2]
                     [--peak-needle-hold 1500] [--peak-needle-fall 40]
                     a thin second needle on the held peak (width in output pixels)
          Store metadata, for a skin published in the VU meter store:
            --id ID --version N [--author ..] [--license ..]

  pack    vu-skin-build.py pack SKIN_DIR --out DIR
          Packs a built skin whose skin.json has id and version into
          DIR/<id>-<version>.vupak (a zip of skin.json and the files it names)
          plus DIR/<id>-<version>.jpg, its preview (needles at rest at 62/55,
          backlight lit), for the VU meter store.

  index   vu-skin-build.py index DIR
          Writes DIR/index.json, the store catalogue, out of every .vupak in
          DIR (the highest version of each id). Sign it next to it, with the
          OTA signing key the devices trust:
            openssl pkeyutl -sign -inkey ota-signing-key.pem -rawin \\
                    -in DIR/index.json -out DIR/index.json.sig

  needle  vu-skin-build.py needle needles.png --x X0,X1 --top Y --to Y --out needle.png
          For artwork that draws both needles, with their coils, in one layer
          at rest (straight up): cuts the left dial's moving part (needle,
          collar and coil) out of columns X0..X1, rows TOP..TO, and it turns
          as one piece around the pivot, like a real moving-coil meter. The
          coil stays inside the dark cavity round the magnet and slides under
          the bracket in the frame layer.
          With --cut Y --rest coil.png it keeps the coil still instead: the
          needle stops at row CUT (where the collar begins), its last row is
          stretched down to row TO (past the pivot) so it runs on behind the
          coil, and everything from row CUT down, for both dials, goes to
          --rest, to pass to build as an --over below the frame.
          Prints the --needle-pivot to pass to build for a pivot at AXIS,PY:
          AXIS-X0, PY-TOP.

  measure vu-skin-build.py measure dials.png --range X0,X1 [--range X0,X1]
          Finds each dial's pivot as the centre of its main scale arc and
          lists the tick angles around it: the first and last tick are the
          --angles to pass to build (0 = straight up, clockwise positive).

Needs Pillow and numpy (a dev-machine tool, never shipped to the device).
"""
import argparse
import hashlib
import io
import json
import math
import os
import re
import sys
import zipfile

import numpy as np
from PIL import Image


def triple(s):
    a, b, c = s.split(',')
    return float(a), float(b), float(c)


def pair(s):
    a, b = s.split(',')
    return float(a), float(b)


def build(args):
    under = None
    size = None
    for path in args.under:
        im = Image.open(path).convert('RGBA')
        if size is None:
            size = im.size
            under = Image.new('RGBA', size)
        elif im.size != size:
            sys.exit(f'{path}: {im.size} differs from {size}, every layer must share one canvas')
        under.alpha_composite(im)
    over = Image.new('RGBA', size)
    for path in args.over:
        im = Image.open(path).convert('RGBA')
        if im.size != size:
            sys.exit(f'{path}: {im.size} differs from {size}')
        over.alpha_composite(im)
    k = args.width / size[0]
    out_size = (args.width, round(size[1] * k))
    os.makedirs(args.out, exist_ok=True)
    under.resize(out_size, Image.LANCZOS).save(os.path.join(args.out, 'under.png'), optimize=True)
    over.resize(out_size, Image.LANCZOS).save(os.path.join(args.out, 'over.png'), optimize=True)
    needle = Image.open(args.needle).convert('RGBA')
    needle.save(os.path.join(args.out, 'needle.png'), optimize=True)
    px, py = args.needle_pivot
    r = lambda v: round(v * k, 2)
    skin = {}
    if args.id:
        if not re.match(r'^[a-z0-9][a-z0-9_-]{0,40}$', args.id) or not args.version or args.version < 1:
            sys.exit('--id must be a lowercase id and --version a number >= 1')
        skin.update({'id': args.id, 'version': args.version})
        if args.author:
            skin['author'] = args.author
        if args.license:
            skin['license'] = args.license
    skin.update({
        'name': {'en': args.name_en, 'it': args.name_it},
        'order': args.order,
        'size': list(out_size),
        'under': 'under.png',
        'over': 'over.png',
        'needle': {'image': 'needle.png', 'width': r(needle.size[0]), 'height': r(needle.size[1]),
                   'pivotX': r(px), 'pivotY': r(py)},
        'meters': [[r(x), r(y)] for x, y in args.meter],
        'angles': list(args.angles),
    })
    files = ['under.png', 'over.png', 'needle.png']
    effects = {}
    if args.ballistics:
        effects['ballistics'] = dict(zip(('stiffness', 'damping', 'mass'), args.ballistics))
    if args.backlight:
        lit = Image.open(args.backlight).convert('RGBA')
        if lit.size != size:
            sys.exit(f'{args.backlight}: {lit.size} differs from {size}')
        lit.resize(out_size, Image.LANCZOS).save(os.path.join(args.out, 'backlight.png'), optimize=True)
        effects['backlight'] = {'image': 'backlight.png', 'off': args.backlight_off, 'fadeMs': args.backlight_fade}
        files.append('backlight.png')
    if args.peak_lamp:
        if len(args.peak_lamp_at or []) < 2:
            sys.exit('--peak-lamp needs two --peak-lamp-at, left dial first')
        lamp = Image.open(args.peak_lamp).convert('RGBA')
        lamp.save(os.path.join(args.out, 'peak-lamp.png'), optimize=True)
        effects['peakLamp'] = {'image': 'peak-lamp.png', 'at': [[r(x), r(y)] for x, y in args.peak_lamp_at[:2]],
                               'width': r(lamp.size[0]), 'height': r(lamp.size[1]),
                               'threshold': args.peak_lamp_threshold, 'holdMs': args.peak_lamp_hold}
        if args.peak_lamp_over:
            effects['peakLamp']['layer'] = 'over'
        files.append('peak-lamp.png')
    if args.peak_needle:
        effects['peakNeedle'] = {'color': args.peak_needle_color, 'width': args.peak_needle_width, 'minWidth': 1.5,
                                 'height': round(skin['needle']['pivotY'] * 0.92, 2),
                                 'holdMs': args.peak_needle_hold, 'fall': args.peak_needle_fall}
    if effects:
        skin['format'] = 2
        skin['effects'] = effects
    with open(os.path.join(args.out, 'skin.json'), 'w', encoding='utf-8') as f:
        json.dump(skin, f, indent=2, ensure_ascii=False)
        f.write('\n')
    for n in files + ['skin.json']:
        print(f'{n:13s} {os.path.getsize(os.path.join(args.out, n)) // 1024} KiB')


def skin_files(skin):
    """The files a skin.json names, in the order a package lists them."""
    names = [skin['under'], skin['over']]
    if skin.get('needle', {}).get('image'):
        names.append(skin['needle']['image'])
    for eff in (skin.get('effects') or {}).values():
        if isinstance(eff, dict) and eff.get('image'):
            names.append(eff['image'])
    return names


def render_preview(d, skin, width=960, levels=(62, 55)):
    """The skin as VuPanel draws it with the needles at rest: under,
    backlight lit, peak needle a little above, needle, over."""
    sw, sh = skin['size']
    k = width / sw
    out = (width, round(sh * k))

    def layer(name):
        return Image.open(os.path.join(d, name)).convert('RGBA').resize(out, Image.LANCZOS)

    im = Image.new('RGBA', out, (18, 18, 18, 255))
    im.alpha_composite(layer(skin['under']))
    fx = skin.get('effects') or {}
    if fx.get('backlight'):
        im.alpha_composite(layer(fx['backlight']['image']))
    a0, a1 = skin['angles']

    def angle(level):
        return a0 + (a1 - a0) * max(0, min(100, level)) / 100

    def place(sprite, pivot, at, deg):
        th = math.radians(deg)
        c, s_ = math.cos(th), math.sin(th)
        mx, my = at
        px, py = pivot
        return sprite.transform(out, Image.AFFINE, (c, s_, px - c * mx - s_ * my, -s_, c, py + s_ * mx - c * my),
                                resample=Image.BICUBIC)

    def needle(n, at, deg):
        if n.get('image'):
            spr = Image.open(os.path.join(d, n['image'])).convert('RGBA')
            spr = spr.resize((max(1, round(n['width'] * k)), max(1, round(n['height'] * k))), Image.LANCZOS)
            im.alpha_composite(place(spr, (n['pivotX'] * k, n['pivotY'] * k), at, deg))
            return
        w = max(n.get('minWidth', 0), n.get('width', 2) * k)
        h = n.get('height', 300) * k
        spr = Image.new('RGBA', (max(2, math.ceil(w)), max(2, math.ceil(h))), n.get('color', '#111111'))
        im.alpha_composite(place(spr, (spr.size[0] / 2, spr.size[1]), at, deg))

    for i in range(2):
        at = (skin['meters'][i][0] * k, skin['meters'][i][1] * k)
        if fx.get('peakNeedle'):
            needle(dict({'color': '#d32f2f', 'width': 2, 'height': skin['needle'].get('height', 300)}, **fx['peakNeedle']),
                   at, angle(levels[i] + 14))
        needle(skin['needle'], at, angle(levels[i]))
    im.alpha_composite(layer(skin['over']))
    return im.convert('RGB')


def pack(args):
    with open(os.path.join(args.skin, 'skin.json'), encoding='utf-8') as f:
        skin = json.load(f)
    if 'id' not in skin or 'version' not in skin:
        sys.exit(f'{args.skin}/skin.json has no id/version: build it with --id and --version')
    base = f"{skin['id']}-{skin['version']}"
    os.makedirs(args.out, exist_ok=True)
    names = skin_files(skin)
    with zipfile.ZipFile(os.path.join(args.out, base + '.vupak'), 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.write(os.path.join(args.skin, 'skin.json'), 'skin.json')
        for n in names:
            zf.write(os.path.join(args.skin, n), n)
    buf = io.BytesIO()
    render_preview(args.skin, skin).save(buf, 'JPEG', quality=85, optimize=True)
    with open(os.path.join(args.out, base + '.jpg'), 'wb') as f:
        f.write(buf.getvalue())
    for n in (base + '.vupak', base + '.jpg'):
        print(f'{n}  {os.path.getsize(os.path.join(args.out, n)) // 1024} KiB')


def index(args):
    best = {}
    for fn in sorted(os.listdir(args.dir)):
        if not fn.endswith('.vupak'):
            continue
        path = os.path.join(args.dir, fn)
        with zipfile.ZipFile(path) as zf:
            skin = json.loads(zf.read('skin.json'))
        data = open(path, 'rb').read()
        entry = {'id': skin['id'], 'version': skin['version'], 'format': skin.get('format', 1),
                 'name': skin['name'], 'author': skin.get('author', ''), 'license': skin.get('license', ''),
                 'file': fn, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        preview = os.path.join(args.dir, fn[:-len('.vupak')] + '.jpg')
        if os.path.isfile(preview):
            pv = open(preview, 'rb').read()
            entry.update({'preview': os.path.basename(preview), 'previewSize': len(pv),
                          'previewSha256': hashlib.sha256(pv).hexdigest()})
        if skin['id'] not in best or best[skin['id']]['version'] < skin['version']:
            best[skin['id']] = entry
    doc = {'format': 1, 'skins': [best[k] for k in sorted(best)]}
    with open(os.path.join(args.dir, 'index.json'), 'w', encoding='utf-8') as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
        f.write('\n')
    print(f"index.json: {len(doc['skins'])} skin(s)")


def needle(args):
    a = np.array(Image.open(args.layer).convert('RGBA'))
    (x0, x1), top, cut, to = (int(v) for v in args.x), args.top, args.cut, args.to
    if cut is None:
        if not top < to:
            sys.exit('need TOP < TO')
        Image.fromarray(a[top:to, x0:x1]).save(args.out, optimize=True)
    else:
        if not top < cut < to or not args.rest:
            sys.exit('--cut needs --rest and TOP < CUT < TO')
        sprite = np.zeros((to - top, x1 - x0, 4), np.uint8)
        sprite[:cut - top] = a[top:cut, x0:x1]
        sprite[cut - top:] = a[cut - 1, x0:x1]
        Image.fromarray(sprite).save(args.out, optimize=True)
        rest = a.copy()
        rest[:cut] = 0
        Image.fromarray(rest).save(args.rest, optimize=True)
    print(f'{args.out}: {x1 - x0}x{to - top}, origin {x0},{top} -> --needle-pivot AXIS-{x0},PIVOT_Y-{top}')


def kasa(x, y):
    """Least-squares circle through the points: (cx, cy, r)."""
    a = np.c_[2 * x, 2 * y, np.ones_like(x)]
    c, *_ = np.linalg.lstsq(a, x * x + y * y, rcond=None)
    return c[0], c[1], np.sqrt(c[2] + c[0] ** 2 + c[1] ** 2)


def measure(args):
    q = np.array(Image.open(args.dials).convert('RGBA')).astype(float)
    luma = 0.299 * q[:, :, 0] + 0.587 * q[:, :, 1] + 0.114 * q[:, :, 2]
    dark = (q[:, :, 3] > 200) & (luma < 70)
    for x0, x1 in args.range:
        ys, xs = np.where(dark[:, int(x0):int(x1)])
        xs = (xs + x0).astype(float)
        ys = ys.astype(float)
        # coarse: the centre that makes the dark pixels' radii the most peaked
        # (concentric arcs), searched below the dial, then a circle fit on the
        # strongest arc alone so ticks and lettering stop pulling on it
        best = None
        for cx in np.arange((x0 + x1) / 2 - 60, (x0 + x1) / 2 + 61, 4):
            for cy in np.arange(ys.min(), ys.max() + q.shape[0] // 2, 4):
                rr = np.hypot(xs - cx, ys - cy)
                h, _ = np.histogram(rr, bins=np.arange(rr.min(), rr.max() + 2, 2))
                s = np.sort(h)[-3:].sum()
                if best is None or s > best[0]:
                    best = (s, cx, cy)
        _, cx, cy = best
        rr = np.hypot(xs - cx, ys - cy)
        h, e = np.histogram(rr, bins=np.arange(rr.min(), rr.max() + 2, 2))
        arc = e[np.argmax(h)] + 1
        for _ in range(4):
            rr = np.hypot(xs - cx, ys - cy)
            ang = np.degrees(np.arctan2(xs - cx, -(ys - cy)))
            sel = (np.abs(rr - arc) < 9) & (np.abs(ang) < 40)
            cx, cy, arc = kasa(xs[sel], ys[sel])
        rr = np.hypot(xs - cx, ys - cy)
        ang = np.degrees(np.arctan2(xs - cx, -(ys - cy)))
        sel = (rr > arc + 8) & (rr < arc + 36)
        h, e = np.histogram(ang[sel], bins=np.arange(-80, 80.01, 0.25))
        ticks, i = [], 0
        while i < len(h):
            if h[i] > 12:
                j = i
                while j < len(h) and h[j] > 12:
                    j += 1
                w, c = h[i:j], e[i:j] + 0.125
                ticks.append(round(float((w * c).sum() / w.sum()), 2))
                i = j
            else:
                i += 1
        print(f'dial {x0:.0f}..{x1:.0f}: pivot {cx:.2f},{cy:.2f}  arc radius {arc:.1f}')
        print(f'  ticks (deg): {ticks}')
        if ticks:
            print(f'  scale ends: {ticks[0]},{ticks[-1]}')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build')
    b.add_argument('out')
    b.add_argument('--name-en', required=True)
    b.add_argument('--name-it', required=True)
    b.add_argument('--under', action='append', required=True, help='bottom to top, repeatable')
    b.add_argument('--over', action='append', required=True, help='bottom to top, repeatable')
    b.add_argument('--needle', required=True)
    b.add_argument('--needle-pivot', type=pair, required=True, help='rotation centre inside needle.png')
    b.add_argument('--meter', type=pair, action='append', required=True, help='pivot of each dial, left first')
    b.add_argument('--angles', type=pair, required=True, help='needle angle at level 0 and at level 100')
    b.add_argument('--width', type=int, default=2048)
    b.add_argument('--order', type=int, default=50)
    b.add_argument('--ballistics', type=triple)
    b.add_argument('--backlight')
    b.add_argument('--backlight-off', type=float, default=0.0)
    b.add_argument('--backlight-fade', type=int, default=600)
    b.add_argument('--peak-lamp')
    b.add_argument('--peak-lamp-at', type=pair, action='append')
    b.add_argument('--peak-lamp-threshold', type=float, default=90)
    b.add_argument('--peak-lamp-hold', type=int, default=800)
    b.add_argument('--peak-lamp-over', action='store_true')
    b.add_argument('--peak-needle', action='store_true')
    b.add_argument('--peak-needle-color', default='#d32f2f')
    b.add_argument('--peak-needle-width', type=float, default=2)
    b.add_argument('--peak-needle-hold', type=int, default=1500)
    b.add_argument('--peak-needle-fall', type=float, default=40)
    b.add_argument('--id')
    b.add_argument('--version', type=int)
    b.add_argument('--author')
    b.add_argument('--license')
    pk = sub.add_parser('pack')
    pk.add_argument('skin')
    pk.add_argument('--out', required=True)
    ix = sub.add_parser('index')
    ix.add_argument('dir')
    n = sub.add_parser('needle')
    n.add_argument('layer')
    n.add_argument('--x', type=pair, required=True, help='column span of the left needle and coil')
    n.add_argument('--top', type=int, required=True, help='first row of the needle')
    n.add_argument('--to', type=int, required=True, help='last row + 1 (with --cut: stretch the shaft down to it)')
    n.add_argument('--cut', type=int, help='keep the coil still: first row of the collar')
    n.add_argument('--out', required=True)
    n.add_argument('--rest', help='with --cut: the still coils, an --over for build')
    m = sub.add_parser('measure')
    m.add_argument('dials')
    m.add_argument('--range', type=pair, action='append', required=True, help='x span of one dial')
    args = p.parse_args()
    {'build': build, 'needle': needle, 'measure': measure, 'pack': pack, 'index': index}[args.cmd](args)


if __name__ == '__main__':
    main()
