#!/usr/bin/env python3
"""Art for the Now Playing animation "CD changer" (qml/AnimChanger.qml).

A late-90s champagne file-type CD changer seen from the front: the window
shows the discs standing in the rotating file, the loader lifts one up into
the drive. The albums view "CD changer" (ChangerView.qml) shows it too.

    python3 native-ui-qt/tools/np-anim/changer.py [--out DIR]

DIR defaults to native-ui-qt/assets/anim/changer/. Needs Pillow and numpy
and the DejaVu fonts. Geometry is in design units (the scene's stage is
600 x 260); AnimChanger.qml mirrors the constants below. Deterministic:
same input, same bytes.
"""
import argparse
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, '..', '..', 'assets', 'anim', 'changer'))
SS = 6            # drawing pixels per unit (supersampled)
K = 3             # output pixels per unit
W, H = 600, 260
SANS = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
SANSB = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
SERIF = '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf'

# ── geometry (units) ──────────────────────────────────────────────────────
BODY = (10, 8, 591, 243.5)
SPLIT_Y = 198.5                      # the lower strip of the face
RECESS = (112, 20.5, 354, 195.5)     # the window's sunken frame
GLASS = (127, 25.5, 344, 187.5)      # the hole: the mechanism shows here
GLASS_R = 5
# the drive's window, top right: the disc brought from the file onto the
# laser lens and turning, seen straight from above like the top-loading CD
# scene (whose disc pictures, assets/anim/cd/, it uses)
DRIVE_RECESS = (360, 13, 582, 133)
DRIVE_GLASS = (366, 18, 576, 128)
DRIVE_R = 4
DRIVE_C = (471, 73)                  # the spindle
DRIVE_DISC = 100                     # the disc's diameter there
VFD = (366, 136, 576, 176)
FEET = [(73.5, 131), (471, 523.5)]
FOOT_Y = (238, 249.5)

# 🚨 Drawn for a screen, not to the real thing's scale: in the Now Playing
# panel the whole front is ~560 px wide, so the keys are few and large and
# the lettering is 3.5-6 units tall (the real one's would be 2-3 px).
KEYS = {
    'power': (31, 120, 81, 142),
    'random': (366, 180, 414, 197), 'repeat': (418, 180, 466, 197),
    'discm': (470, 180, 521, 197), 'discp': (525, 180, 576, 197),
    'eject': (112, 204, 176, 238), 'unload': (180, 204, 244, 238),
    'play': (256, 204, 322, 238), 'stop': (326, 204, 372, 238),
    'prev': (376, 204, 422, 238), 'next': (426, 204, 472, 238),
}
KNOB = (563, 218)
KNOB_R = 9
JACK = (535, 218)
PHONES_BOX = (482, 204.5, 584, 240.5)

# the window's insides
LOADER_X = 255.5                     # the loader's column (the LEDs)
LEDS = [(LOADER_X, 116), (LOADER_X, 123.5), (LOADER_X, 131.5)]
DISC_D = 128                         # disc diameter in units
VFD_COL = (196, 236, 255)

# the display cells (glyph pictures one unit larger all round, for the glow)
CELL_W, CELL_H, CELL_Y = 11, 19, 145


def font(path, size):
    return ImageFont.truetype(path, max(1, round(size * SS)))


def px(v):
    return round(v * SS)


def box(b):
    return [px(b[0]), px(b[1]), px(b[2]), px(b[3])]


def canvas(w=W, h=H):
    return Image.new('RGBA', (px(w), px(h)), (0, 0, 0, 0))


def finish(img, k=K, w=None, h=None):
    w = w or img.width * k // SS
    h = h or img.height * k // SS
    return img.resize((w, h), Image.LANCZOS)


def save(img, name):
    img.save(os.path.join(OUT, name), optimize=True)


def shape_mask(size, b, r):
    m = Image.new('L', size, 0)
    ImageDraw.Draw(m).rounded_rectangle(box(b), px(r), fill=255)
    return m


def vgrad(w, h, top, bottom, mid=None):
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    top = np.array(top, np.float32)
    bottom = np.array(bottom, np.float32)
    if mid is None:
        a = top + (bottom - top) * t
    else:
        mid = np.array(mid, np.float32)
        a = np.where(t < 0.5, top + (mid - top) * t * 2, mid + (bottom - mid) * (t - 0.5) * 2)
    return np.broadcast_to(a, (h, w, len(top))).copy()


def brushed(w, h, seed, amp, streak=500):
    """Horizontal brushing: noise smeared along x."""
    rng = np.random.default_rng(seed)
    n = rng.normal(0, 1, (h, w + streak)).astype(np.float32)
    c = np.cumsum(n, axis=1)
    n = (c[:, streak:] - c[:, :-streak]) / math.sqrt(streak)
    n += rng.normal(0, 0.8, (h, 1)).astype(np.float32)
    n += rng.normal(0, 0.35, (h, w)).astype(np.float32)
    return n * amp


def paste_rgb(img, arr, mask):
    layer = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), 'RGB').convert('RGBA')
    img.paste(layer, (0, 0), mask)


def blur_shadow(img, b, r, blur, alpha, dx=0, dy=0, colour=(0, 0, 0)):
    m = Image.new('L', img.size, 0)
    ImageDraw.Draw(m).rounded_rectangle(box((b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy)), px(r), fill=alpha)
    m = m.filter(ImageFilter.GaussianBlur(px(blur)))
    sh = Image.new('RGBA', img.size, colour + (0,))
    sh.putalpha(m)
    img.alpha_composite(sh)


def text_layer(s, size, fill, path=SANS, spacing=0.0, italic=0.0):
    f = font(path, size)
    widths = [f.getlength(ch) for ch in s]
    w = int(sum(widths) + px(spacing) * max(0, len(s) - 1) + px(size) * 2)
    h = int(px(size) * 2.2)
    lay = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    x = px(size)
    for ch, cw in zip(s, widths):
        d.text((x, h * 0.5), ch, font=f, fill=fill, anchor='lm')
        x += cw + px(spacing)
    if italic:
        lay = lay.transform(lay.size, Image.AFFINE, (1, italic, -italic * h * 0.5, 0, 1, 0), Image.BICUBIC)
    bb = lay.getbbox()
    return lay.crop(bb) if bb else lay


def place(img, lay, x, y, anchor='mm'):
    """x, y in units; anchor: l/m/r + t/m/b"""
    w, h = lay.size
    X = px(x) - (0 if anchor[0] == 'l' else w // 2 if anchor[0] == 'm' else w)
    Y = px(y) - (0 if anchor[1] == 't' else h // 2 if anchor[1] == 'm' else h)
    img.alpha_composite(lay, (int(X), int(Y)))


def text(img, s, x, y, size, fill, anchor='mm', **kw):
    place(img, text_layer(s, size, fill, **kw), x, y, anchor)


INK = (62, 59, 55, 255)
INK_SOFT = (88, 84, 78, 255)


# ── the front ─────────────────────────────────────────────────────────────
def keycap(img, b, r=1.4, label=None, lsize=2.15, sym=None, symk=1.0):
    blur_shadow(img, b, r, 0.7, 150, dy=0.7)
    blur_shadow(img, b, r, 0.25, 160, dy=0.25)
    w, h = img.size
    m = shape_mask(img.size, b, r)
    g = vgrad(w, 1, (0, 0, 0), (0, 0, 0))  # placeholder shape
    y0, y1 = px(b[1]), px(b[3])
    arr = np.zeros((h, w, 3), np.float32)
    cap = vgrad(w, y1 - y0, (226, 222, 212), (182, 177, 166), mid=(210, 205, 194))
    arr[y0:y1] = cap
    arr[y0:y1] += brushed(w, y1 - y0, int(b[0] * 7 + b[1]), 1.6, 120)[..., None]
    paste_rgb(img, arr, m)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box(b), px(r), outline=(118, 113, 104, 255), width=max(1, px(0.22)))
    d.line([px(b[0] + r), px(b[1] + 0.35), px(b[2] - r), px(b[1] + 0.35)], fill=(246, 243, 236, 200), width=px(0.25))
    d.line([px(b[0] + r), px(b[3] - 0.4), px(b[2] - r), px(b[3] - 0.4)], fill=(140, 134, 124, 200), width=px(0.3))
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    if label:
        lines = label.split('\n')
        for i, ln in enumerate(lines):
            text(img, ln, cx, cy + (i - (len(lines) - 1) / 2) * lsize * 1.05, lsize, INK, path=SANSB, spacing=0.1)
    if sym:
        draw_symbol(img, sym, cx, cy, symk)


def draw_symbol(img, sym, cx, cy, k=1.0):
    d = ImageDraw.Draw(img)
    c = (48, 46, 43, 255)

    def tri(x, y, s, right=True):
        x, y, s = cx + (x - cx) * k, cy + (y - cy) * k, s * k
        if right:
            pts = [(x - s * 0.45, y - s * 0.55), (x - s * 0.45, y + s * 0.55), (x + s * 0.55, y)]
        else:
            pts = [(x + s * 0.45, y - s * 0.55), (x + s * 0.45, y + s * 0.55), (x - s * 0.55, y)]
        d.polygon([(px(a), px(b)) for a, b in pts], fill=c)

    def bar(x, y, wd, ht):
        x, y, wd, ht = cx + (x - cx) * k, cy + (y - cy) * k, wd * k, ht * k
        d.rectangle([px(x - wd / 2), px(y - ht / 2), px(x + wd / 2), px(y + ht / 2)], fill=c)

    if sym == 'playpause':
        tri(cx - 3.2, cy, 3.6)
        d.line([px(cx - 0.6 * k), px(cy + 2.0 * k), px(cx + 0.6 * k), px(cy - 2.0 * k)], fill=c, width=px(0.35 * k))
        bar(cx + 2.1, cy, 0.8, 3.4)
        bar(cx + 3.6, cy, 0.8, 3.4)
    elif sym == 'stop':
        bar(cx, cy, 3.1, 3.1)
    elif sym == 'prev':
        bar(cx - 3.3, cy, 0.6, 3.0)
        tri(cx - 1.4, cy, 2.8, right=False)
        tri(cx + 1.3, cy, 2.8, right=False)
    elif sym == 'next':
        tri(cx - 1.3, cy, 2.8)
        tri(cx + 1.4, cy, 2.8)
        bar(cx + 3.3, cy, 0.6, 3.0)


def recess(img, b, r, depth_top=4.0):
    """A sunken frame lit from above: its top inner wall in shade."""
    d = ImageDraw.Draw(img)
    w, h = img.size
    m = shape_mask(img.size, b, r)
    y0, y1 = px(b[1]), px(b[3])
    arr = np.zeros((h, w, 3), np.float32)
    arr[y0:y1] = vgrad(w, y1 - y0, (176, 171, 160), (204, 199, 188))
    arr[y0:y1] += brushed(w, y1 - y0, 77, 2.0)[..., None]
    paste_rgb(img, arr, m)
    # shade under the top edge
    sh = Image.new('L', img.size, 0)
    ImageDraw.Draw(sh).rectangle(box((b[0], b[1] - 3, b[2], b[1] + depth_top)), fill=140)
    sh = sh.filter(ImageFilter.GaussianBlur(px(1.6)))
    sh = Image.fromarray((np.array(sh, np.float32) * (np.array(m, np.float32) / 255)).astype(np.uint8))
    lay = Image.new('RGBA', img.size, (30, 26, 20, 0))
    lay.putalpha(sh)
    img.alpha_composite(lay)
    d.rounded_rectangle(box(b), px(r), outline=(150, 144, 133, 255), width=px(0.3))
    d.line([px(b[0] + r), px(b[1] + 0.2), px(b[2] - r), px(b[1] + 0.2)], fill=(110, 104, 95, 255), width=px(0.45))
    d.line([px(b[0] + r), px(b[3] + 0.3), px(b[2] - r), px(b[3] + 0.3)], fill=(236, 232, 224, 255), width=px(0.4))


def base():
    img = canvas()
    w, h = img.size
    # contact shadow under the feet and the body
    blur_shadow(img, (20, 241, 581, 252), 4, 3.0, 120)
    for x0, x1 in FEET:
        blur_shadow(img, (x0 - 2, 248, x1 + 2, 252), 2, 1.2, 150)
        fb = (x0, FOOT_Y[0], x1, FOOT_Y[1])
        m = shape_mask(img.size, fb, 2.5)
        arr = np.zeros((h, w, 3), np.float32)
        t = np.linspace(0, 1, px(x1) - px(x0), dtype=np.float32)
        prof = 0.55 + 0.45 * np.abs(np.sin(np.pi * np.clip(t * 1.1 - 0.05, 0, 1))) ** 0.7
        arr[:, px(x0):px(x1)] = (np.array([150, 147, 142], np.float32)[None, :] * prof[:, None])[None, :, :]
        arr[px(FOOT_Y[0]):px(FOOT_Y[0] + 3)] *= 0.55
        paste_rgb(img, arr, m)
    # the body
    m = shape_mask(img.size, BODY, 2.5)
    arr = np.zeros((h, w, 3), np.float32)
    top, split, bot = px(BODY[1]), px(SPLIT_Y), px(BODY[3])
    arr[top:split] = vgrad(w, split - top, (208, 202, 189), (190, 184, 171), mid=(201, 195, 182))
    arr[split:bot] = vgrad(w, bot - split, (194, 188, 175), (172, 166, 154))
    arr += brushed(w, h, 11, 2.4)[..., None]
    # light falling off to the left and right ends
    xs = np.linspace(-1, 1, w, dtype=np.float32)
    arr *= (1 - 0.05 * xs ** 2)[None, :, None]
    paste_rgb(img, arr, m)
    d = ImageDraw.Draw(img)
    # the top edge (the lid's front lip) and the bottom edge
    d.rectangle(box((BODY[0] + 1.5, BODY[1], BODY[2] - 1.5, BODY[1] + 0.6)), fill=(232, 228, 219, 255))
    d.rectangle(box((BODY[0] + 1.5, BODY[1] + 2.2, BODY[2] - 1.5, BODY[1] + 2.6)), fill=(168, 162, 151, 160))
    d.rectangle(box((BODY[0] + 1.5, BODY[3] - 0.8, BODY[2] - 1.5, BODY[3])), fill=(120, 114, 104, 255))
    d.rounded_rectangle(box(BODY), px(2.5), outline=(130, 124, 114, 255), width=px(0.3))
    # the groove between the face and the lower strip
    d.line([px(BODY[0] + 0.6), px(SPLIT_Y), px(BODY[2] - 0.6), px(SPLIT_Y)], fill=(122, 117, 107, 255), width=px(0.45))
    d.line([px(BODY[0] + 0.6), px(SPLIT_Y + 0.55), px(BODY[2] - 0.6), px(SPLIT_Y + 0.55)], fill=(226, 222, 213, 255), width=px(0.3))

    # the window
    recess(img, RECESS, 3.5)
    blur_shadow(img, GLASS, GLASS_R + 1, 1.2, 180, dy=0.4)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box((GLASS[0] - 1.1, GLASS[1] - 1.1, GLASS[2] + 1.1, GLASS[3] + 1.1)), px(GLASS_R + 1), fill=(22, 21, 20, 255))
    # the drive's window, the same kind of frame
    recess(img, DRIVE_RECESS, 3.5, depth_top=3.0)
    blur_shadow(img, DRIVE_GLASS, DRIVE_R + 1, 1.2, 180, dy=0.4)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box((DRIVE_GLASS[0] - 1.1, DRIVE_GLASS[1] - 1.1, DRIVE_GLASS[2] + 1.1, DRIVE_GLASS[3] + 1.1)),
                        px(DRIVE_R + 1), fill=(22, 21, 20, 255))
    for g, r in ((GLASS, GLASS_R), (DRIVE_GLASS, DRIVE_R)):
        hole = shape_mask(img.size, g, r)
        a = np.array(img.getchannel('A'))
        # the holes: the windows' own pictures draw there
        img.putalpha(Image.fromarray(np.minimum(a, 255 - np.array(hole)).astype(np.uint8)))

    # the display window
    blur_shadow(img, VFD, 1.5, 0.8, 150, dy=-0.3)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box((VFD[0] - 0.9, VFD[1] - 0.9, VFD[2] + 0.9, VFD[3] + 0.9)), px(2.2), fill=(150, 145, 135, 255))
    m = shape_mask(img.size, VFD, 1.5)
    arr = np.zeros((h, w, 3), np.float32)
    arr[px(VFD[1]):px(VFD[3])] = vgrad(w, px(VFD[3]) - px(VFD[1]), (26, 28, 31), (8, 9, 11))
    paste_rgb(img, arr, m)
    d = ImageDraw.Draw(img)
    d.line([px(VFD[0] + 2), px(VFD[1] + 0.5), px(VFD[2] - 2), px(VFD[1] + 0.5)], fill=(70, 74, 80, 255), width=px(0.3))
    d.line([px(VFD[0] + 1), px(VFD[3] + 0.6), px(VFD[2] - 1), px(VFD[3] + 0.6)], fill=(228, 224, 215, 255), width=px(0.3))
    # the reflection across the display glass
    refl = Image.new('L', img.size, 0)
    ImageDraw.Draw(refl).polygon([(px(VFD[0] + 30), px(VFD[1])), (px(VFD[0] + 62), px(VFD[1])),
                                  (px(VFD[0] + 40), px(VFD[3])), (px(VFD[0] + 8), px(VFD[3]))], fill=16)
    refl = Image.fromarray((np.array(refl, np.float32) * np.array(m, np.float32) / 255).astype(np.uint8))
    lay = Image.new('RGBA', img.size, (255, 255, 255, 0))
    lay.putalpha(refl.filter(ImageFilter.GaussianBlur(px(3))))
    img.alpha_composite(lay)

    # the name and the printing
    text(img, 'OSMIUM', 31, 31, 12, (40, 38, 36, 255), anchor='lm', path=SANSB, spacing=0.3, italic=0.22)
    text(img, 'FILE-TYPE', 31, 48, 5.0, INK, anchor='lm', path=SANSB, spacing=0.2)
    text(img, 'COMPACT DISC PLAYER', 31, 55.5, 5.0, INK, anchor='lm', path=SANSB, spacing=0.1)
    text(img, 'OS-F101', 31, 67, 7.0, INK, anchor='lm', path=SERIF, spacing=0.3)
    text(img, 'STANDBY', 56, 97.5, 5.6, INK, path=SANSB, spacing=0.2)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box((35.5, 104, 76.5, 109)), px(0.8), fill=(70, 66, 60, 255))
    d.rounded_rectangle(box((36.3, 104.7, 75.7, 108.3)), px(0.5), fill=(32, 20, 18, 255))
    # power symbol + STANDBY/ON
    cx, cy, rr = 34, 114.5, 2.6
    d.arc(box((cx - rr, cy - rr, cx + rr, cy + rr)), -60, 240, fill=INK, width=px(0.7))
    d.line([px(cx), px(cy - rr - 0.6), px(cx), px(cy)], fill=INK, width=px(0.7))
    text(img, 'ON', 39, 114.5, 5.6, INK, anchor='lm', path=SANSB, spacing=0.2)
    labels = {'power': None, 'random': 'RANDOM', 'repeat': 'REPEAT', 'discm': 'DISC \u2212', 'discp': 'DISC +',
              'eject': 'OPEN/CLOSE', 'unload': 'UNLOAD'}
    syms = {'play': 'playpause', 'stop': 'stop', 'prev': 'prev', 'next': 'next'}
    for k, b in KEYS.items():
        size = 6.3 if k in ('random', 'repeat', 'discm', 'discp') else 6.5
        keycap(img, b, label=labels.get(k), lsize=size, sym=syms.get(k), symk=2.2)

    # the headphone box
    d = ImageDraw.Draw(img)
    pb = PHONES_BOX
    d.rounded_rectangle(box(pb), px(1.6), outline=(118, 113, 104, 255), width=px(0.35))
    d.rounded_rectangle(box((pb[0] + 0.3, pb[1] + 0.3, pb[2] + 0.3, pb[3] + 0.3)), px(1.6), outline=(226, 222, 213, 140), width=px(0.25))
    text(img, '1-BIT', pb[0] + 5, 215.5, 7, (44, 42, 39, 255), anchor='lm', path=SANSB, italic=0.22)
    text(img, 'DAC', pb[0] + 5, 229.5, 7, (44, 42, 39, 255), anchor='lm', path=SANSB, italic=0.22)
    d = ImageDraw.Draw(img)
    d.line([px(JACK[0] + 8), px(KNOB[1]), px(KNOB[0] - 13), px(KNOB[1])], fill=(110, 105, 96, 255), width=px(0.4))
    text(img, 'PHONES', JACK[0], 234.8, 4.6, INK, path=SANSB, spacing=0.1)
    text(img, 'LEVEL', KNOB[0], 234.8, 4.6, INK, path=SANSB, spacing=0.1)
    # the jack
    jx, jy = JACK
    d.ellipse(box((jx - 5.4, jy - 5.4, jx + 5.4, jy + 5.4)), fill=(96, 92, 86, 255))
    m = Image.new('L', img.size, 0)
    ImageDraw.Draw(m).ellipse(box((jx - 4.8, jy - 4.8, jx + 4.8, jy + 4.8)), fill=255)
    arr = np.zeros((h, w, 3), np.float32)
    arr[px(jy - 4.8):px(jy + 4.8)] = vgrad(w, px(jy + 4.8) - px(jy - 4.8), (236, 233, 226), (130, 126, 118))
    paste_rgb(img, arr, m)
    d = ImageDraw.Draw(img)
    d.ellipse(box((jx - 2.6, jy - 2.6, jx + 2.6, jy + 2.6)), fill=(60, 58, 54, 255))
    d.ellipse(box((jx - 1.9, jy - 1.9, jx + 1.9, jy + 1.9)), fill=(8, 8, 8, 255))
    # the knob's collar and shadow (the knob itself turns: knob.png)
    kx, ky = KNOB
    blur_shadow(img, (kx - KNOB_R, ky - KNOB_R + 1.2, kx + KNOB_R, ky + KNOB_R + 1.2), KNOB_R, 1.0, 170)
    d.ellipse(box((kx - KNOB_R - 0.9, ky - KNOB_R - 0.9, kx + KNOB_R + 0.9, ky + KNOB_R + 0.9)), fill=(136, 131, 122, 255))
    # scale ticks around the knob
    for i in range(11):
        ang = math.radians(-135 + 27 * i - 90)
        r0, r1 = KNOB_R + 1.4, KNOB_R + (2.6 if i in (0, 10) else 2.0)
        d.line([px(kx + r0 * math.cos(ang)), px(ky + r0 * math.sin(ang)),
                px(kx + r1 * math.cos(ang)), px(ky + r1 * math.sin(ang))], fill=INK_SOFT, width=px(0.3))
    save(finish(img), 'base.png')


def knob():
    s = 2 * (KNOB_R + 0.4)
    img = canvas(s, s)
    w, h = img.size
    c = s / 2
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dx, dy = xx / SS - c, yy / SS - c
    r = np.hypot(dx, dy)
    ang = np.arctan2(dy, dx)
    # a knurled skirt and a brushed (spun) cap
    skirt = (r > KNOB_R * 0.80)
    knurl = 0.5 + 0.5 * np.cos(ang * 48)
    spun = np.sin(r * 9.0) * 0.5 + np.cos(ang * 2 + 0.6) * 0.5     # the turned finish catches the light
    lum = np.where(skirt, 150 + 50 * knurl * (0.6 - dy / KNOB_R * 0.4),
                   188 + 16 * spun - 22 * dy / KNOB_R + 10 * (dx / KNOB_R))
    rgb = np.stack([lum * 1.02, lum, lum * 0.95], -1)
    a = np.clip((KNOB_R - r) * SS, 0, 1) * 255
    arr = np.dstack([np.clip(rgb, 0, 255), a]).astype(np.uint8)
    img = Image.fromarray(arr, 'RGBA')
    d = ImageDraw.Draw(img)
    d.line([px(c), px(c - KNOB_R * 0.78), px(c), px(c - KNOB_R * 0.30)], fill=(40, 38, 35, 255), width=px(0.55))
    save(finish(img, k=8), 'knob.png')


def standby_led():
    b = (36.3, 104.7, 75.7, 108.3)
    img = canvas(50, 12)
    ox, oy = 31, 100.5
    g = Image.new('L', img.size, 0)
    ImageDraw.Draw(g).rounded_rectangle(box((b[0] - ox, b[1] - oy, b[2] - ox, b[3] - oy)), px(0.4), fill=255)
    glow = g.filter(ImageFilter.GaussianBlur(px(1.4)))
    lay = Image.new('RGBA', img.size, (255, 40, 30, 0))
    lay.putalpha(glow.point(lambda v: int(v * 0.55)))
    img.alpha_composite(lay)
    core = Image.new('RGBA', img.size, (255, 70, 55, 0))
    core.putalpha(g)
    img.alpha_composite(core)
    hot = Image.new('L', img.size, 0)
    ImageDraw.Draw(hot).rounded_rectangle(box((b[0] - ox + 1, b[1] - oy + 0.6, b[2] - ox - 1, b[3] - oy - 0.6)), px(0.3), fill=150)
    lay = Image.new('RGBA', img.size, (255, 190, 170, 0))
    lay.putalpha(hot.filter(ImageFilter.GaussianBlur(px(0.4))))
    img.alpha_composite(lay)
    save(finish(img), 'led-standby.png')


# ── the window: insides, lip, glass ───────────────────────────────────────
def interior():
    gw, gh = GLASS[2] - GLASS[0], GLASS[3] - GLASS[1]
    img = canvas(gw, gh)
    w, h = img.size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    u, v = xx / SS, yy / SS
    lx = LOADER_X - GLASS[0]
    # the back of the cabinet, a little light from the loader
    base = 9 + 10 * np.exp(-((u - lx) ** 2) / (2 * 40 ** 2)) * np.exp(-((v - 95) ** 2) / (2 * 50 ** 2))
    rgb = np.stack([base * 1.05, base, base * 0.95], -1)
    arr = np.dstack([rgb, np.full((h, w), 255, np.float32)])
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), 'RGBA')
    d = ImageDraw.Draw(img)
    # the drive up top: a dark housing with a slot the disc goes into
    d.rectangle(box((lx - 72, 0, lx + 58, 15)), fill=(24, 24, 25, 255))
    d.rectangle(box((lx - 72, 15, lx + 58, 16.2)), fill=(44, 44, 46, 255))
    d.rectangle(box((lx - 3.2, 12, lx + 3.2, 16.2)), fill=(4, 4, 4, 255))
    for x in (lx - 60, lx + 46):
        d.ellipse(box((x - 1.6, 6, x + 1.6, 9.2)), fill=(58, 58, 60, 255))
    # the loader's column: two rails behind the discs
    for x in (lx - 5.0, lx + 5.0):
        d.rectangle(box((x - 0.8, 16, x + 0.8, gh)), fill=(30, 30, 32, 255))
        d.rectangle(box((x - 0.8, 16, x - 0.4, gh)), fill=(52, 52, 55, 255))
    # the far side of the file: the discs' tops beyond the turntable hub
    for i in range(-22, 23):
        x = gw / 2 + i * 5.6 + 1.3
        d.line([px(x), px(36), px(x), px(42)], fill=(20, 20, 22, 255), width=px(0.9))
    d.rectangle(box((0, 41, gw, 44.5)), fill=(14, 14, 15, 255))
    save(finish(img), 'interior.png')


def led_glow():
    s = 64
    img = canvas(s, s)
    w, h = img.size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    u, v = xx / SS - s / 2, yy / SS - s / 2
    a = np.zeros((h, w), np.float32)
    for (lx, ly) in LEDS:
        dx, dy = u - (lx - LOADER_X), v - (ly - LEDS[1][1])
        r = np.hypot(dx, dy)
        a += 0.55 * np.exp(-r ** 2 / (2 * 6.5 ** 2)) + 0.25 * np.exp(-r ** 2 / (2 * 16 ** 2))
        # the starburst the photographs of the real thing show
        ang = np.arctan2(dy, dx)
        a += 0.22 * np.exp(-r / 9) * np.abs(np.cos(ang * 4)) ** 24
    a = np.clip(a, 0, 1)
    rgb = np.stack([np.full_like(a, 238), np.full_like(a, 226), np.full_like(a, 96)], -1)
    arr = np.dstack([rgb, a * 255])
    save(finish(Image.fromarray(arr.astype(np.uint8), 'RGBA')), 'led-glow.png')


def led_dots():
    s = 8
    gh = 26
    img = canvas(s, gh)
    w, h = img.size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    u, v = xx / SS - s / 2, yy / SS
    a = np.zeros((h, w), np.float32)
    core = np.zeros((h, w), np.float32)
    for (lx, ly) in LEDS:
        r = np.hypot(u, v - (ly - LEDS[0][1] + 5))
        a += np.exp(-r ** 2 / (2 * 1.3 ** 2))
        core += np.clip((0.8 - r) * SS * 0.5, 0, 1)
    a = np.clip(a, 0, 1)
    rgb = np.stack([235 + 20 * core, 228 + 27 * core, 70 + 150 * core], -1)
    arr = np.dstack([np.clip(rgb, 0, 255), np.clip(a + core, 0, 1) * 255])
    save(finish(Image.fromarray(arr.astype(np.uint8), 'RGBA')), 'led-dots.png')


def lip():
    """The turntable's front rim, across the bottom of the window: the discs
    stand in it."""
    gw = GLASS[2] - GLASS[0]
    y0 = 140                          # the picture spans y 140..162 of the window
    hh = GLASS[3] - GLASS[1] - y0
    img = canvas(gw, hh)
    w, h = img.size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    u, v = xx / SS, yy / SS + y0
    t = (u - gw / 2) / (gw / 2)
    edge = 151.0 - 3.2 * t ** 2       # the rim's top curves away at the sides
    inside = v > edge
    lum = 24 + 18 * np.exp(-(v - edge) / 1.2) * inside + 6 * (1 - t ** 2)
    rgb = np.stack([lum, lum, lum * 1.04], -1)
    a = np.clip((v - edge) * SS * 0.7, 0, 1) * 255
    # a soft dark band above the rim: the discs' feet in the shade of the slots
    shade = np.clip(1 - (edge - v) / 7, 0, 1) * (v <= edge) * 150
    a = np.maximum(a, shade)
    rgb = np.where(inside[..., None], rgb, 0)
    # slot numbers every ten discs, printed on the rim
    arr = np.dstack([np.clip(rgb, 0, 255), a]).astype(np.uint8)
    img = Image.fromarray(arr, 'RGBA')
    save(finish(img), 'lip.png')


def glass():
    gw, gh = GLASS[2] - GLASS[0], GLASS[3] - GLASS[1]
    img = canvas(gw, gh)
    w, h = img.size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    u, v = xx / SS, yy / SS
    t = (u - gw / 2) / (gw / 2)
    # smoked tint, darker to the sides and under the top edge
    a = 0.52 + 0.40 * np.abs(t) ** 2.0 + 0.35 * np.exp(-v / 9) + 0.20 * np.clip((v - 120) / 40, 0, 1)
    a = np.clip(a, 0, 0.94)
    rgb = np.zeros((h, w, 3), np.float32) + np.array([6, 6, 7], np.float32)
    # reflections of the room: a broad soft band and two thin streaks
    refl = 0.07 * np.exp(-((u + 0.55 * v - 70) ** 2) / (2 * 14 ** 2))
    refl += 0.05 * np.exp(-((u + 0.55 * v - 120) ** 2) / (2 * 2.2 ** 2))
    refl += 0.035 * np.exp(-((u + 0.55 * v - 196) ** 2) / (2 * 1.4 ** 2))
    refl += 0.10 * np.exp(-v / 1.6)                               # the lit top edge of the glass
    refl += 0.05 * np.exp(-(gh - v) / 2.5)
    rgb = rgb * (1 - refl[..., None] / np.maximum(a + refl, 1e-3)[..., None]) + 235 * (refl / np.maximum(a + refl, 1e-3))[..., None]
    a = np.clip(a + refl, 0, 1)
    m = np.array(shape_mask((w, h), (0, 0, gw, gh), GLASS_R), np.float32) / 255
    arr = np.dstack([np.clip(rgb, 0, 255), a * m * 255]).astype(np.uint8)
    img = Image.fromarray(arr, 'RGBA')
    text(img, 'FILE-TYPE CD MECHANISM', LOADER_X - GLASS[0] - 26, 133, 4.6, (150, 150, 150, 170), spacing=0.3)
    save(finish(img), 'glass.png')


# ── the drive's window ────────────────────────────────────────────────────
def drive_bg():
    """The drive seen straight from above: the chassis, the platter's well,
    the spindle and, on its rails, the laser sled with its lens."""
    gx, gy = DRIVE_GLASS[0], DRIVE_GLASS[1]
    gw, gh = DRIVE_GLASS[2] - gx, DRIVE_GLASS[3] - gy
    img = canvas(gw, gh)
    w, h = img.size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    u, v = xx / SS, yy / SS
    cx, cy = DRIVE_C[0] - gx, DRIVE_C[1] - gy
    R = DRIVE_DISC / 2 + 4
    rr = np.hypot(u - cx, v - cy)
    lum = 21 - 7 * (v / gh) + 7 * np.exp(-rr ** 2 / (2 * 80 ** 2))
    # the platter's well, a shade darker, its lower rim catching the light
    lum = np.where(rr < R, lum * 0.55, lum)
    ang = np.arctan2(v - cy, u - cx)
    lum = lum + 40 * np.exp(-((rr - R) ** 2) / (2 * 0.7 ** 2)) * np.clip(np.sin(ang), 0, 1)
    lum = lum - 8 * np.exp(-((rr - R) ** 2) / (2 * 0.7 ** 2)) * np.clip(-np.sin(ang), 0, 1)
    rgb = np.stack([lum * 1.02, lum, lum * 1.04], -1)
    img = Image.fromarray(np.dstack([np.clip(rgb, 0, 255), np.full((h, w), 255, np.float32)]).astype(np.uint8), 'RGBA')
    d = ImageDraw.Draw(img)
    # the sled's two rails, from the spindle out to the right
    for dy in (-11, 11):
        d.line([px(cx + 10), px(cy + dy), px(gw - 3), px(cy + dy)], fill=(112, 114, 118, 255), width=px(1.6))
        d.line([px(cx + 10), px(cy + dy - 0.55), px(gw - 3), px(cy + dy - 0.55)], fill=(196, 198, 202, 255), width=px(0.45))
    # the sled, under where the disc's music starts, and the lens on it
    sx, sy = cx + 30, cy
    blur_shadow(img, (sx - 11, sy - 13, sx + 11, sy + 13), 2, 1.2, 170, dy=1)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box((sx - 11, sy - 13, sx + 11, sy + 13)), px(2), fill=(46, 46, 49, 255))
    d.rounded_rectangle(box((sx - 11, sy - 13, sx + 11, sy - 10.5)), px(1.5), fill=(80, 80, 84, 255))
    d.ellipse(box((sx - 6.5, sy - 6.5, sx + 6.5, sy + 6.5)), fill=(14, 14, 18, 255))
    lr = np.hypot(u - sx, v - sy) / 5
    hl = np.exp(-((u - sx + 1.6) ** 2 + (v - sy + 1.6) ** 2) / 2.4)
    ln = np.dstack([60 + 110 * hl, 50 + 100 * hl, 140 + 110 * hl, np.clip((1 - lr) * SS * 0.5, 0, 1) * 255 * (lr < 1)])
    img.alpha_composite(Image.fromarray(np.clip(ln, 0, 255).astype(np.uint8), 'RGBA'))
    # the spindle: the turntable hub and its centring cone
    d = ImageDraw.Draw(img)
    d.ellipse(box((cx - 12, cy - 12 + 1, cx + 12, cy + 12 + 1)), fill=(30, 30, 32, 255))
    d.ellipse(box((cx - 12, cy - 12, cx + 12, cy + 12)), fill=(128, 130, 134, 255))
    d.ellipse(box((cx - 10, cy - 10, cx + 10, cy + 10)), fill=(94, 96, 100, 255))
    d.ellipse(box((cx - 4.5, cy - 4.5, cx + 4.5, cy + 4.5)), fill=(178, 180, 184, 255))
    d.ellipse(box((cx - 2, cy - 3, cx + 1, cy - 1)), fill=(230, 232, 236, 255))
    for a in (35, 145, 250):
        x, y = cx + (R + 7) * math.cos(math.radians(a)), cy + (R + 7) * math.sin(math.radians(a))
        if 4 < x < gw - 4 and 4 < y < gh - 4:
            d.ellipse(box((x - 1.6, y - 1.6, x + 1.6, y + 1.6)), fill=(66, 66, 70, 255))
    save(finish(img), 'drive-bg.png')


def drive_glass():
    gw, gh = DRIVE_GLASS[2] - DRIVE_GLASS[0], DRIVE_GLASS[3] - DRIVE_GLASS[1]
    img = canvas(gw, gh)
    w, h = img.size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    u, v = xx / SS, yy / SS
    t = (u - gw / 2) / (gw / 2)
    a = 0.16 + 0.22 * np.abs(t) ** 2.4 + 0.35 * np.exp(-v / 6)
    refl = 0.06 * np.exp(-((u + 0.6 * v - 60) ** 2) / (2 * 10 ** 2)) + 0.04 * np.exp(-((u + 0.6 * v - 150) ** 2) / (2 * 1.8 ** 2))
    refl += 0.10 * np.exp(-v / 1.4)
    tot = np.clip(a + refl, 0, 1)
    rgb = (np.array([6, 6, 7], np.float32) * (a / np.maximum(tot, 1e-3))[..., None]
           + 235 * (refl / np.maximum(tot, 1e-3))[..., None])
    m = np.array(shape_mask((w, h), (0, 0, gw, gh), DRIVE_R), np.float32) / 255
    save(finish(Image.fromarray(np.dstack([np.clip(rgb, 0, 255), tot * m * 255]).astype(np.uint8), 'RGBA')), 'drive-glass.png')


def drive_shadow():
    rx = ry = DRIVE_DISC / 2
    img = canvas(2 * rx + 16, 2 * ry + 16)
    m = Image.new('L', img.size, 0)
    ImageDraw.Draw(m).ellipse(box((8, 8, 8 + 2 * rx, 8 + 2 * ry)), fill=200)
    m = m.filter(ImageFilter.GaussianBlur(px(3)))
    lay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    lay.putalpha(m)
    save(finish(lay), 'drive-shadow.png')


# ── the discs ─────────────────────────────────────────────────────────────
DISC_PX = 320


def polar(n=DISC_PX * 2):
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    c = (n - 1) / 2
    dx, dy = (xx - c) / c, (yy - c) / c
    return np.hypot(dx, dy), np.arctan2(dy, dx), n


def hsv2rgb(hh, s, v):
    i = np.floor(hh * 6) % 6
    f = hh * 6 - np.floor(hh * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    r = np.choose(i.astype(int), [v, q, p, p, t, v])
    g = np.choose(i.astype(int), [t, v, v, q, p, p])
    b = np.choose(i.astype(int), [p, p, t, v, v, q])
    return np.stack([r, g, b], -1)


def hub(rgb, a, r, n):
    """The clear centre, the stacking ring, the hole and the clear rim."""
    aa = 1.5 / n
    clear = (r >= 0.125) & (r < 0.19)
    rgb[clear] = [150, 156, 162]
    a[clear] = 120
    ring = (r >= 0.155) & (r < 0.17)
    rgb[ring] = [182, 188, 194]
    a[ring] = 170
    rim = r >= 0.975
    rgb[rim] = [165, 170, 176]
    a[rim] = 120
    a[r < 0.125] = 0
    a[:] = a * np.clip((1.0 - r) / aa, 0, 1) * np.clip((r - 0.125) / aa, 0, 1)


def disc_data():
    r, th, n = polar()
    rgb = np.zeros((n, n, 3), np.float32)
    a = np.full((n, n), 255, np.float32)
    silver = 150 + 34 * np.cos(th * 2 + 0.7) ** 2
    rgb[:] = silver[..., None]
    # diffraction: two opposite wedges of rainbow whose colour runs with the radius
    wedge = np.exp(-(np.sin(th - 0.9) ** 2) / 0.06)
    rain = hsv2rgb((r * 1.7 + 0.15) % 1.0, 0.75, 1.0) * 255
    data = (r >= 0.38) & (r < 0.975)
    mix = (wedge * 0.42)[..., None]
    rgb = np.where(data[..., None], rgb * (1 - mix) + rain * mix, rgb)
    # the end of the music: an unrecorded band, a shade lighter
    rgb = np.where(((r >= 0.86) & (r < 0.975))[..., None], rgb * 0.92 + 18, rgb)
    lead = (r >= 0.19) & (r < 0.38)
    rgb[lead] = (rgb[lead] * 0.5 + np.array([214, 218, 224]) * 0.5)
    rgb[(r > 0.295) & (r < 0.305)] = [120, 126, 132]
    hub(rgb, a, r, n)
    out = Image.fromarray(np.dstack([np.clip(rgb, 0, 255), a]).astype(np.uint8), 'RGBA')
    save(out.resize((DISC_PX, DISC_PX), Image.LANCZOS), 'disc-data.png')


LABELS = [
    # base colour, accent, pattern
    ((236, 233, 226), (200, 30, 40), 'band'),
    ((22, 22, 24), (210, 170, 70), 'rings'),
    ((150, 20, 28), (240, 220, 200), 'rings'),
    ((28, 60, 140), (130, 190, 240), 'grad'),
    ((196, 200, 206), (20, 20, 20), 'wedge'),
    ((240, 160, 30), (250, 230, 120), 'rays'),
    ((30, 110, 70), (240, 240, 230), 'dot'),
    ((90, 40, 120), (220, 160, 230), 'rays'),
    ((60, 60, 64), (255, 120, 40), 'band'),
    ((210, 214, 220), (30, 30, 30), 'text'),
]


def disc_label(i, base_rgb, acc, kind):
    r, th, n = polar()
    rng = np.random.default_rng(100 + i)
    rgb = np.zeros((n, n, 3), np.float32) + np.array(base_rgb, np.float32)
    acc = np.array(acc, np.float32)
    if kind == 'band':
        m = (np.abs(np.sin(th) * r) < 0.16) & (r > 0.4)
        rgb[m] = acc
    elif kind == 'rings':
        for rr in (0.42, 0.62, 0.9):
            rgb[np.abs(r - rr) < 0.012] = acc
    elif kind == 'grad':
        t = np.clip((np.cos(th) * r + 1) / 2, 0, 1)[..., None]
        rgb = rgb * (1 - t) + acc * t
    elif kind == 'wedge':
        rgb[(np.cos(th - 2.2) > 0.75)] = acc
    elif kind == 'rays':
        rgb = np.where((np.cos(th * 9) > 0.55)[..., None], rgb * 0.5 + acc * 0.5, rgb)
    elif kind == 'dot':
        rgb[np.hypot(r * np.cos(th) - 0.35, r * np.sin(th) + 0.2) < 0.3] = acc
    # printed lines of text (titles, the track list) as bars
    img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), 'RGB')
    d = ImageDraw.Draw(img)
    ink = (20, 20, 20) if sum(base_rgb) > 400 else (235, 235, 235)
    c = n / 2
    for k in range(int(rng.integers(2, 6))):
        y = c + n * (0.22 + 0.05 * k) * (1 if k % 2 else -1) * (1 if rng.random() > 0.3 else 0.7)
        half = n * rng.uniform(0.08, 0.25)
        d.rectangle([c - half, y - n * 0.008, c + half, y + n * 0.008], fill=ink)
    if kind == 'text':
        for k in range(10):
            y = c + n * (0.05 + 0.03 * k)
            d.rectangle([c + n * 0.16, y - n * 0.005, c + n * rng.uniform(0.25, 0.36), y + n * 0.005], fill=ink)
    rgb = np.array(img, np.float32)
    # a little sheen: printing is matt but not dead
    rgb += (14 * np.cos(th * 2 - 0.4) ** 8)[..., None]
    a = np.full((n, n), 255, np.float32)
    hub(rgb, a, r, n)
    out = Image.fromarray(np.dstack([np.clip(rgb, 0, 255), a]).astype(np.uint8), 'RGBA')
    save(out.resize((DISC_PX, DISC_PX), Image.LANCZOS), f'disc-lbl-{i}.png')


def disc_mask_and_gloss():
    r, th, n = polar()
    aa = 1.5 / n
    print_a = np.clip((r - 0.19) / aa, 0, 1) * np.clip((0.975 - r) / aa, 0, 1)
    m = (print_a * 255).astype(np.uint8)
    out = Image.fromarray(np.dstack([m, m, m, m]), 'RGBA')
    save(out.resize((DISC_PX, DISC_PX), Image.LANCZOS), 'disc-mask.png')
    rgb = np.zeros((n, n, 3), np.float32) + 255
    a = 255 * 0.08 * np.cos(th * 2 - 0.4) ** 8 * (r < 0.975)
    a = a.astype(np.float32)
    hub(rgb, a, r, n)
    keep = (r < 0.19) | (r >= 0.975)
    sheen = 255 * 0.08 * np.cos(th * 2 - 0.4) ** 8
    a = np.where(keep, a, sheen * np.clip((r - 0.19) / aa, 0, 1))
    rgb = np.where(keep[..., None], rgb, 255)
    hubpart = np.zeros((n, n, 3), np.float32)
    hub_rgb = rgb.copy()
    out = Image.fromarray(np.dstack([np.clip(hub_rgb, 0, 255), np.clip(a, 0, 255)]).astype(np.uint8), 'RGBA')
    save(out.resize((DISC_PX, DISC_PX), Image.LANCZOS), 'disc-gloss.png')


# ── the fluorescent display ───────────────────────────────────────────────
SEGS = {
    '0': 'abcdef', '1': 'bc', '2': 'abdeg', '3': 'abcdg', '4': 'bcfg', '5': 'acdfg', '6': 'acdefg',
    '7': 'abc', 'O': 'abcdef', '8': 'abcdefg', '9': 'abcdfg', 'A': 'abcefg', 'b': 'cdefg', 'C': 'adef', 'c': 'deg',
    'd': 'bcdeg', 'E': 'adefg', 'F': 'aefg', 'H': 'bcefg', 'L': 'def', 'n': 'ceg', 'o': 'cdeg',
    'P': 'abefg', 'r': 'eg', 'S': 'acdfg', 't': 'defg', 'U': 'bcdef', 'u': 'cde', 'y': 'bcdfg', '-': 'g',
}


# what the display spells: the numbers, '-', "UnLd" and "LOAd" (O is the 0)
USED = '0123456789-UnLdLA'


def glyph_name(ch):
    if ch.isdigit():
        return ch
    if ch == '-':
        return 'dash'
    return ('u' if ch.isupper() else 'l') + ch.lower()


def lit(img_l, colour=VFD_COL, glow=0.55, glow_r=0.9):
    """A drawn mask lit like a VFD element: the core and its halo."""
    g = img_l.filter(ImageFilter.GaussianBlur(px(glow_r)))
    halo = Image.new('RGBA', img_l.size, colour + (0,))
    halo.putalpha(g.point(lambda v: int(v * glow)))
    core = Image.new('RGBA', img_l.size, tuple(min(255, int(c * 0.35 + 255 * 0.65)) for c in colour) + (0,))
    core.putalpha(img_l)
    out = Image.new('RGBA', img_l.size, (0, 0, 0, 0))
    out.alpha_composite(halo)
    out.alpha_composite(core)
    return out


def glyphs():
    w, h, t, gap = CELL_W, CELL_H, 1.6, 0.4
    for ch, segs in [(c, SEGS[c]) for c in USED]:
        m = Image.new('L', (px(w + 2), px(h + 2)), 0)
        d = ImageDraw.Draw(m)
        ox, oy = 1, 1

        def hseg(y):
            x0, x1 = ox + gap + t / 2, ox + w - gap - t / 2
            pts = [(x0, y), (x0 + t / 2, y - t / 2), (x1 - t / 2, y - t / 2), (x1, y), (x1 - t / 2, y + t / 2), (x0 + t / 2, y + t / 2)]
            d.polygon([(px(a), px(b)) for a, b in pts], fill=255)

        def vseg(x, y0, y1):
            y0, y1 = y0 + gap + t / 2, y1 - gap - t / 2
            pts = [(x, y0), (x + t / 2, y0 + t / 2), (x + t / 2, y1 - t / 2), (x, y1), (x - t / 2, y1 - t / 2), (x - t / 2, y0 + t / 2)]
            d.polygon([(px(a), px(b)) for a, b in pts], fill=255)

        top, mid, bot = oy + t / 2, oy + h / 2, oy + h - t / 2
        left, right = ox + t / 2, ox + w - t / 2
        for s in segs:
            if s == 'a': hseg(top)
            if s == 'g': hseg(mid)
            if s == 'd': hseg(bot)
            if s == 'f': vseg(left, top, mid)
            if s == 'b': vseg(right, top, mid)
            if s == 'e': vseg(left, mid, bot)
            if s == 'c': vseg(right, mid, bot)
        save(finish(lit(m), k=8), f'g-{glyph_name(ch)}.png')
    # the colon
    m = Image.new('L', (px(6), px(h + 2)), 0)
    d = ImageDraw.Draw(m)
    for y in (1 + h * 0.32, 1 + h * 0.70):
        d.ellipse(box((3 - 1.0, y - 1.0, 3 + 1.0, y + 1.0)), fill=255)
    save(finish(lit(m), k=8), 'g-colon.png')


def vfd_words():
    """The indicators that light one by one, each its own picture."""
    def word(name, s, size, bold=False):
        lay = text_layer(s, size, (255, 255, 255, 255), path=SANSB if bold else SANS, spacing=0.15)
        pad = px(1.2)
        m = Image.new('L', (lay.width + 2 * pad, lay.height + 2 * pad), 0)
        m.paste(lay.getchannel('A'), (pad, pad))
        save(finish(lit(m, glow=0.45, glow_r=0.6), k=8), name)
        return (m.width / SS, m.height / SS)

    sizes = {}
    sizes['ind-all'] = word('ind-all.png', 'ALL', 5, True)
    sizes['ind-one'] = word('ind-one.png', '1', 5.2, True)
    sizes['ind-repeat'] = word('ind-repeat.png', 'REPEAT', 5, True)
    sizes['ind-random'] = word('ind-random.png', 'RANDOM', 5, True)
    # play and pause
    m = Image.new('L', (px(8), px(8)), 0)
    ImageDraw.Draw(m).polygon([(px(1.8), px(1.4)), (px(1.8), px(6.6)), (px(6.4), px(4))], fill=255)
    save(finish(lit(m, glow=0.5, glow_r=0.6), k=8), 'ind-play.png')
    m = Image.new('L', (px(8), px(8)), 0)
    d = ImageDraw.Draw(m)
    d.rectangle(box((2.0, 1.4, 3.4, 6.6)), fill=255)
    d.rectangle(box((4.6, 1.4, 6.0, 6.6)), fill=255)
    save(finish(lit(m, glow=0.5, glow_r=0.6), k=8), 'ind-pause.png')
    return sizes


def vfd_panel():
    """What is always printed or lit on the display while it is on: the
    captions and the logo. Spans the whole display window."""
    vw, vh = VFD[2] - VFD[0], VFD[3] - VFD[1]
    m = Image.new('L', (px(vw), px(vh)), 0)
    d = ImageDraw.Draw(m)
    ox, oy = VFD[0], VFD[1]
    dim = Image.new('L', m.size, 0)

    def cap(s, x, y, size=4.6):
        lay = text_layer(s, size, (255, 255, 255, 255), spacing=0.2)
        a = lay.getchannel('A')
        dim.paste(Image.new('L', a.size, 185), (int(px(x - ox) - a.width / 2), int(px(y - oy) - a.height / 2)), a)

    cap('DISC', 427.7, 140.5)
    cap('TRACK', 473, 140.5)
    cap('MIN', 512.2, 140.5)
    cap('SEC', 543.6, 140.5)
    # the logo: a disc with a swoosh, "101-DISC" under it
    cx, cy = 378 - ox, 151 - oy
    d.ellipse(box((cx - 6, cy - 6, cx + 6, cy + 6)), outline=255, width=px(1.0))
    d.ellipse(box((cx - 1.5, cy - 1.5, cx + 1.5, cy + 1.5)), fill=255)
    d.arc(box((cx - 4, cy - 4, cx + 4, cy + 4)), 200, 320, fill=255, width=px(0.9))
    lay = text_layer('FILE', 6.4, (255, 255, 255, 255), path=SANSB, spacing=0.15, italic=0.18)
    m.paste(Image.new('L', lay.size, 255), (int(px(cx + 8)), int(px(cy - 1) - lay.height / 2)), lay.getchannel('A'))
    lay = text_layer('101-DISC', 4.0, (255, 255, 255, 255), path=SANSB, spacing=0.15)
    m.paste(Image.new('L', lay.size, 230), (int(px(cx - 6)), int(px(cy + 12.5) - lay.height / 2)), lay.getchannel('A'))
    out = lit(m)
    out.alpha_composite(lit(dim, colour=(150, 190, 215), glow=0.25, glow_r=0.5))
    save(finish(out), 'vfd-panel.png')


def main():
    global OUT
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', default=OUT)
    OUT = ap.parse_args().out
    os.makedirs(OUT, exist_ok=True)
    base()
    knob()
    standby_led()
    interior()
    led_glow()
    led_dots()
    lip()
    glass()
    drive_bg()
    drive_glass()
    drive_shadow()
    disc_data()
    for i, (b, a, k) in enumerate(LABELS):
        disc_label(i, b, a, k)
    disc_mask_and_gloss()
    glyphs()
    vfd_words()
    vfd_panel()


if __name__ == '__main__':
    main()
