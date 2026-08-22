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
