#!/usr/bin/env python3
"""Render the images of the "Cassette" Now Playing animation (qml/AnimCassette.qml).

The scene is the front of a cassette deck: a dark brushed front panel with the
cassette bay on the left (a bottom-hinged door with a smoked window), a row of
transport keys under it, a display, a volume fader, a headphone jack and the
power key on the right. Through the window the cassette: a smoked shell, a graphite
label (the album title and artist are drawn live by the QML), the tape packs
and the white toothed hubs behind a clear window, the tape running along the
bottom between the guide rollers.

Everything is drawn procedurally (signed distance fields for the shapes, a
height field for bevels and chamfers, Lambert + Blinn lighting from the top
left), rendered 2x supersampled and box-filtered down for clean edges.
Shadows and reflections are baked: the kiosk only moves, scales, rotates and
fades these quads (the light on the hubs is a separate static overlay, so it
stays put while they turn).

Run it with any Python 3 that has numpy, scipy and Pillow:

    python3 native-ui-qt/tools/np-anim/cassette.py [--out DIR] [--only a,b]

The output is deterministic (fixed random seeds). DIR defaults to
native-ui-qt/assets/anim/cassette/. Files (positions in the 520 x 260 point
design of AnimCassette.qml; the geometry constants below are mirrored there):

  deck.png          the whole deck without the door: drop shadow, brushed
                    front panel, the bay behind the door (back wall lit by a
                    lamp under the top lip, the two reel spindles), the six
                    transport keys, the window of the tape LCD (LcdTape.qml),
                    the volume fader's slot, jack, power key and the prints
  door.png          the door: brushed frame, cassette holder lip and clips,
                    smoked glass with its reflection (tilts open in the QML)
  door-edge.png     the top face of the door, seen only while it is tilted
  key-play.png      the PLAY key held down while playing, its symbol lit
  key-<k>-down.png  each key pressed (rew, play, ff, stop, pause, eject,
                    power): shown while a finger is on it (over deck.png)
  fader.png         the volume fader's cap (moved by the QML to follow the
                    volume)
  led.png           the lit LED next to the power key
  cas.png           the cassette front: smoked shell, screws, graphite label
                    with a clear window cut out (see-through), the tape path
                    in the lower trapezoid
  cas-back.png      what is seen through the window behind the tape packs
  cas-shadow.png    soft shadow of the cassette on the bay's back wall
  pack.png          a tape pack at its largest radius (scaled by the QML)
  hub.png           a reel hub with its teeth and the spindle in it (turns)
  hub-light.png     the static light and shade over a hub
"""
import argparse
import math
import os

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.special import erfc

# ── geometry of the 520 x 260 point design (mirrored in AnimCassette.qml) ───
CANVAS = (520, 260)
BODY = (4, 3, 516, 247)           # x0, y0, x1, y1
BODY_R = 8
BAY = (16, 13, 322, 213)          # the opening behind the door
BAY_R = 5
DOOR = (18.5, 15.5, 319.5, 210.5)  # hinged along its bottom edge
DOOR_R = 4
DOOR_EDGE = 6                     # thickness of the door (its top face)
WIN = (32, 26, 306, 194)          # the smoked window in the door
WIN_R = 5
HOLDER_Y = 186.5                  # top of the holder lip along the window bottom
CAS_X, CAS_Y = 47.0, 32.5         # cassette top left, seated in the holder
MM = 244.0 / 100.4                # points per millimetre of a real cassette
CAS_W = 100.4 * MM
CAS_H = 63.8 * MM
HUBS_MM = ((28.95, 31.0), (71.45, 31.0))
HUB_R_MM = 10.75                  # hub radius = empty tape pack
PACK_R_MM = 22.0                  # a full tape pack
KEY_Y = (220, 240)
KEY_X0, KEY_W, KEY_GAP = 16, 46, 6
PLAY_KEY = 1                      # rewind, play, fast forward, stop, pause, eject
DISPLAY = (336, 17, 502, 81)
DISPLAY_R = 6
# the volume: a horizontal fader, its ticks numbered 0-10
FADER = (352.0, 488.0, 146.0)                 # x at 0, x at 100, y of the slot
FADER_CAP = (12.0, 20.0)                      # the cap, centred on its position
JACK_C = (350, 230)
LED_C = (442, 230)
POWER = (456, 220, 502, 240)
DIVIDER_X = 328

# pixels per point of the images (2.7 keeps the big ones under ~1400 px, the
# cassette parts get 3.6 = 4K)
PPT_BIG = 2.7
PPT_CAS = 3.6
SS = 2

LIGHT = np.array([-0.42, -0.62, 0.66])
LIGHT /= np.linalg.norm(LIGHT)
HALF = LIGHT + np.array([0.0, 0.0, 1.0])
HALF /= np.linalg.norm(HALF)
LXY = LIGHT[:2] / np.linalg.norm(LIGHT[:2])       # towards the light, on screen
LSLOPE = np.linalg.norm(LIGHT[:2]) / LIGHT[2]     # horizontal shift per unit of height


def mm(v):
    return v * MM


def hubs_local():
    return [(mm(x), mm(y)) for x, y in HUBS_MM]


def key_rect(i):
    x0 = KEY_X0 + i * (KEY_W + KEY_GAP)
    return (x0, KEY_Y[0], x0 + KEY_W, KEY_Y[1])


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


def sd_poly(X, Y, pts):
    """Convex polygon, vertices clockwise on screen (max of the edge half planes)."""
    d = None
    for i in range(len(pts)):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % len(pts)]
        ex, ey = bx - ax, by - ay
        ln = math.hypot(ex, ey)
        di = (X - ax) * (ey / ln) + (Y - ay) * (-ex / ln)
        d = di if d is None else np.maximum(d, di)
    return d


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


def gray3(v, tint=(1.0, 1.0, 1.0)):
    return np.repeat(np.asarray(v, dtype=np.float32)[..., None], 3, axis=2) * rgb3(tint)


def mix(a, b, m):
    m = np.asarray(m, dtype=np.float32)
    if m.ndim == 2:
        m = m[..., None]
    return a * (1 - m) + b * m


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


def radial_noise(r, rng, scale_pt, rmax=120.0):
    """Turned (lathe) finish or wound tape: a random function of the radius only."""
    k = int(rmax / scale_pt)
    v = ndimage.gaussian_filter1d(rng.standard_normal(k * 4).astype(np.float32), 2.0)
    v /= v.std() + 1e-6
    idx = np.clip(r / rmax * (k * 4 - 1), 0, k * 4 - 1)
    return np.interp(idx.ravel(), np.arange(k * 4), v).reshape(r.shape).astype(np.float32)


def grain(shape, rng, sigma):
    g = ndimage.gaussian_filter(rng.standard_normal(shape).astype(np.float32), sigma)
    return g / (g.std() + 1e-6)


def save(img, out, name):
    path = os.path.join(out, name)
    img.save(path, optimize=True)
    print(f"{name:18s} {img.size[0]:5d}x{img.size[1]:<5d} {os.path.getsize(path):8d} B")


# ── symbols (engraved on the keys, lit on the display) ─────────────────────
def tri_right(X, Y, cx, cy, h):
    return sd_poly(X, Y, [(cx - 0.8 * h, cy - h), (cx + 0.9 * h, cy), (cx - 0.8 * h, cy + h)])


def tri_left(X, Y, cx, cy, h):
    return sd_poly(X, Y, [(cx - 0.9 * h, cy), (cx + 0.8 * h, cy - h), (cx + 0.8 * h, cy + h)])


def symbol_sd(X, Y, kind, cx, cy):
    big = 1e3
    if kind == "play":
        return tri_right(X, Y, cx + 0.3, cy, 3.6)
    if kind == "rew":
        return np.minimum(tri_left(X, Y, cx - 2.3, cy, 3.0), tri_left(X, Y, cx + 2.5, cy, 3.0))
    if kind == "ff":
        return np.minimum(tri_right(X, Y, cx - 2.5, cy, 3.0), tri_right(X, Y, cx + 2.3, cy, 3.0))
    if kind == "stop":
        return sd_rrect(X, Y, cx - 3.0, cy - 3.0, cx + 3.0, cy + 3.0, 0.4)
    if kind == "pause":
        return np.minimum(sd_rrect(X, Y, cx - 3.0, cy - 3.5, cx - 1.0, cy + 3.5, 0.3),
                          sd_rrect(X, Y, cx + 1.0, cy - 3.5, cx + 3.0, cy + 3.5, 0.3))
    if kind == "eject":
        t = sd_poly(X, Y, [(cx, cy - 4.0), (cx + 4.0, cy + 0.4), (cx - 4.0, cy + 0.4)])
        return np.minimum(t, sd_rrect(X, Y, cx - 4.0, cy + 1.9, cx + 4.0, cy + 3.3, 0.3))
    if kind == "power":
        r = np.hypot(X - cx, Y - cy)
        phi = np.degrees(np.arctan2(X - cx, -(Y - cy)))        # 0 = straight up
        ring = np.abs(r - 3.4) - 0.55
        ring = np.where(np.abs(phi) < 38, np.maximum(ring, 0.8), ring)
        bar = sd_rrect(X, Y, cx - 0.55, cy - 4.6, cx + 0.55, cy - 0.6, 0.5)
        return np.minimum(ring, bar)
    return np.full_like(X, big)


KEY_SYMBOLS = ("rew", "play", "ff", "stop", "pause", "eject")


def shade_key(cv, x0, y0, x1, y1, kind, pressed=False, lit=False):
    """A machined aluminium key with an engraved symbol: returns (rgb, coverage)."""
    X, Y, n = cv.X, cv.Y, cv.n
    rng = np.random.default_rng(97)
    dy = 0.45 if pressed else 0.0
    sd = sd_rrect(X, Y - dy, x0, y0, x1, y1, 2.4)
    e = np.clip(-sd, 0, None)
    B = 1.5
    h = B * np.sqrt(1 - (1 - np.clip(e / B, 0, 1)) ** 2)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2 + dy
    h = h + 0.25 * (1 - ((Y - cy) / ((y1 - y0) / 2)) ** 2)        # a slight crown
    ssd = symbol_sd(X, Y, kind, cx, cy)
    h = h - 0.5 * (1 - smoothstep(-0.25, 0.25, ssd))
    nx, ny, nz = normals(h, n)
    t = np.clip((Y - y0 - dy) / (y1 - y0), 0, 1)
    br = streaks(X.shape, n, rng, 30, 0.15)
    env = 1.20 - 0.40 * t
    alb = 0.080 * (1 + 0.10 * br) * env * (0.80 if pressed else 1.0)
    lam = lambert(nx, ny, nz)
    col = alb * (0.35 + 0.65 * lam) + 0.55 * blinn(nx, ny, nz, 45) + 0.05 * blinn(nx, ny, nz, 6)
    col = gray3(col, (1.0, 1.0, 1.02))
    # engraving: dark floor, its lower right wall catching the light
    sm = cv.cov(ssd)
    wall = sm * (1 - cv.cov(symbol_sd(X - 0.35, Y - 0.35, kind, cx, cy)))
    floor = gray3(np.full_like(X, 0.010))
    col = mix(col, floor, sm) + gray3(0.10 * wall)
    if lit:
        gold = rgb3((1.0, 0.80, 0.40))
        core = sm * (0.75 + 0.25 * smoothstep(0.0, -1.2, ssd))
        col = mix(col, gold * (0.85 + 0.15 * (1 - t))[..., None], core)
    return col, cv.cov(sd), sd


# ── the deck ───────────────────────────────────────────────────────────────
# a 90s front panel: the display window holds the grey-green tape LCD
# (LcdTape.qml, drawn by the scene), the panel carries silk-screen prints
def build_deck(out):
    cv = Canvas(0, 0, CANVAS[0], CANVAS[1], PPT_BIG)
    X, Y, n = cv.X, cv.Y, cv.n
    rng = np.random.default_rng(31)

    # soft drop shadow, faded out before the canvas edge
    bx0, by0, bx1, by1 = BODY
    sh = (0.55 * soft(sd_rrect(X, Y - 6, bx0 + 10, by0 + 6, bx1 - 10, by1 - 1, BODY_R), 6.0)
          + 0.45 * soft(sd_rrect(X, Y - 1.5, bx0 + 1, by0 + 1, bx1 - 1, by1, BODY_R), 1.8))
    edge = np.minimum(np.minimum(X, CANVAS[0] - X), np.minimum(Y, CANVAS[1] - Y))
    cv.over((0, 0, 0), np.clip(sh, 0, 0.9) * smoothstep(0, 5, edge))

    sd_body = sd_rrect(X, Y, *BODY, BODY_R)
    body = cv.cov(sd_body)
    sd_bay = sd_rrect(X, Y, *BAY, BAY_R)
    in_bay = cv.cov(sd_bay)

    # ── the bay: a matte black back wall lit by a lamp under the top lip ──
    ins = np.clip(-sd_bay, 0, None)
    top = np.clip(Y - BAY[1], 0, None)
    lamp = np.exp(-top / 34.0) * (0.55 + 0.45 * np.exp(-((X - (BAY[0] + BAY[2]) / 2) / 110.0) ** 2))
    g = grain(X.shape, rng, 0.9 * n / 2.7)
    wall_l = (0.0040 + 0.016 * lamp) * (1 + 0.06 * g)
    wall_l = wall_l * (1 - 0.65 * np.exp(-ins / 4.5))
    wall = gray3(wall_l, (1.0, 0.95, 0.86))
    # the lamp: a warm diffuser strip just under the top lip (the closed door
    # hides it; it shows when the door leans out)
    strip = sd_rrect(X, Y, BAY[0] + 46, 17.6, BAY[2] - 46, 19.6, 1.0)
    wall = wall + (0.014 * np.exp(-np.clip(strip, 0, None) / 3.0))[..., None] * rgb3((1.0, 0.80, 0.58))
    glow = rgb3((0.075, 0.058, 0.040)) * (0.70 + 0.30 * smoothstep(19.6, 17.6, Y))[..., None]
    wall = mix(wall, glow, cv.cov(strip))
    # a pressed rib across the back wall, above the spindles
    rib = np.exp(-((Y - 62.0) / 1.2) ** 2) * smoothstep(BAY[0] + 10, BAY[0] + 30, X) * smoothstep(BAY[2] - 10, BAY[2] - 30, X)
    wall = wall * (1 + 1.2 * rib[..., None]) * (1 - 0.5 * np.exp(-((Y - 64.2) / 0.9) ** 2))[..., None]
    # the cassette guides along both sides, and two screws
    for gx in (BAY[0] + 10, BAY[2] - 10):
        wall = wall * (1 - 0.55 * soft(sd_rrect(X - 1.2, Y - 2.4, gx - 2.4, 28, gx + 2.4, 206, 1.6), 1.8))[..., None]
        gsd = sd_rrect(X, Y, gx - 2.4, 28, gx + 2.4, 206, 1.6)
        gl = (0.010 + 0.040 * np.exp(-((X - (gx - 1.5)) / 0.7) ** 2)) * (0.45 + 0.55 * np.exp(-np.clip(Y - 28, 0, None) / 60.0))
        wall = mix(wall, gray3(gl), cv.cov(gsd))
    for sx, sy in ((BAY[0] + 40, 40.0), (BAY[2] - 40, 40.0)):
        rs = np.hypot(X - sx, Y - sy)
        hs = 0.8 * np.sqrt(np.clip(1 - (rs / 3.0) ** 2, 0, 1))
        cross = (np.minimum(np.abs(X - sx), np.abs(Y - sy)) < 0.4) & (np.maximum(np.abs(X - sx), np.abs(Y - sy)) < 2.0)
        hs = hs - 0.4 * cross
        snx, sny, snz = normals(hs, n)
        sc = (0.012 * (0.3 + 0.7 * lambert(snx, sny, snz)) + 0.35 * blinn(snx, sny, snz, 30)) * (0.5 + 0.5 * lamp)
        wall = mix(wall, gray3(np.where(cross, 0.002, sc)), cv.cov(rs - 3.0))
    for hx, hy in [(CAS_X + x, CAS_Y + y) for x, y in hubs_local()]:
        r = np.hypot(X - hx, Y - hy)
        phi = np.arctan2(Y - hy, X - hx)
        # reel table: a dark plastic disc; its shadow falls downwards (lamp above)
        wall = wall * (1 - 0.6 * soft(sd_circle(X, Y - 3.5, hx, hy, 13.0), 2.6))[..., None]
        ht = 1.2 * np.sqrt(1 - (1 - np.clip((13.0 - r) / 1.2, 0, 1)) ** 2)
        # the spindle: a shaft with six splines and a chrome cap
        spl = np.clip(np.cos(3 * phi) * 0, 0, 0)
        ang = np.mod(phi + math.pi / 6, math.pi / 3) - math.pi / 6
        perp = np.abs(r * np.sin(ang))
        spline = (perp < 0.75) & (r < 8.6)
        hs = np.where(r < 5.2, 3.0, 0.0) + np.where(spline & (r >= 5.2), 2.6, 0.0)
        hs = ndimage.gaussian_filter(hs.astype(np.float32), 0.35 * n)
        nx, ny, nz = normals(ht + hs, n)
        lam = lambert(nx, ny, nz)
        table = 0.010 * (0.4 + 0.6 * lam) + 0.25 * blinn(nx, ny, nz, 30)
        metal = 0.050 * (0.3 + 0.7 * lam) + 0.9 * blinn(nx, ny, nz, 35)
        cap = r < 2.6
        metal = np.where(cap, 0.09 + 0.8 * np.exp(-(np.hypot(X - hx + 0.8, Y - hy + 0.9)) ** 2 / 0.5), metal)
        sm = smoothstep(0.5, 2.2, hs)
        col = gray3(table * (1 - sm) + metal * sm)
        ao = 1 - 0.55 * np.exp(-np.clip(r - 8.8, 0, None) / 1.2) * (r > 8.6)
        col = col * ao[..., None]
        wall = mix(wall, col, cv.cov(r - 13.0))
        del spl
    cv.over(srgb(wall), body * in_bay)

    # ── the front panel: brushed dark aluminium ──
    e = np.clip(-sd_body, 0, None)
    B = 2.6
    h = B * np.sqrt(1 - (1 - np.clip(e / B, 0, 1)) ** 2)
    h = h - 1.7 * (1 - smoothstep(0.0, 2.2, sd_bay))                      # lip into the bay
    for i in range(6):
        k = key_rect(i)
        h = h - 1.0 * (1 - smoothstep(0.0, 1.1, sd_rrect(X, Y, k[0] - 1.1, k[1] - 1.1, k[2] + 1.1, k[3] + 1.1, 3.3)))
    h = h - 1.0 * (1 - smoothstep(0.0, 1.1, sd_rrect(X, Y, POWER[0] - 1.1, POWER[1] - 1.1, POWER[2] + 1.1, POWER[3] + 1.1, 3.3)))
    sd_disp = sd_rrect(X, Y, *DISPLAY, DISPLAY_R)
    h = h - 1.5 * (1 - smoothstep(0.0, 1.8, sd_disp))
    div = np.exp(-((X - DIVIDER_X) / 0.55) ** 2) * smoothstep(BODY[1] + 6, BODY[1] + 12, Y) * smoothstep(BODY[3] - 6, BODY[3] - 12, Y)
    h = h - 0.7 * div
    rj = np.hypot(X - JACK_C[0], Y - JACK_C[1])
    h = h - 0.8 * (1 - smoothstep(6.6, 7.6, rj))
    rl = np.hypot(X - LED_C[0], Y - LED_C[1])
    h = h - 0.6 * (1 - smoothstep(3.0, 3.7, rl))
    nx, ny, nz = normals(h, n)
    br = 0.07 * streaks(X.shape, n, rng, 70, 0.22) + 0.05 * streaks(X.shape, n, rng, 10, 0.10)
    sheen = 1 + 0.35 * np.exp(-((X - 200) / 170) ** 2) * (1.15 - 0.6 * Y / CANVAS[1])
    alb = 0.022 * (1 + br) * sheen
    plate = alb * (0.28 + 0.72 * lambert(nx, ny, nz)) + 0.50 * blinn(nx, ny, nz, 60) + 0.05 * blinn(nx, ny, nz, 6)
    plate = gray3(plate, (0.985, 0.995, 1.02))

    # the keys in their slots
    for i in range(6):
        k = key_rect(i)
        slot = cv.cov(sd_rrect(X, Y, k[0] - 1.1, k[1] - 1.1, k[2] + 1.1, k[3] + 1.1, 3.3))
        plate = plate * (1 - 0.85 * slot)[..., None]
        kc, km, _ = shade_key(cv, *k, KEY_SYMBOLS[i])
        plate = mix(plate, kc, km)
    slot = cv.cov(sd_rrect(X, Y, POWER[0] - 1.1, POWER[1] - 1.1, POWER[2] + 1.1, POWER[3] + 1.1, 3.3))
    plate = plate * (1 - 0.85 * slot)[..., None]
    kc, km, _ = shade_key(cv, *POWER, "power")
    plate = mix(plate, kc, km)

    # display window: black glass, the unlit play symbol and track
    inside = np.clip(-sd_disp, 0, None)
    glass = 0.0010 + 0.0025 * smoothstep(0, 30, Y - DISPLAY[1])
    glass = glass * (1 - 0.6 * np.exp(-inside / 2.0))
    glass = gray3(glass)
    plate = mix(plate, glass, cv.cov(sd_disp))


    # headphone jack: chrome ring, gold-plated throat
    ring = cv.cov(rj - 6.4) * (1 - cv.cov(rj - 3.6))
    jh = np.clip(1 - np.abs(rj - 5.0) / 1.4, 0, 1)
    jnx, jny, jnz = normals(1.0 * np.sqrt(jh), n)
    chrome = 0.06 + 0.25 * lambert(jnx, jny, jnz) + 1.2 * blinn(jnx, jny, jnz, 25)
    plate = mix(plate, gray3(chrome), ring)
    throat = cv.cov(rj - 3.6)
    tcol = rgb3((0.30, 0.21, 0.06)) * smoothstep(1.8, 3.5, rj)[..., None] + rgb3((0.004, 0.004, 0.004))
    tcol = tcol + rgb3((0.7, 0.6, 0.35)) * np.exp(-((X - JACK_C[0] + 1.6) ** 2 + (Y - JACK_C[1] + 1.8) ** 2) / 0.4)[..., None]
    plate = mix(plate, tcol, throat)

    # the unlit LED: amber glass bead in a chrome bezel
    bez = cv.cov(np.abs(rl - 2.9) - 0.45)
    plate = mix(plate, gray3(0.10 + 0.5 * np.exp(-((Y - LED_C[1] + 2.3) ** 2 + (X - LED_C[0] + 1.6) ** 2) / 1.5)), bez)
    bead = cv.cov(rl - 2.45)
    bead_c = rgb3((0.022, 0.011, 0.002)) + rgb3((0.5, 0.45, 0.4)) * np.exp(-((X - LED_C[0] + 0.8) ** 2 + (Y - LED_C[1] + 0.9) ** 2) / 0.25)[..., None]
    plate = mix(plate, bead_c, bead)

    # the volume fader's slot (no knobs): a dark cut with rounded ends, its
    # lower lip catching the light, eleven ticks above it; the cap is fader.png
    fx0, fx1, fy = FADER
    sd_slot = sd_rrect(X, Y, fx0 - 3, fy - 1.6, fx1 + 3, fy + 1.6, 1.6)
    slot = cv.cov(sd_slot)
    lip = cv.cov(sd_rrect(X, Y, fx0 - 3, fy + 1.6, fx1 + 3, fy + 2.3, 0.4)) * (1 - slot)
    plate = mix(plate, gray3(0.003 + 0.004 * smoothstep(fy - 1.6, fy + 1.6, Y)), slot)
    plate = plate * (1 - 0.4 * lip)[..., None] + gray3(0.05 * lip)
    for k in range(11):
        tx = fx0 + (fx1 - fx0) * k / 10
        tm = cv.cov(sd_rrect(X, Y, tx - 0.3, fy - 9.5, tx + 0.3, fy - 6.5 + (1.2 if k % 5 == 0 else 0), 0.1))
        plate = plate * (1 - tm[..., None]) + 0.40 * tm[..., None]
    import cdfront
    items = [(name, (key_rect(i)[0] + key_rect(i)[2]) / 2, 214.5, 3.8, True, "m", 0.3)
             for i, name in enumerate(("REW", "PLAY", "F.FWD", "STOP", "PAUSE", "EJECT"))]
    items += [
        ("OSMIUM", DISPLAY[0], 92, 8.0, True, "l", 1.9),
        ("TC-90", DISPLAY[2], 92, 6.2, True, "r", 0.4),
        ("STEREO CASSETTE DECK", DISPLAY[0], 102, 3.8, False, "l", 0.7),
        ("AUTO REVERSE  \u00b7  NR", DISPLAY[2], 102, 3.6, False, "r", 0.3),
        ("VOLUME", (FADER[0] + FADER[1]) / 2, 160, 3.8, True, "m", 0.6),
        ("PHONES", JACK_C[0], 214.5, 3.8, True, "m", 0.3),
        ("POWER", (POWER[0] + POWER[2]) / 2, 214.5, 3.8, True, "m", 0.3),
    ]
    items += [(str(k), FADER[0] + (FADER[1] - FADER[0]) * k / 10, FADER[2] - 14.5, 3.4, True, "m", 0.0)
              for k in range(11)]
    ink = cdfront.text_mask(cv, items)
    plate = plate * (1 - ink[..., None]) + 0.50 * ink[..., None]
    cv.over(srgb(plate), body * (1 - in_bay))
    save(cv.image(), out, "deck.png")


def build_key_image(out, k, kind, lit, name):
    """A key pressed into its slot (7 points of margin for the glow)."""
    m_ = 7
    cv = Canvas(k[0] - m_, k[1] - m_, k[2] - k[0] + 2 * m_, k[3] - k[1] + 2 * m_, PPT_CAS)
    X, Y = cv.X, cv.Y
    cx, cy = (k[0] + k[2]) / 2, (k[1] + k[3]) / 2 + 0.45
    # the slot round the key: the pressed key shows more of it at the top
    slot_sd = sd_rrect(X, Y, k[0] - 1.1, k[1] - 1.1, k[2] + 1.1, k[3] + 1.1, 3.3)
    cv.over((0.004, 0.004, 0.005), cv.cov(slot_sd))
    col, km, _ = shade_key(cv, *k, kind, pressed=True, lit=lit)
    cv.over(srgb(col), km)
    if lit:
        ssd = symbol_sd(X, Y, kind, cx, cy)
        cv.over((0.95, 0.72, 0.25), 0.40 * soft(ssd, 1.6) * (1 - cv.cov(ssd)))
    save(cv.image(), out, name)


def build_keys(out):
    build_key_image(out, key_rect(PLAY_KEY), "play", True, "key-play.png")
    for i, kind in enumerate(KEY_SYMBOLS):
        build_key_image(out, key_rect(i), kind, False, "key-" + kind + "-down.png")
    build_key_image(out, POWER, "power", False, "key-power-down.png")


def build_fader(out):
    """The volume fader's cap of the 90s panel: black ribbed plastic with a
    white index line, and its shadow on the panel."""
    w, h = FADER_CAP
    cv = Canvas(-w / 2 - 4, -h / 2 - 4, w + 8, h + 8, PPT_CAS)
    X, Y, n = cv.X, cv.Y, cv.n
    sd = sd_rrect(X, Y, -w / 2, -h / 2, w / 2, h / 2, 1.8)
    cv.over((0, 0, 0), 0.7 * soft(sd_rrect(X - 1.2, Y - 1.8, -w / 2, -h / 2, w / 2, h / 2, 1.8), 1.6))
    e = np.clip(-sd, 0, None)
    hh = 1.2 * np.sqrt(1 - (1 - np.clip(e / 1.2, 0, 1)) ** 2)
    hh = hh + 0.18 * np.cos(Y * 2 * math.pi / 1.6) * smoothstep(1.4, 2.2, e) * (np.abs(Y) > 2.0)
    nx, ny, nz = normals(hh, n)
    col = 0.030 * (0.35 + 0.65 * lambert(nx, ny, nz)) + 0.45 * blinn(nx, ny, nz, 40)
    rgb = gray3(col)
    line = cv.cov(sd_rrect(X, Y, -w / 2 + 2.2, -0.45, w / 2 - 2.2, 0.45, 0.2))
    rgb = rgb * (1 - line[..., None]) + 0.75 * line[..., None]
    cv.over(srgb(rgb), cv.cov(sd))
    save(cv.image(), out, "fader.png")


def build_led(out):
    # the lit LED
    cx, cy = LED_C
    cv = Canvas(cx - 12, cy - 12, 24, 24, PPT_CAS)
    X, Y = cv.X, cv.Y
    r = np.hypot(X - cx, Y - cy)
    cv.over((0.83, 0.62, 0.18), 0.20 * np.exp(-(r / 6.5) ** 2))
    cv.over((0.95, 0.72, 0.25), 0.50 * np.exp(-(r / 3.2) ** 2))
    bead = cv.cov(r - 2.45)
    c = np.zeros(X.shape + (3,), np.float32) + rgb3((1.0, 0.72, 0.22))
    c = c + (np.exp(-(r / 1.3) ** 2))[..., None] * rgb3((0.0, 0.22, 0.45))
    c = c + np.exp(-((X - cx + 0.8) ** 2 + (Y - cy + 0.9) ** 2) / 0.25)[..., None] * 0.6
    cv.over(np.clip(c, 0, 1), bead)
    save(cv.image(), out, "led.png")


# ── the door ───────────────────────────────────────────────────────────────
def build_door(out):
    m_ = 3
    x0, y0, x1, y1 = DOOR
    cv = Canvas(x0 - m_, y0 - m_, x1 - x0 + 2 * m_, y1 - y0 + 2 * m_, PPT_BIG)
    X, Y, n = cv.X, cv.Y, cv.n
    rng = np.random.default_rng(41)
    sd_d = sd_rrect(X, Y, *DOOR, DOOR_R)
    sd_w = sd_rrect(X, Y, *WIN, WIN_R)
    cov_d = cv.cov(sd_d)
    cov_w = cv.cov(sd_w)

    # ── inside the window, back to front: holder lip and clips, then glass ──
    wx0, wy0, wx1, wy1 = WIN
    lip_sd = sd_rrect(X, Y, wx0 - 4, HOLDER_Y, wx1 + 4, wy1 + 4, 1.2)
    lip = cv.cov(lip_sd)
    lt = np.clip((Y - HOLDER_Y) / 3.0, 0, 1)
    lip_col = gray3(0.010 + 0.05 * np.exp(-((Y - HOLDER_Y - 0.6) / 0.5) ** 2) + 0.004 * (1 - lt), (1.0, 1.0, 1.03))
    cv.over(srgb(lip_col), lip * cov_w)
    for cxc in (CAS_X + 18, CAS_X + CAS_W - 18):
        tab_sd = sd_rrect(X, Y, cxc - 7, wy0 - 4, cxc + 7, CAS_Y + 3.2, 1.2)
        tab = cv.cov(tab_sd)
        tcol = gray3(0.012 + 0.07 * np.exp(-((Y - CAS_Y - 2.4) / 0.5) ** 2), (1.0, 1.0, 1.03))
        cv.over((0, 0, 0), 0.45 * soft(tab_sd - 0.3, 1.0) * (1 - tab) * cov_w * (Y > CAS_Y))
        cv.over(srgb(tcol), tab * cov_w)

    # the frame's shadow on what is behind the glass (light from the top left)
    sd_ws = sd_rrect(X - 2.6, Y - 3.8, *WIN, WIN_R)
    cv.over((0, 0, 0), 0.50 * (1 - soft(sd_ws, 2.2)) * cov_w)
    # smoked glass
    t = (Y - wy0) / (wy1 - wy0)
    u = (X - wx0) / (wx1 - wx0)
    cv.over((0.010, 0.011, 0.014), (0.30 + 0.06 * t) * cov_w)
    diag = u * 0.95 + t * 0.55
    refl = (0.055 * np.exp(-((diag - 0.30) / 0.12) ** 2)
            + 0.030 * np.exp(-((diag - 0.52) / 0.022) ** 2)
            + 0.030 * (1 - smoothstep(0.0, 0.25, t)) * (1 - 0.6 * u))
    cv.over((0.85, 0.88, 0.95), refl * cov_w)

    # ── the frame: brushed aluminium, rounded outer edge, chamfer into the glass ──
    e = np.clip(-sd_d, 0, None)
    B = 2.2
    h = B * np.sqrt(1 - (1 - np.clip(e / B, 0, 1)) ** 2)
    h = h - 1.6 * (1 - smoothstep(0.0, 2.4, sd_w))
    # a finger recess in the frame's top edge (to pull the door)
    fr = sd_rrect(X, Y, (x0 + x1) / 2 - 22, y0 + 2.6, (x0 + x1) / 2 + 22, y0 + 7.2, 2.3)
    h = h - 0.9 * (1 - smoothstep(-1.2, 0.6, fr))
    nx, ny, nz = normals(h, n)
    br = 0.07 * streaks(X.shape, n, rng, 70, 0.22) + 0.05 * streaks(X.shape, n, rng, 10, 0.10)
    sheen = 1 + 0.45 * np.exp(-((X - 150) / 140) ** 2) * (1.2 - 0.7 * (Y - y0) / (y1 - y0))
    alb = 0.026 * (1 + br) * sheen
    frame = alb * (0.28 + 0.72 * lambert(nx, ny, nz)) + 0.60 * blinn(nx, ny, nz, 60) + 0.05 * blinn(nx, ny, nz, 6)
    frame = gray3(frame, (0.985, 0.995, 1.02))
    fm = np.clip(cov_d - cov_w, 0, 1)
    # a thin contact shadow round the door on the bay edge
    cv.over((0, 0, 0), 0.5 * soft(sd_d - 0.4, 0.9) * (1 - cov_d))
    cv.over(srgb(frame), fm)
    save(cv.image(), out, "door.png")


def build_door_edge(out):
    x0, x1 = DOOR[0], DOOR[2]
    cv = Canvas(x0, 0, x1 - x0, DOOR_EDGE, PPT_BIG)
    X, Y, n = cv.X, cv.Y, cv.n
    rng = np.random.default_rng(43)
    sd = sd_rrect(X, Y, x0, -2, x1, DOOR_EDGE + 2, DOOR_R)
    t = Y / DOOR_EDGE                         # 0 back (in the deck) .. 1 front
    br = streaks(X.shape, n, rng, 50, 0.1)
    l = (0.030 + 0.050 * smoothstep(0.0, 1.0, t)) * (1 + 0.08 * br)
    l = l + 0.18 * np.exp(-((t - 0.88) / 0.08) ** 2)             # the rounded front edge
    l = l * (1 - 0.7 * np.exp(-t / 0.12))                         # the back edge in shadow
    cv.over(srgb(gray3(l)), cv.cov(sd))
    save(cv.image(), out, "door-edge.png")


# ── the cassette ───────────────────────────────────────────────────────────
TRAP = [(17.0, 50.6), (83.4, 50.6), (89.2, 63.8), (11.2, 63.8)]   # mm, clockwise
LABEL = (8.4, 2.6, 92.0, 49.2)
WRITE = (10.4, 4.4, 90.0, 19.4)
WIN_H_MM = 8.6                    # half height of the label's window
SCREWS = ((4.3, 4.3), (96.1, 4.3), (4.3, 58.8), (96.1, 58.8), (50.2, 55.2))


def window_sd(X, Y, grow=0.0):
    (hx0, hy), (hx1, _) = hubs_local()
    rw = mm(WIN_H_MM) + grow
    return sd_rrect(X, Y, hx0 - rw, hy - rw, hx1 + rw, hy + rw, rw)


def build_cassette(out, variant="graphite"):
    m_ = 2
    cv = Canvas(-m_, -m_, CAS_W + 2 * m_, CAS_H + 2 * m_, PPT_CAS)
    X, Y, n = cv.X, cv.Y, cv.n
    rng = np.random.default_rng(53)
    Xm, Ym = X / MM, Y / MM                   # millimetres

    sd_s = sd_rrect(X, Y, 0, 0, CAS_W, CAS_H, mm(2.2))
    shell = cv.cov(sd_s)
    sd_t = sd_poly(X, Y, [(mm(a), mm(b)) for a, b in TRAP])
    sd_t = np.maximum(sd_t, sd_s)
    sd_win = window_sd(X, Y)
    win = cv.cov(sd_win)
    sd_lab = sd_rrect(X, Y, *[mm(v) for v in LABEL], mm(1.0))

    # ── shell: smoked, glossy polystyrene ──
    e = np.clip(-sd_s, 0, None)
    B = 1.6
    h = B * np.sqrt(1 - (1 - np.clip(e / B, 0, 1)) ** 2)
    h = h + 0.9 * (1 - smoothstep(-0.9, 0.3, sd_t))                 # the raised trapezoid
    for sx, sy in SCREWS:
        rs = np.hypot(Xm - sx, Ym - sy)
        h = h - 0.9 * (1 - smoothstep(1.5, 2.0, rs))
    h = h - 0.6 * (1 - smoothstep(-0.2, 1.0, window_sd(X, Y, 1.0)))  # the window recess
    nx, ny, nz = normals(h, n)
    lam = lambert(nx, ny, nz)
    u = X / CAS_W
    t = Y / CAS_H
    env = 0.012 * np.exp(-((u * 0.8 + t * 0.6 - 0.30) / 0.22) ** 2) + 0.004 * (1 - t)
    base = 0.0065 * (0.35 + 0.65 * lam) + env + 0.85 * blinn(nx, ny, nz, 90) + 0.05 * blinn(nx, ny, nz, 8)
    # the lamp above the bay catches the shell's top and side edges
    base = base + (0.020 * np.exp(-e / 0.7) * (0.35 + 0.65 * smoothstep(CAS_H * 0.6, 0, Y)))
    col = gray3(base, (1.0, 1.0, 1.04))

    # inside the trapezoid, seen through the smoke: guide rollers, the tape,
    # capstan and pin holes, the felt pressure pad on its spring
    trap = cv.cov(sd_t)
    smoke = rgb3((0.55, 0.55, 0.60))
    inner = gray3(np.full_like(X, 0.0045))
    ty0, ty1 = mm(60.9), mm(62.4)
    tape = cv.cov(sd_rrect(X, Y, mm(15.6), ty0, mm(84.8), ty1, 0.2))
    tape_c = rgb3((0.150, 0.080, 0.036)) * (1 + 0.8 * np.exp(-((Y - ty0 - 0.3) / 0.35) ** 2))[..., None]
    inner = mix(inner, tape_c, tape)
    for rx in (15.9, 84.5):
        rr = np.hypot(Xm - rx, Ym - 59.9) * MM
        ro = cv.cov(rr - mm(1.9))
        rc = gray3(0.30 * (0.5 + 0.5 * smoothstep(mm(1.9), 0, rr)) + 0.4 * np.exp(-((Xm - rx + 0.6) ** 2 + (Ym - 59.4) ** 2) / 0.3))
        rc = mix(rc, gray3(np.full_like(X, 0.02)), cv.cov(rr - mm(0.5)))
        inner = mix(inner, rc, ro)
    pad = cv.cov(sd_rrect(X, Y, mm(47.4), mm(60.3), mm(53.0), mm(61.9), 0.3))
    inner = mix(inner, gray3(0.16 + 0.03 * grain(X.shape, rng, 0.6)), pad)
    spring = cv.cov(sd_rrect(X, Y, mm(42.5), mm(59.6), mm(57.9), mm(60.2), 0.3))
    inner = mix(inner, rgb3((0.22, 0.14, 0.05)), spring)
    col = mix(col, inner * smoke + col * 0.6, trap * 0.85)
    for hx in (26.0, 74.4):
        rh_ = np.hypot(Xm - hx, Ym - 58.0) * MM
        hole = cv.cov(rh_ - mm(1.55))
        wall = np.exp(-np.clip(mm(1.55) - rh_, 0, None) / 0.8)
        hc = gray3(0.002 + 0.03 * wall * smoothstep(0, 1, (Y - (mm(58.0))) / mm(1.55)))
        col = mix(col, hc, hole)
    for px_ in (37.6, 62.8):
        sq = cv.cov(sd_rrect(X, Y, mm(px_ - 1.0), mm(58.6), mm(px_ + 1.0), mm(60.6), 0.5))
        col = mix(col, gray3(np.full_like(X, 0.003)), sq)

    # screws: dark phosphated heads with a cross recess
    for sx, sy in SCREWS:
        rs = np.hypot(Xm - sx, Ym - sy) * MM
        dx, dy = X - mm(sx), Y - mm(sy)
        hs = 0.7 * np.sqrt(np.clip(1 - (rs / mm(1.45)) ** 2, 0, 1))
        cross = (np.minimum(np.abs(dx), np.abs(dy)) < 0.55) & (np.maximum(np.abs(dx), np.abs(dy)) < mm(0.95))
        hs = hs - 0.5 * cross
        snx, sny, snz = normals(hs, n)
        sc = 0.03 * (0.3 + 0.7 * lambert(snx, sny, snz)) + 0.6 * blinn(snx, sny, snz, 30)
        sc = np.where(cross, 0.005, sc)
        col = mix(col, gray3(sc), cv.cov(rs - mm(1.45)))

    # ── label ──
    lab = np.clip(cv.cov(sd_lab) - win, 0, 1)
    if variant == "ivory":
        paper = rgb3((0.60, 0.555, 0.46))
    else:
        paper = rgb3((0.0115, 0.0112, 0.0108))
    pg = grain(X.shape, rng, 0.5)
    lt = smoothstep(0, 1, 1 - (u * 0.5 + t * 0.7))
    lab_c = paper * ((1 + 0.035 * pg) * (0.85 + 0.30 * lt))[..., None]
    sd_wr = sd_rrect(X, Y, *[mm(v) for v in WRITE], mm(0.8))
    if variant != "ivory":
        lab_c = mix(lab_c, lab_c * 1.55, cv.cov(sd_wr))
    gold = rgb3((0.55, 0.40, 0.11))
    gline = cv.cov(np.abs(sd_wr) - 0.22)
    lab_c = mix(lab_c, gold, 0.75 * gline)
    # stripes under the window
    def stripe(y0_, y1_, c, a=1.0):
        s = cv.cov(sd_rrect(X, Y, mm(WRITE[0]), mm(y0_), mm(WRITE[2]), mm(y1_), 0.1))
        v = (Y - mm(y0_)) / max(1e-3, mm(y1_ - y0_))
        shade = 0.8 + 0.35 * np.exp(-((v - 0.35) / 0.3) ** 2)
        return mix(lab_c, rgb3(c) * shade[..., None], s * a)
    lab_c = stripe(43.3, 44.9, (0.50, 0.36, 0.09))
    lab_c = stripe(45.7, 46.1, (0.25, 0.25, 0.26))
    lab_c = stripe(46.9, 47.2, (0.50, 0.36, 0.09), 0.8)
    # side ticks by the window: a small gold dot on each side
    for sx in (13.2, 87.2):
        d = cv.cov(np.hypot(Xm - sx, Ym - 31.0) * MM - mm(1.1))
        lab_c = mix(lab_c, gold * 1.1, d)
    # paper edge: a hairline of shadow round the label and round the cut-out
    lab_c = lab_c * (1 - 0.35 * np.exp(-np.clip(-sd_lab, 0, None) / 0.35))[..., None]
    col_srgb = srgb(col)
    lab_s = srgb(lab_c) if variant != "ivory" else srgb(lab_c)
    out_c = mix(col_srgb, lab_s, lab)
    cv.over(out_c, shell * (1 - win))

    # ── the clear window: a light smoke, its moulded rim, the hub holes ──
    ins_w = np.clip(-sd_win, 0, None)
    cv.over((0.02, 0.02, 0.025), 0.10 * win)
    cv.over((0, 0, 0), 0.55 * np.exp(-ins_w / 0.6) * win)
    gxw, gyw = np.gradient(sd_win)
    gl = np.sqrt(gxw * gxw + gyw * gyw) + 1e-6
    facing = np.clip(-(gxw / gl * LXY[0] + gyw / gl * LXY[1]), 0, 1)       # rim faces the light
    rim = np.exp(-((ins_w - 1.3) / 0.45) ** 2)
    cv.over((1, 1, 1), (0.05 + 0.22 * facing) * rim * win)
    for hx, hy in hubs_local():
        rr = np.hypot(X - hx, Y - hy)
        cv.over((1, 1, 1), 0.10 * np.exp(-((rr - 12.2) / 0.35) ** 2) * win)
        cv.over((0, 0, 0), 0.20 * np.exp(-((rr - 11.6) / 0.35) ** 2) * win)
    diag = u * 1.0 + t * 0.9
    refl = 0.07 * np.exp(-((diag - 0.42) / 0.10) ** 2) + 0.05 * np.exp(-((diag - 0.60) / 0.018) ** 2)
    cv.over((0.9, 0.92, 0.98), refl * win)
    save(cv.image(), out, "cas.png" if variant == "graphite" else "cas-" + variant + ".png")


def build_cassette_back(out):
    (hx0, hy), (hx1, _) = hubs_local()
    rw = mm(WIN_H_MM)
    m_ = 3
    x0, y0 = hx0 - rw - m_, hy - rw - m_
    cv = Canvas(x0, y0, hx1 - hx0 + 2 * (rw + m_), 2 * (rw + m_), PPT_CAS)
    X, Y = cv.X, cv.Y
    rng = np.random.default_rng(59)
    sd_win = window_sd(X, Y)
    # the slip sheet behind the packs: satin silver-grey, embossed in fine rings
    base = 0.16 * (1 + 0.04 * grain(X.shape, rng, 0.8))
    emb = np.zeros_like(X)
    for hx in (hx0, hx1):
        r = np.hypot(X - hx, Y - hy)
        emb = emb + 0.5 * np.sin(r * 2 * math.pi / 2.2) * np.exp(-r / 60.0)
    l = base * (1 + 0.10 * emb)
    l = l * (0.75 + 0.45 * smoothstep(hy + rw, hy - rw, Y))           # lamp from above
    ins = np.clip(-sd_win, 0, None)
    l = l * (1 - 0.75 * np.exp(-ins / 3.5))
    for hx in (hx0, hx1):
        r = np.hypot(X - hx, Y - hy)
        l = l * (1 - 0.8 * soft(r - 11.0, 1.0))
    cv.over(srgb(gray3(l, (1.0, 0.98, 0.95))), cv.cov(sd_win - 1.5))
    save(cv.image(), out, "cas-back.png")


def build_cassette_shadow(out):
    pad = 16
    cv = Canvas(-pad, -pad, CAS_W + 2 * pad, CAS_H + 2 * pad, 1.2, ss=1)
    X, Y = cv.X, cv.Y
    sd = sd_rrect(X, Y - 3.5, 1.5, 1.0, CAS_W - 1.5, CAS_H, mm(2.2))
    cv.over((0, 0, 0), 0.75 * soft(sd, 4.0))
    save(cv.image(), out, "cas-shadow.png")


def build_pack(out):
    R = mm(PACK_R_MM)
    cv = Canvas(-R - 1, -R - 1, 2 * R + 2, 2 * R + 2, PPT_CAS)
    X, Y = cv.X, cv.Y
    r = np.hypot(X, Y)
    phi = np.arctan2(Y, X)
    rng = np.random.default_rng(61)
    phl = math.atan2(LXY[1], LXY[0])
    fine = radial_noise(r, rng, 0.25, rmax=R + 2)
    coarse = radial_noise(r, rng, 2.5, rmax=R + 2)
    # the wound tape's edges: dark brown, rings, a satin bow tie towards the light
    base = rgb3((0.046, 0.024, 0.012)) * (1 + 0.12 * fine + 0.12 * coarse)[..., None]
    aniso = np.exp(-(np.sin(phi - phl) ** 2) / 0.05) * smoothstep(0.35 * R, 0.8 * R, r)
    spec = (0.150 * aniso * (1 + 0.35 * fine))[..., None] * rgb3((1.0, 0.78, 0.60))
    broad = (0.012 * np.exp(-((X + 0.35 * R) ** 2 + (Y + 0.45 * R) ** 2) / (2 * (0.45 * R) ** 2)))[..., None]
    col = base + spec + broad * rgb3((1.0, 0.85, 0.70))
    col = col * (1 - 0.45 * np.exp(-(R - r) / 0.6))[..., None]      # the outer turns
    cv.over(srgb(col), cv.cov(r - R))
    save(cv.image(), out, "pack.png")


def build_hub(out):
    RH = mm(HUB_R_MM)
    cv = Canvas(-RH - 1, -RH - 1, 2 * RH + 2, 2 * RH + 2, PPT_CAS)
    X, Y, n = cv.X, cv.Y, cv.n
    r = np.hypot(X, Y)
    phi = np.arctan2(Y, X)
    rng = np.random.default_rng(67)
    RHOLE = mm(4.3)
    # teeth: six, pointing inwards; the spindle's three splines sit between them
    ang = np.mod(phi, math.pi / 3) - math.pi / 6            # tooth centred on 30 + 60k degrees
    perp = r * np.sin(ang)
    wt = 1.2 + 0.35 * np.clip((r - 7.6) / (RHOLE - 7.6), 0, 1)
    tooth_sd = np.maximum(np.abs(perp) - wt, np.maximum(7.6 - r, r - RHOLE - 0.5))
    hub_sd = np.maximum(r - RH, RHOLE - r)
    body_sd = np.minimum(hub_sd, tooth_sd)
    body = cv.cov(body_sd)
    # ivory plastic, lit evenly (the directional light is hub-light.png)
    ivory = rgb3((0.40, 0.39, 0.35))
    l = 1 + 0.03 * grain(X.shape, rng, 0.7)
    l = l * (1 - 0.30 * np.exp(-np.clip(-body_sd, 0, None) / 0.5))                   # edges
    l = l * (1 - 0.25 * np.exp(-((r - mm(7.4)) / 0.5) ** 2)) * (1 + 0.12 * np.exp(-((r - mm(7.4) - 0.9) / 0.5) ** 2))
    l = l * (0.92 + 0.08 * smoothstep(RHOLE, RH, r))
    l = l * (1 - 0.45 * np.exp(-np.clip(RH - r, 0, None) / 0.45))                  # where the tape starts
    col = ivory * l[..., None]
    # the tape clamp let into the rim: a wedge with a hairline gap round it
    cl_sd = np.maximum(np.abs(r * np.sin(phi)) - 3.2 * (0.7 + 0.3 * (r - RH + 6) / 6), np.maximum(RH - 5.6 - r, -X))
    clamp = cv.cov(cl_sd)
    col = mix(col, ivory * 0.80, clamp)
    col = col * (1 - 0.55 * np.exp(-np.abs(cl_sd) / 0.28) * (r > RH - 6.4) * (X > 0))[..., None]
    # inside the hole: the deck's spindle, a dark shaft with three splines
    hole = 1 - body
    ang3 = np.mod(phi, 2 * math.pi / 3) - math.pi / 3
    sp_sd = np.maximum(np.abs(r * np.sin(ang3 + math.pi / 3)) - 0.65, r - 8.8)
    sp_sd = np.minimum(sp_sd, r - 4.6)
    hole_c = gray3(0.004 * (1 + 0.5 * smoothstep(RHOLE, 3, r)))
    spin = cv.cov(sp_sd)
    metal = gray3(0.030 + 0.020 * smoothstep(8.8, 2.0, r))
    cap = cv.cov(r - 2.2)
    capc = gray3(0.10 + 0.35 * np.exp(-r ** 2 / 1.2))
    hc = mix(mix(hole_c, metal, spin), capc, cap)
    full = mix(hc, col, body)
    cv.over(srgb(full), cv.cov(r - RH))
    save(cv.image(), out, "hub.png")

    # static light over the hub: gloss towards the lamp, shade on the far side
    cv = Canvas(-RH - 1, -RH - 1, 2 * RH + 2, 2 * RH + 2, PPT_CAS / 2, ss=2)
    X, Y = cv.X, cv.Y
    r = np.hypot(X, Y)
    d = X * LXY[0] + Y * LXY[1]                              # towards the light
    m = cv.cov(r - RH) * smoothstep(mm(4.3) - 0.5, mm(4.3) + 1.0, r)
    cv.over((0, 0, 0), 0.30 * smoothstep(0.1 * RH, -RH, d) * m)
    cv.over((1.0, 0.98, 0.94), 0.16 * np.exp(-((X - LXY[0] * 0.55 * RH) ** 2 + (Y - LXY[1] * 0.55 * RH) ** 2) / (2 * (0.38 * RH) ** 2)) * m)
    save(cv.image(), out, "hub-light.png")


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.normpath(os.path.join(here, "..", "..", "assets", "anim", "cassette")))
    ap.add_argument("--only", default="", help="comma separated builder names (debug)")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    builders = {"deck": build_deck, "fader": build_fader, "keys": build_keys, "led": build_led,
                "door": build_door, "dooredge": build_door_edge, "cassette": build_cassette,
                "back": build_cassette_back, "shadow": build_cassette_shadow, "pack": build_pack,
                "hub": build_hub}
    only = [s for s in args.only.split(",") if s]
    for k, f in builders.items():
        if not only or k in only:
            f(args.out)


if __name__ == "__main__":
    main()
