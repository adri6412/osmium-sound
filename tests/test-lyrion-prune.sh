#!/bin/bash
# Osmium Sound — which old Lyrion versions hifi-lyrion-update.sh keeps on an
# image (/data/lyrion/<version>, `current` pointing at the one in use).
#
# Only "the previous one" is meant to stay, as a way back. The old loop kept
# whichever directory sorted last ALPHABETICALLY, so after 9.0.9 → 9.0.10 →
# 9.1.0 it deleted 9.0.10 (the one just replaced) and kept 9.0.9.
#
# The script itself needs a real appliance (/data mounted, dpkg-deb, systemd),
# so this runs the REAL lines that pick the previous version and prune, cut out
# of it by their comments, under dash with `set -eu` like the script.
# shellcheck disable=SC2016  # the script's own $variables, matched and written as is
set -u
S="distro/config/includes.chroot/usr/local/sbin/hifi-lyrion-update.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); }
bad() { fail=$((fail+1)); echo "FAIL: $1"; }
expect() { if [ "$2" = "$3" ]; then ok; else bad "$1: expected '$3', got '$2'"; fi; }

[ -f "$S" ] || { echo "missing $S"; exit 1; }
if command -v dash >/dev/null 2>&1; then SH="dash"; else SH="sh"; fi

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT

# the line that reads the outgoing version, and the pruning block
PREV_LINE=$(grep -m1 '^ *prev=\$(basename "\$(readlink "\$LYR_ROOT/current"' "$S")
PRUNE=$(sed -n '/# versioni vecchie: si tiene solo la precedente/,/write_status restarting 90/p' "$S" | sed '$d')
if [ -z "$PREV_LINE" ] || [ -z "$PRUNE" ]; then echo "FAIL: blocks not found in $S"; exit 1; fi
{
    echo 'set -eu'
    echo 'LYR_ROOT=$1; ver=$2'
    echo "$PREV_LINE"
    echo 'ln -sfn "$ver" "$LYR_ROOT/current.new" && mv -T "$LYR_ROOT/current.new" "$LYR_ROOT/current"'
    echo "$PRUNE"
} > "$T/prune.sh"

run() {  # <installed dirs...> -- <current before> <new version> -> what is left
    _r="$T/lyrion"; rm -rf "$_r"; mkdir -p "$_r"
    while [ "$1" != -- ]; do mkdir -p "$_r/$1"; shift; done
    shift
    [ -n "$1" ] && ln -s "$1" "$_r/current"
    mkdir -p "$_r/$2"
    "$SH" "$T/prune.sh" "$_r" "$2" || echo "rc=$?"
    find "$_r" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort -V | tr '\n' ' ' | sed 's/ *$//'
}

expect "9.0.10 replaced by 9.1.0: 9.0.10 stays, not 9.0.9" \
    "$(run 9.0.9 9.0.10 -- 9.0.10 9.1.0)" "9.0.10 9.1.0"
expect "a downgrade keeps the version just left" \
    "$(run 9.0.9 9.0.10 9.1.0 -- 9.1.0 9.0.10)" "9.0.10 9.1.0"
expect "reinstalling the same version: the highest other one stays" \
    "$(run 9.0.9 9.0.10 9.1.0 -- 9.1.0 9.1.0)" "9.0.10 9.1.0"
expect "first install: nothing else to keep" \
    "$(run -- '' 9.1.0)" "9.1.0"
expect "nightlies are ordered by version too" \
    "$(run 9.1.0~1727000000 9.1.0~1729000000 -- 9.1.0~1729000000 9.2.0~1730000000)" \
    "9.1.0~1729000000 9.2.0~1730000000"
expect "a leftover .new of an interrupted install goes" \
    "$(run 9.0.10 9.0.9.new -- 9.0.10 9.1.0)" "9.0.10 9.1.0"

echo "test-lyrion-prune: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
