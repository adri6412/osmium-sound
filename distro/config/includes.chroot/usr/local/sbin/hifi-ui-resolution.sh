#!/bin/sh
# shellcheck shell=sh
# HiFi Player — risoluzione di rendering dell'interfaccia.
#
# PERCHÉ ESISTE
# La UI è disegnata su un canvas fisso 1024x600 e ingrandita con CSS `zoom`
# (src/components/ScaledCanvas.jsx), e la finestra Electron nasce grande quanto
# il pannello fisico (main/main.js). Su un 1080p questo significa che Chromium
# rasterizza davvero 1920x1080 pixel ad ogni repaint, su un 4K 3840x2160 — e
# ogni blur della UI (artwork glow, sfondo album sfocato, VU meter, backdrop
# dei pannelli) vede un kernel proporzionale allo zoom su una superficie
# proporzionale allo zoom. Sulle iGPU di classe kiosk (Intel Gemini Lake) la
# GPU resta inchiodata attorno al 90% durante il normale ascolto.
#
# Le mitigazioni già in essere (30 FPS, `zoom` invece di `transform`, blur
# ridotti) abbassano il costo PER pixel; nessuna riduce il NUMERO di pixel, che
# è l'unico parametro che scala il problema. Dentro Chromium quella leva non
# esiste: --force-device-scale-factor cambia il rapporto CSS-px/device-px ma i
# pixel fisici della finestra vengono rasterizzati comunque, e tornare a
# `transform: scale()` reintrodurrebbe la regressione già documentata in
# ScaledCanvas.jsx. L'unico punto in cui il conteggio cala davvero è SOTTO
# Electron: il framebuffer X.
#
# COME
#     xrandr --output <OUT> --scale-from <W>x<H>
# Il modo video resta quello nativo (nessuna rinegoziazione dell'HDMI, nessuna
# dipendenza dallo scaler del TV, nessun EDID da assecondare): cambia solo
# l'area di framebuffer mappata sull'uscita, che X scala a schermo intero in
# scansione. A valle, screen.getPrimaryDisplay().size ritorna la dimensione
# ridotta, la BrowserWindow nasce di quella dimensione e ScaledCanvas calcola
# uno zoom più basso — Chromium rasterizza 921k pixel invece di 2.07M (1080p) o
# 8.3M (4K).
#
# ASPECT RATIO: `--scale-from` stira l'area di framebuffer fino a riempire
# TUTTO il modo, quindi il target non può essere la costante 1280x720 o la UI
# esce deformata. Si fissa l'ALTEZZA al cap e si ricava la larghezza dal
# rapporto del pannello (allineata a multipli di 8 per lo stride del driver):
# 1920x1080 -> 1280x720, 1920x1200 -> 1152x720, 3840x2160 -> 1280x720.
#
# Stato in /etc/hifi-player/ui-resolution: "auto" | "720" | "1080" | "native".
# ASSENTE significa "auto" — a differenza di display-mode, qui il default vuole
# deliberatamente raggiungere anche la flotta già installata: un'unità che non
# ha mai scritto il file è esattamente quella che soffre del problema e che non
# aprirà mai le impostazioni.
#
# Uso:
#   hifi-ui-resolution.sh get                       -> stampa la preferenza
#   hifi-ui-resolution.sh apply                     -> applica al server X corrente
#   hifi-ui-resolution.sh set auto|720|1080|native [--live]
#
# `apply` è invocato dalla sessione kiosk (~/.xsession) come utente hifi, prima
# di lanciare Electron: deve solo LEGGERE lo stato. Solo `set` scrive sotto
# /etc/hifi-player e richiede root (api_server.py gira già come root, nessuna
# voce sudoers necessaria).
#
# Senza --live la scelta vale dal prossimo login. Con --live si riavvia anche la
# sessione grafica, dopo un breve ritardo, così che il chiamante (api_server.py)
# faccia in tempo a rispondere prima che la UI che ha inviato la richiesta
# sparisca; al login successivo ~/.xsession richiama `apply` da sé.

set -eu

# NOTA: deliberatamente NON rediretto su hifi-log.sh — lo stdout di questo
# script È il suo canale dati (api_server.py legge e interpreta la riga
# "auto"/"720"/"1080"/"native" direttamente dallo stdout del sottoprocesso),
# non chiacchiericcio diagnostico. Rediregerlo romperebbe in silenzio il
# selettore di risoluzione.
RES_FILE=/etc/hifi-player/ui-resolution

# Sotto quale altezza fisica "auto" non tocca nulla. 800 e non 720: lascia
# intatti il touchscreen 1024x600, i pannelli 1366x768 e i 1280x800, dove il
# guadagno sarebbe marginale e l'unica cosa percepibile sarebbe la perdita di
# nitidezza.
AUTO_MIN_HEIGHT=800

die() { echo "$1" >&2; exit 1; }

# L'ambiente X della sessione kiosk (autologin hifi = :0). Impostato con dei
# default e non forzato, così lo script funziona sia invocato da root
# (api_server) sia già dentro la sessione X dell'utente hifi.
: "${DISPLAY:=:0}"
: "${XAUTHORITY:=/home/hifi/.Xauthority}"
export DISPLAY XAUTHORITY

get_pref() {
    pref="$(cat "$RES_FILE" 2>/dev/null | tr -d '[:space:]')" || pref=""
    case "$pref" in
        720|1080|native) echo "$pref" ;;
        *)               echo auto ;;   # assente o illeggibile => auto
    esac
}

# Output da pilotare: il primo connesso, preferendo quello marcato "primary".
# Stampa nulla (e basta) se non c'è X o non c'è nessun output connesso.
find_output() {
    xrandr --query 2>/dev/null | awk '
        / connected/ {
            if ($3 == "primary") { print $1; exit }
            if (first == "")     { first = $1 }
        }
        END { if (first != "") print first }
    '
}

# Modo FISICO dell'output: la riga della sua lista modi marcata "*". Va letta di
# lì e non dalla geometria corrente, perché con un transform già attivo la
# geometria riporta l'area di framebuffer scalata (es. 1280x720) mentre il modo
# resta quello vero — leggere la geometria renderebbe `apply` non idempotente,
# rimpicciolendo lo schermo un po' di più ad ogni esecuzione.
current_mode() {
    xrandr --query 2>/dev/null | awk -v out="$1" '
        $1 == out && / connected/ { inblock = 1; next }
        inblock && / connected/   { exit }          # inizio di un altro output
        inblock && /\*/ {
            if ($1 ~ /^[0-9]+x[0-9]+$/) { print $1; exit }
        }
    '
}

# Area di framebuffer attualmente mappata sull'output: il "WxH" della geometria
# WxH+X+Y sulla riga "connected". Con un transform attivo questa è la dimensione
# SCALATA (es. 1280x720) mentre current_mode resta quella fisica: confrontarle
# dice se c'è già la configurazione voluta, così `apply` al login non tocca il
# CRTC — e non fa sfarfallare lo schermo — quando non c'è niente da cambiare.
current_geometry() {
    xrandr --query 2>/dev/null | awk -v out="$1" '
        $1 == out && / connected/ {
            for (i = 2; i <= NF; i++) {
                if ($i ~ /^[0-9]+x[0-9]+\+[0-9]+\+[0-9]+$/) {
                    sub(/\+.*/, "", $i); print $i; exit
                }
            }
            exit
        }
    '
}

# Cap in altezza per la preferenza data e il pannello dato. Stampa nulla se non
# c'è nulla da fare (pannello già abbastanza piccolo, o "native").
cap_for() {
    pref="$1"; ph="$2"
    case "$pref" in
        native) return 0 ;;
        720)    [ "$ph" -gt 720 ]  && echo 720 ;;
        1080)   [ "$ph" -gt 1080 ] && echo 1080 ;;
        auto)   [ "$ph" -gt "$AUTO_MIN_HEIGHT" ] && echo 720 ;;
    esac
    return 0
}

# Larghezza target: stesso rapporto del pannello, arrotondata al multiplo di 8
# più vicino (stride del driver) e mai sotto 8.
target_width() {
    pw="$1"; ph="$2"; th="$3"
    awk -v pw="$pw" -v ph="$ph" -v th="$th" 'BEGIN {
        w = pw * th / ph
        w = int((w + 4) / 8) * 8
        if (w < 8) w = 8
        print w
    }'
}

apply_pref() {
    command -v xrandr >/dev/null 2>&1 || return 0

    OUT="$(find_output)"
    # Nessun X in ascolto (modalità headless), o nessun pannello collegato:
    # niente da fare. Mai fatale — questo script è invocato dalla sessione di
    # login e un errore qui non deve poter impedire l'avvio del kiosk.
    [ -n "$OUT" ] || return 0

    MODE="$(current_mode "$OUT")"
    [ -n "$MODE" ] || return 0
    PW="${MODE%x*}"
    PH="${MODE#*x}"
    case "$PW$PH" in *[!0-9]*) return 0 ;; esac

    PREF="$(get_pref)"
    TH="$(cap_for "$PREF" "$PH")"

    if [ -n "$TH" ]; then
        TARGET="$(target_width "$PW" "$PH" "$TH")x${TH}"
        # Non ingrandire mai il framebuffer oltre il pannello.
        [ "${TARGET%x*}" -lt "$PW" ] || TARGET="$MODE"
    else
        TARGET="$MODE"
    fi

    # Già come lo vogliamo: non toccare il CRTC (evita uno sfarfallio inutile
    # ad ogni login sui pannelli che non vanno ridimensionati affatto).
    [ "$(current_geometry "$OUT")" = "$TARGET" ] && return 0

    if [ "$TARGET" = "$MODE" ]; then
        # Nessun ridimensionamento voluto: azzera il transform residuo (es.
        # l'utente è appena tornato a "Nativa") riportando il framebuffer alla
        # dimensione del modo. `--scale 1x1` è il modo documentato di annullare
        # uno `--scale-from`/`--scale` precedente.
        xrandr --output "$OUT" --scale 1x1 >/dev/null 2>&1 || true
    else
        xrandr --output "$OUT" --scale-from "$TARGET" >/dev/null 2>&1 || true
    fi
}

case "${1:-}" in
    get)
        get_pref
        ;;
    apply)
        apply_pref
        ;;
    set)
        PREF="${2:-}"
        case "$PREF" in
            auto|720|1080|native) ;;
            *) die "usage: $0 set auto|720|1080|native [--live]" ;;
        esac
        LIVE=0
        [ "${3:-}" = "--live" ] && LIVE=1

        # Persistenza atomica (tmp + mv), stesso schema di display-mode.
        mkdir -p "$(dirname "$RES_FILE")"
        tmp="${RES_FILE}.tmp.$$"
        printf '%s\n' "$PREF" > "$tmp"
        mv -f "$tmp" "$RES_FILE"
        chmod 644 "$RES_FILE" 2>/dev/null || true

        if [ "$LIVE" = 1 ]; then
            # One-shot staccato DOPO un breve ritardo, così la risposta HTTP del
            # chiamante è già partita quando la UI che l'ha richiesta viene
            # abbattuta.
            #
            # Si riavvia lightdm invece di ridimensionare a caldo e terminare la
            # sola app, per due motivi. (1) La finestra Electron è creata
            # `resizable: false` e dimensionata una volta sola all'avvio, quindi
            # va comunque ricreata: ridimensionare il framebuffer sotto una
            # finestra viva lascerebbe solo qualche secondo di immagine rotta.
            # (2) Terminare il solo processo Electron per nome non è affidabile:
            # "hifi-media-player" è più lungo dei 15 caratteri del campo `comm`
            # del kernel (pkill -x non troverebbe nulla) e un pkill -f
            # ucciderebbe anche la shell che lo esegue, visto che il nome
            # compare nella sua stessa riga di comando. Il riavvio della
            # sessione X rifà tutto in ordine: al login ~/.xsession richiama
            # `apply` e Electron nasce già della dimensione giusta. È anche ciò
            # che fa hifi-ota-update.sh per rimettere in piedi il kiosk.
            #
            # Guardato da is-active: in modalità headless lightdm NON è in
            # esecuzione, e un restart lo avvierebbe — riaccendendo uno schermo
            # che l'utente ha spento di proposito.
            if command -v systemd-run >/dev/null 2>&1; then
                # Nome unità transitorio auto-generato (niente --unit fisso) così
                # due cambi ravvicinati non collidono su un'unità esistente.
                systemd-run --collect --description="HiFi UI resolution switch" \
                    /bin/sh -c 'sleep 1; systemctl is-active --quiet lightdm && systemctl restart lightdm' \
                    >/dev/null 2>&1 || true
            fi
        fi

        echo "$PREF"
        ;;
    *)
        die "usage: $0 get | apply | set auto|720|1080|native [--live]"
        ;;
esac
