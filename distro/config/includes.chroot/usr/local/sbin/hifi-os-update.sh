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
# Invoked as root by api_server.py via systemd-run so it survives any service
# restart the payload may trigger:
#     hifi-os-update.sh <tarball_url> <sha256> <sig_url> <version>
set -eu

# Don't leak downloaded bytes to other local users while we work on them.
umask 077

URL="${1:-}"
SHA="${2:-}"
SIG_URL="${3:-}"
VERSION="${4:-unknown}"

PUBKEY=/etc/hifi-player/ota-pubkey.pem
VERSION_FILE=/etc/hifi-player/OS_VERSION
STATUS=/run/hifi-os-status.json
# Cap the download so a hostile/garbage URL can't fill the disk (DoS).
MAX_TARBALL_BYTES=524288000   # 500 MiB
MAX_SIG_BYTES=4096

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

[ -n "$URL" ]     || fail "URL di download mancante"
[ -n "$SHA" ]     || fail "Checksum sha256 mancante"
[ -n "$SIG_URL" ] || fail "Firma mancante: aggiornamento OS rifiutato"
[ -s "$PUBKEY" ]  || fail "Chiave pubblica OTA assente ($PUBKEY): impossibile verificare"
command -v openssl >/dev/null 2>&1 || fail "openssl non disponibile: impossibile verificare la firma"

# ── validate untrusted inputs (these arrive from the network) ─────────
# SHA must be exactly 64 hex chars — it is interpolated into the signed sidecar
# text and compared against the tarball; reject anything else outright.
case "$SHA" in
    *[!0-9a-fA-F]*) fail "Checksum malformato" ;;
esac
[ "${#SHA}" -eq 64 ] || fail "Checksum di lunghezza errata"

# VERSION is interpolated into the signed sidecar filename and written to the
# OS_VERSION file — restrict it to a safe charset so it cannot inject content
# or traverse paths. (A mismatch vs. the signed version fails verification.)
case "$VERSION" in
    ''|*[!0-9A-Za-z._-]*) fail "Versione non valida" ;;
esac

# Only download over TLS — never let a release point the updater at plain HTTP.
case "$URL"     in https://*) ;; *) fail "URL non sicuro (TLS richiesto)" ;; esac
case "$SIG_URL" in https://*) ;; *) fail "URL firma non sicuro (TLS richiesto)" ;; esac

# The signature scheme is Ed25519; make sure the baked key really is one so a
# swapped-in weaker key can't silently change the trust model.
openssl pkey -pubin -in "$PUBKEY" -text -noout 2>/dev/null | grep -qi 'ED25519' \
    || fail "Chiave pubblica OTA non è Ed25519: verifica rifiutata"

# ── download ─────────────────────────────────────────────────────────
write_status downloading 10 "Scaricamento aggiornamento OS $VERSION…"
# Create a private, unpredictable workdir (avoid symlink/preplaced-file races in
# the world-writable /var/tmp).
WORKDIR=$(mktemp -d /var/tmp/hifi-os-ota.XXXXXX) || fail "mktemp fallito"
TARBALL="$WORKDIR/hifi-os.tar.gz"
SHAFILE="$WORKDIR/hifi-os.sha256"
SIGFILE="$WORKDIR/hifi-os.sha256.sig"
PAYLOAD="$WORKDIR/payload"
mkdir -p "$PAYLOAD"
curl -fL --retry 3 --proto '=https' --proto-redir '=https' --tlsv1.2 --max-filesize "$MAX_TARBALL_BYTES" \
    -o "$TARBALL" "$URL"     || fail "Download fallito da $URL"
curl -fL --retry 3 --proto '=https' --proto-redir '=https' --tlsv1.2 --max-filesize "$MAX_SIG_BYTES" \
    -o "$SIGFILE" "$SIG_URL" || fail "Download firma fallito da $SIG_URL"

# We sign the sha256 sidecar (small), then check the tarball against it.
# Reconstruct that exact sidecar text so the signed bytes match.
printf '%s  hifi-os-%s.tar.gz\n' "$SHA" "$VERSION" > "$SHAFILE"

# ── verify signature (authenticity) ──────────────────────────────────
write_status verifying 30 "Verifica firma…"
# Ed25519 detached signature over the sha256 sidecar file.
if ! openssl pkeyutl -verify -pubin -inkey "$PUBKEY" \
        -rawin -in "$SHAFILE" -sigfile "$SIGFILE" >/dev/null 2>&1; then
    fail "Firma non valida: aggiornamento OS rifiutato (possibile manomissione)"
fi

# ── verify checksum (integrity) ──────────────────────────────────────
write_status verifying 45 "Verifica integrità…"
ACTUAL=$(sha256sum "$TARBALL" | awk '{print $1}')
if [ "$ACTUAL" != "$SHA" ]; then
    fail "Checksum non valido (atteso $SHA, ottenuto $ACTUAL)"
fi

# ── extract ──────────────────────────────────────────────────────────
write_status applying 60 "Estrazione…"
# --no-same-owner/--no-same-permissions: don't honour ownership/setuid bits from
# the archive. The bundle is signed (authentic), but this keeps a buggy archive
# from dropping a root-owned setuid file outside apply.sh's control.
tar xzf "$TARBALL" -C "$PAYLOAD" --no-same-owner --no-same-permissions \
    || fail "Estrazione del bundle fallita"

[ -f "$PAYLOAD/apply.sh" ] \
    || fail "Bundle non valido: apply.sh mancante"

# ── run the payload's apply.sh as root ───────────────────────────────
# Run with a scrubbed environment (env -i) and a fixed PATH so nothing inherited
# from the API/systemd context can influence the root script; only
# HIFI_OS_VERSION/HIFI_PAYLOAD_DIR are passed through.
write_status applying 80 "Applicazione modifiche di sistema…"
chmod +x "$PAYLOAD/apply.sh"
LOG="$WORKDIR/apply.log"
if ! env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin \
        HIFI_OS_VERSION="$VERSION" HIFI_PAYLOAD_DIR="$PAYLOAD" \
        sh "$PAYLOAD/apply.sh" >"$LOG" 2>&1; then
    tail=$(tail -n 3 "$LOG" 2>/dev/null | tr '\n' ' ')
    fail "apply.sh fallito: ${tail:-errore sconosciuto}"
fi

# record the new version (outside /opt so a UI OTA can't wipe it)
mkdir -p "$(dirname "$VERSION_FILE")"
printf '%s\n' "$VERSION" > "$VERSION_FILE"

# ── done ─────────────────────────────────────────────────────────────
# An OS change often needs a reboot to take full effect. The payload signals
# that by leaving a REBOOT marker in its dir; we honour it last.
if [ -f "$PAYLOAD/REBOOT" ]; then
    write_status restarting 95 "Riavvio del sistema…"
    sync
    rm -rf "$WORKDIR"
    systemctl reboot
    exit 0
fi

rm -rf "$WORKDIR"
write_status done 100 "Sistema operativo aggiornato a $VERSION"
