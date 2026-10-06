#!/bin/bash
# Osmium Sound — marking an A/B boot good, and the watchdog that falls back.
#
# With RAUC's GRUB scheme every boot is a trial (the selector sets <slot>_TRY=1,
# `rauc status mark-good` clears it). The health check used to give up after
# 300 s and the watchdog rebooted any slot still on trial at 10 minutes, so a
# single slow boot of an image that had been running fine for months sent
# the device back to the older image, for good. What must hold now:
#  - the health check keeps trying, and once good records the image as proven;
#  - the watchdog never reboots a proven image, waits while a first boot is
#    still busy (bounded), and still reboots a new image that never comes up;
#  - on the fallback slot, a proven image in the other slot gets its next
#    try back (bounded), a new one does not.
#
# Hermetic: the real scripts and the real hifi-ab-lib.sh, with its paths
# pointed into a temp dir (HIFI_AB_LIB) and stand-ins on PATH for
# grub-editenv, rauc, curl, systemctl, mount and friends.
set -u
SB="$PWD/distro/config/includes.chroot/usr/local/sbin"
pass=0; fail=0
ok()  { pass=$((pass+1)); }
bad() { fail=$((fail+1)); echo "FAIL: $1"; }
expect() { if [ "$2" = "$3" ]; then ok; else bad "$1: expected '$3', got '$2'"; fi; }

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/root/boot/grub" "$T/slots"
CALLS="$T/calls"

cat > "$T/lib.sh" <<LIB
. "$SB/hifi-ab-lib.sh"
AB_GRUBENV="$T/grubenv"
AB_RAUC_CONF="$T/system.conf"
AB_IMAGE_ID_FILE="/boot/grub/osmium-id.env"
ab_booted_slot() { echo "\$HIFI_TEST_SLOT"; }
ab_is_image() { return 1; }
ab_mount_esp() { return 0; }
ab_image_id() { sed -n 's/^OSMIUM_ID=//p' "\${1:-$T/root}\$AB_IMAGE_ID_FILE" 2>/dev/null | head -n 1; }
LIB

# grub-editenv on a plain KEY=VALUE file: list and set are all that is used.
cat > "$T/bin/grub-editenv" <<'EOF'
#!/bin/sh
f=$1; shift
case "$1" in
    list) cat "$f" ;;
    set) shift
         for kv in "$@"; do
             k=${kv%%=*}
             grep -v "^$k=" "$f" > "$f.n" 2>/dev/null; echo "$kv" >> "$f.n"; mv "$f.n" "$f"
         done
         echo "editenv $*" >> "$HIFI_TEST_CALLS" ;;
esac
EOF
# curl answers once HIFI_TEST_API_AFTER calls have been made.
cat > "$T/bin/curl" <<'EOF'
#!/bin/sh
n=$(cat "$HIFI_TEST_DIR/curl.n" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$HIFI_TEST_DIR/curl.n"
[ "$n" -gt "${HIFI_TEST_API_AFTER:-0}" ]
EOF
cat > "$T/bin/rauc" <<'EOF'
#!/bin/sh
echo "rauc $*" >> "$HIFI_TEST_CALLS"
if [ "$*" = "status mark-good" ]; then
    f=$HIFI_TEST_DIR/grubenv; s=$HIFI_TEST_SLOT
    grep -v "^${s}_OK=\|^${s}_TRY=" "$f" > "$f.n"; printf '%s_OK=1\n%s_TRY=0\n' "$s" "$s" >> "$f.n"; mv "$f.n" "$f"
fi
exit 0
EOF
cat > "$T/bin/systemctl" <<'EOF'
#!/bin/sh
case "$1" in
    list-jobs) cat "$HIFI_TEST_DIR/jobs" 2>/dev/null ;;
    *) echo "systemctl $*" >> "$HIFI_TEST_CALLS" ;;
esac
EOF
# mount -t squashfs -o ro <dev> <dir>: the slot's files from $T/slots/<dev name>
cat > "$T/bin/mount" <<'EOF'
#!/bin/sh
echo "mount $*" >> "$HIFI_TEST_CALLS"
src="$HIFI_TEST_DIR/slots/$(basename "$5")"
[ -d "$src" ] || exit 32
cp -a "$src/." "$6/"
EOF
cat > "$T/bin/umount" <<'EOF'
#!/bin/sh
rm -rf "${1:?}"/*
EOF
# sleep that does not: the uptime moves on instead, so a wait shows up in it
cat > "$T/bin/sleep" <<'EOF'
#!/bin/sh
u=$(cut -d. -f1 "$HIFI_TEST_DIR/uptime"); echo "$((u + $1)).00 0.00" > "$HIFI_TEST_DIR/uptime"
EOF
printf '#!/bin/sh\nexit 0\n' > "$T/bin/mountpoint"
printf '#!/bin/sh\n' > "$T/bin/sync"
chmod +x "$T/bin/"*

cat > "$T/system.conf" <<'EOF'
[system]
compatible=osmium-x86_64
[slot.rootfs.0]
device=/dev/fake3
type=raw
bootname=A
[slot.rootfs.1]
device=/dev/fake4
type=raw
bootname=B
EOF

id_of_root() { printf '# GRUB Environment Block\nOSMIUM_ID=%s\n' "$1" > "$T/root/boot/grub/osmium-id.env"; }
slot_image() {  # <dev name> <id>: what the other slot holds
    rm -rf "$T/slots/$1"; mkdir -p "$T/slots/$1/boot/grub"
    printf '# GRUB Environment Block\nOSMIUM_ID=%s\n' "$2" > "$T/slots/$1/boot/grub/osmium-id.env"
}
env_is() { printf '%s\n' "$@" > "$T/grubenv"; }
env_get() { sed -n "s/^$1=//p" "$T/grubenv"; }

run() {  # <script> [VAR=value...]
    s=$1; shift
    : > "$CALLS"; rm -f "$T/curl.n" "$T/good"
    env HIFI_AB_LIB="$T/lib.sh" HIFI_TEST_DIR="$T" HIFI_TEST_CALLS="$CALLS" \
        HIFI_BOOT_GOOD_FLAG="$T/good" HIFI_AB_PEEK_DIR="$T/peek" HIFI_UPTIME_FILE="$T/uptime" \
        "$@" PATH="$T/bin:$PATH" sh "$SB/$s" >/dev/null 2>"$T/stderr"
}
echo "30.00 0.00" > "$T/uptime"
calls() { grep -c "$1" "$CALLS"; }

# ── health ───────────────────────────────────────────────────────────────
# 1. late, but it gets there: no giving up at the old 300 s
id_of_root img-2
env_is "ORDER=B A" A_OK=1 A_TRY=0 B_OK=1 B_TRY=1
run hifi-boot-health.sh HIFI_TEST_SLOT=B HIFI_TEST_API_AFTER=5 HIFI_BOOT_HEALTH_TIMEOUT=0
expect "a late boot is still marked good"        "$?" 0
expect "...with rauc"                            "$(calls 'rauc status mark-good')" 1
expect "...and says it was late"                 "$(grep -c 'still trying' "$T/stderr")" 1
expect "the image is recorded as proven"         "$(env_get B_GOOD)" img-2
expect "...with its attempts"                    "$(env_get B_LEFT)" 2

# 2. no id in the root (converted legacy root): nothing recorded
rm -f "$T/root/boot/grub/osmium-id.env"
env_is "ORDER=A B" A_OK=1 A_TRY=1 B_OK=0 B_TRY=0
run hifi-boot-health.sh HIFI_TEST_SLOT=A
expect "a root without an id records nothing"    "$(env_get A_GOOD)" ""

# 3. on the fallback, a proven image in the other slot gets its try back
id_of_root img-1
slot_image fake4 img-2
env_is "ORDER=B A" A_OK=1 A_TRY=1 B_OK=1 B_TRY=1 B_GOOD=img-2 B_LEFT=2
run hifi-boot-health.sh HIFI_TEST_SLOT=A
expect "proven B is re-armed"                    "$(env_get B_TRY)" 0
expect "...out of its attempts"                  "$(env_get B_LEFT)" 1
expect "...after looking into the slot itself"   "$(calls 'mount -t squashfs -o ro /dev/fake4')" 1
expect "...and A is proven too"                  "$(env_get A_GOOD)" img-1

# 4. ...but not once the attempts are used up
env_is "ORDER=B A" A_OK=1 A_TRY=1 B_OK=1 B_TRY=1 B_GOOD=img-2 B_LEFT=0
run hifi-boot-health.sh HIFI_TEST_SLOT=A
expect "no attempts left: B stays out"           "$(env_get B_TRY)" 1
expect "...and the log says so"                  "$(grep -c 'attempts used up' "$T/stderr")" 1

# 5. ...and never for a NEW image whose first boot failed (stale proof)
slot_image fake4 img-3
env_is "ORDER=B A" A_OK=1 A_TRY=1 B_OK=1 B_TRY=1 B_GOOD=img-2 B_LEFT=2
run hifi-boot-health.sh HIFI_TEST_SLOT=A
expect "a broken new image stays out"            "$(env_get B_TRY)" 1

# 6. not on the fallback (A is RAUC's primary): the other slot is left alone
slot_image fake4 img-2
env_is "ORDER=A B" A_OK=1 A_TRY=1 B_OK=1 B_TRY=1 B_GOOD=img-2 B_LEFT=2
run hifi-boot-health.sh HIFI_TEST_SLOT=A
expect "not a fallback: B untouched"             "$(env_get B_TRY)" 1
expect "...and not even looked at"               "$(calls 'mount ')" 0

# ── watchdog ─────────────────────────────────────────────────────────────
# 7. a new image that never came up: reboot (the protection that stays)
id_of_root img-3
env_is "ORDER=B A" A_OK=1 A_TRY=0 B_OK=1 B_TRY=1 B_GOOD=img-2 B_LEFT=2
: > "$T/jobs"; echo "600.00 0.00" > "$T/uptime"
run hifi-boot-watchdog.sh HIFI_TEST_SLOT=B
expect "a new image that is not good is rebooted" "$(calls 'systemctl reboot')" 1

# 8. a proven image on a slow boot: no reboot
id_of_root img-2
run hifi-boot-watchdog.sh HIFI_TEST_SLOT=B
expect "a proven image is not rebooted"          "$(calls 'systemctl reboot')" 0
expect "...and the log says why"                 "$(grep -c 'has been good before' "$T/stderr")" 1

# 9. good already: nothing
id_of_root img-3
: > "$T/already-good"
run hifi-boot-watchdog.sh HIFI_TEST_SLOT=B HIFI_BOOT_GOOD_FLAG="$T/already-good"
expect "a good boot is left alone"               "$(calls 'systemctl reboot')" 0

# 10. a new image still busy starting up: waits, then reboots at the cap
printf '42 hifi-migrate.service start running\n7 hifi-boot-health.service start running\n' > "$T/jobs"
echo "600.00 0.00" > "$T/uptime"
run hifi-boot-watchdog.sh HIFI_TEST_SLOT=B HIFI_BOOT_WATCHDOG_CAP=1800 HIFI_BOOT_WATCHDOG_POLL=30
expect "busy: waited until the cap"              "$(cut -d. -f1 "$T/uptime")" 1800
expect "...then rebooted all the same"           "$(calls 'systemctl reboot')" 1

# 11. only our own two units in the job list: that is not "busy"
printf '7 hifi-boot-health.service start running\n8 hifi-boot-watchdog.service start running\n' > "$T/jobs"
echo "600.00 0.00" > "$T/uptime"
run hifi-boot-watchdog.sh HIFI_TEST_SLOT=B
expect "health and watchdog alone are not busy"  "$(cut -d. -f1 "$T/uptime")" 600
expect "...so it reboots at once"                "$(calls 'systemctl reboot')" 1

# 12. not on trial (TRY=0): nothing
env_is "ORDER=B A" A_OK=1 A_TRY=0 B_OK=1 B_TRY=0
run hifi-boot-watchdog.sh HIFI_TEST_SLOT=B
expect "a slot not on trial is not rebooted"     "$(calls 'systemctl reboot')" 0

echo "test-boot-health: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
