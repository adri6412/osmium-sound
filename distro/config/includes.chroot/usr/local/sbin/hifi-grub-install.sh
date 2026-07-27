#!/bin/sh
# hifi-grub-install.sh
#
# Run in-target (chrooted into /target, with /sys bind-mounted — confirmed by
# grub-installer's own "Success mounting /target/sys" log line) by
# hifi-finalize-install.sh via the preseed late_command, AFTER d-i's own
# grub-installer step has been disabled (d-i grub-installer/skip boolean
# true, see includes.installer/preseed.cfg).
#
# WHY THIS EXISTS: this appliance's live image ships BOTH bootloader families
# pre-installed — grub-pc (BIOS) and grub-efi-amd64-signed + shim-signed
# (UEFI Secure Boot) — so a fresh install works fully offline regardless of
# which firmware mode the target machine boots with. d-i's own
# grub-installer component assumes only ONE family is ever present and, as
# part of "switching to" the one it wants, tries to `dpkg --purge` the
# other. That purge fails here: shim-signed still depends on
# grub-efi-amd64-bin, and grub-efi-amd64-signed is a dpkg *protected*
# package that refuses removal outright — aborting the whole step, on
# EITHER firmware (confirmed on real hardware and in a BIOS-mode VM: both
# failed identically with "dpkg: error processing package
# grub-efi-amd64-signed (--purge): this is a protected package").
#
# THE FIX: skip grub-installer's broken purge-then-install logic entirely,
# and instead re-trigger the postinst of whichever ONE already-installed
# package family actually matches this machine's real firmware — that is
# each package's own authoritative, tested setup logic (copying the signed
# EFI binaries, registering the NVRAM boot entry, embedding BIOS boot code),
# not a hand-rolled reimplementation of it. The messages that failed were
# emitted by `grub-installer` itself (the d-i component), NOT by grub-pc's or
# grub-efi-amd64-signed's own postinst — neither individual package's
# postinst has any business touching the other's files, so going straight to
# `dpkg-reconfigure` on the one we actually want never touches the sibling
# family at all.
set -eu

log() { echo "I: [hifi-grub-install] $*"; }
die() { echo "E: [hifi-grub-install] $*" >&2; exit 1; }

if [ -d /sys/firmware/efi ]; then
    log "UEFI firmware detected — configuring the signed EFI GRUB chain"
    findmnt -n /boot/efi >/dev/null 2>&1 || die "/boot/efi is not mounted"
    # Also force the fallback removable-media path (\EFI\BOOT\BOOTX64.EFI), not
    # just the NVRAM "debian" boot entry — some firmwares ignore/lose NVRAM
    # entries. d-i's grub-installer used to do this via
    # grub-installer/force-efi-extra-removable; that d-i component is skipped
    # now, but the underlying grub2 debconf template is the same one its
    # postinst reads, so setting it here reproduces the same behavior. Inert
    # (ignored) if this package build never queries the key.
    debconf-set-selections <<EOF
grub2 grub2/force_efi_extra_removable boolean true
EOF
    export DEBIAN_FRONTEND=noninteractive
    dpkg-reconfigure grub-efi-amd64-signed
else
    log "BIOS/legacy firmware detected — configuring GRUB for the MBR"
    # Target disk: derive from the mounted root (grub-installer/bootdev is
    # unused now that grub-installer itself is skipped). Strips the trailing
    # partition suffix (sda3 -> sda, nvme0n1p3 -> nvme0n1, mmcblk0p1 ->
    # mmcblk0).
    ROOT_DEV=$(readlink -f "$(findmnt -n -o SOURCE /)") || die "cannot resolve root device"
    DISK=$(lsblk -no pkname "$ROOT_DEV" 2>/dev/null | head -n1)
    [ -n "$DISK" ] || die "cannot resolve parent disk for $ROOT_DEV"
    DISK="/dev/$DISK"
    log "target disk: $DISK (root: $ROOT_DEV)"
    # The live chroot's build-time preseed (config/preseed.cfg) intentionally
    # answered grub-pc/install_devices as empty, so its postinst wouldn't try
    # to grub-install against a fake disk while building the image — that
    # same (now stale) answer got cloned onto this target along with the rest
    # of the debconf database. Override it with the real disk before
    # reconfiguring, or grub-pc's postinst would see "no devices" and skip
    # the actual install.
    debconf-set-selections <<EOF
grub-pc grub-pc/install_devices multiselect $DISK
grub-pc grub-pc/install_devices_empty boolean false
EOF
    export DEBIAN_FRONTEND=noninteractive
    dpkg-reconfigure grub-pc
fi

log "done"
