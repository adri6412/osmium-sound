#!/bin/sh
# HiFi Player — OS update payload.
#
# This script is the heart of an OS OTA: it is packaged into
# hifi-os-<ver>.tar.gz, signed, and executed AS ROOT on the appliance by
# /usr/local/sbin/hifi-os-update.sh after the signature + checksum verify.
#
# Put here whatever change to the operating system this release needs:
# rewrite a config under /etc, add a udev/modprobe rule, install a file that
# ships alongside this script, migrate data, adjust GRUB, etc. Use apt-get only
# if you truly must — the whole point of this channel is scripted, deterministic
# changes that don't depend on a package being in the archive.
#
# Environment provided by the updater:
#   HIFI_OS_VERSION   the version string being applied (e.g. v1.4.0)
#   HIFI_PAYLOAD_DIR  absolute path to this extracted bundle, so you can copy in
#                     files you shipped next to apply.sh:
#                         install -m644 "$HIFI_PAYLOAD_DIR/files/foo.conf" /etc/foo.conf
#
# Contract:
#   • Be idempotent — it may re-run after a failed/aborted update.
#   • Exit non-zero on failure; the updater records the error and stops.
#   • If the change needs a reboot to take effect, leave a REBOOT marker:
#         : > "$HIFI_PAYLOAD_DIR/REBOOT"
#     and the updater will reboot cleanly once apply.sh succeeds.
set -eu

echo "Applying HiFi OS update ${HIFI_OS_VERSION:-?}"

# ── Fix: white screen after long uptime ──────────────────────────────
# The kiosk session used to `exec` Electron once. If the Chromium renderer/GPU
# process died after long uptime, the main process stayed alive showing a blank
# (white) window and nothing relaunched it. The UI bundle now reloads a crashed
# renderer itself; this OS update adds the second layer of defence by relaunching
# the whole app if it ever exits or is killed outright, instead of leaving the
# screen dead. Rewrites /home/hifi/.xsession in place (idempotent).

HIFI_HOME=/home/hifi
XSESSION="$HIFI_HOME/.xsession"

if [ -d "$HIFI_HOME" ]; then
    echo "Installing self-healing kiosk session at $XSESSION"
    cat > "$XSESSION" <<'XSESSION_EOF'
#!/bin/sh
# Disable screen blanking / power management
xset s off
xset -dpms
xset s noblank

# Hide the mouse cursor when idle
unclutter -idle 1 -root &

# Make sure audio is unmuted
amixer -q sset Master unmute 2>/dev/null || true
amixer -q sset PCM unmute 2>/dev/null || true

# Resolve the Electron binary (electron-builder symlinks it into /usr/bin)
APP="$(command -v hifi-media-player || true)"
[ -z "$APP" ] && APP="/opt/hifi-media-player/hifi-media-player"

# Launch the player in kiosk/fullscreen mode on X11. Wrapped in a restart loop:
# if the app ever exits or is killed (full crash after long uptime), relaunch it
# instead of dropping to a dead/blank screen. A short sleep avoids a hot loop if
# it fails to start at all.
while true; do
    "$APP" \
        --no-sandbox \
        --disable-dev-shm-usage \
        --enable-features=UseOzonePlatform \
        --ozone-platform=x11 \
        --start-fullscreen
    echo "hifi kiosk exited ($?) — relaunching in 3s" >&2
    sleep 3
done
XSESSION_EOF
    chmod +x "$XSESSION"
    chown hifi:hifi "$XSESSION" 2>/dev/null || true

    # The new session takes effect on the next login, so reboot to apply cleanly.
    : > "$HIFI_PAYLOAD_DIR/REBOOT"
else
    echo "W: $HIFI_HOME not present — skipping kiosk session update" >&2
fi

echo "OS update ${HIFI_OS_VERSION:-?} applied."
