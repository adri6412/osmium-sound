# shellcheck shell=sh
# 0018 — Install Samba and seed the base configuration for internal music shares.
#
# The appliance can expose internal music disks over SMB so users can copy music
# from a PC. sources_server.py writes the per-disk share definitions to
# /etc/samba/hifi-shares.conf and reloads smbd. This migration only installs the
# package and the static base config once.

ensure_pkg samba || true
ensure_pkg exfatprogs || true

UNIT=/etc/samba/smb.conf
ensure_file_content "$UNIT" 644 root:root <<'EOF'
# HiFi Player — Samba configuration.
# Shares are added dynamically by sources_server.py via the included file
# /etc/samba/hifi-shares.conf. Do not edit by hand.

[global]
   workgroup = WORKGROUP
   server string = Osmium Sound
   server role = standalone server
   map to guest = never
   security = user
   passdb backend = tdbsam
   obey pam restrictions = yes
   unix password sync = no
   pam password change = no
   usershare allow guests = no
   load printers = no
   printing = bsd
   printcap name = /dev/null
   disable spoolss = yes
   log file = /var/log/samba/log.%m
   max log size = 1000
   socket options = TCP_NODELAY IPTOS_LOWDELAY
   min protocol = SMB2
   vfs objects = recycle
   recycle:repository = .recycle
   recycle:keeptree = yes
   recycle:versions = yes

include = /etc/samba/hifi-shares.conf
EOF

SHARES=/etc/samba/hifi-shares.conf
if [ ! -f "$SHARES" ]; then
    : > "$SHARES"
    chmod 644 "$SHARES"
    chown root:root "$SHARES"
    mark_changed "created $SHARES"
fi

if migration_changed; then
    systemctl daemon-reload 2>/dev/null || true
fi
