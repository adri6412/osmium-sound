#!/bin/sh
# HiFi Player appliance — server-side OTA stage sequencer.
#
# First half of the isolated update flow. Downloads and verifies every
# component in the plan — nothing is applied yet, the running system (hifi-api,
# hifi-webui, squeezelite, lightdm/Electron) stays fully live the whole time,
# exactly like the old single-phase hifi-update-runner.sh used to. Once every
# step has staged successfully, this creates /system-update and reboots: the
# next boot lands in system-update.target instead of the normal graphical
# session (see hifi-update-apply.service), where nothing from the app stack is
# running at all, and hifi-update-apply-runner.sh applies the three staged
# payloads in one isolated pass.
#
# Splitting stage from apply is what actually fixes the "update only applied
# some of the components" class of bug: applying used to happen on the live
# system, so a service restart mid-apply (hifi-api restarting after the system
# step, lightdm restarting after the ui step) or an OS-payload reboot could
# still interrupt an in-progress install. Staging never touches the running
# system at all — a failure here just leaves the device fully live and normal,
# same as a failed check does today.
#
# Runs each updater's `stage` subcommand SYNCHRONOUSLY and judges it by exit
# code plus a persisted STAGED marker (never by the /run status file, which is
# only ever a progress display), under its own transient systemd unit
# (hifi-update-stage) so restarting hifi-api/hifi-webui mid-plan cannot kill
# it. A step interrupted by an unrelated reboot is resolved on the next boot by
# hifi-update-stage-resume.service, exactly as hifi-update-resume.service used
# to for the old single-phase runner.
#
# Plan file (written by api_server.py, /var/lib/hifi-player/update/plan):
#
#     v 2
#     plan <plan_id> <channel> <created_epoch>
#     step <kind> <state> <attempts> <version> <url> <sha> <sig_url>
#     [finished <epoch> <overall>]
#
#   kind    system | os | ui        (staged in this order, though order does
#                                     not matter for staging — see below)
#   state   pending | running | done | error
#   sig_url '-' when the asset has no detached signature (UI/system bundles)
#
# `v 2` (was `v 1` for the old single-phase runner) is purely a schema-version
# fence — the fields themselves are unchanged — so a device mid-upgrade of
# this very feature can never have an old-format plan misread as a new one, or
# vice versa. Field values are whitespace-free by construction (URLs, hex
# digests, and the version charset api_server validates), so plain
# `awk`/`set --` parsing is safe.
#
# Usage (no arguments):
#     hifi-update-stage-runner.sh
set -eu

MAX_ATTEMPTS=2

# HIFI_UPDATE_TEST_ROOT is the single test hook (tests/test-update-stage-runner.sh):
# it relocates every path this script touches into a sandbox and skips the
# logging + private-copy setup. Deliberately all-or-nothing — individual paths
# are NOT overridable, so nothing can redirect just the OS updater on a real
# appliance. Unset in production, which is the only case the defaults describe.
if [ -n "${HIFI_UPDATE_TEST_ROOT:-}" ]; then
    _R=$HIFI_UPDATE_TEST_ROOT
    UPDATE_DIR="$_R/update"
    PLAN="$UPDATE_DIR/plan"
    STATE_FILE="$UPDATE_DIR/state"
    STAGE_ROOT="$UPDATE_DIR/staged"
    SYSTEM_UPDATE_LINK="$_R/system-update"
    SYS_SCRIPT="$_R/sbin/hifi-system-update.sh"
    OS_SCRIPT="$_R/sbin/hifi-os-update.sh"
    UI_SCRIPT="$_R/sbin/hifi-ota-update.sh"
    IMG_SCRIPT="$_R/sbin/hifi-image-update.sh"
    HIFI_RUNNER_PRIVATE=1
else
    UPDATE_DIR=/var/lib/hifi-player/update
    PLAN="$UPDATE_DIR/plan"
    STATE_FILE="$UPDATE_DIR/state"
    STAGE_ROOT="$UPDATE_DIR/staged"
    SYSTEM_UPDATE_LINK=/system-update
    SYS_SCRIPT=/usr/local/sbin/hifi-system-update.sh
    OS_SCRIPT=/usr/local/sbin/hifi-os-update.sh
    UI_SCRIPT=/usr/local/sbin/hifi-ota-update.sh
    IMG_SCRIPT=/usr/local/sbin/hifi-image-update.sh
    # The log helper is sourced defensively: under `set -e` a missing or
    # unreadable /usr/local/sbin/hifi-log.sh would abort this script before it
    # could record anything at all — exactly the silent failure mode this
    # whole change is about removing.
    if [ -r /usr/local/sbin/hifi-log.sh ]; then
        # shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-log.sh
        # shellcheck disable=SC1091  # absolute target, only present on the appliance
        . /usr/local/sbin/hifi-log.sh
        hifi_log_init hifi-update-stage-runner
    fi
fi

log() { printf '%s [hifi-update-stage-runner] %s\n' "$(date -Is 2>/dev/null || date)" "$*"; }

# ── run from a private copy ──────────────────────────────────────────
# The system bundle installs /usr/local/sbin/*.sh with `cp -af`, which rewrites
# each file IN PLACE. /bin/sh reads a script incrementally, by offset, so the
# system step's `apply` would corrupt this very script mid-execution — except
# apply never runs here (this script only ever calls `stage`). Kept anyway:
# nothing about that guarantee is worth relying on across a future change, and
# the cost of the private copy is negligible.
if [ "${HIFI_RUNNER_PRIVATE:-}" != "1" ]; then
    _self=$(readlink -f "$0" 2>/dev/null || echo "$0")
    _dir=$(mktemp -d /var/tmp/hifi-update-stage-runner.XXXXXX) || {
        log "mktemp failed; running in place"
        _dir=""
    }
    if [ -n "$_dir" ] && cp -f "$_self" "$_dir/runner.sh"; then
        chmod +x "$_dir/runner.sh"
        HIFI_RUNNER_PRIVATE=1
        HIFI_RUNNER_TMPDIR="$_dir"
        export HIFI_RUNNER_PRIVATE HIFI_RUNNER_TMPDIR
        exec /bin/sh "$_dir/runner.sh" "$@"
    fi
    [ -n "$_dir" ] && rm -rf "$_dir"
fi
# Must end on a success: an EXIT trap whose last command fails can replace this
# script's exit status, and our exit status is how the caller (and the tests)
# tell a completed plan from a broken one.
# shellcheck disable=SC2317,SC2329  # invoked indirectly, by the trap below
cleanup() {
    [ -n "${HIFI_RUNNER_TMPDIR:-}" ] && rm -rf "$HIFI_RUNNER_TMPDIR"
    return 0
}
trap cleanup EXIT INT TERM

[ -f "$PLAN" ] || { log "no plan at $PLAN — nothing to do"; exit 0; }

# Was this plan already fully finished before this invocation? Needed below to
# fire the end-of-plan reboot exactly once — the resume unit runs on EVERY
# boot, so if we rebooted whenever `next_step` finds nothing left to do, a
# completed-but-not-yet-consumed plan would reboot the box again on its very
# next unrelated boot, and again after that: an infinite reboot loop. Only the
# run that ADDS the `finished` line (real work just landed) should reboot; a
# run that finds it already there is the no-op case and must stay quiet.
already_finished=0
grep -q '^finished ' "$PLAN" 2>/dev/null && already_finished=1

# ── plan helpers ─────────────────────────────────────────────────────
# Rewrite the plan atomically: temp sibling + mv, so a power cut can never
# leave a half-written plan (the file is the only record of what is pending).
plan_write() {  # reads the new content on stdin
    _tmp=$(mktemp "${PLAN}.XXXXXX") || return 1
    cat > "$_tmp"
    chmod 644 "$_tmp"
    mv -f "$_tmp" "$PLAN"
}

plan_set() {  # <kind> <state> <attempts>
    awk -v k="$1" -v s="$2" -v a="$3" \
        '$1=="step" && $2==k { $3=s; $4=a } { print }' "$PLAN" | plan_write
}

plan_finish() {  # <overall: finished|error>
    { grep -v '^finished ' "$PLAN" || true; printf 'finished %s %s\n' "$(date +%s)" "$1"; } \
        | plan_write
}

# First step still needing work, as "<kind> <state> <attempts> <version> <url> <sha> <sig>".
next_step() {
    awk '$1=="step" && ($3=="pending" || $3=="running") {
             print $2, $3, $4, $5, $6, $7, $8; exit }' "$PLAN"
}

staged_version() {  # <kind> <version>
    _sv_file="$STAGE_ROOT/$1/$2/STAGED"
    if [ -r "$_sv_file" ]; then
        head -n 1 "$_sv_file" | tr -d ' \t\r\n'
    else
        echo unknown
    fi
}

run_step() {  # <kind> <version> <url> <sha> <sig>
    case "$1" in
        system) "$SYS_SCRIPT" stage "$3" "$4" "$2" ;;
        os)     "$OS_SCRIPT"  stage "$3" "$4" "$5" "$2" ;;
        ui)     "$UI_SCRIPT"  stage "$3" "$4" "$2" ;;
        image)  "$IMG_SCRIPT" stage "$3" "$2" ;;
        *)      return 64 ;;
    esac
}

# ── walk the plan ────────────────────────────────────────────────────
overall=finished
while :; do
    line=$(next_step)
    [ -n "$line" ] || break
    # shellcheck disable=SC2086  # fields are whitespace-free by construction
    set -- $line
    kind=$1; state=$2; attempts=$3; version=$4; url=$5; sha=$6; sig=$7

    if [ "$state" = running ]; then
        # We were interrupted (power cut, or a manual reboot mid-download).
        # Each updater writes its STAGED marker only after full verification,
        # so a marker matching the target version means this step really did
        # land before the interruption.
        if [ "$(staged_version "$kind" "$version")" = "$version" ]; then
            log "step $kind was interrupted but $version is already staged — treating as done"
            plan_set "$kind" 'done' "$attempts"
            continue
        fi
        if [ "$attempts" -ge "$MAX_ATTEMPTS" ]; then
            log "step $kind interrupted $attempts time(s) without staging $version — giving up"
            plan_set "$kind" error "$attempts"
            overall=error
            break
        fi
        log "step $kind was interrupted before $version staged — retrying"
    fi

    attempts=$((attempts + 1))
    plan_set "$kind" running "$attempts"
    log "step $kind → $version (attempt $attempts)"

    rc=0
    run_step "$kind" "$version" "$url" "$sha" "$sig" || rc=$?

    if [ "$rc" -ne 0 ]; then
        log "step $kind failed to stage (rc=$rc)"
        plan_set "$kind" error "$attempts"
        overall=error
        break
    fi

    # Belt and braces: a zero exit is not proof the payload actually landed.
    got=$(staged_version "$kind" "$version")
    if [ "$got" != "$version" ]; then
        log "step $kind reported success but staged marker is '$got', expected '$version'"
        plan_set "$kind" error "$attempts"
        overall=error
        break
    fi

    log "step $kind staged ($version)"
    plan_set "$kind" 'done' "$attempts"
done

plan_finish "$overall"
log "stage plan $overall"

# Once every component has staged, enter update mode: create /system-update
# (systemd-system-update-generator(8) redirects default.target to
# system-update.target for the NEXT boot only when this exists — see
# hifi-update-apply.service) and reboot. Guarded by already_finished for the
# same reason the old runner guarded its own end-of-plan reboot: this must
# fire exactly once per completed plan, never on a later, unrelated boot that
# happens to find an already-finished plan still on disk.
if [ "$overall" = finished ] && [ "$already_finished" -eq 0 ]; then
    if [ -n "${HIFI_UPDATE_TEST_ROOT:-}" ]; then
        # Test hook: record the intent instead of touching the real machine.
        : > "${PLAN}.would-reboot"
    else
        # Con uno step `image` (schema A/B) RAUC ha già scritto lo slot inattivo e
        # lo ha reso primario: si riavvia e il selettore GRUB fa partire il nuovo
        # sistema. Niente /system-update: la sessione isolata di apply servirebbe
        # solo ai componenti legacy, che il nuovo slot rende comunque superati.
        if awk '$1=="step" && $2=="image" { f=1 } END { exit !f }' "$PLAN"; then
            log "image staged — rebooting into the new slot (no update-mode session)"
            mkdir -p "$UPDATE_DIR"
            _tmp=$(mktemp "${STATE_FILE}.XXXXXX") || _tmp=""
            if [ -n "$_tmp" ]; then
                { echo 'phase=staged'; echo "ts=$(date +%s)"; echo 'message=System image installed, restarting into the new system'; echo 'key=update.image.rebooting'; } > "$_tmp"
                chmod 644 "$_tmp"; mv -f "$_tmp" "$STATE_FILE"
            fi
            sync
            systemctl reboot || log "systemctl reboot failed"
            exit 0
        fi
        log "all components staged — entering update mode"
        mkdir -p "$UPDATE_DIR"
        _tmp=$(mktemp "${STATE_FILE}.XXXXXX") || _tmp=""
        if [ -n "$_tmp" ]; then
            {
                echo 'phase=staged'
                echo "ts=$(date +%s)"
                echo 'message=Update verified, restarting to apply it'
                echo 'key=update.stagedRebooting'
            } > "$_tmp"
            chmod 644 "$_tmp"
            mv -f "$_tmp" "$STATE_FILE"
        else
            log "could not write $STATE_FILE (mktemp failed)"
        fi
        if ! ln -sfn "$UPDATE_DIR" "$SYSTEM_UPDATE_LINK" 2>/dev/null; then
            log "could not create $SYSTEM_UPDATE_LINK — update-mode boot will NOT trigger"
        fi
        sync
        # hifi-quiesce-audio-shutdown.service (Before=/Conflicts=shutdown.target,
        # unconditional for every halt/reboot however triggered) already stops
        # any active DMA audio path first, so no extra mitigation is needed here.
        systemctl reboot || log "systemctl reboot failed"
    fi
fi

[ "$overall" = finished ] || exit 1
exit 0
