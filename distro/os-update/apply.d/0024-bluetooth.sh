# shellcheck shell=sh
# 0024 — Bluetooth audio (A2DP sink) prerequisites + reconciliation.
#
# Lets the appliance appear as a Bluetooth speaker: a phone connects and
# streams music straight to the DAC, no app/account needed (guest-friendly
# input, matching Volumio/WiiM/Bluesound/Eversolo). OFF by default — this
# migration only makes the toggle available, it never enables anything.
#
# 0009-faster-boot-2.sh blacklists btusb/bluetooth and masks bluetooth.service
# on EVERY OS update (that migration is cumulative, so it reasserts its state
# every run). This migration always runs AFTER 0009 (numeric order), so it is
# the one place that re-applies the user's actual choice (persisted by
# api_server.py in /etc/hifi-player/bluetooth.json) on top of 0009's default —
# otherwise Bluetooth enabled from Settings would silently break on the very
# next OS update.
#
# The daemon (/usr/local/sbin/hifi-bt-watcher.py) and the aplay wrapper
# (/usr/local/sbin/hifi-bt-aplay-run) are delivered by the *system* OTA
# channel (same as hifi-room-measure.py / hifi-rip-cd.py) — this migration
# only sets up packages, units, and enable/disable state.
#
# Idempotent: packages via ensure_pkg, units via ensure_file_content, and the
# reconciliation step only touches systemd state when the persisted choice
# actually differs from what's currently applied. Non-fatal: an offline device
# just keeps the toggle "unavailable" until the packages land on a later run.

ensure_pkg bluez || true
ensure_pkg bluez-tools || true
ensure_pkg bluez-alsa-utils || true

# ── Neutralise Debian's own auto-enabled units ───────────────────────
# The bluez-alsa-utils package enables bluealsa.service/bluealsa-aplay.service
# on install. We ship our own hifi-bluealsa/hifi-bt-aplay units instead (so
# aplay's target device can be resolved dynamically at start — see
# hifi-bt-aplay-run) — disable Debian's so they never fight ours for the
# Bluetooth adapter or the DAC.
for u in bluealsa.service bluealsa-aplay.service; do
    state=$(systemctl is-enabled "$u" 2>/dev/null) || state=""
    if [ -n "$state" ] && [ "$state" != "disabled" ] && [ "$state" != "masked" ]; then
        systemctl disable --now "$u" >/dev/null 2>&1 && mark_changed "disabled stock $u"
    fi
done

# Resolve the bluealsa daemon binary name (renamed bluealsa -> bluealsad in
# newer bluez-alsa releases; Debian 12 bookworm ships "bluealsa").
BLUEALSA_BIN=$(command -v bluealsad || command -v bluealsa || echo /usr/bin/bluealsa)

# ── Units (installed disabled; the toggle in Settings enables them) ──
ensure_file_content /etc/systemd/system/hifi-bluealsa.service 644 root:root <<EOF
[Unit]
Description=HiFi Player - BlueALSA (Bluetooth A2DP sink)
After=dbus.service bluetooth.service
Requires=dbus.service

[Service]
Type=simple
ExecStart=$BLUEALSA_BIN -p a2dp-sink
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

ensure_file_content /etc/systemd/system/hifi-bt-agent.service 644 root:root <<'EOF'
[Unit]
Description=HiFi Player - Bluetooth pairing agent (no PIN, headless)
After=bluetooth.service
Requires=bluetooth.service

[Service]
Type=simple
ExecStart=/usr/bin/bt-agent -c NoInputNoOutput
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

ensure_file_content /etc/systemd/system/hifi-bt-aplay.service 644 root:root <<'EOF'
[Unit]
Description=HiFi Player - Bluetooth A2DP playback (phone -> DAC)
After=hifi-bluealsa.service
Requires=hifi-bluealsa.service

[Service]
Type=simple
ExecStart=/usr/local/sbin/hifi-bt-aplay-run
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

ensure_file_content /etc/systemd/system/hifi-bt-watcher.service 644 root:root <<'EOF'
[Unit]
Description=HiFi Player - Bluetooth DAC handover + Now Playing metadata
After=bluetooth.service hifi-bluealsa.service

[Service]
Type=simple
ExecStart=/usr/local/sbin/hifi-bt-watcher.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

if migration_changed; then
    systemctl daemon-reload 2>/dev/null || true
fi

# ── Reconcile against the user's persisted choice ────────────────────
# Mirrors the exact modprobe.d content 0009 writes (blacklist variant) so
# ensure_file_content never churns between the two migrations when Bluetooth
# is OFF (the common case).
BT_STATE_FILE=/etc/hifi-player/bluetooth.json
BT_ENABLED=0
if [ -f "$BT_STATE_FILE" ] && grep -q '"enabled"[[:space:]]*:[[:space:]]*true' "$BT_STATE_FILE" 2>/dev/null; then
    BT_ENABLED=1
fi

if [ "$BT_ENABLED" = 1 ]; then
    ensure_file_content /etc/modprobe.d/hifi-no-bluetooth.conf 644 root:root <<'EOF'
# Bluetooth is enabled (Settings -> Bluetooth) on this device.
EOF
    modprobe btusb 2>/dev/null || true
    modprobe bluetooth 2>/dev/null || true
    systemctl unmask bluetooth.service >/dev/null 2>&1 || true
    for u in bluetooth.service hifi-bluealsa.service hifi-bt-agent.service hifi-bt-aplay.service hifi-bt-watcher.service; do
        state=$(systemctl is-enabled "$u" 2>/dev/null) || state=""
        if [ "$state" != "enabled" ]; then
            systemctl enable --now "$u" >/dev/null 2>&1 && mark_changed "enabled $u (bluetooth on)"
        fi
    done
fi
# BT_ENABLED=0: nothing to do here — 0009 already wrote the blacklist variant
# and masked bluetooth.service for this run.
