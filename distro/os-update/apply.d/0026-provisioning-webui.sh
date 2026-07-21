# shellcheck shell=sh
# 0026 — Provisioning hotspot prerequisites + web-admin service enable.
#
# Companion to 0025 (display-mode). Ships the fleet-wide prerequisites for the
# first-boot hotspot/captive flow and the web-admin gateway (webui_server.py):
#   * dnsmasq-base — required by NetworkManager's ipv4.method=shared (the setup
#     hotspot). Absent by default because the image is built --apt-recommends
#     false.
#   * the captive-portal dnsmasq drop-in — inert on every configured unit (NM
#     only feeds it to a shared-mode connection, which a normal unit never has),
#     so shipping it fleet-wide is safe.
#   * enable hifi-webui.service so the whole fleet gains the web-admin UI.
#
# The daemon (webui_server.py) + its unit are delivered by the *system* OTA
# channel; this migration only sets up packages, the captive conf, and the
# enable state. If the unit file has not landed yet (system bundle applied after
# this OS bundle), the enable is a guarded no-op and takes effect on the next
# update run — the OS payload is cumulative.
#
# FLEET SAFETY: this migration must NEVER create /etc/hifi-player/provisioning-
# pending. That marker is the fresh-install-only signal that puts the box into
# hotspot/captive setup mode; it is created ONLY by the ISO build and by
# hifi-factory-reset.sh (an explicit user action). Creating it here would drop
# every configured unit in the fleet into setup mode on an OS update.
#
# Idempotent: ensure_pkg / ensure_file_content are no-ops once applied; the
# service enable only acts when the unit exists and is not already enabled.
# Never reboots.

ensure_pkg dnsmasq-base || true

mkdir -p /etc/NetworkManager/dnsmasq-shared.d 2>/dev/null || true
ensure_file_content /etc/NetworkManager/dnsmasq-shared.d/hifi-captive.conf 644 root:root <<'EOF'
# HiFi Player — captive-portal DNS for the setup hotspot.
# NetworkManager feeds this ONLY to the dnsmasq spawned for an ipv4.method=shared
# connection (the Osmium-Setup hotspot); inert on every normal unit. Resolve all
# names to the appliance so a joining phone's connectivity check is answered by
# webui_server.py, triggering the captive-portal auto-popup.
address=/#/10.42.0.1
EOF

# Enable the web-admin service (guarded so CI / an early OS bundle stays a
# clean no-op when the unit file has not been shipped yet).
WEBUI_UNIT=/etc/systemd/system/hifi-webui.service
if [ -f "$WEBUI_UNIT" ]; then
    state=$(systemctl is-enabled hifi-webui.service 2>/dev/null) || state=""
    if [ "$state" != "enabled" ]; then
        systemctl daemon-reload 2>/dev/null || true
        if systemctl enable hifi-webui.service >/dev/null 2>&1; then
            mark_changed "enabled hifi-webui.service"
        fi
    fi
fi
