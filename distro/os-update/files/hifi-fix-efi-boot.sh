#!/bin/sh
# HiFi Player / Osmium Sound — UEFI boot-entry cleanup.
#
# Deployed to two places (both harmless, kept for defence in depth):
#   • /etc/kernel/postinst.d/zzz-hifi-fix-efi-boot — runs inside the KERNEL
#     package's own postinst. Limited: in a combined kernel+grub apt
#     transaction this runs BEFORE grub-efi-amd64-signed/shim-signed are
#     configured, so it can't see an entry THEY create — but it still cleans
#     up stale/duplicate entries on a kernel-only update.
#   • /usr/local/sbin/hifi-fix-efi-boot.sh, invoked by
#     /etc/apt/apt.conf.d/99-hifi-fix-efi-boot's DPkg::Post-Invoke — runs
#     after the ENTIRE apt/dpkg transaction (every package configured, every
#     trigger processed), so it reliably runs after grub-efi-amd64-signed/
#     shim-signed too. This is the one that actually catches the bug below.
#
# Bug this fixes: this fleet's images set GRUB_DISTRIBUTOR="Osmium Sound" in
# /etc/default/grub (branding). grub-efi-amd64-signed/shim-signed's postinst
# derives grub-install's --bootloader-id FROM GRUB_DISTRIBUTOR, so a device
# whose original install predates that branding (bootloader-id "debian" at
# install time) gets a BRAND NEW, DIVERGENT \EFI\osmium\ directory + UEFI
# NVRAM entry the next time grub-efi-amd64-signed/shim-signed is reinstalled
# — without removing the old \EFI\debian\ one. The firmware's BootOrder then
# accumulates entries across every such event (some pointing at long-stale
# ESP partition GUIDs from a past reinstall/repartition too) and can end up
# trying a broken one first, dropping to a bare `grub>` rescue prompt.
#
# Fix: collapse the NVRAM down to exactly ONE entry — named "osmium",
# pointing at whichever grubx64.efi was written MOST RECENTLY (grub-install
# always rewrites its target directory fresh, so the newest copy is
# definitionally the one meant to be booted next) — and make it the only
# entry in BootOrder.
#
# Safety: the NEW entry is created and VERIFIED present BEFORE any existing
# entry is touched, so a failure partway through can never leave zero boot
# entries. Only NVRAM is touched — files already on the ESP are never
# modified or deleted. Any unexpected condition (no efibootmgr, BIOS boot
# instead of UEFI, ESP not mounted, no grubx64.efi found, the new entry
# didn't parse back out of efibootmgr's output) is a silent no-op — this
# script must never be the reason an apt/dpkg run or kernel update fails.
#
# Cheap on every apt run, NVRAM-write only when something actually changed:
# via the apt hook this runs on EVERY dpkg transaction, not just kernel/grub
# ones (Post-Invoke has no way to know which packages were involved). The
# scan below (find over a couple of small directories) is negligible, but
# efibootmgr writes are real NVRAM writes with finite endurance on some
# firmwares — so the create/verify/delete/reorder dance only runs when the
# newest grubx64.efi (path+mtime) differs from the last time we acted,
# recorded in STATE. A plain `apt install curl` is a no-op past this point.
set -e

command -v efibootmgr >/dev/null 2>&1 || exit 0
[ -d /sys/firmware/efi ] || exit 0

ESP=/boot/efi
mountpoint -q "$ESP" 2>/dev/null || exit 0

LOADER_REL=$(cd "$ESP" 2>/dev/null \
    && find EFI -maxdepth 2 -iname 'grubx64.efi' -printf '%T@ %p\n' 2>/dev/null \
    | sort -rn | head -n1 | cut -d' ' -f2-)
[ -n "$LOADER_REL" ] && [ -f "$ESP/$LOADER_REL" ] || exit 0
LOADER_ARG=$(printf '/%s' "$LOADER_REL" | tr '/' '\\')

STATE=/var/lib/hifi-player/efi-boot-fix.state
LOADER_MTIME=$(stat -c %Y "$ESP/$LOADER_REL" 2>/dev/null) || exit 0
FINGERPRINT="$LOADER_REL@$LOADER_MTIME"
if [ -f "$STATE" ] && [ "$(cat "$STATE" 2>/dev/null)" = "$FINGERPRINT" ]; then
    exit 0
fi

# -t vfat: on devices where /boot/efi is set up with x-systemd.automount
# (common — seen in the field), `findmnt -o SOURCE /boot/efi` returns TWO
# lines (the "systemd-1" autofs trigger AND the real block device stacked at
# the same mountpoint). Filtering by the ESP's known filesystem type (always
# vfat/FAT32 on this fleet's own partition layout) skips the autofs entry and
# leaves exactly the real device.
ESP_DEV=$(findmnt -n -o SOURCE -t vfat "$ESP" 2>/dev/null | head -n1) || exit 0
[ -n "$ESP_DEV" ] || exit 0
ESP_PART=$(cat "/sys/class/block/$(basename "$ESP_DEV")/partition" 2>/dev/null) || exit 0
DISK_DEV=$(lsblk -no PKNAME "$ESP_DEV" 2>/dev/null) || exit 0
[ -n "$DISK_DEV" ] && [ -n "$ESP_PART" ] || exit 0

# 1) Create the new entry first — nothing existing is touched yet.
NEW_OUT=$(efibootmgr -c -d "/dev/$DISK_DEV" -p "$ESP_PART" -L osmium -l "$LOADER_ARG" 2>/dev/null) || exit 0
NEW_NUM=$(printf '%s\n' "$NEW_OUT" | sed -n 's/^Boot\([0-9A-Fa-f]\{4\}\)\*\{0,1\} osmium$/\1/p' | tail -n1)
[ -n "$NEW_NUM" ] || exit 0
echo "I: [hifi-efi-boot] created Boot$NEW_NUM osmium -> $LOADER_ARG"

# 2) Only now remove every OTHER entry (stale/duplicate entries from past
#    kernel/grub updates, or a previous run of this same script).
efibootmgr | sed -n 's/^Boot\([0-9A-Fa-f]\{4\}\)\*\{0,1\} .*/\1/p' | while read -r num; do
    [ "$num" = "$NEW_NUM" ] && continue
    efibootmgr -b "$num" -B >/dev/null 2>&1 || true
done

# 3) Boot the new entry (and only it) from now on.
efibootmgr -o "$NEW_NUM" >/dev/null 2>&1 || true
echo "I: [hifi-efi-boot] EFI boot NVRAM collapsed to Boot$NEW_NUM osmium"

mkdir -p "$(dirname "$STATE")" 2>/dev/null || true
printf '%s' "$FINGERPRINT" > "$STATE" 2>/dev/null || true

exit 0
