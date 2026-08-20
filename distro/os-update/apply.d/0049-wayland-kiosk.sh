# shellcheck shell=sh
# 0049 — sessione kiosk su Wayland (labwc) al posto di X11.
#
# PERCHÉ
# Il costo GPU della UI su X11 era per due terzi del server X, non dell'app:
# con la scalatura del framebuffer (hifi-ui-resolution.sh) una trasformata RandR
# non identitaria disabilita il page-flip e costringe Xorg a ricomporre e
# riscalare tutto lo schermo ad ogni frame. Un compositor wlroots manda la
# finestra a schermo intero in scanout diretto e sparisce quasi del tutto dal
# profilo GPU. Misurato su Gemini Lake (J4105/UHD 600), stessa scena, stesso
# modo video 1280x720: 1.74 W (X11 + --scale-from) -> 0.81 W (X11 + modo reale)
# -> 0.59 W (Wayland + modo reale), pacchetto da 7.21 W a 5.04 W.
#
# COSA FA
#   - installa labwc (compositor), wlr-randr (configurazione output, usata da
#     hifi-ui-resolution.sh / hifi-ui-refresh.sh sul backend Wayland) e xwayland
#     (ci gira dentro la finestra del kiosk);
#   - installa la sessione (/usr/local/bin/hifi-kiosk-wayland + hifi-kiosk-launch
#     + la voce in /usr/share/wayland-sessions);
#   - crea /run/hifi-player (tmpfiles.d) dove la sessione, che gira come utente
#     hifi, memorizza il modo nativo del pannello;
#   - punta l'autologin di lightdm alla sessione Wayland.
#
# ROLLBACK: la sessione X11 resta installata (~/.xsession, /usr/share/xsessions/
# hifi-kiosk.desktop, Xorg, unclutter). Rimettere user-session=hifi-kiosk nel
# file di autologin riporta tutto com'era, senza disinstallare nulla.

LIGHTDM_CONF=/etc/lightdm/lightdm.conf.d/99-hifi-autologin.conf
HIFI_HOME=/home/hifi

# Prima condizione: esserci davvero un kiosk da spostare. Senza la home di hifi
# e senza l'autologin di lightdm questa non è un'appliance (è il runner della CI,
# o un checkout su una macchina qualsiasi) e la migrazione non deve toccare
# niente — stesso guard di 0001-selfhealing-xsession.sh, e per lo stesso motivo:
# una migrazione che modifica lo stato di una macchina che non è un'appliance
# chiederebbe anche un riavvio che nessuno le ha chiesto.
if [ ! -d "$HIFI_HOME" ] || [ ! -f "$LIGHTDM_CONF" ]; then
    log_info "nessuna sessione kiosk qui ($HIFI_HOME o $LIGHTDM_CONF assenti) — niente da fare"
# Senza il compositor non si va da nessuna parte: se l'installazione fallisce
# (rete assente durante l'OTA) non si tocca niente, la sessione X11 resta al suo
# posto e il prossimo OTA riproverà. Tutto il resto della migrazione sta dentro
# l'ultimo ramo proprio per questo.
elif ! ensure_pkg labwc; then
    log_warn "labwc non installato — sessione kiosk lasciata su X11"
else
    ensure_pkg wlr-randr || log_warn "wlr-randr assente: su Wayland la risoluzione UI resterà quella nativa"
    # XWayland: la finestra del kiosk gira lì dentro, non come client Wayland
    # nativo — vedi il commento su --ozone-platform=x11 in kiosk-wayland-launch
    # (bug del touch in labwc). Senza, la sessione parte e resta a schermo nero.
    ensure_pkg xwayland || log_warn "xwayland assente: il kiosk non partirà finché non si installa"

    if [ -f "$HIFI_PAYLOAD_DIR/files/kiosk-wayland-session" ] && \
       [ -f "$HIFI_PAYLOAD_DIR/files/kiosk-wayland-launch" ]; then
        ensure_file_content /usr/local/bin/hifi-kiosk-wayland 755 root:root \
            < "$HIFI_PAYLOAD_DIR/files/kiosk-wayland-session"
        ensure_file_content /usr/local/bin/hifi-kiosk-launch 755 root:root \
            < "$HIFI_PAYLOAD_DIR/files/kiosk-wayland-launch"
        mkdir -p /usr/share/wayland-sessions
        ensure_file_content /usr/share/wayland-sessions/hifi-kiosk-wayland.desktop 644 root:root \
            < "$HIFI_PAYLOAD_DIR/files/hifi-kiosk-wayland.desktop"
    fi

    # /run/hifi-player: la sessione gira come utente hifi e /run è di root,
    # quindi senza questa regola il modo nativo del pannello non sarebbe
    # memorizzabile e hifi-ui-resolution.sh perderebbe l'idempotenza dopo il
    # primo cambio di modo.
    if [ -f "$HIFI_PAYLOAD_DIR/files/hifi-player-tmpfiles.conf" ]; then
        ensure_file_content /usr/lib/tmpfiles.d/hifi-player.conf 644 root:root \
            < "$HIFI_PAYLOAD_DIR/files/hifi-player-tmpfiles.conf"
        systemd-tmpfiles --create /usr/lib/tmpfiles.d/hifi-player.conf >/dev/null 2>&1 || true
    fi

    # Autologin: dalla sessione X11 a quella Wayland. Solo se il file esiste ed
    # è ancora puntato alla sessione X11 — se l'utente o una migrazione futura
    # l'ha cambiato a mano non lo si sovrascrive.
    if [ -f "$LIGHTDM_CONF" ] && grep -q '^user-session=hifi-kiosk$' "$LIGHTDM_CONF" &&
       [ -x /usr/local/bin/hifi-kiosk-wayland ] && command -v labwc >/dev/null 2>&1; then
        backup_and_edit "$LIGHTDM_CONF" "" 's/^user-session=hifi-kiosk$/user-session=hifi-kiosk-wayland/' || true
    fi

    # La sessione cambia solo al prossimo login: se abbiamo toccato qualcosa
    # serve un riavvio per applicarla davvero.
    if migration_changed; then
        request_reboot
    fi
fi
