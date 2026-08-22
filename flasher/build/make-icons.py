#!/usr/bin/env python3
"""Regenerate the app icons from the project logo.

    pip install Pillow
    python3 build/make-icons.py

Writes:
    build/icon.png    1024x1024 — electron-builder derives the .ico and .icns
                                  from this at build time; neither is committed.
    assets/icon.png    256x256  — the BrowserWindow icon, which Linux needs set
                                  explicitly (see src/main.js).

The source logo is a 800x468 hero image: a circular emblem with "OSMIUM SOUND"
lettering underneath. Squashing that into a square would render the lettering
illegible by 32px, so only the emblem is used, cropped just above the text and
padded so the gold ring does not touch the edges.
"""
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is required: pip install Pillow")

ROOT = Path(__file__).resolve().parents[2]
FLASHER = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "logo.png"

# Centre of the emblem in the source, and the half-width that keeps the crop
# clear of the "OSMIUM" lettering starting around y=330.
CENTRE_X, CENTRE_Y, HALF = 403, 177, 148
PADDING = 1.18   # canvas grows by this factor, so the ring has some air


def main():
    if not SOURCE.exists():
        sys.exit(f"logo not found: {SOURCE}")

    src = Image.open(SOURCE).convert("RGBA")
    emblem = src.crop((CENTRE_X - HALF, CENTRE_Y - HALF,
                       CENTRE_X + HALF, CENTRE_Y + HALF))

    background = src.convert("RGB").getpixel((6, 6))  # the logo's own backdrop
    side = int(emblem.size[0] * PADDING)
    canvas = Image.new("RGBA", (side, side), background + (255,))
    offset = (side - emblem.size[0]) // 2
    canvas.paste(emblem, (offset, offset), emblem)

    master = canvas.resize((1024, 1024), Image.LANCZOS)
    master.save(FLASHER / "build" / "icon.png")
    master.resize((256, 256), Image.LANCZOS).save(FLASHER / "assets" / "icon.png")
    print("wrote build/icon.png (1024) and assets/icon.png (256)")


if __name__ == "__main__":
    main()
