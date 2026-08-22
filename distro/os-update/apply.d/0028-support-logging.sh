# shellcheck shell=sh
# 0028 — Persistent, rotated logging for the support-bundle feature.
#
# Ships the fleet-wide prerequisites for /var/log/hifi/ (written by the Python
# daemons via hifi_logging.py and by the shell helper hifi-log.sh — both land
# in the System channel, not here) and for a persistent journald, so history
# survives a reboot instead of vanishing:
#   * /var/log/hifi/ — 0750 root:root (SSID/hostname can show up in these logs,
#     so keep it off world-readable).
#   * logrotate package + /etc/logrotate.d/hifi — rotates the plain-appended
#     shell-script logs (the Python daemons' own logs already self-rotate via
#     RotatingFileHandler; see the comment in that file for why they're NOT
#     listed here too).
#   * /var/log/journal/ — makes journald persistent (Debian defaults to
#     volatile-unless-this-dir-exists), so `journalctl` history for native
#     units (squeezelite, bluetooth, NetworkManager, ...) also survives.
#
# Idempotent: ensure_pkg / ensure_file_content are no-ops once applied; mkdir/
# chmod/chown/tmpfiles are unconditional but harmless no-ops on a re-run.
# Never reboots — all of this takes effect immediately/on next log write.

mkdir -p /var/log/hifi 2>/dev/null || true
chmod 0750 /var/log/hifi 2>/dev/null || true
chown root:root /var/log/hifi 2>/dev/null || true

ensure_pkg logrotate || true

ensure_file_content /etc/logrotate.d/hifi 644 root:root <<'EOF'
# Rotates the plain-appended logs written by the shell helper hifi-log.sh
# (distro/config/includes.chroot/usr/local/sbin/hifi-log.sh) and the persisted
# hifi-os-update.sh apply.log. Listed explicitly rather than /var/log/hifi/*.log
# — the Python daemons' logs in the same directory (webui.log, api.log, ...)
# already self-rotate via logging.handlers.RotatingFileHandler and must NOT
# also be truncated from underneath by logrotate.
/var/log/hifi/hifi-factory-reset.log
/var/log/hifi/hifi-format-disk.log
/var/log/hifi/hifi-lyrion-update.log
/var/log/hifi/hifi-ota-update.log
/var/log/hifi/hifi-system-update.log
/var/log/hifi/os-update.log
{
    daily
    rotate 5
    maxsize 2M
    compress
    missingok
    notifempty
    copytruncate
}
EOF

mkdir -p /var/log/journal
systemd-tmpfiles --create --prefix /var/log/journal 2>/dev/null || true
