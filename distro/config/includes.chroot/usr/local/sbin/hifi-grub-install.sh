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
# grub-efi-amd64-signed (--purge): this is a protected package"). Standard
# Debian's grub-installer normally distinguishes EFI vs BIOS just fine on its
# own — that logic isn't broken; it's the cross-family purge (an artifact of
# THIS image shipping both families side by side) that is.
#
# ATTEMPT 1 (superseded): skip grub-installer, dpkg-reconfigure the matching
# package. On BIOS this reported success but left the disk with NO bootloader
# at all — dpkg-reconfigure grub-pc's postinst apparently did not actually
# perform (or silently no-op'd) the MBR write on real hardware, and the
# caller swallowed the exit status anyway (see hifi-finalize-install.sh),
# so the installer reported success on an unbootable disk.
#
# THE FIX (this version): for BIOS, install GRUB directly with the same
# `grub-install` command a human would type by hand — the actual, certain,
# directly-verifiable primitive that grub-pc's own postinst wraps internally
# — instead of trusting the indirect dpkg-reconfigure path. Its exit status
# is checked and fatal on failure (see set -eu / die below); the caller no
# longer swallows this. dpkg-reconfigure grub-pc still runs afterward,
# best-effort, purely to keep its debconf/device-map bookkeeping consistent
# for future kernel-postinst-triggered updates — its failure is NOT fatal
# once the real MBR write has already succeeded.
#
# For UEFI, install the signed boot chain with a direct `grub-install`
# invocation — the same philosophy as the BIOS branch below (the actual,
# certain, directly-verifiable primitive, instead of trusting a package's
# postinst). Confirmed live on the test VM that neither package in the
# shim-signed/grub-efi-amd64-signed pair does this via dpkg-reconfigure:
# grub-efi-amd64-signed has NO postinst at all (dpkg -L: ships only the raw
# *.efi.signed blobs under /usr/lib/grub/x86_64-efi-signed/), and
# shim-signed's postinst only runs its SecureBoot/DKMS safety checks and
# stops — confirmed even with a full `apt-get install --reinstall` (not just
# dpkg-reconfigure), still nothing written. Plain `grub-install
# --target=x86_64-efi` DOES work — Debian's grub-install auto-detects and
# copies the pre-signed shim/grub images when shim-signed/grub-efi-amd64-
# signed are installed, no special flag needed — confirmed live: produced
# grubx64.efi/shimx64.efi/BOOTX64.CSV/etc. under /boot/efi/EFI/debian/ and
# exited 0 with "Installation finished. No error reported."
set -eu

log() { echo "I: [hifi-grub-install] $*"; }
die() { echo "E: [hifi-grub-install] $*" >&2; exit 1; }

if [ -d /sys/firmware/efi ]; then
    log "UEFI firmware detected — installing the signed EFI GRUB chain"
    findmnt -n /boot/efi >/dev/null 2>&1 || die "/boot/efi is not mounted"
    grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=debian --recheck \
        || die "grub-install (UEFI) failed"
    # Also install to the fallback removable-media path (\EFI\BOOT\BOOTX64.EFI),
    # not just the NVRAM "debian" boot entry — some firmwares ignore/lose NVRAM
    # entries. Best-effort: the primary install above is what matters, this is
    # belt-and-braces.
    grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=debian --recheck --removable \
        || log "WARNING: fallback removable-media GRUB install failed (non-fatal, primary install already succeeded)"
    if [ ! -e /boot/efi/EFI/debian/grubx64.efi ] && [ ! -e /boot/efi/EFI/debian/shimx64.efi ]; then
        die "grub-install completed but no boot files were found under /boot/efi/EFI/debian — UEFI boot chain was NOT installed"
    fi
    log "UEFI boot chain present under /boot/efi/EFI/debian"
else
    log "BIOS/legacy firmware detected — installing GRUB directly to the MBR"
    # Target disk: derive from the mounted root (grub-installer/bootdev is
    # unused now that grub-installer itself is skipped). Strips the trailing
    # partition suffix (sda3 -> sda, nvme0n1p3 -> nvme0n1, mmcblk0p1 ->
    # mmcblk0).
    ROOT_DEV=$(readlink -f "$(findmnt -n -o SOURCE /)") || die "cannot resolve root device"
    DISK=$(lsblk -no pkname "$ROOT_DEV" 2>/dev/null | head -n1)
    [ -n "$DISK" ] || die "cannot resolve parent disk for $ROOT_DEV"
    DISK="/dev/$DISK"
    log "target disk: $DISK (root: $ROOT_DEV)"

    # Keep grub-pc's own debconf record consistent (read by e.g. kernel
    # postinst hooks and future `apt upgrade`s) — the live chroot's build-time
    # preseed (config/preseed.cfg) intentionally answered install_devices as
    # empty (no real disk existed at build time), and that stale answer got
    # cloned onto this target along with the rest of the debconf database.
    debconf-set-selections <<EOF
grub-pc grub-pc/install_devices multiselect $DISK
grub-pc grub-pc/install_devices_empty boolean false
EOF

    # The actual, certain MBR write — the same command a human runs by hand.
    # Checked directly rather than trusting dpkg-reconfigure's indirect
    # postinst path (which reported success but wrote nothing on real BIOS
    # hardware — see ATTEMPT 1 above).
    grub-install --target=i386-pc --recheck "$DISK" \
        || die "grub-install --target=i386-pc $DISK failed — BIOS boot code was NOT written"
    log "grub-install (BIOS) succeeded for $DISK"

    # Best-effort only from here: the disk is already bootable at this point,
    # so a hiccup in the package's own bookkeeping must not be treated as a
    # bootloader failure.
    export DEBIAN_FRONTEND=noninteractive
    if ! dpkg-reconfigure grub-pc; then
        log "WARNING: dpkg-reconfigure grub-pc reported an error after the direct grub-install already succeeded — debconf/device-map bookkeeping may be stale, but the MBR boot code is installed"
    fi
fi

# Regenerate the real boot menu (kernel/initrd entries) at /boot/grub/grub.cfg.
# grub-install (UEFI) only writes a small stub in the ESP that chainloads
# this; grub-pc's own postinst (best-effort above) normally does it too on
# BIOS — but "the bootloader binary is in place" and "the system actually
# boots into a kernel" are two different claims, and only update-grub proves
# the second one. Explicit and fatal here, unlike everything after the direct
# grub-install call above, which is genuinely cosmetic/best-effort.
export DEBIAN_FRONTEND=noninteractive
update-grub || die "update-grub failed — /boot/grub/grub.cfg was NOT (re)generated"
[ -s /boot/grub/grub.cfg ] || die "update-grub completed but /boot/grub/grub.cfg is missing or empty"
log "grub.cfg regenerated"

log "done"
