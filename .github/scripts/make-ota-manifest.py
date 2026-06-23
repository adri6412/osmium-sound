#!/usr/bin/env python3
"""Generate the static OTA release manifest published to GitHub Pages.

Usage:
    make-ota-manifest.py <version> <repo> <channel> <ui_tar> <sys_tar> <os_tar>

Writes ``manifest-out/latest-<channel>.json`` mirroring the shape of a GitHub
release object (``tag_name`` + ``assets[]`` with ``browser_download_url``), so
the appliance's update check can read it from Pages (a CDN, not rate-limited)
instead of the GitHub REST API. Asset download URLs are the deterministic
release-CDN URLs for this tag.
"""
import json
import os
import sys


def main():
    version, repo, channel, uitar, systar, ostar = sys.argv[1:7]
    base = f"https://github.com/{repo}/releases/download/{version}"
    names = [
        uitar, uitar + ".sha256",
        systar, systar + ".sha256",
        ostar, ostar + ".sha256", ostar + ".sha256.sig",
    ]
    assets = []
    for n in names:
        try:
            size = os.path.getsize(n)
        except OSError:
            size = 0
        assets.append({
            "name": n,
            "browser_download_url": f"{base}/{n}",
            "size": size,
        })
    os.makedirs("manifest-out", exist_ok=True)
    out = f"manifest-out/latest-{channel}.json"
    with open(out, "w") as f:
        json.dump(
            {"tag_name": version, "name": version, "body": "", "assets": assets},
            f, indent=2,
        )
    print(f"wrote {out} with {len(assets)} assets")


if __name__ == "__main__":
    main()
