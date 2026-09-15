#!/usr/bin/env python3
"""Render the turntable of the "Vinyl" Now Playing animation (AnimVinyl.qml).

The Now Playing screen can show, in place of the VU meters, a record played
on a turntable seen from above. Everything that looks like material, light
or shadow is baked here, once, into PNG layers; the kiosk only moves a few
flat textures (the label and the strobe dots turn, the tone arm swings).

  vinyl.py [OUT_DIR]      default: native-ui-qt/assets/anim/vinyl/

Deterministic (fixed seeds, no inputs, no fonts: the engraved name is drawn
with strokes). Needs numpy, scipy and Pillow; about a minute on one core. All geometry is written in "base points": the scene is designed at
520 x 260 points and AnimVinyl.qml scales it uniformly. The constants the
QML needs (centre, pivot, arm length, radii, image rectangles) are printed at
the end and must match the ones at the top of AnimVinyl.qml.

Layers, bottom to top, as AnimVinyl.qml stacks them:
  plinth_shadow.png  soft drop shadow of the plinth (low resolution, blurry)
  plinth.png         walnut plinth, arm board, pivot base, arm rest, cue
                     lever, anti-skate knob, start/stop and speed buttons,
                     the LED (off), the engraved name plate and the
                     platter's shadow
  platter.png        machined platter rim + rubber mat, light baked in (static:
                     it is round, only the dots show that it turns)
  dots.png           the strobe dots on the rim            (rotates while slow)
  dots_blur.png      the dots blurred by the speed          (static, fades in)
  record_shadow.png  the record's shadow while it is lowered (moves/fades)
  label.png          generic label when there is no artwork (rotates)
  label_shade.png    light on the label: edge vignette, spindle shadow (static)
  record.png         the record with its grooves and the static anisotropic
                     sheen baked in, transparent where the label shows
  spindle.png        the spindle tip                         (static)
  arm_shadow.png     tone arm shadow                         (moves with the arm)
  arm.png            tone arm, drawn at rest (pointing down), turns around
                     its pivot
  led_on.png         the lit LED with its glow              (fades)

Light comes from the upper left, a little in front of the viewer; every
shadow falls to the lower right.
"""
import math
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

# ─── scene geometry (base points) ──────────────────────────────────────────
SCENE_W, SCENE_H = 520, 260
MM = 193.0 / 302.0                       # points per millimetre: a 12" record is 193 pt

PLINTH = (80.0, 12.0, 360.0, 232.0)      # x, y, w, h
PLINTH_R = 9.0
C = (200.0, 128.0)                       # platter / spindle centre
R_PLATTER = 104.0
R_MAT = 93.6
R_DOTS = 99.6
N_DOTS = 120                             # 3 deg pitch: at 200 deg/s a 30 Hz tick moves 6.67 deg,
                                         # the dots creep forward slowly like a real strobe
R_RECORD = 96.5
R_LEADIN = 94.4                          # where the lead-in groove starts
R_START = 92.6                           # first music groove (progress 0)
R_END = 40.5                             # last music groove (progress 1)
R_RUNOUT = 35.4
R_LABEL = 32.0
R_SPINDLE = 2.4
BANDS = (82.4, 71.8, 63.0, 52.6)         # silent gaps between tracks

ARM_L = 229.0 * MM                       # pivot -> stylus (effective length)
ARM_D = 211.0 * MM                       # pivot -> spindle (overhang 18 mm)
_th = math.radians(25.0)
P = (C[0] + ARM_D * math.cos(_th), C[1] - ARM_D * math.sin(_th))   # arm pivot
OFFSET_DEG = 24.0                        # headshell offset angle (tangent to the groove)
HEAD_BACK = 22.0                         # stylus -> headshell collar, along the headshell
# The arm's own frame: pivot at 0,0, the arm at rest points down (+y). The
# headshell is turned by OFFSET_DEG (clockwise on screen) so the cartridge is
# tangent to the groove; the straight tube runs from the pivot to its collar.
_phi = math.radians(OFFSET_DEG)
HEAD_AXIS = (-math.sin(_phi), math.cos(_phi))
STYLUS = (0.0, ARM_L)
COLLAR = (STYLUS[0] - HEAD_BACK * HEAD_AXIS[0], STYLUS[1] - HEAD_BACK * HEAD_AXIS[1])
TUBE_LEN = math.hypot(*COLLAR)
REST_T = 0.80                            # the arm rest holds the tube at 80 % of its length

# front left controls
BTN_START = (106.0, 219.0)
BTN_33 = (130.5, 229.0)
BTN_45 = (147.5, 232.0)
LED = (125.0, 205.5)
NAMEPLATE = (404.0, 229.5)

LIGHT = np.array([-0.42, -0.55, 0.72], dtype=np.float32)
LIGHT /= np.linalg.norm(LIGHT)
HALF = LIGHT + np.array([0, 0, 1], dtype=np.float32)
HALF /= np.linalg.norm(HALF)
SHADOW_DIR = (-LIGHT[0] / LIGHT[2], -LIGHT[1] / LIGHT[2])            # offset per point of height

DPP = 3.5          # pixels per point: devScale 3.6 is a 4K panel
SS = 2             # supersampling factor

# colours (0..1, sRGB)
GOLD = np.array([212, 175, 55], dtype=np.float32) / 255
ALU = np.array([0.62, 0.62, 0.63], dtype=np.float32)
BLACK_ANO = np.array([0.085, 0.085, 0.09], dtype=np.float32)


# ─── small rendering kit ───────────────────────────────────────────────────
class Grid:
    """Pixel-centre coordinates, in base points, of a supersampled image."""

    def __init__(self, x, y, w, h, dpp=DPP, ss=SS):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.W = max(1, int(round(w * dpp)))
        self.H = max(1, int(round(h * dpp)))
        self.ss = ss
        nx = self.W * ss / w
        ny = self.H * ss / h
        self.px = 1.0 / nx                     # one supersampled pixel, in points
        xs = (x + (np.arange(self.W * ss, dtype=np.float32) + 0.5) / nx).astype(np.float32)
        ys = (y + (np.arange(self.H * ss, dtype=np.float32) + 0.5) / ny).astype(np.float32)
        self.X, self.Y = np.meshgrid(xs, ys)
        self.shape = self.X.shape


class Canvas:
    """Premultiplied RGBA, composited with "over"."""

    def __init__(self, g):
        self.g = g
        self.rgb = np.zeros(g.shape + (3,), dtype=np.float32)
        self.a = np.zeros(g.shape, dtype=np.float32)

    def over(self, color, alpha):
        alpha = np.clip(alpha, 0, 1).astype(np.float32)
        col = np.asarray(color, dtype=np.float32)
        if col.ndim == 1:
            col = col.reshape(1, 1, 3)
        self.rgb = col * alpha[..., None] + self.rgb * (1 - alpha[..., None])
        self.a = alpha + self.a * (1 - alpha)

    def shadow(self, cover, sigma_pt, opacity):
        s = ndimage.gaussian_filter(cover.astype(np.float32), sigma_pt / self.g.px, mode="constant")
        self.over((0, 0, 0), s * opacity)

    def image(self):
        g = self.g
        ss = g.ss
        rgb = self.rgb.reshape(g.H, ss, g.W, ss, 3).mean(axis=(1, 3))
        a = self.a.reshape(g.H, ss, g.W, ss).mean(axis=(1, 3))
        out = np.zeros((g.H, g.W, 4), dtype=np.float32)
        nz = a > 1e-6
        out[..., :3][nz] = rgb[nz] / a[nz][:, None]
        out[..., 3] = a
        return Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8), "RGBA")


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def cov(d, g):
    """Coverage of a signed distance field (negative inside), one pixel of AA."""
    return np.clip(0.5 - d / g.px, 0, 1)


def sd_circle(X, Y, cx, cy, r):
    return np.hypot(X - cx, Y - cy) - r


def sd_rrect(X, Y, cx, cy, hw, hh, r):
    qx = np.abs(X - cx) - hw + r
    qy = np.abs(Y - cy) - hh + r
    return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r


def sd_segment(X, Y, ax, ay, bx, by, r):
    pax, pay = X - ax, Y - ay
    bax, bay = bx - ax, by - ay
    h = np.clip((pax * bax + pay * bay) / max(bax * bax + bay * bay, 1e-9), 0, 1)
    return np.hypot(pax - bax * h, pay - bay * h) - r


def noise(g, cell_x, cell_y, seed, order=3):
    """Smooth value noise in 0..1 with cells of cell_x x cell_y points."""
    rng = np.random.default_rng(seed)
    gw = int(math.ceil(g.w / cell_x)) + 4
    gh = int(math.ceil(g.h / cell_y)) + 4
    grid = rng.random((gh, gw)).astype(np.float32)
    cx = (g.X[0] - g.x) / cell_x + 1.5
    cy = (g.Y[:, 0] - g.y) / cell_y + 1.5
    rows = ndimage.map_coordinates(grid, np.vstack([np.repeat(cy, gw), np.tile(np.arange(gw), cy.size)]),
                                   order=order, mode="nearest").reshape(cy.size, gw)
    out = ndimage.map_coordinates(rows, np.vstack([np.repeat(np.arange(cy.size), cx.size), np.tile(cx, cy.size)]),
                                  order=order, mode="nearest").reshape(cy.size, cx.size)
    return out.astype(np.float32)


def noise1(values, cell, seed, order=3):
    """Smooth 1-D value noise in 0..1 sampled at values (points)."""
    rng = np.random.default_rng(seed)
    n = int(np.max(values) / cell) + 8
    grid = rng.random(n).astype(np.float32)
    return ndimage.map_coordinates(grid, [values.ravel() / cell + 2], order=order,
                                   mode="nearest").reshape(values.shape).astype(np.float32)


def normals_from_height(h, g):
    gy, gx = np.gradient(h, g.px)
    n = np.dstack([-gx, -gy, np.ones_like(h)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    return n.astype(np.float32)


def light(base, n, amb=0.30, kd=0.85, ks=0.35, shin=30.0):
    ndl = np.clip(n @ LIGHT, 0, 1)[..., None]
    ndh = np.clip(n @ HALF, 0, 1)[..., None]
    b = np.asarray(base, dtype=np.float32)
    return b * (amb + kd * ndl) + ks * ndh ** shin


def aniso(g, cx, cy, sharp):
    """Kajiya-Kay highlight of concentric (turned) grooves: the two opposite
    radial wedges pointing at the light."""
    th = np.arctan2(g.Y - cy, g.X - cx)
    th_h = math.atan2(HALF[1], HALF[0])
    s = np.sin(th - th_h)
    return np.exp(-sharp * s * s).astype(np.float32)


def bevel_height(inside, b):
    """Rounded edge profile: 0 at the outline, b at b points inside."""
    t = np.clip(inside, 0, b)
    return np.sqrt(np.maximum(b * b - (b - t) ** 2, 0)).astype(np.float32)


def save(img, out_dir, name):
    path = os.path.join(out_dir, name)
    img.save(path, optimize=True)
    return path


# ─── plinth ────────────────────────────────────────────────────────────────
def walnut(g):
    """Dark oiled walnut, the grain running along the long side."""
    X, Y = g.X, g.Y
    warp = (noise(g, 90, 22, 11) - 0.5) * 12.0 + (noise(g, 30, 6, 12) - 0.5) * 2.4
    v = Y + warp + 0.018 * (X - 260)
    period = 3.4 + 1.8 * noise(g, 140, 50, 13)
    phase = v / period + 6.0 * noise(g, 220, 70, 14)
    f = phase - np.floor(phase)
    late = smoothstep(0.50, 0.86, f) * (1 - smoothstep(0.90, 1.0, f))       # late wood bands
    late = late * (0.35 + 0.65 * noise(g, 60, 7, 18))                        # some rings fainter
    fibre = noise(g, 22, 0.32, 15, order=1)                                 # fine streaks
    pores = smoothstep(0.82, 0.96, noise(g, 3.5, 0.28, 16, order=1))        # dark flecks
    figure = noise(g, 40, 12, 17)                                           # slow light drift
    hue = noise(g, 110, 60, 19)[..., None]                                  # chocolate <-> honey
    light_wood = np.array([0.245, 0.158, 0.100], np.float32) * (1 - hue) + np.array([0.262, 0.165, 0.092], np.float32) * hue
    dark_wood = np.array([0.100, 0.062, 0.042], np.float32) * (1 - hue) + np.array([0.118, 0.068, 0.038], np.float32) * hue
    t = (0.60 - 0.42 * late - 0.16 * (fibre - 0.5) - 0.26 * pores + 0.34 * (figure - 0.5))
    t = np.clip(t, 0, 1)[..., None]
    return dark_wood + (light_wood - dark_wood) * t


def render_plinth_shadow(out_dir):
    x, y, w, h = PLINTH
    g = Grid(x - 24, y - 16, w + 48, h + 44, dpp=1.0, ss=4)
    cv = Canvas(g)
    body = cov(sd_rrect(g.X, g.Y, x + w / 2 + 2.5, y + h / 2 + 5.0, w / 2, h / 2, PLINTH_R), g)
    cv.shadow(body, 7.0, 0.80)
    body = cov(sd_rrect(g.X, g.Y, x + w / 2 + 0.8, y + h / 2 + 1.5, w / 2, h / 2, PLINTH_R), g)
    cv.shadow(body, 2.0, 0.55)
    return save(cv.image(), out_dir, "plinth_shadow.png"), (g.x, g.y, g.w, g.h)


def part_shadow(cv, sdf_fn, height, opacity=0.75):
    """Soft shadow of a part `height` points above the surface."""
    g = cv.g
    ox, oy = SHADOW_DIR[0] * height, SHADOW_DIR[1] * height
    c = cov(sdf_fn(g.X - ox, g.Y - oy), g)
    cv.shadow(c, 0.35 * height + 0.5, opacity)


def machined_disc(g, cx, cy, r, base, sheen=0.55, sharp=9.0, seed=0, rings=0.06):
    """Top face of a turned metal part: fine concentric tool marks with the
    anisotropic highlight of turned metal."""
    rr = np.hypot(g.X - cx, g.Y - cy)
    marks = noise1(rr, 0.18, seed, order=1)
    col = np.asarray(base, dtype=np.float32) * (1 - rings + 2 * rings * marks)[..., None]
    hi = aniso(g, cx, cy, sharp) * (0.75 + 0.5 * marks)
    return col + sheen * hi[..., None] * np.array([1.0, 1.0, 1.02], dtype=np.float32)


def render_plinth(out_dir):
    x, y, w, h = PLINTH
    g = Grid(x, y, w, h)
    cv = Canvas(g)
    X, Y = g.X, g.Y
    px, py = P

    # the plinth: walnut, oiled satin finish, rounded top edge
    d = sd_rrect(X, Y, x + w / 2, y + h / 2, w / 2, h / 2, PLINTH_R)
    body = cov(d, g)
    hgt = bevel_height(-d, 3.2)
    n = normals_from_height(hgt, g)
    wood = walnut(g)
    col = light(wood, n, amb=0.55, kd=0.62, ks=0.10, shin=14)
    # a broad soft reflection of the room light on the satin finish
    glow = np.exp(-(((X - 150) / 170) ** 2 + ((Y - 30) / 120) ** 2))[..., None]
    col = col + glow * np.array([0.045, 0.036, 0.030], dtype=np.float32)
    # the polished edge catches the light on the upper and left sides
    edge = smoothstep(3.2, 0.0, -d) * body
    col = col + (edge * np.clip(n @ LIGHT - 0.55, 0, 1) * 0.9)[..., None] * np.array([0.9, 0.75, 0.6], dtype=np.float32)
    cv.over(col, body)

    # platter shadow (the platter is round: the shadow never moves)
    cv.shadow(cov(sd_circle(X, Y, C[0] + 2.6, C[1] + 3.4, R_PLATTER), g), 4.5, 0.80)
    cv.shadow(cov(sd_circle(X, Y, C[0] + 0.5, C[1] + 0.7, R_PLATTER + 0.2), g), 1.0, 0.70)
    # the bearing well: a dark gap round the platter
    cv.over((0.02, 0.015, 0.01), cov(sd_circle(X, Y, C[0], C[1], R_PLATTER + 1.2), g) * 0.85)

    # arm board: black anodised disc flush with the wood, polished chamfer
    r_board = 27.0
    cv.shadow(cov(sd_circle(X, Y, px, py, r_board + 0.6), g), 0.8, 0.8)
    dd = sd_circle(X, Y, px, py, r_board)
    board = cov(dd, g)
    hb = bevel_height(-dd, 1.4)
    nb = normals_from_height(hb, g)
    top = machined_disc(g, px, py, r_board, BLACK_ANO * 1.2, sheen=0.10, sharp=6.0, seed=21)
    cham = smoothstep(1.4, 0.2, -dd)[..., None]
    colb = light(top, nb, amb=0.8, kd=0.3, ks=0.0) * (1 - cham) + light(ALU * 0.9, nb, amb=0.25, kd=0.8, ks=0.6, shin=18) * cham
    cv.over(colb, board)

    # pivot base: turned aluminium pillar with a knurled height-adjust ring
    part_shadow(cv, lambda X_, Y_: sd_circle(X_, Y_, px, py, 13.0), 5.0, 0.85)
    dp = sd_circle(X, Y, px, py, 13.0)
    base = cov(dp, g)
    rr = np.hypot(X - px, Y - py)
    ang = np.arctan2(Y - py, X - px)
    knurl = 0.5 + 0.5 * np.cos(ang * 90)
    ring = smoothstep(10.2, 10.8, rr)
    hk = bevel_height(-dp, 1.0) + ring * 0.25 * knurl + (1 - ring) * 1.2
    nk = normals_from_height(hk, g)
    top = machined_disc(g, px, py, 10.5, ALU * 0.75, sheen=0.35, sharp=8.0, seed=22)
    ringcol = ALU * (0.55 + 0.25 * knurl)[..., None]
    colp = light(top * (1 - ring[..., None]) + ringcol * ring[..., None], nk, amb=0.45, kd=0.65, ks=0.45, shin=24)
    cv.over(colp, base)
    cv.over((0.02, 0.02, 0.02), cov(sd_circle(X, Y, px, py, 10.3), g) * smoothstep(9.6, 10.3, rr) * 0.8)

    # anti-skate knob on the arm board
    kx, ky = px + 17.5, py + 13.5
    part_shadow(cv, lambda X_, Y_: sd_circle(X_, Y_, kx, ky, 4.4), 4.0, 0.8)
    dk = sd_circle(X, Y, kx, ky, 4.4)
    ka = np.arctan2(Y - ky, X - kx)
    hk = bevel_height(-dk, 0.8) + 0.12 * (0.5 + 0.5 * np.cos(ka * 36)) * smoothstep(3.0, 3.6, np.hypot(X - kx, Y - ky))
    colk = light(machined_disc(g, kx, ky, 3.4, ALU * 0.8, sheen=0.35, seed=23), normals_from_height(hk, g), amb=0.45, kd=0.6, ks=0.5, shin=26)
    cv.over(colk, cov(dk, g))
    cv.over(GOLD * 0.9, cov(sd_circle(X, Y, kx - 2.1, ky - 2.1, 0.55), g))

    # arm rest: a post under the tube and a cradle across it
    rest_x, rest_y = px + COLLAR[0] * REST_T, py + COLLAR[1] * REST_T
    part_shadow(cv, lambda X_, Y_: sd_circle(X_, Y_, rest_x + 1.5, rest_y, 3.6), 7.0, 0.8)
    part_shadow(cv, lambda X_, Y_: sd_rrect(X_, Y_, rest_x, rest_y, 7.5, 2.6, 2.4), 9.0, 0.75)
    dpost = sd_circle(X, Y, rest_x + 1.5, rest_y + 0.8, 3.4)
    cv.over(light(ALU * 0.7, normals_from_height(bevel_height(-dpost, 3.4), g), amb=0.35, kd=0.7, ks=0.6, shin=30), cov(dpost, g))
    dc = sd_rrect(X, Y, rest_x, rest_y, 7.5, 2.6, 2.4)
    cv.over(light(ALU * 0.8, normals_from_height(bevel_height(-dc, 2.2), g), amb=0.35, kd=0.75, ks=0.7, shin=34), cov(dc, g))
    dpad = sd_rrect(X, Y, rest_x, rest_y, 3.6, 1.7, 1.2)
    cv.over(light(np.array([0.05, 0.05, 0.05], np.float32), normals_from_height(bevel_height(-dpad, 1.0), g), amb=0.8, kd=0.4, ks=0.1, shin=8), cov(dpad, g))

    # cue lever: pillar, lever arm, knob
    cx_, cy_ = rest_x + 24.0, rest_y - 26.0
    kx2, ky2 = cx_ + 4.0, cy_ + 21.0
    part_shadow(cv, lambda X_, Y_: np.minimum(sd_circle(X_, Y_, cx_, cy_, 4.6), sd_segment(X_, Y_, cx_, cy_, kx2, ky2, 1.3)), 8.0, 0.75)
    part_shadow(cv, lambda X_, Y_: sd_circle(X_, Y_, kx2, ky2, 2.9), 9.0, 0.7)
    dcp = sd_circle(X, Y, cx_, cy_, 4.6)
    cv.over(light(machined_disc(g, cx_, cy_, 4.6, ALU * 0.75, sheen=0.35, seed=24), normals_from_height(bevel_height(-dcp, 1.4), g), amb=0.4, kd=0.7, ks=0.5, shin=28), cov(dcp, g))
    dl = sd_segment(X, Y, cx_, cy_, kx2, ky2, 1.3)
    cv.over(light(ALU * 0.85, normals_from_height(bevel_height(-dl, 1.3), g), amb=0.35, kd=0.75, ks=0.8, shin=40), cov(dl, g))
    dkn = sd_circle(X, Y, kx2, ky2, 2.9)
    cv.over(light(np.array([0.06, 0.06, 0.065], np.float32), normals_from_height(bevel_height(-dkn, 2.9), g), amb=0.5, kd=0.6, ks=0.55, shin=40), cov(dkn, g))

    # front left: start/stop, the LED, 33 and 45
    for (bx, by, br, hgt_, gold) in ((BTN_START[0], BTN_START[1], 9.0, 2.0, False),
                                     (BTN_33[0], BTN_33[1], 4.8, 1.6, True),
                                     (BTN_45[0], BTN_45[1], 4.8, 1.6, False)):
        # a tight machined recess round the button, darker on the side away from the light
        drec = sd_circle(X, Y, bx, by, br + 0.9)
        cv.over((0.012, 0.009, 0.007), cov(drec, g) * 0.92)
        rim = smoothstep(-0.5, 0.0, drec) * cov(drec - 0.35, g)
        facing = np.clip(-((X - bx) * LIGHT[0] + (Y - by) * LIGHT[1]) / (br + 0.9), 0, 1)
        cv.over((0.55, 0.42, 0.30), rim * facing * 0.35)
        part_shadow(cv, lambda X_, Y_, bx=bx, by=by, br=br: sd_circle(X_, Y_, bx, by, br), hgt_ * 0.6, 0.85)
        db = sd_circle(X, Y, bx, by, br)
        hb = bevel_height(-db, 1.1) + 0.2 * (1 - smoothstep(0, br * 0.9, np.hypot(X - bx, Y - by)))
        colb = light(machined_disc(g, bx, by, br, ALU * 0.78, sheen=0.42, sharp=8.0, seed=int(bx)), normals_from_height(hb, g),
                     amb=0.45, kd=0.65, ks=0.45, shin=26)
        cv.over(colb, cov(db, g))
        if gold:   # the selected speed: a fine gold ring
            rrb = np.hypot(X - bx, Y - by)
            cv.over(GOLD * 0.95, smoothstep(br * 0.52, br * 0.58, rrb) * (1 - smoothstep(br * 0.64, br * 0.70, rrb)) * 0.9)
    lx, ly = LED
    cv.over((0.0, 0.0, 0.0), cov(sd_circle(X, Y, lx, ly, 2.4), g) * 0.9)
    dled = sd_circle(X, Y, lx, ly, 1.7)
    ledcol = light(np.array([0.16, 0.10, 0.03], np.float32), normals_from_height(bevel_height(-dled, 1.7), g), amb=0.6, kd=0.3, ks=0.9, shin=60)
    cv.over(ledcol, cov(dled, g))

    # front right: a small black anodised plate with the name engraved
    nx, ny = NAMEPLATE
    nhw, nhh = 19.0, 4.6
    part_shadow(cv, lambda X_, Y_: sd_rrect(X_, Y_, nx, ny, nhw, nhh, 1.4), 0.8, 0.8)
    dpl = sd_rrect(X, Y, nx, ny, nhw, nhh, 1.4)
    letters = text_sdf(X, Y, nx, ny, 3.6, 0.42)
    engraved = smoothstep(0.12, -0.12, letters)
    hpl = bevel_height(-dpl, 0.8) - 0.30 * engraved
    brushed = 0.9 + 0.1 * noise(g, 9.0, 0.08, 71, order=1)
    plate = BLACK_ANO * 1.5 * brushed[..., None]
    plate = plate * (1 - engraved[..., None]) + (GOLD * 0.42) * engraved[..., None]
    cv.over(light(plate, normals_from_height(hpl, g), amb=0.6, kd=0.45, ks=0.35, shin=22), cov(dpl, g))

    return save(cv.image(), out_dir, "plinth.png"), (g.x, g.y, g.w, g.h)


def _glyphs(h):
    """OSMIUM as stroke centre lines (lists of points), in a box h high whose
    baseline is +h/2 and cap line -h/2; returns [(width, [polyline, ...])]."""
    def arc(cx, cy, rx, ry, a0, a1, n=24):
        t = np.linspace(math.radians(a0), math.radians(a1), n)
        return list(zip(cx + rx * np.cos(t), cy + ry * np.sin(t)))
    O = (h * 0.98, [arc(0, 0, h * 0.49, h * 0.5, 0, 360, 40)])
    sw = h * 0.70
    S = (sw, [arc(0, -h / 4, sw / 2, h / 4, -25, -270, 20) + arc(0, h / 4, sw / 2, h / 4, -90, 155, 20)])
    mw = h * 0.92
    M = (mw, [[(-mw / 2, h / 2), (-mw / 2, -h / 2), (0, h * 0.22), (mw / 2, -h / 2), (mw / 2, h / 2)]])
    I = (0.0, [[(0, -h / 2), (0, h / 2)]])
    uw = h * 0.76
    U = (uw, [[(-uw / 2, -h / 2)] + arc(0, h / 2 - uw / 2, uw / 2, uw / 2, 180, 0, 20) + [(uw / 2, -h / 2)]])
    return [O, S, M, I, U, M]


def text_sdf(X, Y, cx, cy, h, stroke, tracking=0.62):
    glyphs = _glyphs(h)
    total = sum(w for w, _ in glyphs) + tracking * h * (len(glyphs) - 1)
    x = cx - total / 2
    d = np.full(X.shape, 1e3, np.float32)
    for w, lines in glyphs:
        gx = x + w / 2
        for pl in lines:
            for (ax, ay), (bx, by) in zip(pl[:-1], pl[1:]):
                d = np.minimum(d, sd_segment(X, Y, gx + ax, cy + ay, gx + bx, cy + by, stroke / 2))
        x += w + tracking * h
    return d


# ─── platter, strobe dots ──────────────────────────────────────────────────
def disc_grid(r, dpp=DPP, ss=SS, pad=0.5):
    return Grid(C[0] - r - pad, C[1] - r - pad, 2 * (r + pad), 2 * (r + pad), dpp=dpp, ss=ss)


def render_platter(out_dir):
    g = disc_grid(R_PLATTER)
    cv = Canvas(g)
    X, Y = g.X, g.Y
    rr = np.hypot(X - C[0], Y - C[1])
    d = rr - R_PLATTER
    # rim: turned aluminium, rounded outer edge, a fine engraved line
    h = bevel_height(-d, 2.2)
    h = h - 0.10 * np.exp(-((rr - 102.2) / 0.22) ** 2)
    n = normals_from_height(h, g)
    marks = noise1(rr, 0.12, 31, order=1) * 0.6 + noise1(rr, 0.9, 32) * 0.4
    base = ALU * (0.50 + 0.14 * marks)[..., None]
    hi = aniso(g, C[0], C[1], 14.0) * (0.55 + 0.45 * marks)
    col = light(base, n, amb=0.40, kd=0.55, ks=0.45, shin=24) + (0.40 * hi)[..., None]
    cv.over(col, cov(d, g))
    # the step down to the mat
    cv.over((0, 0, 0), smoothstep(R_MAT + 1.1, R_MAT + 0.2, rr) * 0.75 * cov(d, g))
    # rubber mat: fine concentric ribs, a smooth centre
    dm = rr - R_MAT
    ribs = 0.5 + 0.5 * np.cos(rr / 1.25 * 2 * math.pi)
    centre = smoothstep(36.0, 34.0, rr)
    hm = (1 - centre) * ribs * 0.18
    nm = normals_from_height(hm, g)
    mat = np.array([0.045, 0.045, 0.048], np.float32) * (0.95 + 0.1 * noise(g, 1.2, 1.2, 33))[..., None]
    colm = light(mat, nm, amb=0.9, kd=0.25, ks=0.06, shin=10) + (0.035 * aniso(g, C[0], C[1], 5.0) * (1 - centre))[..., None]
    cv.over(colm, cov(dm, g))
    return save(cv.image(), out_dir, "platter.png"), (g.x, g.y, g.w, g.h)


DOT_R = 0.62
DOT_ALPHA = 0.85


def render_dots(out_dir):
    """The strobe dots, and the same dots as the eye sees them at speed: a
    blurred ring. AnimVinyl.qml turns the dots while the platter is slow and
    crossfades to the (still) blurred ring as it gets up to speed, so a 30 Hz
    tick never shows them strobing backwards."""
    g = disc_grid(R_PLATTER)
    X, Y = g.X, g.Y
    dx, dy = X - C[0], Y - C[1]
    rr = np.hypot(dx, dy)
    ang = np.arctan2(dy, dx)
    pitch = 2 * math.pi / N_DOTS
    a0 = np.round(ang / pitch) * pitch
    # distance to the nearest dot centre (along the ring and across it)
    along = (ang - a0) * R_DOTS
    across = rr - R_DOTS
    band = np.abs(across) < 3
    cv = Canvas(g)
    cv.over((0.02, 0.02, 0.02), cov(np.hypot(along, across) - DOT_R, g) * band * DOT_ALPHA)
    dots = save(cv.image(), out_dir, "dots.png"), (g.x, g.y, g.w, g.h)
    # the average of a dot row round the ring: chord length / pitch
    step = 2 * math.pi * R_DOTS / N_DOTS
    chord = 2 * np.sqrt(np.maximum(DOT_R ** 2 - across ** 2, 0)) / step
    chord = ndimage.gaussian_filter(chord, 0.5 * g.ss)
    cv = Canvas(g)
    cv.over((0.02, 0.02, 0.02), chord * DOT_ALPHA * band)
    save(cv.image(), out_dir, "dots_blur.png")
    return dots


# ─── record ────────────────────────────────────────────────────────────────
def render_record_shadow(out_dir):
    pad = 14.0
    g = Grid(C[0] - R_RECORD - pad, C[1] - R_RECORD - pad, 2 * (R_RECORD + pad), 2 * (R_RECORD + pad), dpp=1.5, ss=2)
    cv = Canvas(g)
    cv.shadow(cov(sd_circle(g.X, g.Y, C[0], C[1], R_RECORD), g), 3.2, 1.0)
    return save(cv.image(), out_dir, "record_shadow.png"), (g.x, g.y, g.w, g.h)


def render_record(out_dir):
    g = disc_grid(R_RECORD)
    cv = Canvas(g)
    X, Y = g.X, g.Y
    rr = np.hypot(X - C[0], Y - C[1])
    d = rr - R_RECORD
    inside = cov(d, g) * cov(R_LABEL - rr, g)

    # zones
    grooves = smoothstep(R_END - 0.15, R_END + 0.15, rr) * smoothstep(R_START + 0.15, R_START - 0.15, rr)
    leadin = smoothstep(R_START, R_START + 0.1, rr) * smoothstep(R_LEADIN + 0.2, R_LEADIN - 0.1, rr)
    runout = smoothstep(R_RUNOUT - 0.1, R_RUNOUT + 0.1, rr) * smoothstep(R_END + 0.1, R_END - 0.1, rr)
    gaps = np.zeros_like(rr)
    for b in BANDS:
        gaps = np.maximum(gaps, np.exp(-((rr - b) / 0.42) ** 4))
    grooves = grooves * (1 - gaps)
    # modulation of the grooves: loud and quiet passages reflect differently
    mod = 0.50 + 0.30 * noise1(rr, 1.1, 41) + 0.20 * noise1(rr, 0.22, 42, order=1)
    spiral_lead = 0.5 + 0.5 * np.cos((rr - R_START) / 0.45 * 2 * math.pi)
    spiral_run = np.exp(-((((rr - R_RUNOUT) / 1.62) % 1.0 - 0.5) / 0.10) ** 2)

    # height: the raised rim bead and the label pad
    h = bevel_height(-d, 1.3) + 0.35 * smoothstep(R_RECORD - 2.4, R_RECORD - 1.2, rr) * smoothstep(R_RECORD - 0.2, R_RECORD - 1.0, rr)
    h = h + 0.25 * smoothstep(R_LABEL + 2.2, R_LABEL + 1.2, rr)
    n = normals_from_height(h, g)

    vinyl = np.array([0.018, 0.018, 0.020], np.float32)
    col = light(vinyl, n, amb=1.0, kd=0.15, ks=0.55, shin=60)
    # The anisotropic sheen: the grooves reflect the light as two opposite
    # radial wedges, a broad glow with a brighter core; the side towards the
    # light is brighter. Baked here because the record never turns on screen.
    side = np.cos(np.arctan2(Y - C[1], X - C[0]) - math.atan2(HALF[1], HALF[0]))
    side = 0.72 + 0.28 * side
    broad = aniso(g, C[0], C[1], 3.5) * side
    mid = aniso(g, C[0], C[1], 18.0) * side
    core = aniso(g, C[0], C[1], 110.0) * side
    # the reflection gets a little wider towards the outside of the record
    outer = smoothstep(R_END, R_START, rr)
    groove_light = 0.07 * broad + (0.30 + 0.10 * outer) * mid * mod + 0.30 * core * (0.6 + 0.4 * mod)
    col = col + (grooves * groove_light
                 + leadin * (0.05 * broad + (0.22 + 0.12 * spiral_lead) * mid)
                 + runout * (0.02 * broad + (0.06 + 0.30 * spiral_run) * mid)
                 + gaps * (0.015 * broad + 0.05 * core))[..., None] * np.array([0.96, 0.975, 1.0], np.float32)
    # broad soft reflection of the room light on the gloss (smooth areas show it best)
    smooth = 1 - 0.6 * grooves
    blob = np.exp(-(((X - (C[0] - 40)) / 42) ** 2 + ((Y - (C[1] - 50)) / 26) ** 2))
    col = col + (0.035 * blob * smooth)[..., None]
    # label edge shadow on the dead wax
    col = col * (1 - 0.5 * smoothstep(R_LABEL + 1.2, R_LABEL, rr))[..., None]
    cv.over(col, inside)
    return save(cv.image(), out_dir, "record.png"), (g.x, g.y, g.w, g.h)


LABEL_BOX = R_LABEL + 1.0          # label images are squares of 2 * LABEL_BOX points


def render_label(out_dir, name="label.png", gold_paper=True):
    """The label used when the album has no artwork: satin gold paper with
    dark print, no words; asymmetric so the turning shows."""
    g = Grid(C[0] - LABEL_BOX, C[1] - LABEL_BOX, 2 * LABEL_BOX, 2 * LABEL_BOX)
    cv = Canvas(g)
    X, Y = g.X - C[0], g.Y - C[1]
    rr = np.hypot(X, Y)
    grain = (0.94 + 0.08 * noise(g, 0.45, 0.45, 51, order=1) + 0.04 * noise(g, 6.0, 6.0, 52))[..., None]
    if gold_paper:
        paper = np.array([0.70, 0.56, 0.24], np.float32) * grain
        ink = np.array([0.09, 0.075, 0.05], np.float32)
    else:
        paper = np.array([0.075, 0.072, 0.070], np.float32) * grain
        ink = GOLD * 0.92
    cv.over(paper, np.ones(g.shape, np.float32))

    def ring(r, w):
        return smoothstep(r - w / 2 - g.px, r - w / 2, rr) * smoothstep(r + w / 2 + g.px, r + w / 2, rr)
    cv.over(ink, ring(29.5, 0.55) * 0.9)
    cv.over(ink, ring(28.3, 0.20) * 0.8)
    cv.over(ink, ring(8.4, 0.35) * 0.85)
    # two rules across the label, stopping short of the centre ring
    for yy in (-6.5, 6.5):
        line = cov(np.abs(Y - yy) - 0.17, g) * cov(np.abs(X) - np.sqrt(np.maximum(25.6 ** 2 - yy ** 2, 0)), g)
        line = line * (1 - cov(rr - 10.8, g))
        cv.over(ink, line * 0.8)
    # the mark: a small ring with a dot, above; three dots below
    cv.over(ink, cov(np.abs(np.hypot(X, Y + 17.0) - 3.4) - 0.38, g) * 0.9)
    cv.over(ink, cov(np.hypot(X, Y + 17.0) - 1.15, g) * 0.9)
    for xx in (-2.6, 0.0, 2.6):
        cv.over(ink, cov(np.hypot(X - xx, Y - 17.5) - 0.58, g) * 0.8)
    # a short printed arc near the rim, on one side only
    ang = np.arctan2(Y, X)
    arc = smoothstep(0.35, 0.42, ang) * smoothstep(1.25, 1.18, ang) * ring(25.0, 1.0)
    cv.over(ink, arc * 0.8)
    return save(cv.image(), out_dir, name), (g.x, g.y, g.w, g.h)


def render_label_shade(out_dir):
    g = Grid(C[0] - LABEL_BOX, C[1] - LABEL_BOX, 2 * LABEL_BOX, 2 * LABEL_BOX)
    cv = Canvas(g)
    X, Y = g.X - C[0], g.Y - C[1]
    rr = np.hypot(X, Y)
    inner = cov(rr - R_LABEL - 0.6, g)
    # light falls across the label from the upper left
    tilt = (-(X * LIGHT[0] + Y * LIGHT[1]) / R_LABEL)                        # -1..1
    dark = np.clip(0.10 * tilt, 0, 1) + 0.38 * smoothstep(R_LABEL - 5.0, R_LABEL, rr)
    cv.over((0, 0, 0), dark * inner)
    lite = np.clip(-0.07 * tilt, 0, 1) * (1 - smoothstep(R_LABEL - 6, R_LABEL - 2, rr))
    cv.over((1, 1, 1), lite * inner)
    # the spindle's shadow
    sx, sy = SHADOW_DIR[0] * 3.0, SHADOW_DIR[1] * 3.0
    cv.shadow(cov(sd_circle(X, Y, sx, sy, R_SPINDLE + 0.3), g), 1.0, 0.8)
    return save(cv.image(), out_dir, "label_shade.png"), (g.x, g.y, g.w, g.h)


def render_spindle(out_dir):
    half = 5.0
    g = Grid(C[0] - half, C[1] - half, 2 * half, 2 * half, dpp=DPP, ss=4)
    cv = Canvas(g)
    X, Y = g.X - C[0], g.Y - C[1]
    rr = np.hypot(X, Y)
    d = rr - R_SPINDLE
    h = np.sqrt(np.maximum(R_SPINDLE ** 2 - rr ** 2, 0))
    n = normals_from_height(h, g)
    col = light(np.array([0.55, 0.55, 0.57], np.float32), n, amb=0.25, kd=0.7, ks=1.0, shin=45)
    cv.over(col, cov(d, g))
    return save(cv.image(), out_dir, "spindle.png"), (g.x, g.y, g.w, g.h)


# ─── tone arm ──────────────────────────────────────────────────────────────
ARM_BOX = (-14.0, -49.0, 36.0, 208.0)     # sprite rectangle in the arm's frame (pivot at 0,0)
ARM_BAKE_DEG = 30.0                       # the arm's light is baked for this swing


def arm_light():
    """The light direction seen from the arm's frame at ARM_BAKE_DEG."""
    a = math.radians(ARM_BAKE_DEG)
    lx, ly = LIGHT[0], LIGHT[1]
    v = np.array([lx * math.cos(a) + ly * math.sin(a), -lx * math.sin(a) + ly * math.cos(a), LIGHT[2]], np.float32)
    return v / np.linalg.norm(v)


def cyl_normals(u, ax, ay):
    """Normals of a cylinder whose axis runs along (ax, ay); u is -1..1 across it."""
    u = np.clip(u, -0.999, 0.999)
    nz = np.sqrt(1 - u * u)
    px_, py_ = ay, -ax                      # across the axis
    return np.dstack([u * px_, u * py_, nz]).astype(np.float32)


def shade_dir(base, n, L, amb, kd, ks, shin):
    H = L + np.array([0, 0, 1], np.float32)
    H /= np.linalg.norm(H)
    ndl = np.clip(n @ L, 0, 1)[..., None]
    ndh = np.clip(n @ H, 0, 1)[..., None]
    return np.asarray(base, np.float32) * (amb + kd * ndl) + ks * ndh ** shin


def arm_parts(X, Y):
    """Signed distance fields of the arm's parts in its own frame."""
    ax, ay = HEAD_AXIS
    qx, qy = ay, -ax           # across the headshell (towards the outside, +x at rest)
    # headshell frame: s along the axis from the collar, t across
    s = (X - COLLAR[0]) * ax + (Y - COLLAR[1]) * ay
    t = (X - COLLAR[0]) * (-qx) + (Y - COLLAR[1]) * (-qy)
    t = -t
    parts = {}
    parts["weight"] = sd_rrect(X, Y, 0.0, -36.0, 8.4, 10.5, 1.4)
    parts["stub"] = sd_segment(X, Y, 0.0, -8.0, 0.0, -27.0, 2.1)
    parts["yoke"] = sd_rrect(X, Y, 0.0, 0.5, 6.8, 9.2, 3.2)
    parts["cap"] = sd_circle(X, Y, 0.0, 0.0, 5.0)
    tl = TUBE_LEN
    tx, ty = COLLAR[0] / tl, COLLAR[1] / tl
    parts["tube"] = sd_segment(X, Y, tx * 7, ty * 7, COLLAR[0] - tx * 1.0, COLLAR[1] - ty * 1.0, 2.6)
    parts["collar"] = sd_segment(X, Y, COLLAR[0] - tx * 4.5, COLLAR[1] - ty * 4.5, COLLAR[0] + ax * 1.0, COLLAR[1] + ay * 1.0, 3.3)
    # the cartridge hangs under the headshell: from above only its gold nose
    # and a sliver of its sides show round the plate
    width = 4.3 + (np.clip(s, 0, 23) / 23) * 0.9
    parts["shell"] = np.maximum(np.maximum(np.abs(t) - width, -s + 0.5), s - 23.0)
    parts["lift"] = np.minimum(sd_segment(s, t, 20.5, 4.2, 18.4, 15.0, 1.0), sd_circle(s, t, 18.2, 15.4, 1.65))
    parts["cart"] = sd_rrect(s, t, 17.3, 0.0, 6.9, 5.9, 1.1)
    parts["nose"] = sd_rrect(s, t, 24.6, 0.0, 0.9, 2.2, 0.6)
    parts["slot1"] = sd_rrect(s, t, 15.5, 2.9, 5.0, 0.55, 0.55)
    parts["slot2"] = sd_rrect(s, t, 15.5, -2.9, 5.0, 0.55, 0.55)
    parts["screw1"] = sd_circle(s, t, 16.0, 2.9, 1.0)
    parts["screw2"] = sd_circle(s, t, 16.0, -2.9, 1.0)
    return parts, s, t


def render_arm(out_dir):
    bx, by, bw, bh = ARM_BOX
    g = Grid(bx, by, bw, bh)
    cv = Canvas(g)
    X, Y = g.X, g.Y
    L = arm_light()
    parts, s, t = arm_parts(X, Y)
    ax, ay = HEAD_AXIS
    tl = TUBE_LEN
    tx, ty = COLLAR[0] / tl, COLLAR[1] / tl
    silver = np.array([0.70, 0.70, 0.71], np.float32)
    black = np.array([0.055, 0.055, 0.06], np.float32)

    def cyl_across(px_, py_, dx, dy, r):
        # signed distance across an axis through (px_, py_) with direction (dx, dy), as -1..1
        return ((X - px_) * dy - (Y - py_) * dx) / r

    # counterweight: turned steel cylinder, knurled at both ends, a black decoupling ring
    u = -X / 8.4
    n = cyl_normals(u, 0.0, 1.0)
    knurl = ((np.abs(Y + 36.0) > 7.6)).astype(np.float32)
    ph = np.arcsin(np.clip(u, -1, 1)) * 16
    kn = 0.5 + 0.5 * np.cos(ph * 2 * math.pi / math.pi)
    base = silver * (0.78 + 0.22 * noise1(np.abs(Y + 60), 0.15, 61, order=1))[..., None]
    col = shade_dir(base * (1 - 0.35 * knurl * kn)[..., None], n, L, 0.25, 0.8, 0.9 * (1 - 0.6 * knurl)[..., None], 30)
    ringz = np.exp(-((Y + 25.8) / 0.9) ** 4)
    col = col * (1 - ringz[..., None]) + shade_dir(black, n, L, 0.4, 0.5, 0.25, 20) * ringz[..., None]
    cv.over(col, cov(parts["weight"], g))
    # rear stub
    u = -X / 2.1
    cv.over(shade_dir(silver * 0.9, cyl_normals(u, 0.0, 1.0), L, 0.25, 0.8, 1.0, 40), cov(parts["stub"], g))
    # tube: satin silver, a long specular line
    u = cyl_across(0.0, 0.0, tx, ty, 2.6)
    col = shade_dir(silver, cyl_normals(u, tx, ty), L, 0.22, 0.85, 1.1, 36)
    cv.over(col, cov(parts["tube"], g))
    # bearing yoke: black anodised block with polished edges, silver cap with a gold ring
    dy_ = parts["yoke"]
    hy = bevel_height(-dy_, 2.2)
    col = light(black * 1.4, normals_from_height(hy, g), amb=0.55, kd=0.5, ks=0.55, shin=22)
    cv.over(col, cov(dy_, g))
    dc = parts["cap"]
    rr = np.hypot(X, Y)
    hc = bevel_height(-dc, 1.6)
    top = machined_disc(g, 0.0, 0.0, 5.0, silver * 0.8, sheen=0.35, sharp=8.0, seed=62)
    col = light(top, normals_from_height(hc, g), amb=0.4, kd=0.65, ks=0.6, shin=30)
    cv.over(col, cov(dc, g))
    cv.over(GOLD, smoothstep(2.6, 2.8, rr) * smoothstep(3.3, 3.1, rr) * 0.9)
    cv.over((0.08, 0.08, 0.08), cov(rr - 0.9, g) * 0.8)
    # collar
    u = cyl_across(COLLAR[0], COLLAR[1], tx, ty, 3.3)
    cv.over(shade_dir(black * 1.6, cyl_normals(u, tx, ty), L, 0.4, 0.6, 0.45, 22), cov(parts["collar"], g))
    # cartridge body (brushed dark gold) and its black stylus guard
    dca = parts["cart"]
    brushed = 0.85 + 0.15 * noise1(np.abs(t + 20), 0.08, 63, order=1)
    body = GOLD * 0.72 * brushed[..., None]
    cv.over(light(body, normals_from_height(bevel_height(-dca, 1.2), g), amb=0.5, kd=0.6, ks=0.45, shin=24), cov(dca, g))
    dn = parts["nose"]
    cv.over(light(black, normals_from_height(bevel_height(-dn, 0.6), g), amb=0.6, kd=0.4, ks=0.6, shin=40), cov(dn, g))
    # headshell plate: black anodised, chamfered, two slots with the mounting screws
    dsh = parts["shell"]
    cv.shadow(cov(dsh, g), 0.5, 0.6)
    hs = bevel_height(-dsh, 1.1)
    col = light(black * 1.5, normals_from_height(hs, g), amb=0.55, kd=0.5, ks=0.55, shin=26)
    cv.over(col, cov(dsh, g))
    for key in ("slot1", "slot2"):
        cv.over((0.0, 0.0, 0.0), cov(parts[key], g) * 0.9)
    for key in ("screw1", "screw2"):
        dsc = parts[key]
        cv.over(light(silver, normals_from_height(np.sqrt(np.maximum(1.0 - (dsc + 1.0) ** 2, 0)), g), amb=0.3, kd=0.7, ks=0.9, shin=40), cov(dsc, g))
    # finger lift
    dl = parts["lift"]
    cv.over(light(silver * 0.95, normals_from_height(bevel_height(-dl, 1.0), g), amb=0.3, kd=0.75, ks=0.9, shin=40), cov(dl, g))
    return save(cv.image(), out_dir, "arm.png"), (g.x, g.y, g.w, g.h)


def render_arm_shadow(out_dir):
    bx, by, bw, bh = ARM_BOX
    pad = 6.0
    g = Grid(bx - pad, by - pad, bw + 2 * pad, bh + 2 * pad, dpp=1.75, ss=2)
    cv = Canvas(g)
    parts, _, _ = arm_parts(g.X, g.Y)
    union = None
    for k in ("weight", "stub", "yoke", "cap", "tube", "collar", "shell", "lift", "cart", "nose"):
        union = parts[k] if union is None else np.minimum(union, parts[k])
    cv.shadow(cov(union, g), 1.3, 0.85)
    return save(cv.image(), out_dir, "arm_shadow.png"), (g.x, g.y, g.w, g.h)


def render_led(out_dir):
    half = 7.0
    g = Grid(LED[0] - half, LED[1] - half, 2 * half, 2 * half, dpp=DPP, ss=2)
    cv = Canvas(g)
    X, Y = g.X - LED[0], g.Y - LED[1]
    rr = np.hypot(X, Y)
    warm = np.array([1.0, 0.78, 0.36], np.float32)
    cv.over(warm, np.exp(-(rr / 3.2) ** 2) * 0.55)
    dl = rr - 1.7
    h = np.sqrt(np.maximum(1.7 ** 2 - rr ** 2, 0))
    core = light(np.array([1.0, 0.72, 0.30], np.float32), normals_from_height(h, g), amb=0.9, kd=0.2, ks=0.6, shin=40)
    cv.over(core, cov(dl, g))
    cv.over((1.0, 0.97, 0.85), cov(rr - 0.7, g) * 0.8)
    return save(cv.image(), out_dir, "led_on.png"), (g.x, g.y, g.w, g.h)


# ─── main ──────────────────────────────────────────────────────────────────
def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "..", "..", "assets", "anim", "vinyl")
    os.makedirs(out_dir, exist_ok=True)
    for fn in (render_plinth_shadow, render_plinth, render_platter, render_dots, render_record_shadow,
               render_record, render_label, render_label_shade, render_spindle, render_arm, render_arm_shadow,
               render_led):
        path, rect = fn(out_dir)
        names = [os.path.basename(path)] + (["dots_blur.png"] if fn is render_dots else [])
        for name in names:
            full = os.path.join(out_dir, name)
            print("%-18s %4d x %-4d %8d B  rect %s" % (name, *Image.open(full).size, os.path.getsize(full),
                                                       ", ".join("%.2f" % v for v in rect)))
    ang = lambda r: math.degrees(math.atan2(C[1] - P[1], C[0] - P[0])
                                 - math.acos((ARM_D ** 2 + ARM_L ** 2 - r * r) / (2 * ARM_D * ARM_L))) - 90
    print("centre %.3f, %.3f  pivot %.3f, %.3f  armL %.3f  armD %.3f" % (C[0], C[1], P[0], P[1], ARM_L, ARM_D))
    print("radii start %.2f end %.2f record %.2f label %.2f" % (R_START, R_END, R_RECORD, R_LABEL))
    print("arm swing: record edge %.2f  start %.2f  end %.2f deg" % (ang(R_RECORD), ang(R_START), ang(R_END)))


if __name__ == "__main__":
    main()
