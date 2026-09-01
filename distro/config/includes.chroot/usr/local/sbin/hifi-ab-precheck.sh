#!/bin/sh
# Osmium Sound — dice se QUESTO apparecchio legacy può essere convertito allo
# schema A/B, e perché no in caso contrario. Non modifica nulla.
#
#   hifi-ab-precheck.sh          esito leggibile + JSON in /run/hifi-ab-precheck.json
#   exit 0 convertibile · 1 non convertibile · 2 già convertito
#
# Tutte le condizioni devono valere: chi non le rispetta resta sul canale
# legacy e in Impostazioni compare il motivo (l'API legge il JSON).
set -u
# shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-ab-lib.sh
# shellcheck disable=SC1091  # percorso assoluto, esiste solo sull'apparecchio
. /usr/local/sbin/hifi-ab-lib.sh

OUT=/run/hifi-ab-precheck.json
reasons=""
add() { reasons="${reasons}${reasons:+; }$1"; }
json_out() {  # <convertible 0|1> <converted 0|1>
    _r=$(printf '%s' "$reasons" | sed 's/\\/\\\\/g; s/"/\\"/g')
    printf '{"convertible":%s,"converted":%s,"reasons":"%s","disk":"%s","disk_mib":%s,"root_min_mib":%s,"slot_mib":%s,"state":"%s"}\n' \
        "$( [ "$1" = 1 ] && echo true || echo false)" "$( [ "$2" = 1 ] && echo true || echo false)" \
        "$_r" "${disk:-}" "${disk_mib:-0}" "${root_min_mib:-0}" "${slot_a_mib:-$AB_SLOT_MIB}" "$(ab_state_get)" > "$OUT.new" 2>/dev/null \
        && mv -f "$OUT.new" "$OUT"
}

disk=$(ab_disk 2>/dev/null) || disk=
disk_mib=0; root_min_mib=0; slot_a_mib=$AB_SLOT_MIB
ab_mount_esp 2>/dev/null || true

if [ -n "$disk" ] && ab_part_by_name hifi-data >/dev/null 2>&1; then
    echo "già convertito: partizione hifi-data presente su $disk (stato: $(ab_state_get))"
    json_out 0 1
    exit 2
fi

[ -d /sys/firmware/efi ] || add "avvio BIOS legacy: la conversione A/B richiede UEFI"
read -r cmdline < /proc/cmdline || cmdline=
case " $cmdline " in *" boot=live "*) add "sessione live: nessun disco da convertire" ;; esac
ab_is_image && add "questo sistema è già un'immagine A/B"
[ -n "$disk" ] || add "disco di root non determinabile"

if [ -n "$disk" ]; then
    dn=${disk#/dev/}
    [ "$(cat "/sys/block/$dn/removable" 2>/dev/null)" = 0 ] || add "il disco di root è rimovibile"
    [ "$(lsblk -dno TRAN "$disk" 2>/dev/null)" != usb ] || add "il disco di root è USB"
    n=0; for s in /sys/class/block/"$dn"*; do [ -f "$s/partition" ] && n=$((n + 1)); done
    [ "$n" = 3 ] || add "layout non standard: $n partizioni (attese 3)"
    rootdev=$(ab_root_dev 2>/dev/null) || rootdev=
    [ "$(ab_part_num "$rootdev" 2>/dev/null)" = 3 ] || add "la root non è la partizione 3"
    esp=$(ab_part_by_name "EFI System" 2>/dev/null) || esp=
    [ "$(ab_part_num "$esp" 2>/dev/null)" = 2 ] || add "ESP non trovata come partizione 2"
    disk_mib=$(( $(blockdev --getsize64 "$disk" 2>/dev/null || echo 0) / 1048576 ))
    need=$(( 1 + 512 + AB_SLOT_MIB + AB_SLOT_B_MIB + 3072 ))
    [ "$disk_mib" -ge "$need" ] || add "disco da ${disk_mib} MiB: ne servono almeno ${need}"
    slot_a_mib=$AB_SLOT_MIB
    [ "$(blkid -o value -s TYPE "$rootdev" 2>/dev/null)" = ext4 ] || add "la root non è ext4"

    # spazio: stima resize2fs -P (funziona anche a filesystem montato) AL NETTO
    # del journal (l'initrd di conversione lo toglie prima del resize e ne
    # ricrea uno da 64 MiB), ripiego su df
    uuid=$(blkid -o value -s UUID "$rootdev" 2>/dev/null || true)
    blksz=$(dumpe2fs -h "$rootdev" 2>/dev/null | sed -n 's/^Block size: *//p')
    minblk=$(resize2fs -P "$rootdev" 2>/dev/null | sed -n 's/.*: *\([0-9]*\)$/\1/p')
    # e2fsprogs 1.47 la chiama "Total journal size", le versioni prima "Journal size"
    jsize=$(dumpe2fs -h "$rootdev" 2>/dev/null | sed -n 's/^\(Total \)\{0,1\}[Jj]ournal size: *\([0-9]*\)M$/\2/p' | head -n 1)
    if [ -n "$blksz" ] && [ -n "$minblk" ]; then
        root_min_mib=$(( minblk * blksz / 1048576 + 1 - ${jsize:-0} + 64 ))
    else
        root_min_mib=$(( $(df -Pm / | awk 'NR==2{print $3}') * 115 / 100 ))
    fi
    # La stima di resize2fs è prudente (gruppi flex_bg interi, tabelle inode): è
    # anche il minimo che resize2fs FA RISPETTARE, quindi lo slot A dei convertiti
    # si dimensiona su di essa — almeno AB_SLOT_MIB, altrimenti stima + 256 MiB,
    # a multipli di 8 — purché a /data restino almeno 3 GiB. Le installazioni
    # nuove non c'entrano: là gli slot sono da AB_SLOT_B_MIB.
    slot_a_mib=$AB_SLOT_MIB
    if [ $(( root_min_mib + 256 )) -gt "$slot_a_mib" ]; then
        slot_a_mib=$(( (root_min_mib + 256 + 7) / 8 * 8 ))
    fi
    need=$(( 1 + 512 + slot_a_mib + AB_SLOT_B_MIB + 3072 ))
    [ "$disk_mib" -ge "$need" ] \
        || add "la root occupa almeno ${root_min_mib} MiB: con uno slot A da ${slot_a_mib} MiB e uno B da ${AB_SLOT_B_MIB} resterebbero meno di 3 GiB per i dati su un disco da ${disk_mib} MiB (pulizia: hifi-ab-convert.sh cleanup)"

    # lo stub GRUB sulla ESP dev'essere quello che conosciamo (o già il nostro selettore)
    if mountpoint -q "$AB_ESP_MNT" && [ -f "$AB_STUB" ]; then
        stub=$(sed 's/[[:space:]]*$//' "$AB_STUB" | grep -v '^$' | tr '\n' '|')
        if ! grep -q 'selettore di avvio A/B' "$AB_STUB" \
           && [ "$stub" != "search.fs_uuid $uuid root|set prefix=(\$root)'/boot/grub'|configfile \$prefix/grub.cfg|" ]; then
            add "stub GRUB sulla ESP non riconosciuto"
        fi
        avail=$(df -Pm "$AB_ESP_MNT" | awk 'NR==2{print $4}')
        [ "${avail:-0}" -ge 4 ] || add "ESP quasi piena (${avail:-0} MiB liberi)"
    else
        add "ESP non montabile o senza $AB_STUB"
    fi
fi

for t in rauc grub-editenv grub-reboot mkinitramfs sfdisk resize2fs update-grub busybox; do
    command -v "$t" >/dev/null 2>&1 || add "manca $t"
done
[ -f "/boot/vmlinuz-$(uname -r)" ] || add "kernel in uso ($(uname -r)) non presente in /boot"
if command -v fuser >/dev/null 2>&1 && fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; then
    add "apt/dpkg in esecuzione"
fi

if [ -z "$reasons" ]; then
    echo "convertibile: disco $disk (${disk_mib} MiB), root minima ${root_min_mib} MiB → slot A ${slot_a_mib} MiB, slot B ${AB_SLOT_B_MIB} MiB, dati $(( disk_mib - 513 - slot_a_mib - AB_SLOT_B_MIB )) MiB"
    json_out 1 0
    exit 0
fi
echo "NON convertibile: $reasons"
json_out 0 0
exit 1
