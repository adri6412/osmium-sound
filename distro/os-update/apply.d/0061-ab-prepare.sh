# shellcheck shell=sh
# 0061 — prerequisiti dello schema A/B (RAUC) sugli apparecchi già installati.
#
# PERCHÉ
# Il nuovo sistema di aggiornamento tiene due copie del sistema (slot A e B) e
# passa dall'una all'altra a ogni aggiornamento, con ritorno automatico se la
# nuova non parte. Gli apparecchi in campo hanno una root sola che riempie il
# disco: la conversione (restringimento, nuove partizioni, selettore GRUB
# sulla ESP) la fanno gli script hifi-ab-*.sh arrivati col pacchetto di
# sistema, dentro il flusso "Aggiorna ora". Questa migrazione mette solo i
# prerequisiti che richiedono root e apt: il pacchetto rauc e l'abilitazione
# delle unità che restano inerti finché il layout A/B non esiste davvero.
#
# COSA NON FA
# Non tocca l'initrd di produzione, non tocca GRUB, non tocca la ESP, non
# riavvia: tutto questo avviene solo dopo le pre-verifiche
# (hifi-ab-precheck.sh) e con un initrd dedicato. Un apparecchio che non passa
# le pre-verifiche resta esattamente com'è.
#
# Idempotente: ensure_pkg è un no-op a pacchetto presente; le unità vengono
# abilitate solo se esistono e non lo sono già. Nessun request_reboot.
if command -v apt-get >/dev/null 2>&1 && [ -f /etc/debian_version ]; then
    ensure_pkg rauc || log_warn "rauc non installabile ora: la conversione A/B resterà in attesa"
    ensure_pkg rauc-service || true
fi

for u in hifi-rauc-config.service hifi-ab-finish.service hifi-boot-health.service hifi-boot-watchdog.timer; do
    [ -f "/etc/systemd/system/$u" ] || continue
    if ! systemctl is-enabled --quiet "$u" 2>/dev/null; then
        if systemctl enable "$u" >/dev/null 2>&1; then
            mark_changed "abilitata $u"
        else
            log_warn "impossibile abilitare $u"
        fi
    fi
done
unset u
