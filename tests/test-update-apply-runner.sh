#!/bin/sh
# Tests for hifi-update-apply-runner.sh — phase 2 of the isolated update flow
# (applies already-staged, already-verified payloads under system-update.target,
# with nothing else from the app stack running).
#
# Exercised through HIFI_APPLY_TEST_ROOT, which relocates every path the
# script touches into a sandbox — including systemctl and plymouth, which a
# test environment cannot safely call for real. The stub updaters record that
# they ran and write the target version file, exactly the contract the real
# ones honour via their `apply` subcommand.
#
# Run with:
#     sh tests/test-update-apply-runner.sh
set -eu

REPO=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
RUNNER="$REPO/distro/config/includes.chroot/usr/local/sbin/hifi-update-apply-runner.sh"
[ -f "$RUNNER" ] || { echo "runner not found at $RUNNER" >&2; exit 1; }

pass=0
fail=0
ok()   { pass=$((pass + 1)); printf 'ok   — %s\n' "$1"; }
bad()  { fail=$((fail + 1)); printf 'FAIL — %s\n' "$1"; }
check() { # <description> <expected> <actual>
    if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (expected '$2', got '$3')"; fi
}

# ── sandbox ──────────────────────────────────────────────────────────
ROOT=$(mktemp -d "${TMPDIR:-/tmp}/hifi-apply-runner-test.XXXXXX")
trap 'rm -rf "$ROOT"' EXIT INT TERM

setup() {  # fresh sandbox for one case
    rm -rf "$ROOT"
    mkdir -p "$ROOT/sbin" "$ROOT/bin" "$ROOT/update/staged/system" \
             "$ROOT/update/staged/os" "$ROOT/update/staged/ui"
    : > "$ROOT/calls"
    : > "$ROOT/systemctl-calls"
    : > "$ROOT/plymouth-calls"
    printf 'old\n' > "$ROOT/SYSTEM_VERSION"
    printf 'old\n' > "$ROOT/OS_VERSION"
    printf 'old\n' > "$ROOT/UI_VERSION"
    : > "$ROOT/system-update"   # present = "we are in update mode", like the real symlink

    cat > "$ROOT/bin/systemctl-stub" <<EOF
#!/bin/sh
printf '%s\n' "\$*" >> "$ROOT/systemctl-calls"
case "\$1" in
    is-enabled)
        [ -f "$ROOT/ssh-enabled" ] && exit 0 || exit 1
        ;;
    reboot)
        exit 0
        ;;
    *)
        exit 0
        ;;
esac
EOF
    chmod +x "$ROOT/bin/systemctl-stub"

    cat > "$ROOT/bin/plymouth-stub" <<EOF
#!/bin/sh
printf '%s\n' "\$*" >> "$ROOT/plymouth-calls"
exit 0
EOF
    chmod +x "$ROOT/bin/plymouth-stub"
}

# stub <kind> <behaviour: ok|fail>
#   ok   — records the call and writes the target version file (the real
#          updaters all do this only after apply genuinely succeeds)
#   fail — records the call and exits non-zero, writing nothing
stub() {
    _kind=$1; _mode=$2
    case $_kind in
        system) _file=$ROOT/sbin/hifi-system-update.sh; _ver=$ROOT/SYSTEM_VERSION ;;
        os)     _file=$ROOT/sbin/hifi-os-update.sh;     _ver=$ROOT/OS_VERSION ;;
        ui)     _file=$ROOT/sbin/hifi-ota-update.sh;    _ver=$ROOT/UI_VERSION ;;
    esac
    cat > "$_file" <<EOF
#!/bin/sh
printf '%s %s\n' "$_kind" "\$*" >> "$ROOT/calls"
EOF
    case $_mode in
        fail)
            printf 'exit 3\n' >> "$_file"
            ;;
        *)
            cat >> "$_file" <<EOF
printf '%s\n' "\$3" > "$_ver"
EOF
            ;;
    esac
    chmod +x "$_file"
}

write_plan() {  # steps on stdin (state must be 'done' — apply only ever runs
                # once every step has finished staging)
    { echo 'v 2'; echo 'plan test-1 dev 1700000000'; cat; echo 'finished 1700000000 finished'; } \
        > "$ROOT/update/plan"
}

stage_dir() {  # <kind> <version> — mkdir the staged dir the plan step refers to
    mkdir -p "$ROOT/update/staged/$1/$2"
}

run_runner() {
    HIFI_APPLY_TEST_ROOT="$ROOT" sh "$RUNNER" >> "$ROOT/runner.log" 2>&1 || return $?
}

installed() { cat "$ROOT/$1" 2>/dev/null; }  # <SYSTEM_VERSION|OS_VERSION|UI_VERSION>
calls()     { tr '\n' ' ' < "$ROOT/calls" | sed 's/ *$//'; }
state_of()  { awk -F= -v k="$1" '$1==k{print substr($0,length(k)+2)}' "$ROOT/update/state" 2>/dev/null; }

# ── 1. happy path: all three applied, in order, box "reboots" ─────────
setup
stub system ok; stub os ok; stub ui ok
stage_dir system v2; stage_dir os v2; stage_dir ui v2
write_plan <<EOF
step system done 1 v2 https://e/sys.tgz aaaa -
step os done 1 v2 https://e/os.tgz bbbb https://e/os.sig
step ui done 1 v2 https://e/ui.tgz cccc -
EOF
rc=0
run_runner || rc=$?
check "happy path: exits 0" "0" "$rc"
check "happy path: system applied first" "system apply $ROOT/update/staged/system/v2 v2" \
      "$(head -n 1 "$ROOT/calls")"
check "happy path: os applied second" "os apply $ROOT/update/staged/os/v2 v2" \
      "$(sed -n 2p "$ROOT/calls")"
check "happy path: ui applied last" "ui apply $ROOT/update/staged/ui/v2 v2" \
      "$(sed -n 3p "$ROOT/calls")"
check "happy path: every version landed" "v2 v2 v2" \
      "$(installed SYSTEM_VERSION) $(installed OS_VERSION) $(installed UI_VERSION)"
check "happy path: plan removed" "no" "$([ -f "$ROOT/update/plan" ] && echo yes || echo no)"
check "happy path: state is done" "done" "$(state_of phase)"
check "happy path: /system-update cleared" "no" "$([ -f "$ROOT/system-update" ] && echo yes || echo no)"
check "happy path: rebooted" "yes" "$(grep -q '^reboot$' "$ROOT/systemctl-calls" && echo yes || echo no)"
check "happy path: splash reached 100%" "yes" \
      "$(grep -q 'system-update --progress=100' "$ROOT/plymouth-calls" && echo yes || echo no)"

# ── 2. a component already applied (matching version) is skipped ──────
# Guards the crash-recovery path: system-update.target re-enters this script
# from the top after a mid-apply crash, so an already-landed step must not be
# re-applied (the UI step's staged payload is consumed by its own swap — a
# second call would find it gone and fail for the wrong reason).
setup
stub system ok; stub os ok; stub ui ok
stage_dir system v2; stage_dir os v2; stage_dir ui v2
printf 'v2\n' > "$ROOT/SYSTEM_VERSION"   # system already applied
write_plan <<EOF
step system done 1 v2 https://e/sys.tgz aaaa -
step os done 1 v2 https://e/os.tgz bbbb https://e/os.sig
step ui done 1 v2 https://e/ui.tgz cccc -
EOF
run_runner || true
check "skip: system not re-applied" "" "$(grep '^system ' "$ROOT/calls" || true)"
check "skip: os and ui still applied" "os apply $ROOT/update/staged/os/v2 v2 ui apply $ROOT/update/staged/ui/v2 v2" \
      "$(calls)"
check "skip: overall still succeeds" "done" "$(state_of phase)"

# ── 3. a step not marked 'done' in the plan is a hard, immediate error ─
# The stage runner only creates /system-update once EVERY step reached
# 'done' — anything else here means the on-disk plan was corrupted between
# boots. Must never guess or silently proceed.
setup
stub system ok; stub os ok; stub ui ok
stage_dir system v2; stage_dir os v2; stage_dir ui v2
write_plan <<EOF
step system done 1 v2 https://e/sys.tgz aaaa -
step os pending 0 v2 https://e/os.tgz bbbb https://e/os.sig
step ui done 1 v2 https://e/ui.tgz cccc -
EOF
rc=0
run_runner || rc=$?
check "bad plan: exits non-zero" "1" "$rc"
check "bad plan: system applied before the bad step was hit" "system apply $ROOT/update/staged/system/v2 v2" \
      "$(calls)"
check "bad plan: state is error" "error" "$(state_of phase)"
check "bad plan: does not reboot" "no" "$(grep -q '^reboot$' "$ROOT/systemctl-calls" && echo yes || echo no)"
check "bad plan: /system-update left in place" "yes" "$([ -f "$ROOT/system-update" ] && echo yes || echo no)"

# ── 4. a step that keeps failing gives up after its retry budget ──────
setup
stub system fail; stub ui ok
stage_dir system v2; stage_dir ui v2
write_plan <<EOF
step system done 1 v2 https://e/sys.tgz aaaa -
step ui done 1 v2 https://e/ui.tgz cccc -
EOF
rc=0
run_runner || rc=$?
check "retry: exits non-zero" "1" "$rc"
check "retry: attempted exactly twice" "2" "$(grep -c '^system ' "$ROOT/calls")"
check "retry: ui never reached" "" "$(grep '^ui ' "$ROOT/calls" || true)"
check "retry: state is error" "error" "$(state_of phase)"
check "retry: /system-update left in place" "yes" "$([ -f "$ROOT/system-update" ] && echo yes || echo no)"

# ── 5. a missing staged directory is refused, not silently skipped ────
setup
stub system ok
write_plan <<EOF
step system done 1 v2 https://e/sys.tgz aaaa -
EOF
rc=0
run_runner || rc=$?
check "missing staged dir: exits non-zero" "1" "$rc"
check "missing staged dir: updater never invoked" "" "$(calls)"
check "missing staged dir: state is error" "error" "$(state_of phase)"

# ── 6. SSH is brought up only if the owner had already enabled it ─────
setup
stub system ok; stub os ok; stub ui ok
stage_dir system v2; stage_dir os v2; stage_dir ui v2
write_plan <<EOF
step system done 1 v2 https://e/sys.tgz aaaa -
step os done 1 v2 https://e/os.tgz bbbb https://e/os.sig
step ui done 1 v2 https://e/ui.tgz cccc -
EOF
run_runner || true
check "ssh: left off when never enabled" "" "$(grep '^start ssh.service$' "$ROOT/systemctl-calls" || true)"

setup
stub system ok; stub os ok; stub ui ok
stage_dir system v2; stage_dir os v2; stage_dir ui v2
: > "$ROOT/ssh-enabled"
write_plan <<EOF
step system done 1 v2 https://e/sys.tgz aaaa -
step os done 1 v2 https://e/os.tgz bbbb https://e/os.sig
step ui done 1 v2 https://e/ui.tgz cccc -
EOF
run_runner || true
check "ssh: started when already enabled" "start ssh.service" \
      "$(grep '^start ssh.service$' "$ROOT/systemctl-calls" || true)"


# ── 7. A/B conversion: one single upgrade — the UI step is skipped when the
#      box is about to convert (the image brings the interface), and the
#      conversion is armed after the last step ─────────────────────────────
ab_stubs() {  # <precheck-exit-code>
    cat > "$ROOT/sbin/hifi-ab-precheck.sh" <<EOF
#!/bin/sh
printf 'precheck\n' >> "$ROOT/calls"
printf '{"convertible":false,"reasons":"not enough space","free_needed_mib":470,"disk_mib":6208}\n' > "$ROOT/hifi-ab-precheck.json"
exit $1
EOF
    cat > "$ROOT/sbin/hifi-ab-convert.sh" <<EOF
#!/bin/sh
printf 'convert %s\n' "\$*" >> "$ROOT/calls"
exit 0
EOF
    chmod +x "$ROOT/sbin/hifi-ab-precheck.sh" "$ROOT/sbin/hifi-ab-convert.sh"
}

setup
stub system ok; stub os ok; stub ui ok
stage_dir system v2; stage_dir os v2; stage_dir ui v2
ab_stubs 0
write_plan <<EOF
step system done 1 v2 https://e/sys.tgz aaaa -
step os done 1 v2 https://e/os.tgz bbbb https://e/os.sig
step ui done 1 v2 https://e/ui.tgz cccc -
EOF
rc=0
run_runner || rc=$?
check "ab convertible: exits 0" "0" "$rc"
check "ab convertible: system+os applied, ui skipped, conversion armed" \
      "system apply $ROOT/update/staged/system/v2 v2 os apply $ROOT/update/staged/os/v2 v2 precheck convert cleanup convert prepare" \
      "$(calls)"
check "ab convertible: legacy UI left as is" "old" "$(installed UI_VERSION)"
check "ab convertible: state stays applying (continuous overlay)" "applying update.ab.converting" \
      "$(state_of phase) $(state_of key)"

setup
stub system ok; stub os ok; stub ui ok
stage_dir system v2; stage_dir os v2; stage_dir ui v2
ab_stubs 1
write_plan <<EOF
step system done 1 v2 https://e/sys.tgz aaaa -
step os done 1 v2 https://e/os.tgz bbbb https://e/os.sig
step ui done 1 v2 https://e/ui.tgz cccc -
EOF
run_runner || true
check "ab not convertible: ui applied, pre-check retried after cleanup, no prepare" \
      "system apply $ROOT/update/staged/system/v2 v2 os apply $ROOT/update/staged/os/v2 v2 precheck ui apply $ROOT/update/staged/ui/v2 v2 convert cleanup --deep precheck" \
      "$(calls)"
check "ab not convertible: UI landed" "v2" "$(installed UI_VERSION)"
check "ab not convertible: the update is reported as failed" "error update.ab.noSpace" \
      "$(state_of phase) $(state_of key)"
check "ab not convertible: how much to free is carried" "470 6208" \
      "$(state_of params | sed -n 's/.*"needed":\([0-9]*\),"disk":\([0-9]*\).*/\1 \2/p')"
check "ab not convertible: the error file names the failure too" "update.ab.noSpace" \
      "$(sed -n 's/.*"key":"\([^"]*\)".*/\1/p' "$ROOT/update/error.json")"

# already an image (or RAUC configured): the A/B block must stay out of the way
setup
stub system ok; stub os ok; stub ui ok
stage_dir system v2; stage_dir os v2; stage_dir ui v2
ab_stubs 0
mkdir -p "$ROOT/etc/rauc"; : > "$ROOT/etc/rauc/system.conf"
write_plan <<EOF
step system done 1 v2 https://e/sys.tgz aaaa -
step ui done 1 v2 https://e/ui.tgz cccc -
EOF
run_runner || true
check "ab already configured: no pre-check, ui applied" \
      "system apply $ROOT/update/staged/system/v2 v2 ui apply $ROOT/update/staged/ui/v2 v2" "$(calls)"

# a failing step reports a translation key next to its English text
setup
stub system fail
stage_dir system v2
write_plan <<EOF
step system done 1 v2 https://e/sys.tgz aaaa -
EOF
run_runner || true
check "failed step: error.json carries the key" "update.apply.failed" \
      "$(sed -n 's/.*"key":"\([^"]*\)".*/\1/p' "$ROOT/update/error.json")"
check "failed step: params name the kind" "yes" \
      "$(grep -q '"params":{"kind":"system","version":"v2"' "$ROOT/update/error.json" && echo yes || echo no)"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
