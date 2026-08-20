#!/bin/sh
# shellcheck shell=sh
# HiFi Player — refresh rate del pannello (nativo <-> basso consumo GPU).
#
# PERCHÉ ESISTE
# Su iGPU di classe kiosk (Intel Gemini Lake) sia il blit di scala X (quando
# hifi-ui-resolution.sh è in "auto"/"720"/"1080") sia il compositor di Chromium
# sono agganciati al vblank del pannello: il loro costo GPU per secondo scala
# linearmente col refresh. Dimezzare il refresh dimezza (circa) entrambi i
# costi, misurato: ~79% di render engine busy a 49.98Hz contro ~49% a 29.99Hz
# sulla stessa scena, stesso contenuto. Non serve ridisegnare né Chromium né X:
# è puro tempo macchina risparmiato riducendo QUANTE volte al secondo tutta la
# catena ridisegna, indipendentemente da cosa cambia sullo schermo.
#
# COME
#     xrandr --output <OUT> --mode <MODO-NATIVO> --rate <Hz>
# A differenza di hifi-ui-resolution.sh questo NON tocca l'area di framebuffer
# mappata (nessun --scale/--scale-from): la finestra Electron, già dimensionata
# una volta sola all'avvio su screen.getPrimaryDisplay().size, non cambia
# affatto — cambia solo la cadenza del CRTC. Per questo "set --live" applica
# subito, in modo sincrono, senza il giro di riavvio di lightdm che serve a
# hifi-ui-resolution.sh (lì la finestra va ricreata; qui no).
#
# DISPONIBILITÀ: non tutti i pannelli espongono un modo a refresh basso per la
# risoluzione nativa (i pannelli embedded a frequenza fissa spesso ne hanno
# uno solo). Se non c'è un rate <=32Hz distinto da quello nativo per il modo
# corrente, la preferenza "low" resta silenziosamente inapplicata (si tiene il
# nativo) — vedi il sottocomando `supported`, che il chiamante (api_server.py)
# usa per decidere se offrire il controllo in UI.
#
# Stato in /etc/hifi-player/ui-refresh: "native" | "low". ASSENTE = "native":
# nessuna unità già installata cambia comportamento finché non lo sceglie
# esplicitamente dalle Impostazioni.
#
# Uso:
#   hifi-ui-refresh.sh get                    -> stampa la preferenza
#   hifi-ui-refresh.sh supported              -> "1"/"0": il pannello ha un rate basso?
#   hifi-ui-refresh.sh apply                  -> applica al server X corrente
#   hifi-ui-refresh.sh set native|low [--live]
#
# `apply` è invocato dalla sessione kiosk (~/.xsession) come utente hifi, prima
# o dopo hifi-ui-resolution.sh apply (indifferente, toccano proprietà diverse
# dello stesso output).

set -eu

# NOTA: deliberatamente NON rediretto su hifi-log.sh — lo stdout di questo
# script È il suo canale dati (api_server.py legge "native"/"low"/"1"/"0"
# direttamente dallo stdout del sottoprocesso), non chiacchiericcio
# diagnostico. Stesso schema di hifi-ui-resolution.sh.
REFRESH_FILE=/etc/hifi-player/ui-refresh

# Stesso schema di default di hifi-ui-resolution.sh / hifi-display-mode.sh:
# funziona sia invocato da root (api_server) sia dentro la sessione X di hifi.
: "${DISPLAY:=:0}"
: "${XAUTHORITY:=/home/hifi/.Xauthority}"
: "${XDG_RUNTIME_DIR:=/run/user/1000}"
: "${WAYLAND_DISPLAY:=wayland-0}"
export DISPLAY XAUTHORITY XDG_RUNTIME_DIR WAYLAND_DISPLAY

# Quale server grafico è in ascolto ORA — stesso helper di
# hifi-ui-resolution.sh, che con questo script condivide anche l'output da
# pilotare e il modo su cui lavorare.
backend() {
    if [ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ] && command -v wlr-randr >/dev/null 2>&1; then
        echo wayland
    elif command -v xrandr >/dev/null 2>&1; then
        echo x11
    fi
}

die() { echo "$1" >&2; exit 1; }

get_pref() {
    pref="$(cat "$REFRESH_FILE" 2>/dev/null | tr -d '[:space:]')" || pref=""
    case "$pref" in
        low) echo low ;;
        *)   echo native ;;   # assente o illeggibile => native
    esac
}

# Stesso identico helper di hifi-ui-resolution.sh: su X11 il primo output
# connesso preferendo "primary", su Wayland il primo abilitato.
find_output() {
    case "$1" in
        x11)
            xrandr --query 2>/dev/null | awk '
                / connected/ {
                    if ($3 == "primary") { print $1; exit }
                    if (first == "")     { first = $1 }
                }
                END { if (first != "") print first }
            '
            ;;
        wayland)
            wlr-randr 2>/dev/null | awk '
                /^[^ \t]/      { name = $1; next }
                /Enabled: yes/ { if (name != "") { print name; exit } }
            '
            ;;
    esac
}

# Modo FISICO dell'output (WxH marcato "*" nell'elenco modi), stesso helper di
# hifi-ui-resolution.sh: va letto di lì e non dalla geometria corrente perché
# con un --scale-from attivo la geometria riporta l'area di framebuffer
# scalata, non il modo vero.
current_mode() {
    case "$1" in
        x11)
            xrandr --query 2>/dev/null | awk -v out="$2" '
                $1 == out && / connected/ { inblock = 1; next }
                inblock && / connected/   { exit }
                inblock && /\*/ {
                    if ($1 ~ /^[0-9]+x[0-9]+$/) { print $1; exit }
                }
            '
            ;;
        wayland)
            wlr-randr 2>/dev/null | awk -v out="$2" '
                /^[^ \t]/ { inblock = ($1 == out); next }
                !inblock  { next }
                $2 == "px," && /\(current\)/ { print $1; exit }
            '
            ;;
    esac
}

# Per il modo WxH dato, stampa "NATIVO BASSO CORRENTE" (Hz, senza suffissi
# */+). NATIVO è il rate marcato "+" (preferito dall'EDID); se il pannello non
# ne marca uno (visto su alcuni monitor di test) si usa quello marcato "*"
# (quello attivo ora) come riferimento nativo. BASSO è, tra i rate della
# stessa riga, il più alto che sia <=32Hz — margine sopra i 30.00 esatti per
# coprire le varianti 29.97/29.98/29.99 comuni sui pannelli video — ma solo se
# diverso dal nativo; altrimenti stringa vuota (nessuna alternativa reale).
compute_rates() {
    case "$1" in
        x11)
            xrandr --query 2>/dev/null | awk -v out="$2" -v mode="$3" '
                $1 == out && / connected/ { inblock = 1; next }
                inblock && / connected/   { exit }
                inblock && $1 == mode {
                    native = ""; low = ""; current = ""
                    for (i = 2; i <= NF; i++) {
                        tok = $i
                        isCur  = (tok ~ /\*/)
                        isPref = (tok ~ /\+/)
                        gsub(/[*+]/, "", tok)
                        if (tok !~ /^[0-9]+(\.[0-9]+)?$/) continue
                        val = tok + 0
                        if (isCur)  current = tok
                        if (isPref) native = tok
                        if (val > 0 && (top == "" || val > (top + 0))) top = tok
                        if (val > 0 && val <= 32 && (low == "" || val > (low + 0))) low = tok
                    }
                    # Se il pannello non marca un modo preferito (capita, ed è
                    # il caso del monitor di test) si prende il rate PIÙ ALTO
                    # del modo, non quello corrente: prendere il corrente
                    # renderebbe impossibile tornare indietro da "low", perché
                    # dopo il primo cambio il rate basso diventerebbe lui
                    # stesso il riferimento "nativo".
                    if (native == "") native = top
                    if (native == "") native = current
                    if (low == native) low = ""
                    # Placeholder "-" al posto dei campi vuoti: senza, un campo
                    # centrale vuoto sparisce nella riga stampata e il chiamante
                    # leggerebbe il rate CORRENTE come se fosse quello basso,
                    # credendo che il pannello abbia una alternativa che non ha.
                    if (native == "")  native = "-"
                    if (low == "")     low = "-"
                    if (current == "") current = "-"
                    print native, low, current
                    exit
                }
            '
            ;;
        wayland)
            # Su wlr-randr ogni rate è una riga a sé ("1280x720 px, 60.000000 Hz
            # (current)"), quindi si accumula sull'intero blocco dell'output
            # invece che su una sola riga. I marcatori sono "(current)" e
            # "(preferred)" al posto di "*" e "+".
            wlr-randr 2>/dev/null | awk -v out="$2" -v mode="$3" '
                /^[^ \t]/ { inblock = ($1 == out); next }
                !inblock  { next }
                $2 == "px," && $1 == mode {
                    tok = $3
                    if (tok !~ /^[0-9]+(\.[0-9]+)?$/) next
                    val = tok + 0
                    if ($0 ~ /\(current\)/)   current = tok
                    if ($0 ~ /\(preferred\)/) native = tok
                    if (val > 0 && (top == "" || val > (top + 0))) top = tok
                    if (val > 0 && val <= 32 && (low == "" || val > (low + 0))) low = tok
                }
                END {
                    if (native == "") native = top
                    if (native == "") native = current
                    if (low == native) low = ""
                    if (native == "")  native = "-"
                    if (low == "")     low = "-"
                    if (current == "") current = "-"
                    print native, low, current
                }
            '
            ;;
    esac
}

# Stampa "1" se il pannello ha un'alternativa a refresh basso per il suo modo
# fisico corrente, altrimenti "0". Mai fatale.
is_supported() {
    BE="$(backend)"
    [ -n "$BE" ] || { echo 0; return 0; }
    OUT="$(find_output "$BE")"
    [ -n "$OUT" ] || { echo 0; return 0; }
    MODE="$(current_mode "$BE" "$OUT")"
    [ -n "$MODE" ] || { echo 0; return 0; }
    RATES="$(compute_rates "$BE" "$OUT" "$MODE")"
    LOW="$(printf '%s' "$RATES" | awk '{print $2}')"
    [ "$LOW" = "-" ] && LOW=""
    [ -n "$LOW" ] && echo 1 || echo 0
}

apply_pref() {
    BE="$(backend)"
    [ -n "$BE" ] || return 0

    OUT="$(find_output "$BE")"
    # Nessun server grafico in ascolto (headless) o nessun pannello: niente da
    # fare. Mai fatale — invocato dalla sessione di login, un errore qui non
    # deve poter impedire l'avvio del kiosk.
    [ -n "$OUT" ] || return 0

    MODE="$(current_mode "$BE" "$OUT")"
    [ -n "$MODE" ] || return 0

    RATES="$(compute_rates "$BE" "$OUT" "$MODE")"
    NATIVE_RATE="$(printf '%s' "$RATES" | awk '{print $1}')"
    LOW_RATE="$(printf '%s' "$RATES" | awk '{print $2}')"
    CURRENT_RATE="$(printf '%s' "$RATES" | awk '{print $3}')"
    [ "$NATIVE_RATE" = "-" ]  && NATIVE_RATE=""
    [ "$LOW_RATE" = "-" ]     && LOW_RATE=""
    [ "$CURRENT_RATE" = "-" ] && CURRENT_RATE=""
    [ -n "$NATIVE_RATE" ] || return 0

    PREF="$(get_pref)"
    if [ "$PREF" = low ] && [ -n "$LOW_RATE" ]; then
        TARGET_RATE="$LOW_RATE"
    else
        TARGET_RATE="$NATIVE_RATE"
    fi

    # Già come lo vogliamo: non toccare il CRTC (evita uno sfarfallio inutile).
    [ "$CURRENT_RATE" = "$TARGET_RATE" ] && return 0

    case "$BE" in
        wayland) wlr-randr --output "$OUT" --mode "${MODE}@${TARGET_RATE}" >/dev/null 2>&1 || true ;;
        x11)     xrandr --output "$OUT" --mode "$MODE" --rate "$TARGET_RATE" >/dev/null 2>&1 || true ;;
    esac
}

case "${1:-}" in
    get)
        get_pref
        ;;
    supported)
        is_supported
        ;;
    apply)
        apply_pref
        ;;
    set)
        PREF="${2:-}"
        case "$PREF" in
            native|low) ;;
            *) die "usage: $0 set native|low [--live]" ;;
        esac
        LIVE=0
        [ "${3:-}" = "--live" ] && LIVE=1

        # Persistenza atomica (tmp + mv), stesso schema di ui-resolution/display-mode.
        mkdir -p "$(dirname "$REFRESH_FILE")"
        tmp="${REFRESH_FILE}.tmp.$$"
        printf '%s\n' "$PREF" > "$tmp"
        mv -f "$tmp" "$REFRESH_FILE"
        chmod 644 "$REFRESH_FILE" 2>/dev/null || true

        # Niente riavvio di lightdm: cambiare solo il refresh del CRTC non
        # richiede di ricreare la finestra Electron (a differenza di
        # hifi-ui-resolution.sh, che cambia l'area di framebuffer). Si applica
        # quindi subito e in modo sincrono.
        [ "$LIVE" = 1 ] && apply_pref

        echo "$PREF"
        ;;
    *)
        die "usage: $0 get | supported | apply | set native|low [--live]"
        ;;
esac
