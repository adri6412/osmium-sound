#!/bin/sh
# HiFi Player appliance — update Lyrion Music Server to a newer stable .deb.
#
# Downloads the .deb from the community downloads server and installs it with
# apt (which resolves dependencies and upgrades the existing package), then
# restarts the service. Invoked as root by api_server.py via systemd-run:
#     hifi-lyrion-update.sh <download_url> <version>
set -eu

# shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-log.sh
# shellcheck disable=SC1091  # percorso assoluto, esiste solo sull'apparecchio
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

# ── slot immagine (root in sola lettura): niente apt, Lyrion vive su /data ──
# Il .deb viene solo scompattato (dpkg-deb -x) in /data/lyrion/<ver>; i percorsi
# canonici nell'immagine sono symlink verso /data/lyrion/current. Prima di
# installare, tre controlli ("guardiano"): le dipendenze devono essere già
# nell'immagine, i file devono stare nei percorsi collegati, gli script di
# controllo devono essere quelli noti (le loro migrazioni vanno rifatte qui a
# mano). Se uno fallisce l'aggiornamento è TRATTENUTO e Lyrion resta com'è:
# la correzione arriva con l'immagine successiva.
if [ -f /usr/lib/osmium/IMAGE_VERSION ]; then
    LYR_ROOT=/data/lyrion
    KNOWN_CTL=/usr/local/share/hifi-ab/lyrion-control.sha256
    HELD=/var/lib/hifi-player/lyrion-held.json
    hold() {  # <motivo> — trattenuto, non è un guasto
        esc=$(printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g')
        mkdir -p "$(dirname "$HELD")"
        printf '{"version":"%s","reason":"%s","when":"%s"}\n' "$VERSION" "$esc" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$HELD"
        write_status error 0 "Aggiornamento Lyrion trattenuto: $1 — richiede un aggiornamento di sistema"
        echo "W: [hifi-lyrion] trattenuto: $1" >&2
        exit 3
    }
    mountpoint -q /data || fail "/data non montata"
    rm -rf "$WORKDIR"; mkdir -p "$WORKDIR"
    hifi_curl_progress "$URL" "$DEB" 20 55 "Scaricamento Lyrion $VERSION…" \
        || fail "Download fallito da $URL"
    head -c2 "$DEB" | grep -q '!<' || fail "Il file scaricato non è un .deb valido"
    ver=$(dpkg-deb -f "$DEB" Version 2>/dev/null || true)
    [ -n "$ver" ] || fail "Impossibile leggere la versione dal .deb"
    write_status verifying 58 "Verifica compatibilità con l'immagine…"

    # 1) dipendenze: tutte già nell'immagine — per nome di pacchetto o per
    #    nome virtuale (Provides: es. libgcc1 ← libgcc-s1), elenco scritto in build
    PROVIDED=/usr/lib/osmium/packages-provided.txt
    missing=""
    for d in $(dpkg-deb -f "$DEB" Depends 2>/dev/null | tr ',' '\n' | sed 's/|.*//; s/(.*//; s/^[[:space:]]*//; s/[[:space:]]*$//' | grep -v '^$'); do
        if grep -qx "$d" "$PROVIDED" 2>/dev/null || grep -q "^$d	" /usr/lib/osmium/packages.txt 2>/dev/null; then
            continue
        fi
        missing="$missing $d"
    done
    [ -z "$missing" ] || hold "dipendenze assenti dall'immagine:$missing"

    # 2) percorsi: solo quelli collegati dall'immagine (o scrivibili)
    stray=$(dpkg-deb -c "$DEB" | awk '{print $6}' | sed 's|^\./||; s|/$||' | grep -v '^$' \
        | grep -vE '^(usr|usr/share|usr/sbin|usr/lib|etc|etc/default|etc/init\.d|etc/logrotate\.d|lib|lib/systemd|lib/systemd/system|usr/lib/systemd|usr/lib/systemd/system)$' \
        | grep -vE '^(usr/share/squeezeboxserver(/.*)?|usr/share/perl5(/Slim(/.*)?)?|usr/sbin/squeezeboxserver[^/]*|etc/squeezeboxserver(/.*)?|etc/default/lyrionmusicserver|etc/init\.d/lyrionmusicserver|etc/logrotate\.d/lyrionmusicserver|lib/systemd/system/[^/]+|usr/lib/systemd/system/[^/]+|usr/share/doc(/.*)?|usr/share/lintian(/.*)?|var(/.*)?)$' \
        | head -n 5 | tr '\n' ' ')
    [ -z "$stray" ] || hold "file fuori dai percorsi previsti: $stray"

    # 3) script di controllo: solo quelli già esaminati
    rm -rf "$WORKDIR/ctl"; mkdir -p "$WORKDIR/ctl"
    dpkg-deb -e "$DEB" "$WORKDIR/ctl" || fail "Impossibile estrarre gli script di controllo"
    unknown=""
    for sname in preinst postinst prerm postrm; do
        [ -f "$WORKDIR/ctl/$sname" ] || continue
        h=$(sha256sum "$WORKDIR/ctl/$sname" | cut -d' ' -f1)
        grep -q "^$h  $sname$" "$KNOWN_CTL" 2>/dev/null || unknown="$unknown $sname"
    done
    if [ -n "$unknown" ] && [ "${HIFI_LYRION_ALLOW_UNKNOWN_SCRIPTS:-0}" != 1 ]; then
        hold "script di installazione nuovi ($unknown) da esaminare"
    fi
    rm -f "$HELD"

    write_status applying 60 "Installazione in /data/lyrion/$ver…"
    dest="$LYR_ROOT/$ver"
    rm -rf "$dest.new"; mkdir -p "$dest.new"
    dpkg-deb -x "$DEB" "$dest.new" || fail "Estrazione del .deb fallita"
    printf '%s\n' "$ver" > "$dest.new/VERSION"
    rm -rf "$dest"; mv "$dest.new" "$dest"
    systemctl stop lyrionmusicserver 2>/dev/null || true
    ln -sfn "$ver" "$LYR_ROOT/current.new" && mv -T "$LYR_ROOT/current.new" "$LYR_ROOT/current"
    sync
    # ciò che faceva il postinst: cartelle di stato del server e loro proprietario
    for d in /var/lib/squeezeboxserver /var/lib/squeezeboxserver/prefs /var/lib/squeezeboxserver/cache \
             /var/lib/squeezeboxserver/playlists /var/log/squeezeboxserver; do
        mkdir -p "$d"; chown squeezeboxserver:nogroup "$d" 2>/dev/null || true
    done
    # versioni vecchie: si tiene solo la precedente
    keep=$(readlink "$LYR_ROOT/current")
    for old in "$LYR_ROOT"/*/; do
        old=${old%/}; b=$(basename "$old")
        [ "$b" = "$keep" ] && continue
        [ "$b" = current ] && continue
        n=$(find "$LYR_ROOT" -mindepth 1 -maxdepth 1 -type d ! -name "$keep" | wc -l)
        [ "$n" -gt 1 ] && rm -rf "$old"
    done
    write_status restarting 90 "Riavvio Lyrion…"
    systemctl daemon-reload 2>/dev/null || true
    systemctl start lyrionmusicserver 2>/dev/null || true
    rm -rf "$WORKDIR"
    write_status 'done' 100 "Lyrion aggiornato a $VERSION"
    exit 0
fi

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
write_status 'done' 100 "Lyrion aggiornato a $VERSION"
