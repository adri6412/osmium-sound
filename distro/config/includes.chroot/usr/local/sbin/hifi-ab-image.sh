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
MARK_REBOOT="$LOCAL/armed-reboot-done"
# Dove si vede se sta uscendo audio davvero (sovrascrivibile dalla prova).
PCM_GLOB=${HIFI_AB_PCM_GLOB:-/proc/asound/card*/pcm*p/sub*/status}
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

# Arma la conversione per il PROSSIMO riavvio: `prepare` imposta una voce GRUB
# una tantum. Il riavvio lo provoca reboot_for_conversion() qui sotto, che
# prima guarda se c'e' qualcuno che ascolta.
# 1 solo quando la conversione è stata armata IN QUESTO giro: è la condizione
# del riavvio qui sotto. "Lo snippet GRUB c'è" non basta — dopo un avvio che
# non ha convertito resterebbe lì, e si riavvierebbe per niente.
armed_now=0
arm_conversion() {
    [ -x "$AB_CONVERT" ] || return 0
    [ -f "$RAUC_CONF" ] && return 0
    # Già armata: si converte al prossimo riavvio, non c'è niente da rifare
    # (e rifare `prepare` vorrebbe dire ricostruire l'initrd a ogni avvio).
    [ -f "$AB_GRUBD" ] && return 0
    if "$AB_PRECHECK" >/dev/null 2>&1; then
        if "$AB_CONVERT" prepare >/dev/null 2>&1; then
            log "conversione A/B armata: verrà eseguita al prossimo riavvio"
            # Detto anche a chi guarda lo schermo o il web admin: se il
            # riavvio qui sotto non si può fare (sta suonando), il proprietario
            # che ha appena liberato spazio deve poter sapere che la sua mossa
            # è servita e che manca solo un riavvio.
            write_state_done "Ready to switch to the new system at the next restart" update.ab.armed
            armed_now=1
            return 0
        else
            log "conversione A/B: prepare fallito, si riprova al prossimo avvio"
        fi
    else
        log "conversione A/B non possibile: $(sed -n 's/.*"reasons":"\([^"]*\)".*/\1/p' "$AB_PRECHECK_JSON" 2>/dev/null | cut -c1-160)"
    fi
}

# 🚨 Armare non basta. La conversione avviene al riavvio, e un apparecchio che
# nessuno spegne resta armato all'infinito: visto sul campo con la dev.10 —
# aggiornato, armato, e ancora su root singola finché il proprietario non l'ha
# riavviato a mano. Il runner degli aggiornamenti un riavvio ce l'ha (chiude
# lui la sessione), ma qui ci si arriva proprio quando il runner era quello
# VECCHIO, che di A/B non sapeva nulla — cioè per OGNI apparecchio ancora da
# convertire, visto che il blocco A/B nel runner esiste solo dalla 2.5.24-dev.10
# in avanti. Senza questo riavvio la flotta resta ferma ad aspettare che
# qualcuno stacchi la corrente.
#
# Due paletti, perché resta un lettore musicale:
#   * mai mentre suona — /proc/asound dice se sta uscendo audio davvero, per
#     qualunque sorgente, e chi sta ascoltando non si vede troncare il brano.
#     Chi non ascolta non si accorge di niente: la riproduzione viene comunque
#     ripresa al riavvio (hifi-capture-playback-state.py).
#   * una volta sola per apparecchio (MARK_REBOOT). Se la conversione fallisse
#     e si riarmasse da sola, un riavvio a ogni avvio sarebbe un ciclo senza
#     fine — e su un apparecchio senza schermo non se ne accorgerebbe nessuno
#     finché non smette di suonare per sempre.
audio_running() {
    for _st in $PCM_GLOB; do
        [ -r "$_st" ] || continue
        grep -q '^state: RUNNING' "$_st" 2>/dev/null && return 0
    done
    return 1
}

reboot_for_conversion() {
    [ "$armed_now" = 1 ] || return 0      # armata adesso, o non c'è niente da completare
    [ -f "$RAUC_CONF" ] && return 0
    if [ -f "$MARK_REBOOT" ]; then
        log "conversione armata: riavvio automatico già tentato una volta, non si insiste"
        return 0
    fi
    if audio_running; then
        log "conversione armata: sta suonando, si converte al prossimo riavvio"
        return 0
    fi
    # Un attimo perché il resto dell'avvio si assesti, poi si ricontrolla:
    # qualcuno può aver premuto play nel frattempo.
    sleep "${HIFI_AB_REBOOT_DELAY:-20}"
    if audio_running; then
        log "conversione armata: è partita la musica, riavvio rimandato"
        return 0
    fi
    mkdir -p "$LOCAL"
    date -u +%Y-%m-%dT%H:%M:%SZ > "$MARK_REBOOT"
    log "conversione armata: riavvio per completarla"
    write_state_done "Restarting to switch to the new system" update.ab.rebooting
    ${HIFI_REBOOT_CMD:-systemctl reboot} || log "riavvio fallito"
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
    reboot_for_conversion
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
            reboot_for_conversion
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
