"""remote-map.py PHOTO KEYS.py LANG OUT.png TITLE [--ui] — the photo of a remote with, next to
every key, the action it does out of the box (names from the web admin's translations).

The key tables (<model>_keys.py) hold each key's position on the photo, its evdev code and the
action kModels in native-ui-qt/src/remote.cpp gives it: change both together. --ui renders the
variant the interface shows (no title, no key codes); make-all.sh writes every picture into
native-ui-qt/assets/remotes and admin-webui/public/remotes. Needs Pillow."""
import os, sys, json, importlib.util
from PIL import Image, ImageDraw, ImageFont

TR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../../admin-webui/src/i18n/locales/%s.json')

photo, keys_py, lang, out, title = sys.argv[1:6]
# the pictures inside the interface: no title (the card has one) and no
# key codes (jargon to the person holding the remote)
UI = '--ui' in sys.argv
spec = importlib.util.spec_from_file_location('k', keys_py); k = importlib.util.module_from_spec(spec); spec.loader.exec_module(k)
tr = json.load(open(TR % lang))
ACT = tr['settings']['remote']['actions']
EXTRA = {'it': {'shortcut': 'scorciatoia'}, 'en': {'shortcut': 'shortcut'}}[lang]
# 🚨 No shorter names of our own here: the picture once said "Context menu"
# while the list of actions said "Menu of the chosen item", and whoever looked
# for the picture's words in the list thought actions were missing. If a name
# is too long for the picture, shorten it in the translations, for both.

BG, GOLD, WHITE, GREY = (10, 10, 10), (212, 175, 55), (240, 240, 240), (150, 150, 150)
F = '/usr/share/fonts/truetype/dejavu/'
fAct = ImageFont.truetype(F + 'DejaVuSans-Bold.ttf', 25)
fKey = ImageFont.truetype(F + 'DejaVuSansMono.ttf', 16)
fTitle = ImageFont.truetype(F + 'DejaVuSans-Bold.ttf', 38)

src = Image.open(photo).convert('RGB')
if getattr(k, 'CROP_BOTTOM', 0): src = src.crop((0, 0, src.width, k.CROP_BOTTOM))
RH = 1560                                   # height of the remote on the board
sc = RH / src.height
rem = src.resize((round(src.width * sc), RH), Image.LANCZOS)
_m = ImageDraw.Draw(Image.new('RGB', (1, 1)))
LW = max(max(_m.textlength(ACT.get(kk[4], kk[4]), font=fAct), _m.textlength(kk[3] + '  ·  ' + EXTRA.get(kk[5], kk[5]) if len(kk) > 5 else kk[3], font=fKey)) for kk in k.KEYS)
W, TOP = int(rem.width + 2 * (LW + 110)), (40 if UI else 120)
H = TOP + RH + 50
rx = (W - rem.width) // 2
img = Image.new('RGB', (W, H), BG)
img.paste(rem, (rx, TOP))
d = ImageDraw.Draw(img)
tw = d.textlength(title, font=fTitle)
if not UI: d.text(((W - tw) / 2, 34), title, font=fTitle, fill=WHITE)

# keys in the left column get their label on the left, the others on the
# right; the centre column alternates so one side does not get crowded
mid = src.width / 2
items = []
for i, (name, x, y, code, act, *rest) in enumerate(k.KEYS):
    side = getattr(k, 'SIDE', {}).get(name)
    if side is None:
        side = 'L' if x < mid - 80 else 'R' if x > mid + 80 else ('R' if i % 2 else 'L')
    items.append(dict(name=name, x=x, y=y, bx=rx + x * sc, by=TOP + y * sc, code=code, act=act, side=side,
                      note=rest[0] if rest else ''))

# The lane: a line that would cross another key on its way out first drops
# (or rises) into the gap between two rows, where there is nothing.
R = getattr(k, 'CLEAR', 75)                 # a key's radius, in photo pixels
def blocked(it, y):
    for o in items:
        if o is it: continue
        between = (o['x'] < it['x']) if it['side'] == 'L' else (o['x'] > it['x'])
        if between and abs(o['y'] - y) < R: return True
    return False
for it in items:
    it['lane'] = it['y']
    if blocked(it, it['y']):
        for dy in (130, -130, 150, -150, 110, -110, 170, -170):
            if not blocked(it, it['y'] + dy): it['lane'] = it['y'] + dy; break
    it['ly0'] = TOP + it['lane'] * sc

GAP = 60
for side in 'LR':
    col = sorted([it for it in items if it['side'] == side], key=lambda it: it['ly0'])
    # label positions: next to their key, never overlapping
    ys = [it['ly0'] for it in col]
    for i in range(1, len(ys)):
        ys[i] = max(ys[i], ys[i - 1] + GAP)
    for i in range(len(ys) - 2, -1, -1):
        ys[i] = min(ys[i], ys[i + 1] - GAP)
    for it, ly in zip(col, ys):
        lane = (ly - TOP) / sc
        if abs(ly - it['ly0']) > 0.5 and not blocked(it, lane):
            it['ly0'] = ly                  # the line reaches the label straight
        label = ACT.get(it['act'], it['act'])
        note = EXTRA.get(it['note'], it['note']) if it['note'] else ''
        sub = note if UI else it['code'] + ('  ·  ' + note if note else '')
        edge = rx - 30 if side == 'L' else rx + rem.width + 30
        elbow = rx - 12 if side == 'L' else rx + rem.width + 12
        # the line: from the key to the edge of the remote, then to the label
        d.line([(it['bx'], it['by']), (it['bx'], it['ly0']), (elbow, it['ly0']), (edge, ly)], fill=GOLD, width=2, joint='curve')
        d.ellipse((it['bx'] - 7, it['by'] - 7, it['bx'] + 7, it['by'] + 7), outline=GOLD, width=3)
        aw = d.textlength(label, font=fAct); kw = d.textlength(sub, font=fKey)
        if side == 'L':
            d.text((edge - 12 - aw, ly - (22 if sub else 15)), label, font=fAct, fill=WHITE)
            d.text((edge - 12 - kw, ly + 7), sub, font=fKey, fill=GREY)
        else:
            d.text((edge + 12, ly - (22 if sub else 15)), label, font=fAct, fill=WHITE)
            d.text((edge + 12, ly + 7), sub, font=fKey, fill=GREY)
img.save(out)
print(out, img.size)
