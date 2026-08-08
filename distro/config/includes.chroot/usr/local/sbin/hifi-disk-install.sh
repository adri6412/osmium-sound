#!/bin/sh
# HiFi Player — install the running live system onto a physical disk.
#
# Called by api_server.py via systemd-run (same detached-worker + /run
# status-file shape as hifi-format-disk.sh):
#   hifi-disk-install.sh <device>
#
# This is the disk-install backend for the Electron installer UI
# (src/pages/InstallWizard.jsx), which replaces Debian Installer entirely —
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

write_status running 2 "Preparazione…"

# ─────────────────────────── locate the squashfs source ────────────
SQUASHFS=""
for base in /run/live/medium /lib/live/mount/medium; do
    [ -f "$base/live/filesystem.squashfs" ] && SQUASHFS="$base/live/filesystem.squashfs" && break
done
if [ -z "$SQUASHFS" ]; then
    SQUASHFS=$(find /run/live /lib/live/mount -maxdepth 4 -name '*.squashfs' 2>/dev/null | head -n1 || true)
fi
[ -n "$SQUASHFS" ] && [ -f "$SQUASHFS" ] || fail "could not locate the live filesystem.squashfs on the boot medium"
log() { echo "I: [hifi-install] $*"; }
log "squashfs source: $SQUASHFS"

# ─────────────────────────── partition + format ─────────────────────
write_status running 5 "Rimozione firme precedenti…"
for part in $(lsblk -no PATH "$DEVICE" 2>/dev/null | grep -v "^${DEVICE}$"); do
    mp=$(lsblk -no MOUNTPOINT "$part" 2>/dev/null | head -n1)
    [ -n "$mp" ] && umount -l "$part" 2>/dev/null || true
    swapoff "$part" 2>/dev/null || true
    wipefs -a "$part" >/dev/null 2>&1 || true
done
wipefs -a "$DEVICE" >/dev/null 2>&1 || true
sync

write_status running 10 "Creazione tabella partizioni…"
BIOSGRUB_TYPE="21686148-6449-6E6F-744E-656564454649"
EFI_TYPE="C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
LINUX_TYPE="0FC63DAF-8483-4772-8E79-3D69D8477DE4"
SFDISK_ERR=$(printf 'label: gpt\nsize=1MiB, type=%s, name="BIOS boot"\nsize=512MiB, type=%s, name="EFI System"\ntype=%s, name="Linux filesystem"\n' \
        "$BIOSGRUB_TYPE" "$EFI_TYPE" "$LINUX_TYPE" \
        | sfdisk --wipe always --quiet "$DEVICE" 2>&1) \
    || fail "partizionamento fallito: $(printf '%s' "$SFDISK_ERR" | tr '\n' ' ' | cut -c1-200)"
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
[ -n "$P1" ] && [ -n "$P2" ] && [ -n "$P3" ] || fail "partizioni non trovate dopo il partizionamento"

write_status running 20 "Formattazione…"
mkfs.vfat -F32 -n EFI "$P2" >/dev/null 2>&1 || fail "mkfs.vfat (EFI) fallito su $P2"
mkfs.ext4 -F -L hifi-root "$P3" >/dev/null 2>&1 || fail "mkfs.ext4 fallito su $P3"
sync

# ─────────────────────────── mount target ────────────────────────────
mkdir -p "$TARGET"
mount "$P3" "$TARGET" || fail "mount root fallito ($P3)"
mkdir -p "$TARGET/boot/efi"
mount "$P2" "$TARGET/boot/efi" || fail "mount EFI fallito ($P2)"

# ─────────────────────────── copy the system ─────────────────────────
write_status running 30 "Copia del sistema…"
: > "$UNSQUASHFS_LOG"
unsquashfs -f -d "$TARGET" "$SQUASHFS" >"$UNSQUASHFS_LOG" 2>&1 &
US_PID=$!
while kill -0 "$US_PID" 2>/dev/null; do
    PCT=$(grep -o '[0-9]\{1,3\}%' "$UNSQUASHFS_LOG" 2>/dev/null | tail -1 | tr -d '%')
    if [ -n "$PCT" ]; then
        SCALED=$((30 + PCT * 50 / 100))
        write_status running "$SCALED" "Copia del sistema… $PCT%"
    fi
    sleep 1
done
wait "$US_PID"
US_STATUS=$?
[ "$US_STATUS" -eq 0 ] || fail "copia del sistema fallita (unsquashfs exit $US_STATUS) — vedi $UNSQUASHFS_LOG"

write_status running 82 "Configurazione sistema…"

# ─────────────────────────── fstab ────────────────────────────────────
ROOT_UUID=$(blkid -s UUID -o value "$P3")
EFI_UUID=$(blkid -s UUID -o value "$P2")
[ -n "$ROOT_UUID" ] && [ -n "$EFI_UUID" ] || fail "impossibile leggere gli UUID delle partizioni create"
cat > "$TARGET/etc/fstab" <<EOF
# /etc/fstab — generated by hifi-disk-install.sh at install time
UUID=$ROOT_UUID  /          ext4  errors=remount-ro  0  1
UUID=$EFI_UUID   /boot/efi  vfat  umask=0077          0  1
EOF

# Fresh machine-id: unsquashfs cloned the live image's own (or absent) one,
# and every unit installed from the same ISO must not share an identity.
rm -f "$TARGET/etc/machine-id" "$TARGET/var/lib/dbus/machine-id" 2>/dev/null || true

# ─────────────────────────── bootloader ───────────────────────────────
write_status running 88 "Installazione bootloader…"
for fs in dev proc sys; do
    # --rbind, not --bind: a plain bind of /sys does NOT carry through the
    # efivarfs mounted at /sys/firmware/efi/efivars (a separate mount nested
    # inside sysfs), so the chroot would see an empty efivars dir. That's
    # enough for the "[ -d /sys/firmware/efi ]" UEFI detection in
    # hifi-grub-install.sh to pass, but not enough for dpkg-reconfigure
    # grub-efi-amd64-signed to actually write the signed boot chain — it
    # reports success while writing nothing. --rbind carries every nested
    # mount (efivars, devpts, ...) through instead.
    mount --rbind "/$fs" "$TARGET/$fs" || fail "bind mount /$fs fallito"
done

chroot "$TARGET" /bin/sh -c 'systemd-machine-id-setup' >/dev/null 2>&1 || true

if ! chroot "$TARGET" /bin/sh /usr/local/sbin/hifi-grub-install.sh >>/var/log/hifi/hifi-install-grub.log 2>&1; then
    fail "installazione bootloader fallita — vedi /var/log/hifi/hifi-install-grub.log"
fi
chroot "$TARGET" /bin/sh /usr/local/sbin/hifi-finalize-boot.sh >>/var/log/hifi/hifi-install-finalize-boot.log 2>&1 || true

write_status done 100 "Installazione completata"
log "done"
