# shellcheck shell=sh
# 0056 — le librerie che servono alla seconda interfaccia su schermo (Qt).
#
# PERCHÉ
# Da 2.5.24 l'apparecchio può mostrare due interfacce: quella storica in
# Electron (dentro la sessione di lightdm) e una nuova scritta in Qt 6 Quick
# che disegna diritto su DRM/KMS — niente X, niente compositore. Sulla stessa
# schermata "in riproduzione", coi VU in movimento, misurati sul mini PC di
# collaudo: 3,3 W contro i 4,9 W di Electron, 175 MB di RAM contro 653, e il
# 4K resta fluido (Electron a quella risoluzione arranca).
#
# I FILE della nuova interfaccia arrivano col pacchetto di SISTEMA (finiscono
# in /opt/hifi-qt); qui si installano solo le librerie di sistema che le
# servono, perché è l'unico canale che può usare apt.
#
# COSA NON FA
# Non abilita niente e non cambia l'interfaccia di nessuno: la scelta sta in
# /etc/hifi-player/ui-engine (assente = Electron) e la fa l'utente dalla
# pagina di amministrazione web. Questa migrazione si limita a rendere
# POSSIBILE quella scelta.
#
# Idempotenza: ensure_pkg è un no-op se il pacchetto c'è già; nessun riavvio.
if hifi_suite_is trixie; then
    # Solo i moduli QML importati dal QML più il plugin di piattaforma eglfs:
    # apt tira dentro da sé libQt6Quick/Qml/Gui/Network e il resto.
    # 🚨 kbd serve per chvt: l'unità porta in primo piano il terminale 1 prima
    # di partire e senza quel comando l'interfaccia non partiva affatto
    # (schermo nero). Non era installato di serie e niente altro lo tirava
    # dentro.
    for p in \
        qt6-qpa-plugins \
        kbd \
        qml6-module-qtquick \
        qml6-module-qtquick-window \
        qml6-module-qtquick-effects \
        qml6-module-qtquick-shapes \
        qml6-module-qtquick-vectorimage \
        qml6-module-qtqml-workerscript
    do
        ensure_pkg "$p" || log_warn "interfaccia Qt: manca $p, resterà non selezionabile finché non si installa"
    done
else
    # Su una base diversa da trixie i nomi dei pacchetti non sono questi: si
    # lascia stare invece di installare qualcosa a caso.
    log_info "base non trixie ($(hifi_suite)) — librerie Qt non installate"
fi
