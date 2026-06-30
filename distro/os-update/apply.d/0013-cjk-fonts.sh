# shellcheck shell=sh
# 0013 — CJK (Japanese / Chinese / Korean) fonts for the kiosk UI.
#
# The base image shipped no CJK font, so album/track names in Japanese (and
# Chinese/Korean) rendered as tofu boxes (□□□) in the player. Install Noto CJK
# so Chromium/Electron has the glyphs. Baked into new images via the package
# list; this migration carries it to already-installed devices.
#
# Idempotent: ensure_pkg is a no-op once the package is present. Non-fatal: if
# apt can't run right now (no network / stale index) we just leave it for a
# later update instead of failing the whole OS update over a font. Reboots ONCE
# — only when the font was actually added — so the running Electron picks it up.

if dpkg -s fonts-noto-cjk >/dev/null 2>&1; then
    exit 0                                   # already installed → nothing to do
fi

# Best-effort index refresh so apt can resolve the package on a device whose
# cache is stale (ignore failures; ensure_pkg will retry on a future update).
if [ "${HIFI_OS_NO_APT:-0}" != 1 ]; then
    DEBIAN_FRONTEND=noninteractive apt-get update >/dev/null 2>&1 || true
fi

if ensure_pkg fonts-noto-cjk; then
    # Refresh the fontconfig cache and reboot once so the kiosk session reloads
    # with the new font available (Chromium reads fonts at startup).
    fc-cache -f >/dev/null 2>&1 || true
    request_reboot "installed CJK fonts"
fi
