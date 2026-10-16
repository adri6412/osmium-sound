#!/bin/sh
# Osmium Sound — what a live session ("Try" or "Install" from the ISO) needs
# before the services start, now that the live system IS the slot image.
#
# The single-filesystem ISO boots the very squashfs that the installer copies
# into slot A, and build-image.sh shapes that squashfs for a disk with a data
# partition: it drops the first-boot marker from /etc (the installer seeds it
# on /data instead) and points Lyrion at /data/lyrion/current. On a disk the
# initramfs (local-bottom/hifi-state) mounts that partition; in a live session
# nothing does, so:
#   - without /etc/hifi-player/provisioning-pending the web admin never serves
#     the setup (or install) portal and the kiosk shows no wizard;
#   - /data is a bare folder of the image, so everything that asks "is the data
#     partition mounted?" says no: the wizard's Lyrion install refuses with
#     "/data non montata", the music folder is never made, the disk reported
#     is the read-only squashfs.
# Here both are put back the way a fresh install has them: /data as a tmpfs
# (the same fallback hifi-state takes when the partition is missing) and the
# marker in /etc. Both live in memory and vanish at shutdown, like everything
# else a live session writes.
#
# A no-op without boot=live on the kernel command line: an installed system
# must never get the marker back (that would drop a configured device into
# setup mode).
set -u
CMDLINE="${HIFI_CMDLINE:-/proc/cmdline}"
CONFIG_DIR="${HIFI_CONFIG_DIR:-/etc/hifi-player}"
DATA="${HIFI_DATA:-/data}"
MOUNTPOINT="${HIFI_MOUNTPOINT:-mountpoint}"
MOUNT="${HIFI_MOUNT:-mount}"
log() { echo "hifi-live-state: $*"; }

read -r cmdline < "$CMDLINE" 2>/dev/null || cmdline=
case " $cmdline " in *" boot=live "*) ;; *) exit 0 ;; esac

mkdir -p "$DATA"
if ! "$MOUNTPOINT" -q "$DATA"; then
    if "$MOUNT" -t tmpfs -o mode=0755 tmpfs "$DATA"; then
        log "$DATA in memory for this live session"
    else
        log "could not mount a tmpfs on $DATA"
    fi
fi

# An account already made means setup was finished (a live medium with
# persistence): the wizard must not come back.
if [ ! -e "$CONFIG_DIR/provisioning-pending" ] && [ ! -e "$CONFIG_DIR/webui.db" ]; then
    mkdir -p "$CONFIG_DIR"
    printf 'pending\n' > "$CONFIG_DIR/provisioning-pending"
    log "first-boot wizard armed"
fi
exit 0
