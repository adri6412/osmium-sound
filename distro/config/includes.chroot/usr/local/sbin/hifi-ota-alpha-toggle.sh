#!/bin/sh
# HiFi Player appliance — show/hide the private "alpha" OTA channel.
#
# The alpha channel is NOT a privacy/security boundary (the repo and its
# releases are public) — it exists purely so the owner's own device(s) can
# opt into ad hoc test builds (tags vX.Y.Z-dev.N-alphaM, cut from the
# dedicated `alpha` git branch) without that option ever showing up, or being
# settable, on any other device. Presence of the marker file is all that
# matters; its content is never read.
#
# SECURITY: root-only, local operation ON PURPOSE — deliberately NOT exposed
# over the network API, and NOT granted to the kiosk user via sudoers. Run it
# from a console or over SSH as root.
#
# Usage:
#     hifi-ota-alpha-toggle.sh enable
#     hifi-ota-alpha-toggle.sh disable
#     hifi-ota-alpha-toggle.sh status
set -eu

DEST=/etc/hifi-player/ota-alpha-unlocked
CMD="${1:-}"

die() { echo "E: [alpha-toggle] $1" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "Deve essere eseguito come root."

case "$CMD" in
    enable)
        mkdir -p "$(dirname "$DEST")"
        install -m 644 -o root -g root /dev/null "$DEST"
        echo "OK: canale alpha sbloccato → $DEST"
        ;;
    disable)
        rm -f "$DEST"
        echo "OK: canale alpha nascosto (marker rimosso)"
        ;;
    status)
        if [ -f "$DEST" ]; then
            echo "alpha: sbloccato"
        else
            echo "alpha: nascosto"
        fi
        ;;
    *)
        die "Uso: hifi-ota-alpha-toggle.sh {enable|disable|status}"
        ;;
esac
