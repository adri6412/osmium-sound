# shellcheck shell=sh
# 0044 — Beta-testing telemetry agent.
#
# Ships hifi-beta-agent.service (persistent daemon, Type=simple/Restart=always
# like hifi-vumeter.service — not a timer) and enables it. The worker script
# itself (hifi-beta-agent.py) ships as a plain file under usr/local/sbin,
# picked up by the existing glob in build-ui-ota.yml, same as
# 0033-backup-scheduler.sh's worker script -- this migration only manages the
# unit.
#
# Unconditional enable: unlike the backup timer, this isn't a user-facing
# on/off toggle -- every machine on the alpha channel is a beta-test unit for
# the duration of the private beta, so it always runs. It self-registers with
# the cloud server (see hifi-beta-agent.py) and takes all of its actual
# cadence/behaviour from there, not from anything decided here.
#
# Idempotent: unit via ensure_file_content (no-op once byte-identical), enable
# only touches systemd state when it actually differs from what's wanted.
# Never reboots -- a Type=simple service takes effect immediately.

ensure_file_content /etc/systemd/system/hifi-beta-agent.service 644 root:root <<'EOF'
[Unit]
Description=HiFi Player - Beta Testing Telemetry Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=hifi
StateDirectory=hifi-beta-agent
WorkingDirectory=/usr/local/sbin
ExecStart=/usr/bin/python3 /usr/local/sbin/hifi-beta-agent.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

if migration_changed; then
    systemctl daemon-reload 2>/dev/null || true
fi

state=$(systemctl is-enabled hifi-beta-agent.service 2>/dev/null) || state=""
if [ "$state" != "enabled" ]; then
    systemctl enable --now hifi-beta-agent.service >/dev/null 2>&1 \
        && mark_changed "enabled hifi-beta-agent.service"
elif migration_changed; then
    # Unit content itself changed (not just first-enable) -- restart to pick
    # it up. Content-only updates to hifi-beta-agent.py (no unit change) are
    # instead picked up by hifi-system-update.sh's restart of this service.
    systemctl restart hifi-beta-agent.service >/dev/null 2>&1 || true
fi
