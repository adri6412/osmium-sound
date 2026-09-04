#!/bin/sh
# Osmium Sound — says whether THIS legacy device can be converted to the A/B
# layout, and why not when it can't. Changes nothing.
#
#   hifi-ab-precheck.sh    human-readable verdict + JSON in /run/hifi-ab-precheck.json
#   exit 0 convertible · 1 not convertible · 2 already converted
#
# Every condition must hold. When one doesn't, the device stays on the legacy
# channels and the reason is what the updater reports (the API reads the JSON),
# so these strings are user-facing: keep them in English and to the point.
set -u
# shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-ab-lib.sh
# shellcheck disable=SC1091  # absolute path, only exists on the appliance
. /usr/local/sbin/hifi-ab-lib.sh

OUT=/run/hifi-ab-precheck.json
reasons=""
add() { reasons="${reasons}${reasons:+; }$1"; }
json_out() {  # <convertible 0|1> <converted 0|1>
    _r=$(printf '%s' "$reasons" | sed 's/\\/\\\\/g; s/"/\\"/g')
    printf '{"convertible":%s,"converted":%s,"reasons":"%s","disk":"%s","disk_mib":%s,"root_min_mib":%s,"slot_mib":%s,"data_mib":%s,"free_needed_mib":%s,"state":"%s"}\n' \
        "$( [ "$1" = 1 ] && echo true || echo false)" "$( [ "$2" = 1 ] && echo true || echo false)" \
        "$_r" "${disk:-}" "${disk_mib:-0}" "${root_min_mib:-0}" "${slot_a_mib:-$AB_SLOT_MIB}" \
        "${data_mib:-0}" "${free_needed_mib:-0}" "$(ab_state_get)" > "$OUT.new" 2>/dev/null \
        && mv -f "$OUT.new" "$OUT"
}

disk=$(ab_disk 2>/dev/null) || disk=
disk_mib=0; root_min_mib=0; slot_a_mib=$AB_SLOT_MIB; data_mib=0; free_needed_mib=0
ab_mount_esp 2>/dev/null || true

if [ -n "$disk" ] && ab_part_by_name hifi-data >/dev/null 2>&1; then
    echo "already converted: hifi-data partition present on $disk (state: $(ab_state_get))"
    json_out 0 1
    exit 2
fi

[ -d /sys/firmware/efi ] || add "legacy BIOS boot: the A/B layout needs UEFI"
read -r cmdline < /proc/cmdline || cmdline=
case " $cmdline " in *" boot=live "*) add "live session: no disk to convert" ;; esac
ab_is_image && add "this system is already an A/B image"
[ -n "$disk" ] || add "root disk could not be determined"

if [ -n "$disk" ]; then
    dn=${disk#/dev/}
    [ "$(cat "/sys/block/$dn/removable" 2>/dev/null)" = 0 ] || add "the root disk is removable"
    [ "$(lsblk -dno TRAN "$disk" 2>/dev/null)" != usb ] || add "the root disk is on USB"
    n=0; for s in /sys/class/block/"$dn"*; do [ -f "$s/partition" ] && n=$((n + 1)); done
    [ "$n" = 3 ] || add "non-standard layout: $n partitions (3 expected)"
    rootdev=$(ab_root_dev 2>/dev/null) || rootdev=
    [ "$(ab_part_num "$rootdev" 2>/dev/null)" = 3 ] || add "the root is not partition 3"
    esp=$(ab_esp_dev 2>/dev/null) || esp=
    [ "$(ab_part_num "$esp" 2>/dev/null)" = 2 ] || add "no EFI System partition as partition 2"
    disk_mib=$(( $(blockdev --getsize64 "$disk" 2>/dev/null || echo 0) / 1048576 ))
    [ "$(blkid -o value -s TYPE "$rootdev" 2>/dev/null)" = ext4 ] || add "the root filesystem is not ext4"
    uuid=$(blkid -o value -s UUID "$rootdev" 2>/dev/null || true)

    # ── space ─────────────────────────────────────────────────────────────
    # Slot A is NOT a fixed size: it is the legacy root shrunk to the smallest
    # size resize2fs allows (ab_root_min_mib, ~1.55x what is in use — measured,
    # and repeating the resize does not improve it) plus a margin. Everything
    # else goes to /data. So on a small disk the question is not "which size do
    # I pick" but "how much must I free": that is free_needed_mib, and the deep
    # cleanup (hifi-ab-convert.sh cleanup --deep) tries to free it by itself.
    #
    # The space to share out runs from the start of the root to the end of the
    # disk — NOT "disk minus 513": when someone grows the disk (virtual
    # machines) the new space sits after partition 3 and must be counted, and
    # a non-standard head of disk still adds up correctly.
    p3start=$(cat "/sys/class/block/${rootdev#/dev/}/start" 2>/dev/null || echo 0)
    if [ "${p3start:-0}" -gt 0 ]; then
        avail=$(( disk_mib - p3start / 2048 - 1 ))
    else
        avail=$(( disk_mib - AB_HEAD_MIB ))
    fi
    root_min_mib=$(ab_root_min_mib "$rootdev")
    a_max=$(( avail - AB_SLOT_B_MIB - AB_DATA_MIN_MIB ))
    slot_a_mib=$(( root_min_mib + AB_SLOT_A_MARGIN_MIB ))
    # never smaller than an image slot: an image has to fit in here as well
    [ "$slot_a_mib" -lt "$AB_SLOT_B_MIB" ] && slot_a_mib=$AB_SLOT_B_MIB
    [ "$slot_a_mib" -gt "$a_max" ] && slot_a_mib=$a_max
    slot_a_mib=$(( slot_a_mib / 8 * 8 ))
    data_mib=$(( avail - slot_a_mib - AB_SLOT_B_MIB ))
    room=$(( root_min_mib + AB_SLOT_A_MARGIN_MIN_MIB ))
    if [ "$a_max" -lt "$AB_SLOT_B_MIB" ]; then
        # not even two slots plus the data: the disk is simply too small
        need=$(( disk_mib - avail + AB_SLOT_B_MIB * 2 + AB_DATA_MIN_MIB ))
        add "disk of ${disk_mib} MiB: the A/B layout needs at least ${need} MiB (8 GB)"
        data_mib=0
    elif [ "$room" -gt "$a_max" ]; then
        free_needed_mib=$(( (room - a_max) * 100 / AB_RESIZE_TAX + 1 ))
        # usual suspects: bundles or packages copied into the home, test kernels
        big=$(find / -xdev -type f -size +300M ! -path '/usr/*' ! -path '/opt/*' 2>/dev/null | head -n 3 | tr '\n' ' ')
        add "not enough space: free at least ${free_needed_mib} MiB (the root uses $(df -Pm / | awk 'NR==2{print $3}') MiB, cannot shrink below ${root_min_mib} MiB, and slot A can only reach ${a_max} MiB on a ${disk_mib} MiB disk)${big:+; large files to move away: $big}"
        data_mib=0
    fi

    # the GRUB stub on the ESP must be the one we know (or our selector already)
    if mountpoint -q "$AB_ESP_MNT" && [ -f "$AB_STUB" ]; then
        # The stub grub-install writes is three lines, but the first one may
        # carry the search hints (search.fs_uuid <uuid> root hd0,gpt3): some
        # installations have them, some don't, so compare line by line and
        # tolerate that tail — a plain string equality left devices with hints
        # on the legacy layout for no real reason (seen on the test VM,
        # 2026-09-01).
        stub=$(sed 's/[[:space:]]*$//' "$AB_STUB" | grep -v '^$')
        s1=$(printf '%s\n' "$stub" | sed -n 1p)
        s2=$(printf '%s\n' "$stub" | sed -n 2p)
        s3=$(printf '%s\n' "$stub" | sed -n 3p)
        nl=$(printf '%s\n' "$stub" | wc -l)
        stub_ok=1
        [ "$nl" = 3 ] || stub_ok=0
        case "$s1" in "search.fs_uuid $uuid root"|"search.fs_uuid $uuid root "*) ;; *) stub_ok=0 ;; esac
        [ "$s2" = "set prefix=(\$root)'/boot/grub'" ] || stub_ok=0
        # shellcheck disable=SC2016  # $prefix is GRUB's own variable, literal here
        [ "$s3" = 'configfile $prefix/grub.cfg' ] || stub_ok=0
        # marker of our own selector, in either language (the template header)
        if ! grep -qE 'selettore di avvio A/B|A/B boot selector' "$AB_STUB" && [ "$stub_ok" = 0 ]; then
            add "the GRUB stub on the ESP is not one we recognise"
        fi
        esp_free=$(df -Pm "$AB_ESP_MNT" | awk 'NR==2{print $4}')
        [ "${esp_free:-0}" -ge 4 ] || add "the ESP is nearly full (${esp_free:-0} MiB free)"
    else
        add "the ESP is not mounted, or $AB_STUB is missing"
    fi
fi

for t in rauc grub-editenv grub-reboot mkinitramfs sfdisk resize2fs update-grub busybox; do
    command -v "$t" >/dev/null 2>&1 || add "$t is missing"
done
[ -f "/boot/vmlinuz-$(uname -r)" ] || add "the running kernel ($(uname -r)) is not in /boot"
if command -v fuser >/dev/null 2>&1 && fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; then
    add "apt/dpkg is running"
fi

if [ -z "$reasons" ]; then
    echo "convertible: disk $disk (${disk_mib} MiB), root minimum ${root_min_mib} MiB -> slot A ${slot_a_mib} MiB, slot B ${AB_SLOT_B_MIB} MiB, data ${data_mib} MiB"
    json_out 1 0
    exit 0
fi
echo "NOT convertible: $reasons"
json_out 0 0
exit 1
