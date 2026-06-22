# shellcheck shell=sh
# HiFi Player — OS-update helper library.
#
# Sourced by apply.sh (the runner) and available to every migration in apply.d/.
# Pure POSIX sh (dash) — no bashisms, no `local`. Helpers encapsulate the diff /
# idempotency / reboot / safe-edit logic that used to be hand-rolled in every
# block of the old monolithic apply.sh, so each migration stays small and the
# three OS-channel invariants (cumulative, idempotent, no spurious reboot) are
# enforced by the library instead of by author discipline.
#
# Conventions:
#   • All human-readable logging goes to STDERR (log_info/log_change/log_warn),
#     so STDOUT stays clean for the runner's machine-readable SUMMARY line.
#   • A migration signals "I changed something" by calling mark_changed (or via a
#     helper that calls it); the runner reads that to build the audit ledger and
#     the SUMMARY. Reboot is requested explicitly with request_reboot, and ONLY
#     when a real change was made (the payload re-runs on every release).

# Set by the runner before each migration; default empty so log_* is safe under
# `set -u` even when called from the runner itself.
MIGRATION_ID="${MIGRATION_ID:-}"

# Persisted audit ledger. Lives under /var/lib (NOT /opt — a UI OTA wipes /opt)
# so the record of what each OS update did survives on this headless appliance.
HIFI_LEDGER="${HIFI_LEDGER:-/var/lib/hifi-player/os-migrations}"

# ── logging (stderr) ─────────────────────────────────────────────────
log_info()   { printf 'I: [hifi-os%s] %s\n' "${MIGRATION_ID:+/$MIGRATION_ID}" "$*" >&2; }
log_change() { printf 'C: [hifi-os%s] %s\n' "${MIGRATION_ID:+/$MIGRATION_ID}" "$*" >&2; }
log_warn()   { printf 'W: [hifi-os%s] %s\n' "${MIGRATION_ID:+/$MIGRATION_ID}" "$*" >&2; }

# ── run-state setup ──────────────────────────────────────────────────
# Creates a private, per-run scratch dir under the (temp, signed-and-extracted)
# payload dir where helpers drop one flag file per migration that changed
# something. The runner inspects these after each migration subshell.
hifi_os_init() {
    HIFI_STATE_DIR="${HIFI_PAYLOAD_DIR:-.}/.hifi-state"
    rm -rf "$HIFI_STATE_DIR"
    mkdir -p "$HIFI_STATE_DIR"
    mkdir -p "$(dirname "$HIFI_LEDGER")" 2>/dev/null || true
}

# ── change / reboot signalling ───────────────────────────────────────
# Record that the current migration changed system state. Cross-subshell safe:
# writes a flag file the parent runner can stat.
mark_changed() {
    [ -n "$MIGRATION_ID" ] && : > "$HIFI_STATE_DIR/changed.$MIGRATION_ID"
    log_change "$1"
}

# Did the current migration change anything (this run)?
migration_changed() {
    [ -n "$MIGRATION_ID" ] && [ -f "$HIFI_STATE_DIR/changed.$MIGRATION_ID" ]
}

# Ask the updater (hifi-os-update.sh) to reboot once apply.sh succeeds. Call this
# ONLY after a real change that needs a reboot to take effect — the payload runs
# on every release, so an unconditional reboot would reboot the box every update.
request_reboot() {
    : > "${HIFI_PAYLOAD_DIR:?}/REBOOT"
    log_info "reboot requested"
}

# ── idempotent file writer ───────────────────────────────────────────
# usage: ensure_file_content <path> [mode] [owner:group]   (desired bytes on stdin)
# Writes <path> only if its content differs from stdin; on a write it calls
# mark_changed. Always returns 0 (safe under `set -e`); use migration_changed (or
# check before/after) if you need to react to a change.
ensure_file_content() {
    _ec_path="$1"; _ec_mode="${2:-}"; _ec_owner="${3:-}"
    _ec_tmp="$(mktemp "${_ec_path}.hifi.XXXXXX")" || {
        log_warn "mktemp failed for $_ec_path"; return 0
    }
    cat > "$_ec_tmp"
    if [ -f "$_ec_path" ] && cmp -s "$_ec_tmp" "$_ec_path"; then
        rm -f "$_ec_tmp"
        return 0
    fi
    [ -n "$_ec_mode" ]  && chmod "$_ec_mode" "$_ec_tmp"
    [ -n "$_ec_owner" ] && { chown "$_ec_owner" "$_ec_tmp" 2>/dev/null || true; }
    mv -f "$_ec_tmp" "$_ec_path"
    mark_changed "wrote $_ec_path"
    return 0
}

# ── validated in-place edit with rollback ────────────────────────────
# usage: backup_and_edit <file> <validator|""> <sed-expr> [<sed-expr> ...]
# Backs the file up, applies the sed edits, then runs `<validator> <file>`; if
# the validator fails the original is restored (so a bad edit can never brick the
# file — generalises the sudoers safe-edit from the old apply.sh). Returns 0 if
# applied (and calls mark_changed), 1 if reverted.
backup_and_edit() {
    _be_file="$1"; _be_validate="$2"; shift 2
    _be_bak="${_be_file}.hifi-bak.$$"
    cp -a "$_be_file" "$_be_bak"
    for _be_e in "$@"; do sed -i "$_be_e" "$_be_file"; done
    # word-splitting of $_be_validate is intentional (it's a command + args).
    # shellcheck disable=SC2086
    if [ -z "$_be_validate" ] || $_be_validate "$_be_file" >/dev/null 2>&1; then
        rm -f "$_be_bak"
        mark_changed "edited $_be_file"
        return 0
    fi
    mv -f "$_be_bak" "$_be_file"
    log_warn "edit of $_be_file reverted (validation failed)"
    return 1
}

# ── package install (idempotent) ─────────────────────────────────────
# Installs a package only if missing. Honours HIFI_OS_NO_APT=1 (set by the CI
# idempotency test) to stay offline/deterministic. Returns non-zero if the
# install was attempted but failed — caller decides whether that's fatal.
ensure_pkg() {
    if dpkg -s "$1" >/dev/null 2>&1; then
        return 0
    fi
    if [ "${HIFI_OS_NO_APT:-0}" = 1 ]; then
        log_info "skip install $1 (HIFI_OS_NO_APT set)"
        return 0
    fi
    log_info "installing $1…"
    if DEBIAN_FRONTEND=noninteractive apt-get install -y "$1" >/dev/null 2>&1; then
        mark_changed "installed package $1"
        return 0
    fi
    log_warn "could not install $1 now (retry later)"
    return 1
}

# ── audit ledger ─────────────────────────────────────────────────────
# Append one tab-separated row per migration per run: time, version, id, result.
ledger_record() {
    printf '%s\t%s\t%s\t%s\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo '?')" \
        "${HIFI_OS_VERSION:-?}" "$1" "$2" >> "$HIFI_LEDGER" 2>/dev/null || true
}
