#!/bin/sh
# HiFi Player — OS update payload (RUNNER).
#
# This script is the entrypoint of an OS OTA: it is packaged into
# hifi-os-<ver>.tar.gz, signed, and executed AS ROOT on the appliance by
# /usr/local/sbin/hifi-os-update.sh after the signature + checksum verify.
#
# It is now a thin runner: it sources lib.sh (shared helpers) and executes, in
# order, every migration in apply.d/NNNN-*.sh, each in an isolated subshell so a
# failure is attributed to one migration and can't leave the runner in a dirty
# state. The actual OS changes live in apply.d/ — see those files.
#
# ── The OS-channel contract (unchanged — still enforced here) ─────────
#   • CUMULATIVE: the updater only ever fetches and runs the LATEST release's
#     payload (check_os_update → releases/latest); there is NO sequential replay
#     of intermediate versions. A device that jumps from an old version straight
#     to the newest runs ONLY this payload, so apply.d/ must contain EVERY OS
#     change ever shipped. To add a change, ADD a new apply.d/NNNN-*.sh file;
#     never delete or rewrite an existing migration.
#   • IDEMPOTENT: every migration must be a clean no-op when already applied.
#     The lib helpers (ensure_file_content, backup_and_edit, ensure_pkg) make
#     this the default — they only act, and only call mark_changed, on a real
#     diff.
#   • NO SPURIOUS REBOOT: the payload version is the release tag, so this runs on
#     EVERY release. A migration must call request_reboot ONLY after a real
#     change that needs a reboot — otherwise every update would reboot the box.
#     The idempotency CI test (build-ui-ota.yml) asserts a second run reports
#     changed=0 and requests no reboot.
#
# Environment provided by the updater (hifi-os-update.sh):
#   HIFI_OS_VERSION   the version string being applied (e.g. v1.4.0)
#   HIFI_PAYLOAD_DIR  absolute path to this extracted bundle (migrations read
#                     shipped files from "$HIFI_PAYLOAD_DIR/files/…")
set -eu

SELF_DIR=$(unset CDPATH; cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=/dev/null
. "$SELF_DIR/lib.sh"

: "${HIFI_OS_VERSION:=unknown}"
: "${HIFI_PAYLOAD_DIR:=$SELF_DIR}"

hifi_os_init
log_info "Applying HiFi OS update $HIFI_OS_VERSION"

changed=0
for mig in "$SELF_DIR"/apply.d/[0-9]*.sh; do
    [ -f "$mig" ] || continue          # no-match glob stays literal → skip
    MIGRATION_ID=$(basename "$mig" .sh)

    # Run the migration in an isolated subshell. It MUST be a standalone
    # statement (not the condition of `if`/`&&`/`||`) or POSIX `set -e` would be
    # suppressed inside it and a mid-migration failure wouldn't abort. We disable
    # the runner's own -e around it so we can capture the status and attribute the
    # failure ourselves.
    set +e
    # shellcheck source=/dev/null
    ( set -eu; . "$mig" )
    rc=$?
    set -e

    if [ "$rc" -eq 0 ]; then
        if [ -f "$HIFI_STATE_DIR/changed.$MIGRATION_ID" ]; then
            changed=$((changed + 1))
            ledger_record "$MIGRATION_ID" changed
        else
            ledger_record "$MIGRATION_ID" ok
        fi
    else
        ledger_record "$MIGRATION_ID" "failed(rc=$rc)"
        log_warn "migration $MIGRATION_ID FAILED (rc=$rc) — stopping"
        # Fail-fast: let hifi-os-update.sh surface the error and NOT record a new
        # OS_VERSION, so the device retries this same payload next time.
        reboot=no; [ -f "$HIFI_PAYLOAD_DIR/REBOOT" ] && reboot=yes
        echo "SUMMARY: changed=$changed failed=1 reboot=$reboot"
        exit "$rc"
    fi
    MIGRATION_ID=""
done

reboot=no; [ -f "$HIFI_PAYLOAD_DIR/REBOOT" ] && reboot=yes
echo "SUMMARY: changed=$changed failed=0 reboot=$reboot"
log_info "OS update $HIFI_OS_VERSION applied (changed=$changed, reboot=$reboot)."
