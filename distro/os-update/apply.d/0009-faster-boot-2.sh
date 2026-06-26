# shellcheck shell=sh
# 0009 — Further boot speedups: drop unused Bluetooth + redundant ifupdown.
#
# Measured on the x86 mini-PC after the initramfs shrink (0008):
#   • The Bluetooth stack (btusb + bluetooth, a ~1 MB module plus an RTL
#     firmware load) is brought up at boot but unused on this wired/Wi-Fi music
#     appliance. Blacklisting btusb (the USB entry point) keeps the whole stack
#     out of boot.
#   • networking.service (ifupdown) only brings up loopback here — every real
#     interface is managed by NetworkManager — so it is redundant boot work.
#
# Neither lives in the initrd, so no initramfs regen is needed; both take effect
# at the next boot (nothing is stopped on the running system). Idempotent.

ensure_file_content /etc/modprobe.d/hifi-no-bluetooth.conf 644 <<'EOF'
# Bluetooth is unused on the appliance — keep it out of boot (faster startup).
blacklist btusb
blacklist bluetooth
install btusb /bin/true
EOF

# Mask (don't --now: avoid touching the running session) only if present and not
# already masked, and only mark changed on a real, successful state change.
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

mask_unit networking.service
mask_unit bluetooth.service
