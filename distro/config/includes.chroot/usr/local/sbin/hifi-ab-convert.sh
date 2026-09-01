#!/bin/sh
# Osmium Sound — conversione di un apparecchio legacy (root unica) allo schema
# A/B con RAUC, un passo alla volta e sempre con una via di ritorno:
#
#   status                      stato della conversione e del layout
#   cleanup                     libera spazio sulla root legacy (cache apt, .old, kernel vecchi)
#   prepare  [--reboot]         pre-verifiche → blocco pacchetti di avvio → initrd DEDICATO
#                               di conversione + voce GRUB one-shot → grub-reboot.
#                               L'initrd di produzione e la ESP NON vengono toccati.
#   finish                      (al primo avvio dopo la conversione, da hifi-ab-finish.service)
#                               system.conf RAUC, grubenv, rauc.slot=A sulla cmdline, /data in fstab
#   install <bundle> [--reboot] semina /data → rauc install nello slot B → SOLO ORA scrive il
#                               selettore sulla ESP (con lo stub di oggi come ultimo ramo)
#   select                      (ri)scrive il selettore sulla ESP
#   restore-selector            rimette il selettore se un grub-install lo ha riscritto (hook apt)
#
# Stato (sulla ESP, sopravvive a tutto): none → prepared → converted → ready → installed
set -u
# shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-ab-lib.sh
# shellcheck disable=SC1091  # percorso assoluto, esiste solo sull'apparecchio
. /usr/local/sbin/hifi-ab-lib.sh

LOCAL=/var/lib/hifi-player/ab
CONV_INITRD=/boot/initrd.img-abconvert
GRUBD=/etc/grub.d/45_hifi_abconvert
APT_HOOK=/etc/apt/apt.conf.d/98-hifi-ab-selector
HOLD_PKGS="linux-image-amd64 grub-efi-amd64-signed grub-efi-amd64 grub-efi-amd64-bin grub-common grub2-common shim-signed shim-signed-common"
CMD="${1:-status}"
[ $# -gt 0 ] && shift

die() { ab_warn "$*"; exit 1; }
need_root() { [ "$(id -u)" -eq 0 ] || die "serve root"; }
have_layout() {
    ab_part_by_name hifi-root-a >/dev/null 2>&1 && ab_part_by_name hifi-root-b >/dev/null 2>&1 \
        && ab_part_by_name hifi-data >/dev/null 2>&1
}
root_uuid() { blkid -o value -s UUID "$(ab_root_dev)" 2>/dev/null; }
default_cmdline() {
    # entrambe le variabili, come fa 10_linux per la voce normale (GRUB_CMDLINE_LINUX
    # porta i parametri propri dell'apparecchio, es. una console seriale)
    _a=$(sed -n 's/^GRUB_CMDLINE_LINUX="\(.*\)"$/\1/p' /etc/default/grub 2>/dev/null | tail -n 1)
    _b=$(sed -n 's/^GRUB_CMDLINE_LINUX_DEFAULT="\(.*\)"$/\1/p' /etc/default/grub 2>/dev/null | tail -n 1)
    printf '%s %s\n' "$_a" "$_b" | sed 's/^ *//; s/ *$//'
}
grub_cmdline_add() {  # <token>... in GRUB_CMDLINE_LINUX; 0 se ha cambiato qualcosa
    _f=/etc/default/grub
    _cur=$(sed -n 's/^GRUB_CMDLINE_LINUX="\(.*\)"$/\1/p' "$_f" 2>/dev/null | tail -n 1)
    _new=$_cur
    for _t in "$@"; do
        case " $_new " in *" $_t "*) ;; *) _new="${_new:+$_new }$_t" ;; esac
    done
    [ "$_new" != "$_cur" ] || return 1
    if grep -q '^GRUB_CMDLINE_LINUX=' "$_f"; then
        sed -i "s|^GRUB_CMDLINE_LINUX=.*|GRUB_CMDLINE_LINUX=\"$_new\"|" "$_f"
    else
        printf 'GRUB_CMDLINE_LINUX="%s"\n' "$_new" >> "$_f"
    fi
    return 0
}

render_selector() {  # -> stampa il selettore reso per questo apparecchio
    _uuid=$(cat "$LOCAL/legacy-uuid" 2>/dev/null || root_uuid)
    [ -n "$_uuid" ] || die "UUID della root legacy sconosciuto"
    ab_render "$AB_SHARE/grub-selector.cfg.tmpl" "LEGACY_UUID=$_uuid"
}

cmd_status() {
    ab_mount_esp 2>/dev/null || true
    echo "stato conversione : $(ab_state_get)"
    echo "disco             : $(ab_disk 2>/dev/null || echo '?')   root: $(ab_root_dev 2>/dev/null || echo '?')"
    for n in hifi-root-a hifi-root-b hifi-data; do
        printf '%-18s: %s\n' "$n" "$(ab_part_by_name "$n" 2>/dev/null || echo assente)"
    done
    echo "immagine          : $(ab_is_image && cat "$AB_IMAGE_MARKER" || echo 'no (root legacy)')"
    echo "slot avviato      : $(ab_booted_slot 2>/dev/null || echo '-')"
    [ -f "$AB_ENABLED" ] && echo "selettore ESP     : attivo" || echo "selettore ESP     : non attivo (stub legacy)"
    if [ -r "$AB_GRUBENV" ]; then
        printf 'grubenv           : '; grub-editenv "$AB_GRUBENV" list 2>/dev/null | grep -E '^(ORDER|A_OK|A_TRY|B_OK|B_TRY)=' | tr '\n' ' '; echo
    fi
    if [ -f "$AB_RAUC_CONF" ]; then
        rauc status 2>/dev/null | sed 's/^/  rauc: /' | head -n 25 || true
    fi
    [ -f "$AB_ESP_DIR/abconvert.log" ] && { echo "--- abconvert.log (ESP) ---"; tail -n 15 "$AB_ESP_DIR/abconvert.log"; }
    return 0
}

cmd_cleanup() {
    need_root
    ab_is_image && die "sono un'immagine: niente da pulire"
    before=$(df -Pm / | awk 'NR==2{print $3}')
    apt-get clean >/dev/null 2>&1 || true
    rm -rf /var/lib/apt/lists/* /var/cache/apt/*.bin 2>/dev/null || true
    rm -rf /opt/hifi-media-player.old /opt/hifi-qt.old 2>/dev/null || true
    rm -rf /var/lib/hifi-player/update/staged 2>/dev/null || true
    DEBIAN_FRONTEND=noninteractive apt-get -y autoremove --purge >/dev/null 2>&1 || true
    journalctl --vacuum-size=32M >/dev/null 2>&1 || true
    after=$(df -Pm / | awk 'NR==2{print $3}')
    ab_log "pulizia: root da ${before} a ${after} MiB usati"
    return 0
}

cmd_prepare() {
    need_root
    reboot=0; [ "${1:-}" = "--reboot" ] && reboot=1
    ab_is_image && die "sono un'immagine: niente da convertire"
    st=$(ab_state_get)
    case "$st" in
        converted|ready|installed) die "già convertito (stato $st): usare finish/install" ;;
    esac
    if ! /usr/local/sbin/hifi-ab-precheck.sh; then
        die "pre-verifiche non superate: l'apparecchio resta legacy"
    fi
    kver=$(uname -r)
    uuid=$(root_uuid)
    [ -n "$uuid" ] || die "UUID root sconosciuto"
    mkdir -p "$LOCAL"
    printf '%s\n' "$uuid" > "$LOCAL/legacy-uuid"

    ab_log "blocco degli aggiornamenti di kernel e bootloader durante la conversione"
    # shellcheck disable=SC2086  # elenco di pacchetti
    apt-mark hold $HOLD_PKGS >/dev/null 2>&1 || true
    systemctl disable --now apt-daily.timer apt-daily-upgrade.timer >/dev/null 2>&1 || true
    systemctl stop unattended-upgrades.service >/dev/null 2>&1 || true

    ab_log "initrd dedicato di conversione ($kver)"
    # mkinitramfs ignora in silenzio gli hook non eseguibili (il pacchetto di
    # sistema non conserva i bit di esecuzione sotto /usr/local/share)
    chmod +x "$AB_SHARE/initramfs/hooks/hifi-ab" "$AB_SHARE/initramfs/scripts/local-premount/hifi-ab-convert"
    rm -f "$CONV_INITRD"
    if ! mkinitramfs -d "$AB_SHARE/initramfs" -o "$CONV_INITRD" "$kver" >"$LOCAL/mkinitramfs.log" 2>&1; then
        tail -n 20 "$LOCAL/mkinitramfs.log" >&2
        die "mkinitramfs fallito"
    fi
    for must in scripts/local-premount/hifi-ab-convert sbin/sfdisk sbin/resize2fs sbin/mke2fs sbin/e2fsck; do
        lsinitramfs "$CONV_INITRD" | grep -qE "(^|/)${must}$" \
            || die "l'initrd di conversione non contiene $must"
    done

    ab_log "voce GRUB one-shot 'hifi-ab-convert'"
    cat > "$GRUBD" <<GRUBEOF
#!/bin/sh
exec tail -n +3 \$0
menuentry 'Osmium Sound — conversione A/B' --id hifi-ab-convert --class osmium {
	insmod part_gpt
	insmod ext2
	search --no-floppy --fs-uuid --set=root $uuid
	linux /boot/vmlinuz-$kver root=UUID=$uuid ro hifi.abconvert=1 hifi.abconvert.uuid=$uuid hifi.abconvert.slot_mib=$AB_SLOT_MIB hifi.abconvert.slotb_mib=$AB_SLOT_B_MIB panic=30 $(default_cmdline)
	initrd $CONV_INITRD
}
GRUBEOF
    chmod +x "$GRUBD"
    update-grub >"$LOCAL/update-grub.log" 2>&1 || die "update-grub fallito"
    grep -q "hifi-ab-convert" /boot/grub/grub.cfg || die "la voce di conversione non è in grub.cfg"
    grub-reboot hifi-ab-convert || die "grub-reboot fallito"
    grep -q '^next_entry=hifi-ab-convert' /boot/grub/grubenv || die "next_entry non impostato"

    ab_mount_esp || die "ESP non montabile"
    ab_state_set prepared
    sync
    ab_log "pronto: al prossimo avvio la root viene ristretta a ${AB_SLOT_MIB} MiB e nascono gli slot B e dati (1-5 min, NON spegnere)"
    if [ "$reboot" = 1 ]; then
        systemctl reboot
    fi
    return 0
}

cmd_finish() {
    need_root
    ab_is_image && exit 0
    if ! have_layout; then
        st=$(ab_state_get 2>/dev/null || echo none)
        [ "$st" = prepared ] && ab_warn "layout A/B assente dopo l'avvio di conversione: vedi $AB_ESP_DIR/abconvert.log"
        exit 0
    fi
    /usr/local/sbin/hifi-rauc-config.sh
    [ -f "$AB_RAUC_CONF" ] || die "system.conf non generato"
    ab_mount_esp || die "ESP non montabile"
    if [ ! -f "$AB_GRUBENV" ]; then
        grub-editenv "$AB_GRUBENV" create || die "grub-editenv create fallito"
    fi
    if ! grub-editenv "$AB_GRUBENV" list 2>/dev/null | grep -q '^ORDER='; then
        grub-editenv "$AB_GRUBENV" set ORDER="A B" A_OK=1 A_TRY=0 B_OK=0 B_TRY=0 \
            || die "grub-editenv set fallito"
    fi
    changed=0
    grub_cmdline_add "rauc.slot=A" "panic=10" && changed=1
    if [ -f "$GRUBD" ] || [ -f "$CONV_INITRD" ]; then
        rm -f "$GRUBD" "$CONV_INITRD"
        changed=1
    fi
    [ "$changed" = 1 ] && { update-grub >/dev/null 2>&1 || ab_warn "update-grub fallito"; }
    if ! grep -qE '^[^#]*[[:space:]]/data[[:space:]]' /etc/fstab; then
        printf 'PARTLABEL=hifi-data  /data  ext4  defaults,noatime,nofail  0  2\n' >> /etc/fstab
        systemctl daemon-reload 2>/dev/null || true
    fi
    systemctl enable hifi-rauc-config.service hifi-boot-health.service hifi-boot-watchdog.timer >/dev/null 2>&1 || true
    systemctl start hifi-boot-health.service >/dev/null 2>&1 || true
    mkdir -p "$LOCAL"
    ab_state_set ready
    ab_log "conversione completata: pronto per la prima immagine (install <bundle>)"
    return 0
}

cmd_select() {
    need_root
    have_layout || die "layout A/B assente"
    ab_mount_esp || die "ESP non montabile"
    mkdir -p "$LOCAL"
    render_selector > "$LOCAL/selector.cfg.new" || die "rendering del selettore fallito"
    if command -v grub-script-check >/dev/null 2>&1; then
        grub-script-check "$LOCAL/selector.cfg.new" || die "il selettore reso NON passa grub-script-check: non lo scrivo"
    fi
    mv -f "$LOCAL/selector.cfg.new" "$LOCAL/selector.cfg"
    [ -f "$AB_STUB_LEGACY" ] || cp -a "$AB_STUB" "$AB_STUB_LEGACY"
    if ab_write_atomic "$AB_STUB" 0644 < "$LOCAL/selector.cfg"; then
        ab_log "selettore scritto in $AB_STUB"
    fi
    if [ -f "$AB_ESP_MNT/EFI/BOOT/grub.cfg" ]; then
        [ -f "$AB_ESP_MNT/EFI/BOOT/grub.cfg.legacy" ] || cp -a "$AB_ESP_MNT/EFI/BOOT/grub.cfg" "$AB_ESP_MNT/EFI/BOOT/grub.cfg.legacy"
        ab_write_atomic "$AB_ESP_MNT/EFI/BOOT/grub.cfg" 0644 < "$LOCAL/selector.cfg" || true
    fi
    cat > "$APT_HOOK" <<'HOOKEOF'
DPkg::Post-Invoke { "test -x /usr/local/sbin/hifi-ab-convert.sh && /usr/local/sbin/hifi-ab-convert.sh restore-selector; true"; };
HOOKEOF
    if [ ! -f "$AB_ENABLED" ]; then
        : > "$AB_ENABLED.new" && mv -f "$AB_ENABLED.new" "$AB_ENABLED"
        sync
        ab_log "A/B attivo sulla ESP (ab-enabled)"
    fi
    return 0
}

cmd_restore_selector() {
    need_root
    ab_mount_esp 2>/dev/null || exit 0
    [ -f "$AB_ENABLED" ] && [ -f "$LOCAL/selector.cfg" ] || exit 0
    if ! grep -q 'selettore di avvio A/B' "$AB_STUB" 2>/dev/null; then
        ab_warn "lo stub sulla ESP era stato riscritto: ripristino il selettore"
        ab_write_atomic "$AB_STUB" 0644 < "$LOCAL/selector.cfg" || true
    fi
    return 0
}

cmd_install() {
    need_root
    bundle="${1:-}"; [ -n "$bundle" ] || die "uso: $0 install <bundle.raucb|https://…> [--reboot]"
    reboot=0; [ "${2:-}" = "--reboot" ] && reboot=1
    ab_is_image && die "da un'immagine si aggiorna con l'API/rauc, non con questo comando"
    have_layout || die "layout A/B assente: prima prepare (e riavvio)"
    st=$(ab_state_get)
    case "$st" in ready|installed) ;; *) die "stato '$st': serve 'ready' (finish non ancora eseguito?)" ;; esac
    /usr/local/sbin/hifi-rauc-config.sh
    case "$bundle" in
        http://*|https://*) modprobe nbd 2>/dev/null || true ;;
        *) [ -f "$bundle" ] || die "bundle non trovato: $bundle" ;;
    esac
    ab_log "semina di /data dalla root legacy"
    /usr/local/sbin/hifi-ab-seed.sh || die "semina fallita"
    ab_log "rauc install $bundle (scrive lo slot B, il sistema in uso non cambia)"
    rauc install "$bundle" || die "rauc install fallito"
    if ! grub-editenv "$AB_GRUBENV" list 2>/dev/null | grep -q '^ORDER=B A'; then
        die "dopo l'installazione grubenv non indica B come primario"
    fi
    cmd_select
    /usr/local/sbin/hifi-ab-seed.sh >/dev/null 2>&1 || true
    ab_state_set installed
    sync
    ab_log "slot B installato e selettore attivo: al riavvio parte l'immagine; se non si dichiara buona in 10 min si torna qui"
    [ "$reboot" = 1 ] && systemctl reboot
    return 0
}

case "$CMD" in
    status)           cmd_status ;;
    cleanup)          cmd_cleanup ;;
    prepare)          cmd_prepare "$@" ;;
    finish)           cmd_finish ;;
    install)          cmd_install "$@" ;;
    select)           cmd_select ;;
    restore-selector) cmd_restore_selector ;;
    *) echo "uso: $0 status|cleanup|prepare [--reboot]|finish|install <bundle> [--reboot]|select|restore-selector" >&2; exit 64 ;;
esac
