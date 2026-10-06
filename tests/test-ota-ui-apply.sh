#!/bin/bash
# Osmium Sound — `hifi-ota-update.sh apply`, the UI step of an update.
#
# Two things went wrong here and must not again:
#  - under `set -eu` a failed install_payload ended the script before `fail`
#    ran, so the status file stayed on "applying" forever;
#  - the payload is consumed (renamed into /opt) before UI_VERSION is
#    written, so a power cut in between left nothing to install and every
#    retry failed: the update could never complete.
#
# Hermetic: HIFI_OTA_TEST_ROOT puts every path under a temp dir.
set -u
S="$PWD/distro/config/includes.chroot/usr/local/sbin/hifi-ota-update.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); }
bad() { fail=$((fail+1)); echo "FAIL: $1"; }
expect() { if [ "$2" = "$3" ]; then ok; else bad "$1: expected '$3', got '$2'"; fi; }

[ -f "$S" ] || { echo "missing $S"; exit 1; }

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
export HIFI_OTA_TEST_ROOT="$T"

reset() {
    rm -rf "${T:?}"/*
    mkdir -p "$T/opt/hifi-qt" "$T/etc/hifi-player" "$T/run" "$T/update/staged/ui"
    printf '#!/bin/sh\n' > "$T/opt/hifi-qt/hifi-qt"; chmod +x "$T/opt/hifi-qt/hifi-qt"
    echo old > "$T/opt/hifi-qt/WHICH"
    echo 1.0 > "$T/etc/hifi-player/UI_VERSION"
}

stage() {  # <version> [noui]
    D="$T/update/staged/ui/$1"
    mkdir -p "$D/payload"
    if [ "${2:-}" != noui ]; then
        printf '#!/bin/sh\n' > "$D/payload/hifi-qt"; chmod +x "$D/payload/hifi-qt"
    fi
    echo "$1" > "$D/payload/WHICH"
    echo "$1" > "$D/STAGED"
}

apply() { sh "$S" apply "$T/update/staged/ui/$1" "$1" >/dev/null 2>&1; echo $?; }
state() { sed -n 's/.*"state":"\([^"]*\)".*/\1/p' "$T/run/hifi-ota-status.json" 2>/dev/null; }
ver()   { cat "$T/etc/hifi-player/UI_VERSION" 2>/dev/null; }

# 1. The ordinary case.
reset; stage 2.0
expect "plain apply rc" "$(apply 2.0)" 0
expect "plain apply installs the payload" "$(cat "$T/opt/hifi-qt/WHICH")" 2.0
expect "plain apply writes the version" "$(ver)" 2.0
expect "plain apply keeps the old tree aside" "$(cat "$T/opt/hifi-qt.old/WHICH")" old
expect "plain apply status" "$(state)" "done"

# 2. A payload with no interface in it: an error on the status file, not a
#    script that dies silently with "applying" left behind.
reset; stage 2.0 noui
expect "bad payload rc" "$(apply 2.0)" 1
expect "bad payload status" "$(state)" error
expect "bad payload leaves the interface alone" "$(cat "$T/opt/hifi-qt/WHICH")" old

# 3. Interrupted after the swap, before the version: the first run cannot
#    write UI_VERSION (a directory in the way of the temp file), which is
#    exactly the state a power cut there leaves. It must say so, and the retry
#    must finish the job instead of failing on a payload that is gone.
reset; stage 2.0
mkdir "$T/etc/hifi-player/UI_VERSION.tmp"
expect "version not writable rc" "$(apply 2.0)" 1
expect "version not writable status" "$(state)" error
expect "payload already consumed" "$([ -e "$T/update/staged/ui/2.0/payload" ] && echo yes || echo no)" no
expect "old version still on file" "$(ver)" 1.0
rmdir "$T/etc/hifi-player/UI_VERSION.tmp"
expect "retry after interruption rc" "$(apply 2.0)" 0
expect "retry writes the version" "$(ver)" 2.0
expect "retry status" "$(state)" "done"
expect "retry leaves the new tree" "$(cat "$T/opt/hifi-qt/WHICH")" 2.0

# 4. Payload gone and the installed tree is NOT that version: still an error.
reset; stage 2.0
rm -rf "$T/update/staged/ui/2.0/payload"
expect "missing payload rc" "$(apply 2.0)" 1
expect "missing payload status" "$(state)" error
expect "missing payload keeps the version" "$(ver)" 1.0

# 5. Interrupted between the two renames of the swap: /opt/hifi-qt gone, the
#    running interface in hifi-qt.old. The retry installs the payload and must
#    not throw away the only other copy of the interface.
reset; stage 2.0
mv "$T/opt/hifi-qt" "$T/opt/hifi-qt.old"
expect "mid-swap retry rc" "$(apply 2.0)" 0
expect "mid-swap retry installs" "$(cat "$T/opt/hifi-qt/WHICH")" 2.0
expect "mid-swap retry keeps the backup" "$(cat "$T/opt/hifi-qt.old/WHICH" 2>/dev/null)" old
expect "mid-swap retry version" "$(ver)" 2.0

# 6. The stamp travels with the tree.
expect "installed tree carries its version" "$(cat "$T/opt/hifi-qt/.hifi-ui-version")" 2.0

echo "test-ota-ui-apply: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
