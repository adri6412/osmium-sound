#!/bin/bash
# Osmium Sound — the Lyrion install's bar keeps moving through the unpacking
# and the write-out (hifi-lyrion-update.sh, image branch).
#
# On a USB stick that stretch takes minutes, and with one status for all of it
# the bar sat at 60 % and looked hung. This runs the REAL helper functions,
# cut out of the script, under dash with `set -eu` like the script, on a real
# .deb built here.
# shellcheck disable=SC2016  # the generated script's own $variables, written as is
set -u
S="distro/config/includes.chroot/usr/local/sbin/hifi-lyrion-update.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); }
bad() { fail=$((fail+1)); echo "FAIL: $1"; }

[ -f "$S" ] || { echo "missing $S"; exit 1; }
command -v dpkg-deb >/dev/null 2>&1 || { echo "SKIP: no dpkg-deb"; exit 0; }
if command -v dash >/dev/null 2>&1; then SH="dash"; else SH="sh"; fi
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT

FUNCS=$(sed -n '/^dirty_kb() {/,/^flush_with_progress() {/p' "$S"; sed -n '/^flush_with_progress() {/,/^}/p' "$S" | sed 1d)
[ -n "$FUNCS" ] || { echo "FAIL: helpers not found in $S"; exit 1; }

# a package with a few thousand small files, like Lyrion's
mkdir -p "$T/pkg/DEBIAN" "$T/pkg/usr/share/squeezeboxserver"
printf 'Package: lyrionmusicserver\nVersion: 9.9.9\nArchitecture: all\nMaintainer: t <t@t>\nDescription: t\n' > "$T/pkg/DEBIAN/control"
for d in $(seq 1 40); do
    mkdir -p "$T/pkg/usr/share/squeezeboxserver/d$d"
    for f in $(seq 1 50); do head -c 2000 /dev/urandom > "$T/pkg/usr/share/squeezeboxserver/d$d/f$f.pm"; done
done
dpkg-deb -Zgzip -b "$T/pkg" "$T/t.deb" >/dev/null || { echo "FAIL: dpkg-deb -b"; exit 1; }

{
    echo 'set -eu'
    echo 'write_status() { echo "$1 $2" >> "$STATUS_LOG"; }'
    echo "$FUNCS"
    # sleep shortened so a fast extraction still reports at least once
    echo 'sleep() { command sleep 0.05; }'
    echo 'mkdir -p "$2"'
    echo 'extract_with_progress "$1" "$2" "$(dpkg-deb -c "$1" | wc -l)"'
    echo 'flush_with_progress "$2"'
    echo 'echo finished'
} > "$T/run.sh"

out=$(STATUS_LOG="$T/status" "$SH" "$T/run.sh" "$T/t.deb" "$T/dest" 2>&1)
if [ "$out" = finished ]; then ok; else bad "the helpers did not run through: $out"; fi
n=$(find "$T/dest" -type f | wc -l)
if [ "$n" -eq 2000 ]; then ok; else bad "unpacked $n files, expected 2000"; fi

# every status is `applying`, inside 60..89, and never goes backwards
if [ -s "$T/status" ]; then ok; else bad "no progress was reported"; fi
prev=0; bad_line=""
while read -r st p; do
    if [ "$st" != applying ] || [ "$p" -lt 60 ] || [ "$p" -gt 89 ] || [ "$p" -lt "$prev" ]; then
        bad_line="$st $p after $prev"; break
    fi
    prev=$p
done < "$T/status"
if [ -z "$bad_line" ]; then ok; else bad "out-of-range or backwards progress: $bad_line"; fi

# a broken package fails the install instead of passing as done
printf 'not a deb' > "$T/broken.deb"
rc=0; STATUS_LOG="$T/status2" "$SH" "$T/run.sh" "$T/broken.deb" "$T/dest2" >/dev/null 2>&1 || rc=$?
if [ "$rc" -ne 0 ]; then ok; else bad "a broken .deb did not fail the extraction"; fi

echo "test-lyrion-progress: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
