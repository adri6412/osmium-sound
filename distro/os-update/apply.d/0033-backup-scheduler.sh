# shellcheck shell=sh
# 0033 — Scheduled backups: units + reconciliation.
#
# Ships hifi-backup.service (oneshot, runs hifi-backup-run.py --scheduled) and
# hifi-backup.timer (weekly), then enables/disables the timer to match the
# user's persisted choice in /etc/hifi-player/backup.json (written by
# sources_server.py's POST /api/backup/settings). Same shape as
# 0024-bluetooth.sh: install the units disabled, only the reconciliation step
# turns them on, and it re-applies the user's actual choice on every OS update
# so an unrelated release can never silently flip it back.
#
# Persistent=false on the timer, same reasoning as 0031-boot-speed-samba.sh:
# this appliance gets power-cycled like any household device, and a missed
# weekly slot catching up right at boot would compete with startup for
# CPU/disk exactly when it matters least to have a backup RIGHT NOW. A backup
# that runs a few hours later than scheduled costs nothing; a slower boot does.
# RandomizedDelaySec spreads devices that boot around the same time (e.g. after
# a power outage) instead of every one of them hitting the disk at once.
#
# The worker script and hifi_backup.py themselves ship via the System channel
# (they're plain files under usr/local/{sbin,bin}, picked up by the existing
# glob in build-ui-ota.yml) — this migration only manages the timer/service
# units and the on/off state, exactly like 0024 does for the Bluetooth units.
#
# Idempotent: units via ensure_file_content (no-op once byte-identical), the
# enable/disable step only touches systemd state when it actually differs from
# what's wanted. Never reboots — a timer takes effect immediately.

ensure_file_content /etc/systemd/system/hifi-backup.service 644 root:root <<'EOF'
[Unit]
Description=HiFi Player scheduled backup
# If a manual backup is already running (systemd-run --unit=hifi-backup, same
# name sources_server.py uses), let it finish rather than colliding with it.
ConditionPathExists=!/run/hifi-backup-job.json

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/hifi-backup-run.py --scheduled
# Backing up Lyrion's prefs tree can take a while on a device with many
# players/plugins configured; give it real headroom without hanging forever
# if something is stuck.
TimeoutStartSec=1800
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
EOF

ensure_file_content /etc/systemd/system/hifi-backup.timer 644 root:root <<'EOF'
[Unit]
Description=HiFi Player scheduled backup (weekly)

[Timer]
OnCalendar=weekly
Persistent=false
RandomizedDelaySec=3600

[Install]
WantedBy=timers.target
EOF

if migration_changed; then
    systemctl daemon-reload 2>/dev/null || true
fi

# ── Reconciliation: apply the user's persisted choice ────────────────
BACKUP_SETTINGS=/etc/hifi-player/backup.json
want_enabled=0
if [ -f "$BACKUP_SETTINGS" ] \
   && grep -q '"scheduled"[[:space:]]*:[[:space:]]*true' "$BACKUP_SETTINGS" 2>/dev/null; then
    want_enabled=1
fi

state=$(systemctl is-enabled hifi-backup.timer 2>/dev/null) || state=""
if [ "$want_enabled" = 1 ]; then
    if [ "$state" != "enabled" ]; then
        systemctl enable --now hifi-backup.timer >/dev/null 2>&1 \
            && mark_changed "enabled hifi-backup.timer (scheduled backup on)"
    fi
else
    if [ "$state" = "enabled" ] || [ "$state" = "static" ]; then
        systemctl disable --now hifi-backup.timer >/dev/null 2>&1 \
            && mark_changed "disabled hifi-backup.timer"
    fi
fi
