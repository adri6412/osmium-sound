#!/bin/sh
# HiFi Player appliance — OTA update of the custom system components.
#
# Downloads a `hifi-system-<ver>.tar.gz` bundle, verifies its sha256, and
# installs the files it contains (Python API/daemons under /usr/local/bin,
# helper scripts under /usr/local/sbin, systemd units under
# /etc/systemd/system), then records the new SYSTEM_VERSION.
#
# The bundle mirrors the target filesystem layout, e.g.:
#     ./usr/local/bin/api_server.py
#     ./etc/systemd/system/hifi-api.service
#     ./SYSTEM_VERSION
#
# Split into two subcommands so download+verify (safe while the box is fully
# live) is separate from apply (which only ever runs isolated under
# system-update.target, driven by hifi-update-apply-runner.sh — nothing reads
# these files while apply installs them, so there is nothing to restart
# afterwards, unlike the old single-shot flow):
#     hifi-system-update.sh stage <download_url> <sha256> <version>
#     hifi-system-update.sh apply <staged_dir> <version>
#
# A third mode keeps the ORIGINAL single-shot behaviour (download, verify,
# install and restart the affected services — all in one call, on the live
# system) for api_server.py's single-component `/system_update/apply`
# endpoint, which is deliberately NOT part of the isolated-update-mode
# redesign (see apply_system_update() there):
#     hifi-system-update.sh full <download_url> <sha256> <version>
set -eu

CMD="${1:-}"
# Backward-compat: an old orchestrator (the pre-split hifi-update-runner.sh,
# quite possibly still running on THIS device when it received the very
# bundle that replaced this script) calls it with the OLD 3-arg convention —
# <url> <sha256> <version>, no subcommand. Without this, the very first
# update after this split lands would fail outright (URL lands in $CMD,
# matches nothing, exit 64) and need a manual retry. Detect it and treat it
# as `full`, so that first transition completes in one pass too. Must happen
# before the private-copy re-exec check below, which keys off $CMD too.
case "$CMD" in
    stage|apply|full) ;;
    *) set -- full "$@"; CMD=full ;;
esac
VERSION_FILE=/etc/hifi-player/SYSTEM_VERSION
STATUS=/run/hifi-system-status.json
STAGE_ROOT=/var/lib/hifi-player/update/staged/system
VERSION=unknown

# Sourced defensively: under `set -e` a missing/unreadable helper would abort
# this script before write_status/fail exist, i.e. before it could report
# anything — the status file would just stay on its previous contents and the
# caller would wait for a step that already died.
if [ -r /usr/local/sbin/hifi-log.sh ]; then
    # shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-log.sh
    # shellcheck disable=SC1091  # absolute target, only present on the appliance
    . /usr/local/sbin/hifi-log.sh
    hifi_log_init hifi-system-update
fi

# ── run `apply`/`full` from a private copy ───────────────────────────
# Both install /usr/local/sbin/*.sh with `cp -af`, which rewrites files IN
# PLACE — including this one. /bin/sh reads a script incrementally, by byte
# offset, so from the copy onwards we would be executing whatever happens to
# sit at our old offset inside the NEW file: a truncated run that silently
# skips the rest of the install. Re-exec from a copy under /var/tmp first,
# which nothing in the bundle touches. `stage` never touches /usr/local/sbin
# (it only writes under the persistent staging dir), so it doesn't need this.
if { [ "$CMD" = apply ] || [ "$CMD" = full ]; } && [ "${HIFI_SYSUPD_PRIVATE:-}" != "1" ]; then
    _self=$(readlink -f "$0" 2>/dev/null || echo "$0")
    _dir=$(mktemp -d /var/tmp/hifi-system-update.XXXXXX) || _dir=""
    if [ -n "$_dir" ] && cp -f "$_self" "$_dir/update.sh"; then
        chmod +x "$_dir/update.sh"
        HIFI_SYSUPD_PRIVATE=1
        HIFI_SYSUPD_TMPDIR="$_dir"
        export HIFI_SYSUPD_PRIVATE HIFI_SYSUPD_TMPDIR
        exec /bin/sh "$_dir/update.sh" "$@"
    fi
    [ -n "$_dir" ] && rm -rf "$_dir"
fi
# The `: ` keeps the trap's exit status at 0: a trap whose last command fails can
# replace the script's exit status, and the caller reads that status to
# decide whether this step succeeded.
trap '{ [ -n "${HIFI_SYSUPD_TMPDIR:-}" ] && rm -rf "$HIFI_SYSUPD_TMPDIR"; }; :' EXIT INT TERM

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

case "$CMD" in
stage)
    URL="${2:-}"
    SHA="${3:-}"
    VERSION="${4:-unknown}"
    [ -n "$URL" ] || fail "URL di download mancante"
    [ -n "$SHA" ] || fail "Checksum sha256 mancante"
    case "$VERSION" in
        ''|*[!0-9A-Za-z._-]*) fail "Versione non valida" ;;
    esac

    # Persistent staging dir (survives the reboot into update-mode), keyed by
    # version so a re-stage of the same release cleanly replaces itself.
    WORKDIR="$STAGE_ROOT/$VERSION"
    rm -rf "$WORKDIR"; mkdir -p "$WORKDIR/root"
    TARBALL="$WORKDIR/hifi-system.tar.gz"
    if command -v hifi_curl_progress >/dev/null 2>&1; then
        hifi_curl_progress "$URL" "$TARBALL" 10 40 "Scaricamento componenti $VERSION…" \
            || fail "Download fallito da $URL"
    else
        write_status downloading 10 "Scaricamento componenti $VERSION…"
        curl -fL --retry 3 -o "$TARBALL" "$URL" \
            || fail "Download fallito da $URL"
    fi

    write_status verifying 55 "Verifica integrità…"
    ACTUAL=$(sha256sum "$TARBALL" | awk '{print $1}')
    if [ "$ACTUAL" != "$SHA" ]; then
        fail "Checksum non valido (atteso $SHA, ottenuto $ACTUAL)"
    fi

    write_status applying 75 "Estrazione…"
    tar xzf "$TARBALL" -C "$WORKDIR/root" || fail "Estrazione del bundle fallita"

    # sanity-check the payload before it is trusted for later
    [ -f "$WORKDIR/root/usr/local/bin/api_server.py" ] \
        || fail "Bundle non valido: api_server.py mancante"

    rm -f "$TARBALL"
    printf '%s\n' "$VERSION" > "$WORKDIR/STAGED"
    write_status staged 100 "Componenti verificati ($VERSION), in attesa di applicazione"
    ;;

apply)
    STAGED_DIR="${2:-}"
    VERSION="${3:-unknown}"
    NEWROOT="$STAGED_DIR/root"
    [ -n "$STAGED_DIR" ] || fail "Percorso staging mancante"
    [ "$(cat "$STAGED_DIR/STAGED" 2>/dev/null)" = "$VERSION" ] \
        || fail "Pacchetto system mancante o non corrispondente in $STAGED_DIR"
    [ -f "$NEWROOT/usr/local/bin/api_server.py" ] \
        || fail "Bundle non valido: api_server.py mancante"

    # ── install files ────────────────────────────────────────────────
    write_status applying 50 "Installazione file…"
    [ -d "$NEWROOT/usr/local/bin" ]      && cp -af "$NEWROOT/usr/local/bin/."      /usr/local/bin/
    [ -d "$NEWROOT/usr/local/sbin" ]     && cp -af "$NEWROOT/usr/local/sbin/."     /usr/local/sbin/
    [ -d "$NEWROOT/etc/systemd/system" ] && cp -af "$NEWROOT/etc/systemd/system/." /etc/systemd/system/
    # Web-admin Vue build ships under /opt (outside the three dirs above).
    [ -d "$NEWROOT/opt/hifi-webui" ]     && { mkdir -p /opt/hifi-webui; cp -af "$NEWROOT/opt/hifi-webui/." /opt/hifi-webui/; }

    # normalise CRLF + perms for the things we just shipped
    for f in /usr/local/bin/api_server.py /usr/local/bin/vu_meter_daemon.py \
             /usr/local/bin/sources_server.py /usr/local/bin/webui_server.py \
             /usr/local/bin/hifi_logging.py; do
        [ -f "$f" ] && { sed -i 's/\r$//' "$f"; chmod +x "$f"; }
    done
    chmod +x /usr/local/sbin/hifi-*.sh /usr/local/sbin/hifi-*.py 2>/dev/null || true

    # record the new version (outside /opt so a UI OTA can't wipe it)
    mkdir -p "$(dirname "$VERSION_FILE")"
    printf '%s\n' "$VERSION" > "$VERSION_FILE"

    # Enable any new units this bundle shipped. Idempotent and enable-ONLY —
    # `systemctl enable` just creates a symlink, it never starts anything, so
    # this stays safe even though nothing is (or should be) running right now
    # under system-update.target. No restarts here: the box reboots once, at
    # the end of the whole update-mode session, and every service simply comes
    # up fresh with the new code already in place.
    write_status applying 90 "Registrazione servizi…"
    if [ -f /etc/systemd/system/hifi-webui.service ]; then
        systemctl enable hifi-webui.service 2>/dev/null || true
    fi
    if [ -f /etc/systemd/system/hifi-update-stage-resume.service ]; then
        systemctl enable hifi-update-stage-resume.service 2>/dev/null || true
    fi
    if [ -f /etc/systemd/system/hifi-update-apply.service ]; then
        systemctl enable hifi-update-apply.service 2>/dev/null || true
    fi

    write_status 'done' 100 "Componenti aggiornati a $VERSION"
    ;;

full)
    # Original, unmodified single-shot flow: download, verify, install and
    # restart the affected services, all on the live system, in one call.
    # Kept byte-for-byte equivalent to the pre-split script — see
    # api_server.py's apply_system_update() for why this path still exists.
    URL="${2:-}"
    SHA="${3:-}"
    VERSION="${4:-unknown}"
    [ -n "$URL" ] || fail "URL di download mancante"
    [ -n "$SHA" ] || fail "Checksum sha256 mancante"

    WORKDIR=/var/tmp/hifi-system-ota
    TARBALL="$WORKDIR/hifi-system.tar.gz"
    NEWROOT="$WORKDIR/root"
    rm -rf "$WORKDIR"; mkdir -p "$NEWROOT"
    if command -v hifi_curl_progress >/dev/null 2>&1; then
        hifi_curl_progress "$URL" "$TARBALL" 10 35 "Scaricamento componenti $VERSION…" \
            || fail "Download fallito da $URL"
    else
        write_status downloading 10 "Scaricamento componenti $VERSION…"
        curl -fL --retry 3 -o "$TARBALL" "$URL" \
            || fail "Download fallito da $URL"
    fi

    write_status verifying 35 "Verifica integrità…"
    ACTUAL=$(sha256sum "$TARBALL" | awk '{print $1}')
    if [ "$ACTUAL" != "$SHA" ]; then
        fail "Checksum non valido (atteso $SHA, ottenuto $ACTUAL)"
    fi

    write_status applying 55 "Estrazione…"
    tar xzf "$TARBALL" -C "$NEWROOT" || fail "Estrazione del bundle fallita"

    [ -f "$NEWROOT/usr/local/bin/api_server.py" ] \
        || fail "Bundle non valido: api_server.py mancante"

    write_status applying 75 "Installazione file…"
    [ -d "$NEWROOT/usr/local/bin" ]      && cp -af "$NEWROOT/usr/local/bin/."      /usr/local/bin/
    [ -d "$NEWROOT/usr/local/sbin" ]     && cp -af "$NEWROOT/usr/local/sbin/."     /usr/local/sbin/
    [ -d "$NEWROOT/etc/systemd/system" ] && cp -af "$NEWROOT/etc/systemd/system/." /etc/systemd/system/
    [ -d "$NEWROOT/opt/hifi-webui" ]     && { mkdir -p /opt/hifi-webui; cp -af "$NEWROOT/opt/hifi-webui/." /opt/hifi-webui/; }

    for f in /usr/local/bin/api_server.py /usr/local/bin/vu_meter_daemon.py \
             /usr/local/bin/sources_server.py /usr/local/bin/webui_server.py \
             /usr/local/bin/hifi_logging.py; do
        [ -f "$f" ] && { sed -i 's/\r$//' "$f"; chmod +x "$f"; }
    done
    chmod +x /usr/local/sbin/hifi-*.sh /usr/local/sbin/hifi-*.py 2>/dev/null || true

    mkdir -p "$(dirname "$VERSION_FILE")"
    printf '%s\n' "$VERSION" > "$VERSION_FILE"

    write_status restarting 90 "Riavvio servizi…"
    systemctl daemon-reload || true
    for svc in hifi-vumeter hifi-sources squeezelite; do
        systemctl restart "$svc" 2>/dev/null || true
    done
    if [ -f /etc/systemd/system/hifi-webui.service ]; then
        systemctl enable hifi-webui.service 2>/dev/null || true
        systemctl restart hifi-webui.service 2>/dev/null || true
    fi
    if [ -f /etc/systemd/system/hifi-update-stage-resume.service ]; then
        systemctl enable hifi-update-stage-resume.service 2>/dev/null || true
    fi
    if [ -f /etc/systemd/system/hifi-update-apply.service ]; then
        systemctl enable hifi-update-apply.service 2>/dev/null || true
    fi
    if [ -f /etc/systemd/system/hifi-beta-agent.service ]; then
        systemctl restart hifi-beta-agent.service 2>/dev/null || true
    fi

    rm -rf "$WORKDIR"
    write_status 'done' 100 "Componenti aggiornati a $VERSION"

    # Restarting hifi-api kills any client that was polling us — safe here
    # because this path is only ever launched under its own transient
    # systemd-run unit (see apply_system_update() in api_server.py), which
    # survives the restart. Keep it last regardless.
    systemctl restart hifi-api 2>/dev/null || true
    ;;

*)
    echo "Uso: $0 stage <url> <sha256> <versione>" >&2
    echo "     $0 apply <staged_dir> <versione>" >&2
    echo "     $0 full <url> <sha256> <versione>" >&2
    exit 64
    ;;
esac
