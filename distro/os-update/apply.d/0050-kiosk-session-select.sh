# shellcheck shell=sh
# 0050 — il protocollo della sessione kiosk lo decide la macchina, a ogni avvio.
#
# PERCHÉ
# 0049 ha spostato la sessione kiosk su labwc/Wayland puntandoci l'autologin di
# lightdm in modo incondizionato: se labwc è installabile, si va su Wayland. La
# condizione giusta però non è "labwc c'è", è "c'è una GPU vera". wlroots
# inizializza il renderer GLES2 via EGL e sul software si rifiuta di partire
# ("Software rendering detected"), ripiegando su pixman: il compositor si
# accende ma XWayland perde glamor e la finestra del kiosk non si disegna —
# schermo nero col solo puntatore, poi la sessione muore e resta il greeter.
# Succede in macchina virtuale (riprodotto su VMware Workstation e su
# QEMU/bochs) mentre lo stesso identico sistema su un PC fisico parte bene.
#
# COSA FA
# Installa il selettore (/usr/local/sbin/hifi-kiosk-session.sh) e la sua unità,
# che gira prima di lightdm a ogni avvio e scrive lo user-session in un
# frammento a parte, 99-hifi-session.conf: i file di lightdm.conf.d si caricano
# in ordine alfabetico e l'ultimo vince, quindi da qui in poi è LUI a comandare
# e quello che 0049 ha scritto in 99-hifi-autologin.conf non conta più (0049
# resta com'è: su un'unità che non riceve mai questa migrazione — nessuna, ma
# la catena è cumulativa e va letta come tale — il suo comportamento è ancora
# quello giusto).
#
# Sulle unità fisiche non cambia niente di visibile: la sonda trova EGL
# hardware e la sessione resta quella Wayland. Su una VM si torna a X11 al
# primo riavvio, che è la sessione che lì funziona.
#
# ROLLBACK/forzatura: "wayland" o "x11" in /etc/hifi-player/kiosk-session
# vincono sulla decisione automatica.

LIGHTDM_CONF_D=/etc/lightdm/lightdm.conf.d

# Stesso guard di 0049: senza l'autologin di lightdm questa non è un'appliance
# (è il runner della CI o un checkout qualsiasi) e non c'è nessuna sessione
# kiosk da configurare.
if [ ! -f "$LIGHTDM_CONF_D/99-hifi-autologin.conf" ]; then
    log_info "nessuna sessione kiosk qui ($LIGHTDM_CONF_D/99-hifi-autologin.conf assente) — niente da fare"
elif [ ! -f "$HIFI_PAYLOAD_DIR/files/kiosk-session-select" ] || \
     [ ! -f "$HIFI_PAYLOAD_DIR/files/hifi-kiosk-session.service" ]; then
    log_warn "selettore di sessione assente dal payload — sessione kiosk lasciata com'è"
else
    ensure_file_content /usr/local/sbin/hifi-kiosk-session.sh 755 root:root \
        < "$HIFI_PAYLOAD_DIR/files/kiosk-session-select"
    ensure_file_content /etc/systemd/system/hifi-kiosk-session.service 644 root:root \
        < "$HIFI_PAYLOAD_DIR/files/hifi-kiosk-session.service"

    if migration_changed; then
        systemctl daemon-reload 2>/dev/null || true
    fi

    state=$(systemctl is-enabled hifi-kiosk-session.service 2>/dev/null) || state=""
    if [ "$state" != "enabled" ]; then
        systemctl enable hifi-kiosk-session.service >/dev/null 2>&1 \
            && mark_changed "enabled hifi-kiosk-session.service"
    fi

    # Si esegue subito, così il frammento esiste già prima del prossimo avvio di
    # lightdm anche senza riavviare: lo script è idempotente e non tocca la
    # sessione in corso (scrive solo la configurazione del prossimo login).
    if [ -x /usr/local/sbin/hifi-kiosk-session.sh ]; then
        /usr/local/sbin/hifi-kiosk-session.sh >/dev/null 2>&1 || \
            log_warn "prima esecuzione del selettore fallita — deciderà al prossimo avvio"
    fi

    # Se la scelta di adesso è diversa dalla sessione in esecuzione serve un
    # riavvio perché diventi effettiva (la sessione cambia solo al login).
    if [ -f "$LIGHTDM_CONF_D/99-hifi-session.conf" ]; then
        chosen=$(sed -n 's/^user-session=//p' "$LIGHTDM_CONF_D/99-hifi-session.conf" | head -n1)
        current=$(sed -n 's/^user-session=//p' "$LIGHTDM_CONF_D/99-hifi-autologin.conf" | head -n1)
        if [ -n "$chosen" ] && [ "$chosen" != "$current" ]; then
            log_info "sessione kiosk: $current -> $chosen"
            request_reboot
        fi
    fi
fi
