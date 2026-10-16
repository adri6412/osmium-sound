#!/bin/bash
# Osmium Sound — the live session of the ISO gets its wizard and a /data,
# and an installed system never gets the marker back.
set -u
S="distro/config/includes.chroot/usr/local/sbin/hifi-live-state.sh"
U="distro/config/includes.chroot/etc/systemd/system/hifi-live-state.service"
H="distro/config/hooks/normal/0400-enable-services.hook.chroot"
pass=0; fail=0
ok()  { pass=$((pass+1)); }
bad() { fail=$((fail+1)); echo "FAIL: $1"; }
expect() { if [ "$2" = "$3" ]; then ok; else bad "$1: expected $3, got $2"; fi; }

[ -f "$S" ] || { echo "missing $S"; exit 1; }
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
printf 'boot=live components quiet splash hostname=hifiplayer noautologin\n' > "$T/cmdline-live"
printf 'boot=live components quiet hifi.installer=1\n'                       > "$T/cmdline-installer"
printf 'rauc.slot=A ro quiet splash\n'                                       > "$T/cmdline-installed"
printf 'quiet hifi.boot=live\n'                                              > "$T/cmdline-lookalike"
# Stand-ins: mountpoint answers from IS_MOUNTED, mount records its arguments.
# shellcheck disable=SC2016  # the $ are for the stand-ins, not for this shell
printf '#!/bin/sh\nexit "${IS_MOUNTED:-1}"\n' > "$T/fake-mountpoint"
# shellcheck disable=SC2016
printf '#!/bin/sh\necho "$@" >> "$HIFI_TEST_MOUNTS"\n' > "$T/fake-mount"
chmod +x "$T/fake-mountpoint" "$T/fake-mount"

run() {  # <cmdline file>
    rm -rf "${T:?}/etc" "${T:?}/data"; : > "$T/mounts"
    mkdir -p "$T/etc/hifi-player"
    HIFI_CMDLINE="$1" HIFI_CONFIG_DIR="$T/etc/hifi-player" HIFI_DATA="$T/data" \
    HIFI_MOUNTPOINT="$T/fake-mountpoint" HIFI_MOUNT="$T/fake-mount" \
    HIFI_TEST_MOUNTS="$T/mounts" \
        sh "$S" >/dev/null 2>&1
}
marker() { [ -f "$T/etc/hifi-player/provisioning-pending" ] && echo armed || echo absent; }
mounted() { grep -q "^-t tmpfs -o mode=0755 tmpfs $T/data\$" "$T/mounts" && echo tmpfs || echo none; }

run "$T/cmdline-live"
expect "Try: wizard"                 "$(marker)" armed
expect "Try: /data"                  "$(mounted)" tmpfs
expect "Try: marker content"         "$(cat "$T/etc/hifi-player/provisioning-pending")" pending

run "$T/cmdline-installer"
expect "Install: portal"             "$(marker)" armed
expect "Install: /data"              "$(mounted)" tmpfs

run "$T/cmdline-installed"
expect "installed: no marker"        "$(marker)" absent
expect "installed: /data untouched"  "$(mounted)" none

run "$T/cmdline-lookalike"
expect "hifi.boot=live is not boot=live" "$(marker)" absent

# /data already a mount point: nothing mounted over it.
rm -rf "${T:?}/etc" "${T:?}/data"; : > "$T/mounts"; mkdir -p "$T/etc/hifi-player"
IS_MOUNTED=0 HIFI_CMDLINE="$T/cmdline-live" HIFI_CONFIG_DIR="$T/etc/hifi-player" HIFI_DATA="$T/data" \
    HIFI_MOUNTPOINT="$T/fake-mountpoint" HIFI_MOUNT="$T/fake-mount" HIFI_TEST_MOUNTS="$T/mounts" \
    sh "$S" >/dev/null 2>&1
expect "/data already mounted"       "$(mounted)" none
expect "wizard all the same"         "$(marker)" armed

# Setup already finished (persistent live medium): the wizard stays away.
rm -rf "${T:?}/etc" "${T:?}/data"; : > "$T/mounts"; mkdir -p "$T/etc/hifi-player"
: > "$T/etc/hifi-player/webui.db"
HIFI_CMDLINE="$T/cmdline-live" HIFI_CONFIG_DIR="$T/etc/hifi-player" HIFI_DATA="$T/data" \
    HIFI_MOUNTPOINT="$T/fake-mountpoint" HIFI_MOUNT="$T/fake-mount" HIFI_TEST_MOUNTS="$T/mounts" \
    sh "$S" >/dev/null 2>&1
expect "account exists: no wizard"   "$(marker)" absent

# The unit: live only, before the services that read the marker or /data,
# and enabled in the image.
if grep -qx 'ConditionKernelCommandLine=boot=live' "$U"; then ok; else bad "unit not gated on boot=live"; fi
for s in hifi-api hifi-webui hifi-sources hifi-qt lyrionmusicserver; do
    if grep -q "^Before=.*\b$s\.service" "$U"; then ok; else bad "unit not ordered before $s"; fi
done
if grep -q 'systemctl enable hifi-live-state.service' "$H"; then ok; else bad "unit not enabled by $H"; fi

echo "live state: $pass ok, $fail failed"
[ "$fail" = 0 ]
