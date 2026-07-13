# shellcheck shell=sh
# 0020 — Install the EFI-boot-entry fix as a kernel postinst.d hook.
#
# Field bug: on this fleet, a kernel update sometimes leaves a stale UEFI NVRAM
# boot entry that the firmware boots first (dropping to a bare `grub>` rescue
# prompt), while a NEW "debian" entry created by the same update works fine if
# picked by hand from the BIOS boot menu. See files/hifi-fix-efi-boot.sh for
# the full explanation and the fix itself (single source of truth, shared with
# the ISO — distro/config/includes.chroot/etc/kernel/postinst.d/ — via
# build-distro.sh, same pattern as the canonical .xsession).
#
# This migration only DEPLOYS the hook; the hook itself does the NVRAM work,
# and only runs on a future kernel update (not now, not by this OTA) — editing
# UEFI NVRAM outside of a real kernel-update event is unnecessary risk this
# channel avoids (see 0010-secure-boot.sh for why bootloader-adjacent OTA
# changes are treated this carefully on a headless, no-SSH-by-default fleet).
#
# Idempotency: ensure_pkg/ensure_file_content are no-ops when already applied.
# No reboot needed — takes effect on the device's next kernel update.
ensure_pkg efibootmgr || true

HOOK_SRC="$HIFI_PAYLOAD_DIR/files/hifi-fix-efi-boot.sh"
HOOK_DEST=/etc/kernel/postinst.d/zzz-hifi-fix-efi-boot

if [ -f "$HOOK_SRC" ]; then
    ensure_file_content "$HOOK_DEST" 755 < "$HOOK_SRC"
else
    log_warn "missing $HOOK_SRC — skipping EFI boot-entry fix hook"
fi
