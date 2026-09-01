#!/bin/sh
# Osmium Sound — sulla root legacy appena convertita (finish fatto), chiede
# all'API di avviare l'aggiornamento: il piano conterrà lo step `image`
# (RAUC configurato) e il sequencer installerà l'immagine nello slot B in
# streaming, poi riavvierà. Riprova per un po': subito dopo il riavvio la rete
# o il manifest (CDN, ~10 min di cache) possono non essere pronti.
set -u
LOCAL=/var/lib/hifi-player/ab
MARK="$LOCAL/image-kicked"
[ -f /usr/lib/osmium/IMAGE_VERSION ] && exit 0
[ -f "$LOCAL/finished" ] || exit 0
[ -f "$MARK" ] && exit 0
API=http://127.0.0.1:8000
log() { printf 'I: [hifi-ab-image] %s\n' "$*"; }

n=0
until curl -fsS -m 3 "$API/ota_channel" >/dev/null 2>&1; do
    n=$((n + 1)); [ "$n" -gt 60 ] && { log "API non raggiungibile"; exit 1; }
    sleep 5
done
n=0
while :; do
    r=$(curl -fsS -m 30 -X POST -H 'Content-Type: application/json' -d '{}' "$API/update/apply_all" 2>/dev/null || echo '{}')
    case "$r" in
        *'"started": true'*|*'"started":true'*)
            log "aggiornamento avviato: $r"
            mkdir -p "$LOCAL"; date -u +%Y-%m-%dT%H:%M:%SZ > "$MARK"
            exit 0 ;;
        *alreadyInProgress*)
            log "aggiornamento già in corso"; exit 0 ;;
    esac
    n=$((n + 1))
    [ "$n" -gt 20 ] && { log "nessuna immagine disponibile dopo 40 min: $r"; exit 1; }
    log "in attesa dell'immagine ($r)"
    sleep 120
done
