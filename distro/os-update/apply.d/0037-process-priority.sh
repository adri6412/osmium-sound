# shellcheck shell=sh
# 0037 — Process priority: squeezelite first, kiosk UI second.
#
# User-reported symptom: the Electron kiosk UI's own open/close animations
# (the VU-meter page in particular) sometimes felt sluggish to complete —
# traced to background system work (OTA/log/samba/etc.) competing for CPU/IO
# with no priority differentiation. squeezelite already has the strictest
# real-time requirement (an audio underrun is audible; a slow window
# animation is merely annoying), so it gets first priority; the kiosk UI gets
# second.
#
# squeezelite.service: adds Nice=-10 (CPU) + IOSchedulingClass=realtime,
# IOSchedulingPriority=0 (disk I/O ahead of everything else). CPU niceness
# rather than a realtime/RR CPU policy — avoids the risk of a runaway
# squeezelite process starving the whole system (including sshd/watchdog) if
# it ever spins, which a hard RT CPU policy would allow.
#
# Kiosk UI: /etc/security/limits.d/10-hifi-kiosk-nice.conf raises the "hifi"
# user's PAM nice ceiling to -5 so the xsession script (already redeployed by
# 0001-selfhealing-xsession.sh from the same canonical
# distro/os-update/files/xsession this OTA ships) can `nice -n -5` the
# Electron process. Below squeezelite's -10, above the system default of 0.
#
# Idempotent: ensure_file_content is a no-op once applied. squeezelite.service
# is only restarted (brief audio interruption, same as a DAC switch) when its
# unit file actually changed AND the service is currently active; the PAM
# limit only needs a new login session, which is already covered by
# 0001-selfhealing-xsession.sh's request_reboot when the xsession content
# changes in the same release.

ensure_file_content /etc/systemd/system/squeezelite.service 644 root:root <<'EOF'
[Unit]
# Native systemd unit for squeezelite on the HiFi Player appliance.
#
# The Debian `squeezelite` package only ships a SysV init script
# (/etc/init.d/squeezelite); enabling that during the live-build chroot does
# not create a persistent autostart, so squeezelite did not come up on a fresh
# install. This native unit (shadowing the sysv-generated one) is enabled with a
# real wants-symlink by hook 0400 and starts reliably at boot.
#
# Arguments come from /etc/default/squeezelite (ARGS=...), so the UI's DAC
# selection (api_server.py set_audio_device, which rewrites ARGS and restarts
# this service) keeps working. DO NOT hardcode the output device here.
Description=Squeezelite Audio Player (HiFi Player)
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=-/etc/default/squeezelite
ExecStart=/usr/bin/squeezelite $ARGS
Restart=always
RestartSec=5

# Highest scheduling priority on the box: squeezelite feeds the DAC directly,
# so an underrun is audible in a way a dropped UI frame never is. CPU niceness
# (not realtime/RR) to avoid starving other processes if it ever spins; realtime
# I/O class so buffer reads never queue behind UI/log/update disk traffic.
Nice=-10
IOSchedulingClass=realtime
IOSchedulingPriority=0

[Install]
WantedBy=multi-user.target
EOF

if migration_changed; then
    systemctl daemon-reload 2>/dev/null || true
    if [ "$(systemctl is-active squeezelite.service 2>/dev/null)" = "active" ]; then
        systemctl restart squeezelite.service 2>/dev/null || true
    fi
fi

ensure_file_content /etc/security/limits.d/10-hifi-kiosk-nice.conf 644 root:root <<'EOF'
# HiFi Player appliance — let the kiosk session (user "hifi") raise the
# Electron UI's own priority above the system default so its window/animation
# open-close is not starved by background work (updates, logging, samba,
# etc). Ceiling only, not a default: the xsession script (see
# distro/os-update/files/xsession) is what actually applies `nice -n -5`.
# Kept below squeezelite.service's Nice=-10 (audio underruns are worse than a
# slow window animation), so it deliberately does NOT grant -10 or lower.
hifi    -    nice    -5
EOF
