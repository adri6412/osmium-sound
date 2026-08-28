# shellcheck shell=sh
# 0057 — mette a posto i file della seconda interfaccia (Qt) sugli apparecchi
# aggiornati, non solo su quelli usciti di fabbrica con l'immagine nuova.
#
# PERCHÉ
# I file della nuova interfaccia viaggiano nel pacchetto di SISTEMA e vanno in
# /opt/hifi-qt. L'installatore di quel pacchetto, però, non copia il pacchetto
# intero: ha un elenco fisso di cartelle da installare, e /opt/hifi-qt non
# c'era. Risultato: il primo aggiornamento con la nuova interfaccia la
# scaricava, la verificava e poi la buttava via, e nella pagina web non
# compariva niente da scegliere (giustamente: la scelta appare solo se i file
# ci sono davvero).
# L'elenco adesso è corretto, ma la correzione viaggia dentro lo stesso
# pacchetto che deve installare: l'apparecchio applica il pacchetto con la
# copia VECCHIA dello script, quindi da solo si sistemerebbe solo al secondo
# aggiornamento. Questa migrazione chiude il cerchio subito, perché gira DOPO
# il passo di sistema e mentre il pacchetto scaricato è ancora sul disco.
#
# COSA NON FA
# Non abilita e non sceglie niente: la scelta resta in /etc/hifi-player/ui-engine
# (assente = Electron) e la fa l'utente dalla pagina di amministrazione web.
#
# Idempotenza: copia solo se il pacchetto è ancora lì E il programma installato
# manca o è diverso da quello appena scaricato; altrimenti è un no-op che non
# segnala nessun cambiamento e non chiede riavvii.
_qt_src=''
for _d in /var/lib/hifi-player/update/staged/system/*/root/opt/hifi-qt; do
    [ -x "$_d/hifi-qt" ] && _qt_src="$_d"
done

if [ -z "$_qt_src" ]; then
    log_info "nessun pacchetto di sistema in attesa: niente da sistemare per l'interfaccia Qt"
elif [ -x /opt/hifi-qt/hifi-qt ] && cmp -s "$_qt_src/hifi-qt" /opt/hifi-qt/hifi-qt; then
    log_info "interfaccia Qt già installata e aggiornata"
else
    mkdir -p /opt/hifi-qt
    if cp -af "$_qt_src/." /opt/hifi-qt/; then
        mark_changed
        log_change "installati i file della seconda interfaccia (Qt) in /opt/hifi-qt"
    else
        log_warn "copia dei file dell'interfaccia Qt fallita: resterà non selezionabile"
    fi
fi
unset _qt_src _d
