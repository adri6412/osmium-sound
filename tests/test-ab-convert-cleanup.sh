#!/bin/bash
# Osmium Sound — `hifi-ab-convert.sh cleanup [--deep]`, the REAL script.
#
# The dispatcher shifted the command word twice: `cleanup --deep` (what the
# apply runner calls when the legacy root is too full to shrink) lost its
# --deep and never did the deep part, and a bare `cleanup` died under dash on
# "can't shift that many" before freeing anything. Both calls are `|| true`
# in the runner, so nothing ever said so. The runner's own test stubs this
# script out; this one runs it, under dash like the appliance does.
# Further down: `finish` on a device that stays legacy (stale conversion entry,
# boot-package hold) and `restore-selector`'s marker.
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

# ── `finish` on a device that stays legacy, and `restore-selector` ─────────
# `prepare` holds the boot packages and turns the apt timers off; nothing ever
# undid that, and a conversion boot that did not convert left its one-shot
# GRUB entry behind, which hifi-ab-image.sh took as "already armed" for ever.
# Real rm here (the files live under $T); the machine-touching commands are
# stand-ins again, and every path the script writes is redirected under $T.
F="$T/f"
mkdir -p "$F/bin" "$F/local" "$F/grub.d" "$F/boot/grub" "$F/esp"
cat > "$F/lib.sh" <<'LIB'
AB_ESP_DIR="$HIFI_TEST_F/esp"
AB_STUB="$HIFI_TEST_F/esp/grub.cfg"
AB_ENABLED="$HIFI_TEST_F/esp/ab-enabled"
ab_log()  { printf 'I: %s\n' "$*" >> "$HIFI_TEST_CALLS"; }
ab_warn() { printf 'W: %s\n' "$*" >> "$HIFI_TEST_CALLS"; }
ab_is_image() { return 1; }
ab_mount_esp() { return 0; }
ab_part_by_name() { [ "${HIFI_TEST_LAYOUT:-0}" = 1 ]; }
ab_state_get() { cat "$HIFI_TEST_F/state" 2>/dev/null || echo none; }
ab_state_set() { printf '%s\n' "$1" > "$HIFI_TEST_F/state"; }
ab_write_atomic() { cat > /dev/null; echo "rewrite $1" >> "$HIFI_TEST_CALLS"; }
LIB
# dpkg-query answers "hold" for the packages listed in $F/held
cat > "$F/bin/dpkg-query" <<'STUB'
#!/bin/sh
shift 2   # -W -f=...
for p in "$@"; do
    if grep -qx "$p" "$HIFI_TEST_F/held" 2>/dev/null; then echo "hold $p"; else echo "install $p"; fi
done
STUB
cat > "$F/bin/apt-mark" <<'STUB'
#!/bin/sh
echo "apt-mark $*" >> "$HIFI_TEST_CALLS"
[ "$1" = unhold ] && : > "$HIFI_TEST_F/held"
exit 0
STUB
cat > "$F/bin/systemctl" <<'STUB'
#!/bin/sh
case "$1" in
    is-enabled) cat "$HIFI_TEST_F/timers" 2>/dev/null || echo enabled ;;
    *) echo "systemctl $*" >> "$HIFI_TEST_CALLS" ;;
esac
exit 0
STUB
for c in update-grub grub-editenv; do
    # shellcheck disable=SC2016  # expanded by the stub, not here
    printf '#!/bin/sh\necho "%s $*" >> "$HIFI_TEST_CALLS"\nexit 0\n' "$c" > "$F/bin/$c"
done
cp "$T/bin/id" "$F/bin/id"
chmod +x "$F/bin/"*

frun() {
    : > "$CALLS"
    HIFI_AB_LIB="$F/lib.sh" HIFI_TEST_CALLS="$CALLS" HIFI_TEST_F="$F" \
    HIFI_AB_LOCAL="$F/local" HIFI_AB_GRUBD="$F/grub.d/45_hifi_abconvert" \
    HIFI_AB_CONV_INITRD="$F/boot/initrd.img-abconvert" \
    HIFI_AB_LEGACY_GRUBENV="$F/boot/grub/grubenv" \
    PATH="$F/bin:$PATH" "$SH" "$S" "$@" >/dev/null 2>&1
}
arm() {  # the leftovers of `prepare`, with the hold on
    : > "$F/grub.d/45_hifi_abconvert"; : > "$F/boot/initrd.img-abconvert"
    printf 'linux-image-amd64\ngrub-efi-amd64-signed\n' > "$F/held"
    echo disabled > "$F/timers"
}

# armed, its boot still to come: nothing is touched
arm; echo prepared > "$F/state"
printf '# GRUB Environment Block\nnext_entry=hifi-ab-convert\n' > "$F/boot/grub/grubenv"
frun finish
expect "pending conversion: finish completes" "$?" 0
expect "...the entry stays" "$([ -f "$F/grub.d/45_hifi_abconvert" ] && echo yes || echo no)" yes
expect "...the hold stays" "$(grep -c '^apt-mark' "$CALLS")" 0

# the conversion boot came and the initrd bailed out
printf '# GRUB Environment Block\n' > "$F/boot/grub/grubenv"
echo failed > "$F/state"
frun finish
expect "failed conversion: finish completes" "$?" 0
expect "...the entry is gone" "$([ -f "$F/grub.d/45_hifi_abconvert" ] && echo yes || echo no)" no
expect "...the conversion initrd is gone" "$([ -f "$F/boot/initrd.img-abconvert" ] && echo yes || echo no)" no
expect "...grub.cfg is regenerated" "$(grep -c '^update-grub' "$CALLS")" 1
expect "...only the held packages are released" "$(grep '^apt-mark' "$CALLS")" "apt-mark unhold linux-image-amd64 grub-efi-amd64-signed"
expect "...the apt timers are back on" "$(grep -c '^systemctl enable --now --no-block apt-daily' "$CALLS")" 2
expect "...the failure is counted" "$(cat "$F/local/convert-failures" 2>/dev/null)" 1
expect "...the initrd's own outcome is kept" "$(cat "$F/state")" failed

# the initrd could not even write its outcome: still "prepared" on the ESP
arm; echo prepared > "$F/state"
frun finish
expect "silent failure: the state says so" "$(cat "$F/state")" failed
expect "...and it is counted too" "$(cat "$F/local/convert-failures" 2>/dev/null)" 2

# every later legacy boot: nothing held, nothing to do
frun finish
expect "nothing left: no apt-mark" "$(grep -c '^apt-mark' "$CALLS")" 0
expect "...no update-grub" "$(grep -c '^update-grub' "$CALLS")" 0
expect "...the count stays" "$(cat "$F/local/convert-failures" 2>/dev/null)" 2

# timers an owner switched off on a device holding nothing stay off
echo disabled > "$F/timers"; : > "$F/held"
frun finish
expect "never prepared: the timers are left alone" "$(grep -c '^systemctl enable' "$CALLS")" 0
echo enabled > "$F/timers"

# the selector on the ESP: the template's marker is "A/B boot selector"
: > "$F/esp/ab-enabled"; : > "$F/local/selector.cfg"
printf '# Osmium Sound — A/B boot selector (version 2).\n' > "$F/esp/grub.cfg"
frun restore-selector
expect "today's selector is left alone" "$(grep -c '^rewrite' "$CALLS")" 0
printf '# Osmium Sound — selettore di avvio A/B\n' > "$F/esp/grub.cfg"
frun restore-selector
expect "an older Italian one too" "$(grep -c '^rewrite' "$CALLS")" 0
# shellcheck disable=SC2016  # GRUB's $root, written as is
printf 'search.fs_uuid 1234 root\nconfigfile ($root)/boot/grub/grub.cfg\n' > "$F/esp/grub.cfg"
frun restore-selector
expect "the stub grub-install writes is replaced" "$(grep -c '^rewrite' "$CALLS")" 1

echo "test-ab-convert-cleanup: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
