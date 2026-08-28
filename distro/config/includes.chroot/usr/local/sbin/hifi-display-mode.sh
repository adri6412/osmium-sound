#!/bin/sh
# shellcheck shell=sh
# HiFi Player — display-mode switch (GUI touchscreen kiosk <-> headless).
#
# The appliance ships GUI-first: the default systemd target is graphical.target,
# which pulls in LightDM -> autologin -> the Electron kiosk. "Headless" here is a
# real, persisted software mode: the box runs on multi-user.target with no X
# server, controlled remotely (companion app, Lyrion :9000, sources :8080). All
# hifi-* daemons + squeezelite + Lyrion are WantedBy=multi-user.target, so they
# keep running in BOTH modes — only the on-screen GUI stack differs.
#
# State lives in /etc/hifi-player/display-mode ("gui" | "headless"). ABSENT means
# gui — that default is the fleet-safety invariant: an existing configured unit
# that never wrote the file must never drift into headless on an OS update.
#
# We switch by flipping the default target (systemctl set-default). The
# gui/headless switch does NOT enable/disable lightdm directly: lightdm is only
# ever pulled in by graphical.target, so changing the default target is
# sufficient and never fights the build-time enable or an OS-OTA migration.
# (The engine switch below is the one exception, and it has to be: choosing
# WHICH of the two on-screen interfaces graphical.target pulls in is exactly
# an enable/disable of their two units.)
#
# Da 2.5.24 l'apparecchio ha DUE interfacce su schermo e questo script sceglie
# anche quale delle due parte ("engine"):
#   electron -> lightdm -> sessione kiosk -> app Electron (quella storica)
#   qt       -> hifi-qt.service, che disegna diritto su DRM/KMS (eglfs), senza
#               X ne' compositore
# Le due si escludono: hifi-qt.service ha Conflicts=lightdm.service. La scelta
# sta in /etc/hifi-player/ui-engine ("electron" | "qt"); ASSENTE = electron,
# stessa invariante di sicurezza della modalita' schermo (un apparecchio gia'
# configurato non deve cambiare interfaccia da solo per un aggiornamento).
# In headless non parte nessuna delle due: il bersaglio e' multi-user.target.
#
# Usage:
#   hifi-display-mode.sh get                 -> prints "gui" or "headless"
#   hifi-display-mode.sh set gui|headless [--live]
#   hifi-display-mode.sh engine              -> prints "electron" or "qt"
#   hifi-display-mode.sh engine set electron|qt [--live]
#
# --live also switches the RUNNING session (systemctl isolate) after a short
# delay, so a caller (api_server.py) can flush its HTTP response before X dies.
# Without --live the change only takes effect at the next boot.

set -eu

# NOTE: deliberately NOT redirected to /var/log/hifi via hifi-log.sh — this
# script's stdout IS its data channel (api_server.py's get_display_mode()
# captures and parses the "gui"/"headless" line straight from subprocess
# stdout), not just diagnostic chatter. Redirecting it would silently break
# the display-mode toggle.
MODE_FILE=/etc/hifi-player/display-mode
ENGINE_FILE=/etc/hifi-player/ui-engine
QT_UI_BIN=/opt/hifi-qt/hifi-qt

# L'ambiente X della sessione kiosk (autologin hifi = :0), solo per la ricerca
# dell'output da spegnere in `set headless --live` qui sotto — stesso schema
# di hifi-ui-resolution.sh.
: "${DISPLAY:=:0}"
: "${XAUTHORITY:=/home/hifi/.Xauthority}"
: "${XDG_RUNTIME_DIR:=/run/user/1000}"
: "${WAYLAND_DISPLAY:=wayland-0}"
export DISPLAY XAUTHORITY XDG_RUNTIME_DIR WAYLAND_DISPLAY

die() { echo "$1" >&2; exit 1; }

# Output da spegnere: TUTTI quelli connessi, non solo il "primary". Su alcune
# macchine (visto su un mini PC con uscita USB-C) più connettori risultano
# "connected" contemporaneamente -- una porta fantasma rilevata come attiva
# pur senza monitor reale, oltre a quella con lo schermo vero -- e spegnere
# solo il primo/primary lasciava lo schermo reale nero ma retroilluminato
# perché il comando andava sul connettore sbagliato. Spegnerli tutti è
# corretto in headless: non deve restare acceso nessun output video.
# Rilevato dinamicamente ad ogni chiamata (mai hardcoded) perché non è detto
# sia lo stesso connettore su tutti i dispositivi. Funziona su entrambi i
# server grafici (xrandr su X11, wlr-randr sulla sessione kiosk Wayland) e
# stampa nulla se non c'è nessuno dei due in ascolto o nessun output.
find_outputs() {
    if [ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ] && command -v wlr-randr >/dev/null 2>&1; then
        wlr-randr 2>/dev/null | awk '/^[^ \t]/ { print $1 }'
    elif command -v xrandr >/dev/null 2>&1; then
        xrandr --query 2>/dev/null | awk '/ connected/ { print $1 }'
    fi
}

# Spegne un output, sul server grafico che è in ascolto.
output_off() {
    if [ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ] && command -v wlr-randr >/dev/null 2>&1; then
        wlr-randr --output "$1" --off >/dev/null 2>&1 || true
    else
        xrandr --output "$1" --off >/dev/null 2>&1 || true
    fi
}

target_for() {
    case "$1" in
        gui)      echo graphical.target ;;
        headless) echo multi-user.target ;;
        *)        die "invalid mode: $1" ;;
    esac
}

# Vero solo se la seconda interfaccia puo' DAVVERO partire: il programma
# (pacchetto di sistema) piu' le librerie Qt (pacchetto OS). Arrivano da due
# canali diversi e possono arrivare separate; con una meta' sola il programma
# parte e muore subito, lasciando lo schermo nero. Il modulo grafico per
# DRM/KMS e il modulo QML di base non sono librerie collegate, quindi vanno
# cercati a parte.
qt_ui_ready() {
    [ -x "$QT_UI_BIN" ] || return 1
    for _q in /usr/lib/*/qt6; do
        if [ -e "$_q/plugins/platforms/libqeglfs.so" ] && [ -e "$_q/qml/QtQuick/libqtquick2plugin.so" ]; then
            return 0
        fi
    done
    return 1
}

get_engine() {
    if [ -f "$ENGINE_FILE" ] && [ "$(cat "$ENGINE_FILE" 2>/dev/null)" = qt ]; then
        echo qt
    else
        echo electron
    fi
}

# Abilita l'unita' dell'interfaccia scelta e disabilita l'altra. Non tocca il
# bersaglio di avvio: entrambe sono WantedBy=graphical.target, quindi in
# headless restano ferme comunque.
apply_engine() {
    _eng="$1"
    _live="${2:-0}"
    if [ "$_eng" = qt ]; then
        systemctl disable lightdm >/dev/null 2>&1 || true
        systemctl enable hifi-qt >/dev/null 2>&1 || true
    else
        systemctl disable hifi-qt >/dev/null 2>&1 || true
        systemctl enable lightdm >/dev/null 2>&1 || true
    fi
    [ "$_live" = 1 ] || return 0
    [ "$(get_mode)" = gui ] || return 0
    # Il cambio a caldo si fa in un'unita' transitoria dopo un attimo: chi
    # chiama (api_server / webui) sta rispondendo a una richiesta HTTP e, se
    # l'interfaccia che si sta spegnendo e' quella che l'ha inviata, la
    # risposta deve uscire prima.
    if [ "$_eng" = qt ]; then
        _cmd="systemctl stop lightdm; systemctl start hifi-qt"
    else
        _cmd="systemctl stop hifi-qt; systemctl start lightdm"
    fi
    if command -v systemd-run >/dev/null 2>&1; then
        systemd-run --collect --description="HiFi UI engine switch" \
            /bin/sh -c "sleep 1; $_cmd" >/dev/null 2>&1 || true
    else
        /bin/sh -c "$_cmd" >/dev/null 2>&1 || true
    fi
}

get_mode() {
    if [ -f "$MODE_FILE" ] && [ "$(cat "$MODE_FILE" 2>/dev/null)" = headless ]; then
        echo headless
    else
        echo gui
    fi
}

case "${1:-}" in
    get)
        get_mode
        ;;
    set)
        MODE="${2:-}"
        [ "$MODE" = gui ] || [ "$MODE" = headless ] || die "usage: $0 set gui|headless [--live]"
        LIVE=0
        [ "${3:-}" = "--live" ] && LIVE=1
        TARGET="$(target_for "$MODE")"

        # Passaggio live a headless: senza questo, il monitor resta acceso con
        # un segnale nero non appena X muore (multi-user.target non ha più
        # nulla che gestisca il DPMS). Spegniamo l'uscita video esplicitamente
        # ORA, mentre X è ancora vivo (xrandr non funziona senza), un attimo
        # prima che venga abbattuto sotto — così il pannello va davvero in
        # standby invece di restare nero e retroilluminato. Nessuna azione
        # equivalente serve nel verso opposto: la sessione X che riparte al
        # ritorno in modalità gui riaccende da sé ogni output connesso (comportamento
        # di default del driver), quindi non c'è uno stato da "riabilitare".
        if [ "$MODE" = headless ] && [ "$LIVE" = 1 ]; then
            for OUT in $(find_outputs); do
                output_off "$OUT"
            done
        fi

        # Persist atomically (tmp + mv), same pattern as pointer-enabled.
        mkdir -p "$(dirname "$MODE_FILE")"
        tmp="${MODE_FILE}.tmp.$$"
        printf '%s\n' "$MODE" > "$tmp"
        mv -f "$tmp" "$MODE_FILE"

        # Persisted boot target.
        if [ "$(systemctl get-default 2>/dev/null)" != "$TARGET" ]; then
            systemctl set-default "$TARGET" >/dev/null 2>&1 || true
        fi

        if [ "$LIVE" = 1 ]; then
            # Isolate the target in a detached one-shot AFTER a short delay, so
            # the caller's HTTP response is flushed before the GUI (which hosts
            # the very UI that issued this request) is torn down. Best-effort:
            # if systemd-run is unavailable the boot target change still applies
            # at the next reboot.
            if command -v systemd-run >/dev/null 2>&1; then
                # Auto-generated transient unit name (no fixed --unit) so back-to-
                # back switches can't collide on an already-existing unit.
                systemd-run --collect --description="HiFi display-mode live switch" \
                    /bin/sh -c "sleep 1; systemctl isolate $TARGET" >/dev/null 2>&1 || true
            fi
        fi

        echo "$MODE"
        ;;
    engine)
        case "${2:-}" in
            ''|get)
                get_engine
                ;;
            set)
                ENG="${3:-}"
                [ "$ENG" = electron ] || [ "$ENG" = qt ] || die "usage: $0 engine set electron|qt [--live]"
                LIVE=0
                [ "${4:-}" = "--live" ] && LIVE=1
                # Non si sceglie un'interfaccia che non c'e': su un apparecchio
                # che non ha ancora ricevuto il pacchetto Qt il passaggio
                # lascerebbe lo schermo nero al riavvio.
                if [ "$ENG" = qt ] && ! qt_ui_ready; then
                    die "interfaccia Qt non installata o incompleta (serve $QT_UI_BIN e le librerie Qt 6)"
                fi
                mkdir -p "$(dirname "$ENGINE_FILE")"
                tmp="${ENGINE_FILE}.tmp.$$"
                printf '%s\n' "$ENG" > "$tmp"
                mv -f "$tmp" "$ENGINE_FILE"
                apply_engine "$ENG" "$LIVE"
                echo "$ENG"
                ;;
            *)
                die "usage: $0 engine [get] | engine set electron|qt [--live]"
                ;;
        esac
        ;;
    *)
        die "usage: $0 get | set gui|headless [--live] | engine [get] | engine set electron|qt [--live]"
        ;;
esac
