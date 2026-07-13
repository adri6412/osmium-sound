#!/bin/sh
# HiFi Player / Osmium Sound — kernel postinst.d hook.
#
# Installed as /etc/kernel/postinst.d/zzz-hifi-fix-efi-boot (the "zzz" prefix
# sorts it after Debian's own zz-update-grub, so it always runs AFTER grub.cfg
# has been regenerated for the new kernel).
#
# Bug this fixes: on this fleet, a kernel update sometimes causes grub-efi's
# postinst to add a NEW "debian" UEFI NVRAM boot entry without removing the
# old one. The firmware keeps booting the STALE entry first, which drops to a
# bare `grub>` rescue prompt; the NEW entry works fine but only if picked by
# hand from the BIOS boot menu. Fix: after every kernel update, collapse the
# NVRAM down to exactly ONE entry — named "osmium", pointing at whatever
# \EFI\<id>\grubx64.efi grub just (re)installed — and make it the only/first
# entry in BootOrder.
#
# Safety order: the NEW entry is created and VERIFIED present before any
# existing entry is touched, so a failure partway through can never leave the
# device with zero boot entries. Any unexpected condition (no efibootmgr, BIOS
# boot instead of UEFI, ESP not where expected, no grubx64.efi found, the new
# entry didn't parse back out of efibootmgr's output) is a silent no-op — this
# script must never be the reason a kernel update fails or a device won't
# boot.
set -e

command -v efibootmgr >/dev/null 2>&1 || exit 0
[ -d /sys/firmware/efi ] || exit 0

ESP=/boot/efi
mountpoint -q "$ESP" 2>/dev/null || exit 0

LOADER_REL=$(cd "$ESP" 2>/dev/null && find EFI -maxdepth 2 -iname 'grubx64.efi' 2>/dev/null | head -n1)
[ -n "$LOADER_REL" ] && [ -f "$ESP/$LOADER_REL" ] || exit 0
LOADER_ARG=$(printf '/%s' "$LOADER_REL" | tr '/' '\\')

ESP_DEV=$(findmnt -n -o SOURCE "$ESP" 2>/dev/null) || exit 0
ESP_PART=$(cat "/sys/class/block/$(basename "$ESP_DEV")/partition" 2>/dev/null) || exit 0
DISK_DEV=$(lsblk -no PKNAME "$ESP_DEV" 2>/dev/null) || exit 0
[ -n "$DISK_DEV" ] && [ -n "$ESP_PART" ] || exit 0

# 1) Create the new entry first — nothing existing is touched yet.
NEW_OUT=$(efibootmgr -c -d "/dev/$DISK_DEV" -p "$ESP_PART" -L osmium -l "$LOADER_ARG" 2>/dev/null) || exit 0
NEW_NUM=$(printf '%s\n' "$NEW_OUT" | sed -n 's/^Boot\([0-9A-Fa-f]\{4\}\)\*\{0,1\} osmium$/\1/p' | tail -n1)
[ -n "$NEW_NUM" ] || exit 0

# 2) Only now remove every OTHER entry (stale/duplicate "debian" entries from
#    past kernel updates, or a previous "osmium" entry).
efibootmgr | sed -n 's/^Boot\([0-9A-Fa-f]\{4\}\)\*\{0,1\} .*/\1/p' | while read -r num; do
    [ "$num" = "$NEW_NUM" ] && continue
    efibootmgr -b "$num" -B >/dev/null 2>&1 || true
done

# 3) Boot the new entry (and only it) from now on.
efibootmgr -o "$NEW_NUM" >/dev/null 2>&1 || true

exit 0
