"""remote-draw.py MODEL OUT.png — a drawn remote in place of the photo, for remote-map.py.

The drawing lives in the photo's own coordinates (same width, keys at the positions in
<model>_keys.py), so remote-map.py places its labels and lines on it exactly as it does
on the photo: `remote-map.py OUT.png <model>_keys.py …`. Flat and without logos: the app
keys are coloured pills with their name in plain letters, the maker's name is left out.
Needs Pillow."""
import math, sys
from PIL import Image, ImageDraw, ImageFont

F = '/usr/share/fonts/truetype/dejavu/'
BG = (10, 10, 10)
BODY_TOP, BODY_BOTTOM, RIM = (52, 53, 58), (30, 31, 35), (78, 79, 85)
KEY, KEY_RIM, KEY_HI = (22, 23, 26), (60, 61, 66), (44, 45, 50)
INK = (232, 232, 232)
W_LINE = 12                                  # icon stroke, in photo pixels


def font(size, bold=True):
    return ImageFont.truetype(F + ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'), size)


class Remote:
    def __init__(self, w, h):
        self.im = Image.new('RGB', (w, h), BG)
        self.d = ImageDraw.Draw(self.im)

    # ── the body: rounded, a light from above, a thin rim ─────────────────
    def body(self, x0, y0, x1, y1, r):
        h = y1 - y0
        grad = Image.new('RGB', (x1 - x0, h))
        gd = ImageDraw.Draw(grad)
        for y in range(h):
            t = y / h
            gd.line([(0, y), (x1 - x0, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(BODY_TOP, BODY_BOTTOM)))
        mask = Image.new('L', (x1 - x0, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, x1 - x0 - 1, h - 1], r, fill=255)
        self.im.paste(grad, (x0, y0), mask)
        self.d.rounded_rectangle([x0, y0, x1, y1], r, outline=RIM, width=6)

    # ── keys ───────────────────────────────────────────────────────────────
    def round_key(self, cx, cy, r, fill=KEY, rim=KEY_RIM):
        self.d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill, outline=rim, width=5)

    def pill(self, cx, cy, w, h, fill=KEY, rim=KEY_RIM):
        self.d.rounded_rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], h / 2, fill=fill, outline=rim, width=5)

    def square_key(self, cx, cy, w, h, r=42):
        self.d.rounded_rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], r, fill=KEY, outline=KEY_RIM, width=5)

    def text(self, cx, cy, s, size, fill=INK, bold=True):
        f = font(size, bold)
        self.d.text((cx, cy), s, font=f, fill=fill, anchor='mm')

    # ── icons (s = half size) ──────────────────────────────────────────────
    def power(self, cx, cy, s, col=INK):
        self.d.arc([cx - s, cy - s, cx + s, cy + s], -58, 238, fill=col, width=W_LINE)
        self.d.line([(cx, cy - s * 1.15), (cx, cy - s * 0.15)], fill=col, width=W_LINE)

    def back_uturn(self, cx, cy, s, col=INK):
        r = s * 0.45
        ax = cx + s * 0.15
        self.d.line([(cx - s * 0.35, cy - r), (ax, cy - r)], fill=col, width=W_LINE)
        self.d.arc([ax - r, cy - r, ax + r, cy + r], -90, 90, fill=col, width=W_LINE)
        self.d.line([(ax, cy + r), (cx - s * 0.55, cy + r)], fill=col, width=W_LINE)
        t = s * 0.32
        self.d.polygon([(cx - s * 0.85, cy + r), (cx - s * 0.5, cy + r - t), (cx - s * 0.5, cy + r + t)], fill=col)

    def back_arrow(self, cx, cy, s, col=INK):
        self.d.line([(cx - s * 0.8, cy), (cx + s * 0.8, cy)], fill=col, width=W_LINE)
        self.d.line([(cx - s * 0.8, cy), (cx - s * 0.2, cy - s * 0.6)], fill=col, width=W_LINE)
        self.d.line([(cx - s * 0.8, cy), (cx - s * 0.2, cy + s * 0.6)], fill=col, width=W_LINE)

    def home(self, cx, cy, s, col=INK):
        pts = [(cx - s * 0.75, cy - s * 0.05), (cx, cy - s * 0.75), (cx + s * 0.75, cy - s * 0.05),
               (cx + s * 0.6, cy - s * 0.05), (cx + s * 0.6, cy + s * 0.7), (cx - s * 0.6, cy + s * 0.7),
               (cx - s * 0.6, cy - s * 0.05)]
        self.d.line(pts + [pts[0]], fill=col, width=W_LINE, joint='curve')

    def menu(self, cx, cy, s, col=INK):
        for dy in (-0.5, 0, 0.5):
            self.d.line([(cx - s * 0.75, cy + dy * s), (cx + s * 0.75, cy + dy * s)], fill=col, width=W_LINE)

    def tri(self, cx, cy, s, right=True, col=INK):
        k = 1 if right else -1
        self.d.polygon([(cx - k * s * 0.5, cy - s * 0.6), (cx + k * s * 0.55, cy), (cx - k * s * 0.5, cy + s * 0.6)], fill=col)

    def rew(self, cx, cy, s, col=INK):
        self.tri(cx - s * 0.4, cy, s * 0.8, False, col); self.tri(cx + s * 0.4, cy, s * 0.8, False, col)

    def ff(self, cx, cy, s, col=INK):
        self.tri(cx - s * 0.4, cy, s * 0.8, True, col); self.tri(cx + s * 0.4, cy, s * 0.8, True, col)

    def playpause(self, cx, cy, s, col=INK):
        self.tri(cx - s * 0.35, cy, s * 0.85, True, col)
        for x in (0.35, 0.68):
            self.d.rectangle([cx + s * x, cy - s * 0.5, cx + s * x + s * 0.16, cy + s * 0.5], fill=col)

    def prev(self, cx, cy, s, col=INK):
        self.d.rectangle([cx - s * 0.85, cy - s * 0.5, cx - s * 0.7, cy + s * 0.5], fill=col)
        self.tri(cx - s * 0.2, cy, s * 0.75, False, col); self.tri(cx + s * 0.45, cy, s * 0.75, False, col)

    def next(self, cx, cy, s, col=INK):
        self.tri(cx - s * 0.45, cy, s * 0.75, True, col); self.tri(cx + s * 0.2, cy, s * 0.75, True, col)
        self.d.rectangle([cx + s * 0.7, cy - s * 0.5, cx + s * 0.85, cy + s * 0.5], fill=col)

    def speaker(self, cx, cy, s, col=INK):
        self.d.polygon([(cx - s * 0.8, cy - s * 0.25), (cx - s * 0.45, cy - s * 0.25), (cx, cy - s * 0.65),
                        (cx, cy + s * 0.65), (cx - s * 0.45, cy + s * 0.25), (cx - s * 0.8, cy + s * 0.25)], fill=col)

    def mute(self, cx, cy, s, col=INK):
        self.speaker(cx - s * 0.2, cy, s, col)
        self.d.line([(cx + s * 0.25, cy - s * 0.3), (cx + s * 0.85, cy + s * 0.3)], fill=col, width=W_LINE)
        self.d.line([(cx + s * 0.25, cy + s * 0.3), (cx + s * 0.85, cy - s * 0.3)], fill=col, width=W_LINE)

    def mute_slash(self, cx, cy, s, col=INK):
        self.speaker(cx + s * 0.1, cy, s, col)
        self.d.line([(cx - s * 0.8, cy - s * 0.8), (cx + s * 0.8, cy + s * 0.8)], fill=col, width=W_LINE)

    def vol(self, cx, cy, s, waves, col=INK):
        self.speaker(cx - s * 0.25, cy, s * 0.9, col)
        for i in range(waves):
            r = s * (0.45 + 0.35 * i)
            self.d.arc([cx - s * 0.25 - r, cy - r, cx - s * 0.25 + r, cy + r], -45, 45, fill=col, width=W_LINE - 2)

    def tv(self, cx, cy, s, col=INK):
        self.d.rounded_rectangle([cx - s * 0.75, cy - s * 0.3, cx + s * 0.75, cy + s * 0.7], 8, outline=col, width=W_LINE)
        self.d.line([(cx - s * 0.4, cy - s * 0.85), (cx, cy - s * 0.35)], fill=col, width=W_LINE)
        self.d.line([(cx + s * 0.4, cy - s * 0.85), (cx, cy - s * 0.35)], fill=col, width=W_LINE)

    def plus(self, cx, cy, s, col=INK):
        self.d.line([(cx - s, cy), (cx + s, cy)], fill=col, width=W_LINE)
        self.d.line([(cx, cy - s), (cx, cy + s)], fill=col, width=W_LINE)

    def minus(self, cx, cy, s, col=INK):
        self.d.line([(cx - s, cy), (cx + s, cy)], fill=col, width=W_LINE)

    def ring(self, cx, cy, s, col=INK, w=W_LINE):
        self.d.ellipse([cx - s, cy - s, cx + s, cy + s], outline=col, width=w)

    def rocker(self, cx, y0, y1, w):
        self.d.rounded_rectangle([cx - w / 2, y0, cx + w / 2, y1], w / 2, fill=KEY, outline=KEY_RIM, width=5)
        self.plus(cx, y0 + w * 0.55, w * 0.2)
        self.minus(cx, y1 - w * 0.55, w * 0.2)

    def dpad(self, cx, cy, ro, ri, dots=False, ok=False, ring_fill=(14, 14, 16), centre=(34, 35, 39)):
        self.d.ellipse([cx - ro, cy - ro, cx + ro, cy + ro], fill=ring_fill, outline=KEY_RIM, width=6)
        self.d.ellipse([cx - ri, cy - ri, cx + ri, cy + ri], fill=centre, outline=(12, 12, 14), width=6)
        if dots:
            m = (ro + ri) / 2
            for dx, dy in ((0, -m), (0, m), (-m, 0), (m, 0)):
                self.d.ellipse([cx + dx - 9, cy + dy - 9, cx + dx + 9, cy + dy + 9], fill=INK)
        if ok:
            self.ring(cx, cy, ri - 14, INK, 7)
            self.text(cx, cy, 'OK', int(ri * 0.62))


def _mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


# ── the three remotes ─────────────────────────────────────────────────────
def firetv():
    r = Remote(1030, 2900)
    r.body(47, 86, 944, 2880, 190)
    r.d.rounded_rectangle([484, 188, 508, 250], 12, fill=(12, 12, 14))            # the microphone
    r.round_key(224, 285, 92); r.power(224, 285, 46)
    r.round_key(488, 474, 98, fill=(38, 190, 214), rim=(20, 150, 170))              # the voice key
    r.ring(488, 474, 40, (240, 250, 252), 12)
    r.dpad(488, 1000, 352, 212)
    r.round_key(224, 1527, 96); r.back_uturn(224, 1527, 58)
    r.round_key(488, 1527, 96); r.home(488, 1527, 54)
    r.round_key(750, 1527, 96); r.menu(750, 1527, 54)
    r.round_key(224, 1785, 96); r.rew(224, 1785, 54)
    r.round_key(488, 1785, 96); r.playpause(488, 1785, 54)
    r.round_key(750, 1785, 96); r.ff(750, 1785, 54)
    r.round_key(224, 2044, 96); r.mute(224, 2044, 58)
    r.rocker(488, 1960, 2410, 200)
    r.round_key(750, 2036, 96); r.tv(750, 2036, 58)
    for cx, cy, fill, ink, name in ((293, 2544, (27, 152, 200), INK, 'prime video'),
                                    (681, 2544, (240, 240, 240), (214, 32, 54), 'NETFLIX'),
                                    (293, 2760, (26, 44, 110), INK, 'Disney+'),
                                    (681, 2760, (30, 52, 112), INK, 'amazon music')):
        r.pill(cx, cy, 320, 132, fill=fill, rim=_mix(fill, (0, 0, 0), 0.35))
        r.text(cx, cy, name, 40 if len(name) > 8 else 46, ink)
    return r.im


def g20s():
    r = Remote(1213, 3400)
    r.body(61, 97, 1140, 3380, 150)
    r.d.ellipse([545, 280, 565, 300], fill=(12, 12, 14)); r.d.ellipse([545, 364, 565, 384], fill=(200, 200, 200))
    r.round_key(263, 332, 92); r.power(263, 332, 46)
    r.round_key(829, 322, 92); r.mute_slash(829, 322, 56)
    r.round_key(273, 595, 92); r.text(273, 595, 'Pg+', 50)
    r.round_key(553, 597, 92)                                                         # the mouse pointer key
    r.d.polygon([(535, 560), (535, 630), (551, 614), (563, 640), (575, 634), (563, 608), (585, 606)], fill=INK)
    r.round_key(829, 595, 92); r.text(829, 595, 'Pg-', 50)
    r.dpad(560, 1150, 410, 165, dots=True, ok=True)
    # back and home share one rocker
    r.d.rounded_rectangle([207, 1540, 913, 1745], 100, fill=KEY, outline=KEY_RIM, width=5)
    r.d.line([(560, 1560), (560, 1725)], fill=(12, 12, 14), width=6)
    r.back_uturn(380, 1658, 58); r.home(751, 1658, 54)
    r.round_key(289, 1930, 92); r.vol(289, 1930, 54, 1)
    r.round_key(571, 1930, 92)
    for i, hgt in enumerate((0.25, 0.5, 0.8, 1.0, 0.8, 0.5, 0.25)):
        x = 571 + (i - 3) * 16
        r.d.line([(x, 1930 - hgt * 42), (x, 1930 + hgt * 42)], fill=INK, width=8)
    r.round_key(854, 1930, 92); r.vol(854, 1930, 54, 2)
    r.round_key(289, 2204, 92); r.prev(289, 2204, 54)
    r.round_key(571, 2204, 92); r.playpause(571, 2204, 54)
    r.round_key(854, 2204, 92); r.next(854, 2204, 54)
    digits = [('1', 302, 2476), ('2', 575, 2476), ('3', 858, 2476), ('4', 302, 2720), ('5', 581, 2720),
              ('6', 858, 2710), ('7', 308, 2954), ('8', 581, 2954), ('9', 858, 2944), ('0', 581, 3188)]
    for n, x, y in digits:
        r.square_key(x, y, 205, 172); r.text(x, y, n, 84, bold=False)
    r.square_key(312, 3198, 205, 172)                                                  # delete
    r.text(312, 3168, 'DEL', 46)
    r.d.polygon([(262, 3222), (286, 3198), (362, 3198), (362, 3246), (286, 3246)], outline=INK, width=6)
    r.square_key(858, 3188, 205, 172)                                                  # the light bulb
    r.d.ellipse([806, 3140, 846, 3180], outline=INK, width=6); r.d.line([(818, 3186), (834, 3186)], fill=INK, width=6)
    r.d.line([(848, 3226), (880, 3150)], fill=INK, width=6)
    for i in range(3):
        r.d.line([(876 + i * 4, 3200 + i * 14), (910, 3200 + i * 14)], fill=INK, width=6)
    return r.im


def xiaomi():
    r = Remote(1213, 2700)
    r.body(117, 146, 1067, 2680, 170)
    r.round_key(556, 312, 92); r.power(556, 312, 46, (226, 58, 48))
    r.round_key(556, 575, 92)                                                         # the microphone
    r.d.rounded_rectangle([538, 530, 574, 598], 18, fill=(66, 133, 244))
    r.d.arc([522, 560, 590, 628], 0, 180, fill=(234, 67, 53), width=7)
    r.d.line([(556, 628), (556, 648)], fill=(52, 168, 83), width=7)
    r.d.line([(540, 650), (572, 650)], fill=(251, 188, 5), width=7)
    r.dpad(566, 1121, 360, 153)
    r.round_key(312, 1658, 92)
    for i in range(3):
        for j in range(3):
            x, y = 288 + i * 24, 1634 + j * 24
            r.d.rectangle([x - 7, y - 7, x + 7, y + 7], fill=INK)
    r.round_key(579, 1658, 92); r.back_arrow(579, 1658, 58)
    r.round_key(854, 1658, 92); r.ring(854, 1658, 34, INK, 10)
    r.pill(380, 1901, 320, 140); r.text(380, 1901, 'NETFLIX', 46, (226, 36, 58))
    r.pill(780, 1892, 320, 140); r.text(800, 1892, 'LIVE', 46)
    r.d.chord([684, 1862, 744, 1922], 45, 225, fill=INK)                              # a small dish
    r.d.line([(714, 1892), (738, 1868)], fill=INK, width=7); r.d.ellipse([734, 1858, 748, 1872], fill=INK)
    r.rocker(595, 2034, 2503, 176)
    return r.im


if __name__ == '__main__':
    model, out = sys.argv[1:3]
    {'firetv': firetv, 'g20s': g20s, 'xiaomi': xiaomi}[model]().save(out)
