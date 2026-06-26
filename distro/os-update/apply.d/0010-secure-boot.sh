# shellcheck shell=sh
# 0010 — UEFI Secure Boot support: install Debian's signed boot chain.
#
# The appliance installs grub-efi-amd64 (UNSIGNED) on UEFI machines, so with
# UEFI Secure Boot turned ON in firmware the box will NOT boot — there is no
# Microsoft-signed shim to anchor the trust chain. This migration installs the
# signed chain so the owner can safely enable Secure Boot in firmware:
#
#     shimx64.efi (MS-signed) → grubx64.efi (Debian-signed) → linux-image-amd64
#                                                              (already signed)
#
# It does NOT — and from the OS cannot — flip the firmware Secure Boot toggle;
# that stays a manual, owner-side action. The device is therefore made
# Secure-Boot-*capable*, not locked: this preserves the project's
# verified-but-not-tivoised stance (the owner still controls the firmware and can
# enrol their own keys).
#
# SAFETY — this is a headless fleet with NO SSH by default, so a broken
# bootloader is unrecoverable. Every step is defensive:
#   • UEFI-ONLY: do nothing on BIOS/CSM installs (no /sys/firmware/efi). Secure
#     Boot is meaningless there and grub-install --target=x86_64-efi would fail.
#   • ADDITIVE: installing the -signed packages does NOT remove grub-efi-amd64,
#     so the existing unsigned grubx64.efi keeps booting if anything goes wrong.
#   • VERIFIED: grub-install runs ONLY after shimx64.efi is actually on disk and
#     a real ESP is mounted; the same NVRAM "debian" entry is rewritten in place
#     (no bootloader-id change, old loader never deleted). A failure logs and
#     leaves the working unsigned GRUB untouched.
#
# No reboot is requested: the new shim/grub on the ESP is used at the next boot,
# and enabling Secure Boot in firmware is a manual reboot-into-setup step anyway.
# Idempotent: packages install only when missing, and grub-install re-runs only
# on the run that freshly installed the shim (migration_changed) — a later run
# with everything present is a clean no-op (changed=0, no grub-install).

# 1) UEFI only — BIOS installs have no Secure Boot to support.
[ -d /sys/firmware/efi ] || { log_info "BIOS boot (no EFI) — Secure Boot N/A, skipping"; return 0; }

# 2) Install the signed chain. grub-efi-amd64-signed depends on shim-signed;
#    efibootmgr lets grub-install register/repair the NVRAM boot entry. Each is
#    a no-op (no mark_changed) when already present.
ensure_pkg grub-efi-amd64-signed || true
ensure_pkg shim-signed           || true
ensure_pkg efibootmgr            || true

# Under the CI idempotency run nothing is installed; stop before touching the
# bootloader so the test stays offline and reports changed=0.
[ "${HIFI_OS_NO_APT:-0}" = 1 ] && return 0

# 3) Re-install GRUB through shim — but ONLY when the shim was actually just put
#    on disk (migration_changed), a real ESP is mounted, and grub-install exists.
#    Re-running with the shim already in place is a clean no-op.
SHIM=/usr/lib/shim/shimx64.efi.signed
ESP=/boot/efi
if migration_changed && [ -f "$SHIM" ] && [ -d "$ESP/EFI" ] \
   && command -v grub-install >/dev/null 2>&1; then
    log_info "installing the signed shim+GRUB chain on the ESP ($ESP)…"
    if grub-install --target=x86_64-efi --efi-directory="$ESP" \
                    --uefi-secure-boot >/dev/null 2>&1; then
        update-grub >/dev/null 2>&1 || true
        log_info "Secure Boot chain installed — enable Secure Boot in firmware to use it."
    else
        log_warn "grub-install (Secure Boot) failed — unsigned GRUB left in place, box still boots."
    fi
fi
