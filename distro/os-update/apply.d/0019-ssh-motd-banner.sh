# shellcheck shell=sh
# 0019 — Osmium Sound ASCII banner on SSH login.
#
# Writes /etc/motd, printed by pam_motd on interactive SSH logins (SSH is
# opt-in via Settings → SSH access, see 0017). Baked into new ISOs at build
# time (distro/config/includes.chroot/etc/motd — keep the two files
# byte-identical); this migration carries the same banner to devices that were
# already installed. Takes effect on the next login — no reboot, no reload.
ensure_file_content /etc/motd 644 <<'EOF'

  ___   ___  __  __  ___  _   _  __  __     ___   ___   _   _  _  _  ___
 / _ \ / __||  \/  ||_ _|| | | ||  \/  |   / __| / _ \ | | | || \| ||   \
| (_) |\__ \| |\/| | | | | |_| || |\/| |   \__ \| (_) || |_| || .` || |) |
 \___/ |___/|_|  |_||___| \___/ |_|  |_|   |___/ \___/  \___/ |_|\_||___/

                     Osmium Sound - network audio streamer

EOF
