#!/bin/sh
# Osmium Sound — continua da solo la catena di aggiornamento A/B.
#
# Due compiti, entrambi una tantum (marcatori in /var/lib/hifi-player/ab):
#   1. "kickoff": su un legacy NON ancora convertito, se una sessione di
#      aggiornamento è appena finita (state phase=done) rilancia
#      /update/apply_all — sul 2.5.23 il primo giro lo fa il runner VECCHIO
#      (che non conosce l'A/B né il pacchetto qtui): senza questo rilancio
#      la migrazione si fermava lì ad aspettare un secondo "Aggiorna ora".
#   2. dopo la conversione (marker `finished`): avvia l'aggiornamento
#      all'immagine (piano con il solo step image).
# Se non riesce a partire scrive phase=error, così il kiosk non resta con
# l'overlay "passaggio al nuovo sistema" appeso.
set -u
LOCAL=/var/lib/hifi-player/ab
MARK_IMAGE="$LOCAL/image-kicked"
MARK_KICKOFF="$LOCAL/kickoff-done"
UPDATE_DIR=/var/lib/hifi-player/update
STATE_FILE="$UPDATE_DIR/state"
ERROR_FILE="$UPDATE_DIR/error.json"
API=http://127.0.0.1:8000
log() { printf 'I: [hifi-ab-image] %s
' "$*"; }

write_error_state() {  # <message-en> <key>
    mkdir -p "$UPDATE_DIR"
    { echo 'phase=error'; echo "ts=$(date +%s)"; echo "message=$1"; echo "key=$2"; } > "$STATE_FILE.tmp"         && mv -f "$STATE_FILE.tmp" "$STATE_FILE"
    printf '{"channel":"image","message":"%s","key":"%s","params":{}}
' "$1" "$2" > "$ERROR_FILE.tmp"         && mv -f "$ERROR_FILE.tmp" "$ERROR_FILE"
}

state_phase() { awk -F= '$1=="phase"{print $2}' "$STATE_FILE" 2>/dev/null; }

[ -f /usr/lib/osmium/IMAGE_VERSION ] && exit 0

MODE=""
if [ -f "$LOCAL/finished" ]; then
    [ -f "$MARK_IMAGE" ] && exit 0
    MODE=image
elif [ -x /usr/local/sbin/hifi-ab-convert.sh ] && [ ! -f /etc/rauc/system.conf ]      && [ ! -f "$MARK_KICKOFF" ] && [ "$(state_phase)" = "done" ]; then
    MODE=kickoff
else
    exit 0
fi

n=0
until curl -fsS -m 3 "$API/ota_channel" >/dev/null 2>&1; do
    n=$((n + 1)); [ "$n" -gt 60 ] && { log "API non raggiungibile"; exit 1; }
    sleep 5
done

n=0
while :; do
    r=$(curl -fsS -m 30 -X POST -H 'Content-Type: application/json' -d '{}' "$API/update/apply_all" 2>/dev/null || echo '{}')
    case "$r" in
        *'"started": true'*|*'"started":true'*)
            log "aggiornamento avviato ($MODE): $r"
            mkdir -p "$LOCAL"
            [ "$MODE" = image ] && date -u +%Y-%m-%dT%H:%M:%SZ > "$MARK_IMAGE"
            date -u +%Y-%m-%dT%H:%M:%SZ > "$MARK_KICKOFF"
            exit 0 ;;
        *alreadyInProgress*)
            log "aggiornamento già in corso"; exit 0 ;;
    esac
    if [ "$MODE" = kickoff ]; then
        # Niente da continuare (es. tutto già applicato): non è un errore.
        case "$r" in *noneAvailable*)
            log "kickoff: nessun altro aggiornamento ($r)"
            mkdir -p "$LOCAL"; date -u +%Y-%m-%dT%H:%M:%SZ > "$MARK_KICKOFF"
            exit 0 ;;
        esac
    fi
    n=$((n + 1))
    if [ "$n" -gt 20 ]; then
        log "impossibile avviare l'aggiornamento dopo 40 min ($MODE): $r"
        write_error_state "The system image update could not be started" update.image.kickFailed
        exit 1
    fi
    log "in attesa ($MODE: $r)"
    sleep 120
done
