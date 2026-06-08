#!/bin/sh
# HiFi Player appliance — OTA update of the Electron UI.
#
# Downloads a new linux-unpacked tarball, verifies its sha256, atomically
# replaces /opt/hifi-media-player (keeping one backup for rollback), re-applies
# the chrome-sandbox SUID + /usr/bin symlink, writes the new version, and
# restarts the kiosk session (lightdm).
#
# Invoked as root by api_server.py, normally via systemd-run so it survives the
# lightdm restart:
#     hifi-ota-update.sh <download_url> <sha256> <version>
set -eu

URL="${1:-}"
SHA="${2:-}"
VERSION="${3:-unknown}"

APPDIR=/opt/hifi-media-player
NEWDIR=/opt/hifi-media-player.new
OLDDIR=/opt/hifi-media-player.old
WORKDIR=/var/tmp/hifi-ota
TARBALL="$WORKDIR/hifi-ui.tar.gz"
STATUS=/run/hifi-ota-status.json

# ── status helper ────────────────────────────────────────────────────
# write_status <state> <progress> <message>
write_status() {
    state="$1"; progress="$2"; msg="$3"
    # message is plain text — escape backslashes and double quotes for JSON.
    esc=$(printf '%s' "$msg" | sed 's/\\/\\\\/g; s/"/\\"/g')
    printf '{"state":"%s","progress":%s,"version":"%s","message":"%s"}\n' \
        "$state" "$progress" "$VERSION" "$esc" > "$STATUS"
}

fail() {
    write_status error 0 "$1"
    echo "E: [hifi-ota] $1" >&2
    exit 1
}

[ -n "$URL" ] || fail "URL di download mancante"
[ -n "$SHA" ] || fail "Checksum sha256 mancante"

# ── download ─────────────────────────────────────────────────────────
write_status downloading 10 "Scaricamento aggiornamento $VERSION…"
rm -rf "$WORKDIR"; mkdir -p "$WORKDIR"
curl -fL --retry 3 -o "$TARBALL" "$URL" \
    || fail "Download fallito da $URL"

# ── verify ───────────────────────────────────────────────────────────
write_status verifying 40 "Verifica integrità…"
ACTUAL=$(sha256sum "$TARBALL" | awk '{print $1}')
if [ "$ACTUAL" != "$SHA" ]; then
    fail "Checksum non valido (atteso $SHA, ottenuto $ACTUAL)"
fi

# ── extract ──────────────────────────────────────────────────────────
write_status applying 60 "Estrazione…"
rm -rf "$NEWDIR"; mkdir -p "$NEWDIR"
tar xzf "$TARBALL" -C "$NEWDIR" || fail "Estrazione del tarball fallita"

# sanity-check the new payload before swapping
[ -x "$NEWDIR/hifi-media-player" ] \
    || fail "Bundle non valido: $NEWDIR/hifi-media-player mancante"

# ── atomic swap (keep a single backup) ───────────────────────────────
write_status applying 80 "Applicazione…"
rm -rf "$OLDDIR"
if [ -d "$APPDIR" ]; then
    mv "$APPDIR" "$OLDDIR"
fi
if ! mv "$NEWDIR" "$APPDIR"; then
    # restore backup on failure
    [ -d "$OLDDIR" ] && mv "$OLDDIR" "$APPDIR"
    fail "Sostituzione della cartella app fallita"
fi

# ── finalise (mirror 0300-app-install.hook.chroot) ───────────────────
if [ -f "$APPDIR/chrome-sandbox" ]; then
    chown root:root "$APPDIR/chrome-sandbox"
    chmod 4755 "$APPDIR/chrome-sandbox"
fi
ln -sf "$APPDIR/hifi-media-player" /usr/bin/hifi-media-player
printf '%s\n' "$VERSION" > "$APPDIR/UI_VERSION"

# ── restart kiosk session ────────────────────────────────────────────
write_status restarting 95 "Riavvio interfaccia…"
rm -f "$TARBALL"
write_status done 100 "Aggiornamento a $VERSION completato"

# Restarting lightdm kills the running Electron app (and any HTTP client still
# polling). Do it last; systemd-run keeps this script alive across the restart.
systemctl restart lightdm || true
