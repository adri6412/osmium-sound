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

# ── example: nothing to do (template) ────────────────────────────────
# Replace the body below with the real changes for this release.

# Example — drop a sysctl tweak and reload it (idempotent):
#   install -m644 "$HIFI_PAYLOAD_DIR/files/99-hifi.conf" /etc/sysctl.d/99-hifi.conf
#   sysctl --system

# Example — request a reboot when the change needs one:
#   : > "$HIFI_PAYLOAD_DIR/REBOOT"

echo "OS update ${HIFI_OS_VERSION:-?} applied."
