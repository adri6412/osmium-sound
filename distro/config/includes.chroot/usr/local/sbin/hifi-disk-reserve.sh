#!/bin/sh
# Osmium Sound — the system disk's reserve, the kernel's half (the other half,
# for what our own services write, is hifi_diskguard.py).
#
# The data partition (/data, with /var, /home and the /etc overlay on it)
# gets an ext4 reserve of max(2 GiB, 5 %) that only root and the
# hifi-reserve group may use: Lyrion and the kiosk. Anything else — above all
# a Samba copy, which writes as hifimusic — gets "disk full" at that line, and
# Lyrion still has room for its prefs, cache and database.
#
# Idempotent, at every boot before Lyrion (the group must be in its
# credentials when it starts) and after a disk resize: the size follows the
# partition. The reserve's group is a mount-time setting for the kernel, so it
# is written to the superblock (from the next mount on) and applied to the
# running mount with a remount.
set -u
GROUP=hifi-reserve
MEMBERS="squeezeboxserver hifi"
log() { echo "hifi-disk-reserve: $*"; }

MARK=/var/lib/squeezeboxserver
[ -d "$MARK" ] || MARK=/var
fstype=$(findmnt -n -o FSTYPE --target "$MARK" 2>/dev/null)
dev=$(findmnt -n -o SOURCE --target "$MARK" 2>/dev/null | sed 's/\[.*//')
mnt=$(findmnt -n -o TARGET --target "$MARK" 2>/dev/null)
if [ "$fstype" != ext4 ]; then
    log "$MARK is on ${fstype:-?}, not ext4: nothing to do"
    exit 0
fi
case "$dev" in /dev/*) ;; *) log "no block device for $MARK ($dev)"; exit 0 ;; esac
# A bind mount of /data shows up as /var: the remount goes to the real one.
real_mnt=$(findmnt -n -o TARGET -S "$dev" 2>/dev/null | while read -r t; do
    s=$(findmnt -n -o SOURCE "$t" 2>/dev/null)
    case "$s" in *\[*) ;; *) echo "$t"; break ;; esac
done)
[ -n "$real_mnt" ] || real_mnt=$mnt

getent group "$GROUP" >/dev/null 2>&1 || groupadd -r "$GROUP" || { log "groupadd failed"; exit 0; }
for u in $MEMBERS; do
    id -u "$u" >/dev/null 2>&1 || continue
    id -nG "$u" | tr ' ' '\n' | grep -qx "$GROUP" || usermod -aG "$GROUP" "$u"
done
gid=$(getent group "$GROUP" | cut -d: -f3)

bytes=$(python3 /usr/local/bin/hifi_diskguard.py reserve-bytes "$MARK") || { log "cannot size the reserve"; exit 0; }
info=$(tune2fs -l "$dev" 2>/dev/null) || { log "tune2fs cannot read $dev"; exit 0; }
field() { printf '%s\n' "$info" | sed -n "s/^$1:[[:space:]]*\([0-9]*\).*/\1/p" | head -n 1; }
bs=$(field 'Block size')
cur=$(field 'Reserved block count')
cur_gid=$(field 'Reserved blocks gid')
if [ -z "$bs" ] || [ "$bs" -le 0 ]; then
    log "no block size for $dev"
    exit 0
fi
want=$((bytes / bs))

if [ "$cur" != "$want" ] || [ "$cur_gid" != "$gid" ]; then
    if tune2fs -r "$want" -g "$gid" "$dev" >/dev/null 2>&1; then
        log "$dev: reserve $cur -> $want blocks of $bs bytes, group $GROUP ($gid)"
    else
        log "tune2fs -r $want -g $gid $dev failed"
    fi
fi
# the running mount takes the group now, not at the next boot
grep -q "resgid=$gid" /proc/self/mountinfo 2>/dev/null || \
    mount -o "remount,resgid=$gid" "$real_mnt" 2>/dev/null || log "remount of $real_mnt with resgid=$gid failed (applies at the next boot)"
exit 0
