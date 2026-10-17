#!/usr/bin/env python3
"""Generate the static installer-image manifest read by Osmium Flasher.

Usage:
    make-iso-manifest.py <version> <iso> [base_url] [--img <img.xz>] [--out <name>]

Writes ``manifest-out/<name>`` (``latest.json`` by default; the development
channel's is ``latest-dev.json``) in the same shape as the OTA manifests
produced by make-ota-manifest.py (``tag_name`` + ``assets[]`` with
``browser_download_url`` and ``size``), so both consumers parse one format.

With ``--img`` the ready-to-boot USB image (build-usb-image.sh, ``.img.xz``)
is listed next to the ISO, with ``raw_size``: the size of the disk it unpacks
to, which is what has to fit on the stick. Flasher 1.0.1 and older take the
first ``.iso`` asset and ignore the rest, so the extra entries do not disturb
them.

Unlike the OTA manifests, this one is not pushed to gh-pages: the images go
to the root of file.osmiumsound.it (publish-iso-r2.yml, after build-iso.yml),
and the manifest travels with them in the same upload. The flasher reads it
from there, which is also why the URLs are built from ``base_url`` rather than
from the GitHub release CDN.
"""
import argparse
import json
import os
import subprocess
import sys

DEFAULT_BASE = "https://file.osmiumsound.it"


def xz_raw_size(path):
    """Uncompressed size from the .xz index (xz --robot --list), or None."""
    try:
        out = subprocess.run(["xz", "--robot", "--list", path], check=True,
                             capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    for line in out.splitlines():
        cols = line.split("\t")
        if cols[0] == "totals" and len(cols) > 4:
            return int(cols[4])
    return None


def entries(path, base, extra=None):
    """The image and its two sidecars. The .sha256.sig is what makes the
    digest trustworthy; the flasher refuses any image that arrives without
    it, so a missing file here is fatal rather than merely omitted."""
    name = os.path.basename(path)
    out = []
    for suffix in ("", ".sha256", ".sha256.sig"):
        p = path + suffix
        if not os.path.exists(p):
            sys.exit(f"missing required asset: {p}")
        entry = {
            "name": name + suffix,
            "browser_download_url": f"{base}/{name}{suffix}",
            "size": os.path.getsize(p),
        }
        if suffix == "" and extra:
            entry.update(extra)
        out.append(entry)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("version")
    ap.add_argument("iso")
    ap.add_argument("base", nargs="?", default=DEFAULT_BASE)
    ap.add_argument("--img", help="the .img.xz USB image to list next to the ISO")
    ap.add_argument("--out", default="latest.json", help="manifest file name")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    assets = entries(args.iso, base)
    if args.img:
        raw = xz_raw_size(args.img)
        if raw is None:
            sys.exit(f"could not read the uncompressed size of {args.img} (is xz installed?)")
        assets += entries(args.img, base, {"raw_size": raw})

    os.makedirs("manifest-out", exist_ok=True)
    out = os.path.join("manifest-out", os.path.basename(args.out))
    with open(out, "w") as f:
        json.dump(
            {"tag_name": args.version, "name": args.version, "body": "", "assets": assets},
            f, indent=2,
        )
    print(f"wrote {out} with {len(assets)} assets")


if __name__ == "__main__":
    main()
