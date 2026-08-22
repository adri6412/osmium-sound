# shellcheck shell=sh
# 0031 — Boot speed: drop nmbd + samba-ad-dc, stop apt-daily-upgrade racing boot.
#
# Measured live on an x86 mini-PC with `systemd-analyze critical-chain
# graphical.target`: smbd.service is ordered after nmbd.service, and nmbd sits
# idle for ~9s waiting for DHCP to hand out an address before it can bind
# ("No local IPv4 non-loopback interfaces available, waiting for interface...").
# That single unit was ~64% of the entire userspace boot time. nmbd only serves
# legacy NetBIOS name resolution/browsing; SMB2/3 file sharing (smbd) doesn't
# need it, and \\hifiplayer.local already resolves via avahi/mDNS. Masking it
# removes the wait; the running smb.conf already pins `min protocol = SMB2`
# (see 0018-samba-internal-shares.sh), so nothing here relied on NetBIOS.
#
# samba-ad-dc.service isn't on the critical path (it self-skips via an
# exec-condition, since smb.conf has `server role = standalone server`), but it
# still spins up and fails that check on every boot — pure waste, and never
# applicable on this appliance.
#
# apt-daily-upgrade.timer has Persistent=true: if the box was off at its 06:00
# slot (normal for an appliance that gets powered on/off), it fires immediately
# on the next boot instead of waiting for the next scheduled time, competing
# for CPU/network/disk right in the boot window. Persistent=false just skips a
# missed run instead of catching it up at boot.
#
# No reboot requested — service masks and the timer drop-in take effect
# immediately / at the next boot without one.

mask_unit() {
    u="$1"
    command -v systemctl >/dev/null 2>&1 || return 0
    state=$(systemctl is-enabled "$u" 2>/dev/null) || state=""
    [ -n "$state" ] || return 0           # unknown / absent / unreachable → leave
    [ "$state" = "masked" ] && return 0   # already masked → no-op
    if systemctl mask --now "$u" >/dev/null 2>&1; then
        mark_changed "masked $u"
    fi
}

mask_unit nmbd.service
mask_unit samba-ad-dc.service

mkdir -p /etc/systemd/system/apt-daily-upgrade.timer.d 2>/dev/null || true
ensure_file_content /etc/systemd/system/apt-daily-upgrade.timer.d/hifi-no-boot-catchup.conf 644 root:root <<'EOF'
[Timer]
Persistent=false
EOF

if migration_changed; then
    systemctl daemon-reload 2>/dev/null || true
fi
