#!/usr/bin/env python3
"""Generate the static OTA release manifest published to GitHub Pages.

Usage:
    make-ota-manifest.py <version> <repo> <channel> <ui_tar> <sys_tar> <os_tar> [changelog_file]

Writes ``manifest-out/latest-<channel>.json`` mirroring the shape of a GitHub
release object (``tag_name`` + ``assets[]`` with ``browser_download_url``), so
the appliance's update check can read it from Pages (a CDN, not rate-limited)
instead of the GitHub REST API. Asset download URLs are the deterministic
release-CDN URLs for this tag. ``body`` is the release's changelog text (see
the "Generate changelog" workflow step) — surfaced by the appliance's
_check_release_update() as `notes`, and shown in the "what's new" popup on
web-admin, kiosk, and the Android companion app.
"""
import json
import os
import sys


def main():
    version, repo, channel, uitar, systar, ostar = sys.argv[1:7]
    changelog_file = sys.argv[7] if len(sys.argv) > 7 else ""
    body = ""
    if changelog_file:
        try:
            with open(changelog_file, encoding="utf-8") as f:
                body = f.read()
        except OSError:
            pass
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
            {"tag_name": version, "name": version, "body": body, "assets": assets},
            f, indent=2,
        )
    print(f"wrote {out} with {len(assets)} assets")


if __name__ == "__main__":
    main()
