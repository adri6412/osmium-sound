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

# Wipe old partition table and create one primary partition.
write_status running 15 "Cancellazione partizioni…"
parted -s "$DEVICE" mklabel gpt 2>/dev/null || true
sync

write_status running 30 "Creazione partizione…"
# Use 100% of the disk; align optimally.
parted -a optimal -s "$DEVICE" mkpart primary 0% 100% || fail "partition creation failed"
sync

# Find the newly created partition.
PART=$(lsblk -no PATH "$DEVICE" | grep -v "^${DEVICE}$" | head -n1)
[ -n "$PART" ] || fail "could not find created partition"
[ -b "$PART" ] || fail "partition is not a block device: $PART"

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
