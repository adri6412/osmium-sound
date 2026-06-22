# shellcheck shell=sh
# 0002 — Security hardening (idempotent, NO reboot — takes effect live).
#
# These changes are baked into new ISOs at build time; this migration carries the
# same hardening to devices that were already installed. Every step is a clean
# no-op once applied and none request a reboot.

# 1) Drop the kiosk user from the 'sudo' group. The appliance only needs the
#    specific NOPASSWD commands in /etc/sudoers.d/hifi; full 'sudo' membership
#    would turn the well-known default password into trivial full-root.
if id -nG hifi 2>/dev/null | tr ' ' '\n' | grep -qx sudo; then
    gpasswd -d hifi sudo >/dev/null 2>&1 || deluser hifi sudo >/dev/null 2>&1 || true
    mark_changed "removed 'hifi' from sudo group"
fi

# 2) Pin the apt sudoers rule: `apt-get upgrade *` allows `-o DPkg::Pre-Invoke=…`
#    (arbitrary root command execution). Replace the wildcard with the exact
#    invocation the API actually uses. backup_and_edit validates with visudo and
#    reverts on failure, so a bad edit can never lock sudo out.
SUDOERS=/etc/sudoers.d/hifi
if [ -f "$SUDOERS" ] && grep -q 'apt-get upgrade \*' "$SUDOERS"; then
    if backup_and_edit "$SUDOERS" "visudo -cf" \
            's#/usr/bin/apt-get upgrade \*#/usr/bin/apt-get upgrade -y#'; then
        log_info "pinned apt-get sudoers rule"
    fi
fi

# 3) Enable automatic Debian security updates (security archive only, no auto
#    reboot — the box may be mid-playback).
UNATT=/etc/apt/apt.conf.d/52hifi-unattended
ensure_file_content "$UNATT" 644 <<'EOF'
// HiFi Player appliance — automatic security updates (security archive only,
// no automatic reboot). Managed by the OS-update channel.
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
Unattended-Upgrade::Origins-Pattern {
        "origin=Debian,codename=${distro_codename}-security,label=Debian-Security";
};
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
EOF
ensure_pkg unattended-upgrades || true
