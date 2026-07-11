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
write_status applying 55 "Estrazione…"
rm -rf "$NEWDIR"; mkdir -p "$NEWDIR"

# Free-space guard (root cause of the "file too short" brick): a full disk lets
# tar write a truncated file — any file, not just libffmpeg.so — and the kiosk
# then fails to start. Refuse to extract unless the target FS can hold the
# uncompressed tree plus a safety margin. The uncompressed size comes from the
# gzip footer (fast, no full read); fall back to ~4× the compressed size.
need_kb=$(gzip -l "$TARBALL" 2>/dev/null | awk 'NR==2 && $2 ~ /^[0-9]+$/ {print int($2/1024)}')
[ -n "${need_kb:-}" ] && [ "$need_kb" -gt 0 ] 2>/dev/null \
    || need_kb=$(( ($(wc -c < "$TARBALL") / 1024) * 4 ))
free_kb=$(df -Pk "$NEWDIR" | awk 'NR==2 {print $4}')
if [ -n "${free_kb:-}" ] && [ "$free_kb" -lt $(( need_kb + 51200 )) ]; then
    fail "Spazio insufficiente per l'aggiornamento: servono ~$((need_kb/1024)) MB, liberi ~$((free_kb/1024)) MB"
fi

tar xzf "$TARBALL" -C "$NEWDIR" || fail "Estrazione del tarball fallita"

# ── integrity: verify EVERY extracted file against the archive ───────
# Not just the main binary. `tar --compare` re-reads the archive and flags a
# size/content mismatch for ANY member, so a single truncated file (a .so, a
# resource, an asar) can no longer slip through and brick the kiosk. Filter to
# real corruption ("Size differs"/"Contents differ") — ownership/mode/time
# lines are expected (archive stores the CI runner's uid, we extract as root).
write_status verifying 70 "Verifica integrità dei file estratti…"
corrupt=$(tar dzf "$TARBALL" -C "$NEWDIR" 2>&1 \
    | grep -iE 'Size differs|Contents differ' | head -n 1 || true)
if [ -n "$corrupt" ]; then
    rm -rf "$NEWDIR"
    fail "Bundle estratto corrotto: $corrupt"
fi

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
