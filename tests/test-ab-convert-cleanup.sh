#!/bin/bash
# Osmium Sound — `hifi-ab-convert.sh cleanup [--deep]`, the REAL script.
#
# The dispatcher shifted the command word twice: `cleanup --deep` (what the
# apply runner calls when the legacy root is too full to shrink) lost its
# --deep and never did the deep part, and a bare `cleanup` died under dash on
# "can't shift that many" before freeing anything. Both calls are `|| true`
# in the runner, so nothing ever said so. The runner's own test stubs this
# script out; this one runs it, under dash like the appliance does.
#
# Hermetic: a fake hifi-ab-lib.sh (HIFI_AB_LIB) and stand-ins on PATH for
# every command that would touch the machine (rm, apt-get, find, df, ...):
# they only write down how they were called.
set -u
S="$PWD/distro/config/includes.chroot/usr/local/sbin/hifi-ab-convert.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); }
bad() { fail=$((fail+1)); echo "FAIL: $1"; }
expect() { if [ "$2" = "$3" ]; then ok; else bad "$1: expected '$3', got '$2'"; fi; }

[ -f "$S" ] || { echo "missing $S"; exit 1; }
if command -v dash >/dev/null 2>&1; then SH="dash"; else SH="sh"; fi

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin"
CALLS="$T/calls"

cat > "$T/lib.sh" <<'LIB'
AB_SLOT_A_MARGIN_MIN_MIB=0
ab_log()  { printf 'I: %s\n' "$*" >> "$HIFI_TEST_CALLS"; }
ab_warn() { printf 'W: %s\n' "$*" >> "$HIFI_TEST_CALLS"; }
ab_is_image() { return 1; }
ab_slot_a_max_mib() { echo 100; }
ab_root_min_mib() { echo 9999; }
LIB

for c in rm apt-get journalctl find; do
    # shellcheck disable=SC2016  # expanded by the stub, not here
    printf '#!/bin/sh\necho "%s $*" >> "$HIFI_TEST_CALLS"\nexit 0\n' "$c" > "$T/bin/$c"
done
printf '#!/bin/sh\necho 0\n' > "$T/bin/id"
printf '#!/bin/sh\necho "Filesystem 1M-blocks Used Available Capacity Mounted"\necho "/dev/x 1000 500 500 50%% /"\n' > "$T/bin/df"
chmod +x "$T/bin/"*

run() {
    : > "$CALLS"
    HIFI_AB_LIB="$T/lib.sh" HIFI_TEST_CALLS="$CALLS" PATH="$T/bin:$PATH" \
        "$SH" "$S" "$@" >/dev/null 2>&1
}

run cleanup
expect "a bare cleanup completes" "$?" 0
expect "...and does the ordinary part" "$(grep -c '^apt-get clean' "$CALLS")" 1
expect "...but not the deep one" "$(grep -c 'pulizia profonda \[' "$CALLS")" 0

run cleanup --deep
expect "cleanup --deep completes" "$?" 0
expect "--deep reaches the deep steps" "$(grep -c 'pulizia profonda \[' "$CALLS")" 4
expect "...the docs go" "$(grep -c '^rm -rf /usr/share/doc/' "$CALLS")" 1

run cleanup --deep 50000
expect "a target already met stops the deep steps" "$(grep -c 'pulizia profonda: basta' "$CALLS")" 1

echo "test-ab-convert-cleanup: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
