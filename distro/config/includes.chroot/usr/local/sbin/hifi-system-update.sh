#!/bin/sh
# HiFi Player appliance — OTA update of the custom system components.
#
# Downloads a `hifi-system-<ver>.tar.gz` bundle, verifies its sha256, and
# installs the files it contains (Python API/daemons under /usr/local/bin,
# helper scripts under /usr/local/sbin, systemd units under
# /etc/systemd/system), then reloads systemd and restarts the affected
# services. The new SYSTEM_VERSION is recorded under /etc/hifi-player.
#
# The bundle mirrors the target filesystem layout, e.g.:
#     ./usr/local/bin/api_server.py
#     ./etc/systemd/system/hifi-api.service
#     ./SYSTEM_VERSION
#
# Invoked as root by api_server.py, normally via systemd-run so it survives
# the api restart:
#     hifi-system-update.sh <download_url> <sha256> <version>
set -eu

URL="${1:-}"
SHA="${2:-}"
VERSION="${3:-unknown}"

WORKDIR=/var/tmp/hifi-system-ota
TARBALL="$WORKDIR/hifi-system.tar.gz"
NEWROOT="$WORKDIR/root"
VERSION_FILE=/etc/hifi-player/SYSTEM_VERSION
STATUS=/run/hifi-system-status.json

# ── status helper ────────────────────────────────────────────────────
write_status() {
    state="$1"; progress="$2"; msg="$3"
    esc=$(printf '%s' "$msg" | sed 's/\\/\\\\/g; s/"/\\"/g')
    printf '{"state":"%s","progress":%s,"version":"%s","message":"%s"}\n' \
        "$state" "$progress" "$VERSION" "$esc" > "$STATUS"
}

fail() {
    write_status error 0 "$1"
    echo "E: [hifi-system] $1" >&2
    exit 1
}

[ -n "$URL" ] || fail "URL di download mancante"
[ -n "$SHA" ] || fail "Checksum sha256 mancante"

# ── download ─────────────────────────────────────────────────────────
write_status downloading 10 "Scaricamento componenti $VERSION…"
rm -rf "$WORKDIR"; mkdir -p "$NEWROOT"
curl -fL --retry 3 -o "$TARBALL" "$URL" \
    || fail "Download fallito da $URL"

# ── verify ───────────────────────────────────────────────────────────
write_status verifying 35 "Verifica integrità…"
ACTUAL=$(sha256sum "$TARBALL" | awk '{print $1}')
if [ "$ACTUAL" != "$SHA" ]; then
    fail "Checksum non valido (atteso $SHA, ottenuto $ACTUAL)"
fi

# ── extract ──────────────────────────────────────────────────────────
write_status applying 55 "Estrazione…"
tar xzf "$TARBALL" -C "$NEWROOT" || fail "Estrazione del bundle fallita"

# sanity-check the payload before touching the system
[ -f "$NEWROOT/usr/local/bin/api_server.py" ] \
    || fail "Bundle non valido: api_server.py mancante"

# ── install files ────────────────────────────────────────────────────
write_status applying 75 "Installazione file…"
[ -d "$NEWROOT/usr/local/bin" ]      && cp -af "$NEWROOT/usr/local/bin/."      /usr/local/bin/
[ -d "$NEWROOT/usr/local/sbin" ]     && cp -af "$NEWROOT/usr/local/sbin/."     /usr/local/sbin/
[ -d "$NEWROOT/etc/systemd/system" ] && cp -af "$NEWROOT/etc/systemd/system/." /etc/systemd/system/

# normalise CRLF + perms for the things we just shipped
for f in /usr/local/bin/api_server.py /usr/local/bin/vu_meter_daemon.py \
         /usr/local/bin/sources_server.py; do
    [ -f "$f" ] && { sed -i 's/\r$//' "$f"; chmod +x "$f"; }
done
chmod +x /usr/local/sbin/hifi-*.sh 2>/dev/null || true

# record the new version (outside /opt so a UI OTA can't wipe it)
mkdir -p "$(dirname "$VERSION_FILE")"
printf '%s\n' "$VERSION" > "$VERSION_FILE"

# ── restart services ─────────────────────────────────────────────────
write_status restarting 90 "Riavvio servizi…"
systemctl daemon-reload || true
# Restart auxiliary services first; the API (our caller) last. This script
# runs under its own transient systemd unit, so restarting hifi-api here does
# not kill it.
for svc in hifi-vumeter hifi-sources squeezelite; do
    systemctl restart "$svc" 2>/dev/null || true
done

rm -rf "$WORKDIR"
write_status done 100 "Componenti aggiornati a $VERSION"

systemctl restart hifi-api 2>/dev/null || true
