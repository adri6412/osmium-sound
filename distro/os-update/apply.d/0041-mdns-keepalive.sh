# shellcheck shell=sh
# 0041 — mDNS/DHCP keepalive (periodic re-announce).
#
# Reported symptom: after Osmium sits idle overnight with the screensaver up,
# the router "forgets" the mDNS hostname assignment (<name>.local stops
# resolving) even though the box is still up and reachable via its Tailscale
# IP. The in-app screensaver (src/components/Screensaver.jsx, driven from
# App.jsx) is a pure UI overlay — it never touches networking — so nothing on
# this box currently re-asserts the hostname once avahi's own announcement is
# dropped by a flaky AP/router over many hours of silence. avahi-daemon does
# refresh its own records on a timer, but that's no help if the ROUTER's own
# local-DNS/ARP table is what expired; only fresh traffic from this device
# fixes that.
#
# Fix: a lightweight timer that periodically (a) pings the default gateway,
# which touches the router's ARP/DHCP-client table and keeps this device
# "seen" on quiet networks, and (b) restarts avahi-daemon, which forces a
# fresh set of mDNS announcement packets for <name>.local — cheap (sub-second,
# no audio/UI impact) and the most direct way to make a router that dropped
# the record re-learn it, short of a full network-stack bounce.
#
# Always on (no user-facing toggle — this is baseline appliance behaviour,
# same tier as 0038's /etc/hosts self-heal). Idempotent: units via
# ensure_file_content, the enable step only touches systemd state when the
# timer isn't already enabled.

ensure_file_content /usr/local/sbin/hifi-mdns-keepalive.sh 755 root:root <<'EOF'
#!/bin/sh
# HiFi Player — periodic network/mDNS keepalive (see apply.d/0041 for why).
set -eu

GW=$(ip route show default 2>/dev/null | awk '/^default/ {print $3; exit}')
if [ -n "$GW" ]; then
    ping -c 1 -W 2 "$GW" >/dev/null 2>&1 || true
fi

if systemctl is-active --quiet avahi-daemon 2>/dev/null; then
    systemctl try-restart avahi-daemon >/dev/null 2>&1 || true
fi
EOF

ensure_file_content /etc/systemd/system/hifi-mdns-keepalive.service 644 root:root <<'EOF'
[Unit]
Description=HiFi Player - mDNS/DHCP keepalive
After=network-online.target avahi-daemon.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/hifi-mdns-keepalive.sh
EOF

ensure_file_content /etc/systemd/system/hifi-mdns-keepalive.timer 644 root:root <<'EOF'
[Unit]
Description=HiFi Player - mDNS/DHCP keepalive (periodic)

[Timer]
OnBootSec=5min
OnUnitActiveSec=20min
Persistent=false

[Install]
WantedBy=timers.target
EOF

if migration_changed; then
    systemctl daemon-reload 2>/dev/null || true
fi

state=$(systemctl is-enabled hifi-mdns-keepalive.timer 2>/dev/null) || state=""
if [ "$state" != "enabled" ]; then
    systemctl enable --now hifi-mdns-keepalive.timer >/dev/null 2>&1 \
        && mark_changed "enabled hifi-mdns-keepalive.timer"
fi
