#!/bin/sh
# Osmium Sound — rete di sicurezza per gli avvii di prova (slot con *_TRY=1).
# Se dopo il tempo del timer l'avvio non è stato dichiarato buono, riavvia:
# il selettore GRUB vede il tentativo consumato e passa all'altro slot. Uno
# slot già buono (TRY=0) non viene mai riavviato da qui: un guasto passeggero
# dell'API non deve far rimbalzare un sistema che di suo funziona.
set -u
# shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-ab-lib.sh
# shellcheck disable=SC1091  # percorso assoluto, esiste solo sull'apparecchio
. /usr/local/sbin/hifi-ab-lib.sh

[ -f /run/hifi-boot-good ] && exit 0
[ -f "$AB_RAUC_CONF" ] || exit 0
slot=$(ab_booted_slot) || exit 0
ab_mount_esp 2>/dev/null || exit 0
[ -r "$AB_GRUBENV" ] || exit 0
if grub-editenv "$AB_GRUBENV" list 2>/dev/null | grep -qx "${slot}_TRY=1"; then
    ab_warn "slot $slot in prova e non dichiarato buono: riavvio per far scegliere l'altro slot"
    sync
    systemctl reboot
fi
exit 0
