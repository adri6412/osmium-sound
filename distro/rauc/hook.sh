#!/bin/sh
# Osmium Sound — hook del bundle RAUC (viaggia dentro il bundle, firmato).
#
#   install-check      rifiuta il bundle se non è per questo hardware o se
#                      l'apparecchio non ha il layout A/B (partizione dati).
#   slot-post-install  dopo la scrittura dello slot: con la root squashfs non
#                      c'è nulla da fare (resta per gli slot ext4 legacy).
set -eu

case "${1:-}" in
install-check)
    if [ "${RAUC_MF_COMPATIBLE:-}" != "${RAUC_SYSTEM_COMPATIBLE:-}" ]; then
        echo "Immagine per '${RAUC_MF_COMPATIBLE:-?}', apparecchio '${RAUC_SYSTEM_COMPATIBLE:-?}'" >&2
        exit 10
    fi
    if [ ! -e /dev/disk/by-partlabel/hifi-data ]; then
        echo "Manca la partizione dati (hifi-data): l'apparecchio non è ancora convertito ad A/B" >&2
        exit 11
    fi
    ;;
slot-post-install)
    case "${RAUC_SLOT_CLASS:-}" in
    rootfs)
        dev="${RAUC_SLOT_DEVICE:?}"
        # Lo slot è uno squashfs scritto raw: niente da fare. Solo se (per
        # qualche motivo) dentro c'è un ext4 gli si dà un UUID nuovo.
        if [ "$(blkid -o value -s TYPE "$dev" 2>/dev/null)" = ext4 ]; then
            e2fsck -fy "$dev" >/dev/null 2>&1 || true
            tune2fs -U random "$dev" >/dev/null 2>&1 || echo "avviso: tune2fs -U su $dev fallito (non bloccante)" >&2
        fi
        ;;
    esac
    ;;
*)
    exit 1
    ;;
esac
exit 0
