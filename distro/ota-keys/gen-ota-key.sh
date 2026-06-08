#!/bin/sh
# Generate the Ed25519 keypair used to sign OS OTA bundles.
#
#   ./gen-ota-key.sh
#
# Produces, in this directory:
#   ota-signing-key.pem   PRIVATE key — keep OFFLINE. Never commit. Paste its
#                         contents into the GitHub Actions secret OTA_SIGNING_KEY.
#   ota-pubkey.pem        PUBLIC key — copy into the image (see README).
#
# Run once. If the private key is ever lost or leaked, generate a new pair,
# update the secret, and ship a new image carrying the new public key.
set -eu

cd "$(dirname "$0")"

if [ -f ota-signing-key.pem ]; then
    echo "ota-signing-key.pem already exists — refusing to overwrite." >&2
    echo "Delete it by hand if you really mean to rotate the key." >&2
    exit 1
fi

openssl genpkey -algorithm ed25519 -out ota-signing-key.pem
chmod 600 ota-signing-key.pem
openssl pkey -in ota-signing-key.pem -pubout -out ota-pubkey.pem

echo "Wrote ota-signing-key.pem (PRIVATE) and ota-pubkey.pem (PUBLIC)."
echo
echo "Next:"
echo "  1. Copy the public key into the image:"
echo "       cp ota-pubkey.pem ../config/includes.chroot/etc/hifi-player/ota-pubkey.pem"
echo "  2. Store the PRIVATE key as the GitHub secret OTA_SIGNING_KEY:"
echo "       gh secret set OTA_SIGNING_KEY < ota-signing-key.pem"
echo "  3. Keep ota-signing-key.pem offline. It is git-ignored; do NOT commit it."
