#!/bin/sh
# HiFi Player appliance — OTA update of the on-screen interface.
#
# 🚨 Da 2.5.24 il pacchetto di questo canale contiene l'interfaccia Qt
# (/opt/hifi-qt): e' quella che si aggiorna d'ora in poi, e si chiama
# `hifi-qtui-<versione>.tar.gz`. Il contenuto vecchio (l'app Electron
# scompattata, /opt/hifi-media-player) resta riconosciuto, sia per i rilasci
# gia' pubblicati sia per tornare indietro: si guarda che cosa c'e' dentro il
# pacchetto e si installa di conseguenza.
#
# Scarica il tarball, ne verifica lo sha256, sostituisce la cartella giusta in
# blocco (tenendo una copia per il ripristino) e scrive la nuova versione in
# /etc/hifi-player/UI_VERSION, fuori da entrambe le cartelle.
#
# Split into two subcommands so download+verify (safe while the box is fully
# live) is separate from apply (which only ever runs isolated under
# system-update.target, driven by hifi-update-apply-runner.sh — nothing has
# lightdm/Electron running down there, so there is nothing to restart
# afterwards, unlike the old single-shot flow that restarted lightdm mid-swap):
#     hifi-ota-update.sh stage <download_url> <sha256> <version>
#     hifi-ota-update.sh apply <staged_dir> <version>
#
# A third mode keeps the ORIGINAL single-shot behaviour (download, verify,
# swap and restart lightdm — all in one call, on the live system) for
# api_server.py's single-component `/app_update/apply` endpoint, which is
# deliberately NOT part of the isolated-update-mode redesign (see
# apply_app_update() there):
#     hifi-ota-update.sh full <download_url> <sha256> <version>
set -eu

# Sourced defensively: under `set -e` a missing/unreadable helper would abort
# this script before write_status/fail exist, leaving the status file on its
# previous contents with nothing to explain the silence.
if [ -r /usr/local/sbin/hifi-log.sh ]; then
    # shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-log.sh
    # shellcheck disable=SC1091  # absolute target, only present on the appliance
    . /usr/local/sbin/hifi-log.sh
    hifi_log_init hifi-ota-update
fi

CMD="${1:-}"
# Backward-compat: an old orchestrator (the pre-split hifi-update-runner.sh,
# quite possibly still running on THIS device when it received the very
# bundle that replaced this script) calls it with the OLD 3-arg convention —
# <url> <sha256> <version>, no subcommand. Without this, the very first
# update after this split lands would fail outright (URL lands in $CMD,
# matches nothing, exit 64) and need a manual retry. Detect it and treat it
# as `full`, so that first transition completes in one pass too.
case "$CMD" in
    stage|apply|full) ;;
    *) set -- full "$@"; CMD=full ;;
esac
APPDIR=/opt/hifi-media-player
OLDDIR=/opt/hifi-media-player.old
QTDIR=/opt/hifi-qt
QTOLD=/opt/hifi-qt.old
UI_VERSION_FILE=/etc/hifi-player/UI_VERSION
ENGINE_FILE=/etc/hifi-player/ui-engine
DISPLAY_MODE_SCRIPT=/usr/local/sbin/hifi-display-mode.sh

# Sostituisce una cartella in blocco tenendo da parte la precedente.
# $1 = nuova (gia' pronta), $2 = destinazione, $3 = copia di riserva
swap_dir() {
    rm -rf "$3"
    if [ -d "$2" ]; then mv "$2" "$3" || return 1; fi
    if ! mv "$1" "$2"; then
        [ -d "$3" ] && mv "$3" "$2"
        return 1
    fi
    return 0
}

# La versione dell'interfaccia sta FUORI dalle cartelle dei due contenuti, cosi'
# vale per entrambi e sopravvive al passaggio dall'uno all'altro.
write_ui_version() {
    mkdir -p "$(dirname "$UI_VERSION_FILE")"
    printf '%s\n' "$1" > "$UI_VERSION_FILE"
}

# Installa il contenuto gia' scompattato in $1, con versione $2.
# Ritorna 0 se fatto, 1 se la sostituzione e' fallita, 2 se dentro non c'e'
# nessuna interfaccia riconoscibile.
install_payload() {
    _new="$1"
    _ver="$2"
    if [ -x "$_new/hifi-qt" ]; then
        swap_dir "$_new" "$QTDIR" "$QTOLD" || return 1
        chmod 755 "$QTDIR/hifi-qt" 2>/dev/null || true
        # 🚨 Se nessuno ha ancora scelto quale interfaccia mostrare, quella Qt
        # appena installata diventa la predefinita: e' l'unico momento in cui si
        # sa per certo che i suoi file ci sono. Una scelta gia' fatta — anche
        # "electron" — NON si tocca mai.
        if [ ! -f "$ENGINE_FILE" ] && [ -x "$DISPLAY_MODE_SCRIPT" ]; then
            "$DISPLAY_MODE_SCRIPT" engine set qt >/dev/null 2>&1 || true
        fi
    elif [ -x "$_new/hifi-media-player" ]; then
        swap_dir "$_new" "$APPDIR" "$OLDDIR" || return 1
        if [ -f "$APPDIR/chrome-sandbox" ]; then
            chown root:root "$APPDIR/chrome-sandbox"
            chmod 4755 "$APPDIR/chrome-sandbox"
        fi
        ln -sf "$APPDIR/hifi-media-player" /usr/bin/hifi-media-player
        printf '%s\n' "$_ver" > "$APPDIR/UI_VERSION"
    else
        return 2
    fi
    write_ui_version "$_ver"
    return 0
}
STATUS=/run/hifi-ota-status.json
STAGE_ROOT=/var/lib/hifi-player/update/staged/ui
VERSION=unknown

# ── status helper ────────────────────────────────────────────────────
# write_status <state> <progress> <message>
write_status() {
    state="$1"; progress="$2"; msg="$3"
    # message is plain text — escape backslashes and double quotes for JSON.
    esc=$(printf '%s' "$msg" | sed 's/\\/\\\\/g; s/"/\\"/g')
    printf '{"state":"%s","progress":%s,"version":"%s","message":"%s"}\n' \
        "$state" "$progress" "$VERSION" "$esc" > "$STATUS"
}

fail() {
    write_status error 0 "$1"
    echo "E: [hifi-ota] $1" >&2
    exit 1
}

case "$CMD" in
stage)
    URL="${2:-}"
    SHA="${3:-}"
    VERSION="${4:-unknown}"
    [ -n "$URL" ] || fail "URL di download mancante"
    [ -n "$SHA" ] || fail "Checksum sha256 mancante"
    case "$VERSION" in
        ''|*[!0-9A-Za-z._-]*) fail "Versione non valida" ;;
    esac

    # Persistent staging dir (survives the reboot into update-mode), keyed by
    # version so a re-stage of the same release cleanly replaces itself.
    WORKDIR="$STAGE_ROOT/$VERSION"
    rm -rf "$WORKDIR"; mkdir -p "$WORKDIR"
    TARBALL="$WORKDIR/hifi-ui.tar.gz"
    PAYLOAD="$WORKDIR/payload"
    if command -v hifi_curl_progress >/dev/null 2>&1; then
        hifi_curl_progress "$URL" "$TARBALL" 10 40 "Scaricamento aggiornamento $VERSION…" \
            || fail "Download fallito da $URL"
    else
        write_status downloading 10 "Scaricamento aggiornamento $VERSION…"
        curl -fL --retry 3 -o "$TARBALL" "$URL" \
            || fail "Download fallito da $URL"
    fi

    write_status verifying 40 "Verifica integrità…"
    ACTUAL=$(sha256sum "$TARBALL" | awk '{print $1}')
    if [ "$ACTUAL" != "$SHA" ]; then
        fail "Checksum non valido (atteso $SHA, ottenuto $ACTUAL)"
    fi

    write_status applying 55 "Estrazione…"
    rm -rf "$PAYLOAD"; mkdir -p "$PAYLOAD"

    # Free-space guard (root cause of the "file too short" brick): a full disk
    # lets tar write a truncated file — any file, not just libffmpeg.so — and
    # the kiosk then fails to start. Refuse to extract unless the target FS can
    # hold the uncompressed tree plus a safety margin. The uncompressed size
    # comes from the gzip footer (fast, no full read); fall back to ~4x the
    # compressed size.
    need_kb=$(gzip -l "$TARBALL" 2>/dev/null | awk 'NR==2 && $2 ~ /^[0-9]+$/ {print int($2/1024)}')
    [ -n "${need_kb:-}" ] && [ "$need_kb" -gt 0 ] 2>/dev/null \
        || need_kb=$(( ($(wc -c < "$TARBALL") / 1024) * 4 ))
    free_kb=$(df -Pk "$PAYLOAD" | awk 'NR==2 {print $4}')
    if [ -n "${free_kb:-}" ] && [ "$free_kb" -lt $(( need_kb + 51200 )) ]; then
        fail "Spazio insufficiente per l'aggiornamento: servono ~$((need_kb/1024)) MB, liberi ~$((free_kb/1024)) MB"
    fi

    tar xzf "$TARBALL" -C "$PAYLOAD" || fail "Estrazione del tarball fallita"

    # ── integrity: verify EVERY extracted file against the archive ───
    # Not just the main binary. `tar --compare` re-reads the archive and flags
    # a size/content mismatch for ANY member, so a single truncated file (a
    # .so, a resource, an asar) can no longer slip through and brick the
    # kiosk. Filter to real corruption ("Size differs"/"Contents differ") —
    # ownership/mode/time lines are expected (archive stores the CI runner's
    # uid, we extract as root).
    write_status verifying 75 "Verifica integrità dei file estratti…"
    corrupt=$(tar dzf "$TARBALL" -C "$PAYLOAD" 2>&1 \
        | grep -iE 'Size differs|Contents differ' | head -n 1 || true)
    if [ -n "$corrupt" ]; then
        rm -rf "$PAYLOAD"
        fail "Bundle estratto corrotto: $corrupt"
    fi

    # sanity-check the payload before it is trusted for later
    [ -x "$PAYLOAD/hifi-media-player" ] \
        || fail "Bundle non valido: $PAYLOAD/hifi-media-player mancante"

    rm -f "$TARBALL"
    printf '%s\n' "$VERSION" > "$WORKDIR/STAGED"
    write_status staged 100 "Aggiornamento verificato ($VERSION), in attesa di applicazione"
    ;;

apply)
    STAGED_DIR="${2:-}"
    VERSION="${3:-unknown}"
    NEWDIR="$STAGED_DIR/payload"
    [ -n "$STAGED_DIR" ] || fail "Percorso staging mancante"
    [ "$(cat "$STAGED_DIR/STAGED" 2>/dev/null)" = "$VERSION" ] \
        || fail "Pacchetto UI mancante o non corrispondente in $STAGED_DIR"

    # ── atomic swap (keep a single backup) ─────────────────────────
    # NEWDIR and APPDIR are assumed to be on the same filesystem (both under
    # the appliance's single root partition) so this `mv` is a genuinely
    # atomic rename, not a cross-filesystem copy — revisit if /var/lib or
    # /opt is ever split onto its own mount.
    write_status applying 70 "Applicazione…"
    # 🚨 Il pacchetto puo' contenere l'interfaccia Qt (da 2.5.24) oppure la
    # vecchia app Electron: install_payload guarda che cosa c'e' dentro.
    install_payload "$NEWDIR" "$VERSION"
    case $? in
        1) fail "Sostituzione dell'interfaccia fallita" ;;
        2) fail "Bundle non valido: nessuna interfaccia dentro $NEWDIR" ;;
    esac

    write_status 'done' 100 "Aggiornamento a $VERSION completato"
    ;;

full)
    # Original, unmodified single-shot flow: download, verify, swap and
    # restart lightdm, all on the live system, in one call. Kept
    # byte-for-byte equivalent to the pre-split script — see api_server.py's
    # apply_app_update() for why this path still exists.
    URL="${2:-}"
    SHA="${3:-}"
    VERSION="${4:-unknown}"
    [ -n "$URL" ] || fail "URL di download mancante"
    [ -n "$SHA" ] || fail "Checksum sha256 mancante"

    WORKDIR=/var/tmp/hifi-ota
    TARBALL="$WORKDIR/hifi-ui.tar.gz"
    NEWDIR=/opt/hifi-media-player.new
    rm -rf "$WORKDIR"; mkdir -p "$WORKDIR"
    if command -v hifi_curl_progress >/dev/null 2>&1; then
        hifi_curl_progress "$URL" "$TARBALL" 10 40 "Scaricamento aggiornamento $VERSION…" \
            || fail "Download fallito da $URL"
    else
        write_status downloading 10 "Scaricamento aggiornamento $VERSION…"
        curl -fL --retry 3 -o "$TARBALL" "$URL" \
            || fail "Download fallito da $URL"
    fi

    write_status verifying 40 "Verifica integrità…"
    ACTUAL=$(sha256sum "$TARBALL" | awk '{print $1}')
    if [ "$ACTUAL" != "$SHA" ]; then
        fail "Checksum non valido (atteso $SHA, ottenuto $ACTUAL)"
    fi

    write_status applying 55 "Estrazione…"
    rm -rf "$NEWDIR"; mkdir -p "$NEWDIR"

    need_kb=$(gzip -l "$TARBALL" 2>/dev/null | awk 'NR==2 && $2 ~ /^[0-9]+$/ {print int($2/1024)}')
    [ -n "${need_kb:-}" ] && [ "$need_kb" -gt 0 ] 2>/dev/null \
        || need_kb=$(( ($(wc -c < "$TARBALL") / 1024) * 4 ))
    free_kb=$(df -Pk "$NEWDIR" | awk 'NR==2 {print $4}')
    if [ -n "${free_kb:-}" ] && [ "$free_kb" -lt $(( need_kb + 51200 )) ]; then
        fail "Spazio insufficiente per l'aggiornamento: servono ~$((need_kb/1024)) MB, liberi ~$((free_kb/1024)) MB"
    fi

    tar xzf "$TARBALL" -C "$NEWDIR" || fail "Estrazione del tarball fallita"

    write_status verifying 70 "Verifica integrità dei file estratti…"
    corrupt=$(tar dzf "$TARBALL" -C "$NEWDIR" 2>&1 \
        | grep -iE 'Size differs|Contents differ' | head -n 1 || true)
    if [ -n "$corrupt" ]; then
        rm -rf "$NEWDIR"
        fail "Bundle estratto corrotto: $corrupt"
    fi


    write_status applying 80 "Applicazione…"
    # 🚨 Il pacchetto puo' contenere l'interfaccia Qt (da 2.5.24) oppure la
    # vecchia app Electron: install_payload guarda che cosa c'e' dentro.
    install_payload "$NEWDIR" "$VERSION"
    case $? in
        1) fail "Sostituzione dell'interfaccia fallita" ;;
        2) fail "Bundle non valido: nessuna interfaccia dentro $NEWDIR" ;;
    esac

    write_status restarting 95 "Riavvio interfaccia…"
    rm -f "$TARBALL"
    write_status 'done' 100 "Aggiornamento a $VERSION completato"

    # Restarting lightdm kills the running Electron app (and any HTTP client
    # still polling) — safe here because this path is only ever launched
    # under its own transient systemd-run unit (see apply_app_update() in
    # api_server.py), which survives the restart. Keep it last regardless.
    # si riavvia l'interfaccia che sta girando davvero: da 2.5.24 puo' essere
    # quella Qt (hifi-qt), non piu' solo la sessione di lightdm con Electron
    if systemctl is-active --quiet hifi-qt; then
        systemctl restart hifi-qt || true
    elif systemctl is-active --quiet lightdm; then
        systemctl restart lightdm || true
    fi
    ;;

*)
    echo "Uso: $0 stage <url> <sha256> <versione>" >&2
    echo "     $0 apply <staged_dir> <versione>" >&2
    echo "     $0 full <url> <sha256> <versione>" >&2
    exit 64
    ;;
esac
