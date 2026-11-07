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
PREFS_DIR="${HIFI_LMS_PREFS:-/var/lib/squeezeboxserver/prefs}"
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

# True pause instead of stop-and-replay. The plugin's "pausestop" pref turns a
# pause request into a STOP and, on resume, reopens the stream from scratch. On
# our single cheap USB drive that reopen is a fresh capture racing the one still
# holding the drive, so resume fails ("cannot open file") and playback skips —
# the same contention osmium-cdread's lock guards against, here provoked by the
# plugin itself. With osmium-cdread the live stream can simply be held instead:
# squeezelite buffer-pauses it in place (the reader blocks on its full RAM ring)
# and resumes from the exact position. So force pausestop off. The pref file
# only exists once the plugin is installed; its name is the plugin's package
# ("cdplayer"), independent of the unpack folder. Idempotent, and LMS reads prefs
# at start while this runs Before=lyrionmusicserver, so it never races a write.
CDPREFS="$PREFS_DIR/plugin/cdplayer.prefs"
if [ -f "$CDPREFS" ] && ! grep -qx 'pausestop: 0' "$CDPREFS"; then
    tmp="$CDPREFS.osmium.tmp"
    awk '
        /^pausestop:/ { print "pausestop: 0"; seen = 1; next }
        { print }
        END { if (!seen) print "pausestop: 0" }
    ' "$CDPREFS" > "$tmp" 2>/dev/null \
        && grep -qx 'pausestop: 0' "$tmp" \
        && mv "$tmp" "$CDPREFS" \
        && chown "$OWNER" "$CDPREFS" 2>/dev/null \
        && { echo "[hifi-cdplayer-tolerate] forced pausestop off in $CDPREFS"; patched_any=1; } \
        || rm -f "$tmp"
fi

# ESP-style CD playback: the plugin streams audio CDs in real time with cdda2wav
# (icedax) at a fixed speed and NO error handling (see its custom-convert.conf).
# When a USB optical drive stalls mid-track, icedax drops the samples it cannot
# read in time — audible as a crackle ("prr"), like missing samples — while a
# re-reading tool (cdparanoia) would instead stop and buffer. osmium-cdread does
# neither: it reads ahead into a RAM cushion and conceals unrecoverable sectors
# without ever pausing, like a real CD player. So swap the reader
# (cdda2wav -> osmium-cdread) in every rule, keeping each pipeline's encoder tail
# (| flac, | lame, or raw) and the $CDDEVICE$/$CDTRACK$/$CDOFFSET$ tokens LMS
# fills in. $CDOFFSET$ (which the plugin expands to "-offset <sectors>" on a seek,
# empty otherwise) must be kept or seeking breaks. We drop only $CDSPEED$ (the
# reader fixes a cooperative 4x). --raw for the raw (pcm) rule, WAV otherwise.
# Idempotent via the marker, same constraints as the patch above.
CDREAD="$(command -v osmium-cdread 2>/dev/null || true)"
CONVERT_MARKER="# osmium: ESP CD reader"
if [ -n "$CDREAD" ]; then
    for conf in "$INSTALLED_DIR"/*/custom-convert.conf; do
        [ -f "$conf" ] || continue
        grep -qF "$CONVERT_MARKER" "$conf" && continue     # already converted
        grep -q '\[cdda2wav\]' "$conf" || continue         # nothing to convert
        tmp="$conf.osmium.tmp"
        # For each rule's reader line, emit an osmium-cdread equivalent: --raw for
        # the raw (pcm) rule, WAV otherwise; preserve any "| ..." encoder tail.
        awk -v cr="$CDREAD" -v marker="$CONVERT_MARKER" '
            BEGIN { print marker }
            /^[[:space:]]*\[cdda2wav\]/ {
                raw = ($0 ~ /--output-format[[:space:]]+raw/) ? " --raw" : ""
                tail = ""
                i = index($0, "|")
                if (i > 0) tail = " " substr($0, i)
                printf "\t%s --device $CDDEVICE$ --track $CDTRACK$ $CDOFFSET$%s%s\n", cr, raw, tail
                next
            }
            { print }
        ' "$conf" > "$tmp" 2>/dev/null \
            && grep -qF "$CONVERT_MARKER" "$tmp" \
            && grep -qF "$CDREAD" "$tmp" \
            && mv "$tmp" "$conf" \
            && chown "$OWNER" "$conf" 2>/dev/null \
            && { echo "[hifi-cdplayer-tolerate] converted $conf to osmium-cdread"; patched_any=1; } \
            || rm -f "$tmp"
    done
fi

[ "$patched_any" -eq 1 ] || exit 0
exit 0
