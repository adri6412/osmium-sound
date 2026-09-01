#!/bin/sh
# Osmium Sound — aggiornamento IMMAGINE (schema A/B con RAUC).
#
#   hifi-image-update.sh stage <url|file> <versione>
#       installa il bundle nello slot inattivo con `rauc install` (in streaming
#       se è un URL: RAUC scarica solo i blocchi che scrive, niente file locale),
#       sulla root legacy appena convertita semina prima /data e dopo scrive il
#       selettore sulla ESP. Il sistema in uso non cambia: è il riavvio a far
#       partire il nuovo slot (la fase "apply" del sequencer è vuota).
#   hifi-image-update.sh apply <staged_dir> <versione>
#       no-op (compatibilità col sequencer a due fasi).
set -eu

CMD="${1:-}"
STATUS=/run/hifi-image-status.json
STAGE_ROOT=/var/lib/hifi-player/update/staged/image
VERSION=unknown
if [ -r /usr/local/sbin/hifi-log.sh ]; then
    # shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-log.sh
    # shellcheck disable=SC1091
    . /usr/local/sbin/hifi-log.sh
    hifi_log_init hifi-image-update
fi

write_status() {
    state="$1"; progress="$2"; msg="$3"
    esc=$(printf '%s' "$msg" | sed 's/\\/\\\\/g; s/"/\\"/g')
    printf '{"state":"%s","progress":%s,"version":"%s","message":"%s"}\n' \
        "$state" "$progress" "$VERSION" "$esc" > "$STATUS"
}
fail() {
    write_status error 0 "$1"
    echo "E: [hifi-image] $1" >&2
    exit 1
}

case "$CMD" in
stage)
    SRC="${2:-}"
    VERSION="${3:-unknown}"
    [ -n "$SRC" ] || fail "URL o file del bundle mancante"
    case "$VERSION" in ''|*[!0-9A-Za-z._-]*) fail "Versione non valida" ;; esac
    case "$SRC" in
        https://*) modprobe nbd 2>/dev/null || true ;;
        http://*)  modprobe nbd 2>/dev/null || true ;;
        /*) [ -f "$SRC" ] || fail "Bundle non trovato: $SRC" ;;
        *) fail "Sorgente non valida: $SRC" ;;
    esac
    [ -f /etc/rauc/system.conf ] || fail "RAUC non configurato: apparecchio non ancora convertito allo schema A/B"
    legacy=0
    [ -f /usr/lib/osmium/IMAGE_VERSION ] || legacy=1

    WORKDIR="$STAGE_ROOT/$VERSION"
    rm -rf "$WORKDIR"; mkdir -p "$WORKDIR"

    if [ "$legacy" = 1 ]; then
        write_status applying 5 "Copia dello stato sulla partizione dati…"
        /usr/local/sbin/hifi-ab-seed.sh || fail "Copia dello stato su /data fallita"
    fi

    write_status downloading 10 "Installazione dell'immagine $VERSION nello slot inattivo…"
    rcfile="$WORKDIR/rauc.rc"
    { rauc install "$SRC" 2>&1; echo "$?" > "$rcfile"; } | while IFS= read -r line; do
        printf '%s\n' "$line"
        case "$line" in
            *%*)
                pct=$(printf '%s' "$line" | sed -n 's/^[[:space:]]*\([0-9]\{1,3\}\)%.*/\1/p')
                [ -n "$pct" ] && write_status downloading $(( 10 + pct * 80 / 100 )) "$(printf '%s' "$line" | sed 's/^[[:space:]]*//' | cut -c1-120)"
                ;;
        esac
    done
    rc=$(cat "$rcfile" 2>/dev/null || echo 1)
    [ "$rc" = 0 ] || fail "rauc install fallito (rc=$rc): vedi /var/log/hifi/hifi-image-update.log"

    if [ "$legacy" = 1 ]; then
        write_status applying 92 "Attivazione del selettore di avvio A/B…"
        /usr/local/sbin/hifi-ab-convert.sh select || fail "Scrittura del selettore sulla ESP fallita"
        /usr/local/sbin/hifi-ab-seed.sh >/dev/null 2>&1 || true
        # shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-ab-lib.sh
        # shellcheck disable=SC1091
        . /usr/local/sbin/hifi-ab-lib.sh
        ab_mount_esp 2>/dev/null || true
        ab_state_set installed
    fi
    printf '%s\n' "$VERSION" > "$WORKDIR/STAGED"
    write_status staged 100 "Immagine $VERSION installata: al riavvio parte il nuovo sistema"
    ;;
apply)
    # Niente da fare: RAUC ha già scritto lo slot e impostato il primario; il
    # sequencer riavvia e il selettore GRUB fa il resto.
    VERSION="${3:-unknown}"
    write_status 'done' 100 "Immagine $VERSION pronta"
    ;;
*)
    echo "Uso: $0 stage <url|file> <versione> | apply <staged_dir> <versione>" >&2
    exit 64
    ;;
esac
