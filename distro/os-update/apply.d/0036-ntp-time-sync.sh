# shellcheck shell=sh
# 0036 — NTP time sync (systemd-timesyncd) for already-installed units.
#
# Confirmed live on a fielded device: `systemctl status systemd-timesyncd`
# returned "Unit systemd-timesyncd.service could not be found" — on Debian 12
# it is a separate package, NOT bundled into systemd/systemd-sysv, so no
# device in the field has ever had any time sync running (`timedatectl status`
# showed "System clock synchronized: no, NTP service: n/a" everywhere). A unit
# built from old/refurbished hardware with a dead CMOS battery has no other way
# to correct its clock, and OTA/TLS signature checks depend on a roughly
# correct clock. 0400-enable-services.hook.chroot now installs + enables this
# on every fresh image; this migration is the fleet-wide catch-up for units
# that already exist.
#
# Idempotent: ensure_pkg no-ops once installed, the enable check only touches
# systemctl when the unit isn't already enabled.

ensure_pkg systemd-timesyncd || true

if systemctl list-unit-files systemd-timesyncd.service >/dev/null 2>&1; then
    state=$(systemctl is-enabled systemd-timesyncd.service 2>/dev/null) || state=""
    if [ "$state" != "enabled" ]; then
        systemctl enable --now systemd-timesyncd.service >/dev/null 2>&1 && mark_changed "enabled systemd-timesyncd.service"
    fi
fi
