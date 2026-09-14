#!/bin/sh
# Osmium Sound — turn power saving OFF on network interfaces.
#
#   hifi-nic-powersave-off.sh [IFACE ...]    no args = every physical NIC
#
# Called by the NetworkManager dispatcher hook on every interface `up`. Covers
# the two knobs NetworkManager has no setting for (Ethernet EEE and the NIC's
# own runtime power management) plus a belt-and-braces pass on Wi-Fi power
# save, which conf.d/90-hifi-wifi-powersave.conf already disables at
# activation. See that file for why an always-on appliance wants none of this.
#
# Every step is best-effort: a NIC that does not support a knob, or a missing
# tool, is silently skipped. Always exits 0.
set -u
PATH=/usr/sbin:/usr/bin:/sbin:/bin

nic_powersave_off() {
    _if="$1"
    _sys="/sys/class/net/$_if"
    # Only real hardware: lo, tun/tap (tailscale0), bridges, veth… have no
    # backing device and nothing to power-manage.
    [ -d "$_sys/device" ] || return 0

    if [ -d "$_sys/wireless" ] || [ -d "$_sys/phy80211" ]; then
        # Wi-Fi: 802.11 power save off. Fails harmlessly in AP mode (the
        # first-boot setup hotspot).
        if command -v iw >/dev/null 2>&1; then
            iw dev "$_if" set power_save off >/dev/null 2>&1 || true
        fi
    else
        # Ethernet: Energy-Efficient Ethernet low-power idle off (no-op when
        # already off, "not supported" on NICs without EEE — both ignored).
        if command -v ethtool >/dev/null 2>&1; then
            ethtool --set-eee "$_if" eee off >/dev/null 2>&1 || true
        fi
    fi

    # Runtime power management of the controller itself: keep it awake.
    # PCI NICs expose power/control on the device; for USB NICs the netdev's
    # device is the USB *interface* (no runtime-PM knob) and the knob is on
    # its parent, the USB device.
    _pc="$_sys/device/power/control"
    [ -e "$_pc" ] || _pc="$_sys/device/../power/control"
    if [ -w "$_pc" ]; then
        echo on > "$_pc" 2>/dev/null || true
    fi
    return 0
}

if [ $# -gt 0 ]; then
    for _i in "$@"; do nic_powersave_off "$_i"; done
else
    for _p in /sys/class/net/*; do
        [ -e "$_p" ] || continue
        nic_powersave_off "$(basename "$_p")"
    done
fi
exit 0
