#!/bin/sh
# Osmium Sound — continua da solo la catena di aggiornamento A/B.
#
# Due compiti una tantum (marcatori in /var/lib/hifi-player/ab):
#   1. "kickoff": su un legacy NON ancora convertito, se una sessione di
#      aggiornamento è appena finita (state phase=done) rilancia
#      /update/apply_all — sul 2.5.23 il primo giro lo fa il runner VECCHIO
#      (che non conosce l'A/B né il pacchetto qtui): senza questo rilancio
#      la migrazione si fermava lì ad aspettare un secondo "Aggiorna ora".
#   2. dopo la conversione (marker `finished`): avvia l'aggiornamento
#      all'immagine (piano con il solo step image).
# E, a ogni avvio finché l'apparecchio resta legacy, un terzo compito che una
# tantum non è: riprovare ad armare la conversione. Le pre-verifiche possono
# aver detto di no per qualcosa che il proprietario può sistemare (liberare
# spazio, togliere la musica dal disco di sistema), e il rilancio qui sopra
# avviene una volta sola: senza questo, chi rimedia resterebbe legacy fino
# alla prossima release.
# Se non riesce a partire scrive phase=error, così il kiosk non resta con
# l'overlay "passaggio al nuovo sistema" appeso.
set -u
# I percorsi sono quelli veri dell'apparecchio; le variabili servono alla prova
# automatica (tests/test-ab-image.sh), che monta un apparecchio finto in /tmp.
LOCAL=${HIFI_AB_LOCAL:-/var/lib/hifi-player/ab}
AB_CONVERT=${HIFI_AB_CONVERT:-/usr/local/sbin/hifi-ab-convert.sh}
AB_PRECHECK=${HIFI_AB_PRECHECK:-/usr/local/sbin/hifi-ab-precheck.sh}
AB_PRECHECK_JSON=${HIFI_AB_PRECHECK_JSON:-/run/hifi-ab-precheck.json}
RAUC_CONF=${HIFI_RAUC_CONF:-/etc/rauc/system.conf}
IMAGE_VERSION_FILE=${HIFI_IMAGE_VERSION_FILE:-/usr/lib/osmium/IMAGE_VERSION}
# La voce GRUB una tantum che scrive `prepare` e che toglie `finish`: c'è solo
# fra il momento in cui la conversione è armata e quello in cui è avvenuta.
AB_GRUBD=${HIFI_AB_GRUBD:-/etc/grub.d/45_hifi_abconvert}
MARK_IMAGE="$LOCAL/image-kicked"
MARK_KICKOFF="$LOCAL/kickoff-done"
UPDATE_DIR=${HIFI_UPDATE_DIR:-/var/lib/hifi-player/update}
STATE_FILE="$UPDATE_DIR/state"
ERROR_FILE="$UPDATE_DIR/error.json"
API=${HIFI_API_BASE:-http://127.0.0.1:8000}
log() { printf 'I: [hifi-ab-image] %s
' "$*"; }

write_state_done() {  # <message-en> <key>
    mkdir -p "$UPDATE_DIR"
    { echo 'phase=done'; echo "ts=$(date +%s)"; echo "message=$1"; echo "key=$2"; } > "$STATE_FILE.tmp" \
        && mv -f "$STATE_FILE.tmp" "$STATE_FILE"
}

write_error_state() {  # <message-en> <key>
    mkdir -p "$UPDATE_DIR"
    { echo 'phase=error'; echo "ts=$(date +%s)"; echo "message=$1"; echo "key=$2"; } > "$STATE_FILE.tmp"         && mv -f "$STATE_FILE.tmp" "$STATE_FILE"
    printf '{"channel":"image","message":"%s","key":"%s","params":{}}
' "$1" "$2" > "$ERROR_FILE.tmp"         && mv -f "$ERROR_FILE.tmp" "$ERROR_FILE"
}


[ -f "$IMAGE_VERSION_FILE" ] && exit 0

# Arma la conversione per il PROSSIMO riavvio, senza provocarlo: `prepare`
# imposta una voce GRUB una tantum, quindi si converte quando l'apparecchio
# viene riavviato per i fatti suoi (o al prossimo aggiornamento, che riavvia
# comunque). Riavviare qui, di sorpresa, interromperebbe la musica.
arm_conversion() {
    [ -x "$AB_CONVERT" ] || return 0
    [ -f "$RAUC_CONF" ] && return 0
    # Già armata: si converte al prossimo riavvio, non c'è niente da rifare
    # (e rifare `prepare` vorrebbe dire ricostruire l'initrd a ogni avvio).
    [ -f "$AB_GRUBD" ] && return 0
    if "$AB_PRECHECK" >/dev/null 2>&1; then
        if "$AB_CONVERT" prepare >/dev/null 2>&1; then
            log "conversione A/B armata: verrà eseguita al prossimo riavvio"
            # Detto anche a chi guarda lo schermo o il web admin: qui non si
            # riavvia di sorpresa, quindi senza una riga il proprietario che ha
            # appena liberato spazio non ha modo di sapere che la sua mossa è
            # servita.
            write_state_done "Ready to switch to the new system at the next restart" update.ab.armed
        else
            log "conversione A/B: prepare fallito, si riprova al prossimo avvio"
        fi
    else
        log "conversione A/B non possibile: $(sed -n 's/.*"reasons":"\([^"]*\)".*/\1/p' "$AB_PRECHECK_JSON" 2>/dev/null | cut -c1-160)"
    fi
}

MODE=""
if [ -f "$LOCAL/finished" ]; then
    [ -f "$MARK_IMAGE" ] && exit 0
    MODE=image
elif [ -x "$AB_CONVERT" ] && [ ! -f "$RAUC_CONF" ] && [ ! -f "$MARK_KICKOFF" ]; then
    # Non si pretende più che un aggiornamento sia appena finito: anche un
    # apparecchio fermo da giorni all'ultima versione, e mai convertito, deve
    # trovare la strada da solo.
    MODE=kickoff
else
    # 🚨 Niente aggiornamento da rilanciare, ma l'apparecchio può essere ancora
    # legacy: le pre-verifiche possono aver detto di no per qualcosa che il
    # proprietario ha poi sistemato — spazio liberato, oppure la musica tolta
    # dal disco di sistema, che è la richiesta esplicita di uno dei motivi di
    # rifiuto. Il rilancio dell'aggiornamento avviene una volta sola
    # (kickoff-done), quindi senza questo secondo tentativo a ogni avvio chi
    # rimedia oggi resterebbe legacy fino alla prossima release: "ho fatto
    # quello che mi ha chiesto e non è cambiato niente". Costa una pre-verifica
    # per avvio, e solo finché l'apparecchio non è convertito.
    arm_conversion
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
