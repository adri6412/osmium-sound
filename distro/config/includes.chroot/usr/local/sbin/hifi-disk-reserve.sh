#!/bin/sh
# Osmium Sound — the system disk's reserve, the kernel's half (the other half,
# for what our own services write, is hifi_diskguard.py).
#
# The data partition (/data, with /var, /home and the /etc overlay on it)
# gets an ext4 reserve (5 %, between 512 MiB and 2 GiB) that only root and the
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

# ── What nothing uses any more ──────────────────────────────────────
# On a 16 GB disk the data partition is about 5 GB: these add up.
# The Electron kiosk's profile (Chromium's caches, ~340 MB on a device that
# ran it) once the screen is the Qt one; a device still on Electron keeps it.
if [ "$(cat /etc/hifi-player/ui-engine 2>/dev/null)" = qt ]; then
    for d in /home/hifi/.config/hifi-media-player "/home/hifi/.config/Osmium Sound"; do
        if [ -d "$d" ]; then
            rm -rf "$d" && log "removed $d (the Electron kiosk's profile)"
        fi
    done
fi
# Lyrion versions other than the one in use (hifi-lyrion-update.sh no longer
# keeps the previous one; devices updated before still have it). Not a
# <ver>.new: that may be an install going on.
LYR_ROOT=/data/lyrion
keep=$(basename "$(readlink "$LYR_ROOT/current" 2>/dev/null)" 2>/dev/null)
if [ -n "$keep" ] && [ -d "$LYR_ROOT/$keep" ]; then
    find "$LYR_ROOT" -mindepth 1 -maxdepth 1 -type d ! -name "$keep" ! -name current ! -name '*.new' \
        -exec rm -rf {} + -exec echo "hifi-disk-reserve: removed old Lyrion {}" \;
fi

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
