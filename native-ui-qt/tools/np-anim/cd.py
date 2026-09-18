#!/usr/bin/env python3
"""Render the images of the "CD" Now Playing animation (qml/AnimCd.qml).

The scene is a top-loading CD player seen straight from above. Everything is
drawn procedurally (signed distance fields for the shapes, a height field for
the bevels and chamfers, simple Lambert + Blinn lighting from the top left),
rendered 2x supersampled and box-filtered down for clean edges. Shadows and
reflections are baked: the kiosk only moves, rotates and fades these quads.

Run it with any Python 3 that has numpy, scipy and Pillow:

    python3 native-ui-qt/tools/np-anim/cd.py [--out DIR]

The output is deterministic (fixed random seeds). DIR defaults to
native-ui-qt/assets/anim/cd/. Files, all positioned in the 520 x 260 point
design of AnimCd.qml (the geometry constants below are mirrored there):

  cd-base.png         the whole player body without the raised right block:
                      drop shadow, brushed top plate, lid rails, the well with
                      its finger notch, turntable, spindle and laser slot
  cd-bridge.png       the raised right block (drawn over the sliding lid, which
                      parks under it): display window, four buttons and
                      the unlit LED
  cd-glass.png        reflection of the display glass, over the progress bar
  cd-play.png         the lit play symbol of the display (with its glow)
  cd-led.png          the lit LED with its glow (fades in while playing)
  cd-lid.png          the smoked acrylic sliding lid with its static reflection
  cd-disc.png         the disc minus its printed label: clear hub, stacking
                      ring, silver mirror band, clear outer rim (turns)
  cd-mask.png         alpha mask of the printed area, for the album artwork
  cd-label.png        generic print used when there is no artwork (turns)
  cd-sheen.png        static rainbow / gloss reflection over the disc
  cd-shadow-near.png  sharp shadow of the disc once it lies on the turntable
  cd-shadow-far.png   soft shadow of the disc while it is still above the well
  cd-puck.png         the machined magnetic clamp
  cd-puck-shadow.png  its shadow
"""
import argparse
import math
import os

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.special import erfc

# ── geometry of the 520 x 260 point design (mirrored in AnimCd.qml) ─────────
CANVAS = (520, 260)
BODY = (4, 8, 516, 232)           # x0, y0, x1, y1
BODY_R = 12
WELL_C = (134, 120)
WELL_R = 100
NOTCH_C = (37, 120)
NOTCH_R = 14
DISC_R = 92
HOLE_R = 11.5
HUB_R = 24.5                      # clear clamping area ends
PRINT_R0 = 34.5                   # printed label (album artwork)
PRINT_R1 = 89.6
PLATTER_R = 27
LID = (20, 15, 248, 225)          # closed position
LID_R = 6
LID_TRAVEL = 238                  # to the right, under the bridge
BRIDGE = (252, 8, 516, 232)
DISPLAY = (286, 40, 482, 108)
DISPLAY_R = 7
PLAY_C = (305, 74)
BAR = (324, 74, 464)              # x0, y, x1 of the progress track
BUTTONS = ((348, 170), (389.33, 170), (430.67, 170), (472, 170))
BUTTON_R = 9.5
LED_C = (305.5, 170)
PUCK_R = 29

# pixels per point of the images (the kiosk scales them to the screen: 2.7
# keeps the big ones under ~1400 px, the disc parts get 3.6 = 4K)
PPT_BIG = 2.7
PPT_DISC = 3.6
SS = 2

LIGHT = np.array([-0.42, -0.62, 0.66])
LIGHT /= np.linalg.norm(LIGHT)
HALF = LIGHT + np.array([0.0, 0.0, 1.0])
HALF /= np.linalg.norm(HALF)
LXY = LIGHT[:2] / np.linalg.norm(LIGHT[:2])       # towards the light, on screen
LSLOPE = np.linalg.norm(LIGHT[:2]) / LIGHT[2]     # horizontal shift per unit of height


# ── helpers ────────────────────────────────────────────────────────────────
def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def sd_rrect(X, Y, x0, y0, x1, y1, r):
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    qx = np.abs(X - cx) - ((x1 - x0) / 2.0 - r)
    qy = np.abs(Y - cy) - ((y1 - y0) / 2.0 - r)
    return (np.hypot(np.maximum(qx, 0), np.maximum(qy, 0))
            + np.minimum(np.maximum(qx, qy), 0) - r)


def sd_circle(X, Y, cx, cy, r):
    return np.hypot(X - cx, Y - cy) - r


def smin(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b * (1 - h) + a * h - k * h * (1 - h)


def soft(sd, sigma):
    """Coverage of a shape blurred by a gaussian (exact for straight edges)."""
    return 0.5 * erfc(sd / (sigma * math.sqrt(2.0)))


def lin(c):
    return np.power(np.clip(c, 0, 1), 2.2)


def srgb(c):
    return np.power(np.clip(c, 0, 1), 1 / 2.2)


def normals(h, n):
    gy, gx = np.gradient(h)
    gx = gx * n
    gy = gy * n
    inv = 1.0 / np.sqrt(gx * gx + gy * gy + 1.0)
    return -gx * inv, -gy * inv, inv


def lambert(nx, ny, nz):
    return np.clip(nx * LIGHT[0] + ny * LIGHT[1] + nz * LIGHT[2], 0, None) / LIGHT[2]


def blinn(nx, ny, nz, shin):
    s = np.clip(nx * HALF[0] + ny * HALF[1] + nz * HALF[2], 0, 1) ** shin
    flat = HALF[2] ** shin
    return np.clip((s - flat) / (1 - flat), 0, 1)


def rgb3(c):
    return np.asarray(c, dtype=np.float32).reshape(1, 1, 3)


class Canvas:
    """A premultiplied RGBA float image over a rectangle of the design,
    sampled SS x SS per output pixel."""

    def __init__(self, x0, y0, w, h, ppt, ss=SS):
        self.W = int(round(w * ppt))
        self.H = int(round(h * ppt))
        self.ss = ss
        kx, ky = self.W / w, self.H / h
        self.n = kx * ss                                   # samples per point
        xs = x0 + (np.arange(self.W * ss, dtype=np.float32) + 0.5) / (kx * ss)
        ys = y0 + (np.arange(self.H * ss, dtype=np.float32) + 0.5) / (ky * ss)
        self.X, self.Y = np.meshgrid(xs, ys)
        self.img = np.zeros((self.H * ss, self.W * ss, 4), dtype=np.float32)

    def cov(self, sd):
        return np.clip(0.5 - sd * self.n, 0.0, 1.0)

    def over(self, rgb, alpha):
        """Composite a straight-alpha sRGB layer (rgb HxWx3 or colour) on top."""
        a = np.clip(alpha, 0, 1).astype(np.float32)[..., None]
        rgb = np.broadcast_to(np.asarray(rgb, dtype=np.float32), self.img[..., :3].shape)
        self.img[..., :3] = rgb * a + self.img[..., :3] * (1 - a)
        self.img[..., 3:] = a + self.img[..., 3:] * (1 - a)

    def image(self):
        s = self.ss
        p = self.img.reshape(self.H, s, self.W, s, 4).mean(axis=(1, 3))
        a = p[..., 3:4]
        rgb = np.where(a > 1e-6, p[..., :3] / np.maximum(a, 1e-6), 0)
        out = np.concatenate([rgb, a], axis=2)
        return Image.fromarray(np.round(np.clip(out, 0, 1) * 255).astype(np.uint8), "RGBA")


def streaks(shape, n, rng, length_pt, width_pt):
    """Brushed metal: noise stretched along x (box filter passes ~ gaussian)."""
    a = rng.standard_normal(shape).astype(np.float32)
    size = max(1, int(length_pt * n))
    for _ in range(3):
        a = ndimage.uniform_filter1d(a, size, axis=1, mode="wrap")
    if width_pt * n > 0.3:
        a = ndimage.gaussian_filter1d(a, width_pt * n, axis=0)
    a -= a.mean()
    return a / (a.std() + 1e-6)


def radial_noise(r, rng, scale_pt, seed_len=4096, rmax=120.0):
    """Turned (lathe) finish: a random function of the radius only."""
    k = int(rmax / scale_pt)
    v = ndimage.gaussian_filter1d(rng.standard_normal(k * 4).astype(np.float32), 2.0)
    v /= v.std() + 1e-6
    idx = np.clip(r / rmax * (k * 4 - 1), 0, k * 4 - 1)
    return np.interp(idx.ravel(), np.arange(k * 4), v).reshape(r.shape).astype(np.float32)


def save(img, out, name):
    path = os.path.join(out, name)
    img.save(path, optimize=True)
    print(f"{name:22s} {img.size[0]:5d}x{img.size[1]:<5d} {os.path.getsize(path):8d} B")


# ── the player body ────────────────────────────────────────────────────────
def well_sd(X, Y):
    return smin(sd_circle(X, Y, *WELL_C, WELL_R), sd_circle(X, Y, *NOTCH_C, NOTCH_R), 6.0)


def build_base(out):
    cv = Canvas(0, 0, CANVAS[0], CANVAS[1], PPT_BIG)
    X, Y, n = cv.X, cv.Y, cv.n
    rng = np.random.default_rng(11)

    # soft drop shadow on whatever is below, faded out before the canvas edge
    bx0, by0, bx1, by1 = BODY
    sh = (0.55 * soft(sd_rrect(X, Y - 7, bx0 + 8, by0 + 3, bx1 - 8, by1 - 1, BODY_R), 8.5)
          + 0.45 * soft(sd_rrect(X, Y - 2, bx0 + 1, by0 + 1, bx1 - 1, by1, BODY_R), 2.2))
    edge = np.minimum(np.minimum(X, CANVAS[0] - X), np.minimum(Y, CANVAS[1] - Y))
    cv.over((0, 0, 0), np.clip(sh, 0, 0.9) * smoothstep(0, 5, edge))

    sd_body = sd_rrect(X, Y, *BODY, BODY_R)
    body = cv.cov(sd_body)
    sd_w = well_sd(X, Y)
    in_well = cv.cov(sd_w)

    # ── well floor ──
    r = np.hypot(X - WELL_C[0], Y - WELL_C[1])
    depth = 10.0
    sx = X + LXY[0] * depth * LSLOPE
    sy = Y + LXY[1] * depth * LSLOPE
    lip_shadow = smoothstep(-3.0, 4.0, well_sd(sx, sy))
    inside = np.clip(-sd_w, 0, None)
    ao = 1 - 0.6 * np.exp(-inside / 4.0)
    floor_l = 0.0055 * (0.30 + 0.70 * (1 - lip_shadow)) * ao
    floor_l = floor_l * (1 + 0.25 * smoothstep(40, 100, r) * (1 - lip_shadow))
    # platter shadow on the floor (cast away from the light)
    ph = 5.0
    psd = sd_circle(X + LXY[0] * ph * LSLOPE, Y + LXY[1] * ph * LSLOPE, *WELL_C, PLATTER_R)
    floor_l = floor_l * (1 - 0.75 * soft(psd, 2.0))
    floor = np.repeat(floor_l[..., None], 3, axis=2) * rgb3((1.0, 1.0, 1.04))

    # laser slot, pointing up and to the right
    th = math.radians(-38)
    dx, dy = X - WELL_C[0], Y - WELL_C[1]
    u = dx * math.cos(th) + dy * math.sin(th)
    v = -dx * math.sin(th) + dy * math.cos(th)
    slot_sd = sd_rrect(u, v, 36, -8.5, 86, 8.5, 3.0)
    slot = cv.cov(slot_sd)
    s_in = np.clip(-slot_sd, 0, None)
    slot_l = 0.0018 * (0.35 + 0.65 * (1 - np.exp(-s_in / 2.5)))
    floor = floor * (1 - slot[..., None]) + slot_l[..., None] * slot[..., None]
    # two polished guide rods
    for vc in (-5.2, 5.2):
        dv = (v - vc) / 1.05
        m = cv.cov(np.abs(v - vc) - 1.05) * cv.cov(sd_rrect(u, v, 37, -9, 85, 9, 1))
        nzr = np.sqrt(np.clip(1 - dv * dv, 0, 1))
        # rod normal in screen space: across the slot direction
        ax, ay = -math.sin(th), math.cos(th)
        rnx, rny = dv * ax, dv * ay
        rod = 0.16 * (0.25 + 0.75 * lambert(rnx, rny, nzr)) + 1.4 * blinn(rnx, rny, nzr, 40)
        rod = np.repeat(rod[..., None], 3, axis=2)
        floor = floor * (1 - m[..., None]) + rod * m[..., None]
    # optical pickup sled with its lens
    sled_sd = sd_rrect(u, v, 45, -3.9, 58, 3.9, 1.2)
    sled = cv.cov(sled_sd)
    sled_l = 0.022 * (0.6 + 0.4 * smoothstep(-4, 0, v))
    floor = floor * (1 - sled[..., None]) + sled_l[..., None] * sled[..., None]
    lr = np.hypot(u - 51.5, v)
    lens = cv.cov(lr - 2.3)
    lens_col = (rgb3((0.004, 0.004, 0.010))
                + rgb3((0.10, 0.07, 0.35)) * np.exp(-((lr - 1.4) / 0.35) ** 2)[..., None]
                + rgb3((0.9, 0.9, 1.0)) * np.exp(-(np.hypot(u - 51.5 + 0.7, v - 0.6)) ** 2 / 0.12)[..., None])
    ring = cv.cov(np.abs(lr - 2.6) - 0.35)
    floor = floor * (1 - lens[..., None]) + lens_col * lens[..., None]
    floor = floor * (1 - ring[..., None]) + 0.12 * ring[..., None]

    # turntable: rubber mat ring, aluminium rim, chrome centring cone
    sd_p = r - PLATTER_R
    ph_ = 1.5 * np.sqrt(1 - (1 - np.clip(-sd_p / 1.5, 0, 1)) ** 2)
    ph_ = ph_ + 0.05 * np.sin(r * 2 * math.pi / 0.85) * smoothstep(13, 14, r) * (1 - smoothstep(23, 24, r))
    pnx, pny, pnz = normals(ph_, n)
    rim = smoothstep(24.0, 24.4, r)
    alb_p = 0.012 * (1 - rim) + 0.20 * rim * (1 + 0.1 * radial_noise(r, rng, 0.25))
    plat = alb_p * (0.30 + 0.70 * lambert(pnx, pny, pnz)) + (0.2 + 1.2 * rim) * blinn(pnx, pny, pnz, 50)
    plat = np.repeat(plat[..., None], 3, axis=2)
    m = cv.cov(sd_p)
    floor = floor * (1 - m[..., None]) + plat * m[..., None]
    gap = cv.cov(np.abs(r - 12.0) - 0.7)
    floor = floor * (1 - gap[..., None]) + 0.003 * gap[..., None]
    cone_h = 3.2 * (1 - np.clip(r / 11.2, 0, 1))
    cnx, cny, cnz = normals(cone_h, n)
    lamc = lambert(cnx, cny, cnz)
    chrome = 0.05 + 0.30 * np.clip(lamc - 0.6, 0, None) + 1.1 * blinn(cnx, cny, cnz, 18)
    chrome = chrome * (0.8 + 0.2 * np.cos(r * 1.3))
    chrome = np.where(r < 2.6, 0.03 + 0.5 * np.exp(-(np.hypot(X - WELL_C[0] + 0.8, Y - WELL_C[1] + 0.9)) ** 2 / 0.4), chrome)
    m = cv.cov(r - 11.2)
    floor = floor * (1 - m[..., None]) + np.repeat(chrome[..., None], 3, axis=2) * m[..., None]

    cv.over(srgb(floor), body * in_well)

    # ── top plate: brushed dark aluminium ──
    e = np.clip(-sd_body, 0, None)
    B = 3.2
    h = B * np.sqrt(1 - (1 - np.clip(e / B, 0, 1)) ** 2)
    rails = np.zeros_like(h)
    for yg in (LID[1] - 1.8, LID[3] + 1.8):
        xm = smoothstep(BODY[0] + 8, BODY[0] + 12, X) * (1 - smoothstep(BRIDGE[0] + 2, BRIDGE[0] + 6, X))
        rails = rails + np.clip(1 - ((Y - yg) / 0.75) ** 2, 0, 1) ** 0.5 * xm
    h = h - 0.8 * rails
    h = h - 1.8 * (1 - smoothstep(0.0, 2.2, sd_w))
    nx, ny, nz = normals(h, n)
    br = 0.07 * streaks(X.shape, n, rng, 60, 0.25) + 0.05 * streaks(X.shape, n, rng, 9, 0.12)
    sheen = 1 + 0.40 * np.exp(-((X - 175) / 150) ** 2) * (1.15 - 0.6 * Y / CANVAS[1])
    alb = 0.034 * (1 + br) * sheen * (1 - 0.55 * rails)
    plate = alb * (0.28 + 0.72 * lambert(nx, ny, nz)) + 0.55 * blinn(nx, ny, nz, 60) + 0.05 * blinn(nx, ny, nz, 6)
    plate = np.repeat(plate[..., None], 3, axis=2) * rgb3((0.98, 0.995, 1.02))
    cv.over(srgb(plate), body * (1 - in_well))
    save(cv.image(), out, "cd-base.png")


# the 90s front panel of the full-screen view (vintage): a window for the
# grey-green LCD (LcdCd.qml, 196 x 100) instead of the black display, symbols
# on the keys and silk-screen prints
LCD_WIN = (283, 27, 485, 133)
LCD_AT = (286, 30)


def build_bridge(out, vintage=False):
    x0 = BRIDGE[0] - 8
    cv = Canvas(x0, 0, CANVAS[0] - x0, CANVAS[1], PPT_BIG)
    X, Y, n = cv.X, cv.Y, cv.n
    rng = np.random.default_rng(23)

    # the opening the lid slides into: a dark gap along the left edge
    ym = smoothstep(BODY[1] + 2, BODY[1] + 8, Y) * (1 - smoothstep(BODY[3] - 8, BODY[3] - 2, Y))
    gap = np.exp(-np.clip(BRIDGE[0] - X, 0, None) / 2.2) * (X < BRIDGE[0] + 1) * ym
    cv.over((0, 0, 0), 0.65 * gap)

    rr = np.where(X < (BRIDGE[0] + BRIDGE[2]) / 2, 3.0, BODY_R).astype(np.float32)
    sd_b = sd_rrect(X, Y, *BRIDGE, rr)
    cov_b = cv.cov(sd_b)
    e = np.clip(-sd_b, 0, None)
    B = 2.8
    h = B * np.sqrt(1 - (1 - np.clip(e / B, 0, 1)) ** 2)

    sd_d = sd_rrect(X, Y, *LCD_WIN, 3.0) if vintage else sd_rrect(X, Y, *DISPLAY, DISPLAY_R)
    h = h - 1.6 * (1 - smoothstep(0.0, 1.8, sd_d))


    btn_gap = np.zeros_like(h)
    for bc in BUTTONS:
        rb = np.hypot(X - bc[0], Y - bc[1])
        btn_gap = np.maximum(btn_gap, smoothstep(BUTTON_R - 0.2, BUTTON_R + 0.4, rb) * (1 - smoothstep(BUTTON_R + 0.9, BUTTON_R + 1.6, rb)))
    h = h - 1.0 * btn_gap
    rl = np.hypot(X - LED_C[0], Y - LED_C[1])
    h = h - 0.6 * (1 - smoothstep(2.9, 3.6, rl))

    nx, ny, nz = normals(h, n)
    grain = ndimage.gaussian_filter(rng.standard_normal(X.shape).astype(np.float32), 0.7)
    grain /= grain.std() + 1e-6
    # bead-blasted black anodising: a fine grain and a broad satin reflection
    # that fades from the top left, with one soft diagonal band
    u = (X - BRIDGE[0]) / (BRIDGE[2] - BRIDGE[0])
    t = (Y - BRIDGE[1]) / (BRIDGE[3] - BRIDGE[1])
    env = (1.45 - 0.75 * smoothstep(0.0, 1.0, (u * 0.7 + t * 0.9) / 1.6)
           + 0.40 * np.exp(-((u * 0.85 + t * 0.40 - 0.42) / 0.13) ** 2))
    alb = 0.0092 * (1 + 0.04 * grain) * env
    alb = alb * (1 - 0.7 * btn_gap)
    top = alb * (0.25 + 0.75 * lambert(nx, ny, nz)) + 0.45 * blinn(nx, ny, nz, 70) + 0.04 * blinn(nx, ny, nz, 6)
    top = np.repeat(top[..., None], 3, axis=2)

    # display window: black glass, faint unlit play symbol and track
    inside = np.clip(-sd_d, 0, None)
    glass = 0.0010 + 0.0025 * smoothstep(0, 30, Y - DISPLAY[1])
    glass = glass * (1 - 0.6 * np.exp(-inside / 2.0))
    glass = np.repeat(glass[..., None], 3, axis=2)
    if not vintage:
        tri = play_sd(X, Y)
        unlit = cv.cov(tri) * 0.8 + cv.cov(sd_rrect(X, Y, BAR[0], BAR[1] - 1.0, BAR[2], BAR[1] + 1.0, 1.0))
        glass = glass + np.clip(unlit, 0, 1)[..., None] * rgb3((0.010, 0.0075, 0.003))
    dm = cv.cov(sd_d)
    top = top * (1 - dm[..., None]) + glass * dm[..., None]

    # buttons: machined aluminium, a polished chamfer round a face turned in
    # fine concentric rings (whose light gathers in a bow tie towards the lamp)
    phl = math.atan2(LXY[1], LXY[0])
    for bc in BUTTONS:
        dx, dy = X - bc[0], Y - bc[1]
        rb = np.hypot(dx, dy)
        ch = 1.5
        rf = BUTTON_R - ch
        hb = ch * np.sqrt(1 - (1 - np.clip((BUTTON_R - rb) / ch, 0, 1)) ** 2) - 0.18 * (1 - np.clip(rb / rf, 0, 1) ** 2)
        bnx, bny, bnz = normals(hb, n)
        lam_b = lambert(bnx, bny, bnz)
        phi = np.arctan2(dy, dx)
        aniso = np.exp(-(np.sin(phi - phl) ** 2) / 0.018) * smoothstep(0.8, 5.5, rb)
        rings = radial_noise(rb, rng, 0.07, rmax=12)
        face = 0.050 * (1 + 0.25 * rings) * (0.45 + 0.55 * lam_b) + 0.30 * aniso * (1 + 0.35 * rings)
        chamfer = 0.14 * (0.25 + 0.75 * lam_b) + 1.3 * blinn(bnx, bny, bnz, 35)
        fm = smoothstep(rf + 0.25, rf - 0.25, rb)
        cap = face * fm + chamfer * (1 - fm) + 0.5 * blinn(bnx, bny, bnz, 80)
        cap = np.repeat(cap[..., None], 3, axis=2) * rgb3((1.0, 1.0, 1.025))
        m = cv.cov(rb - BUTTON_R)
        top = top * (1 - m[..., None]) + cap * m[..., None]

    # the unlit LED: amber glass bead in a chrome bezel
    bez = cv.cov(np.abs(rl - 2.9) - 0.45)
    top = top * (1 - bez[..., None]) + (0.10 + 0.5 * np.exp(-((Y - LED_C[1] + 2.3) ** 2 + (X - LED_C[0] + 1.6) ** 2) / 1.5))[..., None] * bez[..., None]
    bead = cv.cov(rl - 2.45)
    bead_c = rgb3((0.022, 0.011, 0.002)) + rgb3((0.5, 0.45, 0.4)) * np.exp(-((X - LED_C[0] + 0.8) ** 2 + (Y - LED_C[1] + 0.9) ** 2) / 0.25)[..., None]
    top = top * (1 - bead[..., None]) + bead_c * bead[..., None]

    if vintage:
        from cdfront import symbol_mask, text_mask
        ink = 0.50
        # symbols engraved in the caps: play/pause (a small triangle and two
        # bars side by side), stop, skip back, skip forward
        marks = [symbol_mask(cv, "play", BUTTONS[0][0] - 2.6, BUTTONS[0][1], 4.0),
                 symbol_mask(cv, "pause", BUTTONS[0][0] + 3.0, BUTTONS[0][1], 4.0)]
        marks += [symbol_mask(cv, name, bc[0], bc[1], 5.0) for name, bc in zip(("stop", "prev", "next"), BUTTONS[1:])]
        for sm in marks:
            top = top * (1 - sm[..., None]) + 0.012 * sm[..., None]
        items = [
            ("PLAY/PAUSE", BUTTONS[0][0], 153, 4.0, True, "m", 0.1),
            ("STOP", BUTTONS[1][0], 153, 4.0, True, "m", 0.25),
            ("SKIP", (BUTTONS[2][0] + BUTTONS[3][0]) / 2, 153, 4.0, True, "m", 0.25),
            ("PLAY", LED_C[0], 153, 4.0, True, "m", 0.25),
            ("OSMIUM", 290, 206, 9.5, True, "l", 2.2),
            ("CD-80T", 484, 206, 7.0, True, "r", 0.5),
            ("COMPACT DISC PLAYER", 290, 218, 4.4, False, "l", 0.8),
            ("TOP LOADING  \u00b7  1 BIT DAC", 484, 218, 4.0, False, "r", 0.3),
        ]
        prints = text_mask(cv, items)
        top = top * (1 - prints[..., None]) + ink * prints[..., None]
    cv.over(srgb(top), cov_b)
    save(cv.image(), out, "cd-bridge-v.png" if vintage else "cd-bridge.png")


def play_sd(X, Y):
    """A rounded play triangle centred on PLAY_C, 9 points tall."""
    cx, cy = PLAY_C
    hgt = 4.5
    # equilateral-ish: vertices (-3.4,-4.5) (-3.4,4.5) (4.4,0)
    px, py = X - cx, np.abs(Y - cy)
    a = np.array([-3.4, hgt])
    b = np.array([4.4, 0.0])
    ex, ey = b - a
    ln = math.hypot(ex, ey)
    nxv, nyv = -ey / ln, ex / ln          # outward normal of the slanted edge
    d1 = (px - a[0]) * nxv + (py - a[1]) * nyv
    d2 = -(px - a[0])
    return np.maximum(d1, d2) + 0.0


def build_glass(out):
    x0, y0, x1, y1 = DISPLAY
    cv = Canvas(x0, y0, x1 - x0, y1 - y0, PPT_BIG)
    X, Y = cv.X, cv.Y
    sd = sd_rrect(X, Y, *DISPLAY, DISPLAY_R)
    m = cv.cov(sd)
    t = (Y - y0) / (y1 - y0)
    u = (X - x0) / (x1 - x0)
    diag = (u * 3.4 - t)          # diagonal coordinate
    refl = 0.09 * (1 - smoothstep(0.0, 0.48, t)) * (1 - 0.5 * u)
    refl = refl + 0.06 * np.exp(-((diag - 0.9) / 0.22) ** 2) + 0.035 * np.exp(-((diag - 1.35) / 0.05) ** 2)
    inner = np.clip(-sd, 0, None)
    cv.over((1, 1, 1), np.clip(refl, 0, 1) * m)
    cv.over((0, 0, 0), 0.55 * np.exp(-inner / 1.4) * smoothstep(0.35, 0.0, t) * m)
    cv.over((1, 1, 1), 0.10 * np.exp(-((inner - 0.6) / 0.35) ** 2) * smoothstep(0.6, 1.0, t) * m)
    save(cv.image(), out, "cd-glass.png")


def build_play(out):
    cx, cy = PLAY_C
    cv = Canvas(cx - 9, cy - 9, 18, 18, PPT_DISC)
    X, Y = cv.X, cv.Y
    sd = play_sd(X, Y)
    glow = 0.45 * soft(sd, 1.4)
    cv.over((0.95, 0.72, 0.25), glow)
    core = cv.cov(sd)
    col = np.zeros(X.shape + (3,), np.float32) + rgb3((1.0, 0.86, 0.52))
    col = col + (1 - smoothstep(-1.2, 0, sd))[..., None] * 0 + smoothstep(-0.2, -2.0, sd)[..., None] * rgb3((0.0, 0.08, 0.15))
    cv.over(np.clip(col, 0, 1), core)
    save(cv.image(), out, "cd-play.png")


def build_led(out):
    cx, cy = LED_C
    cv = Canvas(cx - 14, cy - 14, 28, 28, PPT_DISC)
    X, Y = cv.X, cv.Y
    r = np.hypot(X - cx, Y - cy)
    cv.over((0.83, 0.62, 0.18), 0.22 * np.exp(-(r / 7.0) ** 2))
    cv.over((0.95, 0.72, 0.25), 0.55 * np.exp(-(r / 3.4) ** 2))
    bead = cv.cov(r - 2.45)
    c = np.zeros(X.shape + (3,), np.float32) + rgb3((1.0, 0.72, 0.22))
    c = c + (np.exp(-(r / 1.3) ** 2))[..., None] * rgb3((0.0, 0.22, 0.45))
    c = c + np.exp(-((X - cx + 0.8) ** 2 + (Y - cy + 0.9) ** 2) / 0.25)[..., None] * 0.6
    cv.over(np.clip(c, 0, 1), bead)
    save(cv.image(), out, "cd-led.png")


def build_lid(out):
    x0, y0, x1, y1 = LID
    m_ = 3
    cv = Canvas(x0 - m_, y0 - m_, x1 - x0 + 2 * m_, y1 - y0 + 2 * m_, PPT_BIG)
    X, Y = cv.X, cv.Y
    sd = sd_rrect(X, Y, *LID, LID_R)
    m = cv.cov(sd)
    e = np.clip(-sd, 0, None)
    u = (X - x0) / (x1 - x0)
    t = (Y - y0) / (y1 - y0)

    # thin contact shadow of the lid on the plate
    cv.over((0, 0, 0), 0.35 * soft(sd - 0.3, 0.9) * (1 - m))
    # smoked acrylic body
    tint = 0.30 + 0.05 * t
    cv.over((0.012, 0.013, 0.017), tint * m)
    # static window-like reflection: one broad soft band and a fine line
    diag = u * 0.9 + t * 0.55
    refl = (0.050 * np.exp(-((diag - 0.42) / 0.14) ** 2)
            + 0.028 * np.exp(-((diag - 0.70) / 0.030) ** 2)
            + 0.020 * (1 - smoothstep(0.0, 0.30, diag)))
    cv.over((0.85, 0.88, 0.95), refl * m)
    # polished edges: the outward normal decides how much light they catch
    gx, gy = np.gradient(sd)
    gl = np.sqrt(gx * gx + gy * gy) + 1e-6
    onx, ony = gx / gl, gy / gl
    lit = np.clip(-(onx * LXY[0] + ony * LXY[1]), 0, 1)
    lit = np.clip(onx * LXY[0] + ony * LXY[1], 0, 1)
    band = np.exp(-((e - 0.9) / 0.55) ** 2)
    cv.over((1, 1, 1), (0.10 + 0.55 * lit) * band * m)
    inner = np.exp(-((e - 3.2) / 0.45) ** 2)
    cv.over((1, 1, 1), (0.03 + 0.10 * lit) * inner * m)
    cv.over((0, 0, 0), 0.55 * np.exp(-e / 0.35) * m)
    # finger grip: a few fine grooves near the left edge
    gxc = x0 + 9.0
    for i in range(7):
        yc = (y0 + y1) / 2 + (i - 3) * 2.6
        g = cv.cov(sd_rrect(X, Y, gxc - 3.0, yc - 0.35, gxc + 3.0, yc + 0.35, 0.35))
        cv.over((0, 0, 0), 0.45 * g)
        g2 = cv.cov(sd_rrect(X, Y, gxc - 3.0, yc + 0.35, gxc + 3.0, yc + 0.85, 0.25))
        cv.over((1, 1, 1), 0.12 * g2)
    save(cv.image(), out, "cd-lid.png")


# ── the disc ───────────────────────────────────────────────────────────────
def disc_canvas(radius=DISC_R):
    return Canvas(-radius, -radius, 2 * radius, 2 * radius, PPT_DISC)


def ring(cv, r, a, b):
    """Coverage of the annulus a <= r <= b."""
    return cv.cov(a - r) * cv.cov(r - b)


def build_disc(out):
    cv = disc_canvas()
    X, Y = cv.X, cv.Y
    r = np.hypot(X, Y)
    rng = np.random.default_rng(5)
    # clear polycarbonate hub, a little milky towards the stacking ring
    hub = ring(cv, r, HOLE_R, HUB_R)
    cv.over((0.80, 0.83, 0.87), hub * (0.10 + 0.08 * smoothstep(HOLE_R, HUB_R, r)))
    cv.over((1, 1, 1), 0.40 * np.exp(-((r - HOLE_R - 0.5) / 0.45) ** 2) * hub)
    cv.over((1, 1, 1), 0.30 * np.exp(-((r - 21.6) / 0.35) ** 2) * hub)
    cv.over((0, 0, 0), 0.40 * np.exp(-((r - 22.5) / 0.40) ** 2) * hub)
    # silver mirror band (radially symmetric: its reflections are in the sheen)
    band = ring(cv, r, HUB_R, PRINT_R0 + 0.8)
    rn = radial_noise(r, rng, 0.3, rmax=40)
    silver = 0.50 + 0.10 * np.sin((r - HUB_R) / (PRINT_R0 - HUB_R) * math.pi) + 0.03 * rn
    col = np.repeat(silver[..., None], 3, axis=2) * rgb3((0.97, 0.98, 1.0))
    cv.over(col, band)
    cv.over((0, 0, 0), 0.45 * np.exp(-((r - HUB_R - 0.3) / 0.35) ** 2) * band)
    cv.over((1, 1, 1), 0.25 * np.exp(-((r - HUB_R - 1.1) / 0.4) ** 2) * band)
    # soft ink edges of the print
    pr = ring(cv, r, PRINT_R0, PRINT_R1)
    cv.over((0, 0, 0), pr * (0.30 * np.exp(-(r - PRINT_R0) / 1.2) + 0.28 * np.exp(-(PRINT_R1 - r) / 1.4)))
    # clear outer rim
    rim = ring(cv, r, PRINT_R1 - 0.2, DISC_R)
    cv.over((0.78, 0.81, 0.85), rim * 0.22)
    cv.over((1, 1, 1), rim * 0.36 * np.exp(-((DISC_R - r - 0.5) / 0.45) ** 2))
    cv.over((0, 0, 0), rim * 0.35 * np.exp(-((r - PRINT_R1) / 0.4) ** 2))
    save(cv.image(), out, "cd-disc.png")

    # alpha mask of the printed area
    m = ring(cv, r, PRINT_R0 - 0.3, PRINT_R1 + 0.3)
    s = cv.ss
    a = m.reshape(cv.H, s, cv.W, s).mean(axis=(1, 3))
    la = np.stack([np.full_like(a, 1.0), a], axis=2)
    save(Image.fromarray(np.round(la * 255).astype(np.uint8), "LA"), out, "cd-mask.png")


def build_label(out):
    """The generic print for albums without artwork: graphite with a fine
    guilloche and a gold arc that makes the rotation visible."""
    cv = disc_canvas()
    X, Y = cv.X, cv.Y
    r = np.hypot(X, Y)
    phi = np.arctan2(Y, X)
    rng = np.random.default_rng(7)
    area = ring(cv, r, PRINT_R0 - 0.3, PRINT_R1 + 0.3)
    base = 0.034 + 0.020 * smoothstep(PRINT_R1, PRINT_R0, r)
    base = base * (1 - 0.30 * ring(cv, r, 77.0, 86.5))            # a darker printed band
    base = base * (1 + 0.07 * np.sin(r * 2 * math.pi / 1.4)) * (1 + 0.03 * radial_noise(r, rng, 0.2, rmax=100))
    col = np.repeat(base[..., None], 3, axis=2) * rgb3((1.0, 0.99, 0.97))
    cv.over(srgb(col), area)
    cv.over((0.83, 0.69, 0.22), 0.35 * ring(cv, r, 76.6, 77.1))    # gold hairline
    # gold arc, tapered at both ends
    def arc(r0, r1, a0, a1, alpha, color):
        span = (a1 - a0) % 360
        rel = np.mod(phi - math.radians(a0), 2 * math.pi)
        tt = rel / math.radians(span)
        inside = (tt >= 0) & (tt <= 1)
        taper = np.where(inside, smoothstep(0, 0.18, tt) * smoothstep(1, 0.72, tt), 0)
        rr = ring(cv, r, r0, r1)
        shade = 0.75 + 0.25 * np.cos((r - r0) / (r1 - r0) * math.pi - math.pi / 2)
        c = np.repeat(shade[..., None], 3, axis=2) * rgb3(color)
        cv.over(c, rr * taper * alpha)
    arc(60.5, 65.0, 190, 30, 1.0, (0.86, 0.71, 0.24))
    arc(69.5, 70.5, 60, 150, 0.65, (0.82, 0.82, 0.84))
    arc(45.5, 46.5, 250, 340, 0.60, (0.86, 0.71, 0.24))
    save(cv.image(), out, "cd-label.png")


def build_sheen(out):
    cv = disc_canvas()
    X, Y = cv.X, cv.Y
    r = np.hypot(X, Y)
    phi = np.arctan2(Y, X)
    phl = math.atan2(LXY[1], LXY[0])
    disc = ring(cv, r, HOLE_R, DISC_R)
    band = ring(cv, r, HUB_R, PRINT_R0) + ring(cv, r, PRINT_R1, DISC_R)
    # diffraction streak along the light axis, on both sides of the centre
    d1 = np.angle(np.exp(1j * (phi - phl)))
    d2 = np.angle(np.exp(1j * (phi - phl - math.pi)))
    streak = np.exp(-(d1 / 0.16) ** 2) + 0.8 * np.exp(-(d2 / 0.14) ** 2)
    hue = np.mod(0.05 + r / DISC_R * 1.3 + np.where(np.abs(d1) < np.abs(d2), d1, -d2) * 0.9, 1.0)
    rgb = np.stack([np.clip(np.abs(hue * 6 - 3) - 1, 0, 1),
                    np.clip(2 - np.abs(hue * 6 - 2), 0, 1),
                    np.clip(2 - np.abs(hue * 6 - 4), 0, 1)], axis=2)
    rgb = 0.35 + 0.65 * rgb
    strength = (0.16 + 0.40 * band) * streak * smoothstep(HOLE_R, HUB_R, r)
    cv.over(rgb, np.clip(strength, 0, 1) * disc)
    # broad lacquer gloss towards the light
    gx, gy = X + 30, Y + 40
    gloss = 0.10 * np.exp(-(gx * gx + gy * gy) / (2 * 34.0 ** 2))
    cv.over((1, 1, 1), gloss * disc)
    save(cv.image(), out, "cd-sheen.png")


def build_shadows(out):
    pad = 30
    R = DISC_R + pad
    for name, sigma, alpha, ppt in (("cd-shadow-near.png", 1.6, 0.85, 2.4), ("cd-shadow-far.png", 8.0, 0.60, 1.6)):
        cv = Canvas(-R, -R, 2 * R, 2 * R, ppt, ss=1)
        r = np.hypot(cv.X, cv.Y)
        a = soft(r - DISC_R, sigma) - soft(r - HOLE_R, sigma)
        cv.over((0, 0, 0), np.clip(a, 0, 1) * alpha)
        save(cv.image(), out, name)
    R = PUCK_R + 18
    cv = Canvas(-R, -R, 2 * R, 2 * R, 2.4, ss=1)
    r = np.hypot(cv.X, cv.Y)
    cv.over((0, 0, 0), soft(r - PUCK_R + 0.5, 2.4) * 0.8)
    save(cv.image(), out, "cd-puck-shadow.png")


def build_puck(out):
    R = PUCK_R + 3
    cv = Canvas(-R, -R, 2 * R, 2 * R, PPT_DISC)
    X, Y, n = cv.X, cv.Y, cv.n
    r = np.hypot(X, Y)
    phi = np.arctan2(Y, X)
    rng = np.random.default_rng(3)
    e = np.clip(PUCK_R - r, 0, None)
    B = 3.0
    h = B * np.sqrt(1 - (1 - np.clip(e / B, 0, 1)) ** 2)
    h = h - 0.35 * np.exp(-((r - 22.0) / 0.45) ** 2)             # inlay groove
    h = h - 0.9 * (1 - smoothstep(3.5, 5.5, r))                    # centre dimple
    nx, ny, nz = normals(h, n)
    phl = math.atan2(LXY[1], LXY[0])
    aniso = np.exp(-(np.sin(phi - phl) ** 2) / 0.035) * smoothstep(3, 10, r)
    turned = radial_noise(r, rng, 0.12, rmax=40)
    alb = 0.17 * (1 + 0.08 * turned)
    col = alb * (0.35 + 0.65 * lambert(nx, ny, nz)) + 0.16 * aniso * (1 + 0.4 * turned) + 1.0 * blinn(nx, ny, nz, 40)
    col = np.repeat(col[..., None], 3, axis=2) * rgb3((1.0, 1.0, 1.02))
    gold = ring(cv, r, 21.4, 22.6)
    gcol = rgb3((0.60, 0.40, 0.07)) * (0.45 + 0.55 * lambert(nx, ny, nz))[..., None] + (0.5 * aniso + 1.2 * blinn(nx, ny, nz, 30))[..., None] * rgb3((1.0, 0.85, 0.45))
    col = col * (1 - gold[..., None]) + gcol * gold[..., None]
    m = cv.cov(r - PUCK_R)
    cv.over(srgb(col), m)
    save(cv.image(), out, "cd-puck.png")


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.normpath(os.path.join(here, "..", "..", "assets", "anim", "cd")))
    ap.add_argument("--only", default="", help="comma separated builder names (debug)")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    builders = {"base": build_base, "bridge": build_bridge,
                "bridge-v": lambda o: build_bridge(o, vintage=True), "glass": build_glass, "play": build_play,
                "led": build_led, "lid": build_lid, "disc": build_disc, "label": build_label,
                "sheen": build_sheen, "shadows": build_shadows, "puck": build_puck}
    only = [s for s in args.only.split(",") if s]
    for k, f in builders.items():
        if not only or k in only:
            f(args.out)


if __name__ == "__main__":
    main()
