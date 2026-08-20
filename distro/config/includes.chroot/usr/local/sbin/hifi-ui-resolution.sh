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
# DUE BACKEND
# Lo script parla sia con X11 (xrandr) sia con Wayland (wlr-randr, compositore
# wlroots — labwc nella sessione kiosk), scegliendo da sé in base al socket che
# trova. Le due strade qui sotto valgono su X11; su Wayland esiste solo la
# prima, perché la seconda lì non serve (vedi in fondo).
#
# COME — 1) un MODO VIDEO REALE, quando il pannello ne espone uno adatto
#     xrandr    --output <OUT> --mode <W>x<H> --scale 1x1     (X11)
#     wlr-randr --output <OUT> --mode <W>x<H>                 (Wayland)
# È la strada preferita: il framebuffer è piccolo E lo scaler è quello del
# pannello/TV, quindi la GPU non tocca palla. A valle, screen.getPrimaryDisplay()
# .size ritorna la dimensione ridotta, la BrowserWindow nasce di quella
# dimensione e ScaledCanvas calcola uno zoom più basso — Chromium rasterizza
# 921k pixel invece di 2.07M (1080p) o 8.3M (4K).
#
# COME — 2) `--scale-from`, solo come RIPIEGO
#     xrandr --output <OUT> --mode <NATIVO> --scale-from <W>x<H>
# Serve sui pannelli che NON hanno un modo reale con il proprio rapporto
# d'aspetto sotto al cap (ultrawide 21:9, 16:10, ...), dove un modo 16:9 uscirebbe
# deformato dallo scaler del pannello. Qui il modo video resta quello nativo e
# cambia solo l'area di framebuffer mappata sull'uscita.
#
# ATTENZIONE, è la ragione per cui esiste la strada 1): `--scale-from` NON è
# "scalatura gratis in scansione" come si potrebbe pensare. Con modesetting +
# glamor una trasformata RandR non identitaria disabilita il page-flip e obbliga
# il server X a ricomporre e riscalare via GPU l'INTERO schermo ad ogni frame.
# Misurato su Gemini Lake (J4105/UHD 600, pannello 3440x1440, Now Playing con VU
# meter, `intel_gpu_top -J` per-processo):
#
#   framebuffer 1720x720 --scale-from  ->  Xorg ~52% RCS + Electron ~26%, 1.80 W GPU
#   modo reale 1280x720                ->  Xorg ~13% RCS,                 0.89 W GPU
#
# cioè due terzi del carico GPU erano del server X, non dell'app: lo script
# risparmiava pixel a Chromium e ne addossava il quadruplo a Xorg. Da qui la
# preferenza per un modo reale ogni volta che ce n'è uno con l'aspect giusto.
#
# SU WAYLAND IL RIPIEGO NON C'È, di proposito: il compositor manda la finestra
# a schermo intero in scanout diretto, quindi disegnare a risoluzione NATIVA
# costa meno di quanto costi su X11 il framebuffer ridotto con la trasformata
# (misurato, stessa scena: 1.21 W nativo su Wayland contro 1.87 W con
# --scale-from su X11). Su un pannello senza un modo reale adatto si lascia
# semplicemente il nativo.
#
# ASPECT RATIO: sia `--scale-from` sia lo scaler del pannello stirano fino a
# riempire TUTTO lo schermo, quindi il target non può essere la costante
# 1280x720 o la UI esce deformata. Per la strada 1) si scarta ogni modo il cui
# rapporto non combaci (±1%) con quello del pannello; per la 2) si fissa
# l'ALTEZZA al cap e si ricava la larghezza dal rapporto del pannello (allineata
# a multipli di 8 per lo stride del driver): 1920x1080 -> 1280x720 (modo reale),
# 1920x1200 -> 1152x720 (scale-from), 3840x2160 -> 1280x720 (modo reale).
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

# Modo NATIVO del pannello, memorizzato a runtime. Serve da quando `apply` può
# cambiare davvero il modo video: il modo corrente non è più una fonte
# affidabile per "quanto è grande il pannello", perché alla seconda esecuzione
# leggerebbe il modo ridotto appena impostato e si convincerebbe che il
# pannello è piccolo (rimpicciolendolo ancora, o non sapendo più tornare al
# nativo quando l'utente sceglie "Nativa"). Sta in /run e non in /etc perché è
# una proprietà del pannello collegato ORA: si ricostruisce ad ogni boot, e a
# scriverlo è la prima esecuzione dopo l'avvio del server X — che parte sempre
# sul modo preferito da EDID, prima che questo script tocchi qualcosa.
PANEL_DIR=/run/hifi-player
PANEL_FILE=$PANEL_DIR/ui-panel-mode

# Sotto quale altezza fisica "auto" non tocca nulla. 800 e non 720: lascia
# intatti il touchscreen 1024x600, i pannelli 1366x768 e i 1280x800, dove il
# guadagno sarebbe marginale e l'unica cosa percepibile sarebbe la perdita di
# nitidezza.
AUTO_MIN_HEIGHT=800

die() { echo "$1" >&2; exit 1; }

# L'ambiente dei due server grafici. Impostato con dei default e non forzato,
# così lo script funziona sia invocato da root (api_server, che non ha niente in
# ambiente) sia già dentro la sessione dell'utente hifi (che ce l'ha giusto).
: "${DISPLAY:=:0}"
: "${XAUTHORITY:=/home/hifi/.Xauthority}"
: "${XDG_RUNTIME_DIR:=/run/user/1000}"
: "${WAYLAND_DISPLAY:=wayland-0}"
export DISPLAY XAUTHORITY XDG_RUNTIME_DIR WAYLAND_DISPLAY

get_pref() {
    pref="$(cat "$RES_FILE" 2>/dev/null | tr -d '[:space:]')" || pref=""
    case "$pref" in
        720|1080|native) echo "$pref" ;;
        *)               echo auto ;;   # assente o illeggibile => auto
    esac
}

# Quale server grafico è in ascolto ORA. Wayland vince quando il suo socket
# c'è: durante la migrazione una macchina può avere installati entrambi gli
# stack, ma ne gira uno solo per volta.
backend() {
    if [ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ] && command -v wlr-randr >/dev/null 2>&1; then
        echo wayland
    elif command -v xrandr >/dev/null 2>&1; then
        echo x11
    fi
}

# Output da pilotare: su X11 il primo connesso preferendo quello "primary", su
# Wayland il primo abilitato. Stampa nulla (e basta) se non c'è nessun server
# grafico o nessun pannello collegato.
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
                /^[^ \t]/            { name = $1; next }
                /Enabled: yes/       { if (name != "") { print name; exit } }
            '
            ;;
    esac
}

# Stato dell'output, in un formato normalizzato che rende tutto il resto dello
# script indipendente dal backend:
#
#   CUR  <WxH>   modo video attuale
#   GEOM <WxH>   area di framebuffer mappata sull'uscita — su X11 può essere più
#                piccola del modo (è quello che fa `--scale-from`), su Wayland
#                il concetto non esiste e coincide sempre con CUR
#   MODE <WxH>   una riga per ogni modo disponibile
#
# Il modo attuale va letto dalla lista modi (la riga marcata "*" su xrandr,
# "(current)" su wlr-randr) e NON dalla geometria: con un transform attivo la
# geometria riporta l'area scalata mentre il modo resta quello vero, e
# confonderli renderebbe `apply` non idempotente.
query_state() {
    be="$1"; out="$2"
    case "$be" in
        x11)
            xrandr --query 2>/dev/null | awk -v out="$out" '
                $1 == out && / connected/ {
                    for (i = 2; i <= NF; i++)
                        if ($i ~ /^[0-9]+x[0-9]+\+[0-9]+\+[0-9]+$/) {
                            g = $i; sub(/\+.*/, "", g); print "GEOM " g
                        }
                    inblock = 1; next
                }
                inblock && / connected/ { exit }        # inizio di un altro output
                inblock && $1 ~ /^[0-9]+x[0-9]+$/ {
                    print "MODE " $1
                    if ($0 ~ /\*/) print "CUR " $1
                }
            '
            ;;
        wayland)
            wlr-randr 2>/dev/null | awk -v out="$out" '
                /^[^ \t]/ { inblock = ($1 == out); next }
                !inblock  { next }
                $2 == "px," {
                    print "MODE " $1
                    if ($0 ~ /\(current\)/) { print "CUR " $1; print "GEOM " $1 }
                }
            '
            ;;
    esac
}

# Estrattori sullo stato normalizzato (STATE, letto una volta sola per
# esecuzione: interrogare il server ad ogni domanda costerebbe un fork per
# campo e, peggio, potrebbe vedere stati diversi a metà ragionamento).
state_field() { printf '%s\n' "$STATE" | awk -v k="$1" '$1 == k { print $2; exit }'; }
state_modes() { printf '%s\n' "$STATE" | awk '$1 == "MODE" { print $2 }'; }

# Il modo <W>x<H> esiste ancora tra quelli dell'output? (pannello staccato e
# sostituito a caldo, TV diversa sulla stessa presa, ...)
has_mode() { state_modes | grep -qx "$1"; }

# Modo nativo del pannello: quello memorizzato in PANEL_FILE se è ancora un modo
# valido per questo output, altrimenti quello corrente — che alla prima
# esecuzione dopo l'avvio del server grafico è per definizione il preferito da
# EDID.
panel_mode() {
    cur="$1"
    saved="$(cat "$PANEL_FILE" 2>/dev/null | tr -d '[:space:]')" || saved=""
    case "$saved" in
        [0-9]*x[0-9]*)
            if has_mode "$saved"; then
                echo "$saved"
                return 0
            fi
            ;;
    esac
    # Mai fatale: se /run/hifi-player non è scrivibile (manca la regola
    # tmpfiles.d e stiamo girando come utente hifi) si continua a lavorare con
    # il modo corrente, esattamente come prima che questo file esistesse.
    mkdir -p "$PANEL_DIR" 2>/dev/null || true
    printf '%s\n' "$cur" > "$PANEL_FILE" 2>/dev/null || true
    echo "$cur"
}

# Il miglior modo REALE per rimpicciolire il framebuffer senza far lavorare la
# GPU: il più grande tra quelli che
#   - stanno sotto al cap in altezza,
#   - sono più piccoli del pannello,
#   - hanno lo stesso rapporto d'aspetto (±1%, che assorbe i rapporti "quasi"
#     16:9 tipo 1366x768) — altrimenti lo scaler del pannello deforma la UI,
#   - non scendono sotto il canvas di disegno 1024x600 (src/components/
#     ScaledCanvas.jsx): sotto quella soglia la UI verrebbe RIMPICCIOLITA
#     invece che ingrandita, perdendo dettaglio per davvero e non solo
#     nitidezza.
# Stampa nulla se non ce n'è nessuno — ed è il caso normale sui pannelli 21:9 e
# 16:10.
best_real_mode() {
    state_modes | awk -v pw="$1" -v ph="$2" -v th="$3" '
        {
            split($1, d, "x")
            w = d[1] + 0; h = d[2] + 0
            if (h < 1 || h > th)     next
            if (w >= pw && h >= ph)  next
            if (w < 1024 || h < 600) next
            pa = pw / ph; ar = w / h
            if (ar > pa * 1.01 || ar < pa * 0.99) next
            if (w * h > best_px) { best_px = w * h; best = $1 }
        }
        END { if (best != "") print best }
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
    BE="$(backend)"
    [ -n "$BE" ] || return 0

    OUT="$(find_output "$BE")"
    # Nessun server grafico in ascolto (modalità headless), o nessun pannello
    # collegato: niente da fare. Mai fatale — questo script è invocato dalla
    # sessione di login e un errore qui non deve poter impedire l'avvio del
    # kiosk.
    [ -n "$OUT" ] || return 0

    STATE="$(query_state "$BE" "$OUT")"
    CUR="$(state_field CUR)"
    [ -n "$CUR" ] || return 0
    MODE="$(panel_mode "$CUR")"
    PW="${MODE%x*}"
    PH="${MODE#*x}"
    case "$PW$PH" in *[!0-9]*) return 0 ;; esac

    PREF="$(get_pref)"
    TH="$(cap_for "$PREF" "$PH")"

    # Stato voluto, come coppia (modo video, area di framebuffer):
    #   - nessun cap        -> modo nativo, nessuna scala
    #   - c'è un modo reale -> quel modo, nessuna scala  (strada 1, gratis)
    #   - altrimenti        -> modo nativo + --scale-from (strada 2, solo X11)
    WANT_MODE="$MODE"
    WANT_GEOM="$MODE"
    if [ -n "$TH" ]; then
        REAL="$(best_real_mode "$PW" "$PH" "$TH")"
        if [ -n "$REAL" ]; then
            WANT_MODE="$REAL"
            WANT_GEOM="$REAL"
        elif [ "$BE" = x11 ]; then
            TARGET="$(target_width "$PW" "$PH" "$TH")x${TH}"
            # Non ingrandire mai il framebuffer oltre il pannello.
            [ "${TARGET%x*}" -lt "$PW" ] && WANT_GEOM="$TARGET"
        fi
        # Su Wayland il ripiego non esiste ed è voluto: il compositor manda la
        # finestra in scanout diretto, quindi il nativo costa MENO di quanto
        # costi su X11 il framebuffer ridotto (misurato su Gemini Lake, stessa
        # scena: 1.21 W nativo su Wayland contro 1.87 W con --scale-from su
        # X11). Su un pannello senza un modo reale adatto si lascia il nativo e
        # si guadagna comunque.
    fi

    # Già come lo vogliamo: non toccare il CRTC (evita uno sfarfallio inutile ad
    # ogni login, e sui pannelli che non vanno ridimensionati affatto evita di
    # riprogrammare il modo — che azzererebbe anche il --rate impostato da
    # hifi-ui-refresh.sh, l'unica altra cosa che tocca questo output).
    if [ "$CUR" = "$WANT_MODE" ] && [ "$(state_field GEOM)" = "$WANT_GEOM" ]; then
        return 0
    fi

    case "$BE" in
        wayland)
            wlr-randr --output "$OUT" --mode "$WANT_MODE" >/dev/null 2>&1 || true
            ;;
        x11)
            if [ "$WANT_GEOM" = "$WANT_MODE" ]; then
                # Framebuffer = modo: nessuna trasformata. `--scale 1x1` è il
                # modo documentato di annullare uno `--scale-from`/`--scale`
                # precedente, e va passato insieme a `--mode` perché si arriva
                # qui anche tornando da un modo ridotto (utente che sceglie
                # "Nativa") o passando dal ripiego alla strada 1.
                xrandr --output "$OUT" --mode "$WANT_MODE" --scale 1x1 >/dev/null 2>&1 || true
            else
                xrandr --output "$OUT" --mode "$WANT_MODE" --scale-from "$WANT_GEOM" >/dev/null 2>&1 || true
            fi
            ;;
    esac
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
            # sessione grafica rifà tutto in ordine: al login lo script di
            # sessione (~/.xsession su X11, hifi-kiosk-launch su Wayland)
            # richiama `apply` e Electron nasce già della dimensione giusta. È anche ciò
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
