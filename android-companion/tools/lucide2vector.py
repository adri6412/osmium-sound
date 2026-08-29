#!/usr/bin/env python3
"""Turn the appliance's Lucide icons into Android VectorDrawables.

The device draws with the SVGs in native-ui-qt/icons/, generated from the same
lucide-react the kiosk uses (see native-ui-qt/tools/gen-icons.mjs). This script
is the Android end of that pipeline, so the phone draws exactly the same glyphs
instead of the Material icons inherited from android-squeezer.

Only the handful of shapes Lucide actually emits are handled — path, polygon,
polyline, line, circle, rect — and the colour is dropped: the drawables are
tinted at use, which is what both the Qt and the Android side already do.

  usage: lucide2vector.py <icons-dir> <out-dir> <name>[:<android-name>] ...
"""
import re
import sys
from pathlib import Path
from xml.etree import ElementTree

SVG_NS = "{http://www.w3.org/2000/svg}"

HEADER = """<?xml version="1.0" encoding="utf-8"?>
<!--
 Lucide "{name}", converted from native-ui-qt/icons/{name}.svg so the phone and
 the appliance draw the same glyph. Regenerate with
 android-companion/tools/lucide2vector.py rather than editing by hand.
-->
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="24dp"
    android:height="24dp"
    android:viewportWidth="24"
    android:viewportHeight="24"
    android:tint="?attr/colorControlNormal">
"""

STROKE_PATH = """    <path
        android:pathData="{data}"
        android:strokeWidth="2"
        android:strokeColor="#FFFFFFFF"
        android:strokeLineCap="round"
        android:strokeLineJoin="round" />
"""

FILL_PATH = """    <path
        android:pathData="{data}"
        android:fillColor="#FFFFFFFF" />
"""


def points_to_path(points, close):
    numbers = [n for n in re.split(r"[\s,]+", points.strip()) if n]
    pairs = list(zip(numbers[0::2], numbers[1::2]))
    data = "M" + " L".join(f"{x},{y}" for x, y in pairs)
    return data + " Z" if close else data


def circle_to_path(cx, cy, r):
    cx, cy, r = float(cx), float(cy), float(r)
    # Two arcs: SVG cannot draw a full circle with a single arc command.
    return (f"M{cx - r},{cy} a{r},{r} 0 1,0 {2 * r},0 "
            f"a{r},{r} 0 1,0 {-2 * r},0 Z")


def rect_to_path(x, y, w, h, rx):
    x, y, w, h = float(x), float(y), float(w), float(h)
    if rx:
        r = float(rx)
        return (f"M{x + r},{y} L{x + w - r},{y} Q{x + w},{y} {x + w},{y + r} "
                f"L{x + w},{y + h - r} Q{x + w},{y + h} {x + w - r},{y + h} "
                f"L{x + r},{y + h} Q{x},{y + h} {x},{y + h - r} "
                f"L{x},{y + r} Q{x},{y} {x + r},{y} Z")
    return f"M{x},{y} L{x + w},{y} L{x + w},{y + h} L{x},{y + h} Z"


def convert(svg_path):
    root = ElementTree.parse(svg_path).getroot()
    filled = (root.get("fill") or "none") != "none"
    body = []
    for element in root:
        tag = element.tag.replace(SVG_NS, "")
        if tag == "path":
            data = element.get("d")
        elif tag == "polygon":
            data = points_to_path(element.get("points"), close=True)
        elif tag == "polyline":
            data = points_to_path(element.get("points"), close=False)
        elif tag == "line":
            data = (f"M{element.get('x1')},{element.get('y1')} "
                    f"L{element.get('x2')},{element.get('y2')}")
        elif tag == "circle":
            data = circle_to_path(element.get("cx"), element.get("cy"), element.get("r"))
        elif tag == "rect":
            data = rect_to_path(element.get("x", "0"), element.get("y", "0"),
                                element.get("width"), element.get("height"),
                                element.get("rx"))
        else:
            raise SystemExit(f"{svg_path.name}: unhandled element <{tag}>")
        # A filled icon still strokes its outline in Lucide; drawing both keeps
        # the glyph the same weight as on the appliance.
        body.append((FILL_PATH if filled else STROKE_PATH).format(data=data))
        if filled:
            body.append(STROKE_PATH.format(data=data))
    return HEADER.format(name=svg_path.stem) + "".join(body) + "</vector>\n"


def main():
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    icons, out = Path(sys.argv[1]), Path(sys.argv[2])
    for spec in sys.argv[3:]:
        source, _, target = spec.partition(":")
        target = target or source
        svg = icons / f"{source}.svg"
        if not svg.exists():
            raise SystemExit(f"missing {svg}")
        (out / f"{target}.xml").write_text(convert(svg), encoding="utf-8")
        print(f"{source}.svg -> {target}.xml")


if __name__ == "__main__":
    main()
