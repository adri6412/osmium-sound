# shellcheck shell=sh
# 0017 — Disable SSH root login (idempotent, NO reboot — takes effect live).
#
# SSH ships disabled by default and is opt-in via Settings → SSH access. The
# appliance's kiosk account ('hifi') has a well-known default password, so if
# a user enables SSH, root must never be reachable over the network with it —
# only the unprivileged 'hifi' account. Baked into new ISOs at build time
# (distro/config/includes.chroot/etc/ssh/sshd_config.d/); this migration
# carries the same hardening to devices that were already installed. Written
# unconditionally (harmless if sshd is never installed/enabled) so it's
# already in place the moment SSH is turned on.
DROPIN=/etc/ssh/sshd_config.d/99-hifi-no-root-login.conf
ensure_file_content "$DROPIN" 644 <<'EOF'
# Managed by HiFi Player — do not edit by hand (overwritten on update).
PermitRootLogin no
EOF

if migration_changed; then
    for unit in ssh.service sshd.service; do
        if systemctl is-active --quiet "$unit" 2>/dev/null; then
            systemctl reload "$unit" 2>/dev/null || systemctl restart "$unit" 2>/dev/null || true
        fi
    done
fi
