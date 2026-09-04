#!/bin/sh
# Osmium Sound — dichiara "buono" l'avvio corrente (rauc status mark-good).
#
# Criterio: "la via degli aggiornamenti funziona di nuovo" — /data montata
# (sugli slot immagine), l'API locale risponde, RAUC vede la configurazione.
# Di proposito NON dipende da squeezelite o dall'interfaccia: un DAC staccato
# o uno schermo spento non devono far tornare all'altro slot. Se entro il
# tempo massimo non si arriva a "buono", si esce con errore e il flag *_TRY
# resta alzato: al riavvio (watchdog) il selettore GRUB prova l'altro slot.
set -u
# shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-ab-lib.sh
# shellcheck disable=SC1091  # percorso assoluto, esiste solo sull'apparecchio
. /usr/local/sbin/hifi-ab-lib.sh

[ -f "$AB_RAUC_CONF" ] || exit 0
TIMEOUT="${HIFI_BOOT_HEALTH_TIMEOUT:-300}"
deadline=$(( $(date +%s) + TIMEOUT ))
while :; do
    ok=1
    if ab_is_image && ! mountpoint -q "$AB_DATA_MNT"; then ok=0; fi
    curl -fsS -m 3 http://127.0.0.1:8000/ota_channel >/dev/null 2>&1 || ok=0
    rauc status >/dev/null 2>&1 || ok=0
    [ "$ok" = 1 ] && break
    if [ "$(date +%s)" -ge "$deadline" ]; then
        ab_warn "avvio NON dichiarato buono entro ${TIMEOUT}s (data=$(mountpoint -q "$AB_DATA_MNT" && echo ok || echo no), api=$(curl -fsS -m 3 http://127.0.0.1:8000/ota_channel >/dev/null 2>&1 && echo ok || echo no))"
        exit 1
    fi
    sleep 5
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
    : > /run/hifi-boot-good
    ab_log "avvio dichiarato buono (slot $(ab_booted_slot 2>/dev/null || echo legacy))"
    exit 0
fi
ab_warn "rauc status mark-good fallito"
exit 1
