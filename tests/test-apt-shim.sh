#!/bin/sh
# Osmium Sound — the apt shim (/usr/local/bin/apt, ahead of /usr/bin in PATH).
#
# People should not have to learn a new command to install something, so `apt
# install` keeps working — but on an image system it cannot install for real,
# and must route to the add-on machinery instead. What matters here is that the
# routing is exact: the verbs that change the system go to hifi-ext.sh, every
# other verb reaches the real apt untouched, and on a legacy system the shim
# steps aside completely.
set -u
SHIM=${SHIM:-distro/config/includes.chroot/usr/local/bin/apt}
[ -f "$SHIM" ] || { echo "not found: $SHIM (run from the repo root)"; exit 1; }

pass=0; fail=0
ok()  { pass=$((pass + 1)); printf 'ok   — %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf 'FAIL — %s\n' "$1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (expected '$2', got '$3')"; fi; }

ROOT=$(mktemp -d "${TMPDIR:-/tmp}/hifi-apt-shim-test.XXXXXX")
trap 'rm -rf "$ROOT"' EXIT INT TERM

setup() {  # [--legacy]
    rm -rf "$ROOT"; mkdir -p "$ROOT/usr/bin" "$ROOT/usr/local/sbin" "$ROOT/usr/lib/osmium"
    [ "${1:-}" = "--legacy" ] || printf 'v2.5.24-test\n' > "$ROOT/usr/lib/osmium/IMAGE_VERSION"
    for n in apt apt-get; do
        printf '#!/bin/sh\nprintf "REAL %%s %%s\\n" "%s" "$*" >> "%s"\n' "$n" "$ROOT/calls" > "$ROOT/usr/bin/$n"
    done
    printf '#!/bin/sh\nprintf "EXT %%s\\n" "$*" >> "%s"\n' "$ROOT/calls" > "$ROOT/usr/local/sbin/hifi-ext.sh"
    chmod +x "$ROOT/usr/bin"/* "$ROOT/usr/local/sbin/hifi-ext.sh"
    : > "$ROOT/calls"
}
run()   { HIFI_APT_TEST_ROOT="$ROOT" sh "$SHIM" "$@" 2>"$ROOT/err"; }
calls() { tr '\n' '|' < "$ROOT/calls" | sed 's/|$//'; }

setup
run install mc >/dev/null
check "install routes to the add-on manager" "EXT add mc" "$(calls)"

setup
run install -y mc vim >/dev/null
check "install: options dropped, every package passed on" "EXT add mc vim" "$(calls)"

setup
run remove mc >/dev/null
check "remove routes to the add-on manager" "EXT remove mc" "$(calls)"

setup
run upgrade >/dev/null; rc=$?
check "upgrade: refused" "1" "$rc"
check "upgrade: nothing was run" "" "$(calls)"
if grep -q "whole image" "$ROOT/err"; then ok "upgrade: explains how updates work"; else bad "upgrade: no explanation"; fi

setup
run search mc >/dev/null
check "search reaches the real apt" "REAL apt search mc" "$(calls)"

setup
run update >/dev/null
check "update reaches the real apt" "REAL apt update" "$(calls)"

setup --legacy
run install mc >/dev/null
check "legacy system: the shim steps aside" "REAL apt install mc" "$(calls)"

setup
HIFI_APT_REAL=1 HIFI_APT_TEST_ROOT="$ROOT" sh "$SHIM" install mc >/dev/null 2>&1
check "HIFI_APT_REAL=1 reaches the real apt" "REAL apt install mc" "$(calls)"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
