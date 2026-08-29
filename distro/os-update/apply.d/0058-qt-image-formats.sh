# shellcheck shell=sh
# 0058 — copertine in WebP (e TIFF, e altri formati meno comuni) nell'interfaccia Qt.
#
# Qt sa leggere da sé solo PNG, JPEG, GIF e poco altro: tutto il resto sta nei
# plugin di qt6-image-formats-plugins, che non era installato. Chromium invece
# decodifica il WebP da solo, quindi le stesse copertine si vedevano nella
# vecchia interfaccia e restavano NERE in quella Qt — una differenza che
# sembrava un difetto di disegno e invece era un formato non riconosciuto.
#
# Idempotenza: ensure_pkg è un no-op se il pacchetto c'è già; nessun riavvio,
# i plugin vengono caricati alla prossima immagine da decodificare.
if hifi_suite_is trixie; then
    ensure_pkg qt6-image-formats-plugins \
        || log_warn "interfaccia Qt: manca qt6-image-formats-plugins, le copertine WebP resteranno vuote"
else
    log_info "base non trixie ($(hifi_suite)) — plugin dei formati immagine non installati"
fi
