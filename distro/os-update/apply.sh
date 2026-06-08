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
#   • CUMULATIVE — this is the most important rule. The updater only ever fetches
#     and runs the LATEST release's apply.sh (check_os_update → releases/latest);
#     there is NO sequential replay of intermediate versions. So a device that
#     jumps from an old version straight to the newest runs ONLY this script. It
#     must therefore contain EVERY OS change ever shipped, as stacked idempotent
#     blocks. NEVER write a "delta-only" apply.sh and NEVER delete an old block —
#     doing so silently breaks any device that skipped versions. To add a change,
#     APPEND a new idempotent block; leave the existing ones in place forever.
#   • Idempotent — every block must be a clean no-op when already applied (it may
#     also re-run after a failed/aborted update).
#   • Exit non-zero on failure; the updater records the error and stops.
#   • If the change needs a reboot to take effect, leave a REBOOT marker:
#         : > "$HIFI_PAYLOAD_DIR/REBOOT"
#     and the updater will reboot cleanly once apply.sh succeeds. Only set it on a
#     REAL change — the version is the release tag, so this runs on every release;
#     a reboot when nothing changed would reboot the box on every single update.
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

# The desired self-healing kiosk session.
NEW_XSESSION='#!/bin/sh
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
done'

if [ ! -d "$HIFI_HOME" ]; then
    echo "W: $HIFI_HOME not present — skipping kiosk session update" >&2
elif [ -f "$XSESSION" ] && [ "$(cat "$XSESSION")" = "$NEW_XSESSION" ]; then
    # Already up to date. Crucially, do NOT request a reboot: this OS payload is
    # re-applied on every release (the version is the release tag), so it must be
    # a clean no-op when nothing changed — otherwise every update would reboot.
    echo "Kiosk session already current — nothing to do."
else
    echo "Installing self-healing kiosk session at $XSESSION"
    printf '%s\n' "$NEW_XSESSION" > "$XSESSION"
    chmod +x "$XSESSION"
    chown hifi:hifi "$XSESSION" 2>/dev/null || true
    # The new session only takes effect on the next login, so reboot to apply it.
    : > "$HIFI_PAYLOAD_DIR/REBOOT"
fi

# ── Security hardening (idempotent, no reboot) ────────────────────────
# These changes are baked into new ISOs at build time; this block carries the
# same hardening to devices that were already installed. Every step is a clean
# no-op once applied, and NONE of them request a reboot — they take effect live.

# 1) Drop the kiosk user from the 'sudo' group. The appliance only needs the
#    specific NOPASSWD commands in /etc/sudoers.d/hifi; full 'sudo' membership
#    would turn the well-known default password into trivial full-root.
if id -nG hifi 2>/dev/null | tr ' ' '\n' | grep -qx sudo; then
    gpasswd -d hifi sudo >/dev/null 2>&1 || deluser hifi sudo >/dev/null 2>&1 || true
    echo "Hardening: removed 'hifi' from sudo group"
fi

# 2) Pin the apt sudoers rule: `apt-get upgrade *` allows `-o DPkg::Pre-Invoke=…`
#    (arbitrary root command execution). Replace the wildcard with the exact
#    invocation the API actually uses. Edit on a backup and revert if visudo
#    rejects the result, so a bad edit can never lock sudo out.
SUDOERS=/etc/sudoers.d/hifi
if [ -f "$SUDOERS" ] && grep -q 'apt-get upgrade \*' "$SUDOERS"; then
    cp -a "$SUDOERS" "$SUDOERS.hifi-bak.$$"
    sed -i 's#/usr/bin/apt-get upgrade \*#/usr/bin/apt-get upgrade -y#' "$SUDOERS"
    if visudo -cf "$SUDOERS" >/dev/null 2>&1; then
        rm -f "$SUDOERS.hifi-bak.$$"
        echo "Hardening: pinned apt-get sudoers rule"
    else
        mv -f "$SUDOERS.hifi-bak.$$" "$SUDOERS"
        echo "W: sudoers edit reverted (validation failed)" >&2
    fi
fi

# 3) Enable automatic Debian security updates (security archive only, no auto
#    reboot — the box may be mid-playback).
UNATT=/etc/apt/apt.conf.d/52hifi-unattended
DESIRED_UNATT='// HiFi Player appliance — automatic security updates (security archive only,
// no automatic reboot). Managed by the OS-update channel.
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
Unattended-Upgrade::Origins-Pattern {
        "origin=Debian,codename=${distro_codename}-security,label=Debian-Security";
};
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";'
if [ ! -f "$UNATT" ] || [ "$(cat "$UNATT" 2>/dev/null)" != "$DESIRED_UNATT" ]; then
    printf '%s\n' "$DESIRED_UNATT" > "$UNATT"
    echo "Hardening: installed $UNATT"
fi
if ! dpkg -s unattended-upgrades >/dev/null 2>&1; then
    echo "Hardening: installing unattended-upgrades…"
    DEBIAN_FRONTEND=noninteractive apt-get install -y unattended-upgrades >/dev/null 2>&1 \
        || echo "W: could not install unattended-upgrades now (config is in place; retry later)" >&2
fi

# ── Audio fixes for already-installed devices ─────────────────────────
# These mirror what the UI/System update now does going forward, but apply to
# the existing /etc/default/squeezelite so users don't have to re-run anything.
SQ=/etc/default/squeezelite
if [ -f "$SQ" ] && grep -q '^ARGS=' "$SQ"; then
    # a) Enable bit-perfect DSD (DoP). Without -D squeezelite downconverts DSD to
    #    PCM. Insert it right after the -o device token if not already present.
    if ! grep '^ARGS=' "$SQ" | grep -q -- ' -D'; then
        sed -i "/^ARGS=/ s/\(-o[[:space:]]\{1,\}[^ ']\{1,\}\)/\1 -D/" "$SQ"
        echo "Audio: enabled DSD (-D) in $SQ"
        SQ_CHANGED=1
    fi
    # b) Migrate a number-based output device (-o hw:N,M) to the stable card name
    #    (-o hw:CARD=<name>,DEV=M). Card numbers reorder across reboots, which is
    #    why the selected DAC reverted to the onboard card; the name is stable.
    o=$(grep '^ARGS=' "$SQ" | sed -n "s/.*-o[[:space:]]\{1,\}\([^ ']\{1,\}\).*/\1/p")
    case "$o" in
        hw:[0-9]*,[0-9]*)
            cardnum=${o#hw:}; cardnum=${cardnum%%,*}
            devnum=${o##*,}
            name=$(aplay -l 2>/dev/null | sed -n "s/^card ${cardnum}: \([^ ]*\) .*/\1/p" | head -n1)
            if [ -n "$name" ]; then
                sed -i "/^ARGS=/ s#-o[[:space:]]\{1,\}${o}#-o hw:CARD=${name},DEV=${devnum}#" "$SQ"
                echo "Audio: migrated output device ${o} -> hw:CARD=${name},DEV=${devnum}"
                SQ_CHANGED=1
            fi
            ;;
    esac
    if [ "${SQ_CHANGED:-0}" = 1 ]; then
        systemctl restart squeezelite 2>/dev/null || true
    fi
fi

echo "OS update ${HIFI_OS_VERSION:-?} applied."
