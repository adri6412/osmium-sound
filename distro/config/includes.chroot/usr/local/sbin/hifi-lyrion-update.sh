#!/bin/sh
# HiFi Player appliance — update Lyrion Music Server to a newer stable .deb.
#
# Downloads the .deb from the community downloads server and installs it with
# apt (which resolves dependencies and upgrades the existing package), then
# restarts the service. Invoked as root by api_server.py via systemd-run:
#     hifi-lyrion-update.sh <download_url> <version>
set -eu

URL="${1:-}"
VERSION="${2:-unknown}"

WORKDIR=/var/tmp/hifi-lyrion-ota
DEB="$WORKDIR/lyrionmusicserver.deb"
STATUS=/run/hifi-lyrion-status.json

write_status() {
    state="$1"; progress="$2"; msg="$3"
    esc=$(printf '%s' "$msg" | sed 's/\\/\\\\/g; s/"/\\"/g')
    printf '{"state":"%s","progress":%s,"version":"%s","message":"%s"}\n' \
        "$state" "$progress" "$VERSION" "$esc" > "$STATUS"
}

fail() {
    write_status error 0 "$1"
    echo "E: [hifi-lyrion] $1" >&2
    exit 1
}

[ -n "$URL" ] || fail "URL di download mancante"

write_status downloading 20 "Scaricamento Lyrion $VERSION…"
rm -rf "$WORKDIR"; mkdir -p "$WORKDIR"
curl -fL --retry 3 -o "$DEB" "$URL" || fail "Download fallito da $URL"

# sanity-check it is really a .deb (download errors often yield HTML)
head -c2 "$DEB" | grep -q '!<' || fail "Il file scaricato non è un .deb valido"

write_status applying 60 "Installazione…"
export DEBIAN_FRONTEND=noninteractive
# apt-get install on a local .deb upgrades the package and pulls any new deps.
if ! apt-get install -y --allow-downgrades "$DEB"; then
    fail "Installazione del pacchetto fallita"
fi

write_status restarting 90 "Riavvio Lyrion…"
systemctl restart lyrionmusicserver 2>/dev/null || true

rm -rf "$WORKDIR"
write_status done 100 "Lyrion aggiornato a $VERSION"
