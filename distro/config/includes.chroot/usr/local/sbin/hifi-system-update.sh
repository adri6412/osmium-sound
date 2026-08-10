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
# Invoked as root by hifi-update-runner.sh (which runs under its own transient
# systemd unit, so it survives the api restart below), or directly by
# api_server.py via systemd-run for a single-component update:
#     hifi-system-update.sh <download_url> <sha256> <version>
set -eu

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

# ── run from a private copy ──────────────────────────────────────────
# This script installs /usr/local/sbin/*.sh with `cp -af`, which rewrites files
# IN PLACE — including this one. /bin/sh reads a script incrementally, by byte
# offset, so from the copy onwards we would be executing whatever happens to sit
# at our old offset inside the NEW file: a truncated run that silently skips the
# service restarts (or worse). Re-exec from a copy under /var/tmp first, which
# nothing in the bundle touches.
if [ "${HIFI_SYSUPD_PRIVATE:-}" != "1" ]; then
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
# replace the script's exit status, and the sequencer reads that status to
# decide whether this step succeeded.
trap '{ [ -n "${HIFI_SYSUPD_TMPDIR:-}" ] && rm -rf "$HIFI_SYSUPD_TMPDIR"; }; :' EXIT INT TERM

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
rm -rf "$WORKDIR"; mkdir -p "$NEWROOT"
if command -v hifi_curl_progress >/dev/null 2>&1; then
    hifi_curl_progress "$URL" "$TARBALL" 10 35 "Scaricamento componenti $VERSION…" \
        || fail "Download fallito da $URL"
else
    write_status downloading 10 "Scaricamento componenti $VERSION…"
    curl -fL --retry 3 -o "$TARBALL" "$URL" \
        || fail "Download fallito da $URL"
fi

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

# ── restart services ─────────────────────────────────────────────────
write_status restarting 90 "Riavvio servizi…"
systemctl daemon-reload || true
# Restart auxiliary services first; the API (our caller) last. This script
# runs under its own transient systemd unit, so restarting hifi-api here does
# not kill it.
for svc in hifi-vumeter hifi-sources squeezelite; do
    systemctl restart "$svc" 2>/dev/null || true
done
# Web-admin gateway: enable (first time it lands on an existing unit) + restart.
# Guarded so a bundle without the unit is a clean no-op.
if [ -f /etc/systemd/system/hifi-webui.service ]; then
    systemctl enable hifi-webui.service 2>/dev/null || true
    systemctl restart hifi-webui.service 2>/dev/null || true
fi
# Resume unit for interrupted OTA plans. Enabled here as well as from the OS
# payload (apply.d/0033) so a device that only ever receives system bundles
# still gets it; both are idempotent. Never *started* — it is a boot-time unit
# and its ConditionPathExists guard makes it a no-op without a pending plan.
if [ -f /etc/systemd/system/hifi-update-resume.service ]; then
    systemctl enable hifi-update-resume.service 2>/dev/null || true
fi

rm -rf "$WORKDIR"
write_status 'done' 100 "Componenti aggiornati a $VERSION"

# Restarting hifi-api kills any client that was polling us. That used to abort
# the multi-component update, because the client itself was driving the
# sequence and its next apply POST landed on a restarting API. The sequence is
# now driven by hifi-update-runner.sh under its own transient unit, which
# judges this step by our exit code — not by the status file above — so the
# restart is safe. Keep it last regardless.
systemctl restart hifi-api 2>/dev/null || true
