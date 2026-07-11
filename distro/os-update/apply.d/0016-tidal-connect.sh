# shellcheck shell=sh
# 0016 — Tidal Connect prerequisites (optional, OFF by default).
#
# Lets the appliance be controlled as a Tidal Connect target: the Tidal app on a
# phone discovers it over mDNS and streams directly to it. The daemon itself is
# an unofficial, reverse-engineered binary that we deliberately do NOT bundle (no
# trusted x86_64 build ships with the image), so this migration only sets up the
# prerequisites and the (disabled) systemd unit. The Settings toggle stays
# "unavailable" until a `tidal_connect` binary is actually present at
# /usr/local/bin/tidal_connect — see api_server.py get_tidal_status().
#
# Idempotent: avahi is installed only if missing; the unit is written only on a
# real diff. Never enabled here — the user opts in from Settings.

# mDNS/Bonjour discovery — Tidal Connect advertises itself via avahi.
ensure_pkg avahi-daemon || true

UNIT=/etc/systemd/system/tidal-connect.service
ensure_file_content "$UNIT" 644 root:root <<'EOF'
[Unit]
Description=Tidal Connect (optional, unofficial)
After=network-online.target avahi-daemon.service sound.target
Wants=network-online.target avahi-daemon.service

[Service]
Type=simple
# The binary is NOT shipped with the image. Provide an x86_64 tidal_connect
# build at this path; the appliance then exposes the toggle in Settings. The
# output device is selected by the same DAC the wizard configures.
ExecStart=/usr/local/bin/tidal_connect
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Make systemd aware of a newly written/changed unit (no enable — stays off).
if migration_changed; then
    systemctl daemon-reload 2>/dev/null || true
fi
