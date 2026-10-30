#!/bin/sh
# Osmium Sound — keep the bundled Lyrion plugins installed in the local
# server's writable, scanned plugin directory, on every boot.
#
# 🚨 Not a first-boot job: the RAUC image root is read-only and replaced whole
# on every OTA, while Lyrion lives on /data and its plugin/cache tree on
# /var/lib/squeezeboxserver. So a plugin cannot be "installed once" — it is
# re-asserted here each boot, idempotently, the same pattern as
# hifi-lyrion-ensure.sh: an OTA that ships a newer plugin updates it on the next
# boot, and a plugin tree wiped with /var is simply put back.
#
# Only the local server needs these: a device that follows another server has
# its Lyrion disabled, and the plugin belongs on whichever server the player
# follows (installed there by its own image/OTA, or by hand on a third party).
#
# Runs before lyrionmusicserver.service so the plugin is in place before the
# server scans. The plugin regenerates its own custom-convert.conf from its
# prefs at init, so replacing the code here never loses a player's settings.
set -u

SRC_DIR="${HIFI_LMS_PLUGINS_SRC:-/usr/local/share/osmium/lms-plugins}"
CACHE_DIR="${HIFI_LMS_CACHE:-/var/lib/squeezeboxserver/cache}"
DST_DIR="$CACHE_DIR/InstalledPlugins/Plugins"
LYRION_CURRENT="${HIFI_LYRION_CURRENT:-/data/lyrion/current}"
OWNER="${HIFI_LMS_USER:-squeezeboxserver}"
CMDLINE="${HIFI_CMDLINE:-/proc/cmdline}"
CONFIG_DIR="${HIFI_CONFIG_DIR:-/etc/hifi-player}"

[ -f "${HIFI_IMAGE_VERSION_FILE:-/usr/lib/osmium/IMAGE_VERSION}" ] || exit 0
grep -qw 'boot=live' "$CMDLINE" 2>/dev/null && exit 0
[ -e "$CONFIG_DIR/provisioning-pending" ] && exit 0

# No local server → nothing to install here.
[ -x "$LYRION_CURRENT/usr/sbin/squeezeboxserver" ] || exit 0
[ -d "$SRC_DIR" ] || exit 0

plugin_version() {  # <install.xml path> -> version string, or empty
    sed -n 's/.*<version>\([^<]*\)<.*/\1/p' "$1" 2>/dev/null | head -n 1
}

for src in "$SRC_DIR"/*/; do
    [ -d "$src" ] || continue
    name=$(basename "$src")
    [ -f "$src/install.xml" ] || continue
    dst="$DST_DIR/$name"

    want=$(plugin_version "$src/install.xml")
    have=$(plugin_version "$dst/install.xml")
    [ -d "$dst" ] && [ -n "$want" ] && [ "$want" = "$have" ] && continue

    mkdir -p "$DST_DIR" || continue
    rm -rf "$dst.tmp" 2>/dev/null
    if cp -a "$src" "$dst.tmp"; then
        [ -f "$dst.tmp/Bin/osmium-convert" ] && chmod 0755 "$dst.tmp/Bin/osmium-convert"
        rm -rf "$dst" 2>/dev/null
        mv "$dst.tmp" "$dst"
        chown -R "$OWNER" "$dst" 2>/dev/null || true
    else
        rm -rf "$dst.tmp" 2>/dev/null
    fi
done

exit 0
