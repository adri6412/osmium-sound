#!/usr/bin/env python3
"""Render the reflective grey-green LCD of the 90s front panels (LcdCd.qml).

A passive twisted-nematic LCD with no backlight: dark segments on a
grey-green ground. The segments float a hair above the rear polariser, so
each one casts a faint shadow down and to the right; the unlit segments stay
just visible. The glass in front of it carries a soft reflection.

    python3 native-ui-qt/tools/np-anim/lcd.py [--out DIR]
    python3 native-ui-qt/tools/np-anim/lcd.py --vfd [--out DIR]

DIR defaults to native-ui-qt/assets/anim/lcd/. With --vfd the same CD panel
(same files, same layout: LcdCd.qml shows either) is drawn as the blue-green
vacuum fluorescent display of the 80s/90s hi-fi players instead, into
assets/anim/vfd/ (no cassette panel): a smoked dark glass with the unlit
segments barely there and the filament wires across it, the lit segments
cyan with their glow painted in (nothing is blurred at run time). Everything is laid out in the
196 x 100 point panel of LcdCd.qml (the layout constants below are mirrored
there). The bottom row is the CD-Text line: sixteen 14-segment characters.

  lcd-bg.png        the panel: ground, vignette, every segment unlit
  lcd-glass.png     the reflection of the glass, drawn over the segments
  d-<c>.png         one lit 7-segment character (0-9, letters, '-'), with its
                    shadow, in a DIGIT box
  colon.png         the lit colon between minutes and seconds
  i-<name>.png      a lit indicator (play, pause, repeat, one, random, track,
                    min, sec, over, disc)
  cal-<n>.png       a lit number of the music calendar (1-16)
  t-<hex>.png       one lit 14-segment character of the CD-Text line (hex =
                    its code point: t-41.png is "A"), in a TEXT box
  tape-bg.png       the cassette deck's panel (160 x 58, LcdTape.qml): ground
                    and every segment unlit
  tape-meter.png    both level meter rows fully lit (the scene clips them)
  i-t-<name>.png    a lit indicator of the tape panel
  spin-<k>.png      the disc indicator with segment k (0-7) dark: turns while
                    playing; spin-all.png with every segment lit
"""
import argparse
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

W, H = 196, 100
PPT = 4.0                 # pixels per point: 4K-sharp at full screen
SS = 3

# ── layout (mirrored in LcdCd.qml) ─────────────────────────────────────────
DIGIT = (15.0, 28.0)      # w, h of a big character box
TRACK_X = (8.0, 26.0)     # x of the two track digits
TIME_X = (60.0, 78.0, 105.0, 123.0)
DIGIT_Y = 18.0
COLON = (97.5, DIGIT_Y)   # top left of the colon box (5 x 28)
SKEW = math.radians(7)
SPIN_C = (170.0, 32.0)
SPIN_R = (6.5, 12.5)      # inner / outer radius of the ring segments
CAL_X0, CAL_Y0 = 8.0, 60.0
CAL_DX, CAL_DY = 16.0, 12.0
CAL_BOX = (13.0, 9.5)
OVER = (137.0, 72.0)      # left, top of "OVER" next to the second calendar row
TEXT = (8.0, 12.0)        # w, h of a 14-segment character box
TEXT_X0, TEXT_Y = 8.0, 85.0
TEXT_DX = 11.25
TEXT_N = 16

SEG_ON = (0.075, 0.090, 0.070)
VFD = False               # --vfd: the fluorescent display instead of the LCD
VFD_CORE = (0.62, 1.00, 0.93)     # sRGB: the hot middle of a lit segment
VFD_EDGE = (0.22, 0.93, 0.82)     # ... its edge
VFD_GLOW = (0.10, 0.80, 0.70)     # ... and the halo round it
VFD_GLOW_A = 0.42
VFD_GHOST = (0.032, 0.074, 0.074)
SHADOW = (0.9, 1.1)        # points, down-right
GHOST_A = 0.075

FONT = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
FONT_R = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"

# indicators: name -> (text, x, y, size, bold); a leading ">" or "||" and a
# trailing ">" are drawn as shapes (the font has no such glyphs)
INDICATORS = {
    "track": ("TRACK", 8.0, 48.5, 5.2, True),
    "min": ("MIN", 64.0, 48.5, 5.2, True),
    "sec": ("SEC", 110.0, 48.5, 5.2, True),
    "play": ("> PLAY", 8.0, 4.0, 6.0, True),
    "pause": ("|| PAUSE", 40.0, 4.0, 6.0, True),
    "repeat": ("REPEAT", 86.0, 4.0, 6.0, True),
    "one": ("1", 112.5, 4.0, 6.0, True),
    "random": ("RANDOM", 121.0, 4.0, 6.0, True),
    "over": ("OVER >", OVER[0], OVER[1], 5.4, True),
}


# 7 segments: a b c d e f g
CHARS = {
    "0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd",
    "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg",
    "A": "abcefg", "b": "cdefg", "C": "adef", "c": "deg", "d": "bcdeg", "E": "adefg",
    "F": "aefg", "H": "bcefg", "I": "ef", "L": "def", "n": "ceg", "o": "cdeg",
    "O": "abcdef", "P": "abefg", "r": "eg", "S": "afgcd", "t": "defg", "U": "bcdef",
    "-": "g",
}
FILE_NAME = {c: (c if c.isdigit() or c == "-" else ("u" + c if c.isupper() else "l" + c)) for c in CHARS}

# 14 segments: A top, B/C right, D bottom, E/F left, G1/G2 the middle halves,
# I/L the centre verticals, H/J/K/M the diagonals (upper left, upper right,
# lower left, lower right), P the decimal point after the character. Upper
# case only, like the real displays.
TEXT_CHARS = {
    "0": "ABCDEFJK", "1": "BCJ", "2": "ABDEG1G2", "3": "ABCDG2", "4": "BCFG1G2", "5": "ACDFG1G2",
    "6": "ACDEFG1G2", "7": "ABC", "8": "ABCDEFG1G2", "9": "ABCDFG1G2",
    "A": "ABCEFG1G2", "B": "ABCDILG2", "C": "ADEF", "D": "ABCDIL", "E": "ADEFG1", "F": "AEFG1",
    "G": "ACDEFG2", "H": "BCEFG1G2", "I": "ADIL", "J": "BCDE", "K": "EFG1JM", "L": "DEF",
    "M": "BCEFHJ", "N": "BCEFHM", "O": "ABCDEF", "P": "ABEFG1G2", "Q": "ABCDEFM", "R": "ABEFG1G2M",
    "S": "ACDFG1G2", "T": "AIL", "U": "BCDEF", "V": "EFJK", "W": "BCEFKM", "X": "HJKM", "Y": "HJL",
    "Z": "ADJK", "-": "G1G2", "+": "G1G2IL", "/": "JK", "'": "J", ",": "K", "(": "JM", ")": "HK",
    "!": "I", "?": "ABG2L", "_": "D", "=": "DG1G2", "*": "G1G2HIJKLM", "&": "ADEHJMG1",
    ":": "IL", "\"": "FI", ".": "P", "[": "ADEF", "]": "ABCD",
}


def seg14_polys(w, h, t):
    g = t * 0.35
    ht = t / 2.0
    hh = h / 2.0

    def hseg(x0, x1, y):
        x0, x1 = x0 + g + ht, x1 - g - ht
        return [(x0 - ht, y), (x0, y - ht), (x1, y - ht), (x1 + ht, y), (x1, y + ht), (x0, y + ht)]

    def vseg(x, y0, y1):
        y0, y1 = y0 + g + ht, y1 - g - ht
        return [(x, y0 - ht), (x + ht, y0), (x + ht, y1), (x, y1 + ht), (x - ht, y1), (x - ht, y0)]

    def diag(x0, y0, x1, y1):
        dx, dy = x1 - x0, y1 - y0
        ln = math.hypot(dx, dy)
        ux, uy = dx / ln, dy / ln
        x0, y0, x1, y1 = x0 + ux * g, y0 + uy * g, x1 - ux * g, y1 - uy * g
        nx, ny = -uy * t * 0.42, ux * t * 0.42
        return [(x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)]

    c = w / 2.0
    return {
        "A": hseg(0, w, ht), "D": hseg(0, w, h - ht),
        "G1": hseg(0, c + ht, hh), "G2": hseg(c - ht, w, hh),
        "F": vseg(ht, ht, hh), "E": vseg(ht, hh, h - ht),
        "B": vseg(w - ht, ht, hh), "C": vseg(w - ht, hh, h - ht),
        "I": vseg(c, ht, hh), "L": vseg(c, hh, h - ht),
        "H": diag(t, t, c - ht, hh - ht), "J": diag(w - t, t, c + ht, hh - ht),
        "K": diag(t, h - t, c - ht, hh + ht), "M": diag(w - t, h - t, c + ht, hh + ht),
        # the point sits right of the box (skew() leans it back under the character)
        "P": [(w + 0.5, h - 1.5), (w + 1.9, h - 1.5), (w + 1.9, h - 0.1), (w + 0.5, h - 0.1)],
    }


def seg14_split(code):
    out, i = [], 0
    while i < len(code):
        if code[i] == "G":
            out.append(code[i:i + 2])
            i += 2
        else:
            out.append(code[i])
            i += 1
    return out


def seg14_mask(c, bx, by, lay, segs=None):
    w, h = TEXT
    polys = seg14_polys(w, h, 1.25)
    for sname in (segs if segs is not None else seg14_split(TEXT_CHARS[c])):
        lay.poly(skew(polys[sname], h, bx, by))


def indicator(lay, t, x, y, sz, b):
    """Draw an indicator; returns its right edge (points)."""
    f = ImageFont.truetype(FONT if b else FONT_R, 100)
    k = sz / 100.0
    e = f.getbbox("E")
    top = y + e[1] * k                          # the cap-height band of the text
    cap = (e[3] - e[1]) * k

    def tri(x0):
        w = cap * 0.9
        lay.poly([(x0, top), (x0 + w, top + cap / 2), (x0, top + cap)])
        return x0 + w

    def bars(x0):
        bw = cap * 0.28
        for i in (0, 1):
            a = x0 + i * bw * 1.9
            lay.poly([(a, top), (a + bw, top), (a + bw, top + cap), (a, top + cap)])
        return x0 + bw * 2.9

    if t == ">":
        return tri(x)
    if t == "<":
        w = cap * 0.9
        lay.poly([(x + w, top), (x, top + cap / 2), (x + w, top + cap)])
        return x + w
    if t.startswith("> "):
        x = tri(x) + sz * 0.35
        t = t[2:]
    elif t.startswith("|| "):
        x = bars(x) + sz * 0.35
        t = t[3:]
    tail = t.endswith(" >")
    if tail:
        t = t[:-2]
    lay.text(t, x, y, sz, b)
    right = x + f.getlength(t) * k
    if tail:
        right = tri(right + sz * 0.35)
    return right


def seg_polys(w, h, t):
    """The seven segments of a character box w x h (points, unskewed) as
    hexagons of thickness t, with a small gap between neighbours."""
    g = t * 0.18
    hh = h / 2.0
    ht = t / 2.0

    def horiz(y):
        x0, x1 = g + ht, w - g - ht
        return [(x0 - ht, y), (x0, y - ht), (x1, y - ht), (x1 + ht, y), (x1, y + ht), (x0, y + ht)]

    def vert(x, y0, y1):
        y0, y1 = y0 + g + ht, y1 - g - ht
        return [(x, y0 - ht), (x + ht, y0), (x + ht, y1), (x, y1 + ht), (x - ht, y1), (x - ht, y0)]

    return {
        "a": horiz(ht), "g": horiz(hh), "d": horiz(h - ht),
        "f": vert(ht, ht, hh), "b": vert(w - ht, ht, hh),
        "e": vert(ht, hh, h - ht), "c": vert(w - ht, hh, h - ht),
    }


def skew(poly, h, ox, oy):
    # italic: the top leans right, pivot at the bottom
    return [(ox + x + (h - y) * math.tan(SKEW), oy + y) for x, y in poly]


class Layer:
    """A supersampled coverage mask over a box of the panel."""

    def __init__(self, x0, y0, w, h, ppt=PPT):
        self.x0, self.y0 = x0, y0
        self.W, self.H = int(round(w * ppt)), int(round(h * ppt))
        self.k = ppt * SS
        self.img = Image.new("L", (self.W * SS, self.H * SS), 0)
        self.d = ImageDraw.Draw(self.img)

    def poly(self, pts):
        self.d.polygon([((x - self.x0) * self.k, (y - self.y0) * self.k) for x, y in pts], fill=255)

    def text(self, s, x, y, size, bold=True):
        f = ImageFont.truetype(FONT if bold else FONT_R, int(round(size * self.k)))
        self.d.text(((x - self.x0) * self.k, (y - self.y0) * self.k), s, font=f, fill=255)

    def ellipse(self, cx, cy, r):
        k = self.k
        self.d.ellipse([(cx - r - self.x0) * k, (cy - r - self.y0) * k, (cx + r - self.x0) * k, (cy + r - self.y0) * k], fill=255)

    def mask(self):
        a = np.asarray(self.img, dtype=np.float32) / 255.0
        return a.reshape(self.H, SS, self.W, SS).mean(axis=(1, 3))


def lit(mask, ppt=PPT):
    """A lit element: dark segment over its soft shadow, straight alpha."""
    if VFD:
        return lit_vfd(mask, ppt)
    sx, sy = SHADOW[0] * ppt, SHADOW[1] * ppt
    sh = ndimage.shift(mask, (sy, sx), order=1, mode="constant")
    sh = ndimage.gaussian_filter(sh, 0.55 * ppt) * 0.30
    a = np.clip(mask * 0.93 + sh * (1 - mask * 0.93), 0, 1)
    rgb = np.zeros(mask.shape + (3,), dtype=np.float32)
    rgb[:] = SEG_ON
    # the shadow is a darker ground, not black
    rgb = np.where((mask > 0.01)[..., None], rgb, np.array((0.22, 0.25, 0.19), dtype=np.float32))
    out = np.concatenate([rgb, a[..., None]], axis=2)
    return Image.fromarray(np.round(np.clip(out, 0, 1) * 255).astype(np.uint8), "RGBA")


def lit_vfd(mask, ppt=PPT):
    """A lit fluorescent element: a hot cyan core, lighter in its middle,
    inside a soft halo of the same light. Straight alpha: the halo is a
    translucent cyan over the dark glass."""
    glow = ndimage.gaussian_filter(mask, 0.55 * ppt)
    inner = ndimage.gaussian_filter(mask, 0.18 * ppt) * mask      # 1 in the middle of a stroke, less at its edge
    a = np.clip(mask + VFD_GLOW_A * glow * (1 - mask), 0, 1)
    core = np.array(VFD_EDGE, np.float32) + (np.array(VFD_CORE, np.float32) - np.array(VFD_EDGE, np.float32)) * np.clip(inner, 0, 1)[..., None] ** 2
    w = np.clip(mask / np.maximum(a, 1e-4), 0, 1)[..., None]
    rgb = core * w + np.array(VFD_GLOW, np.float32) * (1 - w)
    out = np.concatenate([rgb, a[..., None]], axis=2)
    return Image.fromarray(np.round(np.clip(out, 0, 1) * 255).astype(np.uint8), "RGBA")


def save(img, out, name):
    img.save(os.path.join(out, name), optimize=True)


def pad_box(x, y, w, h, m=2.0):
    # room for the italic lean and the shadow
    return x - m, y - m, w + 2 * m + h * math.tan(SKEW), h + 2 * m


def char_mask(c, bx, by, lay, k=1.0):
    w, h = DIGIT[0] * k, DIGIT[1] * k
    for s in CHARS[c]:
        lay.poly(skew(seg_polys(w, h, 3.3 * k)[s], h, bx, by))


def digit_box():
    w, h = DIGIT
    return pad_box(0, 0, w, h)


def colon_polys(x, y):
    h = DIGIT[1]
    out = []
    for yy in (h * 0.30, h * 0.72):
        cx, cy = x + 2.5 + (h - yy) * math.tan(SKEW), y + yy
        out.append([(cx - 1.6, cy - 1.6), (cx + 1.6, cy - 1.6), (cx + 1.6, cy + 1.6), (cx - 1.6, cy + 1.6)])
    return out


def spin_polys(k):
    cx, cy = SPIN_C
    r0, r1 = SPIN_R
    a0 = math.radians(k * 45 + 4 - 90)
    a1 = math.radians(k * 45 + 41 - 90)
    pts = []
    for i in range(9):
        a = a0 + (a1 - a0) * i / 8
        pts.append((cx + r1 * math.cos(a), cy + r1 * math.sin(a)))
    for i in range(9):
        a = a1 + (a0 - a1) * i / 8
        pts.append((cx + r0 * math.cos(a), cy + r0 * math.sin(a)))
    return pts


def cal_cell(n):
    i = n - 1
    return CAL_X0 + (i % 8) * CAL_DX, CAL_Y0 + (i // 8) * CAL_DY


def cal_draw(lay, n):
    x, y = cal_cell(n)
    s = str(n)
    f = ImageFont.truetype(FONT, int(round(7.0 * lay.k)))
    tw = lay.d.textlength(s, font=f) / lay.k
    lay.d.text(((x + (CAL_BOX[0] - tw) / 2 - lay.x0) * lay.k, (y + 0.4 - lay.y0) * lay.k), s, font=f, fill=255)


def cal_frame(lay, n):
    # the thin box round each number, lit with it
    x, y = cal_cell(n)
    w, h = CAL_BOX
    t = 0.55
    for (a, b, c, d) in ((x, y, x + w, y + t), (x, y + h - t, x + w, y + h), (x, y, x + t, y + h), (x + w - t, y, x + w, y + h)):
        lay.poly([(a, b), (c, b), (c, d), (a, d)])


def all_segments(lay):
    for bx in TRACK_X + TIME_X:
        char_mask("8", bx, DIGIT_Y, lay)
    for p in colon_polys(*COLON):
        lay.poly(p)
    for k in range(8):
        lay.poly(spin_polys(k))
    for name, (t, x, y, sz, b) in INDICATORS.items():
        indicator(lay, t, x, y, sz, b)
    lay.ellipse(SPIN_C[0], SPIN_C[1], 2.2)
    for n in range(1, 17):
        cal_draw(lay, n)
        cal_frame(lay, n)
    allseg = list(seg14_polys(*TEXT, 1.25).keys())
    for i in range(TEXT_N):
        seg14_mask(None, TEXT_X0 + i * TEXT_DX, TEXT_Y, lay, allseg)


def build_bg_vfd(out):
    """The fluorescent display behind its smoked glass: nearly black with a
    blue-green cast, every segment faintly there, and the thin filament wires
    running across in front of the segments."""
    rng = np.random.default_rng(6)
    Wp, Hp = int(W * PPT), int(H * PPT)
    y, x = np.mgrid[0:Hp, 0:Wp].astype(np.float32)
    u, v = x / Wp, y / Hp
    base = np.array((0.016, 0.030, 0.032), dtype=np.float32)
    shade = 1.0 + 0.25 * (0.5 - v) - 0.35 * ((2 * u - 1) ** 4 + (2 * v - 1) ** 4)
    grain = ndimage.gaussian_filter(rng.standard_normal((Hp, Wp)).astype(np.float32), 1.0) * 0.05
    rgb = base[None, None, :] * np.clip(shade + grain, 0.3, None)[..., None]
    lay = Layer(0, 0, W, H)
    all_segments(lay)
    m = lay.mask()
    rgb = rgb * (1 - m[..., None]) + np.array(VFD_GHOST, np.float32) * m[..., None]
    # the filament wires, very fine, across the three rows of the display
    for wy in (12.5, 57.5, 82.0):
        wire = np.exp(-((y / PPT - wy) / 0.16) ** 2) * 0.05
        rgb = rgb + wire[..., None] * np.array((0.6, 0.7, 0.7), np.float32)
    img = np.concatenate([np.clip(rgb, 0, 1), np.ones((Hp, Wp, 1), np.float32)], axis=2)
    save(Image.fromarray(np.round(img * 255).astype(np.uint8), "RGBA"), out, "lcd-bg.png")


def build_bg(out):
    if VFD:
        return build_bg_vfd(out)
    rng = np.random.default_rng(5)
    Wp, Hp = int(W * PPT), int(H * PPT)
    y, x = np.mgrid[0:Hp, 0:Wp].astype(np.float32)
    u, v = x / Wp, y / Hp
    # grey-green ground, a little lighter towards the top, darker at the edges
    base = np.array((0.585, 0.625, 0.505), dtype=np.float32)
    shade = 1.0 + 0.05 * (0.5 - v) - 0.10 * ((2 * u - 1) ** 4 + (2 * v - 1) ** 4)
    grain = ndimage.gaussian_filter(rng.standard_normal((Hp, Wp)).astype(np.float32), 1.2) * 0.012
    rgb = base[None, None, :] * (shade + grain)[..., None]
    lay = Layer(0, 0, W, H)
    all_segments(lay)
    m = lay.mask()
    # unlit segments: a faint darker trace with the same shadow
    sh = ndimage.gaussian_filter(ndimage.shift(m, (SHADOW[1] * PPT, SHADOW[0] * PPT), order=1), 0.5 * PPT)
    rgb = rgb * (1 - GHOST_A * m[..., None]) * (1 - 0.025 * sh[..., None])
    img = np.concatenate([np.clip(rgb, 0, 1), np.ones((Hp, Wp, 1), np.float32)], axis=2)
    save(Image.fromarray(np.round(img * 255).astype(np.uint8), "RGBA"), out, "lcd-bg.png")


def build_glass(out):
    Wp, Hp = int(W * PPT), int(H * PPT)
    y, x = np.mgrid[0:Hp, 0:Wp].astype(np.float32)
    u, v = x / Wp, y / Hp
    # a broad diagonal sheen and a thin bright line near the top edge
    d = (u * 0.55 + v) - 0.42
    a = 0.10 * np.exp(-(d / 0.16) ** 2) + 0.05 * np.exp(-((v - 0.035) / 0.02) ** 2)
    a = a + 0.05 * (1 - v) ** 3
    if VFD:
        a = a * 0.55                                    # smoked glass: a dimmer reflection
    img = np.zeros((Hp, Wp, 4), np.float32)
    img[..., :3] = 1.0
    img[..., 3] = np.clip(a, 0, 1)
    save(Image.fromarray(np.round(img * 255).astype(np.uint8), "RGBA"), out, "lcd-glass.png")


def build_chars(out):
    x, y, w, h = digit_box()
    for c in CHARS:
        lay = Layer(x, y, w, h)
        char_mask(c, 0, 0, lay)
        save(lit(lay.mask()), out, f"d-{FILE_NAME[c]}.png")
    lay = Layer(-2, -2, 9, DIGIT[1] + 4)
    for p in colon_polys(0, 0):
        lay.poly(p)
    save(lit(lay.mask()), out, "colon.png")


def text_box(t, x, y, sz, b):
    right = indicator(Layer(0, 0, 1, 1), t, x, y, sz, b)
    f = ImageFont.truetype(FONT if b else FONT_R, 100)
    bt = f.getbbox("Ag")[3] * sz / 100.0
    return x - 1.5, y - 1.5, right - x + 3, bt + 3


def build_indicators(out):
    for name, (t, x, y, sz, b) in INDICATORS.items():
        bx, by, bw, bh = text_box(t, x, y, sz, b)
        lay = Layer(bx, by, bw, bh)
        indicator(lay, t, x, y, sz, b)
        save(lit(lay.mask()), out, f"i-{name}.png")
    # the disc indicator's hub, lit whenever a disc is loaded
    lay = Layer(SPIN_C[0] - 3.5, SPIN_C[1] - 3.5, 7, 7)
    lay.ellipse(SPIN_C[0], SPIN_C[1], 2.2)
    save(lit(lay.mask()), out, "i-disc.png")
    for k in range(8):
        r = SPIN_R[1] + 2
        lay = Layer(SPIN_C[0] - r, SPIN_C[1] - r, 2 * r, 2 * r)
        for j in range(8):
            if j != k:
                lay.poly(spin_polys(j))
        save(lit(lay.mask()), out, f"spin-{k}.png")
    r = SPIN_R[1] + 2
    lay = Layer(SPIN_C[0] - r, SPIN_C[1] - r, 2 * r, 2 * r)
    for j in range(8):
        lay.poly(spin_polys(j))
    save(lit(lay.mask()), out, "spin-all.png")


def seg14_box():
    w, h = TEXT
    return pad_box(0, 0, w, h, m=1.5)


def build_text(out):
    x, y, w, h = seg14_box()
    for c in TEXT_CHARS:
        lay = Layer(x, y, w, h)
        seg14_mask(c, 0, 0, lay)
        save(lit(lay.mask()), out, f"t-{ord(c):02x}.png")


def build_calendar(out):
    for n in range(1, 17):
        x, y = cal_cell(n)
        lay = Layer(x - 1.5, y - 1.5, CAL_BOX[0] + 3, CAL_BOX[1] + 3)
        cal_draw(lay, n)
        cal_frame(lay, n)
        save(lit(lay.mask()), out, f"cal-{n}.png")


# ── the cassette deck's panel (mirrored in LcdTape.qml) ─────────────────────
TW, TH = 160, 58
T_K = 0.72                         # its counter digits: the big ones scaled
T_COUNTER_X = (100.0, 113.0, 126.0, 139.0)
T_COUNTER_Y = 14.0
T_METER_X0, T_SEG_W, T_SEG_DX, T_SEGS = 16.0, 4.0, 4.8, 16
T_ROWS = (15.0, 25.5)              # top of the L and R rows
T_ROW_H = 5.5
T_METER_BOX = (14.0, 13.0, 80.0, 20.0)
TAPE_IND = {
    "play": ("> PLAY", 6.0, 3.0, 5.2, True),
    "pause": ("|| PAUSE", 34.0, 3.0, 5.2, True),
    "nr": ("NR", 66.0, 3.0, 5.2, True),
    "autorev": ("AUTO REV", 80.0, 3.0, 5.2, True),
    "rec": ("REC", 116.0, 3.0, 5.2, True),
    "l": ("L", 6.0, 14.6, 5.4, True),
    "r": ("R", 6.0, 25.1, 5.4, True),
    "counter": ("COUNTER", 104.0, 37.5, 4.2, True),
    "type": ("TYPE", 6.0, 46.0, 5.0, True),
    "t1": ("I", 26.0, 46.0, 5.0, True),
    "t2": ("II", 33.0, 46.0, 5.0, True),
    "t4": ("IV", 42.0, 46.0, 5.0, True),
    "rev": ("<", 104.0, 46.0, 6.0, True),
    "fwd": (">", 112.0, 46.0, 6.0, True),
}
# The dB scale under the meters, where the bar really reaches that level.
# The meters show VuMeter's 0..100, which vu_meter_daemon.py makes from the
# RMS of what goes to the DAC: -50 dBFS -> 0, -5 dBFS -> 100, then ^1.2.
# 0 on the scale is 0 VU at -18 dBFS (the usual digital reference).
VU_MIN_DBFS, VU_MAX_DBFS, VU_GAMMA = -50.0, -5.0, 1.2
VU_ZERO_DBFS = -18.0
T_SCALE = (-30, -20, -10, -5, 0, 3, 6, 10)


def tape_level_x(vu_db):
    """x of the bar's end when the level is vu_db (dB against 0 VU)."""
    f = min(1.0, max(0.0, (vu_db + VU_ZERO_DBFS - VU_MIN_DBFS) / (VU_MAX_DBFS - VU_MIN_DBFS))) ** VU_GAMMA
    return T_METER_X0 + f * (T_SEGS * T_SEG_DX - (T_SEG_DX - T_SEG_W))


def tape_seg(i, row):
    x = T_METER_X0 + i * T_SEG_DX
    y = T_ROWS[row]
    return [(x, y), (x + T_SEG_W, y), (x + T_SEG_W, y + T_ROW_H), (x, y + T_ROW_H)]


def tape_scale(lay):
    f = ImageFont.truetype(FONT, int(round(3.8 * lay.k)))
    for v in T_SCALE:
        t = ("+" if v > 0 else "") + str(v)
        cx = tape_level_x(v)
        tw = lay.d.textlength(t, font=f) / lay.k
        lay.d.text(((cx - tw / 2 - lay.x0) * lay.k, (33.5 - lay.y0) * lay.k), t, font=f, fill=255)


def build_tape(out):
    rng = np.random.default_rng(7)
    Wp, Hp = int(TW * PPT), int(TH * PPT)
    y, x = np.mgrid[0:Hp, 0:Wp].astype(np.float32)
    u, v = x / Wp, y / Hp
    base = np.array((0.585, 0.625, 0.505), dtype=np.float32)
    shade = 1.0 + 0.05 * (0.5 - v) - 0.10 * ((2 * u - 1) ** 4 + (2 * v - 1) ** 4)
    grain = ndimage.gaussian_filter(rng.standard_normal((Hp, Wp)).astype(np.float32), 1.2) * 0.012
    rgb = base[None, None, :] * (shade + grain)[..., None]
    lay = Layer(0, 0, TW, TH)
    for bx in T_COUNTER_X:
        char_mask("8", bx, T_COUNTER_Y, lay, T_K)
    for row in (0, 1):
        for i in range(T_SEGS):
            lay.poly(tape_seg(i, row))
    for name, (t, x0, y0, sz, b) in TAPE_IND.items():
        indicator(lay, t, x0, y0, sz, b)
    tape_scale(lay)
    m = lay.mask()
    sh = ndimage.gaussian_filter(ndimage.shift(m, (SHADOW[1] * PPT, SHADOW[0] * PPT), order=1), 0.5 * PPT)
    rgb = rgb * (1 - GHOST_A * m[..., None]) * (1 - 0.025 * sh[..., None])
    img = np.concatenate([np.clip(rgb, 0, 1), np.ones((Hp, Wp, 1), np.float32)], axis=2)
    save(Image.fromarray(np.round(img * 255).astype(np.uint8), "RGBA"), out, "tape-bg.png")

    lay = Layer(*T_METER_BOX)
    for row in (0, 1):
        for i in range(T_SEGS):
            lay.poly(tape_seg(i, row))
    save(lit(lay.mask()), out, "tape-meter.png")
    for name, (t, x0, y0, sz, b) in TAPE_IND.items():
        bx, by, bw, bh = text_box(t, x0, y0, sz, b)
        lay = Layer(bx, by, bw, bh)
        indicator(lay, t, x0, y0, sz, b)
        save(lit(lay.mask()), out, f"i-t-{name}.png")
        print(f"i-t-{name}: box", tuple(round(q, 2) for q in (bx, by, bw, bh)))
    lay = Layer(12, 32, 84, 7)
    tape_scale(lay)
    save(lit(lay.mask()), out, "i-t-scale.png")


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=None)
    ap.add_argument("--vfd", action="store_true", help="the fluorescent display (assets/anim/vfd/)")
    args = ap.parse_args()
    global VFD
    VFD = args.vfd
    if args.out is None:
        args.out = os.path.normpath(os.path.join(here, "..", "..", "assets", "anim", "vfd" if VFD else "lcd"))
    os.makedirs(args.out, exist_ok=True)
    build_bg(args.out)
    build_glass(args.out)
    build_chars(args.out)
    build_indicators(args.out)
    build_calendar(args.out)
    build_text(args.out)
    if not VFD:
        build_tape(args.out)
    # the boxes QML needs, printed so they can be checked against LcdCd.qml
    x, y, w, h = digit_box()
    print(f"digit box: offset ({x:.2f}, {y:.2f}) size {w:.2f} x {h:.2f}")
    x, y, w, h = seg14_box()
    print(f"text box: offset ({x:.2f}, {y:.2f}) size {w:.2f} x {h:.2f}")
    print("text chars:", "".join(sorted(TEXT_CHARS)))
    for name, v in INDICATORS.items():
        print(f"i-{name}: box", tuple(round(q, 2) for q in text_box(*v)))


if __name__ == "__main__":
    main()
