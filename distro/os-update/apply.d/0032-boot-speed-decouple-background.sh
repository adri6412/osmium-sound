# shellcheck shell=sh
# 0032 — Boot speed: stop background services from gating "boot complete".
#
# Measured live via `systemd-analyze critical-chain graphical.target`: after
# 0031 removed nmbd, smbd.service itself became the sole blocker (+3.222s) on
# the path graphical.target ← multi-user.target ← smbd.service. The root cause
# is systemd's own default: a unit pulled in via WantedBy=multi-user.target
# gets an implicit `Before=multi-user.target`, so the target (and graphical.
# target, which Requires it) isn't "reached" until every such unit has started
# — even ones the kiosk UI never actually waits on in practice (file sharing,
# the owner's own Tailscale tailnet, SSH).
#
# This is the same pattern commercial appliances use: the UI comes up as soon
# as its own real prerequisites (display, network) are ready; slower
# non-essential services keep starting in parallel, in the background.
#
# DefaultDependencies=no strips systemd's automatic Before=multi-user.target/
# shutdown.target + After=basic.target for that unit, so we restate the
# specific ordering each one still genuinely needs (so it doesn't try to bind
# before dbus/network exist) without the "block boot" side effect. Trade-off:
# these three lose systemd's automatic clean-shutdown ordering guarantee —
# acceptable here (no unflushed critical state on shutdown for file sharing,
# a VPN tunnel, or SSH).
#
# No reboot requested — takes effect at the next boot, nothing is touched on
# the running system.

decouple() {
    _dc_unit="$1"; shift
    _dc_dir="/etc/systemd/system/${_dc_unit}.d"
    mkdir -p "$_dc_dir" 2>/dev/null || true
    ensure_file_content "$_dc_dir/hifi-no-boot-block.conf" 644 root:root <<EOF
[Unit]
DefaultDependencies=no
After=$*
EOF
}

decouple smbd.service basic.target network-online.target
decouple tailscaled.service basic.target network-online.target
decouple ssh.service basic.target network.target

if migration_changed; then
    systemctl daemon-reload 2>/dev/null || true
fi
