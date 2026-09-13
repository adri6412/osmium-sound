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
            --under back.png --under dials.png --over frame.png \\
            --needle needle.png --needle-pivot X,Y \\
            --meter X,Y --meter X,Y --angles=MIN,MAX [--width 2048] [--order N]
          (write --angles with "=": a leading minus is otherwise read as an option)

  measure vu-skin-build.py measure dials.png --range X0,X1 [--range X0,X1]
          Finds each dial's pivot as the centre of its main scale arc and
          lists the tick angles around it: the first and last tick are the
          --angles to pass to build (0 = straight up, clockwise positive).

Needs Pillow and numpy (a dev-machine tool, never shipped to the device).
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image


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
    over = Image.open(args.over).convert('RGBA')
    if over.size != size:
        sys.exit(f'{args.over}: {over.size} differs from {size}')
    k = args.width / size[0]
    out_size = (args.width, round(size[1] * k))
    os.makedirs(args.out, exist_ok=True)
    under.resize(out_size, Image.LANCZOS).save(os.path.join(args.out, 'under.png'), optimize=True)
    over.resize(out_size, Image.LANCZOS).save(os.path.join(args.out, 'over.png'), optimize=True)
    needle = Image.open(args.needle).convert('RGBA')
    needle.save(os.path.join(args.out, 'needle.png'), optimize=True)
    px, py = args.needle_pivot
    r = lambda v: round(v * k, 2)
    skin = {
        'name': {'en': args.name_en, 'it': args.name_it},
        'order': args.order,
        'size': list(out_size),
        'under': 'under.png',
        'over': 'over.png',
        'needle': {'image': 'needle.png', 'width': r(needle.size[0]), 'height': r(needle.size[1]),
                   'pivotX': r(px), 'pivotY': r(py)},
        'meters': [[r(x), r(y)] for x, y in args.meter],
        'angles': list(args.angles),
    }
    with open(os.path.join(args.out, 'skin.json'), 'w', encoding='utf-8') as f:
        json.dump(skin, f, indent=2, ensure_ascii=False)
        f.write('\n')
    for n in ('under.png', 'over.png', 'needle.png', 'skin.json'):
        print(f'{n:11s} {os.path.getsize(os.path.join(args.out, n)) // 1024} KiB')


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
    b.add_argument('--over', required=True)
    b.add_argument('--needle', required=True)
    b.add_argument('--needle-pivot', type=pair, required=True, help='rotation centre inside needle.png')
    b.add_argument('--meter', type=pair, action='append', required=True, help='pivot of each dial, left first')
    b.add_argument('--angles', type=pair, required=True, help='needle angle at level 0 and at level 100')
    b.add_argument('--width', type=int, default=2048)
    b.add_argument('--order', type=int, default=50)
    m = sub.add_parser('measure')
    m.add_argument('dials')
    m.add_argument('--range', type=pair, action='append', required=True, help='x span of one dial')
    args = p.parse_args()
    build(args) if args.cmd == 'build' else measure(args)


if __name__ == '__main__':
    main()
