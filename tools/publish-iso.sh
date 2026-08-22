#!/usr/bin/env bash
# publish-iso.sh — from an ISO, produce everything that goes on file.osmiumsound.it.
#
# Osmium Flasher discovers the current installer image by reading
#   https://file.osmiumsound.it/latest.json
# and refuses to write any image whose sha256 sidecar is not signed by our
# offline Ed25519 key. So a published ISO needs THREE companions next to it:
#
#     hifi-player-<tag>.iso              the image itself
#     hifi-player-<tag>.iso.sha256       "<hex>  <basename>"  (sha256sum format)
#     hifi-player-<tag>.iso.sha256.sig   raw Ed25519 signature over the .sha256
#     latest.json                        manifest the flasher polls
#
# This is exactly what .github/workflows/build-iso.yml produces in CI; this
# tool does the same by hand for an ISO you already have on disk (e.g. built
# locally, or downloaded from a Release), so signature + manifest are
# byte-compatible with what the flasher verifies.
#
# ── Usage ──────────────────────────────────────────────────────────────────
#   tools/publish-iso.sh <iso> [options]
#
#   --key <pem|->     Ed25519 PRIVATE signing key: a PEM file path, or "-" to
#                     read the PEM from stdin. If omitted, the env var
#                     OTA_SIGNING_KEY is used (either a path or the PEM text
#                     itself, matching the GitHub Actions secret of that name).
#                     Not needed when the ISO already ships a valid signature
#                     (see below) — a Release ISO is signed by CI, so publishing
#                     one to S3 needs no key at all.
#   --resign          Ignore any existing signature and sign afresh with --key.
#   --tag <vX.Y.Z>    Release tag for latest.json. Default: parsed from the ISO
#                     name (hifi-player-<tag>.iso).
#   --base <url>      Base URL the assets will live under.
#                     Default: https://file.osmiumsound.it  (what the flasher
#                     reads — see MANIFEST_URL in flasher/src/image.js).
#   --pubkey <pem>    Public key to verify the fresh signature against.
#                     Default: flasher/assets/ota-pubkey.pem (the key the
#                     flasher actually checks with) — this is what proves the
#                     ISO will be accepted, so verification is mandatory.
#   --out <dir>       Where to write the sidecar/sig/manifest. Default:
#                     ./publish-<tag>/ . The ISO is NOT copied there (it is
#                     large); the upload list at the end names it in place.
#   -h, --help        This help.
#
# ── Example ────────────────────────────────────────────────────────────────
#   OTA_SIGNING_KEY=~/secrets/ota-signing-key.pem \
#     tools/publish-iso.sh ~/isos/hifi-player-v2.5.21.iso
#
# Then upload the four files it lists to file.osmiumsound.it.
set -euo pipefail

die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$*" >&2; }
info() { printf '\033[36m•\033[0m %s\n' "$*" >&2; }

# ── Locate the repo so defaults (pubkey, manifest helper) resolve wherever
#    this script is invoked from. Falls back to cwd if run detached.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

# One cleanup trap for all temp paths; empty until the branches that need them
# assign, so it is safe under `set -u` whichever path runs.
KEYPEM=""
LINKDIR=""
cleanup() { [ -n "$KEYPEM" ] && rm -f "$KEYPEM"; [ -n "$LINKDIR" ] && rm -rf "$LINKDIR"; return 0; }
trap cleanup EXIT

ISO=""
KEY_SRC="${OTA_SIGNING_KEY:-}"
TAG=""
BASE="https://file.osmiumsound.it"
PUBKEY="$REPO_ROOT/flasher/assets/ota-pubkey.pem"
OUT=""
RESIGN=0

while [ $# -gt 0 ]; do
  case "$1" in
    --key)    KEY_SRC="${2:?--key needs a value}"; shift 2 ;;
    --tag)    TAG="${2:?--tag needs a value}"; shift 2 ;;
    --base)   BASE="${2:?--base needs a value}"; shift 2 ;;
    --pubkey) PUBKEY="${2:?--pubkey needs a value}"; shift 2 ;;
    --out)    OUT="${2:?--out needs a value}"; shift 2 ;;
    --resign) RESIGN=1; shift ;;
    -h|--help) sed -n '2,55p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --) shift; break ;;
    -*) die "unknown option: $1 (see --help)" ;;
    *)  [ -z "$ISO" ] || die "unexpected extra argument: $1"; ISO="$1"; shift ;;
  esac
done

[ -n "$ISO" ] || die "no ISO given. Usage: tools/publish-iso.sh <iso> [options] (--help)"
[ -f "$ISO" ] || die "ISO not found: $ISO"
[ -f "$PUBKEY" ] || die "public key not found: $PUBKEY (pass --pubkey)"
command -v openssl >/dev/null || die "openssl not found on PATH"

# sha256sum (Linux) or shasum -a 256 (macOS).
if command -v sha256sum >/dev/null; then
  sha256_of() { sha256sum "$1"; }
elif command -v shasum >/dev/null; then
  sha256_of() { shasum -a 256 "$1"; }
else
  die "neither sha256sum nor shasum found on PATH"
fi

ISO_DIR="$(cd -- "$(dirname -- "$ISO")" && pwd)"
ISO_NAME="$(basename -- "$ISO")"

# Tag: prefer --tag, else parse hifi-player-<tag>.iso, else refuse (the
# manifest's tag_name is not something to guess wrong).
if [ -z "$TAG" ]; then
  case "$ISO_NAME" in
    hifi-player-*.iso) TAG="${ISO_NAME#hifi-player-}"; TAG="${TAG%.iso}" ;;
    *) die "cannot parse a tag from '$ISO_NAME'; pass --tag vX.Y.Z" ;;
  esac
fi
info "tag: $TAG"
info "iso: $ISO_DIR/$ISO_NAME"

# ── Output dir.
[ -n "$OUT" ] || OUT="publish-$TAG"
mkdir -p -- "$OUT"
OUT="$(cd -- "$OUT" && pwd)"
SHA="$OUT/$ISO_NAME.sha256"
SIG="$OUT/$ISO_NAME.sha256.sig"
JSON="$OUT/latest.json"

# ── Reuse an existing valid signature when one already sits next to the ISO
#    (a Release ISO is signed by CI with the offline key, and downloaded with
#    its .sha256/.sha256.sig). No private key is needed in that case — which is
#    the whole point when the real key is offline. Fall through to signing only
#    when the pair is absent, doesn't verify, or --resign was asked for.
SRC_SHA="$ISO.sha256"
SRC_SIG="$ISO.sha256.sig"
REUSE=0
if [ "$RESIGN" -ne 1 ] && [ -f "$SRC_SHA" ] && [ -f "$SRC_SIG" ]; then
  if openssl pkeyutl -verify -pubin -inkey "$PUBKEY" -rawin -in "$SRC_SHA" -sigfile "$SRC_SIG" >/dev/null 2>&1; then
    REUSE=1
  else
    warn "existing $ISO_NAME.sha256.sig does not verify against $(basename "$PUBKEY") — re-signing"
  fi
fi

if [ "$REUSE" -eq 1 ]; then
  # Trust the signed sidecar's name/format, but confirm the ISO on disk really
  # is the one it signs (guards a truncated/corrupt download).
  cp -- "$SRC_SHA" "$SHA"
  cp -- "$SRC_SIG" "$SIG"
  want="$(cut -d' ' -f1 < "$SHA" | tr 'A-F' 'a-f')"
  got="$( ( cd -- "$ISO_DIR" && sha256_of "$ISO_NAME" ) | cut -d' ' -f1 )"
  [ "$want" = "$got" ] || die "the ISO does not match its .sha256 ($got != $want) — corrupt download?"
  info "sha256: $want"
  info "reusing the shipped signature (verifies against $(basename "$PUBKEY")) ✓ — no key needed"
else
  # ── Resolve the signing key into a temp PEM (never left on disk). Accept a
  #    file path, "-" for stdin, or the PEM text itself (the CI-secret form).
  KEYPEM="$(mktemp)"
  if [ -z "$KEY_SRC" ]; then
    die "no signing key, and no valid signature ships with the ISO.
       Pass --key <pem|-> or set OTA_SIGNING_KEY (path or PEM text)."
  elif [ "$KEY_SRC" = "-" ]; then
    cat > "$KEYPEM"
    info "signing key: read from stdin"
  elif [ -f "$KEY_SRC" ]; then
    cat -- "$KEY_SRC" > "$KEYPEM"
    info "signing key: $KEY_SRC"
  elif printf '%s' "$KEY_SRC" | grep -q 'BEGIN .*PRIVATE KEY'; then
    printf '%s\n' "$KEY_SRC" > "$KEYPEM"
    info "signing key: from OTA_SIGNING_KEY (inline PEM)"
  else
    die "signing key '$KEY_SRC' is neither a file nor inline PEM text"
  fi

  # Must be an Ed25519 private key — the flasher/OTA scheme is Ed25519-only, and
  # a wrong key type would sign happily and then fail verification below.
  openssl pkey -in "$KEYPEM" -text -noout 2>/dev/null | grep -qi 'ED25519' \
    || die "the signing key is not an Ed25519 private key"

  # ── Sidecar: "<hex>  <basename>" — byte-identical to `sha256sum <iso>` run in
  #    the ISO's own directory, so the name the flasher checks is the bare
  #    basename (it compares path.basename(signedName) === iso asset name).
  ( cd -- "$ISO_DIR" && sha256_of "$ISO_NAME" ) > "$SHA"
  info "sha256: $(cut -d' ' -f1 < "$SHA")"

  # ── Detached Ed25519 signature over the RAW BYTES of the sidecar file.
  #    (openssl pkeyutl -rawin: Ed25519 is one-shot over the whole message —
  #    exactly what crypto.verify(null, sidecar, key, sig) checks in image.js.)
  openssl pkeyutl -sign -inkey "$KEYPEM" -rawin -in "$SHA" -out "$SIG"

  # ── Verify NOW, against the key the flasher uses. A signature that doesn't
  #    verify here would be refused on-device, so this is a hard gate.
  if openssl pkeyutl -verify -pubin -inkey "$PUBKEY" -rawin -in "$SHA" -sigfile "$SIG" >/dev/null 2>&1; then
    info "signature verifies against $(basename "$PUBKEY") ✓"
  else
    die "signature does NOT verify against $PUBKEY — the flasher would reject this ISO.
       The signing key must be the private counterpart of that public key."
  fi
fi

# ── Manifest. Reuse the repo's generator when present so latest.json stays in
#    one format; fall back to an identical inline writer otherwise.
GEN="$REPO_ROOT/.github/scripts/make-iso-manifest.py"
if [ -f "$GEN" ] && command -v python3 >/dev/null; then
  # The generator wants the three assets beside the ISO name it's given; point
  # it at the ISO while the sidecars live in $OUT, via a scratch dir of links.
  LINKDIR="$(mktemp -d)"
  ln -sf -- "$ISO_DIR/$ISO_NAME" "$LINKDIR/$ISO_NAME"
  ln -sf -- "$SHA" "$LINKDIR/$ISO_NAME.sha256"
  ln -sf -- "$SIG" "$LINKDIR/$ISO_NAME.sha256.sig"
  ( cd -- "$LINKDIR" && python3 "$GEN" "$TAG" "$ISO_NAME" "$BASE" >/dev/null )
  mv -- "$LINKDIR/manifest-out/latest.json" "$JSON"
  info "manifest: via make-iso-manifest.py"
else
  ISO_SIZE="$(wc -c < "$ISO" | tr -d ' ')"
  SHA_SIZE="$(wc -c < "$SHA" | tr -d ' ')"
  SIG_SIZE="$(wc -c < "$SIG" | tr -d ' ')"
  B="${BASE%/}"
  cat > "$JSON" <<EOF
{
  "tag_name": "$TAG",
  "name": "$TAG",
  "body": "",
  "assets": [
    {
      "name": "$ISO_NAME",
      "browser_download_url": "$B/$ISO_NAME",
      "size": $ISO_SIZE
    },
    {
      "name": "$ISO_NAME.sha256",
      "browser_download_url": "$B/$ISO_NAME.sha256",
      "size": $SHA_SIZE
    },
    {
      "name": "$ISO_NAME.sha256.sig",
      "browser_download_url": "$B/$ISO_NAME.sha256.sig",
      "size": $SIG_SIZE
    }
  ]
}
EOF
  info "manifest: inline writer"
fi

# ── The base the flasher actually reads from. If the upload base points
#    somewhere else, latest.json will be internally consistent but the flasher
#    still polls its own hard-coded URL — warn loudly.
EXPECTED_BASE="$(grep -oE "https://[a-z0-9.]+/latest\.json" "$REPO_ROOT/flasher/src/image.js" 2>/dev/null | head -1 | sed 's#/latest\.json##')"
if [ -n "$EXPECTED_BASE" ] && [ "${BASE%/}" != "$EXPECTED_BASE" ]; then
  warn "you chose base '$BASE', but the flasher polls '$EXPECTED_BASE/latest.json'."
  warn "either upload to '$EXPECTED_BASE', or update MANIFEST_URL in flasher/src/image.js"
  warn "(and the download links in website/index.html + website/beta/index.html)."
fi

printf '\n\033[32mReady.\033[0m Upload these to %s (same directory):\n\n' "${BASE%/}"
printf '    %s\n' "$ISO_DIR/$ISO_NAME"
printf '    %s\n' "$SHA"
printf '    %s\n' "$SIG"
printf '    %s\n\n' "$JSON"
info "latest.json contents:"
cat "$JSON"
echo
