#!/bin/sh
# Osmium Sound — make the third-party Lyrion "CD Player" plugin tolerate flaky
# USB optical drives, on every boot.
#
# The CD Player plugin polls the drive status (CDhandler.pm::cdromstatus) with a
# rigid sequence that many modern USB CD readers do not answer the way it
# expects, so playback stalls with "No CD in drive" even with a disc loaded and
# the device readable (the cdrom-group permission half is already handled by
# hifi-firstboot.sh + 99-hifi-cdrom.rules). We relax that check so the plugin
# trusts the disc is there and lets squeezelite read it.
#
# 🚨 Same pattern/constraints as hifi-lyrion-plugins-ensure.sh: the RAUC image
# root is read-only and replaced whole on every OTA, while the plugin lives on
# the writable /var tree and can be (re)installed or updated by the user through
# the LMS extension manager. So this is NOT a first-boot job — it re-asserts the
# patch idempotently on every boot, before lyrionmusicserver scans its plugins.
#
# The plugin is NOT bundled by us: it is user-installed, landing under
# cache/InstalledPlugins/Plugins/<Name> (the extension installer owns that tree).
# We never create it — if the plugin is absent we do nothing.
set -u

CACHE_DIR="${HIFI_LMS_CACHE:-/var/lib/squeezeboxserver/cache}"
INSTALLED_DIR="${HIFI_LMS_INSTALLED:-$CACHE_DIR/InstalledPlugins/Plugins}"
LYRION_CURRENT="${HIFI_LYRION_CURRENT:-/data/lyrion/current}"
OWNER="${HIFI_LMS_USER:-squeezeboxserver}"
CMDLINE="${HIFI_CMDLINE:-/proc/cmdline}"
CONFIG_DIR="${HIFI_CONFIG_DIR:-/etc/hifi-player}"
MARKER="# osmium: tolerate flaky USB drive status"

[ -f "${HIFI_IMAGE_VERSION_FILE:-/usr/lib/osmium/IMAGE_VERSION}" ] || exit 0
grep -qw 'boot=live' "$CMDLINE" 2>/dev/null && exit 0
[ -e "$CONFIG_DIR/provisioning-pending" ] && exit 0

# No local server → the plugin (if any) belongs to whichever server the player
# follows, not here.
[ -x "$LYRION_CURRENT/usr/sbin/squeezeboxserver" ] || exit 0
[ -d "$INSTALLED_DIR" ] || exit 0

# Find the plugin by its handler file rather than assuming the folder name: the
# user-visible "CD Player" plugin may unpack under CDplayer, CdPlayer, etc.
patched_any=0
for handler in "$INSTALLED_DIR"/*/CDhandler.pm; do
    [ -f "$handler" ] || continue
    if grep -qF "$MARKER" "$handler"; then
        continue    # already tolerant
    fi
    # Insert an early "disc present, readable" return at the top of cdromstatus,
    # just after its opening brace. Idempotent via the marker above. Note: the
    # sub-name boundary is "followed by a non-word char or end of line", not
    # \b — \b is a word boundary in grep but undefined in awk.
    if grep -qE '^[[:space:]]*sub[[:space:]]+cdromstatus([^[:alnum:]_]|$)' "$handler"; then
        tmp="$handler.osmium.tmp"
        awk -v marker="$MARKER" '
            { print }
            !done && /^[[:space:]]*sub[[:space:]]+cdromstatus([^[:alnum:]_]|$)/ { in_sub = 1 }
            in_sub && !done && /\{/ {
                print "    return (1, 100, \"OK\"); " marker
                in_sub = 0; done = 1
            }
        ' "$handler" > "$tmp" 2>/dev/null \
            && grep -qF "$MARKER" "$tmp" \
            && mv "$tmp" "$handler" \
            && chown "$OWNER" "$handler" 2>/dev/null \
            && { echo "[hifi-cdplayer-tolerate] patched $handler"; patched_any=1; } \
            || rm -f "$tmp"
    fi
done

[ "$patched_any" -eq 1 ] || exit 0
exit 0
