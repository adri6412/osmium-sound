#!/usr/bin/env bash
#
# build-usb-image.sh — a disk image to write straight onto a USB stick or a
# disk (Etcher, Rufus, Raspberry Pi Imager, dd), next to the installer ISO.
#
#   sudo ./build-usb-image.sh --rootfs hifi-image-v2.6.0.rootfs.squashfs \
#                             --out hifi-player-v2.6.0.img
#
# What comes out is what hifi-disk-install.sh writes onto a disk, already
# done: the same five-partition A/B layout, the system image in slot A, slot B
# empty, GRUB for UEFI (shim, removable path) and for legacy BIOS on the ESP,
# the A/B selector and its grubenv. Two differences only:
#   • the data partition is 16 MiB, unformatted, and named "hifi-data-grow":
#     at the first boot the initramfs (scripts/local-premount/hifi-data-grow)
#     stretches it to the end of whatever medium the image was written to,
#     formats it and renames it hifi-data;
#   • no firmware boot entry is registered (there is no firmware here to
#     register it with): the box boots through EFI/BOOT/BOOTX64.EFI, the path
#     every UEFI firmware looks at on a removable medium.
#
# The bootloader is installed by the image's own grub-install, run in a
# throwaway chroot on top of the slot just written — the very binaries the
# installer uses on the live system, so a disk made here and one installed
# from the ISO boot the same way.
#
# Needs root, losetup with partition scanning, sfdisk, and overlayfs. Works in
# a privileged container as well: missing /dev nodes for loop devices and
# their partitions are created by hand (udev does not run there).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB="$SCRIPT_DIR/config/includes.chroot/usr/local/sbin/hifi-ab-lib.sh"
ROOTFS=""
OUT=""
DATA_SEED_MIB=16

log() { printf '\033[1;36m[hifi-usb-image]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[hifi-usb-image ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --rootfs) ROOTFS="$2"; shift 2 ;;
        --out) OUT="$2"; shift 2 ;;
        -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "unknown argument: $1" ;;
    esac
done
[ "$(id -u)" -eq 0 ] || die "needs root"
[ -f "$ROOTFS" ] || die "--rootfs: no such file: $ROOTFS"
[ -n "$OUT" ] || die "--out missing"
# shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-ab-lib.sh
# shellcheck disable=SC1091  # sourced by path, checked on its own
. "$LIB"
for t in losetup sfdisk mount umount truncate; do
    command -v "$t" >/dev/null || die "$t missing on the build host"
done

img_bytes=$(stat -c %s "$ROOTFS")
[ "$img_bytes" -le $(( AB_SLOT_B_MIB * 1048576 )) ] \
    || die "the system image ($(( img_bytes / 1048576 )) MiB) does not fit a ${AB_SLOT_B_MIB} MiB slot"

WORK="$(mktemp -d "${IMAGE_WORK:-/var/tmp}/hifi-usb-image.XXXXXX")"
C="$WORK/chroot"
LOOP=""
cleanup() {
    set +e
    for m in "$C/mnt/esp" "$C/run" "$C/sys" "$C/proc" "$C/dev" "$C" "$WORK/rw" "$WORK/lower"; do
        mountpoint -q "$m" && umount -R "$m" 2>/dev/null
    done
    [ -n "$LOOP" ] && losetup -d "$LOOP" 2>/dev/null
    rm -rf "$WORK"
}
trap cleanup EXIT

# ── 1. the empty disk and its partition table ───────────────────────────
# 1 MiB of alignment in front (sfdisk's default first sector) and room for
# the backup GPT behind: the first boot moves that one to the real end.
total_mib=$(( 1 + AB_HEAD_MIB + AB_SLOT_B_MIB * 2 + DATA_SEED_MIB + 1 ))
log "disk image: ${total_mib} MiB (slots of ${AB_SLOT_B_MIB} MiB, system image $(( img_bytes / 1048576 )) MiB)"
rm -f "$OUT"
truncate -s "${total_mib}M" "$OUT"
_bios="21686148-6449-6E6F-744E-656564454649"
_efi="C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
_lin="0FC63DAF-8483-4772-8E79-3D69D8477DE4"
# Same table as hifi-disk-install.sh (install_ab), the last partition aside.
printf 'label: gpt\nsize=1MiB, type=%s, name="BIOS boot"\nsize=512MiB, type=%s, name="EFI System"\nsize=%sMiB, type=%s, name="hifi-root-a"\nsize=%sMiB, type=%s, name="hifi-root-b"\nsize=%sMiB, type=%s, name="hifi-data-grow"\n' \
    "$_bios" "$_efi" "$AB_SLOT_B_MIB" "$_lin" "$AB_SLOT_B_MIB" "$_lin" "$DATA_SEED_MIB" "$_lin" \
    | sfdisk --quiet "$OUT" || die "sfdisk failed"

# ── 2. attached as a loop device, partitions included ───────────────────
mknod_missing() {  # <sysfs dir of a block device>
    _n=$(basename "$1")
    [ -b "/dev/$_n" ] && return 0
    _mm=$(cat "$1/dev")
    mknod "/dev/$_n" b "${_mm%%:*}" "${_mm##*:}"
}
if ! LOOP=$(losetup --find --show --partscan "$OUT" 2>/dev/null); then
    # A container's /dev only holds the loop nodes that existed when it
    # started: make some more and try again.
    for i in $(seq 0 63); do
        [ -e "/dev/loop$i" ] || mknod "/dev/loop$i" b 7 "$i"
    done
    LOOP=$(losetup --find --show --partscan "$OUT") || die "no free loop device"
fi
ln=$(basename "$LOOP")
for i in $(seq 1 20); do
    [ -d "/sys/block/$ln/${ln}p5" ] && break
    partx -a "$LOOP" 2>/dev/null || true
    sleep 0.5
done
[ -d "/sys/block/$ln/${ln}p5" ] || die "the kernel did not pick up the partitions of $LOOP"
for p in /sys/block/"$ln"/"$ln"p*; do mknod_missing "$p"; done
log "attached as $LOOP"

# ── 3. slot A: the system image, block for block ────────────────────────
log "writing the system image into slot A"
dd if="$ROOTFS" of="${LOOP}p3" bs=4M conv=fsync status=none || die "writing slot A failed"
img_ver=""

# ── 4. a throwaway chroot of that very image, to run its grub-install ───
mkdir -p "$WORK/lower" "$WORK/rw" "$C"
mount -t squashfs -o ro "${LOOP}p3" "$WORK/lower" || die "slot A does not mount as squashfs"
img_ver=$(head -n 1 "$WORK/lower/usr/lib/osmium/IMAGE_VERSION" 2>/dev/null || true)
[ -n "$img_ver" ] || die "$ROOTFS is not an Osmium system image (no IMAGE_VERSION)"
mount -t tmpfs tmpfs "$WORK/rw"
mkdir -p "$WORK/rw/upper" "$WORK/rw/work"
mount -t overlay overlay -o "lowerdir=$WORK/lower,upperdir=$WORK/rw/upper,workdir=$WORK/rw/work" "$C" \
    || die "overlayfs mount failed"
mount --rbind /dev "$C/dev"; mount --make-rslave "$C/dev"
mount -t proc proc "$C/proc"
mount --rbind /sys "$C/sys"; mount --make-rslave "$C/sys"
mount -t tmpfs tmpfs "$C/run"
in_chroot() {
    chroot "$C" /usr/bin/env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
        LC_ALL=C.UTF-8 HOME=/root "$@"
}
log "image $img_ver"

# ── 5. the ESP: GRUB for UEFI and for BIOS, the A/B selector ────────────
# Kept in step with install_ab in hifi-disk-install.sh, step for step.
in_chroot mkfs.vfat -F32 -n EFI "${LOOP}p2" >/dev/null || die "mkfs.vfat failed"
mkdir -p "$C/mnt/esp"
mount -t vfat "${LOOP}p2" "$C/mnt/esp" || die "the ESP does not mount"
_grub_efi() {
    in_chroot grub-install --target=x86_64-efi --efi-directory=/mnt/esp \
        --boot-directory=/mnt/esp --bootloader-id=debian --recheck --no-nvram "$@"
}
log "grub-install: UEFI"
_grub_efi || die "grub-install (UEFI) failed"
_grub_efi --removable || die "grub-install (UEFI, removable path) failed"
[ -e "$C/mnt/esp/EFI/BOOT/BOOTX64.EFI" ] || [ -e "$C/mnt/esp/EFI/BOOT/bootx64.efi" ] \
    || die "no EFI/BOOT/BOOTX64.EFI on the ESP"
[ -e "$C/mnt/esp/EFI/debian/shimx64.efi" ] || log "WARNING: no shimx64.efi: this disk will not boot with Secure Boot on"
log "grub-install: legacy BIOS"
in_chroot grub-install --target=i386-pc --boot-directory=/mnt/esp --recheck "$LOOP" \
    || die "grub-install (BIOS) failed"

log "A/B selector and grubenv"
# A fresh disk has no legacy root: the selector's last branch points at a
# UUID that cannot exist and falls through to its own reboot.
in_chroot sh -c '. /usr/local/sbin/hifi-ab-lib.sh && ab_render /usr/local/share/hifi-ab/grub-selector.cfg.tmpl LEGACY_UUID=00000000-0000-0000-0000-000000000000' \
    > "$WORK/selector.cfg" || die "rendering the boot selector failed"
in_chroot grub-script-check < "$WORK/selector.cfg" || die "the rendered boot selector is not valid GRUB script"
in_chroot grub-editenv /mnt/esp/EFI/debian/grubenv create
in_chroot grub-editenv /mnt/esp/EFI/debian/grubenv set ORDER="A B" A_OK=1 A_TRY=0 B_OK=0 B_TRY=0
cp -f "$WORK/selector.cfg" "$C/mnt/esp/EFI/debian/grub.cfg"
cp -f "$WORK/selector.cfg" "$C/mnt/esp/EFI/BOOT/grub.cfg"
{
    echo "# Osmium Sound: legacy BIOS entry, runs the same A/B selector as UEFI."
    echo "# Every module the selector and the slot scripts use, loaded while \$prefix is still on the ESP."
    for _m in part_gpt fat squash4 gzio xzio ext2 regexp test loadenv probe \
              configfile search_fs_uuid sleep reboot linux boot; do
        echo "insmod $_m"
    done
    # shellcheck disable=SC2016  # $root is GRUB's, not the shell's
    echo 'configfile ($root)/EFI/debian/grub.cfg'
} > "$C/mnt/esp/grub/grub.cfg"
: > "$C/mnt/esp/EFI/debian/ab-enabled"
sync
find "$C/mnt/esp/EFI" -type f | sed "s|^$C/mnt/esp/|  |"
umount "$C/mnt/esp"

for m in "$C/run" "$C/sys" "$C/proc" "$C/dev" "$C" "$WORK/rw" "$WORK/lower"; do
    umount -R "$m"
done
losetup -d "$LOOP"; LOOP=""

# The partition table read back from the file: the five names in order.
names=$(sfdisk --json "$OUT" | sed -n 's/.*"name": *"\([^"]*\)".*/\1/p' | tr '\n' ',')
[ "$names" = "BIOS boot,EFI System,hifi-root-a,hifi-root-b,hifi-data-grow," ] \
    || die "unexpected partition table: $names"
log "DONE ✓  $OUT ($img_ver, ${total_mib} MiB)"
