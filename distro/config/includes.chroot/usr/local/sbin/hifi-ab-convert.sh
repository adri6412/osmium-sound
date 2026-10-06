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
. "${HIFI_AB_LIB:-/usr/local/sbin/hifi-ab-lib.sh}"   # HIFI_AB_LIB: tests only

# The HIFI_AB_* overrides are for the tests only (tests/test-ab-convert-cleanup.sh).
LOCAL=${HIFI_AB_LOCAL:-/var/lib/hifi-player/ab}
CONV_INITRD=${HIFI_AB_CONV_INITRD:-/boot/initrd.img-abconvert}
GRUBD=${HIFI_AB_GRUBD:-/etc/grub.d/45_hifi_abconvert}
# The legacy root's own GRUB environment, where grub-reboot leaves next_entry.
LEGACY_GRUBENV=${HIFI_AB_LEGACY_GRUBENV:-/boot/grub/grubenv}
APT_HOOK=/etc/apt/apt.conf.d/98-hifi-ab-selector
HOLD_PKGS="linux-image-amd64 grub-efi-amd64-signed grub-efi-amd64 grub-efi-amd64-bin grub-common grub2-common shim-signed shim-signed-common"
# Conversion boots that came and went without converting; hifi-ab-image.sh
# stops re-arming at boot after a few of them.
FAILS="$LOCAL/convert-failures"
CMD="${1:-status}"
[ $# -gt 0 ] && shift

die() { ab_warn "$*"; exit 1; }

# The one-shot conversion boot is still to come: prepare's entry is in place
# and GRUB has not used next_entry yet. 00_header clears next_entry on the very
# boot that uses it, whatever that boot then does, so once that boot has
# happened this is false — converted or not.
conversion_pending() {
    [ -f "$GRUBD" ] || return 1
    grep -q '^next_entry=hifi-ab-convert$' "$LEGACY_GRUBENV" 2>/dev/null
}

# Undo prepare's lock on updates: the boot packages back under apt, the apt
# timers back on. It acts only while one of THESE packages is on hold, and
# nothing else on the appliance holds them, so it is idempotent, a no-op on a
# device that was never prepared, and it never turns back on timers an owner
# switched off on a device that never tried the conversion. dpkg-query, not
# `apt-mark showhold`: it runs at every legacy boot (from `finish`) and must
# not load the apt cache to find out there is nothing to do.
release_update_hold() {
    # shellcheck disable=SC2086  # list of packages
    _rel=$(dpkg-query -W -f='${db:Status-Want} ${Package}\n' $HOLD_PKGS 2>/dev/null \
        | awk '$1 == "hold" { printf " %s", $2 }')
    [ -n "$_rel" ] || return 0
    # shellcheck disable=SC2086  # list of packages
    if ! apt-mark unhold $_rel >/dev/null 2>&1; then
        ab_warn "apt-mark unhold failed:$_rel"
        return 0
    fi
    for _t in apt-daily.timer apt-daily-upgrade.timer; do
        [ "$(systemctl is-enabled "$_t" 2>/dev/null)" = disabled ] || continue
        # --no-block: this may run at boot, from a unit ordered before hifi-api
        systemctl enable --now --no-block "$_t" >/dev/null 2>&1 || ab_warn "could not re-enable $_t"
    done
    ab_log "kernel and bootloader updates unblocked again:$_rel"
}

# A conversion boot that came and went without converting (the initrd bailed
# out, or could not even record why): its one-shot entry and initrd are
# leftovers. Left in place they made hifi-ab-image.sh take the device as
# "already armed" for ever — no re-arm at boot, only at the next release.
disarm_conversion() {
    rm -f "$GRUBD" "$CONV_INITRD"
    update-grub >/dev/null 2>&1 || ab_warn "update-grub failed"
    # the initrd writes "failed" itself; "prepared" here means it could not
    if [ "$(ab_state_get 2>/dev/null)" = prepared ]; then ab_state_set failed; fi
    mkdir -p "$LOCAL"
    _n=$(cat "$FAILS" 2>/dev/null || echo 0)
    case "$_n" in ''|*[!0-9]*) _n=0 ;; esac
    printf '%s\n' "$((_n + 1))" > "$FAILS"
}

# `prepare` died after putting the hold on: nothing would ever lift it (the
# conversion boot `finish` waits for is not coming), so undo what it did.
prepare_abort() {
    if [ -f "$GRUBD" ]; then
        rm -f "$GRUBD"
        if grep -q '^next_entry=hifi-ab-convert$' "$LEGACY_GRUBENV" 2>/dev/null; then
            grub-editenv "$LEGACY_GRUBENV" unset next_entry 2>/dev/null || true
        fi
        update-grub >/dev/null 2>&1 || true
    fi
    rm -f "$CONV_INITRD"
    release_update_hold
}
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

# Passi della pulizia profonda, dal più innocuo al più invasivo. Servono solo
# sui dischi piccoli: la root legacy diventa lo slot A e resize2fs non scende
# sotto ~1,55 volte l'occupato, quindi ogni MiB liberato qui vale ~1,5 MiB in
# più per /data. Si tocca solo roba che l'immagine non ha comunque (doc, man,
# lingue) o che si ricrea da sola (cache di Lyrion); Electron va via soltanto
# se l'interfaccia in uso è quella Qt. Mai i firmware Wi-Fi/Bluetooth: servono
# a questo stesso avvio per scaricare l'immagine.
deep_step() {  # <passo>
    case "$1" in
        docs)
            rm -rf /usr/share/doc/* /usr/share/man/* /usr/share/info/* \
                   /usr/share/doc-base/* /usr/share/lintian/* 2>/dev/null || true
            find /usr/share/locale -mindepth 1 -maxdepth 1 -type d \
                 ! -name 'en*' ! -name 'it*' ! -name C -exec rm -rf {} + 2>/dev/null || true
            ;;
        firmware)
            for d in amdgpu radeon nvidia mellanox qed bnx2x liquidio netronome \
                     cxgb3 cxgb4 dpaa2 myricom qlogic; do
                rm -rf "/usr/lib/firmware/$d" 2>/dev/null || true
            done
            ;;
        lmscache)
            rm -rf /var/lib/squeezeboxserver/cache/* 2>/dev/null || true
            ;;
        electron)
            if [ "$(cat /etc/hifi-player/ui-engine 2>/dev/null)" != electron ] \
               && [ -d /opt/hifi-qt ]; then
                rm -rf /opt/hifi-media-player 2>/dev/null || true
            fi
            ;;
    esac
}

cmd_cleanup() {  # [--deep [minimo_MiB_da_raggiungere]]
    need_root
    ab_is_image && die "sono un'immagine: niente da pulire"
    deep=0; target=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --deep) deep=1 ;;
            ''|*[!0-9]*) ;;
            *) target=$1 ;;
        esac
        shift
    done
    before=$(df -Pm / | awk 'NR==2{print $3}')
    apt-get clean >/dev/null 2>&1 || true
    rm -rf /var/lib/apt/lists/* /var/cache/apt/*.bin 2>/dev/null || true
    rm -rf /opt/hifi-media-player.old /opt/hifi-qt.old 2>/dev/null || true
    rm -rf /var/lib/hifi-player/update/staged 2>/dev/null || true
    DEBIAN_FRONTEND=noninteractive apt-get -y autoremove --purge >/dev/null 2>&1 || true
    journalctl --vacuum-size=32M >/dev/null 2>&1 || true

    if [ "$deep" = 1 ]; then
        if [ "$target" -le 0 ]; then
            _amax=$(ab_slot_a_max_mib 2>/dev/null || echo 0)
            target=$(( _amax - AB_SLOT_A_MARGIN_MIN_MIB ))
        fi
        for step in docs firmware lmscache electron; do
            # shellcheck disable=SC2119  # the device argument is optional
            _now=$(ab_root_min_mib 2>/dev/null || echo 0)
            if [ "$target" -gt 0 ] && [ "$_now" -gt 0 ] && [ "$_now" -le "$target" ]; then
                ab_log "pulizia profonda: basta così (minimo root ${_now} MiB, tetto ${target})"
                break
            fi
            _u=$(df -Pm / | awk 'NR==2{print $3}')
            deep_step "$step"
            ab_log "pulizia profonda [$step]: liberati $(( _u - $(df -Pm / | awk 'NR==2{print $3}') )) MiB"
        done
    fi

    after=$(df -Pm / | awk 'NR==2{print $3}')
    # shellcheck disable=SC2119  # the device argument is optional
    _min=$(ab_root_min_mib 2>/dev/null || echo '?')
    ab_log "pulizia: root da ${before} a ${after} MiB usati (minimo tecnico ${_min} MiB)"
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
    # lo slot A lo dimensiona la pre-verifica (stima di resize2fs + margine)
    slot_a=$(sed -n 's/.*"slot_mib":\([0-9]*\).*/\1/p' /run/hifi-ab-precheck.json 2>/dev/null)
    [ -n "$slot_a" ] || slot_a=$AB_SLOT_MIB
    kver=$(uname -r)
    uuid=$(root_uuid)
    [ -n "$uuid" ] || die "UUID root sconosciuto"
    mkdir -p "$LOCAL"
    printf '%s\n' "$uuid" > "$LOCAL/legacy-uuid"

    ab_log "blocco degli aggiornamenti di kernel e bootloader durante la conversione"
    # Any `die` from here on lifts the hold again (prepare_abort); the trap is
    # cleared once the conversion is armed. When the conversion boot then does
    # not convert, `finish` lifts it.
    trap prepare_abort EXIT
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
    for must in scripts/local-premount/hifi-ab-convert sbin/hifi-sfdisk sbin/hifi-resize2fs sbin/hifi-mke2fs sbin/hifi-e2fsck; do
        lsinitramfs "$CONV_INITRD" | grep -qE "(^|/)${must}$" \
            || die "l'initrd di conversione non contiene $must"
    done

    ab_log "voce GRUB one-shot 'hifi-ab-convert'"
    # grub-reboot funziona solo con GRUB_DEFAULT=saved (00_header legge next_entry
    # dal grubenv): le ISO recenti non lo impostano, quindi lo si garantisce qui.
    if ! grep -q '^GRUB_DEFAULT=saved$' /etc/default/grub 2>/dev/null; then
        if grep -q '^GRUB_DEFAULT=' /etc/default/grub 2>/dev/null; then
            sed -i 's/^GRUB_DEFAULT=.*/GRUB_DEFAULT=saved/' /etc/default/grub
        else
            printf 'GRUB_DEFAULT=saved\n' >> /etc/default/grub
        fi
    fi
    grep -q '^GRUB_SAVEDEFAULT=' /etc/default/grub 2>/dev/null || printf 'GRUB_SAVEDEFAULT=false\n' >> /etc/default/grub
    cat > "$GRUBD" <<GRUBEOF
#!/bin/sh
exec tail -n +3 \$0
menuentry 'Osmium Sound — conversione A/B' --id hifi-ab-convert --class osmium {
	insmod part_gpt
	insmod ext2
	search --no-floppy --fs-uuid --set=root $uuid
	linux /boot/vmlinuz-$kver root=UUID=$uuid ro hifi.abconvert=1 hifi.abconvert.uuid=$uuid hifi.abconvert.slot_mib=$slot_a hifi.abconvert.slotb_mib=$AB_SLOT_B_MIB hifi.abconvert.datamin_mib=$AB_DATA_MIN_MIB panic=30 $(default_cmdline)
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
    trap - EXIT
    sync
    ab_log "pronto: al prossimo avvio la root viene ristretta a ${slot_a} MiB e nascono gli slot B (${AB_SLOT_B_MIB} MiB) e dati (1-5 min, NON spegnere)"
    if [ "$reboot" = 1 ]; then
        systemctl reboot
    fi
    return 0
}

cmd_finish() {
    need_root
    ab_is_image && exit 0
    if ! have_layout; then
        # Armed, and its boot is still to come: nothing to undo yet.
        conversion_pending && exit 0
        # The device stays legacy. A conversion boot that did not convert
        # leaves its entry and initrd behind (see disarm_conversion), and
        # prepare's hold on kernel/bootloader updates would last for ever:
        # both are undone here. hifi-ab-image.sh re-arms later in this boot
        # when the pre-checks pass.
        if [ -f "$GRUBD" ] || [ -f "$CONV_INITRD" ]; then
            st=$(ab_state_get 2>/dev/null || echo none)
            ab_warn "layout A/B assente dopo l'avvio di conversione (stato $st): vedi $AB_ESP_DIR/abconvert.log"
            disarm_conversion
        fi
        release_update_hold
        exit 0
    fi
    # hifi-data senza filesystem (mke2fs fallito nell'initrd): si formatta qui,
    # dove mke2fs.conf c'è di sicuro — la partizione è vuota per costruzione
    _data=$(ab_part_by_name hifi-data)
    if [ -z "$(blkid -o value -s TYPE "$_data" 2>/dev/null)" ]; then
        ab_log "hifi-data ($_data) senza filesystem: la formatto ext4"
        mkfs.ext4 -q -F -L hifi-data -O metadata_csum_seed "$_data" || die "mkfs.ext4 su $_data fallito"
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
    mkdir -p "$LOCAL"
    date -u +%Y-%m-%dT%H:%M:%SZ > "$LOCAL/finished"
    ab_state_set ready
    ab_log "conversione completata: pronto per la prima immagine (install <bundle>)"
    systemctl enable hifi-rauc-config.service hifi-boot-health.service hifi-boot-watchdog.timer hifi-ab-image.service >/dev/null 2>&1 || true
    # --no-block: la salute aspetta hifi-api, che parte DOPO questa unità
    # (Before=hifi-api): un avvio bloccante qui era uno stallo fino al timeout.
    systemctl start --no-block hifi-boot-health.service >/dev/null 2>&1 || true
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
    # The template's own first line says "A/B boot selector"; the older
    # Italian wording is still accepted for selectors written before it
    # changed. Matching only that one made every apt run on a converted
    # legacy root rewrite a perfectly good selector and log a warning.
    if ! grep -qE 'A/B boot selector|selettore di avvio A/B' "$AB_STUB" 2>/dev/null; then
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
    # Prima la musica, poi le impostazioni: le cartelle di musica o playlist
    # che stanno sulla root (sorgenti locali: /srv, /mnt, /media, /home) vanno
    # su /data adesso, perché la semina qui sotto copia i puntamenti verso di
    # loro (sorgenti, condivisioni Samba, preferenze di Lyrion).
    if [ -x /usr/local/sbin/hifi-ab-media.py ]; then
        ab_log "musica e playlist della root legacy verso /data"
        /usr/local/sbin/hifi-ab-media.py move || die "spostamento della musica su /data fallito"
    fi
    ab_log "semina di /data dalla root legacy"
    /usr/local/sbin/hifi-ab-seed.sh || die "semina fallita"
    # Download first when it fits on /data, as hifi-image-update.sh does: one
    # plain download is several times faster than RAUC's streaming.
    local_copy=""
    case "$bundle" in
        http://*|https://*)
            total=$(ab_url_size "$bundle")
            case "$total" in ''|*[!0-9]*) total=0 ;; esac
            if [ "$total" -gt 0 ] && ab_mount_data && mkdir -p "$AB_DL_DIR" \
                && ab_dl_room "$AB_DL_DIR" "$total"; then
                ab_log "download di $total byte in $AB_DL_DIR"
                if ab_download "$bundle" "$AB_DL_DIR/convert.raucb.part" "$total"; then
                    local_copy="$AB_DL_DIR/convert.raucb"
                    mv -f "$AB_DL_DIR/convert.raucb.part" "$local_copy"
                    trap 'rm -f "$local_copy"' EXIT
                    bundle=$local_copy
                else
                    ab_warn "download fallito: installo in streaming"
                fi
            else
                ab_warn "dimensione ignota o /data senza spazio: installo in streaming"
            fi
            ;;
    esac
    # Same reason as in hifi-image-update.sh: streaming asks the network for
    # one piece per read, and the kernel default (128 KiB) makes that
    # latency-bound. Tune the queues as soon as RAUC creates the devices.
    case "$bundle" in
        http://*|https://*)
            [ -x /usr/local/sbin/hifi-stream-tune.sh ] && \
                /usr/local/sbin/hifi-stream-tune.sh watch 1800 &
            ;;
    esac
    ab_log "rauc install $bundle (scrive lo slot B, il sistema in uso non cambia)"
    rc=0
    rauc install "$bundle" || rc=$?
    if [ -n "$local_copy" ]; then rm -f "$local_copy"; fi
    [ "$rc" = 0 ] || die "rauc install fallito"
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
    # 🚨 No shift here: the command word is already gone (see CMD above). A
    # second one ate --deep, so the apply runner's `cleanup --deep` never did
    # the deep part — and a bare `cleanup` died on "can't shift" under dash.
    cleanup)          cmd_cleanup "$@" ;;
    prepare)          cmd_prepare "$@" ;;
    finish)           cmd_finish ;;
    install)          cmd_install "$@" ;;
    select)           cmd_select ;;
    restore-selector) cmd_restore_selector ;;
    *) echo "uso: $0 status|cleanup [--deep]|prepare [--reboot]|finish|install <bundle> [--reboot]|select|restore-selector" >&2; exit 64 ;;
esac
