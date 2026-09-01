#!/bin/sh
# Osmium Sound — genera la PKI che firma i bundle immagine RAUC.
#
# RAUC verifica i bundle con una firma CMS/X.509 (RSA o ECDSA), non con la
# chiave Ed25519 del canale OS legacy (distro/ota-keys): servono una CA e un
# certificato di firma. L'apparecchio porta SOLO la CA (keyring.pem, pubblica,
# committata e cotta nell'immagine in /etc/rauc/keyring.pem); il certificato di
# firma viaggia dentro ogni bundle e viene verificato contro quella CA.
#
# Uso:
#     sh gen-rauc-ca.sh <cartella-di-uscita> [etichetta]
#
# Produce nella cartella (da tenere OFFLINE, mai nel repo):
#     ca-key.pem            chiave privata della CA        -> segreto, offline
#     ca.pem                certificato della CA            -> = keyring.pem
#     signing-key.pem       chiave privata di firma          -> secret GitHub RAUC_SIGNING_KEY
#     signing-cert.pem      certificato di firma             -> secret GitHub RAUC_SIGNING_CERT
#     keyring.pem           copia di ca.pem da committare in distro/rauc-keys/
#
# Validità 30 anni: un certificato scaduto blocca OGNI aggiornamento della
# flotta (RAUC rifiuta il bundle), e questi apparecchi vivono a lungo. In più
# system.conf imposta use-bundle-signing-time=true, così un orologio fermo al
# 1970 (batteria CMOS scarica) non fa rifiutare un bundle valido.
set -eu

OUT="${1:-}"
LABEL="${2:-prod}"
[ -n "$OUT" ] || { echo "uso: $0 <cartella-di-uscita> [etichetta]" >&2; exit 64; }
mkdir -p "$OUT"
chmod 700 "$OUT"
cd "$OUT"

DAYS=10950
openssl req -x509 -newkey rsa:4096 -nodes -sha256 -days "$DAYS" \
    -subj "/O=Osmium Sound/CN=Osmium Sound RAUC CA ($LABEL)" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -keyout ca-key.pem -out ca.pem

openssl req -newkey rsa:4096 -nodes -sha256 \
    -subj "/O=Osmium Sound/CN=Osmium Sound RAUC signing ($LABEL)" \
    -keyout signing-key.pem -out signing.csr

printf 'basicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=codeSigning\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid\n' > ext.cnf
openssl x509 -req -sha256 -days "$DAYS" -in signing.csr \
    -CA ca.pem -CAkey ca-key.pem -CAcreateserial -extfile ext.cnf \
    -out signing-cert.pem
rm -f signing.csr ext.cnf ca.srl
cp ca.pem keyring.pem
chmod 600 ca-key.pem signing-key.pem

echo "PKI RAUC ($LABEL) pronta in $OUT"
openssl x509 -in signing-cert.pem -noout -subject -enddate
echo "1) committa keyring.pem in distro/rauc-keys/keyring.pem"
echo "2) gh secret set RAUC_SIGNING_KEY  < signing-key.pem"
echo "   gh secret set RAUC_SIGNING_CERT < signing-cert.pem"
echo "3) metti ca-key.pem al sicuro, offline: serve solo per emettere un nuovo certificato di firma"
