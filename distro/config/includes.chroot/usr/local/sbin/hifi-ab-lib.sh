# shellcheck shell=sh
# shellcheck disable=SC2034  # costanti usate dagli script che la includono
# Osmium Sound — funzioni condivise per il layout A/B (RAUC).
# Sorgente sia per gli script dell'immagine sia per la conversione dei legacy.
# POSIX sh puro (dash), niente bashismi.
#
# Layout GPT di riferimento (identico per ISO nuove e apparecchi convertiti):
#   p1 "BIOS boot"    1 MiB      inerte
#   p2 "EFI System"   512 MiB    shim+grub Debian, selettore, grubenv
#   p3 hifi-root-a    5120 MiB (convertiti) / 4096 (nuovi)   slot A
#   p4 hifi-root-b    4096 MiB                                 slot B
#   p5 hifi-data      resto      stato persistente (/data)

# Slot A degli apparecchi CONVERTITI = la root legacy ristretta: le serve più
# spazio (Debian scrivibile, dati Lyrion ancora dentro, journal, margine per il
# resize2fs, che è il passo delicato) di quanto ne prenda un'immagine: 5120 MiB.
# Lo slot B (e ogni slot di un'installazione nuova) è da 4096 MiB; l'immagine è
# da 3584 MiB e RAUC la allarga alla partizione (resize=true). Su una eMMC da
# 16 GB restano ~5 GiB a /data.
AB_SLOT_MIB="${AB_SLOT_MIB:-5120}"
AB_SLOT_B_MIB="${AB_SLOT_B_MIB:-4096}"
AB_ESP_MNT=/boot/efi
AB_ESP_DIR="$AB_ESP_MNT/EFI/debian"
AB_GRUBENV="$AB_ESP_DIR/grubenv"
AB_STUB="$AB_ESP_DIR/grub.cfg"
AB_STUB_LEGACY="$AB_ESP_DIR/grub.cfg.legacy"
AB_ENABLED="$AB_ESP_DIR/ab-enabled"
AB_STATE="$AB_ESP_DIR/abconvert.state"
AB_SHARE=/usr/local/share/hifi-ab
AB_KEYRING_SRC="$AB_SHARE/keyring.pem"
AB_RAUC_CONF=/etc/rauc/system.conf
AB_RAUC_KEYRING=/etc/rauc/keyring.pem
AB_DATA_MNT=/data
AB_IMAGE_MARKER=/usr/lib/osmium/IMAGE_VERSION

ab_log() { printf 'I: [hifi-ab] %s\n' "$*" >&2; }
ab_warn() { printf 'W: [hifi-ab] %s\n' "$*" >&2; }

# Dispositivo a blocchi della root (es. /dev/mmcblk0p3), anche sotto overlay.
ab_root_dev() {
    if [ -r /run/hifi-state/root ]; then
        cat /run/hifi-state/root
        return 0
    fi
    _d=$(findmnt -no SOURCE / 2>/dev/null | head -n 1)
    case "$_d" in
        /dev/*) readlink -f "$_d" ;;
        *) return 1 ;;
    esac
}

# Disco che contiene la root (es. /dev/mmcblk0).
ab_disk() {
    _r=$(ab_root_dev) || return 1
    _n=${_r#/dev/}
    _p=$(readlink -f "/sys/class/block/$_n/..") || return 1
    printf '/dev/%s\n' "$(basename "$_p")"
}

# Partizione del disco di root con un dato nome GPT: ab_part_by_name hifi-data
# -> /dev/mmcblk0p5. Si legge la GPT con blkid (PARTLABEL): l'uevent del kernel
# non porta PARTNAME per le partizioni aggiunte con partx, e i symlink udev
# by-partlabel non distinguono il disco.
ab_part_by_name() {
    _disk=$(ab_disk) || return 1
    _dn=${_disk#/dev/}
    for _s in /sys/class/block/"$_dn"*; do
        [ -f "$_s/partition" ] || continue
        _dev="/dev/$(basename "$_s")"
        if [ "$(blkid -o value -s PARTLABEL "$_dev" 2>/dev/null)" = "$1" ]; then
            printf '%s\n' "$_dev"
            return 0
        fi
    done
    return 1
}

# Numero di partizione di un device (es. /dev/mmcblk0p3 -> 3).
ab_part_num() {
    cat "/sys/class/block/$(basename "$1")/partition" 2>/dev/null
}

# Vero sugli slot immagine (root read-only costruita da build-image.sh).
ab_is_image() { [ -f "$AB_IMAGE_MARKER" ]; }

# Slot avviato (A|B) secondo la riga di comando del kernel; vuoto sui legacy.
ab_booted_slot() {
    read -r _cmdline < /proc/cmdline 2>/dev/null || _cmdline=
    for _x in $_cmdline; do
        case "$_x" in rauc.slot=*) printf '%s\n' "${_x#rauc.slot=}"; return 0 ;; esac
    done
    return 1
}

# Monta la ESP e /data se non lo sono già (idempotente).
ab_mount_esp() {
    mountpoint -q "$AB_ESP_MNT" && return 0
    _esp=$(ab_part_by_name "EFI System") || return 1
    mkdir -p "$AB_ESP_MNT"
    mount -t vfat -o umask=0077 "$_esp" "$AB_ESP_MNT"
}
ab_mount_data() {
    mountpoint -q "$AB_DATA_MNT" && return 0
    _data=$(ab_part_by_name hifi-data) || return 1
    mkdir -p "$AB_DATA_MNT"
    mount -t ext4 -o noatime "$_data" "$AB_DATA_MNT"
}

# Scrittura atomica: ab_write_atomic <dest> [mode]  (contenuto da stdin).
# Restituisce 0 se ha scritto, 1 se il contenuto era già identico.
ab_write_atomic() {
    _dst="$1"; _mode="${2:-0644}"
    _tmp="$_dst.new"
    cat > "$_tmp"
    chmod "$_mode" "$_tmp"
    if [ -f "$_dst" ] && cmp -s "$_tmp" "$_dst"; then
        rm -f "$_tmp"
        return 1
    fi
    sync -f "$_tmp" 2>/dev/null || sync
    mv -f "$_tmp" "$_dst"
    sync
    return 0
}

# Stato della conversione sulla ESP (sopravvive a tutto).
ab_state_get() { cat "$AB_STATE" 2>/dev/null || echo none; }
ab_state_set() {
    mkdir -p "$AB_ESP_DIR" 2>/dev/null || true
    printf '%s\n' "$1" > "$AB_STATE.new" && mv -f "$AB_STATE.new" "$AB_STATE"
    sync
}

# Rende un template sostituendo i segnaposto @NOME@: ab_render <tmpl> NOME=valore...
ab_render() {
    _t="$1"; shift
    _sed=""
    for _kv in "$@"; do
        _k=${_kv%%=*}; _v=${_kv#*=}
        _v=$(printf '%s' "$_v" | sed 's/[\/&|]/\\&/g')
        _sed="$_sed -e s|@$_k@|$_v|g"
    done
    # shellcheck disable=SC2086  # $_sed è un elenco di opzioni costruito qui sopra
    sed $_sed "$_t"
}
