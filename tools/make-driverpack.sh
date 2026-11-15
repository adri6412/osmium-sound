#!/bin/sh
# Osmium Sound — build and sign a driver pack (.osmpack).
#
#   tools/make-driverpack.sh <source-dir> [out-dir]
#
# A driver pack is firmware and/or out-of-tree kernel modules the DEVELOPER ships
# to a user whose laptop needs a blob or driver the image does not carry. The
# user installs it on-device from a USB stick or a web upload (hifi-driverpack.sh),
# and the ONLY thing that makes that safe is this signature: the device verifies
# it with the very same Ed25519 OTA key it uses for OS updates.
#
# SOURCE LAYOUT (what you prepare in <source-dir>):
#   manifest.json                      required — see the template below
#   firmware/<path-under-/lib/firmware>/<blob>     e.g. firmware/mediatek/mt7650e.bin
#   modules/<kernel-version>/<name>.ko             e.g. modules/6.12.113+deb13-amd64/foo.ko
# At least one of firmware/ or modules/ must be present.
#
# manifest.json template (flat JSON — the device reads it with sed, keep it flat):
#   {
#     "name": "mediatek-wifi",                 lowercase [a-z0-9._+-]; the install name
#     "description": "MediaTek MT76x0 Wi-Fi firmware",
#     "type": "firmware",                      firmware | modules | both
#     "target_kernel": "6.12.113+deb13-amd64", required if modules/ is present
#     "modules": ["foo.ko"]                    load order; omit for firmware-only
#   }
#
# OUTPUT (three files the user copies to a USB stick, or uploads via the web UI):
#   <name>.osmpack              the signed tar.gz
#   <name>.osmpack.sha256       the signed sidecar (sha256 + filename)
#   <name>.osmpack.sha256.sig   the detached Ed25519 signature
#
# SIGNING KEY. By default the private OTA key at distro/ota-keys/ota-signing-key.pem
# (gitignored — never committed). In CI, set OTA_SIGNING_KEY to the PEM contents
# (the same secret build-ui-ota.yml uses) and it is written to a temp file.
#
# Building the .ko: see tools/driverpack/README.md — they must be built against
# the exact pinned kernel (linux-headers-6.12.113+deb13-amd64), or the device
# refuses to load them. Firmware needs no build, only the blob at the right path.
set -eu

SRC=${1:-}
OUT=${2:-.}
[ -n "$SRC" ] && [ -d "$SRC" ] || { echo "usage: $0 <source-dir> [out-dir]" >&2; exit 64; }

here=$(cd "$(dirname "$0")/.." && pwd)   # repo root
MAN="$SRC/manifest.json"
[ -f "$MAN" ] || { echo "E: $MAN missing" >&2; exit 1; }
command -v openssl >/dev/null 2>&1 || { echo "E: openssl not found" >&2; exit 1; }

# Pull the name out of the (developer-authored) manifest.
NAME=$(sed -n 's/.*"name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$MAN" | head -n1)
case "$NAME" in
    ''|*[!a-z0-9._+-]*) echo "E: manifest name invalid or missing: '$NAME'" >&2; exit 1 ;;
esac
[ -d "$SRC/firmware" ] || [ -d "$SRC/modules" ] \
    || { echo "E: need firmware/ or modules/ in $SRC" >&2; exit 1; }

# If modules/ is present, target_kernel must be set and must name a modules/<kver>.
if [ -d "$SRC/modules" ]; then
    TGT=$(sed -n 's/.*"target_kernel"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$MAN" | head -n1)
    [ -n "$TGT" ] || { echo "E: modules/ present but manifest has no target_kernel" >&2; exit 1; }
    [ -d "$SRC/modules/$TGT" ] || { echo "E: modules/ present but no modules/$TGT/ to match target_kernel" >&2; exit 1; }
fi

mkdir -p "$OUT"
PACK="$OUT/$NAME.osmpack"
SIDECAR="$PACK.sha256"
SIG="$PACK.sha256.sig"

# Deterministic tar: sorted names, fixed owner/mtime, so the same inputs sign to
# the same bytes.
echo "I: packing $NAME -> $PACK"
tar --sort=name --owner=0 --group=0 --numeric-owner --mtime='@0' \
    -czf "$PACK" -C "$SRC" manifest.json \
    $([ -d "$SRC/firmware" ] && echo firmware) \
    $([ -d "$SRC/modules" ]  && echo modules)

# Sidecar + detached Ed25519 signature — EXACTLY what hifi-driverpack.sh verify
# reconstructs on the device: "<sha256>  <basename>\n".
SHA=$(sha256sum "$PACK" | awk '{print $1}')
printf '%s  %s\n' "$SHA" "$(basename "$PACK")" > "$SIDECAR"

KEYFILE=${KEYFILE:-$here/distro/ota-keys/ota-signing-key.pem}
CLEANUP=""
if [ -n "${OTA_SIGNING_KEY:-}" ]; then
    KEYFILE=$(mktemp)
    CLEANUP=$KEYFILE
    printf '%s\n' "$OTA_SIGNING_KEY" > "$KEYFILE"
fi
[ -s "$KEYFILE" ] || { echo "E: signing key not found ($KEYFILE); set OTA_SIGNING_KEY or place the PEM" >&2; exit 1; }

openssl pkeyutl -sign -inkey "$KEYFILE" -rawin -in "$SIDECAR" -out "$SIG" \
    || { echo "E: signing failed" >&2; [ -n "$CLEANUP" ] && rm -f "$CLEANUP"; exit 1; }
[ -n "$CLEANUP" ] && rm -f "$CLEANUP"

# Verify against the tracked public key so a bad key fails here, not on a device.
PUB=$here/distro/ota-keys/ota-pubkey.pem
if [ -s "$PUB" ]; then
    openssl pkeyutl -verify -pubin -inkey "$PUB" -rawin -in "$SIDECAR" -sigfile "$SIG" >/dev/null 2>&1 \
        && echo "I: signature verifies against $PUB" \
        || { echo "E: signature does NOT verify against $PUB — wrong key?" >&2; exit 1; }
fi

echo "I: done. Ship these three files:"
echo "     $PACK"
echo "     $SIDECAR"
echo "     $SIG"
