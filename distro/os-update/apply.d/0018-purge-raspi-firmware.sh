# shellcheck shell=sh
# 0018 — Remove stray raspi-firmware (the appliance is an x86 mini PC — the
# Raspberry Pi firmware package is never needed). Its kernel/initramfs hooks
# fail on x86 ("missing /boot/firmware") and abort the linux-image postinst,
# leaving kernel updates half-configured and every later apt/dpkg run broken.
#
# Replicates the fix verified by hand on a device:
#   rm -f /etc/kernel/postinst.d/z50-raspi-firmware      ← the one that aborts
#   rm -f /etc/initramfs/post-update.d/z50-raspi-firmware
#   apt-get purge -y raspi-firmware
# Order matters: purging triggers `dpkg --configure` of any pending
# linux-image, which re-runs /etc/kernel/postinst.d/* — so BOTH hooks must be
# gone BEFORE the purge or the purge itself fails (seen in the field).
#
# Idempotency:
#   • Hooks are removed (and mark_changed called) only if present.
#   • dpkg -s succeeds for installed and removed-but-not-purged ("rc") states
#     and fails once fully purged, so a second run is a clean no-op.
#   • HIFI_OS_NO_APT=1 (CI idempotency test) skips the apt call entirely.
# No reboot needed. Also purged at ISO build time by the matching chroot hook
# (distro/config/hooks/normal/0450-purge-raspi-firmware.hook.chroot).

for hook in /etc/kernel/postinst.d/z50-raspi-firmware \
            /etc/initramfs/post-update.d/z50-raspi-firmware; do
    if [ -e "$hook" ]; then
        rm -f "$hook"
        mark_changed "removed raspi-firmware hook $hook"
    fi
done

PKG=raspi-firmware
if dpkg -s "$PKG" >/dev/null 2>&1; then
    if [ "${HIFI_OS_NO_APT:-0}" = 1 ]; then
        log_info "skip purge $PKG (HIFI_OS_NO_APT set)"
    else
        log_info "purging $PKG…"
        if DEBIAN_FRONTEND=noninteractive apt-get purge -y "$PKG" >/dev/null 2>&1; then
            mark_changed "purged package $PKG"
        else
            log_warn "could not purge $PKG now (retry on a later update)"
        fi
    fi
fi
