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

# The 60 -> 89 stretch of an image install: unpacking about ten thousand small
# files, then getting them onto the disk. On an internal disk that is seconds;
# on a USB stick small writes are the slowest thing it does, and it can take
# many minutes. With a single status for all of it the bar sat at 60 % the
# whole time and the install looked hung. These two keep it moving with what
# is really happening; the state stays `applying`, which every interface
# already shows in its own language.
dirty_kb() {  # what the kernel still has to write out, in kB
    awk '/^(Dirty|Writeback):/ { s += $2 } END { print s + 0 }' /proc/meminfo
}

extract_with_progress() {  # <deb> <dest> <entries in the deb>: 60 -> 80
    dpkg-deb -x "$1" "$2" &
    _ewp_pid=$!
    _ewp_total=$3
    [ "$_ewp_total" -gt 0 ] || _ewp_total=1
    while kill -0 "$_ewp_pid" 2>/dev/null; do
        _ewp_n=$(find "$2" 2>/dev/null | wc -l)
        _ewp_p=$(( 60 + 20 * _ewp_n / _ewp_total ))
        [ "$_ewp_p" -le 79 ] || _ewp_p=79
        write_status applying "$_ewp_p" "Installazione in $2 ($_ewp_n/$3 file)…"
        sleep 2
    done
    wait "$_ewp_pid"
}

flush_with_progress() {  # <path>: write its filesystem's data out, 80 -> 89
    _fwp_d0=$(dirty_kb)
    sync -f "$1" &
    _fwp_pid=$!
    while kill -0 "$_fwp_pid" 2>/dev/null; do
        _fwp_d=$(dirty_kb)
        _fwp_p=80
        if [ "$_fwp_d0" -gt 0 ] && [ "$_fwp_d" -lt "$_fwp_d0" ]; then
            _fwp_p=$(( 80 + 9 * (_fwp_d0 - _fwp_d) / _fwp_d0 ))
        fi
        write_status applying "$_fwp_p" "Scrittura su disco ($(( _fwp_d / 1024 )) MB ancora da scrivere)…"
        sleep 2
    done
    wait "$_fwp_pid"
}

[ -n "$URL" ] || fail "URL di download mancante"

# The package is installed as root (apt-get on a legacy root, extracted into
# the server's own paths on an image), and the download server publishes no
# checksum to hold it against: lyrion.org/downloads, which api_server.py
# parses, lists bare .deb links and nothing else. What vouches for the file
# is TLS to that server, so https only — redirects included (the curl flags
# below) — and then the package must be a well-formed .deb that says it is
# lyrionmusicserver (check_deb).
case "$URL" in
    https://*) ;;
    *) fail "URL di download non https: $URL" ;;
esac

download_deb() {
    # The .deb and what it unpacks into: about 1 GiB. Checked first, so a full
    # disk is said plainly instead of ending in a half-installed Lyrion.
    if [ -f /usr/local/bin/hifi_diskguard.py ]; then
        mkdir -p "$WORKDIR"
        if ! _room=$(python3 /usr/local/bin/hifi_diskguard.py need-free "$WORKDIR" 1073741824 2>/dev/null); then
            if [ -n "$_room" ]; then fail "$_room"; fi
        fi
    fi
    hifi_curl_progress "$URL" "$DEB" 20 55 "Scaricamento Lyrion $VERSION…" \
        --proto '=https' --proto-redir '=https' \
        || fail "Download fallito da $URL"
}

check_deb() {
    # download errors often yield HTML: a .deb is an ar archive
    head -c2 "$DEB" | grep -q '!<' || fail "Il file scaricato non è un .deb valido"
    dpkg-deb --info "$DEB" >/dev/null 2>&1 || fail "Il file scaricato non è un .deb valido"
    _pkg=$(dpkg-deb -f "$DEB" Package 2>/dev/null || true)
    [ "$_pkg" = lyrionmusicserver ] \
        || fail "Il pacchetto scaricato non è Lyrion (Package: ${_pkg:-?})"
}

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
    download_deb
    check_deb
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
    entries=$(dpkg-deb -c "$DEB" | wc -l)
    extract_with_progress "$DEB" "$dest.new" "$entries" || fail "Estrazione del .deb fallita"
    printf '%s\n' "$ver" > "$dest.new/VERSION"
    # On the disk before `current` points at it, and with the bar moving
    # while it gets there (the slow part on a USB stick).
    flush_with_progress "$dest.new" || fail "Scrittura su disco fallita"
    rm -rf "$dest"; mv "$dest.new" "$dest"
    systemctl stop lyrionmusicserver 2>/dev/null || true
    ln -sfn "$ver" "$LYR_ROOT/current.new" && mv -T "$LYR_ROOT/current.new" "$LYR_ROOT/current"
    sync
    # ciò che faceva il postinst: cartelle di stato del server e loro proprietario
    for d in /var/lib/squeezeboxserver /var/lib/squeezeboxserver/prefs /var/lib/squeezeboxserver/cache \
             /var/lib/squeezeboxserver/playlists /var/log/squeezeboxserver; do
        mkdir -p "$d"; chown squeezeboxserver:nogroup "$d" 2>/dev/null || true
    done
    # versioni vecchie: si tiene solo quella in uso
    # Only the version in use stays. The one it replaced used to be kept "as
    # a way back", but nothing ever went back to it by itself, and on a 16 GB
    # disk (about 5 GB of data partition) its ~225 MB were missed. A leftover
    # <ver>.new of an interrupted install goes too.
    keep=$(basename "$(readlink "$LYR_ROOT/current")")
    # (never with no version in use to go by: that would take them all)
    if [ -n "$keep" ] && [ -d "$LYR_ROOT/$keep" ]; then
        find "$LYR_ROOT" -mindepth 1 -maxdepth 1 -type d ! -name "$keep" ! -name current -exec rm -rf {} +
    fi
    write_status restarting 90 "Riavvio Lyrion…"
    systemctl daemon-reload 2>/dev/null || true
    # A deliberate start must not be refused by the unit's crash-loop limit
    # (five starts in five minutes), which also counts the stops and starts
    # the first-run setup does around this install.
    # The new version's /etc/squeezeboxserver is fresh: put the PCM to DSD
    # rules of this device's players back before Lyrion reads it.
    python3 /usr/local/bin/hifi_squeezelite.py lms-rules 2>/dev/null || true
    systemctl reset-failed lyrionmusicserver 2>/dev/null || true
    systemctl start lyrionmusicserver 2>/dev/null || true
    rm -rf "$WORKDIR"
    write_status 'done' 100 "Lyrion aggiornato a $VERSION"
    exit 0
fi

rm -rf "$WORKDIR"; mkdir -p "$WORKDIR"
download_deb
check_deb

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
# The new version's /etc/squeezeboxserver is fresh: put the PCM to DSD
# rules of this device's players back before Lyrion reads it.
python3 /usr/local/bin/hifi_squeezelite.py lms-rules 2>/dev/null || true
systemctl reset-failed lyrionmusicserver 2>/dev/null || true
systemctl restart lyrionmusicserver 2>/dev/null || true

rm -rf "$WORKDIR"
write_status 'done' 100 "Lyrion aggiornato a $VERSION"
