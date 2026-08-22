# shellcheck shell=sh
# 0052 — Remove the private-beta telemetry agent from devices that have it.
#
# Counterpart to 0044 (now a no-op): the private beta is over, the agent, the
# cloud server and the site's privacy notice all went with it, so any unit
# still running it has to stop — an appliance must not keep sending
# diagnostics that nothing discloses any more.
#
# Removes, in the order that matters: the service (stop first, so nothing is
# mid-upload when its script disappears), the worker script, the registration
# state (device token + queued snapshots, so a reinstall of an older build
# could never resume the same identity), and the capture-schedule file the
# kiosk used to poll — main.js no longer reads it, but leaving a stale
# "enabled" schedule behind on disk is exactly the kind of thing that comes
# back to bite.
#
# HAR/perf captures already on disk are left alone: they are the owner's own
# data, visible and deletable in the web admin's Debug section, and nothing
# uploads them anywhere any more.
#
# One-time: gated on the leftover unit/script, so once they are gone this is
# a permanent no-op and reports changed=0 on every later update. 0044 no
# longer recreates them, so there is no churn. Never reboots — stopping a
# Type=simple service takes effect immediately.

UNIT=/etc/systemd/system/hifi-beta-agent.service
WORKER=/usr/local/sbin/hifi-beta-agent.py
STATE_DIR=/var/lib/hifi-beta-agent
SCHEDULE_FILE=/home/hifi/.config/hifi-media-player/beta-capture-schedule.json

if [ ! -e "$UNIT" ] && [ ! -e "$WORKER" ] && [ ! -e "$STATE_DIR" ] && [ ! -e "$SCHEDULE_FILE" ]; then
    exit 0
fi

if [ -e "$UNIT" ]; then
    systemctl disable --now hifi-beta-agent.service >/dev/null 2>&1 || true
    rm -f "$UNIT"
    systemctl daemon-reload >/dev/null 2>&1 || true
    mark_changed "removed the beta telemetry agent service"
fi

if [ -e "$WORKER" ]; then
    rm -f "$WORKER"
    mark_changed "removed the beta telemetry agent"
fi

if [ -e "$STATE_DIR" ]; then
    rm -rf "$STATE_DIR"
    mark_changed "removed the beta telemetry registration state"
fi

if [ -e "$SCHEDULE_FILE" ]; then
    rm -f "$SCHEDULE_FILE"
    mark_changed "removed the beta capture schedule"
fi
