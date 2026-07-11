from pathlib import Path
from PIL import Image

BASE_ICON = Path("logo.png")
OUTPUT_DIR = Path("android/app/src/main/res")

DENSITIES = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}


def generate_icons():
    img = Image.open(BASE_ICON)
    if img.mode != "RGBA":
        img = img.convert("RGBA")

    for folder, size in DENSITIES.items():
        out_folder = OUTPUT_DIR / folder
        out_folder.mkdir(parents=True, exist_ok=True)
        resized = img.resize((size, size), Image.Resampling.LANCZOS)
        out_path = out_folder / "ic_launcher.png"
        resized.save(out_path, "PNG")
        print(f"Generata: {out_path} ({size}x{size})")


if __name__ == "__main__":
    generate_icons()
