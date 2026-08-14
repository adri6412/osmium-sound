#!/bin/sh
# Tests for hifi-update-runner.sh — the server-side OTA sequencer.
#
# Every case here is a failure mode that was actually observed in the field as
# "the update only applied some of the components". Run with:
#     sh tests/test-update-runner.sh
#
# The runner is exercised through HIFI_UPDATE_TEST_ROOT, which relocates the
# plan file, the three updater scripts and the three version files into a
# sandbox. The stub updaters record that they ran and write the version file,
# which is exactly the contract the real ones honour.
set -eu

REPO=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
RUNNER="$REPO/distro/config/includes.chroot/usr/local/sbin/hifi-update-runner.sh"
[ -f "$RUNNER" ] || { echo "runner not found at $RUNNER" >&2; exit 1; }

pass=0
fail=0
ok()   { pass=$((pass + 1)); printf 'ok   — %s\n' "$1"; }
bad()  { fail=$((fail + 1)); printf 'FAIL — %s\n' "$1"; }
check() { # <description> <expected> <actual>
    if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (expected '$2', got '$3')"; fi
}

# ── sandbox ──────────────────────────────────────────────────────────
ROOT=$(mktemp -d "${TMPDIR:-/tmp}/hifi-runner-test.XXXXXX")
trap 'rm -rf "$ROOT"' EXIT INT TERM

setup() {  # fresh sandbox for one case
    rm -rf "$ROOT"; mkdir -p "$ROOT/sbin"
    : > "$ROOT/calls"
    printf 'old\n' > "$ROOT/SYSTEM_VERSION"
    printf 'old\n' > "$ROOT/OS_VERSION"
    printf 'old\n' > "$ROOT/UI_VERSION"
}

# stub <kind> <behaviour: ok|fail|reboot>
#   ok      — records the call and writes the version file (the real updaters
#             all record their version before returning)
#   fail    — records the call and exits non-zero
#   reboot  — records the call, writes the version file, then kills the runner
#             the way `systemctl reboot` does: the step stays 'running' in the
#             plan and the process never comes back
#
# Built with quoted-free heredocs (never `echo`) on purpose: `echo` expands
# backslash escapes in dash but not in bash, so an `echo "printf '%s\n' …"`
# here generates a *different*, broken stub depending on which /bin/sh runs
# the suite.
stub() {
    _kind=$1; _mode=$2
    # _vn: which positional argument carries the version. The OS updater takes
    # an extra signature-URL argument, so its version is $4, not $3.
    case $_kind in
        system) _file=$ROOT/sbin/hifi-system-update.sh; _ver=$ROOT/SYSTEM_VERSION; _vn=3 ;;
        os)     _file=$ROOT/sbin/hifi-os-update.sh;     _ver=$ROOT/OS_VERSION;     _vn=4 ;;
        ui)     _file=$ROOT/sbin/hifi-ota-update.sh;    _ver=$ROOT/UI_VERSION;     _vn=3 ;;
    esac
    cat > "$_file" <<EOF
#!/bin/sh
printf '%s %s\n' "$_kind" "\$*" >> "$ROOT/calls"
EOF
    case $_mode in
        fail)
            printf 'exit 3\n' >> "$_file"
            ;;
        reboot)
            cat >> "$_file" <<EOF
printf '%s\n' "\$$_vn" > "$_ver"
kill -9 \$PPID 2>/dev/null
exit 0
EOF
            ;;
        *)
            cat >> "$_file" <<EOF
printf '%s\n' "\$$_vn" > "$_ver"
EOF
            ;;
    esac
    chmod +x "$_file"
}

write_plan() {  # steps on stdin
    { echo 'v 1'; echo 'plan test-1 dev 1700000000'; cat; } > "$ROOT/update-plan"
}

run_runner() {
    HIFI_UPDATE_TEST_ROOT="$ROOT" sh "$RUNNER" >> "$ROOT/runner.log" 2>&1 || return $?
}

step_state() {  # <kind>
    awk -v k="$1" '$1=="step" && $2==k { print $3 }' "$ROOT/update-plan"
}
overall() { awk '$1=="finished" { print $3 }' "$ROOT/update-plan"; }
calls()   { tr '\n' ' ' < "$ROOT/calls" | sed 's/ *$//'; }

# ── 1. happy path: all three steps, in order ─────────────────────────
setup
stub system ok; stub os ok; stub ui ok
write_plan <<EOF
step system pending 0 v2 https://e/sys.tgz aaaa -
step os pending 0 v2 https://e/os.tgz bbbb https://e/os.sig
step ui pending 0 v2 https://e/ui.tgz cccc -
EOF
run_runner || true
check "happy path: system applied first" "system https://e/sys.tgz aaaa v2" \
      "$(head -n 1 "$ROOT/calls")"
check "happy path: os receives the signature URL" "os https://e/os.tgz bbbb https://e/os.sig v2" \
      "$(sed -n 2p "$ROOT/calls")"
check "happy path: ui applied last" "ui https://e/ui.tgz cccc v2" "$(sed -n 3p "$ROOT/calls")"
check "happy path: plan finished" "finished" "$(overall)"
check "happy path: every step done" "done done done" \
      "$(step_state system) $(step_state os) $(step_state ui)"
check "happy path: mandatory reboot fired" "yes" \
      "$([ -f "$ROOT/update-plan.would-reboot" ] && echo yes || echo no)"

# ── 2. the field bug: an OS step that reboots must not lose the UI step ──
# The OS payload reboots, so the runner dies mid-plan and /run is wiped. The
# boot-time resume unit re-runs the runner: the os step is still 'running', but
# its version landed before the reboot, so it counts as done and the plan
# carries on to the UI — which is exactly what used to be dropped.
setup
stub system ok; stub os reboot; stub ui ok
write_plan <<EOF
step system pending 0 v2 https://e/sys.tgz aaaa -
step os pending 0 v2 https://e/os.tgz bbbb https://e/os.sig
step ui pending 0 v2 https://e/ui.tgz cccc -
EOF
run_runner || true   # killed by the reboot stub
check "reboot: os left marked running" "running" "$(step_state os)"
check "reboot: ui not started yet" "" "$(step_state ui | sed 's/pending//')"
check "reboot: ui still pending" "pending" "$(step_state ui)"
run_runner || true   # second boot: hifi-update-resume.service
check "reboot: os resolved as done after resume" "done" "$(step_state os)"
check "reboot: ui applied after the reboot" "ui https://e/ui.tgz cccc v2" \
      "$(grep '^ui ' "$ROOT/calls")"
check "reboot: plan finished" "finished" "$(overall)"
check "reboot: mandatory reboot fires once resume completes it" "yes" \
      "$([ -f "$ROOT/update-plan.would-reboot" ] && echo yes || echo no)"

# ── 3. a failing step stops the plan (and doesn't apply the rest) ─────
setup
stub system fail; stub os ok; stub ui ok
write_plan <<EOF
step system pending 0 v2 https://e/sys.tgz aaaa -
step os pending 0 v2 https://e/os.tgz bbbb https://e/os.sig
step ui pending 0 v2 https://e/ui.tgz cccc -
EOF
run_runner || true
check "failure: system marked error" "error" "$(step_state system)"
check "failure: later steps untouched" "pending pending" "$(step_state os) $(step_state ui)"
check "failure: only the failing step ran" "system https://e/sys.tgz aaaa v2" "$(calls)"
check "failure: plan reports error" "error" "$(overall)"
check "failure: does not reboot" "no" \
      "$([ -f "$ROOT/update-plan.would-reboot" ] && echo yes || echo no)"

# ── 4. a step that exits 0 without landing its version is a failure ───
# A truncated bundle, or an updater that dies after its own success message,
# used to look like success to the client because the /run status file said so.
setup
stub system ok; stub os ok; stub ui ok
cat > "$ROOT/sbin/hifi-system-update.sh" <<EOF
#!/bin/sh
printf '%s %s\n' system "\$*" >> "$ROOT/calls"
exit 0
EOF
chmod +x "$ROOT/sbin/hifi-system-update.sh"
write_plan <<EOF
step system pending 0 v2 https://e/sys.tgz aaaa -
step ui pending 0 v2 https://e/ui.tgz cccc -
EOF
run_runner || true
check "silent no-op: caught as an error" "error" "$(step_state system)"
check "silent no-op: ui not applied" "pending" "$(step_state ui)"

# ── 5. retry budget: a step interrupted twice gives up ────────────────
setup
stub system reboot; stub ui ok
write_plan <<EOF
step system pending 0 v9 https://e/sys.tgz aaaa -
step ui pending 0 v9 https://e/ui.tgz cccc -
EOF
# The stub writes the version, so make it write the WRONG one to simulate an
# interruption that never landed.
cat > "$ROOT/sbin/hifi-system-update.sh" <<EOF
#!/bin/sh
printf '%s %s\n' system "\$*" >> "$ROOT/calls"
kill -9 \$PPID 2>/dev/null
exit 0
EOF
chmod +x "$ROOT/sbin/hifi-system-update.sh"
run_runner || true
check "retry: first attempt recorded" "running" "$(step_state system)"
run_runner || true
run_runner || true
check "retry: gives up after the budget" "error" "$(step_state system)"
check "retry: attempted exactly twice" "2" "$(grep -c '^system ' "$ROOT/calls")"

# ── 6. an already-finished plan is a no-op (resume unit on every boot) ──
# The `finished` line is already there, simulating the resume unit running
# again on a LATER, unrelated boot (box manually rebooted before the
# completed overlay was dismissed) — this must NOT reboot again, or every
# such boot would trigger another one forever.
setup
stub system ok; stub os ok; stub ui ok
write_plan <<EOF
step system done 1 v2 https://e/sys.tgz aaaa -
step ui done 1 v2 https://e/ui.tgz cccc -
finished 1700000000 finished
EOF
run_runner || true
check "no-op: nothing re-applied" "" "$(calls)"
check "no-op: still finished" "finished" "$(overall)"
check "no-op: does not reboot again" "no" \
      "$([ -f "$ROOT/update-plan.would-reboot" ] && echo yes || echo no)"

# ── 7. no plan at all → clean exit 0 (the common boot case) ──────────
setup
rc=0
run_runner || rc=$?
check "no plan: exits 0" "0" "$rc"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
