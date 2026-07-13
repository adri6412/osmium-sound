# shellcheck shell=sh
# 0021 — Correct delivery for the EFI-boot-entry fix: an apt DPkg::Post-Invoke
# hook instead of a kernel postinst.d hook.
#
# 0020 (previous release) installed the fix as /etc/kernel/postinst.d/, which
# runs inside the KERNEL package's own postinst — too early to see an entry
# created by grub-efi-amd64-signed/shim-signed's postinst, which configures
# AFTER the kernel in the same apt transaction (confirmed in the field: a
# combined `apt-get install --reinstall linux-image-... grub-efi-amd64-signed
# shim-signed` produced a new duplicate NVRAM entry that the kernel-postinst
# hook never got a chance to clean up). 0020 is left as shipped (the OS
# channel never rewrites a released migration) — it's harmless, still
# self-verifying, and still helps on a kernel-only update with no grub
# involved. This migration ADDS the mechanism that actually catches the bug:
# DPkg::Post-Invoke fires after the ENTIRE apt/dpkg transaction (every
# package configured, every trigger processed), regardless of which packages
# were involved or in what order.
#
# DPkg::Post-Invoke fires on EVERY apt/dpkg transaction, not just kernel/grub
# ones — but the script itself is throttled: it only does real NVRAM writes
# when the newest grubx64.efi on the ESP actually changed since last time
# (fingerprint in /var/lib/hifi-player/efi-boot-fix.state), so `apt install
# curl` is a cheap no-op past a single find(1) scan. See
# files/hifi-fix-efi-boot.sh for the fix logic itself (shared, single source
# of truth with the ISO — distro/build-distro.sh injects the same file to the
# same two paths at image-build time).
#
# Idempotency: ensure_pkg/ensure_file_content are no-ops when already
# applied. No reboot needed. We also run the fix once now (best-effort) so a
# device with an existing duplicate/stale-entry mess (like the one that
# surfaced this bug) is cleaned up immediately rather than waiting for the
# next apt transaction — safe because the script itself never removes an
# existing entry until a new, verified-working one is already in place.
ensure_pkg efibootmgr || true

HOOK_SRC="$HIFI_PAYLOAD_DIR/files/hifi-fix-efi-boot.sh"
SCRIPT_DEST=/usr/local/sbin/hifi-fix-efi-boot.sh

if [ -f "$HOOK_SRC" ]; then
    ensure_file_content "$SCRIPT_DEST" 755 < "$HOOK_SRC"
else
    log_warn "missing $HOOK_SRC — skipping EFI boot-entry apt hook"
fi

ensure_file_content /etc/apt/apt.conf.d/99-hifi-fix-efi-boot 644 <<'EOF'
DPkg::Post-Invoke { "test -x /usr/local/sbin/hifi-fix-efi-boot.sh && /usr/local/sbin/hifi-fix-efi-boot.sh; true"; };
EOF

if [ -x "$SCRIPT_DEST" ]; then
    "$SCRIPT_DEST" || true
fi
