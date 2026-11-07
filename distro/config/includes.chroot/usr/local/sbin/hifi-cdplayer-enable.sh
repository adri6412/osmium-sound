#!/bin/sh
# Osmium Sound — install & enable the third-party Lyrion "CD Player" plugin
# (CDplayer) out of the box, so a freshly imaged device can play audio CDs
# without the user ever opening the plugin settings.
#
# 🚨 We do NOT bundle the plugin (product decision: "activate it through the LMS
# API and let the server install it"). It is pulled from the standard LMS plugin
# repository by the server itself. This script just drives the same web-settings
# action a user would (install:CDplayer), waits for the download, then restarts
# the server so it extracts & enables the plugin — exactly what the extension
# manager does. The plugin lands in cache/InstalledPlugins/Plugins/CDplayer,
# which the extension installer owns (it came from a real repo, so it is not
# pruned — unlike a bundled plugin, which is why the bundled ones live elsewhere;
# see hifi-lyrion-plugins-ensure.sh).
#
# One-shot, marker-guarded: once CDplayer is installed we record a marker and
# never act again, so a user who later removes it on a device that is theirs is
# not overridden. Until the install succeeds (no network / repo unreachable at
# first boot) it retries on the next boot. Unlike hifi-cdplayer-tolerate.sh and
# hifi-lyrion-plugins-ensure.sh this runs AFTER lyrionmusicserver is up (it has
# to POST to its web UI), not before.
set -u

CACHE_DIR="${HIFI_LMS_CACHE:-/var/lib/squeezeboxserver/cache}"
INSTALLED_DIR="${HIFI_LMS_INSTALLED:-$CACHE_DIR/InstalledPlugins/Plugins}"
DOWNLOAD_DIR="${HIFI_LMS_DOWNLOADS:-$CACHE_DIR/DownloadedPlugins}"
LYRION_CURRENT="${HIFI_LYRION_CURRENT:-/data/lyrion/current}"
CMDLINE="${HIFI_CMDLINE:-/proc/cmdline}"
CONFIG_DIR="${HIFI_CONFIG_DIR:-/etc/hifi-player}"
LMS_URL="${HIFI_LMS_URL:-http://127.0.0.1:9000}"
TOLERATE="${HIFI_CDPLAYER_TOLERATE:-/usr/local/sbin/hifi-cdplayer-tolerate.sh}"
MARKER="$CONFIG_DIR/cdplayer-installed"
PLUGIN="CDplayer"

log() { echo "[hifi-cdplayer-enable] $*"; }

[ -f "${HIFI_IMAGE_VERSION_FILE:-/usr/lib/osmium/IMAGE_VERSION}" ] || exit 0
grep -qw 'boot=live' "$CMDLINE" 2>/dev/null && exit 0
[ -e "$CONFIG_DIR/provisioning-pending" ] && exit 0

# No local server → the plugin belongs on whichever server the player follows.
[ -x "$LYRION_CURRENT/usr/sbin/squeezeboxserver" ] || exit 0

# Already done, or the user (or a previous run) already has it installed → record
# the marker and stop. Respects a later deliberate removal (marker stays).
[ -e "$MARKER" ] && exit 0
if [ -f "$INSTALLED_DIR/$PLUGIN/install.xml" ]; then
    mkdir -p "$CONFIG_DIR" 2>/dev/null && : > "$MARKER" 2>/dev/null
    exit 0
fi

# Wait for the server's web UI to answer (it is what installs the plugin).
up=0
i=0
while [ "$i" -lt 60 ]; do
    if curl -fsS -m 3 -o /dev/null "$LMS_URL/" 2>/dev/null; then up=1; break; fi
    i=$((i + 1))
    sleep 2
done
[ "$up" -eq 1 ] || { log "LMS not reachable yet; will retry next boot"; exit 0; }

# The plugins settings page carries the anti-CSRF token (hidden field "rand",
# fixed per server process) and only offers CDplayer once the repo scan has seen
# it — i.e. once the network and the default plugin repo are reachable.
page=$(curl -fsS -m 20 "$LMS_URL/settings/server/plugins.html" 2>/dev/null)
rand=$(printf '%s' "$page" | grep -oE 'name="rand" type="hidden" value="[a-f0-9]{32}"' | grep -oE '[a-f0-9]{32}' | head -n 1)
if [ -z "$rand" ] || ! printf '%s' "$page" | grep -q 'install:'"$PLUGIN"; then
    log "plugin repo not ready (no rand / $PLUGIN not offered); will retry next boot"
    exit 0
fi

# Drive the install the way the settings form does: the hidden field marks the
# plugin as installable and the checkbox value turns it on. Both are required —
# the handler reads $params->{CDplayer}, not $params->{"install:CDplayer"}.
curl -fsS -m 60 -o /dev/null "$LMS_URL/settings/server/plugins.html" \
    --data "rand=$rand&saveSettings=1&install:$PLUGIN=&$PLUGIN=$PLUGIN" 2>/dev/null \
    || { log "install POST failed; will retry next boot"; exit 0; }

# The download is near-instant; wait for the zip to appear in DownloadedPlugins.
got=0
i=0
while [ "$i" -lt 30 ]; do
    if ls "$DOWNLOAD_DIR"/*[Cc][Dd][Pp]layer*.zip >/dev/null 2>&1; then got=1; break; fi
    i=$((i + 1))
    sleep 1
done
[ "$got" -eq 1 ] || { log "download did not appear; will retry next boot"; exit 0; }

# Restart the server so it extracts the plugin, then wait until it reports the
# plugin enabled (state.prefs). A single clean restart does both extract and
# enable; poll and, if it is still mid-extract, give it one more restart.
restart_lms() {
    systemctl restart lyrionmusicserver.service 2>/dev/null || return 1
    j=0
    while [ "$j" -lt 60 ]; do
        curl -fsS -m 3 -o /dev/null "$LMS_URL/" 2>/dev/null && return 0
        j=$((j + 1))
        sleep 2
    done
    return 0
}

enabled=0
attempt=0
while [ "$attempt" -lt 2 ]; do
    restart_lms
    # Give the plugin manager a moment to extract/load, then check state.
    k=0
    while [ "$k" -lt 30 ]; do
        if [ -f "$INSTALLED_DIR/$PLUGIN/install.xml" ] \
           && grep -qiE "^$PLUGIN:[[:space:]]*enabled" \
                "$(dirname "$CACHE_DIR")/prefs/plugin/state.prefs" 2>/dev/null; then
            enabled=1
            break
        fi
        k=$((k + 1))
        sleep 2
    done
    [ "$enabled" -eq 1 ] && break
    attempt=$((attempt + 1))
done

if [ "$enabled" -ne 1 ]; then
    log "plugin downloaded but not enabled yet; will retry next boot"
    exit 0
fi

# Make the freshly installed plugin tolerate flaky USB drives right away, instead
# of waiting for the next boot's hifi-cdplayer-tolerate run. Idempotent.
[ -x "$TOLERATE" ] && "$TOLERATE" >/dev/null 2>&1 || true

mkdir -p "$CONFIG_DIR" 2>/dev/null && : > "$MARKER" 2>/dev/null
log "$PLUGIN installed and enabled"
exit 0
