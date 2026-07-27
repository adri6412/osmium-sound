# shellcheck shell=sh
# 0027 — Quiesce audio before ANY shutdown/reboot (DesignWare DMA panic
# workaround), hooked into systemd's shutdown.target instead of relying on
# every reboot-triggering call site to remember to do it.
#
# Real device logs (persistent journal, `last -x`) confirmed 9 ungraceful
# reboots over one week, all with the exact same signature: the appliance was
# actively serving HTTP requests every few seconds right up to the last
# logged instant, then died with zero warning — no thermal/MCE messages, no
# watchdog-timeout pattern (would require ~30s of prior unresponsiveness,
# which never appears), and squeezelite.service running (CamillaDSP OFF in
# every case checked) at the time. This matches the already-known kernel
# panic in the DesignWare DMA driver (dw_dmac_core: dw_shutdown ->
# do_dw_dma_disable) hit when device_shutdown() races an active DMA-driven
# audio stream — except it turns out NOT to be DSP-specific as originally
# documented, and NOT limited to shutdown/reboot requests that happen to run
# through api_server.py or the OS-update script (the only two places that
# already quiesce audio first). `sudo reboot`/`sudo shutdown` at a shell
# (hifi's sudoers grants these NOPASSWD), `systemctl reboot`, and this
# appliance's own factory-reset script all bypassed both existing mitigations
# entirely.
#
# The systemd-unit approach fixes the "reboot about to happen" half of that
# gap unconditionally, for every trigger, without patching each call site.
# The OTHER half — a fully spontaneous panic during normal, sustained
# playback with no reboot ever requested — cannot be mitigated this way (there
# is no "about to shut down" moment to hook); that needs an upstream kernel
# fix. This migration does not attempt that.
#
# Idempotent: ensure_file_content is a no-op once applied; the unit is only
# enabled when not already enabled. Never reboots.

ensure_file_content /usr/local/sbin/hifi-quiesce-audio-shutdown.sh 755 root:root <<'EOF'
#!/bin/sh
# shellcheck shell=sh
# See distro/os-update/apply.d/0027-quiesce-audio-shutdown.sh for the full
# rationale. Stops the audio-DMA-driving services and gives the hardware a
# moment to go idle before ANY shutdown/reboot proceeds.
set -eu

if [ "$(systemctl is-active camilladsp.service 2>/dev/null)" = "active" ] \
        || [ "$(systemctl is-active squeezelite.service 2>/dev/null)" = "active" ]; then
    systemctl stop camilladsp.service squeezelite.service 2>/dev/null || true
    sleep 2
fi
exit 0
EOF

ensure_file_content /etc/systemd/system/hifi-quiesce-audio-shutdown.service 644 root:root <<'EOF'
[Unit]
Description=HiFi Player - quiesce audio DMA before shutdown/reboot (DesignWare DMA panic workaround)
DefaultDependencies=no
Before=shutdown.target
Conflicts=shutdown.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/hifi-quiesce-audio-shutdown.sh
TimeoutStartSec=15

[Install]
WantedBy=shutdown.target
EOF

if migration_changed; then
    systemctl daemon-reload 2>/dev/null || true
fi

state=$(systemctl is-enabled hifi-quiesce-audio-shutdown.service 2>/dev/null) || state=""
if [ "$state" != "enabled" ]; then
    if systemctl enable hifi-quiesce-audio-shutdown.service >/dev/null 2>&1; then
        mark_changed "enabled hifi-quiesce-audio-shutdown.service"
    fi
fi
