# shellcheck shell=sh
# 0011 — Faster boot, round 3: kill a 2s binfmt stall, drop the VT keymap, and
# take the EFI System Partition off the critical path.
#
# Measured on the x86 mini-PC with `systemd-analyze` after 0007–0009
# (graphical.target was ~6.7s in userspace, total ~18.6s):
#
#   • systemd-binfmt.service stalled a reproducible ~2.0s gating sysinit.target
#     (and so everything downstream). All it does on this appliance is register
#     Python .pyc direct-execution (/usr/lib/binfmt.d/python3.11.conf) via
#     binfmt_misc — we run python by interpreter, never by exec'ing a .pyc, so
#     the whole machinery is dead weight. Masking it dropped sysinit from ~3.0s
#     to ~2.0s. This is the big win.
#
#   • keyboard-setup.service (~0.7s) only sets the *text VT* keymap and sits
#     first on the critical chain. The kiosk is an X session that configures its
#     own keyboard, so the VT keymap is irrelevant here.
#
#   • /boot/efi (the ESP) is only touched during kernel/GRUB updates, never at
#     runtime, yet its fsck+mount cost ~1s on the boot path. Switching it to an
#     on-demand systemd automount removes that from the critical path; it still
#     mounts transparently the instant anything reads it (e.g. update-grub).
#
# Net on the test box: ~18.6s → ~16.0s total, graphical.target ~6.7s → ~4.5s.
#
# No reboot is requested — every change takes effect at the next natural boot and
# nothing is stopped on the running system (masks are NOT --now; the fstab edit
# leaves the currently-mounted ESP alone, the next boot regenerates the unit).
# Idempotent: a second run (and the CI idempotency check) reports changed=0.

# Mask a unit only if present and not already masked, and mark_changed only on a
# real, successful state change. NOT --now: don't disturb the running session.
mask_unit() {
    u="$1"
    command -v systemctl >/dev/null 2>&1 || return 0
    state=$(systemctl is-enabled "$u" 2>/dev/null) || state=""
    [ -n "$state" ] || return 0
    [ "$state" = "masked" ] && return 0
    if systemctl mask "$u" >/dev/null 2>&1; then
        mark_changed "masked $u"
    fi
}

mask_unit systemd-binfmt.service
mask_unit keyboard-setup.service

# ── ESP on-demand automount ──────────────────────────────────────────
# Append noauto + x-systemd.automount to the /boot/efi line's options field,
# matching by mountpoint+fstype so it works regardless of the per-device ESP
# UUID. Guarded so we only touch (and only mark_changed for) an ESP line that
# isn't already an automount; validated so a non-matching/odd fstab is restored.
_efi_is_automount() { grep -qE '/boot/efi[[:space:]].*x-systemd\.automount' "$1"; }

if grep -qE '/boot/efi[[:space:]].*[[:space:]]vfat[[:space:]]' /etc/fstab \
   && ! _efi_is_automount /etc/fstab; then
    backup_and_edit /etc/fstab _efi_is_automount \
        's#\(/boot/efi[[:space:]]\{1,\}vfat[[:space:]]\{1,\}\)\([^[:space:]]\{1,\}\)#\1\2,noauto,x-systemd.automount,x-systemd.idle-timeout=120#'
fi
