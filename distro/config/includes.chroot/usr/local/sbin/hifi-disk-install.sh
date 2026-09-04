#!/bin/sh
# HiFi Player — install the running live system onto a physical disk.
#
# Called by api_server.py via systemd-run (same detached-worker + /run
# status-file shape as hifi-format-disk.sh):
#   hifi-disk-install.sh <device>
#
# This is the disk-install backend for the installer UI on screen — Qt
# (native-ui-qt/qml/Wizard.qml, mode 2) or Electron
# (src/pages/InstallWizard.jsx) — which replaces Debian Installer entirely —
# see distro/README.md. It:
#   1. partitions the target disk (GPT: 1MiB bios_grub + 512MiB EFI + rest
#      ext4 — same geometry the old d-i preseed used),
#   2. unsquashfs's the live filesystem straight from the boot medium's
#      squashfs image onto the target (NOT a copy of the running live
#      session — that would drag in live-session runtime state; the squashfs
#      image itself is the pristine chroot built by build-distro.sh),
#   3. writes fstab + a fresh machine-id,
#   4. chroots in and runs hifi-grub-install.sh + hifi-finalize-boot.sh
#      (both unchanged — they already work from "derive target disk from the
#      mounted root", which is exactly what the chroot gives them).
#
# TWO LAYOUTS. When the boot medium carries a system image
# (<medium>/osmium/rootfs.squashfs) and the machine boots UEFI, the installer
# writes the A/B layout instead: five partitions, the image copied block for
# block into slot A, /data formatted and seeded, and the A/B boot selector and
# grubenv written on the ESP. Nothing is downloaded — the appliance is an image
# system from its very first boot, with no conversion round to go through. When
# the image is not on the medium (or the firmware is BIOS) the historical
# single-root install below runs unchanged.
set -eu

# shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-log.sh
. /usr/local/sbin/hifi-log.sh
hifi_log_init hifi-disk-install

DEVICE="${1:-}"
STATUS="/run/hifi-install-status.json"
TARGET="/mnt/hifi-install"
UNSQUASHFS_LOG="/run/hifi-install-unsquashfs.log"

write_status() {
    state="$1"; progress="$2"; msg="$3"
    esc_msg=$(printf '%s' "$msg" | sed 's/\\/\\\\/g; s/"/\\"/g')
    printf '{"state":"%s","progress":%s,"message":"%s"}\n' \
        "$state" "$progress" "$esc_msg" > "$STATUS"
}

fail() {
    write_status error 0 "$1"
    echo "E: [hifi-install] $1" >&2
    exit 1
}

cleanup() {
    umount -R "$TARGET/boot/efi" 2>/dev/null || true
    umount -R "$TARGET/dev" 2>/dev/null || true
    umount -R "$TARGET/proc" 2>/dev/null || true
    umount -R "$TARGET/sys" 2>/dev/null || true
    umount -R "$TARGET" 2>/dev/null || true
}
trap cleanup EXIT

[ -n "$DEVICE" ] || fail "device missing"
[ -b "$DEVICE" ] || fail "not a block device: $DEVICE"
[ "$(lsblk -no TYPE "$DEVICE" 2>/dev/null | head -n1)" = "disk" ] \
    || fail "not a whole disk: $DEVICE"

# Refuse to touch the disk backing the live boot medium itself.
MEDIUM_SRC=""
for mp in /run/live/medium /lib/live/mount/medium; do
    MEDIUM_SRC=$(findmnt -no SOURCE "$mp" 2>/dev/null || true)
    [ -n "$MEDIUM_SRC" ] && break
done
if [ -n "$MEDIUM_SRC" ]; then
    MEDIUM_DISK=$(lsblk -no PKNAME "$MEDIUM_SRC" 2>/dev/null | head -n1)
    [ -n "$MEDIUM_DISK" ] && [ "/dev/$MEDIUM_DISK" = "$DEVICE" ] \
        && fail "refusing to install onto the boot medium itself: $DEVICE"
fi

write_status running 2 "Preparing…"
log() { echo "I: [hifi-install] $*"; }

# ─────────────────────────── A/B layout, when the medium carries one ────
AB_IMAGE=""
for base in /run/live/medium /lib/live/mount/medium; do
    [ -f "$base/osmium/rootfs.squashfs" ] && AB_IMAGE="$base/osmium/rootfs.squashfs" && break
done

# Copies <file> to <block device> with dd, reporting real progress: the UI must
# not sit still for the ~900 MB this takes on a slow USB stick.
dd_with_progress() {  # <src> <dst> <total bytes> <progress lo> <progress hi>
    _src=$1; _dst=$2; _tot=$3; _lo=$4; _hi=$5
    _log=/run/hifi-install-dd.log
    : > "$_log"
    dd if="$_src" of="$_dst" bs=4M conv=fsync status=progress 2>"$_log" &
    _pid=$!
    while kill -0 "$_pid" 2>/dev/null; do
        _done=$(tr '\r' '\n' < "$_log" | sed -n 's/^\([0-9]\{1,\}\) bytes.*/\1/p' | tail -n 1)
        if [ -n "$_done" ] && [ "$_tot" -gt 0 ]; then
            _pct=$(( _done * 100 / _tot ))
            write_status running $(( _lo + _pct * (_hi - _lo) / 100 )) "Writing the system image… ${_pct}%"
        fi
        sleep 1
    done
    wait "$_pid" || fail "writing the system image failed — see $_log"
}

install_ab() {
    # shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-ab-lib.sh
    # shellcheck disable=SC1091
    . /usr/local/sbin/hifi-ab-lib.sh

    _img_bytes=$(stat -c %s "$AB_IMAGE" 2>/dev/null || echo 0)
    [ "$_img_bytes" -gt 0 ] || fail "the system image on the boot medium is empty"
    _slot_bytes=$(( AB_SLOT_B_MIB * 1048576 ))
    [ "$_img_bytes" -le "$_slot_bytes" ] \
        || fail "the system image ($(( _img_bytes / 1048576 )) MiB) does not fit a ${AB_SLOT_B_MIB} MiB slot"
    _disk_mib=$(( $(blockdev --getsize64 "$DEVICE" 2>/dev/null || echo 0) / 1048576 ))
    _need=$(( AB_HEAD_MIB + AB_SLOT_B_MIB * 2 + AB_DATA_MIN_MIB ))
    [ "$_disk_mib" -ge "$_need" ] \
        || fail "disk of ${_disk_mib} MiB: this layout needs at least ${_need} MiB (8 GB)"

    # Read the image before writing it: a truncated download or a bad stick is
    # better caught here than three minutes into a boot that never comes.
    if [ -f "$AB_IMAGE.sha256" ]; then
        write_status running 4 "Checking the system image…"
        ( cd "$(dirname "$AB_IMAGE")" && sha256sum -c --status "$(basename "$AB_IMAGE").sha256" ) \
            || fail "the system image on the boot medium is damaged (checksum mismatch)"
    fi
    mkdir -p /run/hifi-img
    umount /run/hifi-img 2>/dev/null || true
    mount -o loop,ro "$AB_IMAGE" /run/hifi-img 2>/dev/null \
        || fail "the system image on the boot medium cannot be opened"
    _img_ver=$(head -n 1 /run/hifi-img/usr/lib/osmium/IMAGE_VERSION 2>/dev/null || true)
    [ -n "$_img_ver" ] || { umount /run/hifi-img; fail "the file on the medium is not an Osmium system image"; }
    log "A/B install: image $_img_ver ($(( _img_bytes / 1048576 )) MiB) onto $DEVICE (${_disk_mib} MiB)"

    write_status running 6 "Removing old signatures…"
    for part in $(lsblk -no PATH "$DEVICE" 2>/dev/null | grep -v "^${DEVICE}$"); do
        mp=$(lsblk -no MOUNTPOINT "$part" 2>/dev/null | head -n1)
        [ -n "$mp" ] && umount -l "$part" 2>/dev/null || true
        swapoff "$part" 2>/dev/null || true
        wipefs -a "$part" >/dev/null 2>&1 || true
    done
    wipefs -a "$DEVICE" >/dev/null 2>&1 || true
    sync

    write_status running 10 "Creating partition table…"
    _bios="21686148-6449-6E6F-744E-656564454649"
    _efi="C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
    _lin="0FC63DAF-8483-4772-8E79-3D69D8477DE4"
    # The names are how everything else finds these partitions afterwards
    # (hifi-ab-lib.sh looks them up by PARTLABEL), so they are not decoration.
    _err=$(printf 'label: gpt\nsize=1MiB, type=%s, name="BIOS boot"\nsize=512MiB, type=%s, name="EFI System"\nsize=%sMiB, type=%s, name="hifi-root-a"\nsize=%sMiB, type=%s, name="hifi-root-b"\ntype=%s, name="hifi-data"\n' \
            "$_bios" "$_efi" "$AB_SLOT_B_MIB" "$_lin" "$AB_SLOT_B_MIB" "$_lin" "$_lin" \
            | sfdisk --wipe always --quiet "$DEVICE" 2>&1) \
        || { umount /run/hifi-img 2>/dev/null; fail "partitioning failed: $(printf '%s' "$_err" | tr '\n' ' ' | cut -c1-200)"; }
    blockdev --rereadpt "$DEVICE" 2>/dev/null || true
    udevadm settle --timeout=10 2>/dev/null || true
    sync
    _i=0
    while [ "$_i" -lt 10 ]; do
        PARTS=$(lsblk -no PATH "$DEVICE" 2>/dev/null | grep -v "^${DEVICE}$" || true)
        [ "$(printf '%s\n' "$PARTS" | grep -c .)" -ge 5 ] && break
        _i=$((_i + 1)); sleep 1
    done
    P2=$(printf '%s\n' "$PARTS" | sed -n '2p')
    P3=$(printf '%s\n' "$PARTS" | sed -n '3p')
    P4=$(printf '%s\n' "$PARTS" | sed -n '4p')
    P5=$(printf '%s\n' "$PARTS" | sed -n '5p')
    [ -n "$P2" ] && [ -n "$P3" ] && [ -n "$P4" ] && [ -n "$P5" ] \
        || { umount /run/hifi-img 2>/dev/null; fail "partitions not found after partitioning"; }

    write_status running 14 "Formatting…"
    mkfs.vfat -F32 -n EFI "$P2" >/dev/null 2>&1 || fail "mkfs.vfat (EFI) failed on $P2"
    # -m 1: the default 5% reserved would be MiB thrown away on a data partition
    mkfs.ext4 -F -q -m 1 -L hifi-data -O metadata_csum_seed "$P5" >/dev/null 2>&1 \
        || fail "mkfs.ext4 failed on $P5 (data partition)"
    sync

    # Slot A gets the image; slot B stays empty until the first update — the
    # selector never tries it (B_OK=0), so an empty partition is correct here.
    dd_with_progress "$AB_IMAGE" "$P3" "$_img_bytes" 20 70

    write_status running 74 "Preparing the data partition…"
    _d=/mnt/hifi-data
    mkdir -p "$_d"; umount "$_d" 2>/dev/null || true
    mount "$P5" "$_d" || fail "mount of the data partition failed ($P5)"
    mkdir -p "$_d/etc/upper" "$_d/etc/work" "$_d/var" "$_d/home" "$_d/lyrion" "$_d/rauc"
    chmod 0755 "$_d/etc" "$_d/var" "$_d/home"
    # machine-id, generated here rather than at first boot, because the unique
    # squeezelite MAC below is derived from it — every unit installed from the
    # same medium must not end up sharing a player identity on LMS.
    _mid=$(systemd-id128 new 2>/dev/null || cat /proc/sys/kernel/random/uuid | tr -d '-')
    printf '%s\n' "$_mid" > "$_d/etc/upper/machine-id"
    if [ -f /run/hifi-img/etc/default/squeezelite ]; then
        mkdir -p "$_d/etc/upper/default"
        _mac_hash=$(printf '%s' "$_mid" | md5sum | cut -c1-12)
        _mac=$(printf '02%s' "${_mac_hash#??}" | sed 's/\(..\)/\1:/g; s/:$//')
        sed "s/^ARGS=\(['\"]\)\(.*\)\1\$/ARGS=\1-m $_mac \2\1/" \
            /run/hifi-img/etc/default/squeezelite > "$_d/etc/upper/default/squeezelite"
    fi
    sync
    umount "$_d" 2>/dev/null || true
    umount /run/hifi-img 2>/dev/null || true

    write_status running 82 "Installing bootloader…"
    _esp=/mnt/hifi-esp
    mkdir -p "$_esp"; umount "$_esp" 2>/dev/null || true
    mount "$P2" "$_esp" || fail "mount of the EFI partition failed ($P2)"
    # Straight from the live system: same Debian packages as the image, and
    # nothing here needs a chroot — the slot is a read-only squashfs and the
    # boot menu of each slot ships inside it, so there is no update-grub to run.
    _gb=/run/hifi-grub-boot; rm -rf "$_gb"; mkdir -p "$_gb"
    grub-install --target=x86_64-efi --efi-directory="$_esp" --boot-directory="$_gb" \
        --bootloader-id=debian --recheck >>"$UNSQUASHFS_LOG" 2>&1 \
        || fail "grub-install (UEFI) failed — see $UNSQUASHFS_LOG"
    # Fallback removable path: some firmwares lose NVRAM entries
    grub-install --target=x86_64-efi --efi-directory="$_esp" --boot-directory="$_gb" \
        --bootloader-id=debian --recheck --removable >>"$UNSQUASHFS_LOG" 2>&1 \
        || log "WARNING: the removable-media fallback install failed (non-fatal)"
    [ -e "$_esp/EFI/debian/grubx64.efi" ] || [ -e "$_esp/EFI/debian/shimx64.efi" ] \
        || fail "grub-install wrote no boot files under EFI/debian"

    write_status running 92 "Writing the A/B boot selector…"
    _sel=/run/hifi-selector.cfg
    # No legacy root on a fresh install: the last branch of the selector points
    # at a UUID that cannot exist, so it falls through to its own reboot rather
    # than leaving a headless appliance sitting at a GRUB prompt.
    ab_render /usr/local/share/hifi-ab/grub-selector.cfg.tmpl \
        "LEGACY_UUID=00000000-0000-0000-0000-000000000000" > "$_sel" \
        || fail "rendering the boot selector failed"
    if command -v grub-script-check >/dev/null 2>&1; then
        grub-script-check "$_sel" || fail "the rendered boot selector is not valid GRUB script"
    fi
    grub-editenv "$_esp/EFI/debian/grubenv" create \
        || fail "could not create the GRUB environment on the ESP"
    grub-editenv "$_esp/EFI/debian/grubenv" set ORDER="A B" A_OK=1 A_TRY=0 B_OK=0 B_TRY=0 \
        || fail "could not initialise the GRUB environment"
    cp -f "$_sel" "$_esp/EFI/debian/grub.cfg" || fail "could not write the boot selector"
    [ -d "$_esp/EFI/BOOT" ] && cp -f "$_sel" "$_esp/EFI/BOOT/grub.cfg" 2>/dev/null || true
    : > "$_esp/EFI/debian/ab-enabled"
    sync
    umount "$_esp" 2>/dev/null || true

    write_status "done" 100 "Installation complete"
    log "A/B install done: slot A holds $_img_ver, slot B empty, data on $P5"
    exit 0
}

if [ -n "$AB_IMAGE" ] && [ -d /sys/firmware/efi ]; then
    install_ab
fi
[ -z "$AB_IMAGE" ] || log "system image present but the firmware is BIOS: installing the single-root layout"

# ─────────────────────────── locate the squashfs source ────────────
SQUASHFS=""
for base in /run/live/medium /lib/live/mount/medium; do
    [ -f "$base/live/filesystem.squashfs" ] && SQUASHFS="$base/live/filesystem.squashfs" && break
done
if [ -z "$SQUASHFS" ]; then
    SQUASHFS=$(find /run/live /lib/live/mount -maxdepth 4 -name '*.squashfs' 2>/dev/null | head -n1 || true)
fi
[ -n "$SQUASHFS" ] && [ -f "$SQUASHFS" ] || fail "could not locate the live filesystem.squashfs on the boot medium"
log "squashfs source: $SQUASHFS"

# ─────────────────────────── partition + format ─────────────────────
write_status running 5 "Removing old signatures…"
for part in $(lsblk -no PATH "$DEVICE" 2>/dev/null | grep -v "^${DEVICE}$"); do
    mp=$(lsblk -no MOUNTPOINT "$part" 2>/dev/null | head -n1)
    [ -n "$mp" ] && umount -l "$part" 2>/dev/null || true
    swapoff "$part" 2>/dev/null || true
    wipefs -a "$part" >/dev/null 2>&1 || true
done
wipefs -a "$DEVICE" >/dev/null 2>&1 || true
sync

write_status running 10 "Creating partition table…"
BIOSGRUB_TYPE="21686148-6449-6E6F-744E-656564454649"
EFI_TYPE="C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
LINUX_TYPE="0FC63DAF-8483-4772-8E79-3D69D8477DE4"
SFDISK_ERR=$(printf 'label: gpt\nsize=1MiB, type=%s, name="BIOS boot"\nsize=512MiB, type=%s, name="EFI System"\ntype=%s, name="Linux filesystem"\n' \
        "$BIOSGRUB_TYPE" "$EFI_TYPE" "$LINUX_TYPE" \
        | sfdisk --wipe always --quiet "$DEVICE" 2>&1) \
    || fail "partitioning failed: $(printf '%s' "$SFDISK_ERR" | tr '\n' ' ' | cut -c1-200)"
blockdev --rereadpt "$DEVICE" 2>/dev/null || true
udevadm settle --timeout=10 2>/dev/null || true
sync

# Wait for udev to create the 3 partition nodes, then take them in order.
i=0
while [ "$i" -lt 10 ]; do
    PARTS=$(lsblk -no PATH "$DEVICE" 2>/dev/null | grep -v "^${DEVICE}$" || true)
    [ "$(printf '%s\n' "$PARTS" | grep -c .)" -ge 3 ] && break
    i=$((i + 1))
    sleep 1
done
P1=$(printf '%s\n' "$PARTS" | sed -n '1p')  # bios_grub
P2=$(printf '%s\n' "$PARTS" | sed -n '2p')  # EFI
P3=$(printf '%s\n' "$PARTS" | sed -n '3p')  # root
[ -n "$P1" ] && [ -n "$P2" ] && [ -n "$P3" ] || fail "partitions not found after partitioning"

write_status running 20 "Formatting…"
mkfs.vfat -F32 -n EFI "$P2" >/dev/null 2>&1 || fail "mkfs.vfat (EFI) failed on $P2"
mkfs.ext4 -F -L hifi-root "$P3" >/dev/null 2>&1 || fail "mkfs.ext4 failed on $P3"
sync

# ─────────────────────────── mount target ────────────────────────────
mkdir -p "$TARGET"
mount "$P3" "$TARGET" || fail "mount root failed ($P3)"
mkdir -p "$TARGET/boot/efi"
mount "$P2" "$TARGET/boot/efi" || fail "mount EFI failed ($P2)"

# ─────────────────────────── copy the system ─────────────────────────
write_status running 30 "Copying the system…"
: > "$UNSQUASHFS_LOG"
unsquashfs -f -d "$TARGET" "$SQUASHFS" >"$UNSQUASHFS_LOG" 2>&1 &
US_PID=$!
while kill -0 "$US_PID" 2>/dev/null; do
    PCT=$(grep -o '[0-9]\{1,3\}%' "$UNSQUASHFS_LOG" 2>/dev/null | tail -1 | tr -d '%')
    if [ -n "$PCT" ]; then
        SCALED=$((30 + PCT * 50 / 100))
        write_status running "$SCALED" "Copying the system… $PCT%"
    fi
    sleep 1
done
wait "$US_PID"
US_STATUS=$?
[ "$US_STATUS" -eq 0 ] || fail "copying the system failed (unsquashfs exit $US_STATUS) — see $UNSQUASHFS_LOG"

write_status running 82 "Configuring the system…"

# ─────────────────────────── fstab ────────────────────────────────────
ROOT_UUID=$(blkid -s UUID -o value "$P3")
EFI_UUID=$(blkid -s UUID -o value "$P2")
[ -n "$ROOT_UUID" ] && [ -n "$EFI_UUID" ] || fail "could not read the UUIDs of the created partitions"
cat > "$TARGET/etc/fstab" <<EOF
# /etc/fstab — generated by hifi-disk-install.sh at install time
UUID=$ROOT_UUID  /          ext4  errors=remount-ro  0  1
UUID=$EFI_UUID   /boot/efi  vfat  umask=0077          0  1
EOF

# Fresh machine-id: unsquashfs cloned the live image's own (or absent) one,
# and every unit installed from the same ISO must not share an identity.
rm -f "$TARGET/etc/machine-id" "$TARGET/var/lib/dbus/machine-id" 2>/dev/null || true

# ─────────────────────────── bootloader ───────────────────────────────
write_status running 88 "Installing bootloader…"
for fs in dev proc sys; do
    # --rbind, not --bind: a plain bind of /sys does NOT carry through the
    # efivarfs mounted at /sys/firmware/efi/efivars (a separate mount nested
    # inside sysfs), so the chroot would see an empty efivars dir. That's
    # enough for the "[ -d /sys/firmware/efi ]" UEFI detection in
    # hifi-grub-install.sh to pass, but not enough for dpkg-reconfigure
    # grub-efi-amd64-signed to actually write the signed boot chain — it
    # reports success while writing nothing. --rbind carries every nested
    # mount (efivars, devpts, ...) through instead.
    mount --rbind "/$fs" "$TARGET/$fs" || fail "bind mount /$fs failed"
done

chroot "$TARGET" /bin/sh -c 'systemd-machine-id-setup' >/dev/null 2>&1 || true

# Persistent, unique squeezelite player MAC (-m) — same fix as OTA migration
# 0042-squeezelite-persistent-mac.sh: without it, squeezelite (talking to LMS
# over -s 127.0.0.1, so it doesn't always see a real network MAC) can fall
# back to a non-unique placeholder that collides with other LMS players.
# Assign it here too so a fresh install never boots even once without one —
# derived from the machine-id this script just regenerated above, so it's
# already unique and won't collide with any other unit from the same ISO.
SQ_DEFAULT_INSTALL="$TARGET/etc/default/squeezelite"
# The -m test accepts the opening quote as a boundary because the sed below
# prepends (ARGS='-m .. -o ..') — see 0042 for the duplicate-flag bug that a
# plain (^|[[:space:]])-m caused there.
if [ -f "$SQ_DEFAULT_INSTALL" ] && grep -q '^ARGS=' "$SQ_DEFAULT_INSTALL" 2>/dev/null \
   && ! grep '^ARGS=' "$SQ_DEFAULT_INSTALL" | grep -qE "(^ARGS=['\"]|[[:space:]])-m[[:space:]]"; then
    INSTALL_MAC_SEED="$(cat "$TARGET/etc/machine-id" 2>/dev/null || true)"
    [ -n "$INSTALL_MAC_SEED" ] || INSTALL_MAC_SEED="hifi-install-fallback-$$"
    INSTALL_MAC_HASH="$(printf '%s' "$INSTALL_MAC_SEED" | md5sum | cut -c1-12)"
    INSTALL_MAC_RAW="02${INSTALL_MAC_HASH#??}"
    INSTALL_MAC="$(printf '%s' "$INSTALL_MAC_RAW" | sed 's/\(..\)/\1:/g; s/:$//')"
    sed -i "s/^ARGS=\(['\"]\)\(.*\)\1\$/ARGS=\1-m $INSTALL_MAC \2\1/" "$SQ_DEFAULT_INSTALL" || true
fi

# Log INSIDE the target (not the outer live session's own /var/log/hifi/,
# which is what a plain ">>/var/log/hifi/..." redirect here would hit — the
# redirect is opened by THIS shell, running on the live root, before chroot
# ever switches the child process's filesystem view). Writing into $TARGET
# means these logs survive onto the installed disk and are readable after
# reboot, instead of vanishing with the ephemeral live session.
mkdir -p "$TARGET/var/log/hifi"
if ! chroot "$TARGET" /bin/sh /usr/local/sbin/hifi-grub-install.sh >>"$TARGET/var/log/hifi/hifi-install-grub.log" 2>&1; then
    fail "bootloader installation failed — see /var/log/hifi/hifi-install-grub.log on the installed disk"
fi
chroot "$TARGET" /bin/sh /usr/local/sbin/hifi-finalize-boot.sh >>"$TARGET/var/log/hifi/hifi-install-finalize-boot.log" 2>&1 || true

write_status "done" 100 "Installation complete"
log "done"
