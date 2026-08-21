#!/usr/bin/env python3
"""Generate the static installer-image manifest read by Osmium Flasher.

Usage:
    make-iso-manifest.py <version> <iso> [base_url]

Writes ``manifest-out/latest.json`` in the same shape as the OTA manifests
produced by make-ota-manifest.py (``tag_name`` + ``assets[]`` with
``browser_download_url`` and ``size``), so both consumers parse one format.

Unlike the OTA manifests, this one is not pushed to gh-pages: the ISO is
uploaded by hand to file.osmiumsound.it, and latest.json travels with it in the
same upload. The flasher reads it from there, which is also why the URLs are
built from ``base_url`` rather than from the GitHub release CDN.
"""
import json
import os
import sys

DEFAULT_BASE = "https://file.osmiumsound.it"


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    version, iso = sys.argv[1:3]
    base = (sys.argv[3] if len(sys.argv) > 3 else DEFAULT_BASE).rstrip("/")

    name = os.path.basename(iso)
    assets = []
    # The .sha256.sig is what makes the digest trustworthy; the flasher refuses
    # any release that arrives without it, so a missing file here is fatal
    # rather than merely omitted from the manifest.
    for suffix in ("", ".sha256", ".sha256.sig"):
        path = iso + suffix
        if not os.path.exists(path):
            sys.exit(f"missing required asset: {path}")
        assets.append({
            "name": name + suffix,
            "browser_download_url": f"{base}/{name}{suffix}",
            "size": os.path.getsize(path),
        })

    os.makedirs("manifest-out", exist_ok=True)
    out = "manifest-out/latest.json"
    with open(out, "w") as f:
        json.dump(
            {"tag_name": version, "name": version, "body": "", "assets": assets},
            f, indent=2,
        )
    print(f"wrote {out} with {len(assets)} assets")


if __name__ == "__main__":
    main()
