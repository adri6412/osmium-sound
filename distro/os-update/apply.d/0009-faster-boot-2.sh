# shellcheck shell=sh
# 0009 — Further boot speedups: drop unused Bluetooth + redundant ifupdown.
#
# Measured on the x86 mini-PC after the initramfs shrink (0008):
#   • The Bluetooth stack (btusb + bluetooth, a ~1 MB module plus an RTL
#     firmware load) is brought up at boot but idle until the owner turns on a
#     Bluetooth speaker or pairs a Bluetooth remote. Blacklisting keeps it off
#     the boot path for the many devices that never use it.
#     🚨 blacklist ONLY — no `install btusb /bin/true`. Bluetooth is now a
#     supported feature (speakers AND remotes): hifi-bt-out.py loads the module
#     on demand with an explicit `modprobe btusb`, and an `install … /bin/true`
#     override would silently defeat that modprobe, leaving the adapter
#     invisible (no /sys/class/bluetooth, bluetooth.service ConditionPath unmet)
#     even when the owner asked for Bluetooth — issue #126. A plain blacklist
#     only stops auto-load; an explicit modprobe still works.
#     ensure_file_content rewrites the corrected file on the next OS OTA, so a
#     legacy device that still carries the old override is healed automatically.
#   • networking.service (ifupdown) only brings up loopback here — every real
#     interface is managed by NetworkManager — so it is redundant boot work.
#
# Neither lives in the initrd, so no initramfs regen is needed; both take effect
# at the next boot (nothing is stopped on the running system). Idempotent.

ensure_file_content /etc/modprobe.d/hifi-no-bluetooth.conf 644 <<'EOF'
# Keep Bluetooth off the boot path (faster startup) — but only auto-load:
# hifi-bt-out.py still loads btusb on demand for a speaker or a remote.
# NO `install btusb /bin/true` here: it would defeat that modprobe (issue #126).
blacklist btusb
blacklist bluetooth
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
