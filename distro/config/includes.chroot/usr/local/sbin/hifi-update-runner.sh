#!/bin/sh
# HiFi Player appliance — server-side OTA sequencer.
#
# Historically the "update everything" flow lived in the clients (kiosk,
# web-admin, companion): each one POSTed /system_update/apply, polled the
# status file, then POSTed the next one. That is fragile in four ways, and all
# four produced the same symptom — a run that stops half-way, leaving one
# component behind:
#
#   1. an OS payload that reboots never writes `done` (the status files live in
#      /run, a tmpfs), so the client waited forever and never started the
#      remaining steps — and the client itself was gone anyway;
#   2. hifi-system-update.sh restarts hifi-api right after writing `done`, so
#      the client's very next POST hit a restarting API and the chain aborted;
#   3. the /run status file still held the *previous* run's `done` between the
#      apply POST and the updater's first write, so a step could be declared
#      complete instantly and the next one started concurrently;
#   4. nothing serialised the updaters, so two could run at once.
#
# So the plan now lives on disk, on persistent storage, and this script walks
# it to the end:
#
#   - it runs each updater SYNCHRONOUSLY and judges it by exit code plus the
#     installed version file — never by the /run status file, which is only
#     ever a progress display;
#   - it runs under its own transient systemd unit (hifi-update-runner), so
#     restarting hifi-api / hifi-webui / lightdm mid-plan cannot kill it;
#   - a step interrupted by a reboot is resolved on the next boot by
#     hifi-update-resume.service: if the target version is already installed
#     the step succeeded, otherwise it is retried (every updater is idempotent).
#
# Plan file (written by api_server.py, /var/lib/hifi-player/update-plan):
#
#     v 1
#     plan <plan_id> <channel> <created_epoch>
#     step <kind> <state> <attempts> <version> <url> <sha> <sig_url>
#     [finished <epoch> <overall>]
#
#   kind    system | os | ui        (executed in this order — see below)
#   state   pending | running | done | error
#   sig_url '-' when the asset has no detached signature (UI/system bundles)
#
# Field values are whitespace-free by construction (URLs, hex digests, and the
# version charset api_server validates), so plain `awk`/`set --` parsing is safe.
#
# Step order is system → os → ui and is fixed by api_server:
#   system first  — it brings the API, daemons, helper scripts (including this
#                   one) and unit files up to date before anything else runs;
#   os second     — it may reboot, and the resume unit picks the plan back up;
#   ui last       — it restarts lightdm, which tears down the kiosk.
#
# Once every step has landed, the box reboots unconditionally (exactly once —
# guarded by whether this run is the one that first wrote the `finished` line,
# see `already_finished` below), so the fleet never runs on a half-reloaded
# process tree after an update.
#
# Usage (no arguments):
#     hifi-update-runner.sh
set -eu

MAX_ATTEMPTS=2

# HIFI_UPDATE_TEST_ROOT is the single test hook (tests/test-update-runner.sh):
# it relocates every path this script touches into a sandbox and skips the
# logging + private-copy setup. Deliberately all-or-nothing — individual paths
# are NOT overridable, so nothing can redirect just the OS updater on a real
# appliance. Unset in production, which is the only case the defaults describe.
if [ -n "${HIFI_UPDATE_TEST_ROOT:-}" ]; then
    _R=$HIFI_UPDATE_TEST_ROOT
    PLAN="$_R/update-plan"
    SYS_SCRIPT="$_R/sbin/hifi-system-update.sh"
    OS_SCRIPT="$_R/sbin/hifi-os-update.sh"
    UI_SCRIPT="$_R/sbin/hifi-ota-update.sh"
    SYS_VERSION_FILE="$_R/SYSTEM_VERSION"
    OS_VERSION_FILE="$_R/OS_VERSION"
    UI_VERSION_FILE="$_R/UI_VERSION"
    HIFI_RUNNER_PRIVATE=1
else
    PLAN=/var/lib/hifi-player/update-plan
    SYS_SCRIPT=/usr/local/sbin/hifi-system-update.sh
    OS_SCRIPT=/usr/local/sbin/hifi-os-update.sh
    UI_SCRIPT=/usr/local/sbin/hifi-ota-update.sh
    SYS_VERSION_FILE=/etc/hifi-player/SYSTEM_VERSION
    OS_VERSION_FILE=/etc/hifi-player/OS_VERSION
    UI_VERSION_FILE=/opt/hifi-media-player/UI_VERSION
    # The log helper is sourced defensively: under `set -e` a missing or
    # unreadable /usr/local/sbin/hifi-log.sh would abort this script before it
    # could record anything at all — exactly the silent failure mode this whole
    # change is about removing.
    if [ -r /usr/local/sbin/hifi-log.sh ]; then
        # shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-log.sh
        # shellcheck disable=SC1091  # absolute target, only present on the appliance
        . /usr/local/sbin/hifi-log.sh
        hifi_log_init hifi-update-runner
    fi
fi

log() { printf '%s [hifi-update-runner] %s\n' "$(date -Is 2>/dev/null || date)" "$*"; }

# ── run from a private copy ──────────────────────────────────────────
# The system bundle installs /usr/local/sbin/*.sh with `cp -af`, which rewrites
# each file IN PLACE. /bin/sh reads a script incrementally, by offset, so the
# system step would corrupt this very script (and hifi-system-update.sh itself)
# mid-execution: the shell resumes at its old offset inside brand-new content.
# Re-exec from a copy under /var/tmp, which no updater touches.
if [ "${HIFI_RUNNER_PRIVATE:-}" != "1" ]; then
    _self=$(readlink -f "$0" 2>/dev/null || echo "$0")
    _dir=$(mktemp -d /var/tmp/hifi-update-runner.XXXXXX) || {
        log "mktemp failed; running in place (a system update may interrupt this run)"
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
# completed-but-not-yet-dismissed plan would reboot the box again on its very
# next unrelated boot, and again after that: an infinite reboot loop. Only the
# run that ADDS the `finished` line (real work just landed) should reboot;
# a run that finds it already there is the no-op case and must stay quiet.
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

installed_version() {  # <kind>
    case "$1" in
        system) _f=$SYS_VERSION_FILE ;;
        os)     _f=$OS_VERSION_FILE ;;
        ui)     _f=$UI_VERSION_FILE ;;
        *)      echo unknown; return ;;
    esac
    if [ -r "$_f" ]; then
        # first line, whitespace trimmed
        head -n 1 "$_f" | tr -d ' \t\r\n'
    else
        echo unknown
    fi
}

run_step() {  # <kind> <version> <url> <sha> <sig>
    case "$1" in
        system) "$SYS_SCRIPT" "$3" "$4" "$2" ;;
        os)     "$OS_SCRIPT"  "$3" "$4" "$5" "$2" ;;
        ui)     "$UI_SCRIPT"  "$3" "$4" "$2" ;;
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
        # We were interrupted — almost always the reboot an OS payload asked
        # for. The updaters record their version file before handing control
        # over (hifi-os-update.sh writes OS_VERSION *before* `systemctl
        # reboot`), so an installed version that already matches the target
        # means the step really did complete.
        if [ "$(installed_version "$kind")" = "$version" ]; then
            log "step $kind was interrupted but $version is installed — treating as done"
            plan_set "$kind" 'done' "$attempts"
            continue
        fi
        if [ "$attempts" -ge "$MAX_ATTEMPTS" ]; then
            log "step $kind interrupted $attempts time(s) without landing $version — giving up"
            plan_set "$kind" error "$attempts"
            overall=error
            break
        fi
        log "step $kind was interrupted before $version landed — retrying"
    fi

    attempts=$((attempts + 1))
    plan_set "$kind" running "$attempts"
    log "step $kind → $version (attempt $attempts)"

    rc=0
    run_step "$kind" "$version" "$url" "$sha" "$sig" || rc=$?

    if [ "$rc" -ne 0 ]; then
        log "step $kind failed (rc=$rc)"
        plan_set "$kind" error "$attempts"
        overall=error
        break
    fi

    # Belt and braces: a zero exit is not proof the new files are in place.
    got=$(installed_version "$kind")
    if [ "$got" != "$version" ]; then
        log "step $kind reported success but installed version is '$got', expected '$version'"
        plan_set "$kind" error "$attempts"
        overall=error
        break
    fi

    log "step $kind done ($version)"
    plan_set "$kind" 'done' "$attempts"
done

plan_finish "$overall"
log "plan $overall"

# Mandatory reboot once every step in the plan has actually landed (not on a
# no-op re-run of an already-finished plan — see already_finished above).
# Previously only the OS step could reboot, and only when one of its own
# migrations asked for it — so a System+UI-only update (or an OS update whose
# payload didn't need a reboot) could leave stale code loaded in memory
# (hifi-api, lightdm/Electron, etc.) until the box was next power-cycled by
# hand. A guaranteed reboot at the end removes that class of "the update
# applied but didn't fully take" reports.
if [ "$overall" = finished ] && [ "$already_finished" -eq 0 ]; then
    if [ -n "${HIFI_UPDATE_TEST_ROOT:-}" ]; then
        # Test hook: record the intent instead of touching the real machine.
        : > "${PLAN}.would-reboot"
    else
        log "plan complete — rebooting"
        # hifi-quiesce-audio-shutdown.service (Before=/Conflicts=shutdown.target,
        # unconditional for every halt/reboot however triggered) already stops
        # any active DMA audio path first, so no extra mitigation is needed here.
        systemctl reboot || log "systemctl reboot failed"
    fi
fi

[ "$overall" = finished ] || exit 1
exit 0
