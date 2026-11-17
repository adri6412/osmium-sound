# shellcheck shell=sh
# 0065 — mette a posto i file della pagina web "Now Playing" (/np) sugli
# apparecchi aggiornati, non solo su quelli usciti di fabbrica con l'immagine
# nuova.
#
# PERCHÉ
# Il backend di /np è già nel daemon (webui_server.py), ma serve i file statici
# da /opt/hifi-np; senza quella cartella la pagina risponde "Now Playing web
# build not installed". Quei file (build Qt→WebAssembly) viaggiano nel pacchetto
# di SISTEMA, come l'interfaccia Qt. L'installatore di quel pacchetto, però, non
# copia il pacchetto intero: ha un elenco fisso di cartelle, e /opt/hifi-np è
# NUOVA — quindi il primo aggiornamento la scaricava, la verificava e la buttava
# via (stessa trappola di /opt/hifi-qt, vedi 0057).
# L'elenco adesso è corretto, ma la correzione viaggia dentro lo stesso
# pacchetto che deve installare: l'apparecchio applica il pacchetto con la copia
# VECCHIA dello script, quindi da solo si sistemerebbe solo al secondo
# aggiornamento. Questa migrazione chiude il cerchio subito, perché gira DOPO il
# passo di sistema e mentre il pacchetto scaricato è ancora sul disco.
#
# COSA NON FA
# Niente riavvii né riavvii di servizi: sono file statici serviti da
# hifi-webui, già attivo; alla richiesta successiva li legge dal disco.
#
# Idempotenza: copia solo se il pacchetto è ancora lì E la pagina installata
# manca o è diversa da quella appena scaricata; altrimenti è un no-op.
_np_src=''
for _d in /var/lib/hifi-player/update/staged/system/*/root/opt/hifi-np; do
    [ -f "$_d/index.html" ] && _np_src="$_d"
done

if [ -z "$_np_src" ]; then
    log_info "nessun pacchetto di sistema in attesa: niente da sistemare per la pagina Now Playing (/np)"
elif [ -f /opt/hifi-np/index.html ] && cmp -s "$_np_src/index.html" /opt/hifi-np/index.html; then
    log_info "pagina Now Playing (/np) già installata e aggiornata"
else
    mkdir -p /opt/hifi-np
    if cp -af "$_np_src/." /opt/hifi-np/; then
        mark_changed
        log_change "installati i file della pagina web Now Playing (/np) in /opt/hifi-np"
    else
        log_warn "copia dei file della pagina Now Playing (/np) fallita: /np resterà 'not installed'"
    fi
fi
unset _np_src _d
