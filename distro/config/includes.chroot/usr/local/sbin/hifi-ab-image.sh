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


[ -f /usr/lib/osmium/IMAGE_VERSION ] && exit 0

MODE=""
if [ -f "$LOCAL/finished" ]; then
    [ -f "$MARK_IMAGE" ] && exit 0
    MODE=image
elif [ -x /usr/local/sbin/hifi-ab-convert.sh ] && [ ! -f /etc/rauc/system.conf ] \
     && [ ! -f "$MARK_KICKOFF" ]; then
    # Non si pretende più che un aggiornamento sia appena finito: anche un
    # apparecchio fermo da giorni all'ultima versione, e mai convertito, deve
    # trovare la strada da solo.
    MODE=kickoff
else
    exit 0
fi

# Arma la conversione per il PROSSIMO riavvio, senza provocarlo: `prepare`
# imposta una voce GRUB una tantum, quindi si converte quando l'apparecchio
# viene riavviato per i fatti suoi (o al prossimo aggiornamento, che riavvia
# comunque). Riavviare qui, di sorpresa, interromperebbe la musica.
arm_conversion() {
    [ -x /usr/local/sbin/hifi-ab-convert.sh ] || return 0
    [ -f /etc/rauc/system.conf ] && return 0
    if /usr/local/sbin/hifi-ab-precheck.sh >/dev/null 2>&1; then
        if /usr/local/sbin/hifi-ab-convert.sh prepare >/dev/null 2>&1; then
            log "conversione A/B armata: verrà eseguita al prossimo riavvio"
        else
            log "conversione A/B: prepare fallito, l'apparecchio resta legacy"
        fi
    else
        log "conversione A/B non possibile: $(sed -n 's/.*"reasons":"\([^"]*\)".*/\1/p' /run/hifi-ab-precheck.json 2>/dev/null | cut -c1-160)"
    fi
}

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
        # 🚨 "Niente da aggiornare" NON vuol dire "niente da fare". La
        # conversione allo schema A/B la arma il runner di apply, cioè solo
        # DURANTE un aggiornamento: un apparecchio arrivato all'ultima versione
        # con il runner VECCHIO (quello delle immagini precedenti, che di A/B
        # non sa nulla) resterebbe legacy per sempre, perché quando questa
        # unità parte non c'è più niente da applicare e prima ci si fermava
        # qui. Visto sul campo: un box aggiornato ad alpha4 e rimasto su root
        # singola. Quindi la conversione si arma da soli.
        case "$r" in *noneAvailable*)
            log "kickoff: niente da aggiornare, l'apparecchio è già all'ultima versione"
            arm_conversion
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
