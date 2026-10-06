#!/bin/sh
# Osmium Sound — safety net for the first boot of a newly installed image.
#
# Started by its timer 10 minutes after boot. If the boot has not been marked
# good (hifi-boot-health.sh) it reboots, and the GRUB selector, seeing the
# slot's attempt used up (<slot>_TRY=1), boots the other slot: that is how a
# broken new image goes back to the one that worked.
#
# 🚨 Only for an image that has never been good. With RAUC's GRUB scheme
# EVERY boot is a trial (the selector sets TRY=1 each time, mark-good clears
# it), so the old rule — "TRY=1 and not good after 10 min: reboot" — sent a
# device that had been running an image fine for months back to the older
# one over a single slow boot, and left it there until the next update. An
# image that was marked good before (its id in <slot>_GOOD, written by
# hifi-boot-health.sh) is never rebooted from here: the health check goes on
# trying, and whatever is slow is not something the older image would fix.
#
# And not while the boot is still visibly busy: a first boot doing its
# migrations, or a long disk check, has systemd jobs still running. The wait
# is bounded (CAP seconds after boot), so a unit that hangs for ever still
# ends in the fallback.
set -u
# shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-ab-lib.sh
# shellcheck disable=SC1091  # percorso assoluto, esiste solo sull'apparecchio
. "${HIFI_AB_LIB:-/usr/local/sbin/hifi-ab-lib.sh}"   # HIFI_AB_LIB: tests only

GOOD_FLAG="${HIFI_BOOT_GOOD_FLAG:-/run/hifi-boot-good}"
UPTIME_FILE="${HIFI_UPTIME_FILE:-/proc/uptime}"
CAP="${HIFI_BOOT_WATCHDOG_CAP:-1800}"
POLL="${HIFI_BOOT_WATCHDOG_POLL:-30}"

# systemd still has start-up work queued or running, other than the health
# check and this watchdog themselves.
boot_busy() {
    systemctl list-jobs --no-legend --plain 2>/dev/null \
        | awk '$2 != "hifi-boot-health.service" && $2 != "hifi-boot-watchdog.service" { n++ } END { exit !n }'
}

uptime_s() { cut -d. -f1 "$UPTIME_FILE" 2>/dev/null || echo 0; }

[ -f "$GOOD_FLAG" ] && exit 0
[ -f "$AB_RAUC_CONF" ] || exit 0
slot=$(ab_booted_slot) || exit 0
ab_mount_esp 2>/dev/null || exit 0
[ -r "$AB_GRUBENV" ] || exit 0

said=""
while :; do
    [ -f "$GOOD_FLAG" ] && exit 0
    [ "$(ab_env_get "${slot}_TRY")" = 1 ] || exit 0
    # shellcheck disable=SC2119  # the root argument is optional
    id=$(ab_image_id)
    if [ -n "$id" ] && [ "$(ab_env_get "${slot}_GOOD")" = "$id" ]; then
        ab_warn "slot $slot ($id) not marked good yet, but this image has been good before: not falling back over a slow boot"
        exit 0
    fi
    up=$(uptime_s)
    case "$up" in ''|*[!0-9]*) up=0 ;; esac
    if [ "$up" -lt "$CAP" ] && boot_busy; then
        if [ -z "$said" ]; then
            ab_warn "first boot of slot $slot not marked good yet and still starting up: waiting (at most until ${CAP}s after boot)"
            said=1
        fi
        sleep "$POLL"
        continue
    fi
    break
done
ab_warn "slot $slot on trial and not marked good: rebooting so that the selector picks the other slot"
sync
systemctl reboot
exit 0
