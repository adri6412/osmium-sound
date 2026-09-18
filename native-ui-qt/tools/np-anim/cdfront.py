#!/usr/bin/env python3
"""Render the images of the "CD player" (front-loading) animation (qml/AnimCdFront.qml).

A late-80s / early-90s black front-loading CD player in the manner of the
Japanese and European hi-fi of the time, seen from the front: an upper
fascia with the gold name, the disc drawer at the left with a badge under
it, the blue-green fluorescent display (tools/np-anim/lcd.py --vfd) behind
a smoked window in the middle and the framed PLAY / STOP / PAUSE keys at the
right; a step down to the lower part with the row of slim keys (OPEN, the
track numbers 1-10, REPEAT, RANDOM) and the square skip / search keys; at the
bottom POWER, a gold script, the gold headphone jack and its level knob; and
champagne feet under the case. The drawer slides out towards the viewer;
from above one sees its bed with the disc on it.

Drawing and lighting come from cd.py (same light).

    python3 native-ui-qt/tools/np-anim/cdfront.py [--out DIR]

DIR defaults to native-ui-qt/assets/anim/cdfront/. Files, all in the 520 x 260
point design of AnimCdFront.qml (the geometry constants below are mirrored
there):

  cdf-base.png       the player: drop shadow, feet, front, the drawer slot,
                     the display window (without the display), keys, jack,
                     knob, prints
  cdf-drawer.png     the drawer front, closed flush in the slot
  cdf-bed.png        the drawer's bed seen from above, disc recess included
                     (BED_W x BED_H; its front edge meets the drawer front)
  cdf-drawer-sh.png  the shadow the open drawer casts on the front below it
  cdf-led-red.png    the standby LED lit
  cdf-led-green.png  the power LED lit
"""
import argparse
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from cd import (Canvas, blinn, lambert, normals, radial_noise, rgb3, save, sd_circle, sd_rrect,
                smoothstep, soft, srgb, streaks, LXY, LSLOPE)

CANVAS = (520, 260)
BODY = (4, 12, 516, 222)
BODY_R = 3
FEET = (70, 260, 450)                 # centres of the three feet under the case
FOOT_W, FOOT_Y = 50, (222, 234)
SPLIT_Y = 112                         # the step down to the lower part
SLOT = (18, 34, 224, 98)
DRAWER = (21, 37, 221, 95)
TRAVEL = 106                          # how far the drawer comes out
BED_W, BED_H = 200, 124               # its front edge is the drawer front's top
BED_DISC = (100, 86)                  # disc centre in the bed (middle of what shows when open)
BED_DISC_R = (97, 33)                 # the 12 cm recess as seen (rx, ry)
BADGE = (22, 124, 150, 146)
WIN = (236, 26, 414, 106)             # the smoked window of the display
VFD_AT = (246.6, 26)                  # the LcdCd panel (196 x 100) at VFD_K
VFD_K = 0.8
FRAME = (425, 35, 511, 67)            # the raised frame round PLAY / STOP / PAUSE
KEY_Y = (126, 146)                    # the lower row
BIG_Y = (39, 63)                      # the framed transport keys
NUM_X0, NUM_DX, NUM_W = 262, 10.5, 6.0
KEYS = {                              # name: x0, y0, x1, y1
    "play": (429, 39, 455, 63), "stop": (457, 39, 482, 63), "pause": (484, 39, 508, 63),
    "eject": (236, 126, 252, 146),
    "repeat": (378, 126, 384, 146), "random": (396, 126, 402, 146),
    "prev": (424, 126, 442, 146), "next": (446, 126, 464, 146),
    "rew": (468, 126, 486, 146), "ff": (490, 126, 508, 146),
    "power": (22, 170, 44, 192),
}
for _i in range(10):
    KEYS["n%d" % (_i + 1)] = (NUM_X0 + _i * NUM_DX, 126, NUM_X0 + _i * NUM_DX + NUM_W, 146)
LED = (53, 181)
JACK = (440, 184)
KNOB = (484, 182)
KNOB_R = 10

PPT = 3.6
FONT = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
FONT_R = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
FONT_SCRIPT = "/usr/share/fonts/truetype/freefont/FreeSerifBoldItalic.ttf"
INK = (0.62, 0.60, 0.54)              # the prints: a warm off-white (linear)
GOLD = (0.62, 0.42, 0.13)             # the name and the script (linear)


def text_mask(cv, items, font=None):
    """Coverage of printed text on the canvas grid. items: (text, x, y, size,
    bold, anchor, spacing) with anchor 'l', 'm' or 'r' on x, y the top of the
    caps."""
    img = Image.new("L", (cv.X.shape[1], cv.X.shape[0]), 0)
    d = ImageDraw.Draw(img)
    x0, y0, n = float(cv.X[0, 0]) - 0.5 / cv.n, float(cv.Y[0, 0]) - 0.5 / cv.n, cv.n
    for t, x, y, sz, bold, anchor, spacing in items:
        f = ImageFont.truetype(font or (FONT if bold else FONT_R), max(1, int(round(sz * n))))
        cap = f.getbbox("E")[1]
        w = sum(f.getlength(c) for c in t) + spacing * n * (len(t) - 1)
        px = (x - x0) * n - {"l": 0, "m": w / 2, "r": w}[anchor]
        py = (y - y0) * n - cap
        for c in t:
            d.text((px, py), c, font=f, fill=255)
            px += f.getlength(c) + spacing * n
    return np.asarray(img, dtype=np.float32) / 255.0


def text_width(t, sz, bold=True, spacing=0.0, font=None):
    f = ImageFont.truetype(font or (FONT if bold else FONT_R), 100)
    return sum(f.getlength(c) for c in t) * sz / 100 + spacing * (len(t) - 1)


def symbol_mask(cv, name, cx, cy, s):
    """The symbol printed on a key cap, s = cap height of the symbol."""
    X, Y = cv.X, cv.Y
    def tri(x0, dirn=1):
        # a triangle pointing right (dirn 1) or left (-1), base at x0
        u = (X - x0) * dirn
        return np.maximum(-u, np.maximum(u - s * 0.8, np.abs(Y - cy) - (s / 2) * (1 - u / (s * 0.8))))
    def bar(x0, w):
        return sd_rrect(X, Y, x0, cy - s / 2, x0 + w, cy + s / 2, 0.2)
    if name == "play":
        sd = tri(cx - s * 0.35)
    elif name == "pause":
        sd = np.minimum(bar(cx - s * 0.42, s * 0.28), bar(cx + s * 0.14, s * 0.28))
    elif name == "stop":
        sd = sd_rrect(X, Y, cx - s * 0.42, cy - s * 0.42, cx + s * 0.42, cy + s * 0.42, 0.3)
    elif name == "eject":
        u = Y - (cy - s * 0.5)
        tri_up = np.maximum(np.abs(X - cx) - s * 0.55 * u / (s * 0.55), np.maximum(-u, u - s * 0.55))
        sd = np.minimum(tri_up, sd_rrect(X, Y, cx - s * 0.55, cy + s * 0.25, cx + s * 0.55, cy + s * 0.45, 0.2))
    elif name == "prev":
        sd = np.minimum(np.minimum(bar(cx - s * 0.85, s * 0.16), tri(cx - s * 0.1, -1)), tri(cx + s * 0.7, -1))
    elif name == "next":
        sd = np.minimum(np.minimum(bar(cx + s * 0.69, s * 0.16), tri(cx + s * 0.1, 1)), tri(cx - s * 0.7, 1))
    elif name == "rew":
        sd = np.minimum(tri(cx, -1), tri(cx + s * 0.8, -1))
    elif name == "ff":
        sd = np.minimum(tri(cx, 1), tri(cx - s * 0.8, 1))
    elif name == "power":
        r = np.hypot(X - cx, Y - cy)
        ang = np.arctan2(X - cx, -(Y - cy))
        ring = np.maximum(np.abs(r - s * 0.42) - s * 0.08, 0.55 - np.abs(ang))
        stem = sd_rrect(X, Y, cx - s * 0.08, cy - s * 0.6, cx + s * 0.08, cy - s * 0.05, 0.2)
        sd = np.minimum(ring, stem)
    else:
        return np.zeros_like(X)
    return cv.cov(sd)


def slim(name):
    """The slim keys of the lower row: the numbers, REPEAT, RANDOM (no symbol)."""
    return name[1:].isdigit() or name in ("repeat", "random")


def raised(sd, height, bevel):
    """Height of a raised shape with a rounded bevel."""
    return height * np.sqrt(np.clip(1 - (1 - np.clip(-sd / bevel, 0, 1)) ** 2, 0, 1))


def build_base(out):
    cv = Canvas(0, 0, CANVAS[0], CANVAS[1], PPT)
    X, Y, n = cv.X, cv.Y, cv.n
    rng = np.random.default_rng(31)
    bx0, by0, bx1, by1 = BODY

    # ── shadow on the shelf, under the case and its feet ──
    sh = (0.55 * soft(sd_rrect(X, Y - 8, bx0 + 10, by0 + 4, bx1 - 10, FOOT_Y[1], BODY_R), 8.0)
          + 0.35 * soft(sd_rrect(X, Y - 2, bx0 + 2, by0 + 2, bx1 - 2, FOOT_Y[1] + 1, BODY_R), 2.4))
    for fx in FEET:
        sh = sh + 0.6 * soft(sd_rrect(X, Y - 1.5, fx - FOOT_W / 2, FOOT_Y[1] - 3, fx + FOOT_W / 2, FOOT_Y[1] + 1.5, 2), 1.6)
    edge = np.minimum(np.minimum(X, CANVAS[0] - X), np.minimum(Y, CANVAS[1] - Y))
    cv.over((0, 0, 0), np.clip(sh, 0, 0.9) * smoothstep(0, 5, edge))

    # ── champagne feet: turned aluminium cylinders seen from the front ──
    for fx in FEET:
        fsd = sd_rrect(X, Y, fx - FOOT_W / 2, FOOT_Y[0] - 2, fx + FOOT_W / 2, FOOT_Y[1], 1.2)
        u = np.clip((X - fx) / (FOOT_W / 2), -1, 1)
        nz = np.sqrt(np.clip(1 - u * u, 0, 1))
        fl = np.clip(-u * LXY[0] * 0.8 + nz * 0.6, 0, None)
        v = (Y - FOOT_Y[0]) / (FOOT_Y[1] - FOOT_Y[0])
        band = 0.10 * np.cos(v * 38) * 0.3
        tone = 0.10 + 0.45 * fl + 0.55 * np.exp(-((u + 0.35) / 0.18) ** 2) + band
        tone = tone * (0.55 + 0.45 * smoothstep(-0.1, 0.25, v))       # the case's shadow at the top
        fc = srgb(rgb3((0.78, 0.66, 0.46)) * tone[..., None])
        cv.over(fc, cv.cov(fsd))

    sd_body = sd_rrect(X, Y, *BODY, BODY_R)
    body = cv.cov(sd_body)
    lower = smoothstep(SPLIT_Y - 0.3, SPLIT_Y + 0.3, Y)

    # ── height: case bevel, the step, recesses, frame, keys ──
    e = np.clip(-sd_body, 0, None)
    h = 2.0 * np.sqrt(1 - (1 - np.clip(e / 2.0, 0, 1)) ** 2)
    h = h + 1.4 * (1 - lower)                                     # the upper fascia stands out
    sd_slot = sd_rrect(X, Y, *SLOT, 1.5)
    sd_win = sd_rrect(X, Y, *WIN, 2.0)
    sd_badge = sd_rrect(X, Y, *BADGE, 1.0)
    sd_frame = sd_rrect(X, Y, *FRAME, 2.5)
    h = h - 1.6 * (1 - smoothstep(-1.2, 0.0, sd_slot)) - 1.0 * (1 - smoothstep(-0.8, 0.0, sd_win))
    h = h + 0.5 * cv.cov(sd_badge)
    h = h + raised(sd_frame, 1.4, 1.2) - 1.0 * cv.cov(sd_rrect(X, Y, FRAME[0] + 2.4, FRAME[1] + 2.4, FRAME[2] - 2.4, FRAME[3] - 2.4, 1.5))
    keys = np.zeros_like(X)
    for name, (x0, y0, x1, y1) in KEYS.items():
        r = 1.2 if slim(name) else 1.8
        sd_k = sd_rrect(X, Y, x0, y0, x1, y1, r)
        kc = cv.cov(sd_k)
        base_h = h
        h = h * (1 - kc) + (base_h + raised(sd_k, 1.8, 1.2)) * kc
        keys = np.maximum(keys, kc)
    nx, ny, nz = normals(h, n)

    # ── finish: satin black, a fine horizontal grain on the fascia ──
    br = 0.06 * streaks(X.shape, n, rng, 70, 0.2)
    sheen = 1 + 0.25 * np.exp(-((X - 180) / 190) ** 2) * (1.1 - 0.7 * Y / CANVAS[1])
    alb = (0.024 * (1 + br) * sheen) * (1 - lower) + 0.017 * (1 + 0.4 * br) * lower
    spec = 0.30 * (1 - lower) + 0.18 * lower
    col = alb * (0.30 + 0.70 * lambert(nx, ny, nz)) + spec * blinn(nx, ny, nz, 24) + 0.03 * blinn(nx, ny, nz, 5)
    # keys: glossy black plastic
    kcol = 0.022 * (0.35 + 0.65 * lambert(nx, ny, nz)) + 0.45 * blinn(nx, ny, nz, 70) + 0.05 * blinn(nx, ny, nz, 8)
    col = col * (1 - keys) + kcol * keys

    # slot interior: nearly black (the drawer front sits in it)
    ins = np.clip(-sd_slot, 0, None)
    slot_in = cv.cov(sd_slot)
    col = col * (1 - slot_in) + (0.003 + 0.004 * (1 - np.exp(-ins / 1.5))) * slot_in
    rgb = np.repeat(col[..., None], 3, axis=2) * rgb3((0.985, 0.99, 1.02))

    # the display window: smoked glass round the display, the same dark
    # blue-green as the display's own edges
    win_in = cv.cov(sd_win)
    glass = rgb3((0.00018, 0.00050, 0.00056)) * (1 + 0.0 * X)[..., None]
    glass = glass + (0.12 * blinn(nx, ny, nz, 90))[..., None]
    rgb = rgb * (1 - win_in[..., None]) + glass * win_in[..., None]

    # the badge: a dark plate with a thin light border and its emblem
    bad = cv.cov(sd_badge)
    rgb = rgb * (1 - 0.35 * bad[..., None])
    border = cv.cov(np.abs(sd_rrect(X, Y, BADGE[0] + 1.2, BADGE[1] + 1.2, BADGE[2] - 1.2, BADGE[3] - 1.2, 0.6)) - 0.18)
    em_x, em_y = BADGE[0] + 9, (BADGE[1] + BADGE[3]) / 2
    emblem = np.clip(cv.cov(sd_rrect(X, Y, em_x - 5, em_y - 5, em_x + 5, em_y + 5, 0.6))
                     - cv.cov(sd_rrect(X, Y, em_x - 4.2, em_y - 4.2, em_x + 4.2, em_y + 4.2, 0.4)), 0, 1)
    # inside the emblem: a single pulse, the one bit
    wave = cv.cov(np.maximum(np.abs(Y - em_y - 1.2 + 2.6 * (np.abs(X - em_x) < 1.2)) - 0.3, np.abs(X - em_x) - 3.2))
    emblem = np.clip(emblem + wave, 0, 1)

    # the frame's inner well shows a slightly lighter satin
    ink_all = np.clip(border * 0.6 + emblem, 0, 1)

    # jack: gold ring, black hole
    jr = np.hypot(X - JACK[0], Y - JACK[1])
    ring = cv.cov(np.abs(jr - 4.2) - 1.6)
    rh = np.clip(1 - ((jr - 4.2) / 1.6) ** 2, 0, 1) ** 0.5
    rnx, rny, rnz = normals(rh * 1.4, n)
    gold_j = rgb3(GOLD) * (0.25 + 0.55 * lambert(rnx, rny, rnz))[..., None] + (1.1 * blinn(rnx, rny, rnz, 30))[..., None] * rgb3((1.0, 0.85, 0.55))
    rgb = rgb * (1 - ring[..., None]) + gold_j * ring[..., None]
    hole = cv.cov(jr - 2.5)
    rgb = rgb * (1 - hole[..., None]) + 0.002 * hole[..., None]

    # the level knob: black, knurled, a white index
    kr = np.hypot(X - KNOB[0], Y - KNOB[1])
    sd_knob = kr - KNOB_R
    kh = 3.0 * np.sqrt(np.clip(1 - (1 - np.clip(-sd_knob / 1.8, 0, 1)) ** 2, 0, 1))
    ang = np.arctan2(Y - KNOB[1], X - KNOB[0])
    knurl = 0.25 * np.cos(ang * 60) * smoothstep(KNOB_R - 2.2, KNOB_R - 1.0, kr)
    knx, kny, knz = normals(kh + knurl, n)
    turned = radial_noise(kr, rng, 0.15, rmax=20)
    kcol2 = 0.04 * (1 + 0.1 * turned) * (0.3 + 0.7 * lambert(knx, kny, knz)) + 0.50 * blinn(knx, kny, knz, 40)
    a0 = math.radians(-120)
    u = (X - KNOB[0]) * math.cos(a0) + (Y - KNOB[1]) * math.sin(a0)
    v = -(X - KNOB[0]) * math.sin(a0) + (Y - KNOB[1]) * math.cos(a0)
    line = cv.cov(np.maximum(np.abs(v) - 0.45, np.maximum(3.0 - u, u - (KNOB_R - 2.4))))
    kcol2 = kcol2 * (1 - line) + 0.55 * line
    kn = cv.cov(sd_knob)
    ksh = soft(np.hypot(X - KNOB[0] - LXY[0] * -3 * LSLOPE, Y - KNOB[1] - LXY[1] * -3 * LSLOPE) - KNOB_R, 1.8)
    rgb = rgb * (1 - 0.6 * ksh * (1 - kn))[..., None]
    rgb = rgb * (1 - kn[..., None]) + kcol2[..., None] * kn[..., None]

    # LED socket (unlit)
    led = cv.cov(np.hypot(X - LED[0], Y - LED[1]) - 1.7)
    rgb = rgb * (1 - led[..., None]) + 0.010 * led[..., None]

    # ── prints ──
    name_w = text_width("OSMIUM", 8.5, True, 1.6)
    items = [
        ("COMPACT DISC PLAYER  CD-90", 22 + name_w + 6, 21.5, 3.6, True, "l", 0.35),
        ("1-BIT DAC", BADGE[0] + 18, BADGE[1] + 5.5, 4.2, True, "l", 0.6),
        ("DIGITAL CONVERSION", BADGE[0] + 18, BADGE[1] + 13.5, 3.0, False, "l", 0.4),
        ("REMOTE SENSOR", WIN[0] + 2, 109.5, 2.4, False, "l", 0.3),
        ("PLAY", 442, 29, 3.8, True, "m", 0.4),
        ("STOP", 469.5, 29, 3.8, True, "m", 0.4),
        ("PAUSE", 496, 29, 3.8, True, "m", 0.4),
        ("OPEN", 244, 119.5, 3.0, True, "m", 0.2),
        ("REPEAT", 381, 119.5, 3.0, True, "m", 0.1),
        ("RANDOM", 399, 119.5, 3.0, True, "m", 0.0),
        ("POWER", 33, 163.5, 3.2, True, "m", 0.3),
        ("PHONES", JACK[0], 194, 3.2, True, "m", 0.3),
        ("PHONE", KNOB[0] + 14, 190, 2.8, True, "l", 0.2),
        ("LEVEL", KNOB[0] + 14, 194.5, 2.8, True, "l", 0.2),
        ("0", KNOB[0] - 10, 194.5, 2.8, True, "m", 0.0),
        ("10", KNOB[0] + 9, 194.5, 2.8, True, "m", 0.0),
    ]
    for i in range(10):
        x0 = NUM_X0 + i * NUM_DX
        items.append((str(i + 1), x0 + NUM_W / 2, 119.5, 3.0, True, "m", 0.0))
    ink = np.clip(text_mask(cv, items) + ink_all, 0, 1)
    rgb = rgb * (1 - ink[..., None]) + rgb3(INK) * ink[..., None]
    # symbols on the key caps
    for name, (x0, y0, x1, y1) in KEYS.items():
        if slim(name):
            continue
        size = 7.0 if name in ("play", "stop", "pause") else 5.5
        sm = symbol_mask(cv, name, (x0 + x1) / 2, (y0 + y1) / 2, size)
        rgb = rgb * (1 - sm[..., None]) + rgb3(INK) * 0.95 * sm[..., None]

    # ── gold: the name and the script, a metallic gradient ──
    gold_items = text_mask(cv, [("OSMIUM", 22, 19.5, 8.5, True, "l", 1.6)])
    script = text_mask(cv, [("Reference", 170, 178, 13.0, True, "m", 0.0)], font=FONT_SCRIPT)
    g = np.clip(gold_items + script, 0, 1)
    tg = np.clip(((Y - 12) % 14) / 14, 0, 1)
    gshade = 0.75 + 0.55 * np.exp(-((tg - 0.35) / 0.2) ** 2)
    rgb = rgb * (1 - g[..., None]) + rgb3(GOLD) * gshade[..., None] * g[..., None]

    cv.over(srgb(rgb), body)
    save(cv.image(), out, "cdf-base.png")


def build_drawer(out):
    x0, y0, x1, y1 = DRAWER
    cv = Canvas(x0 - 1, y0 - 1, x1 - x0 + 2, y1 - y0 + 2, PPT)
    X, Y, n = cv.X, cv.Y, cv.n
    rng = np.random.default_rng(41)
    sd = sd_rrect(X, Y, x0, y0, x1, y1, 1.5)
    e = np.clip(-sd, 0, None)
    h = 1.2 * np.sqrt(1 - (1 - np.clip(e / 1.2, 0, 1)) ** 2)
    # the tall flap of the period: a flat face, then a lip standing out a
    # little along the bottom third, with a shallow finger recess in it
    lip_y = y0 + 0.66 * (y1 - y0)
    h = h + 0.7 * smoothstep(lip_y - 0.4, lip_y + 0.4, Y)
    h = h - 0.6 * np.exp(-(((X - (x0 + x1) / 2) / 18) ** 2 + ((Y - y1 + 3) / 2.2) ** 2))
    nx, ny, nz = normals(h, n)
    br = 0.05 * streaks(X.shape, n, rng, 50, 0.2)
    col = 0.026 * (1 + br) * (0.3 + 0.7 * lambert(nx, ny, nz)) + 0.40 * blinn(nx, ny, nz, 50)
    col = col + 0.015 * np.exp(-((Y - y0 - 1.2) / 0.5) ** 2)
    rgb = np.repeat(col[..., None], 3, axis=2)
    # a hairline of blue light along the drawer, from end to end
    line = np.exp(-((Y - (lip_y - 1.2)) / 0.28) ** 2) * smoothstep(x0 + 14, x0 + 34, X) * smoothstep(x1 - 14, x1 - 34, X)
    rgb = rgb + line[..., None] * rgb3((0.05, 0.10, 0.45))
    cv.over(srgb(rgb), cv.cov(sd))
    save(cv.image(), out, "cdf-drawer.png")


def build_bed(out):
    cv = Canvas(0, 0, BED_W, BED_H, PPT)
    X, Y, n = cv.X, cv.Y, cv.n
    rng = np.random.default_rng(43)
    # a trapezoid: narrower towards the back (top of the image)
    inset = 7.0 * (1 - Y / BED_H)
    sd = np.maximum(np.maximum(inset + 1 - X, X - (BED_W - 1 - inset)), -Y)
    sd = np.maximum(sd, Y - BED_H)
    cx, cy = BED_DISC
    rx, ry = BED_DISC_R
    # the recesses, as ellipses (a circle seen at a grazing angle)
    q12 = np.hypot((X - cx) / rx, (Y - cy) / ry) - 1
    q8 = np.hypot((X - cx) / (rx * 0.67), (Y - cy) / (ry * 0.67)) - 1
    hole = np.hypot((X - cx) / 9, (Y - cy) / 3) - 1
    h = -0.9 * smoothstep(0.02, -0.02, q12) - 0.8 * smoothstep(0.03, -0.03, q8)
    nx, ny, nz = normals(h * 2.0, n)
    tex = 0.04 * streaks(X.shape, n, rng, 3, 0.4)
    col = 0.022 * (1 + tex) * (0.35 + 0.65 * lambert(nx, ny, nz)) + 0.25 * blinn(nx, ny, nz, 20)
    # darker towards the back, inside the player
    col = col * (0.35 + 0.65 * smoothstep(0, BED_H * 0.55, Y))
    col = col * (1 - 0.9 * np.clip(0.5 - hole * 3, 0, 1))
    cv.over(srgb(np.repeat(col[..., None], 3, axis=2)), cv.cov(sd))
    save(cv.image(), out, "cdf-bed.png")


def build_drawer_shadow(out):
    x0, y0, x1, y1 = DRAWER
    cv = Canvas(x0 - 8, y1 - 4, x1 - x0 + 16, 24, PPT)
    X, Y = cv.X, cv.Y
    sh = soft(sd_rrect(X, Y - 5, x0 + 2, y0, x1 - 2, y1, 2.0), 3.2) * 0.75
    cv.over((0, 0, 0), sh)
    save(cv.image(), out, "cdf-drawer-sh.png")


def build_leds(out):
    for name, c in (("red", (1.0, 0.16, 0.10)), ("green", (0.25, 1.0, 0.35))):
        r = 7.0
        cv = Canvas(LED[0] - r, LED[1] - r, 2 * r, 2 * r, PPT)
        X, Y = cv.X, cv.Y
        d = np.hypot(X - LED[0], Y - LED[1])
        core = cv.cov(d - 1.9)
        glow = np.exp(-(d / 3.2) ** 2) * 0.55
        hot = np.exp(-(np.hypot(X - LED[0] + 0.5, Y - LED[1] + 0.5) / 0.7) ** 2)
        a = np.clip(core + glow * (1 - core), 0, 1)
        col = rgb3(c) * (0.75 + 0.25 * core)[..., None] + hot[..., None] * 0.8
        cv.over(np.clip(col, 0, 1), a)
        save(cv.image(), out, f"cdf-led-{name}.png")


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.normpath(os.path.join(here, "..", "..", "assets", "anim", "cdfront")))
    ap.add_argument("--only", default="", help="comma separated builder names (debug)")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    builders = {"base": build_base, "drawer": build_drawer, "bed": build_bed,
                "shadow": build_drawer_shadow, "leds": build_leds}
    only = [s for s in args.only.split(",") if s]
    for k, f in builders.items():
        if not only or k in only:
            f(args.out)


if __name__ == "__main__":
    main()
