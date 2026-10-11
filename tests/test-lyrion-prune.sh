#!/bin/bash
# Osmium Sound — which old Lyrion versions hifi-lyrion-update.sh keeps on an
# image (/data/lyrion/<version>, `current` pointing at the one in use).
#
# Only the version in use stays (2026-10-11): the previous one used to be kept
# as a way back, and on a 16 GB disk its ~225 MB were missed. Leftovers of an
# interrupted install go too, and with no version in use nothing is touched.
#
# The script itself needs a real appliance (/data mounted, dpkg-deb, systemd),
# so this runs the REAL pruning lines, cut out of it by their comments, under
# dash with `set -eu` like the script.
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

# the pruning block
PRUNE=$(sed -n '/# versioni vecchie: si tiene solo quella in uso/,/write_status restarting 90/p' "$S" | sed '$d')
if [ -z "$PRUNE" ]; then echo "FAIL: block not found in $S"; exit 1; fi
{
    echo 'set -eu'
    echo 'LYR_ROOT=$1; ver=$2'
    echo '[ -n "$ver" ] && ln -sfn "$ver" "$LYR_ROOT/current.new" && mv -T "$LYR_ROOT/current.new" "$LYR_ROOT/current"'
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

expect "an update keeps only the new version" \
    "$(run 9.0.9 9.0.10 -- 9.0.10 9.1.0)" "9.1.0"
expect "a downgrade keeps only the version installed" \
    "$(run 9.0.9 9.0.10 9.1.0 -- 9.1.0 9.0.10)" "9.0.10"
expect "reinstalling the same version" \
    "$(run 9.0.9 9.0.10 9.1.0 -- 9.1.0 9.1.0)" "9.1.0"
expect "first install: nothing else" \
    "$(run -- '' 9.1.0)" "9.1.0"
expect "nightlies" \
    "$(run 9.1.0~1727000000 9.1.0~1729000000 -- 9.1.0~1729000000 9.2.0~1730000000)" "9.2.0~1730000000"
expect "no version in use: nothing is touched" \
    "$(run 9.0.9 9.1.0 -- '' '')" "9.0.9 9.1.0"
expect "a leftover .new of an interrupted install goes" \
    "$(run 9.0.10 9.0.9.new -- 9.0.10 9.1.0)" "9.1.0"

echo "test-lyrion-prune: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
