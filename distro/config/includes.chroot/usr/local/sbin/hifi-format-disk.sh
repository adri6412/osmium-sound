#!/bin/sh
# HiFi Player — format an internal music disk and report progress.
#
# Called by sources_server.py via systemd-run:
#   hifi-format-disk.sh <device> <ext4|exfat> <label>
#
# Wipes the target disk, creates a single partition, formats it, and writes
# progress to /run/hifi-format-status.json. The service then adopts the new
# partition as an internal music source.
set -eu

DEVICE="${1:-}"
FS="${2:-}"
LABEL="${3:-Musica}"
STATUS="/run/hifi-format-status.json"

write_status() {
    state="$1"; progress="$2"; msg="$3"
    esc_msg=$(printf '%s' "$msg" | sed 's/\\/\\\\/g; s/"/\\"/g')
    printf '{"state":"%s","progress":%s,"message":"%s"}\n' \
        "$state" "$progress" "$esc_msg" > "$STATUS"
}

fail() {
    write_status error 0 "$1"
    echo "E: [hifi-format] $1" >&2
    exit 1
}

[ -n "$DEVICE" ] || fail "device missing"
[ -b "$DEVICE" ] || fail "not a block device: $DEVICE"
case "$FS" in
    ext4|exfat) ;;
    *) fail "unsupported filesystem: $FS" ;;
esac

# Refuse to touch the running system disk.
for target in / /boot/efi; do
    src=$(findmnt -no SOURCE "$target" 2>/dev/null || true)
    [ -n "$src" ] || continue
    case "$src" in
        /dev/*)
            parent=$(lsblk -no PKNAME "$src" 2>/dev/null | awk 'NR==1{print}')
            [ -n "$parent" ] && [ "/dev/$parent" = "$DEVICE" ] && fail "refusing to format system disk $DEVICE"
            ;;
    esac
done

mkdir -p "$(dirname "$STATUS")"
write_status running 5 "Preparazione disco…"

# Make sure nothing on this disk is mounted or active as swap first — the
# kernel refuses to let a busy partition table be rewritten.
for part in $(lsblk -no PATH "$DEVICE" 2>/dev/null | grep -v "^${DEVICE}$"); do
    mp=$(lsblk -no MOUNTPOINT "$part" 2>/dev/null | head -n1)
    if [ -n "$mp" ]; then
        umount -l "$part" 2>/dev/null || true
    fi
    swapoff "$part" 2>/dev/null || true
done

write_status running 10 "Rimozione firme precedenti…"
# Wipe old filesystem/RAID/LVM signatures on every existing partition and the
# disk itself. Stale signatures are the usual reason the kernel refuses to
# re-read a rewritten partition table, which otherwise surfaces as a generic
# partitioning failure below.
for part in $(lsblk -no PATH "$DEVICE" 2>/dev/null | grep -v "^${DEVICE}$"); do
    wipefs -a "$part" >/dev/null 2>&1 || true
done
wipefs -a "$DEVICE" >/dev/null 2>&1 || true
sync

# Create a fresh GPT label with a single partition spanning the whole disk.
# Uses sfdisk (util-linux, always present) rather than parted, which is not
# part of this appliance's package set.
write_status running 20 "Creazione tabella partizioni…"
SFDISK_ERR=$(printf 'label: gpt\n,,\n' | sfdisk --wipe always --quiet "$DEVICE" 2>&1) \
    || fail "creazione partizione fallita: $(printf '%s' "$SFDISK_ERR" | tr '\n' ' ' | cut -c1-200)"
# blockdev/udevadm are util-linux/systemd — no dependency on the parted package.
blockdev --rereadpt "$DEVICE" 2>/dev/null || true
udevadm settle --timeout=10 2>/dev/null || true
sync

# Find the newly created partition (udev can lag briefly behind sfdisk).
PART=""
i=0
while [ "$i" -lt 10 ]; do
    PART=$(lsblk -no PATH "$DEVICE" 2>/dev/null | grep -v "^${DEVICE}$" | head -n1)
    if [ -n "$PART" ] && [ -b "$PART" ]; then
        break
    fi
    i=$((i + 1))
    sleep 1
done
[ -n "$PART" ] && [ -b "$PART" ] || fail "could not find created partition"

write_status running 50 "Formattazione $FS…"
case "$FS" in
    ext4)
        mkfs.ext4 -F -L "$LABEL" "$PART" >/dev/null 2>&1 || fail "mkfs.ext4 failed"
        ;;
    exfat)
        mkfs.exfat -n "$LABEL" "$PART" >/dev/null 2>&1 || fail "mkfs.exfat failed"
        ;;
esac
sync

write_status running 90 "Lettura identificativi…"
PARTUUID=$(lsblk -no PARTUUID "$PART" 2>/dev/null | head -n1 | tr -d ' ')
UUID=$(lsblk -no UUID "$PART" 2>/dev/null | head -n1 | tr -d ' ')
SIZE=$(lsblk -no SIZE "$PART" 2>/dev/null | head -n1 | tr -d ' ')

# Ensure mountpoint parent exists and is owned by the music user.
MOUNT_ROOT="/mnt/hifi-internal"
mkdir -p "$MOUNT_ROOT"

esc_msg=$(printf 'Disco pronto: %s (%s)' "$PART" "$SIZE" | sed 's/\\/\\\\/g; s/"/\\"/g')
printf '{"state":"done","progress":100,"message":"%s","partition":"%s","fstype":"%s","label":"%s","partuuid":"%s","uuid":"%s","size":"%s"}\n' \
    "$esc_msg" "$PART" "$FS" "$LABEL" "${PARTUUID:-}" "${UUID:-}" "${SIZE:-}" > "$STATUS"
