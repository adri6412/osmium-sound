# shellcheck shell=sh
# 0012 — Remove the hibernate (S4) setup trialed in v2.5.13-dev.1.
#
# Hibernate was tried so the appliance would resume instead of cold-booting, but on
# this hardware the resume (reading the multi-GB image back from the SATA SSD) was
# measurably SLOWER than an ordinary cold boot, so it's reverted. This migration
# undoes what the (now-deleted) 0012-hibernate.sh created: the /swapfile and the
# initramfs resume target. It only ever shipped on the dev channel, so nothing
# downstream depends on it.
#
# Idempotent and a clean no-op on any device that never had hibernate — every step
# is guarded by an existence check. No reboot is requested (dropping the resume conf
# only affects future boots, and shutdown is back to a plain poweroff). Skipped
# under the CI idempotency run for the initramfs regen (HIFI_OS_NO_APT).

SWAPFILE=/swapfile
RESUME_CONF=/etc/initramfs-tools/conf.d/resume

# ── 1. deactivate + drop the swapfile ────────────────────────────────
if grep -qE "^${SWAPFILE}[[:space:]]" /proc/swaps 2>/dev/null; then
    if swapoff "$SWAPFILE" 2>/dev/null; then
        mark_changed "swapoff $SWAPFILE"
    else
        log_warn "swapoff $SWAPFILE failed (busy?) — leaving the file in place"
    fi
fi
# remove the fstab line 0012-hibernate.sh appended (custom sed delimiter '#'
# because the path contains a slash).
if grep -qE "^[[:space:]]*${SWAPFILE}[[:space:]]" /etc/fstab 2>/dev/null; then
    sed -i "\\#^[[:space:]]*${SWAPFILE}[[:space:]]#d" /etc/fstab
    mark_changed "removed $SWAPFILE from /etc/fstab"
fi
# delete the file only once it is no longer an active swap device.
if [ -f "$SWAPFILE" ] && ! grep -qE "^${SWAPFILE}[[:space:]]" /proc/swaps 2>/dev/null; then
    rm -f "$SWAPFILE" && mark_changed "removed $SWAPFILE"
fi

# ── 2. drop the initramfs resume target + regenerate ─────────────────
if [ -f "$RESUME_CONF" ]; then
    rm -f "$RESUME_CONF"
    mark_changed "removed $RESUME_CONF"
    if [ "${HIFI_OS_NO_APT:-0}" != 1 ] && command -v update-initramfs >/dev/null 2>&1; then
        log_info "regenerating initramfs without hibernate resume target…"
        update-initramfs -u >/dev/null 2>&1 || log_warn "update-initramfs failed — old initrd kept"
    fi
fi
