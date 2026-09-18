#!/usr/bin/env python3
"""Render the images of the "CD player" (front-loading) animation (qml/AnimCdFront.qml).

A 90s black front-loading CD player seen from the front, a little from
above: the disc drawer at the top left, the grey-green LCD (tools/np-anim/
lcd.py) at the top right, a row of keys along the bottom. The drawer slides
out towards the viewer; from above one sees its bed with the disc on it.

Drawing and lighting come from cd.py (same light, same brushed aluminium).

    python3 native-ui-qt/tools/np-anim/cdfront.py [--out DIR]

DIR defaults to native-ui-qt/assets/anim/cdfront/. Files, all in the 520 x 260
point design of AnimCdFront.qml (the geometry constants below are mirrored
there):

  cdf-base.png       the player: drop shadow, front plate, the drawer slot,
                     the LCD window (without the LCD), keys, jack, knob, prints
  cdf-drawer.png     the drawer front, closed flush in the slot
  cdf-bed.png        the drawer's bed seen from above, disc recess included
                     (BED_W x BED_H; its front edge meets the drawer front)
  cdf-drawer-sh.png  the shadow the open drawer casts on the plate below it
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
BODY = (4, 14, 516, 226)
BODY_R = 4
SPLIT_Y = 148                         # the lower control strip starts here
SLOT = (22, 30, 268, 60)
DRAWER = (25, 33, 265, 57)
TRAVEL = 106                          # how far the drawer comes out
BED_W, BED_H = 240, 124               # its front edge is the drawer front's top
BED_DISC = (120, 86)                  # disc centre in the bed (middle of what shows when open)
BED_DISC_R = (102, 34)                # the 12 cm recess as seen (rx, ry)
LCD_BEZEL = (286, 26, 498, 140)
LCD = (294, 33, 490, 133)             # 196 x 100: the LcdCd panel
KEY_Y = (184, 202)
KEYS = {                              # name: x0, x1 (all KEY_Y)
    "power": (24, 64),
    "repeat": (176, 204), "random": (212, 240),
    "eject": (290, 320), "play": (326, 356), "pause": (362, 392),
    "stop": (398, 428), "prev": (434, 464), "next": (470, 500),
}
LED = (74, 193)
JACK = (100, 193)
KNOB = (140, 193)
KNOB_R = 10

PPT = 3.6
FONT = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
FONT_R = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
INK = 0.50                            # silk-screen print, light grey (linear)


def text_mask(cv, items):
    """Coverage of printed text on the canvas grid. items: (text, x, y, size,
    bold, anchor) with anchor 'l', 'm' or 'r' on x, y the top of the caps."""
    img = Image.new("L", (cv.X.shape[1], cv.X.shape[0]), 0)
    d = ImageDraw.Draw(img)
    x0, y0, n = float(cv.X[0, 0]) - 0.5 / cv.n, float(cv.Y[0, 0]) - 0.5 / cv.n, cv.n
    for t, x, y, sz, bold, anchor, spacing in items:
        f = ImageFont.truetype(FONT if bold else FONT_R, max(1, int(round(sz * n))))
        cap = f.getbbox("E")[1]
        w = sum(f.getlength(c) for c in t) + spacing * n * (len(t) - 1)
        px = (x - x0) * n - {"l": 0, "m": w / 2, "r": w}[anchor]
        py = (y - y0) * n - cap
        for c in t:
            d.text((px, py), c, font=f, fill=255)
            px += f.getlength(c) + spacing * n
    return np.asarray(img, dtype=np.float32) / 255.0


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
    elif name == "power":
        r = np.hypot(X - cx, Y - cy)
        ang = np.arctan2(X - cx, -(Y - cy))
        ring = np.maximum(np.abs(r - s * 0.42) - s * 0.08, 0.55 - np.abs(ang))
        stem = sd_rrect(X, Y, cx - s * 0.08, cy - s * 0.6, cx + s * 0.08, cy - s * 0.05, 0.2)
        sd = np.minimum(ring, stem)
    else:
        return np.zeros_like(X)
    return cv.cov(sd)


def plate(cv, rng, sd_body, lower):
    """Brushed black aluminium above, satin black below the split."""
    X, Y, n = cv.X, cv.Y, cv.n
    e = np.clip(-sd_body, 0, None)
    B = 2.4
    h = B * np.sqrt(1 - (1 - np.clip(e / B, 0, 1)) ** 2)
    # a V groove along the split
    h = h - 0.9 * np.exp(-((Y - SPLIT_Y) / 0.6) ** 2)
    return h


def build_base(out):
    cv = Canvas(0, 0, CANVAS[0], CANVAS[1], PPT)
    X, Y, n = cv.X, cv.Y, cv.n
    rng = np.random.default_rng(31)

    bx0, by0, bx1, by1 = BODY
    sh = (0.55 * soft(sd_rrect(X, Y - 7, bx0 + 8, by0 + 3, bx1 - 8, by1 - 1, BODY_R), 8.5)
          + 0.45 * soft(sd_rrect(X, Y - 2, bx0 + 1, by0 + 1, bx1 - 1, by1, BODY_R), 2.2))
    edge = np.minimum(np.minimum(X, CANVAS[0] - X), np.minimum(Y, CANVAS[1] - Y))
    cv.over((0, 0, 0), np.clip(sh, 0, 0.9) * smoothstep(0, 5, edge))

    sd_body = sd_rrect(X, Y, *BODY, BODY_R)
    body = cv.cov(sd_body)
    lower = smoothstep(SPLIT_Y - 0.3, SPLIT_Y + 0.3, Y)

    h = plate(cv, rng, sd_body, lower)
    # recesses: drawer slot, LCD window
    sd_slot = sd_rrect(X, Y, *SLOT, 2.0)
    sd_lcd = sd_rrect(X, Y, *LCD_BEZEL, 3.0)
    h = h - 1.6 * (1 - smoothstep(-1.2, 0.0, sd_slot)) - 1.2 * (1 - smoothstep(-1.0, 0.0, sd_lcd))
    # raised keys
    keys = np.zeros_like(X)
    for name, (x0, x1) in KEYS.items():
        sd_k = sd_rrect(X, Y, x0, KEY_Y[0], x1, KEY_Y[1], 2.2)
        kh = 2.0 * np.sqrt(np.clip(1 - (1 - np.clip(-sd_k / 1.6, 0, 1)) ** 2, 0, 1))
        h = np.maximum(h, kh * cv.cov(sd_k) + h * (1 - cv.cov(sd_k)))
        keys = np.maximum(keys, cv.cov(sd_k))
    nx, ny, nz = normals(h, n)

    br = 0.07 * streaks(X.shape, n, rng, 60, 0.25) + 0.05 * streaks(X.shape, n, rng, 9, 0.12)
    sheen = 1 + 0.35 * np.exp(-((X - 160) / 170) ** 2) * (1.1 - 0.6 * Y / CANVAS[1])
    alb_up = 0.030 * (1 + br) * sheen
    alb_lo = 0.020 * (1 + 0.35 * br)
    alb = alb_up * (1 - lower) + alb_lo * lower
    spec = 0.50 * (1 - lower) + 0.22 * lower
    col = alb * (0.28 + 0.72 * lambert(nx, ny, nz)) + spec * blinn(nx, ny, nz, 60) + 0.04 * blinn(nx, ny, nz, 6)
    # keys: satin black plastic, a touch lighter
    kcol = 0.030 * (0.35 + 0.65 * lambert(nx, ny, nz)) + 0.30 * blinn(nx, ny, nz, 30)
    col = col * (1 - keys) + kcol * keys

    # slot interior: nearly black with an ambient falloff (the drawer front sits in it)
    ins = np.clip(-sd_slot, 0, None)
    slot_in = cv.cov(sd_slot)
    col = col * (1 - slot_in) + (0.004 + 0.004 * (1 - np.exp(-ins / 1.5))) * slot_in

    # LCD window: glossy black bezel; the LCD itself is drawn by the scene
    lcd_in = cv.cov(sd_lcd)
    bez = 0.010 * (0.4 + 0.6 * lambert(nx, ny, nz)) + 0.9 * blinn(nx, ny, nz, 80)
    col = col * (1 - lcd_in) + bez * lcd_in

    # jack, knob
    jr = np.hypot(X - JACK[0], Y - JACK[1])
    ring = cv.cov(np.abs(jr - 3.6) - 1.3)
    rh = np.clip(1 - ((jr - 3.6) / 1.3) ** 2, 0, 1) ** 0.5
    rnx, rny, rnz = normals(rh * 1.2, n)
    chrome = 0.12 + 0.35 * lambert(rnx, rny, rnz) + 1.2 * blinn(rnx, rny, rnz, 30)
    col = col * (1 - ring) + chrome * ring
    hole = cv.cov(jr - 2.3)
    col = col * (1 - hole) + 0.002 * hole

    kr = np.hypot(X - KNOB[0], Y - KNOB[1])
    sd_knob = kr - KNOB_R
    kh = 3.0 * np.sqrt(np.clip(1 - (1 - np.clip(-sd_knob / 1.8, 0, 1)) ** 2, 0, 1))
    ang = np.arctan2(Y - KNOB[1], X - KNOB[0])
    knurl = 0.25 * np.cos(ang * 60) * smoothstep(KNOB_R - 2.2, KNOB_R - 1.0, kr)
    knx, kny, knz = normals(kh + knurl, n)
    turned = radial_noise(kr, rng, 0.15, rmax=20)
    kcol2 = 0.05 * (1 + 0.1 * turned) * (0.3 + 0.7 * lambert(knx, kny, knz)) + 0.55 * blinn(knx, kny, knz, 40)
    # the index line, at about "11 o'clock"
    a0 = math.radians(-120)
    u = (X - KNOB[0]) * math.cos(a0) + (Y - KNOB[1]) * math.sin(a0)
    v = -(X - KNOB[0]) * math.sin(a0) + (Y - KNOB[1]) * math.cos(a0)
    line = cv.cov(np.maximum(np.abs(v) - 0.45, np.maximum(3.0 - u, u - (KNOB_R - 2.4))))
    kcol2 = kcol2 * (1 - line) + 0.55 * line
    kn = cv.cov(sd_knob)
    col = col * (1 - kn) + kcol2 * kn
    # the knob's shadow on the plate
    ksh = soft(np.hypot(X - KNOB[0] - LXY[0] * -3 * LSLOPE, Y - KNOB[1] - LXY[1] * -3 * LSLOPE) - KNOB_R, 1.8)
    col = col * (1 - 0.6 * ksh * (1 - kn))

    # LED socket (unlit)
    lr = np.hypot(X - LED[0], Y - LED[1])
    led = cv.cov(lr - 1.9)
    col = col * (1 - led) + 0.012 * led

    rgb = np.repeat(col[..., None], 3, axis=2) * rgb3((0.985, 0.99, 1.02))

    # prints
    items = [
        ("OSMIUM", 24, 76, 11.5, True, "l", 2.6),
        ("CD-90", 268, 76, 9.0, True, "r", 0.6),
        ("COMPACT DISC PLAYER", 24, 92, 5.2, False, "l", 0.9),
        ("1 BIT DAC  ·  8x OVERSAMPLING DIGITAL FILTER", 24, 103, 4.2, False, "l", 0.35),
        ("POWER", 44, 176, 4.4, True, "m", 0.3),
        ("PHONES", 100, 176, 4.4, True, "m", 0.3),
        ("LEVEL", KNOB[0], 176, 4.4, True, "m", 0.3),
        ("REPEAT", 190, 176, 4.4, True, "m", 0.3),
        ("RANDOM", 226, 176, 4.4, True, "m", 0.3),
        ("OPEN/CLOSE", 305, 176, 4.0, True, "m", 0.1),
        ("PLAY", 341, 176, 4.4, True, "m", 0.3),
        ("PAUSE", 377, 176, 4.4, True, "m", 0.3),
        ("STOP", 413, 176, 4.4, True, "m", 0.3),
        ("SKIP", 467, 176, 4.4, True, "m", 0.3),
        ("DIGITAL AUDIO", 392, 161, 5.0, True, "m", 1.4),
    ]
    ink = text_mask(cv, items)
    rgb = rgb * (1 - ink[..., None]) + INK * ink[..., None]
    # the thin rule under OSMIUM and the bracket of SKIP
    # the rule runs between OSMIUM and CD-90, at half the height of the capitals
    def width(t, sz, bold, spacing):
        f = ImageFont.truetype(FONT if bold else FONT_R, 100)
        return sum(f.getlength(c) for c in t) * sz / 100 + spacing * (len(t) - 1)
    fb = ImageFont.truetype(FONT, 100).getbbox("E")
    mid = 76 + (fb[3] - fb[1]) * 11.5 / 100 / 2
    r0 = 24 + width("OSMIUM", 11.5, True, 2.6) + 6
    r1 = 268 - width("CD-90", 9.0, True, 0.6) - 6
    rule = cv.cov(sd_rrect(X, Y, r0, mid - 0.3, r1, mid + 0.3, 0.1))
    skip = cv.cov(sd_rrect(X, Y, 437, 177.5, 458, 178.1, 0.1)) + cv.cov(sd_rrect(X, Y, 476, 177.5, 497, 178.1, 0.1))
    extra = np.clip(rule * 0.55 + skip, 0, 1)
    rgb = rgb * (1 - extra[..., None]) + INK * extra[..., None]
    # symbols on the key caps
    for name, (x0, x1) in KEYS.items():
        if name in ("repeat", "random"):
            continue
        sm = symbol_mask(cv, name, (x0 + x1) / 2, (KEY_Y[0] + KEY_Y[1]) / 2, 6.0)
        rgb = rgb * (1 - sm[..., None]) + 0.60 * sm[..., None]

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
    # a shallow finger recess in the middle of the lower edge
    h = h - 0.6 * np.exp(-(((X - (x0 + x1) / 2) / 18) ** 2 + ((Y - y1 + 3) / 2.2) ** 2))
    nx, ny, nz = normals(h, n)
    br = 0.05 * streaks(X.shape, n, rng, 50, 0.2)
    col = 0.026 * (1 + br) * (0.3 + 0.7 * lambert(nx, ny, nz)) + 0.40 * blinn(nx, ny, nz, 50)
    col = col + 0.015 * np.exp(-((Y - y0 - 1.2) / 0.5) ** 2)
    cv.over(srgb(np.repeat(col[..., None], 3, axis=2)), cv.cov(sd))
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
