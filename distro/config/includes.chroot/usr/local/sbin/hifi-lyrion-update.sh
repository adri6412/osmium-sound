#!/bin/sh
# HiFi Player appliance — update Lyrion Music Server to a newer stable .deb.
#
# Downloads the .deb from the community downloads server and installs it with
# apt (which resolves dependencies and upgrades the existing package), then
# restarts the service. Invoked as root by api_server.py via systemd-run:
#     hifi-lyrion-update.sh <download_url> <version>
set -eu

# shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-log.sh
. /usr/local/sbin/hifi-log.sh
hifi_log_init hifi-lyrion-update

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

rm -rf "$WORKDIR"; mkdir -p "$WORKDIR"
hifi_curl_progress "$URL" "$DEB" 20 55 "Scaricamento Lyrion $VERSION…" \
    || fail "Download fallito da $URL"

# sanity-check it is really a .deb (download errors often yield HTML)
head -c2 "$DEB" | grep -q '!<' || fail "Il file scaricato non è un .deb valido"

write_status applying 60 "Installazione…"
export DEBIAN_FRONTEND=noninteractive
# apt-get install on a local .deb upgrades the package and pulls any new deps.
#
# Deliberately NOT trusting apt's exit code on its own: Lyrion's postinst is
# noisy (it enables/starts its own unit and warns about perl/plugin state), and
# a non-zero exit from a maintainer script or a trigger makes apt return
# non-zero even when the package ends up fully unpacked AND configured. That
# made a perfectly good install show up in the setup wizard as
# "Installazione del pacchetto fallita" — the failure was in the reporting,
# not in the install. dpkg's own recorded state is the authority here; apt's
# exit code is kept only as diagnostic detail when dpkg agrees it failed.
apt_rc=0
apt-get install -y --allow-downgrades "$DEB" || apt_rc=$?
pkg_state=$(dpkg-query -W -f='${db:Status-Status}' lyrionmusicserver 2>/dev/null || true)
if [ "$pkg_state" != "installed" ]; then
    fail "Installazione del pacchetto fallita (apt rc=$apt_rc, stato dpkg: ${pkg_state:-assente})"
fi
[ "$apt_rc" -eq 0 ] \
    || echo "W: [hifi-lyrion] apt ha restituito $apt_rc ma dpkg riporta il pacchetto installato e configurato — proseguo" >&2

write_status restarting 90 "Riavvio Lyrion…"
systemctl restart lyrionmusicserver 2>/dev/null || true

rm -rf "$WORKDIR"
write_status done 100 "Lyrion aggiornato a $VERSION"
