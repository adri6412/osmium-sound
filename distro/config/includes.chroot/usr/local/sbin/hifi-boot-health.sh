#!/bin/sh
# Osmium Sound — dichiara "buono" l'avvio corrente (rauc status mark-good).
#
# Criterio: "la via degli aggiornamenti funziona di nuovo" — /data montata
# (sugli slot immagine), l'API locale risponde, RAUC vede la configurazione.
# Di proposito NON dipende da squeezelite o dall'interfaccia: un DAC staccato
# o uno schermo spento non devono far tornare all'altro slot.
#
# 🚨 It never gives up. It used to exit with an error after 300 s, and one
# slow boot (a disk check, the first boot of an image doing its migrations)
# was then enough for the watchdog to send the device back to the other,
# older image for good. Whether a boot that is late gets abandoned is the
# watchdog's call (hifi-boot-watchdog.sh), and it does not abandon an image
# that has already been good once: this keeps trying until it gets there,
# saying so in the log every now and then.
#
# Once the boot is good it also records the image's identity in the grubenv
# (<slot>_GOOD, <slot>_LEFT): that is what tells the selector and the
# watchdog that this image is proven. See grub-selector.cfg.tmpl.
set -u
# shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-ab-lib.sh
# shellcheck disable=SC1091  # percorso assoluto, esiste solo sull'apparecchio
. "${HIFI_AB_LIB:-/usr/local/sbin/hifi-ab-lib.sh}"   # HIFI_AB_LIB: tests only

GOOD_FLAG="${HIFI_BOOT_GOOD_FLAG:-/run/hifi-boot-good}"
PEEK_DIR="${HIFI_AB_PEEK_DIR:-/run/hifi-ab-peek}"
API_URL="${HIFI_BOOT_HEALTH_URL:-http://127.0.0.1:8000/ota_channel}"

# The device of the slot with this bootname, from RAUC's own configuration.
slot_device() {
    awk -v b="$1" '/^\[/ { d = ""; n = "" }
        /^device=/ { d = substr($0, 8) } /^bootname=/ { n = substr($0, 10) }
        d != "" && n == b { print d; exit }' "$AB_RAUC_CONF" 2>/dev/null
}

# This image, good now, is proven: the selector may give it another attempt
# after a bad boot, and the watchdog will not reboot it away from a slow one.
record_proof() {
    _slot=$(ab_booted_slot 2>/dev/null) || return 0
    _id=$(ab_image_id)
    [ -n "$_id" ] || return 0
    [ -w "$AB_GRUBENV" ] || return 0
    if [ "$(ab_env_get "${_slot}_GOOD")" != "$_id" ] \
       || [ "$(ab_env_get "${_slot}_LEFT")" != "$AB_PROVEN_ATTEMPTS" ]; then
        grub-editenv "$AB_GRUBENV" set "${_slot}_GOOD=$_id" "${_slot}_LEFT=$AB_PROVEN_ATTEMPTS" \
            || ab_warn "could not record image $_id as proven in $AB_GRUBENV"
    fi
}

# Running on the fallback: the other slot is RAUC's primary (first in ORDER)
# and its last boot never reached "good". If it holds the very image that was
# proven good before — read from the slot itself, so a newly installed image
# never qualifies — it gets another try at the next boot, out of the same
# attempts the selector counts. Without this, one bad boot of a proven image
# (a power cut while it started) left the device on the older image until
# the next update, without a word. A selector of version 1, which every A/B
# device installed before version 2 still has, depends on this alone.
rearm_other() {
    _slot=$(ab_booted_slot 2>/dev/null) || return 0
    case "$_slot" in A) _o=B ;; B) _o=A ;; *) return 0 ;; esac
    [ -w "$AB_GRUBENV" ] || return 0
    _order=$(ab_env_get ORDER)
    [ "${_order%% *}" = "$_o" ] || return 0
    [ "$(ab_env_get "${_o}_OK")" = 1 ] && [ "$(ab_env_get "${_o}_TRY")" = 1 ] || return 0
    _good=$(ab_env_get "${_o}_GOOD")
    [ -n "$_good" ] || return 0
    _left=$(ab_env_get "${_o}_LEFT")
    case "$_left" in
        1|2|3) ;;
        *) ab_warn "running on fallback slot $_slot: slot $_o failed to come up with its attempts used up; staying here until the next update"
           return 0 ;;
    esac
    _dev=$(slot_device "$_o")
    [ -n "$_dev" ] || return 0
    mkdir -p "$PEEK_DIR" 2>/dev/null || return 0
    mount -t squashfs -o ro "$_dev" "$PEEK_DIR" 2>/dev/null || return 0
    _oid=$(ab_image_id "$PEEK_DIR")
    umount "$PEEK_DIR" 2>/dev/null || true
    if [ -z "$_oid" ] || [ "$_oid" != "$_good" ]; then
        return 0
    fi
    _left=$(( _left - 1 ))
    if grub-editenv "$AB_GRUBENV" set "${_o}_TRY=0" "${_o}_LEFT=$_left"; then
        ab_warn "running on fallback slot $_slot: slot $_o holds $_good, proven good before, whose last boot did not come up; it gets another try at the next boot ($_left left after it)"
    fi
}

[ -f "$AB_RAUC_CONF" ] || exit 0
WARN_AFTER="${HIFI_BOOT_HEALTH_TIMEOUT:-300}"
started=$(date +%s)
next_warn=$(( started + WARN_AFTER ))
while :; do
    ok=1
    if ab_is_image && ! mountpoint -q "$AB_DATA_MNT"; then ok=0; fi
    curl -fsS -m 3 "$API_URL" >/dev/null 2>&1 || ok=0
    rauc status >/dev/null 2>&1 || ok=0
    [ "$ok" = 1 ] && break
    now=$(date +%s)
    if [ "$now" -ge "$next_warn" ]; then
        ab_warn "boot not good yet after $(( now - started ))s (data=$(mountpoint -q "$AB_DATA_MNT" && echo ok || echo no), api=$(curl -fsS -m 3 "$API_URL" >/dev/null 2>&1 && echo ok || echo no), rauc=$(rauc status >/dev/null 2>&1 && echo ok || echo no)); still trying"
        next_warn=$(( now + 600 ))
    fi
    # 🚨 1, not 5. hifi-api.service is Type=simple, so systemd calls it started
    # the moment it execs, not when Flask is listening — the wait happens here
    # either way. With sleep 5 that wait was rounded up to the next turn of the
    # loop: 14.7 s measured on an appliance whose API was ready well before.
    # What a turn costs is the curl -m 3 above, not this pause.
    sleep 1
done
# /data on tmpfs: the initramfs could not mount the data partition, so this
# boot is running on the image's factory /etc and everything written during it
# is lost at the next one. The other slot would not fix a data partition, so
# the boot is still marked good rather than rolled back — but it must not pass
# silently, because from the outside it just looks like settings that "went
# back on their own".
if [ "$(cat /run/hifi-state/data-mounted 2>/dev/null)" = "0" ]; then
    ab_warn "data partition not mounted: /data is a tmpfs, this boot runs on factory settings and any change made now will be lost"
fi
if rauc status mark-good >/dev/null 2>&1; then
    : > "$GOOD_FLAG"
    ab_log "avvio dichiarato buono (slot $(ab_booted_slot 2>/dev/null || echo legacy))"
    # Both best-effort: the boot is good whatever they manage to write.
    ab_mount_esp 2>/dev/null || true
    record_proof || true
    rearm_other || true
    exit 0
fi
ab_warn "rauc status mark-good fallito"
exit 1
