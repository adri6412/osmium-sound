# shellcheck shell=sh
# 0008 — Smaller initramfs (MODULES=dep) for a much faster boot.
#
# The image ships initramfs-tools with MODULES=most, which bundles essentially
# every driver into the initrd (~110 MB on the x86 mini-PC). Read from the slow
# eMMC and decompressed by the kernel, that bloats the GRUB "loader" and kernel
# boot stages by many seconds (measured: loader ~10s + kernel ~10s with the big
# initrd). MODULES=dep includes only the drivers the root device actually needs.
#
# This is regenerated ON EACH DEVICE as part of the OS update, so `dep` resolves
# against that unit's own hardware — no risk of a one-size initrd missing a
# driver some machine needs.
#
# No reboot is requested: the new, smaller initrd is picked up at the next boot.
# Idempotent: the setting is flipped only while it is still "most", and the
# initramfs is regenerated only on that real change (skipped under the CI
# idempotency run via HIFI_OS_NO_APT).

CONF=/etc/initramfs-tools/initramfs.conf
[ -f "$CONF" ] || return 0
grep -q '^MODULES=most' "$CONF" || return 0   # already dep/other → clean no-op

backup_and_edit "$CONF" "" 's/^MODULES=most/MODULES=dep/'

if migration_changed \
   && [ "${HIFI_OS_NO_APT:-0}" != 1 ] \
   && command -v update-initramfs >/dev/null 2>&1; then
    log_info "regenerating initramfs with MODULES=dep (smaller, faster boot)…"
    update-initramfs -u >/dev/null 2>&1 || log_warn "update-initramfs failed — old initrd kept"
fi
