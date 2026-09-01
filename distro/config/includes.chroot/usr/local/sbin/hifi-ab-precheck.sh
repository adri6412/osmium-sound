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
    [ "$(blkid -o value -s TYPE "$rootdev" 2>/dev/null)" = ext4 ] || add "la root non è ext4"
    uuid=$(blkid -o value -s UUID "$rootdev" 2>/dev/null || true)

    # ── spazio ────────────────────────────────────────────────────────────
    # Lo slot A NON ha una taglia fissa: è la root legacy ristretta al minimo
    # che resize2fs concede (ab_root_min_mib, ~1,55 volte l'occupato: misurato,
    # e non migliora ripetendo il resize) più un margine. Tutto il resto va a
    # /data. Quindi su un disco piccolo la domanda non è "che taglia scelgo"
    # ma "quanto devo liberare": lo dice free_needed_mib, e la pulizia
    # profonda (hifi-ab-convert.sh cleanup --deep) prova a farlo da sola.
    # Spazio da spartire = dall'inizio della root alla fine del disco. NON è
    # "disco meno 513": se qualcuno allarga il disco (macchina virtuale) lo
    # spazio nuovo sta in coda alla partizione 3 e va contato, e se la testa
    # del disco è diversa dallo standard il conto resta giusto lo stesso.
    p3start=$(cat "/sys/class/block/${rootdev#/dev/}/start" 2>/dev/null || echo 0)
    if [ "${p3start:-0}" -gt 0 ]; then
        avail=$(( disk_mib - p3start / 2048 - 1 ))
    else
        avail=$(( disk_mib - AB_HEAD_MIB ))
    fi
    root_min_mib=$(ab_root_min_mib "$rootdev")
    a_max=$(( avail - AB_SLOT_B_MIB - AB_DATA_MIN_MIB ))
    slot_a_mib=$(( root_min_mib + AB_SLOT_A_MARGIN_MIB ))
    [ "$slot_a_mib" -gt "$a_max" ] && slot_a_mib=$a_max
    slot_a_mib=$(( slot_a_mib / 8 * 8 ))
    data_mib=$(( avail - slot_a_mib - AB_SLOT_B_MIB ))
    room=$(( root_min_mib + AB_SLOT_A_MARGIN_MIN_MIB ))
    if [ "$a_max" -lt "$AB_SLOT_B_MIB" ]; then
        # nemmeno due slot più i dati: disco troppo piccolo, punto.
        need=$(( disk_mib - avail + AB_SLOT_B_MIB * 2 + AB_DATA_MIN_MIB ))
        add "disco da ${disk_mib} MiB: per lo schema A/B ne servono almeno ${need} (8 GB)"
        data_mib=0
    elif [ "$room" -gt "$a_max" ]; then
        free_needed_mib=$(( (room - a_max) * 100 / AB_RESIZE_TAX + 1 ))
        big=$(find / -xdev -type f -size +300M ! -path '/usr/*' ! -path '/opt/*' 2>/dev/null | head -n 3 | tr '\n' ' ')
        add "la root non si restringe abbastanza: occupa $(df -Pm / | awk 'NR==2{print $3}') MiB (minimo tecnico ${root_min_mib} MiB) e su un disco da ${disk_mib} MiB lo slot A può arrivare a ${a_max} MiB, lasciando ${AB_SLOT_B_MIB} allo slot B e ${AB_DATA_MIN_MIB} ai dati: bisogna liberare almeno ${free_needed_mib} MiB (pulizia: hifi-ab-convert.sh cleanup --deep${big:+; file grandi da spostare via: $big})"
        data_mib=0
    fi

    # lo stub GRUB sulla ESP dev'essere quello che conosciamo (o già il nostro selettore)
    if mountpoint -q "$AB_ESP_MNT" && [ -f "$AB_STUB" ]; then
        # Lo stub scritto da grub-install è di tre righe, ma la prima può avere
        # in coda gli "hint" di ricerca (search.fs_uuid <uuid> root hd0,gpt3):
        # ci sono su alcune installazioni e non su altre, quindi si confronta
        # riga per riga tollerando la coda — con l'uguaglianza secca gli
        # apparecchi con hint restavano legacy senza un vero motivo (visto
        # sulla VM di collaudo il 2026-09-01).
        stub=$(sed 's/[[:space:]]*$//' "$AB_STUB" | grep -v '^$')
        s1=$(printf '%s\n' "$stub" | sed -n 1p)
        s2=$(printf '%s\n' "$stub" | sed -n 2p)
        s3=$(printf '%s\n' "$stub" | sed -n 3p)
        nl=$(printf '%s\n' "$stub" | wc -l)
        stub_ok=1
        [ "$nl" = 3 ] || stub_ok=0
        case "$s1" in "search.fs_uuid $uuid root"|"search.fs_uuid $uuid root "*) ;; *) stub_ok=0 ;; esac
        [ "$s2" = "set prefix=(\$root)'/boot/grub'" ] || stub_ok=0
        [ "$s3" = 'configfile $prefix/grub.cfg' ] || stub_ok=0
        if ! grep -q 'selettore di avvio A/B' "$AB_STUB" && [ "$stub_ok" = 0 ]; then
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
    echo "convertibile: disco $disk (${disk_mib} MiB), root minima ${root_min_mib} MiB → slot A ${slot_a_mib} MiB, slot B ${AB_SLOT_B_MIB} MiB, dati ${data_mib} MiB"
    json_out 1 0
    exit 0
fi
echo "NON convertibile: $reasons"
json_out 0 0
exit 1
