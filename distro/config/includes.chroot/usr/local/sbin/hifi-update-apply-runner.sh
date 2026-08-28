#!/bin/sh
# HiFi Player appliance — isolated OTA apply runner.
#
# Second half of the isolated update flow, and the actual fix for "the update
# only applied some of the components": this script only ever runs under
# hifi-update-apply.service, which systemd only ever schedules while the box
# has booted into system-update.target instead of the normal graphical
# session (systemd-system-update-generator(8) makes that swap for exactly one
# boot whenever /system-update exists — see hifi-update-stage-runner.sh, which
# creates it once every component has staged). Under system-update.target
# nothing from the app stack is even scheduled to start: not hifi-api, not
# hifi-webui, not hifi-sources, not hifi-vumeter, not squeezelite, not
# lightdm/Electron. There is nothing left to restart mid-apply and nothing
# left to race — every payload gets applied to a completely quiescent system.
#
# Reads the SAME plan hifi-update-stage-runner.sh wrote
# (/var/lib/hifi-player/update/plan) and applies each already-staged,
# already-verified payload (system → os → ui) by calling that channel's own
# `apply` subcommand against its staged directory — no network access is
# required for this (staging already did all the downloading and verifying).
#
# A crash mid-apply (power loss, kernel panic) recovers for free: on the next
# boot /system-update still exists, the generator routes back into
# system-update.target, and this script reruns from the top. Every apply step
# is safe to repeat (OS migrations are idempotent by contract, the system step
# just re-copies the same files, and the UI step's version file is checked
# before its already-consumed staged payload would ever be touched again), so
# no separate resume unit is needed for this half — unlike the interrupted-
# download case the stage phase still needs hifi-update-stage-resume.service
# for.
#
# Usage (no arguments):
#     hifi-update-apply-runner.sh
set -eu

MAX_ATTEMPTS=2

# HIFI_APPLY_TEST_ROOT is the test hook (tests/test-update-apply-runner.sh): it
# relocates every path this script touches into a sandbox, including the
# things a real appliance can't safely fake in a test (systemctl, plymouth,
# /system-update itself). Unset in production.
if [ -n "${HIFI_APPLY_TEST_ROOT:-}" ]; then
    _R=$HIFI_APPLY_TEST_ROOT
    UPDATE_DIR="$_R/update"
    PLAN="$UPDATE_DIR/plan"
    STATE_FILE="$UPDATE_DIR/state"
    ERROR_FILE="$UPDATE_DIR/error.json"
    STAGE_ROOT="$UPDATE_DIR/staged"
    SYSTEM_UPDATE_LINK="$_R/system-update"
    SYS_SCRIPT="$_R/sbin/hifi-system-update.sh"
    OS_SCRIPT="$_R/sbin/hifi-os-update.sh"
    UI_SCRIPT="$_R/sbin/hifi-ota-update.sh"
    SYS_VERSION_FILE="$_R/SYSTEM_VERSION"
    OS_VERSION_FILE="$_R/OS_VERSION"
    UI_VERSION_FILE="$_R/UI_VERSION"
    UI_VERSION_FILE_LEGACY="$_R/UI_VERSION"
    SYSTEMCTL="$_R/bin/systemctl-stub"
    PLYMOUTH="$_R/bin/plymouth-stub"
else
    UPDATE_DIR=/var/lib/hifi-player/update
    PLAN="$UPDATE_DIR/plan"
    STATE_FILE="$UPDATE_DIR/state"
    ERROR_FILE="$UPDATE_DIR/error.json"
    STAGE_ROOT="$UPDATE_DIR/staged"
    SYSTEM_UPDATE_LINK=/system-update
    SYS_SCRIPT=/usr/local/sbin/hifi-system-update.sh
    OS_SCRIPT=/usr/local/sbin/hifi-os-update.sh
    UI_SCRIPT=/usr/local/sbin/hifi-ota-update.sh
    SYS_VERSION_FILE=/etc/hifi-player/SYSTEM_VERSION
    OS_VERSION_FILE=/etc/hifi-player/OS_VERSION
    # Da 2.5.24 la versione dell'interfaccia sta fuori dalle due cartelle
    # (Qt ed Electron), cosi' vale per entrambe; il posto vecchio resta letto
    # per gli apparecchi aggiornati prima del passaggio.
    UI_VERSION_FILE=/etc/hifi-player/UI_VERSION
    UI_VERSION_FILE_LEGACY=/opt/hifi-media-player/UI_VERSION
    SYSTEMCTL=systemctl
    PLYMOUTH=plymouth
    if [ -r /usr/local/sbin/hifi-log.sh ]; then
        # shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-log.sh
        # shellcheck disable=SC1091  # absolute target, only present on the appliance
        . /usr/local/sbin/hifi-log.sh
        hifi_log_init hifi-update-apply-runner
    fi
fi

log() { printf '%s [hifi-update-apply-runner] %s\n' "$(date -Is 2>/dev/null || date)" "$*"; }

# ── splash progress (best-effort; never fatal) ─────────────────────────
splash_progress() {  # <0-100>
    if command -v "$PLYMOUTH" >/dev/null 2>&1; then
        "$PLYMOUTH" system-update --progress="$1" 2>/dev/null || true
    fi
}
splash_error() {
    # hifi.script special-cases this exact sentinel: freezes the logo pulse and
    # turns the progress bar red. Everything else stays silenced, same as
    # every other boot message this theme swallows on purpose.
    if command -v "$PLYMOUTH" >/dev/null 2>&1; then
        "$PLYMOUTH" display-message --text=HIFI_UPDATE_ERROR 2>/dev/null || true
    fi
}

# ── state helpers ────────────────────────────────────────────────────
write_state() {  # <phase> <message>
    mkdir -p "$UPDATE_DIR"
    _tmp=$(mktemp "${STATE_FILE}.XXXXXX") || { log "mktemp failed for $STATE_FILE"; return 0; }
    {
        printf 'phase=%s\n' "$1"
        printf 'ts=%s\n' "$(date +%s)"
        printf 'message=%s\n' "$2"
    } > "$_tmp"
    chmod 644 "$_tmp"
    mv -f "$_tmp" "$STATE_FILE"
}

write_error() {  # <kind> <message>
    mkdir -p "$UPDATE_DIR"
    esc=$(printf '%s' "$2" | sed 's/\\/\\\\/g; s/"/\\"/g')
    _tmp=$(mktemp "${ERROR_FILE}.XXXXXX") || { log "mktemp failed for $ERROR_FILE"; return 0; }
    printf '{"channel":"%s","message":"%s"}\n' "$1" "$esc" > "$_tmp"
    chmod 644 "$_tmp"
    mv -f "$_tmp" "$ERROR_FILE"
}

fail_step() {  # <kind> <message>
    log "step $1 failed: $2"
    write_state error "$2"
    write_error "$1" "$2"
    splash_error
    exit 1
}

[ -f "$PLAN" ] || fail_step '' "Nessun piano di aggiornamento trovato in modalità update — stato inatteso"

write_state applying "Applicazione aggiornamento in corso…"
splash_progress 0

# If the owner had already enabled SSH from Settings, keep it available while
# parked here too — same reachability they already opted into, no surprise,
# and it's the only way to intervene remotely if a step below fails. Left off
# if it was never enabled. NetworkManager/network-online.target are already
# required by hifi-update-apply.service before this script starts.
if "$SYSTEMCTL" is-enabled ssh.service >/dev/null 2>&1; then
    "$SYSTEMCTL" start ssh.service >/dev/null 2>&1 || true
fi

# ── plan helpers ─────────────────────────────────────────────────────
step_info() {  # <kind> -> "<state> <version>" (empty if absent from the plan)
    awk -v k="$1" '$1=="step" && $2==k { print $3, $5; exit }' "$PLAN"
}

installed_version() {  # <kind>
    case "$1" in
        system) _f=$SYS_VERSION_FILE ;;
        os)     _f=$OS_VERSION_FILE ;;
        ui)     _f=$UI_VERSION_FILE ;;
        *)      echo unknown; return ;;
    esac
    [ -r "$_f" ] || [ "$1" != ui ] || _f=$UI_VERSION_FILE_LEGACY
    if [ -r "$_f" ]; then
        head -n 1 "$_f" | tr -d ' \t\r\n'
    else
        echo unknown
    fi
}

run_apply() {  # <kind> <staged_dir> <version>
    case "$1" in
        system) "$SYS_SCRIPT" apply "$2" "$3" ;;
        os)     "$OS_SCRIPT"  apply "$2" "$3" ;;
        ui)     "$UI_SCRIPT"  apply "$2" "$3" ;;
        *)      return 64 ;;
    esac
}

# ── apply every staged component, fixed order ──────────────────────────
# system first (brings the API/daemons/units up to date before anything else
# runs on the next normal boot), os second, ui last — same rationale as the
# stage plan's canonical order (UPDATE_PLAN_ORDER in api_server.py).
total=0
for kind in system os ui; do
    info=$(step_info "$kind")
    [ -n "$info" ] || continue
    total=$((total + 1))
done
[ "$total" -gt 0 ] || fail_step '' "Il piano di aggiornamento non contiene componenti — stato inatteso"

done_count=0
for kind in system os ui; do
    info=$(step_info "$kind")
    [ -n "$info" ] || continue
    # shellcheck disable=SC2086  # fields are whitespace-free by construction
    set -- $info
    state=$1; version=$2

    if [ "$state" != "done" ]; then
        # The stage runner only creates /system-update once EVERY step in the
        # plan reached 'done' — a step in any other state here means the
        # on-disk plan was tampered with or corrupted between boots. Refuse
        # rather than guess.
        fail_step "$kind" "Passo '$kind' non risulta completato in fase di staging (stato: $state)"
    fi

    if [ "$(installed_version "$kind")" = "$version" ]; then
        log "step $kind already applied ($version) — skipping"
        done_count=$((done_count + 1))
        splash_progress $(( done_count * 100 / total ))
        continue
    fi

    staged_dir="$STAGE_ROOT/$kind/$version"
    [ -d "$staged_dir" ] || fail_step "$kind" "Pacchetto staged mancante per $kind $version"

    attempt=0
    rc=0
    while :; do
        attempt=$((attempt + 1))
        log "step $kind → $version (attempt $attempt)"
        rc=0
        run_apply "$kind" "$staged_dir" "$version" || rc=$?
        [ "$rc" -eq 0 ] && [ "$(installed_version "$kind")" = "$version" ] && break
        if [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then
            fail_step "$kind" "Applicazione di $kind $version fallita dopo $attempt tentativi (rc=$rc)"
        fi
        log "step $kind attempt $attempt did not land $version (rc=$rc) — retrying"
    done

    log "step $kind applied ($version)"
    done_count=$((done_count + 1))
    splash_progress $(( done_count * 100 / total ))
done

# ── every component landed — clear the flag and go back to normal ──────
log "update-mode session complete — returning to normal boot"
rm -rf "$STAGE_ROOT"
rm -f "$PLAN"
write_state 'done' "Aggiornamento completato"
splash_progress 100

if ! rm -f "$SYSTEM_UPDATE_LINK"; then
    log "could not remove $SYSTEM_UPDATE_LINK — next boot would re-enter update mode"
    write_state error "Impossibile disattivare la modalità update ($SYSTEM_UPDATE_LINK)"
    write_error '' "Impossibile rimuovere $SYSTEM_UPDATE_LINK dopo un aggiornamento riuscito"
    splash_error
    exit 1
fi

sync
# hifi-quiesce-audio-shutdown.service already stops any active DMA audio path
# before any halt/reboot however triggered — no extra mitigation needed here
# (nothing plays audio under system-update.target anyway).
"$SYSTEMCTL" reboot || log "systemctl reboot failed"
exit 0
