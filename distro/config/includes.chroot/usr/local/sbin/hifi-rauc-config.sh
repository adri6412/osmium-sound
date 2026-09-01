#!/bin/sh
# Osmium Sound — genera /etc/rauc/system.conf dai device reali e monta ESP e
# /data. Gira a ogni avvio (hifi-rauc-config.service, prima di rauc.service)
# sugli slot immagine e sulla root legacy convertita; è un no-op silenzioso
# dove il layout A/B non c'è.
set -eu
# shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-ab-lib.sh
# shellcheck disable=SC1091  # percorso assoluto, esiste solo sull'apparecchio
. /usr/local/sbin/hifi-ab-lib.sh

A=$(ab_part_by_name hifi-root-a) || A=
B=$(ab_part_by_name hifi-root-b) || B=
DATA=$(ab_part_by_name hifi-data) || DATA=
ESP=$(ab_part_by_name "EFI System") || ESP=
if [ -z "$A" ] || [ -z "$B" ] || [ -z "$DATA" ] || [ -z "$ESP" ]; then
    ab_log "layout A/B assente su $(ab_disk 2>/dev/null || echo '?'): niente da configurare"
    exit 0
fi

ab_mount_esp || ab_warn "impossibile montare la ESP $ESP"
ab_mount_data || ab_warn "impossibile montare /data ($DATA)"
mkdir -p "$AB_DATA_MNT/rauc" /etc/rauc

# La keyring viaggia nell'immagine (/etc/rauc/keyring.pem cotta) e, per i
# legacy, nel pacchetto di sistema (/usr/local/share/hifi-ab/keyring.pem).
if [ ! -s "$AB_RAUC_KEYRING" ] && [ -s "$AB_KEYRING_SRC" ]; then
    install -m 0644 "$AB_KEYRING_SRC" "$AB_RAUC_KEYRING"
    ab_log "keyring RAUC installata da $AB_KEYRING_SRC"
fi

if ab_render "$AB_SHARE/system.conf.tmpl" "SLOT_A=$A" "SLOT_B=$B" \
        | ab_write_atomic "$AB_RAUC_CONF" 0644; then
    ab_log "scritto $AB_RAUC_CONF (A=$A B=$B)"
fi
# Il servizio D-Bus di RAUC legge la configurazione quando parte: se era già
# su (avvio a caldo di questo script) va riavviato per vedere quella nuova.
if systemctl is-active --quiet rauc.service 2>/dev/null; then
    systemctl restart rauc.service 2>/dev/null || true
fi
exit 0
