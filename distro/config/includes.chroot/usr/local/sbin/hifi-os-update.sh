#!/bin/sh
# HiFi Player appliance — OTA update of the operating system itself.
#
# Unlike the UI / system-components updaters (which just drop files in place),
# an OS update may need to do arbitrary things to the running system: enable a
# kernel module, rewrite a config under /etc, add a udev rule, migrate data,
# tweak GRUB, etc. So the payload is a *signed* bundle that carries its own
# `apply.sh`, which we execute as root.
#
# Because that script runs as root, a plain sha256 (which only proves the file
# downloaded intact) is NOT enough — anyone able to publish a release or MITM
# the download could ship arbitrary root code. We therefore require a
# cryptographic signature made with an offline Ed25519 private key whose public
# half is baked into the image at /etc/hifi-player/ota-pubkey.pem. The bundle is
# rejected (and apply.sh never runs) unless that signature verifies.
#
# Verification chain:
#   1. signature of the .sha256 sidecar verifies against the embedded pubkey
#      → proves the digest was authored by us (authenticity);
#   2. sha256 of the tarball matches that signed digest (integrity).
#
# Bundle layout (hifi-os-<ver>.tar.gz):
#     ./apply.sh        # executable; performs the OS changes, run as root
#     ./OS_VERSION      # the version string (optional, informational)
#     ./...             # any extra files apply.sh wants to install
#
# Split into two subcommands so download+verify (which can safely happen while
# the box is fully live) is separate from apply (which only ever runs isolated
# under system-update.target, driven by hifi-update-apply-runner.sh — see that
# script for why: applying while hifi-api/hifi-webui/lightdm are still running
# is what used to leave updates half-applied):
#     hifi-os-update.sh stage <tarball_url> <sha256> <sig_url> <version>
#     hifi-os-update.sh apply <staged_dir> <version>
#
# `stage` downloads, verifies and extracts the bundle to a *persistent*
# directory under /var/lib/hifi-player/update/staged/os/<version> — it must
# survive the reboot into update-mode. `apply` only ever reads that directory;
# it never touches the network.
#
# A third mode keeps the ORIGINAL single-shot behaviour (download, verify,
# apply and, if the payload asks, reboot — all in one call, on the live
# system) for api_server.py's single-component `/os_update/apply` endpoint,
# which is deliberately NOT part of the isolated-update-mode redesign (see
# apply_os_update() there):
#     hifi-os-update.sh full <tarball_url> <sha256> <sig_url> <version>
set -eu

# Don't leak downloaded bytes to other local users while we work on them.
umask 077

# Optional: only for hifi_curl_progress (progress-reporting curl wrapper used
# below) — this script deliberately does NOT call hifi_log_init, so it keeps
# its existing logging behaviour (persist_apply_log below) untouched.
if [ -r /usr/local/sbin/hifi-log.sh ]; then
    # shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-log.sh
    # shellcheck disable=SC1091  # absolute target, only present on the appliance
    . /usr/local/sbin/hifi-log.sh
fi

CMD="${1:-}"
# Backward-compat: an old orchestrator (the pre-split hifi-update-runner.sh,
# quite possibly still running on THIS device when it received the very
# bundle that replaced this script) calls it with the OLD 4-arg convention —
# <url> <sha256> <sig_url> <version>, no subcommand. Without this, the very
# first update after this split lands would fail the os step outright (URL
# lands in $CMD, matches nothing, exit 64) and need a manual retry. Detect it
# and treat it as `full`, so that first transition completes in one pass too.
case "$CMD" in
    stage|apply|full) ;;
    *) set -- full "$@"; CMD=full ;;
esac
VERSION_FILE=/etc/hifi-player/OS_VERSION
STATUS=/run/hifi-os-status.json
STAGE_ROOT=/var/lib/hifi-player/update/staged/os
VERSION=unknown

# ── status helper ────────────────────────────────────────────────────
write_status() {
    state="$1"; progress="$2"; msg="$3"
    esc=$(printf '%s' "$msg" | sed 's/\\/\\\\/g; s/"/\\"/g')
    printf '{"state":"%s","progress":%s,"version":"%s","message":"%s"}\n' \
        "$state" "$progress" "$VERSION" "$esc" > "$STATUS"
}

fail() {
    write_status error 0 "$1"
    echo "E: [hifi-os] $1" >&2
    exit 1
}

# apply.sh's own log ($PAYLOAD/apply.log, see below) is persisted here so
# OS-update history survives across runs/reboots, for the support-bundle
# endpoint (api_server.py) to pick up.
persist_apply_log() {
    [ -f "${LOG:-}" ] || return 0
    mkdir -p /var/log/hifi 2>/dev/null || true
    {
        printf '\n===== hifi-os-update: apply.sh run %s (version %s) =====\n' \
            "$(date -Is 2>/dev/null || date)" "$VERSION"
        cat "$LOG"
    } >> /var/log/hifi/os-update.log 2>/dev/null || true
}

case "$CMD" in
stage)
    URL="${2:-}"
    SHA="${3:-}"
    SIG_URL="${4:-}"
    VERSION="${5:-unknown}"

    PUBKEY=/etc/hifi-player/ota-pubkey.pem
    # Cap the download so a hostile/garbage URL can't fill the disk (DoS).
    MAX_TARBALL_BYTES=524288000   # 500 MiB
    MAX_SIG_BYTES=4096

    [ -n "$URL" ]     || fail "URL di download mancante"
    [ -n "$SHA" ]     || fail "Checksum sha256 mancante"
    [ -n "$SIG_URL" ] || fail "Firma mancante: aggiornamento OS rifiutato"
    [ -s "$PUBKEY" ]  || fail "Chiave pubblica OTA assente ($PUBKEY): impossibile verificare"
    command -v openssl >/dev/null 2>&1 || fail "openssl non disponibile: impossibile verificare la firma"

    # ── validate untrusted inputs (these arrive from the network) ─────
    # SHA must be exactly 64 hex chars — it is interpolated into the signed
    # sidecar text and compared against the tarball; reject anything else.
    case "$SHA" in
        *[!0-9a-fA-F]*) fail "Checksum malformato" ;;
    esac
    [ "${#SHA}" -eq 64 ] || fail "Checksum di lunghezza errata"

    # VERSION is interpolated into the signed sidecar filename, the staging
    # directory path, and the OS_VERSION file — restrict it to a safe charset
    # so it cannot inject content or traverse paths.
    case "$VERSION" in
        ''|*[!0-9A-Za-z._-]*) fail "Versione non valida" ;;
    esac

    # Only download over TLS — never let a release point the updater at plain HTTP.
    case "$URL"     in https://*) ;; *) fail "URL non sicuro (TLS richiesto)" ;; esac
    case "$SIG_URL" in https://*) ;; *) fail "URL firma non sicuro (TLS richiesto)" ;; esac

    # The signature scheme is Ed25519; make sure the baked key really is one so
    # a swapped-in weaker key can't silently change the trust model.
    openssl pkey -pubin -in "$PUBKEY" -text -noout 2>/dev/null | grep -qi 'ED25519' \
        || fail "Chiave pubblica OTA non è Ed25519: verifica rifiutata"

    # ── download ────────────────────────────────────────────────────
    # Persistent staging dir (survives the reboot into update-mode), keyed by
    # version so a re-stage of the same release cleanly replaces itself and two
    # different pending versions never collide.
    WORKDIR="$STAGE_ROOT/$VERSION"
    rm -rf "$WORKDIR"
    mkdir -p "$WORKDIR"
    TARBALL="$WORKDIR/hifi-os.tar.gz"
    SHAFILE="$WORKDIR/hifi-os.sha256"
    SIGFILE="$WORKDIR/hifi-os.sha256.sig"
    PAYLOAD="$WORKDIR/payload"
    mkdir -p "$PAYLOAD"
    if command -v hifi_curl_progress >/dev/null 2>&1; then
        hifi_curl_progress "$URL" "$TARBALL" 10 25 "Scaricamento aggiornamento OS $VERSION…" \
            --proto '=https' --proto-redir '=https' --tlsv1.2 --max-filesize "$MAX_TARBALL_BYTES" \
            || fail "Download fallito da $URL"
    else
        write_status downloading 10 "Scaricamento aggiornamento OS $VERSION…"
        curl -fL --retry 3 --proto '=https' --proto-redir '=https' --tlsv1.2 --max-filesize "$MAX_TARBALL_BYTES" \
            -o "$TARBALL" "$URL" || fail "Download fallito da $URL"
    fi
    curl -fL --retry 3 --proto '=https' --proto-redir '=https' --tlsv1.2 --max-filesize "$MAX_SIG_BYTES" \
        -o "$SIGFILE" "$SIG_URL" || fail "Download firma fallito da $SIG_URL"

    # We sign the sha256 sidecar (small), then check the tarball against it.
    # Reconstruct that exact sidecar text so the signed bytes match.
    printf '%s  hifi-os-%s.tar.gz\n' "$SHA" "$VERSION" > "$SHAFILE"

    # ── verify signature (authenticity) ────────────────────────────
    write_status verifying 30 "Verifica firma…"
    # Ed25519 detached signature over the sha256 sidecar file.
    if ! openssl pkeyutl -verify -pubin -inkey "$PUBKEY" \
            -rawin -in "$SHAFILE" -sigfile "$SIGFILE" >/dev/null 2>&1; then
        fail "Firma non valida: aggiornamento OS rifiutato (possibile manomissione)"
    fi

    # ── verify checksum (integrity) ────────────────────────────────
    write_status verifying 45 "Verifica integrità…"
    ACTUAL=$(sha256sum "$TARBALL" | awk '{print $1}')
    if [ "$ACTUAL" != "$SHA" ]; then
        fail "Checksum non valido (atteso $SHA, ottenuto $ACTUAL)"
    fi

    # ── extract ─────────────────────────────────────────────────────
    write_status applying 70 "Estrazione…"
    # --no-same-owner/--no-same-permissions: don't honour ownership/setuid bits
    # from the archive. The bundle is signed (authentic), but this keeps a
    # buggy archive from dropping a root-owned setuid file outside apply.sh's
    # control.
    tar xzf "$TARBALL" -C "$PAYLOAD" --no-same-owner --no-same-permissions \
        || fail "Estrazione del bundle fallita"

    [ -f "$PAYLOAD/apply.sh" ] \
        || fail "Bundle non valido: apply.sh mancante"

    # Nothing left to prove authenticity/integrity from at apply time — the
    # extracted, verified payload IS the trust boundary from here on, same as
    # apply.sh already assumed today. Drop the scratch files; keep only what
    # apply needs.
    rm -f "$TARBALL" "$SHAFILE" "$SIGFILE"
    # Second, independent confirmation of what's on disk for the apply step
    # (which may run after an unrelated reboot, possibly minutes/hours later).
    printf '%s\n' "$VERSION" > "$WORKDIR/STAGED"

    write_status staged 100 "Aggiornamento OS verificato ($VERSION), in attesa di applicazione"
    ;;

apply)
    STAGED_DIR="${2:-}"
    VERSION="${3:-unknown}"
    PAYLOAD="$STAGED_DIR/payload"

    [ -n "$STAGED_DIR" ] || fail "Percorso staging mancante"
    [ "$(cat "$STAGED_DIR/STAGED" 2>/dev/null)" = "$VERSION" ] \
        || fail "Pacchetto OS mancante o non corrispondente in $STAGED_DIR"
    [ -f "$PAYLOAD/apply.sh" ] \
        || fail "Bundle non valido: apply.sh mancante"

    # ── run the payload's apply.sh as root ─────────────────────────
    # Run with a scrubbed environment (env -i) and a fixed PATH so nothing
    # inherited from the caller can influence the root script; only
    # HIFI_OS_VERSION/HIFI_PAYLOAD_DIR are passed through.
    write_status applying 50 "Applicazione modifiche di sistema…"
    chmod +x "$PAYLOAD/apply.sh"
    LOG="$STAGED_DIR/apply.log"
    if ! env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin \
            HIFI_OS_VERSION="$VERSION" HIFI_PAYLOAD_DIR="$PAYLOAD" \
            sh "$PAYLOAD/apply.sh" >"$LOG" 2>&1; then
        persist_apply_log
        tail=$(tail -n 3 "$LOG" 2>/dev/null | tr '\n' ' ')
        fail "apply.sh fallito: ${tail:-errore sconosciuto}"
    fi
    persist_apply_log

    # record the new version (outside /opt so a UI OTA can't wipe it)
    mkdir -p "$(dirname "$VERSION_FILE")"
    printf '%s\n' "$VERSION" > "$VERSION_FILE"

    # An OS change often wants a reboot to take full effect (payload leaves a
    # REBOOT marker). Under the isolated update-mode session the box reboots
    # exactly once, after every staged component has been applied — honouring
    # this mid-session would strand the steps still to come (system/ui), which
    # is the exact bug this whole redesign exists to remove. Just log it.
    if [ -f "$PAYLOAD/REBOOT" ]; then
        echo "I: [hifi-os] payload requested a reboot — deferred to end of update session" >&2
    fi

    write_status done 100 "Sistema operativo aggiornato a $VERSION"
    ;;

full)
    # Original, unmodified single-shot flow: download, verify, apply and
    # (if requested) reboot, all on the live system, in one call. Kept
    # byte-for-byte equivalent to the pre-split script — see api_server.py's
    # apply_os_update() for why this path still exists.
    URL="${2:-}"
    SHA="${3:-}"
    SIG_URL="${4:-}"
    VERSION="${5:-unknown}"

    PUBKEY=/etc/hifi-player/ota-pubkey.pem
    MAX_TARBALL_BYTES=524288000   # 500 MiB
    MAX_SIG_BYTES=4096

    [ -n "$URL" ]     || fail "URL di download mancante"
    [ -n "$SHA" ]     || fail "Checksum sha256 mancante"
    [ -n "$SIG_URL" ] || fail "Firma mancante: aggiornamento OS rifiutato"
    [ -s "$PUBKEY" ]  || fail "Chiave pubblica OTA assente ($PUBKEY): impossibile verificare"
    command -v openssl >/dev/null 2>&1 || fail "openssl non disponibile: impossibile verificare la firma"

    case "$SHA" in
        *[!0-9a-fA-F]*) fail "Checksum malformato" ;;
    esac
    [ "${#SHA}" -eq 64 ] || fail "Checksum di lunghezza errata"

    case "$VERSION" in
        ''|*[!0-9A-Za-z._-]*) fail "Versione non valida" ;;
    esac

    case "$URL"     in https://*) ;; *) fail "URL non sicuro (TLS richiesto)" ;; esac
    case "$SIG_URL" in https://*) ;; *) fail "URL firma non sicuro (TLS richiesto)" ;; esac

    openssl pkey -pubin -in "$PUBKEY" -text -noout 2>/dev/null | grep -qi 'ED25519' \
        || fail "Chiave pubblica OTA non è Ed25519: verifica rifiutata"

    WORKDIR=$(mktemp -d /var/tmp/hifi-os-ota.XXXXXX) || fail "mktemp fallito"
    TARBALL="$WORKDIR/hifi-os.tar.gz"
    SHAFILE="$WORKDIR/hifi-os.sha256"
    SIGFILE="$WORKDIR/hifi-os.sha256.sig"
    PAYLOAD="$WORKDIR/payload"
    mkdir -p "$PAYLOAD"
    if command -v hifi_curl_progress >/dev/null 2>&1; then
        hifi_curl_progress "$URL" "$TARBALL" 10 25 "Scaricamento aggiornamento OS $VERSION…" \
            --proto '=https' --proto-redir '=https' --tlsv1.2 --max-filesize "$MAX_TARBALL_BYTES" \
            || fail "Download fallito da $URL"
    else
        write_status downloading 10 "Scaricamento aggiornamento OS $VERSION…"
        curl -fL --retry 3 --proto '=https' --proto-redir '=https' --tlsv1.2 --max-filesize "$MAX_TARBALL_BYTES" \
            -o "$TARBALL" "$URL" || fail "Download fallito da $URL"
    fi
    curl -fL --retry 3 --proto '=https' --proto-redir '=https' --tlsv1.2 --max-filesize "$MAX_SIG_BYTES" \
        -o "$SIGFILE" "$SIG_URL" || fail "Download firma fallito da $SIG_URL"

    printf '%s  hifi-os-%s.tar.gz\n' "$SHA" "$VERSION" > "$SHAFILE"

    write_status verifying 30 "Verifica firma…"
    if ! openssl pkeyutl -verify -pubin -inkey "$PUBKEY" \
            -rawin -in "$SHAFILE" -sigfile "$SIGFILE" >/dev/null 2>&1; then
        fail "Firma non valida: aggiornamento OS rifiutato (possibile manomissione)"
    fi

    write_status verifying 45 "Verifica integrità…"
    ACTUAL=$(sha256sum "$TARBALL" | awk '{print $1}')
    if [ "$ACTUAL" != "$SHA" ]; then
        fail "Checksum non valido (atteso $SHA, ottenuto $ACTUAL)"
    fi

    write_status applying 60 "Estrazione…"
    tar xzf "$TARBALL" -C "$PAYLOAD" --no-same-owner --no-same-permissions \
        || fail "Estrazione del bundle fallita"

    [ -f "$PAYLOAD/apply.sh" ] \
        || fail "Bundle non valido: apply.sh mancante"

    write_status applying 80 "Applicazione modifiche di sistema…"
    chmod +x "$PAYLOAD/apply.sh"
    LOG="$WORKDIR/apply.log"
    if ! env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin \
            HIFI_OS_VERSION="$VERSION" HIFI_PAYLOAD_DIR="$PAYLOAD" \
            sh "$PAYLOAD/apply.sh" >"$LOG" 2>&1; then
        persist_apply_log
        tail=$(tail -n 3 "$LOG" 2>/dev/null | tr '\n' ' ')
        fail "apply.sh fallito: ${tail:-errore sconosciuto}"
    fi
    persist_apply_log

    mkdir -p "$(dirname "$VERSION_FILE")"
    printf '%s\n' "$VERSION" > "$VERSION_FILE"

    if [ -f "$PAYLOAD/REBOOT" ]; then
        write_status restarting 95 "Riavvio del sistema…"
        # Mitigates a kernel panic in the DesignWare DMA driver (dw_dmac_core)
        # hit during device_shutdown() when reboot() runs while a DMA channel
        # is actively streaming audio — reproduced with the DSP engine on.
        if [ "$(systemctl is-active camilladsp.service 2>/dev/null)" = "active" ]; then
            systemctl stop camilladsp.service squeezelite.service 2>/dev/null || true
            sleep 2
        fi
        sync
        rm -rf "$WORKDIR"
        systemctl reboot
        exit 0
    fi

    rm -rf "$WORKDIR"
    write_status done 100 "Sistema operativo aggiornato a $VERSION"
    ;;

*)
    echo "Uso: $0 stage <url> <sha256> <sig_url> <versione>" >&2
    echo "     $0 apply <staged_dir> <versione>" >&2
    echo "     $0 full <url> <sha256> <sig_url> <versione>" >&2
    exit 64
    ;;
esac
