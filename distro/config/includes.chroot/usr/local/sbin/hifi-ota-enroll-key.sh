#!/bin/sh
# HiFi Player appliance — enroll / replace the OTA signing trust root.
#
# Installs a new Ed25519 PUBLIC key at /etc/hifi-player/ota-pubkey.pem, which is
# what hifi-os-update.sh verifies signed OS bundles against. This lets the owner
# of the device point the update channel at THEIR OWN signing key — no need to
# rebuild the ISO. It is the runtime counterpart of baking the key at build time.
#
# SECURITY: this is a root-only, local operation ON PURPOSE. Whoever can set the
# trust root can authorise arbitrary signed root scripts, so it is deliberately
# NOT exposed over the network API — run it from a console or over SSH as root.
#
# Usage:
#     hifi-ota-enroll-key.sh <path-to-pubkey.pem>
#     hifi-ota-enroll-key.sh https://example/ota-pubkey.pem
#     cat ota-pubkey.pem | hifi-ota-enroll-key.sh -
set -eu

DEST=/etc/hifi-player/ota-pubkey.pem
SRC="${1:-}"

die() { echo "E: [enroll-key] $1" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "Deve essere eseguito come root."
[ -n "$SRC" ] || die "Uso: hifi-ota-enroll-key.sh <file.pem | URL | ->"
command -v openssl >/dev/null 2>&1 || die "openssl non disponibile."

TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

# ── fetch the candidate key (file / URL / stdin) ─────────────────────
case "$SRC" in
    http://*|https://*) curl -fL --retry 3 -o "$TMP" "$SRC" || die "Download chiave fallito da $SRC" ;;
    -)                  cat > "$TMP" ;;
    *)                  [ -f "$SRC" ] || die "File non trovato: $SRC"; cp -f "$SRC" "$TMP" ;;
esac
[ -s "$TMP" ] || die "Chiave vuota."

# ── validate: must be a parseable Ed25519 public key ─────────────────
openssl pkey -pubin -in "$TMP" -noout 2>/dev/null \
    || die "Non è una chiave pubblica PEM valida."
if ! openssl pkey -pubin -in "$TMP" -text -noout 2>/dev/null | grep -qi 'ED25519'; then
    die "La chiave non è Ed25519 (le firme OTA usano Ed25519)."
fi

# ── install atomically, keeping one backup ───────────────────────────
mkdir -p "$(dirname "$DEST")"
if [ -f "$DEST" ]; then
    cp -f "$DEST" "${DEST}.bak"
    echo "I: backup della chiave precedente → ${DEST}.bak"
fi
install -m 644 -o root -g root "$TMP" "$DEST"

echo "OK: chiave OTA arruolata → $DEST"
echo "    fingerprint: $(openssl pkey -pubin -in "$DEST" -outform DER 2>/dev/null | sha256sum | awk '{print $1}')"
echo "    Da ora gli aggiornamenti OS devono essere firmati con la chiave privata corrispondente."
