# shellcheck shell=sh
# 0054 — Disable network-interface power saving (Wi-Fi PS, Ethernet EEE,
# PCI/USB runtime PM on the NIC).
#
# Reported symptom (same one 0041 first tried to fix, and it is STILL
# reported with 0041's keepalive active fleet-wide): after hours of idle the
# box disappears from the LAN — Lyrion (:9000) and the web UI stop answering,
# <name>.local stops resolving — while it stays perfectly reachable over
# Tailscale, and the moment something on the box itself generates sustained
# traffic (e.g. starting a Qobuz stream from the screen) it is "magically"
# back on the LAN.
#
# What that pattern actually says: the box can still INITIATE traffic and get
# the replies to its own flows (Tailscale keepalives, 0041's gateway ping,
# streaming), but is deaf to UNSOLICITED inbound frames — ARP who-has
# broadcasts, TCP SYNs to :9000/:8080, mDNS queries. That is the signature of
# a network interface in a power-save state: a Wi-Fi chip in 802.11 power
# save dozes between beacons and only reliably receives while it is awake for
# its own traffic (a 1-packet ping every 5 minutes wakes it for ~100 ms, a
# continuous stream keeps it awake — hence "playing Qobuz fixes it"); the
# same class of failure exists on Ethernet with EEE low-power idle and with
# the NIC's PCI/USB runtime power management. 0041 only re-asserts the box's
# presence to the ROUTER (outbound traffic); it cannot make the box hear
# frames its own NIC is asleep for, which is why it did not cure this.
#
# Nothing in the image ever turned power saving off: Debian's kernel ships
# CONFIG_CFG80211_DEFAULT_PS=y, so every mac80211 Wi-Fi driver (Intel
# iwlwifi, Realtek rtw88/89, MediaTek mt76, …) comes up with power save ON,
# and NetworkManager's wifi.powersave default (0) leaves the driver default
# alone. On a mains-powered appliance that is all cost and no benefit — the
# usual appliance practice (Home Assistant OS, kiosk images) is to switch it
# off fleet-wide, which is what this migration does:
#
#   • /etc/NetworkManager/conf.d/90-hifi-wifi-powersave.conf
#       [connection] wifi.powersave=2 → NetworkManager activates every Wi-Fi
#       connection with 802.11 power save DISABLED (via nl80211, so it covers
#       all mac80211 drivers without per-driver module options). Applies to
#       profiles that leave the property at its default (all of ours).
#       NetworkManager is told to reload its config; the setting takes effect
#       at the next Wi-Fi (re)activation — i.e. at the reboot that ends the
#       update session — and the helper below covers the live connection.
#   • /usr/local/sbin/hifi-nic-powersave-off.sh — per-interface helper:
#       Wi-Fi → `iw dev <if> set power_save off` (belt and braces / live),
#       Ethernet → `ethtool --set-eee <if> eee off` (EEE LPI off),
#       both → PCI/USB runtime PM `power/control=on` on the NIC itself.
#       Every step is best-effort (unsupported NIC, missing tool → silently
#       skipped); it never touches lo, tun (tailscale0) or virtual devices.
#   • /etc/NetworkManager/dispatcher.d/90-hifi-nic-powersave — runs the
#       helper on every `up` of an interface, so the Ethernet/runtime-PM part
#       (which NetworkManager has no setting for) is re-applied on every
#       (re)connect and every boot.
#   • ensure_pkg iw + ethtool: both tiny, neither in the base image. Best
#       effort — if apt can't run now (offline staged apply) the Wi-Fi part
#       still works through NetworkManager alone and the install is retried
#       on the next OS update (ensure_pkg no-ops once installed).
#
# Takes effect live (no reboot requested): on a change the helper is run once
# for every interface that is already up. Idempotent: file writes via
# ensure_file_content, reload/apply only on a real change. Not yet baked into
# the ISO (distro/config/includes.chroot) on purpose — a fresh image picks it
# up with its first OS update, the OS channel being cumulative.
#
# 0041 stays in place (harmless, and it still helps routers that really do
# expire idle neighbours); its header points here for the actual root cause.

ensure_pkg iw      || true
ensure_pkg ethtool || true

mkdir -p /etc/NetworkManager/conf.d /etc/NetworkManager/dispatcher.d 2>/dev/null || true

ensure_file_content /etc/NetworkManager/conf.d/90-hifi-wifi-powersave.conf 644 root:root <<'EOF'
# Installed by HiFi Player OS migration 0054 — see that script for why.
#
# Mains-powered appliance: 802.11 power save only ever made the box deaf to
# unsolicited LAN traffic (ARP, mDNS, new TCP connections) after hours of idle.
# 2 = disable. Applies to every Wi-Fi profile that leaves wifi.powersave at
# its default (0); takes effect at (re)activation.
[connection]
wifi.powersave=2
EOF

ensure_file_content /usr/local/sbin/hifi-nic-powersave-off.sh 755 root:root <<'EOF'
#!/bin/sh
# HiFi Player — turn power saving OFF on network interfaces.
# Installed by OS migration 0054 (see distro/os-update/apply.d/0054-*.sh).
#
#   hifi-nic-powersave-off.sh [IFACE ...]    no args = every physical NIC
#
# Called by the NetworkManager dispatcher hook on every interface `up`, and
# once by the migration itself. Every step is best-effort: a NIC that does not
# support a knob, or a missing tool, is silently skipped. Always exits 0.
set -u
PATH=/usr/sbin:/usr/bin:/sbin:/bin

nic_powersave_off() {
    _if="$1"
    _sys="/sys/class/net/$_if"
    # Only real hardware: lo, tun/tap (tailscale0), bridges, veth… have no
    # backing device and nothing to power-manage.
    [ -d "$_sys/device" ] || return 0

    if [ -d "$_sys/wireless" ] || [ -d "$_sys/phy80211" ]; then
        # Wi-Fi: 802.11 power save off. NetworkManager already activates with
        # wifi.powersave=2 (conf.d); this also covers a connection that was
        # already up when that setting landed. Fails harmlessly in AP mode.
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
EOF

# NetworkManager only runs dispatcher scripts that are root-owned, executable
# and not group/other-writable — 755 root:root satisfies that.
ensure_file_content /etc/NetworkManager/dispatcher.d/90-hifi-nic-powersave 755 root:root <<'EOF'
#!/bin/sh
# HiFi Player — NetworkManager dispatcher hook: on every interface `up`, turn
# its power saving off (Wi-Fi PS / Ethernet EEE / NIC runtime PM). Installed
# by OS migration 0054 — see distro/os-update/apply.d/0054-*.sh for why.
#   $1 = interface name, $2 = action
[ "${2:-}" = "up" ] || exit 0
[ -n "${1:-}" ] || exit 0
[ -x /usr/local/sbin/hifi-nic-powersave-off.sh ] || exit 0
/usr/local/sbin/hifi-nic-powersave-off.sh "$1" || true
exit 0
EOF

if migration_changed; then
    # Make NetworkManager re-read conf.d (no restart, no connection bounce —
    # wifi.powersave applies at the next activation, the helper handles now).
    if command -v nmcli >/dev/null 2>&1 \
       && systemctl is-active --quiet NetworkManager 2>/dev/null; then
        nmcli general reload conf >/dev/null 2>&1 || true
    fi
    # Apply to whatever is up right now so a live update takes effect at once.
    /usr/local/sbin/hifi-nic-powersave-off.sh >/dev/null 2>&1 || true
fi
