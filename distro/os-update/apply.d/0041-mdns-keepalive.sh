# shellcheck shell=sh
# 0041 — mDNS/DHCP keepalive (periodic re-announce).
#
# Reported symptom: after Osmium sits idle overnight with the screensaver up,
# the router "forgets" both the mDNS hostname (<name>.local stops resolving)
# AND the box's direct LAN IP — i.e. the router's own ARP/neighbor table
# entry for the box expired too, not just its mDNS cache, so plain IP
# connections silently die the same way. The box stays reachable the whole
# time via its Tailscale IP (Tailscale keeps its own tunnel warm independent
# of the LAN link), and the moment a Tailscale-routed connection touches the
# box, LAN/.local reachability comes back on its own. The in-app screensaver
# (src/components/Screensaver.jsx, driven from App.jsx) is a pure UI overlay —
# it never touches networking — so nothing on this box currently re-asserts
# its presence on the LAN once the router drops it after hours of silence.
# avahi-daemon does refresh its own mDNS records on a timer, but that's no
# help if the ROUTER's own ARP/local-DNS table is what expired; only fresh
# traffic from this device fixes that.
#
# Fix: a lightweight timer that periodically (a) pings the default gateway,
# which touches the router's ARP/DHCP-client table and keeps this device
# "seen" on quiet networks — this is what fixes plain-IP reachability, not
# just mDNS — and (b) restarts avahi-daemon, which forces a fresh set of mDNS
# announcement packets for <name>.local — cheap (sub-second, no audio/UI
# impact) and the most direct way to make a router that dropped the record
# re-learn it, short of a full network-stack bounce. Runs every 5 minutes
# (tightened from an initial 20min — some routers/APs GC idle ARP entries
# faster than that, letting the box go dark between pings) starting 2 minutes
# after boot.
#
# Always on (no user-facing toggle — this is baseline appliance behaviour,
# same tier as 0038's /etc/hosts self-heal). Idempotent: units via
# ensure_file_content; the enable step enables+starts on first install, and
# restarts the timer (to re-arm its schedule) if the unit content changed on
# an already-enabled box, e.g. picking up this interval tightening.
#
# UPDATE (0054): the symptom kept being reported with this timer active, so
# the router-side theory above was at best incomplete — ping + re-announce
# are OUTBOUND traffic (and Tailscale already keeps that flowing), which can't
# help when the box's own NIC is asleep and deaf to unsolicited frames. The
# actual root cause (NIC power saving: Wi-Fi PS / Ethernet EEE / runtime PM)
# is handled by 0054-nic-no-powersave.sh. This migration stays as-is: it is
# harmless and still covers routers that genuinely expire idle neighbours.

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
OnBootSec=2min
OnUnitActiveSec=5min
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
elif migration_changed; then
    # Already enabled from a previous update: daemon-reload alone doesn't
    # re-arm an active timer's next-elapse against the new OnUnitActiveSec,
    # so restart it to actually pick up the shortened interval.
    systemctl restart hifi-mdns-keepalive.timer >/dev/null 2>&1 \
        && mark_changed "restarted hifi-mdns-keepalive.timer (schedule updated)"
fi
