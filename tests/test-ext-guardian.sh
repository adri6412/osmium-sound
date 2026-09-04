#!/bin/sh
# Osmium Sound — hifi-ext.sh (user add-ons on a read-only image).
#
# What matters here is the guardian: an add-on may only ADD files. If it were
# ever allowed to cover a file the image ships, sysext would keep serving the
# add-on's copy after an image update and that file would be frozen at the old
# version forever — the failure mode that rules out a writable overlay on /usr.
# So these tests drive the real script with apt and dpkg stubbed out, and check
# that it refuses what must be refused and pins what it builds.
set -u
SCRIPT=${SCRIPT:-distro/config/includes.chroot/usr/local/sbin/hifi-ext.sh}
[ -f "$SCRIPT" ] || { echo "not found: $SCRIPT (run from the repo root)"; exit 1; }

pass=0; fail=0
ok()  { pass=$((pass + 1)); printf 'ok   — %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf 'FAIL — %s\n' "$1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (expected '$2', got '$3')"; fi; }
contains() { if printf '%s' "$2" | grep -q "$3"; then ok "$1"; else bad "$1 (no '$3' in: $(printf '%s' "$2" | tr '\n' ' ' | cut -c1-160))"; fi; }

ROOT=$(mktemp -d "${TMPDIR:-/tmp}/hifi-ext-test.XXXXXX")
trap 'rm -rf "$ROOT"' EXIT INT TERM

setup() {  # <files the fake package ships, one per line in $ROOT/deb.list>
    rm -rf "$ROOT"; mkdir -p "$ROOT/usr/lib/osmium" "$ROOT/usr/bin" "$ROOT/bin" \
        "$ROOT/var/lib/extensions" "$ROOT/var/lib/hifi-player/ext" "$ROOT/payload"
    printf 'v2.5.24-test\n' > "$ROOT/usr/lib/osmium/IMAGE_VERSION"
    printf 'Package: base\nStatus: install ok installed\n\n' > "$ROOT/usr/lib/osmium/dpkg-status"
    printf 'ID=debian\nVERSION_ID="13"\nSYSEXT_LEVEL=v2.5.24-test\n' > "$ROOT/usr/lib/os-release"
    # a file the "image" already ships — covering it must be refused
    : > "$ROOT/usr/bin/already-here"

    # stubs: apt-get "downloads" one .deb, dpkg-deb reads the canned listing
    cat > "$ROOT/bin/apt-get" <<EOF
#!/bin/sh
for a in "\$@"; do case "\$a" in -o) ;; Dir::Cache::archives=*) d=\${a#Dir::Cache::archives=} ;; esac; done
d=\$(printf '%s\n' "\$@" | sed -n 's/^Dir::Cache::archives=//p' | head -n 1)
case " \$* " in *" update "*) exit 0 ;; esac
[ -n "\$d" ] && { mkdir -p "\$d"; : > "\$d/fake_1.0_amd64.deb"; }
exit 0
EOF
    cat > "$ROOT/bin/dpkg-deb" <<EOF
#!/bin/sh
case "\$1" in
    -c) awk '{printf "-rw-r--r-- root/root 10 2026-01-01 00:00 ./%s\n", \$0}' "$ROOT/deb.list" ;;
    -f) case "\$3" in Package) echo fake ;; Version) echo 1.0 ;; *) echo "" ;; esac ;;
    -e) mkdir -p "\$3"; [ -f "$ROOT/have-postinst" ] && printf '#!/bin/sh\n' > "\$3/postinst"; exit 0 ;;
    -x) while read -r f; do mkdir -p "\$3/\$(dirname "\$f")"; : > "\$3/\$f"; done < "$ROOT/deb.list" ;;
esac
exit 0
EOF
    for s in ldconfig systemctl systemd-sysext systemd-sysusers systemd-tmpfiles; do
        printf '#!/bin/sh\nprintf "%%s %%s\\n" "%s" "$*" >> "%s"\nexit 0\n' "$s" "$ROOT/calls" > "$ROOT/bin/$s"
    done
    chmod +x "$ROOT/bin"/*
}

run() { HIFI_EXT_TEST_ROOT="$ROOT" PATH="$ROOT/bin:$PATH" sh "$SCRIPT" "$@" 2>&1; }

# ── 1. a plain add: package installed, extension pinned to the image ────────
setup
printf 'usr/bin/newtool\nusr/lib/libnew.so.1\n' > "$ROOT/deb.list"
out=$(run add fake); rc=$?
check "add: exits 0" "0" "$rc"
check "add: extension created" "yes" "$([ -d "$ROOT/var/lib/extensions/fake" ] && echo yes || echo no)"
check "add: files layered under the extension" "yes" \
      "$([ -f "$ROOT/var/lib/extensions/fake/usr/bin/newtool" ] && echo yes || echo no)"
contains "add: extension-release pins this image" \
         "$(cat "$ROOT/var/lib/extensions/fake/usr/lib/extension-release.d/extension-release.fake")" \
         "SYSEXT_LEVEL=v2.5.24-test"
contains "add: the merge is applied" "$(cat "$ROOT/calls")" "systemd-sysext refresh"
contains "add: the request is kept, not just the result" \
         "$(cat "$ROOT/var/lib/hifi-player/ext/fake/request.json")" '"packages":"fake"'

# ── 2. 🚨 covering a file the image ships must be refused ───────────────────
setup
printf 'usr/bin/newtool\nusr/bin/already-here\n' > "$ROOT/deb.list"
out=$(run add fake); rc=$?
check "shadowing: refused" "1" "$rc"
contains "shadowing: says which file" "$out" "already-here"
check "shadowing: nothing installed" "no" \
      "$([ -d "$ROOT/var/lib/extensions/fake" ] && echo yes || echo no)"

# ── 3. files outside /usr, /opt, /etc, /var are refused ─────────────────────
setup
printf 'srv/weird/file\n' > "$ROOT/deb.list"
out=$(run add fake); rc=$?
check "stray path: refused" "1" "$rc"
contains "stray path: says where" "$out" "srv/weird/file"

# ── 4. /etc content is copied out (sysext only merges /usr and /opt) ────────
setup
printf 'usr/bin/newtool\netc/newtool.conf\n' > "$ROOT/deb.list"
run add fake >/dev/null 2>&1
check "side files: /etc content placed on the live system" "yes" \
      "$([ -f "$ROOT/etc/newtool.conf" ] && echo yes || echo no)"
check "side files: not left inside the extension" "no" \
      "$([ -d "$ROOT/var/lib/extensions/fake/etc" ] && echo yes || echo no)"

# ── 5. maintainer scripts are never run, but they are called out ────────────
setup
printf 'usr/bin/newtool\n' > "$ROOT/deb.list"; : > "$ROOT/have-postinst"
out=$(run add fake)
contains "maintainer scripts: warned about, not executed" "$out" "postinst will NOT be run"

# ── 6. after an image update the add-on is rebuilt and re-pinned ────────────
setup
printf 'usr/bin/newtool\n' > "$ROOT/deb.list"
run add fake >/dev/null 2>&1
printf 'v2.5.25-test\n' > "$ROOT/usr/lib/osmium/IMAGE_VERSION"
out=$(run list)
contains "after an update: listed as stale" "$out" "stale"
run refresh >/dev/null 2>&1
contains "refresh: re-pinned to the new image" \
         "$(cat "$ROOT/var/lib/extensions/fake/usr/lib/extension-release.d/extension-release.fake")" \
         "SYSEXT_LEVEL=v2.5.25-test"
contains "refresh: listed as active again" "$(run list)" "active"

# ── 7. removal ──────────────────────────────────────────────────────────────
run remove fake >/dev/null 2>&1
check "remove: extension gone" "no" \
      "$([ -d "$ROOT/var/lib/extensions/fake" ] && echo yes || echo no)"
check "remove: metadata gone" "no" \
      "$([ -d "$ROOT/var/lib/hifi-player/ext/fake" ] && echo yes || echo no)"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
