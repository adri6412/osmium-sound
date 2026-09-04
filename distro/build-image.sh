#!/usr/bin/env bash
#
# build-image.sh — dal chroot di live-build all'immagine di uno slot A/B:
# root read-only (ext4) + bundle RAUC firmato (formato verity, delta a blocchi).
#
#   sudo ./build-image.sh --chroot distro/chroot --version v2.6.0 [opzioni]
#
# Normalmente lo chiama build-distro.sh (--stage image), dopo `lb chroot`.
# Lavora SUL chroot (non su una copia): dopo di qui il chroot non è più buono
# per un `lb binary` (via i pacchetti live, machine-id vuoto, initrd nuovo).
#
# Opzioni / ambiente:
#   --out DIR         cartella di uscita          (IMAGE_OUT, default: radice repo)
#   (root in SQUASHFS gzip: ~1,2 GB per 2,7 GiB di contenuto; lo slot RAUC è
#    `raw` e la partizione minima è AB_SLOT_B_MIB=1792 — vedi hifi-ab-lib.sh)
#   --cert F --key F  certificato/chiave di firma (RAUC_CERT / RAUC_KEY; PEM o
#                     contenuto PEM in RAUC_SIGNING_CERT / RAUC_SIGNING_KEY)
#   --keyring F       CA con cui verificare       (default distro/rauc-keys/keyring.pem)
#   --keep-rootfs     lascia anche rootfs.squashfs accanto al bundle
#
# Cosa fa (in ordine): via i pacchetti solo-live e apt automatico; rauc/zstd
# presenti; Lyrion come symlink verso /data/lyrion/current; utenti a UID fisso
# (sysusers); marcatori di versione fuori da /etc; initrd con overlay/squashfs/
# zstd/plymouth; grub.cfg statico dello slot; fstab dell'immagine; pulizia;
# mksquashfs riproducibile; rauc bundle + verifica contro la keyring.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CH=""
VERSION="${IMAGE_VERSION:-}"
OUT="${IMAGE_OUT:-$REPO_ROOT}"
SLOT_MIB="${AB_SLOT_B_MIB:-1280}"      # lo slot più piccolo: l'immagine deve starci con margine
                                       # (valore vero: AB_SLOT_B_MIB in hifi-ab-lib.sh, verificato più sotto)
CERT="${RAUC_CERT:-}"
KEY="${RAUC_KEY:-}"
KEYRING="${RAUC_KEYRING:-$SCRIPT_DIR/rauc-keys/keyring.pem}"
KEEP_EXT4=0
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(git -C "$REPO_ROOT" log -1 --format=%ct 2>/dev/null || date +%s)}"

log() { printf '\033[1;36m[hifi-image]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[hifi-image ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --chroot) CH="$2"; shift 2 ;;
        --version) VERSION="$2"; shift 2 ;;
        --out) OUT="$2"; shift 2 ;;
        --cert) CERT="$2"; shift 2 ;;
        --key) KEY="$2"; shift 2 ;;
        --keyring) KEYRING="$2"; shift 2 ;;
        --keep-rootfs|--keep-ext4) KEEP_EXT4=1; shift ;;
        -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "argomento sconosciuto: $1" ;;
    esac
done
[ "$(id -u)" -eq 0 ] || die "serve root"
if [ -z "$CH" ] || [ ! -d "$CH" ]; then die "--chroot DIR mancante"; fi
CH="$(cd "$CH" && pwd)"
[ -n "$VERSION" ] || die "--version mancante"
[ -x "$CH/usr/local/bin/api_server.py" ] || die "$CH non sembra il chroot dell'apparecchio"
[ -f "$KEYRING" ] || die "keyring RAUC mancante: $KEYRING"
for t in mksquashfs rauc zstd; do command -v "$t" >/dev/null || die "manca $t sull'host di build"; done
mkdir -p "$OUT"
SHARE="$CH/usr/local/share/hifi-ab"
[ -f "$SHARE/slot-grub.cfg.tmpl" ] || die "manca $SHARE/slot-grub.cfg.tmpl nel chroot"

# ── chiavi di firma: file, o contenuto PEM nell'ambiente (CI) ───────────
WORK="$(mktemp -d "${IMAGE_WORK:-/var/tmp}/hifi-image.XXXXXX")"
cleanup() {
    set +e
    for m in "$CH/dev" "$CH/sys" "$CH/proc" "$CH/run"; do
        mountpoint -q "$m" && umount -R "$m" 2>/dev/null
    done
    rm -f "$CH/usr/sbin/policy-rc.d" 2>/dev/null
    if [ -f "$WORK/resolv.conf.orig" ]; then cp -a "$WORK/resolv.conf.orig" "$CH/etc/resolv.conf"; else rm -f "$CH/etc/resolv.conf.hifi-tmp"; fi
    rm -rf "$WORK"
}
trap cleanup EXIT
if [ -z "$CERT" ] && [ -n "${RAUC_SIGNING_CERT:-}" ]; then printf '%s' "$RAUC_SIGNING_CERT" > "$WORK/cert.pem"; CERT="$WORK/cert.pem"; fi
if [ -z "$KEY" ] && [ -n "${RAUC_SIGNING_KEY:-}" ]; then printf '%s' "$RAUC_SIGNING_KEY" > "$WORK/key.pem"; KEY="$WORK/key.pem"; chmod 600 "$KEY"; fi
if [ -z "$CERT" ] || [ -z "$KEY" ]; then
    log "ATTENZIONE: nessuna chiave di firma — bundle firmato con una chiave usa-e-getta (gli apparecchi lo RIFIUTERANNO)"
    openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 2 -subj "/O=throwaway/CN=throwaway" \
        -keyout "$WORK/key.pem" -out "$WORK/cert.pem" >/dev/null 2>&1
    CERT="$WORK/cert.pem"; KEY="$WORK/key.pem"; KEYRING="$WORK/cert.pem"
fi

# ── chroot pronto per apt/systemctl/update-initramfs ────────────────────
# IMAGE_NO_MOUNTS=1: ambienti senza CAP_SYS_ADMIN (container di sviluppo);
# apt e update-initramfs nel chroot funzionano lo stesso per i nostri passi.
if [ "${IMAGE_NO_MOUNTS:-0}" != 1 ]; then
    mount -t proc proc "$CH/proc"
    mount --rbind /sys "$CH/sys"; mount --make-rslave "$CH/sys"
    mount --rbind /dev "$CH/dev"; mount --make-rslave "$CH/dev"
    mount -t tmpfs tmpfs "$CH/run"
fi
if [ -e "$CH/etc/resolv.conf" ] || [ -L "$CH/etc/resolv.conf" ]; then cp -a "$CH/etc/resolv.conf" "$WORK/resolv.conf.orig"; fi
rm -f "$CH/etc/resolv.conf"; cp /etc/resolv.conf "$CH/etc/resolv.conf"
printf '#!/bin/sh\nexit 101\n' > "$CH/usr/sbin/policy-rc.d"; chmod +x "$CH/usr/sbin/policy-rc.d"
in_chroot() {
    chroot "$CH" /usr/bin/env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
        DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8 HOME=/root "$@"
}

# ── 1. pacchetti: via quelli solo-live e l'apt automatico; dentro rauc/zstd ──
log "pacchetti: rimozione live-*/unattended, verifica rauc/zstd"
purge=()
for p in live-boot live-boot-initramfs-tools live-config live-config-systemd live-tools unattended-upgrades apt-listchanges; do
    in_chroot dpkg -s "$p" >/dev/null 2>&1 && purge+=("$p")
done
if [ ${#purge[@]} -gt 0 ]; then
    in_chroot apt-get -y -q purge "${purge[@]}" >/dev/null
fi
# busybox è ciò che dà all'initrd grep/sed/cp/tr (klibc da solo non li ha):
# nel chroot arriva come dipendenza di live-boot, che qui viene tolto, quindi
# va tenuto esplicitamente. e2fsprogs per il fsck di /data nell'initrd.
missing=()
for p in rauc rauc-service zstd busybox e2fsprogs initramfs-tools; do in_chroot dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p"); done
if [ ${#missing[@]} -gt 0 ]; then
    in_chroot apt-get -q update >/dev/null
    in_chroot apt-get -y -q install --no-install-recommends "${missing[@]}" >/dev/null
fi
in_chroot apt-mark manual busybox rauc rauc-service zstd >/dev/null 2>&1 || true
in_chroot apt-get -y -q autoremove --purge >/dev/null || true
in_chroot dpkg -s busybox >/dev/null 2>&1 || die "busybox mancante nel chroot: l'initrd non avrebbe grep/sed/cp"
in_chroot systemctl mask apt-daily.timer apt-daily-upgrade.timer apt-daily.service apt-daily-upgrade.service >/dev/null 2>&1 || true
# grub-common.service scrive /boot/grub/grubenv ("record successful boot"): su
# una root in sola lettura fallisce a ogni avvio, e l'ambiente GRUB che conta
# è quello del selettore sulla ESP.
in_chroot systemctl mask grub-common.service grub-initrd-fallback.service >/dev/null 2>&1 || true

# ── 2. ciò che in un'immagine non ha senso ─────────────────────────────
log "rimozione degli hook apt/kernel e dei marcatori legacy"
rm -f "$CH/etc/kernel/postinst.d/zzz-hifi-fix-efi-boot" "$CH/etc/apt/apt.conf.d/99-hifi-fix-efi-boot" \
      "$CH/etc/apt/apt.conf.d/52hifi-unattended"
rm -f "$CH/etc/systemd/system/hifi-firstboot.service" "$CH"/etc/systemd/system/*.wants/hifi-firstboot.service
rm -f "$CH/etc/hifi-player/OS_VERSION" "$CH/etc/hifi-player/SYSTEM_VERSION" "$CH/etc/hifi-player/UI_VERSION" \
      "$CH/etc/hifi-player/provisioning-pending"
rm -f "$CH/etc/rauc/system.conf"

# ── 3. Lyrion: symlink verso /data/lyrion/current, unità con condizione ──
log "Lyrion: symlink verso /data/lyrion/current"
mkdir -p "$CH/usr/share/perl5" "$CH/data" "$CH/boot/efi"
lyrion_links=(
    "usr/share/squeezeboxserver" "usr/share/perl5/Slim"
    "usr/sbin/squeezeboxserver" "usr/sbin/squeezeboxserver_safe" "usr/sbin/squeezeboxserver-scanner"
    "usr/sbin/squeezeboxserver-resized" "usr/sbin/squeezeboxserver-cleanup"
    "etc/squeezeboxserver" "etc/default/lyrionmusicserver"
)
for rel in "${lyrion_links[@]}"; do
    rm -rf "${CH:?}/$rel"
    ln -sfn "/data/lyrion/current/$rel" "$CH/$rel"
done
install -m 0644 "$SHARE/lyrionmusicserver.service" "$CH/usr/lib/systemd/system/lyrionmusicserver.service"
install -m 0644 "$SHARE/hifi-lyrion-ensure.service" "$CH/usr/lib/systemd/system/hifi-lyrion-ensure.service"
in_chroot systemctl enable lyrionmusicserver.service hifi-lyrion-ensure.service >/dev/null 2>&1
in_chroot systemctl enable hifi-rauc-config.service hifi-boot-health.service hifi-boot-watchdog.timer hifi-ab-firstboot.service >/dev/null 2>&1
in_chroot systemctl disable hifi-ab-finish.service >/dev/null 2>&1 || true

# ── 4. utenti a UID fisso, cartelle di stato ──────────────────────────────
in_chroot systemd-sysusers >/dev/null 2>&1 || die "systemd-sysusers fallito"
in_chroot id squeezeboxserver >/dev/null || die "utente squeezeboxserver non creato"
for d in var/lib/squeezeboxserver var/lib/squeezeboxserver/prefs var/lib/squeezeboxserver/cache var/lib/squeezeboxserver/playlists var/log/squeezeboxserver; do
    mkdir -p "$CH/$d"; in_chroot chown squeezeboxserver:nogroup "/$d"
done
mkdir -p "$CH/var/lib/hifi-player" "$CH/var/log/hifi" "$CH/mnt" "$CH/media"

# ── 5. RAUC: keyring; marcatori di versione fuori da /etc ────────────────
log "RAUC keyring, IMAGE_VERSION, elenco pacchetti"
mkdir -p "$CH/etc/rauc" "$CH/usr/lib/osmium" "$CH/etc/modules-load.d"
install -m 0644 "$KEYRING" "$CH/etc/rauc/keyring.pem"
# nbd: lo streaming HTTP di RAUC (rauc install https://…) crea un device NBD;
# caricato all'avvio così anche un `rauc install <url>` a mano funziona.
printf '# Osmium Sound: streaming dei bundle RAUC (rauc install https://...)\nnbd\n' > "$CH/etc/modules-load.d/hifi-rauc.conf"
printf '%s\n' "$VERSION" > "$CH/usr/lib/osmium/IMAGE_VERSION"
# shellcheck disable=SC2016  # le ${} sono per dpkg-query, non per la shell
in_chroot dpkg-query -W -f='${Package}\t${Version}\n' | sort > "$CH/usr/lib/osmium/packages.txt"
# Nomi soddisfatti dall'immagine: pacchetti installati E i loro Provides
# (es. libgcc-s1 fornisce libgcc1, che i .deb di Lyrion elencano ancora):
# è l'elenco contro cui l'aggiornatore Lyrion controlla le dipendenze.
# shellcheck disable=SC2016
in_chroot dpkg-query -W -f='${Package}\n${Provides}\n' \
    | tr ',' '\n' | sed 's/([^)]*)//g; s/^[[:space:]]*//; s/[[:space:]]*$//' | grep -v '^$' | sort -u \
    > "$CH/usr/lib/osmium/packages-provided.txt"
{
    echo "version=$VERSION"
    echo "built=$(date -u -d "@$SOURCE_DATE_EPOCH" +%Y-%m-%dT%H:%M:%SZ)"
    echo "git=$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
    echo "kernel=$(find "$CH/boot" -maxdepth 1 -name 'vmlinuz-*' | sed 's|.*/vmlinuz-||' | sort -V | tail -n 1)"
} > "$CH/usr/lib/osmium/BUILD_INFO"

# Package database of THIS image: hifi-ext.sh hands it to apt as the "already
# installed" set when it resolves an add-on. It cannot use /var/lib/dpkg/status
# on the device — /var lives on /data and still describes the first image ever
# installed there, so resolving against it would pull half the system down.
cp "$CH/var/lib/dpkg/status" "$CH/usr/lib/osmium/dpkg-status"

# SYSEXT_LEVEL is what pins an add-on to this exact image: systemd-sysext only
# merges extensions whose extension-release declares the same level, so one
# built for an older image is refused at boot instead of being layered over a
# system it was never resolved against (hifi-ext.sh refresh then rebuilds it).
if grep -q '^SYSEXT_LEVEL=' "$CH/usr/lib/os-release" 2>/dev/null; then
    sed -i "s|^SYSEXT_LEVEL=.*|SYSEXT_LEVEL=$VERSION|" "$CH/usr/lib/os-release"
else
    printf 'SYSEXT_LEVEL=%s\n' "$VERSION" >> "$CH/usr/lib/os-release"
fi
# Senza queste due unità gli add-on verrebbero costruiti e poi mai montati.
# Si abilitano UNA ALLA VOLTA: in blocco, se una fallisce, systemctl non
# installa nemmeno l'altra e l'errore resta nascosto (è successo alla prima
# build). L'esito di systemctl viene riportato nel messaggio, non ingoiato.
_out=$(in_chroot systemctl enable hifi-ext-refresh.service 2>&1) \
    || die "systemctl enable hifi-ext-refresh.service: $_out"
if ! _out=$(in_chroot systemctl enable systemd-sysext.service 2>&1); then
    # alcune build di systemd la distribuiscono senza sezione [Install]:
    # in quel caso il collegamento si fa a mano, il risultato è lo stesso
    log "systemd-sysext.service non abilitabile con systemctl ($_out), collegamento a mano"
    [ -e "$CH/usr/lib/systemd/system/systemd-sysext.service" ] \
        || die "systemd-sysext.service non esiste in questa immagine: systemd troppo vecchio per gli add-on"
    mkdir -p "$CH/etc/systemd/system/sysinit.target.wants"
    ln -sf /usr/lib/systemd/system/systemd-sysext.service \
        "$CH/etc/systemd/system/sysinit.target.wants/systemd-sysext.service"
fi
[ -e "$CH/etc/systemd/system/multi-user.target.wants/hifi-ext-refresh.service" ] \
    || die "hifi-ext-refresh.service non abilitata: gli add-on non verrebbero ricostruiti dopo un aggiornamento"
if ! in_chroot systemctl is-enabled systemd-sysext.service >/dev/null 2>&1 \
   && [ ! -e "$CH/etc/systemd/system/sysinit.target.wants/systemd-sysext.service" ]; then
    die "systemd-sysext.service non abilitata: gli add-on non verrebbero mai montati"
fi
mkdir -p "$CH/var/lib/extensions" "$CH/usr/share/factory/var/lib/hifi-player/ext"

# ── 5b. peso morto: firmware impossibili e la UI Electron ────────────────
# Misurato sull'immagine 2.5.24-dev.9-alpha2 (2715 MiB di contenuto): 855 MiB
# erano firmware e 354 la UI Electron. Qui si toglie ciò che su un mini PC x86
# audio non può servire, e l'interfaccia Electron, che dall'immagine in poi è
# sostituita da quella Qt (l'unica installata: vedi ui-engine qui sotto).
# NON si tocca amdgpu/radeon: esistono mini PC AMD e restare senza driver
# video sarebbe un guasto grave. Restano fuori dall'INITRD (vedi hook
# zz-hifi-slim più sotto), dove non servono a nessuno.
# La taglia dello slot vive in hifi-ab-lib.sh (la usano pre-verifica, initrd e
# installer): se qui se ne usasse un'altra, il tetto sull'immagine sarebbe
# calcolato su una partizione che nessuno crea davvero.
lib_slot=$(sed -n 's/^AB_SLOT_B_MIB="\${AB_SLOT_B_MIB:-\([0-9]*\)}"/\1/p' "$CH/usr/local/sbin/hifi-ab-lib.sh" 2>/dev/null | head -n 1)
if [ -n "$lib_slot" ] && [ "$lib_slot" != "$SLOT_MIB" ]; then
    die "taglia dello slot incoerente: build-image=$SLOT_MIB, hifi-ab-lib.sh=$lib_slot"
fi

log "rimozione dei firmware non pertinenti e della UI Electron"
fw_before=$(du -sxm "$CH/usr/lib/firmware" 2>/dev/null | cut -f1)
for d in netronome nvidia mrvl liquidio cxgb3 cxgb4 bnx2x qed mellanox mlxsw \
         dpaa2 imx qcom powervr myricom qlogic tehuti ueagle-atm; do
    rm -rf "${CH:?}/usr/lib/firmware/$d"
done
log "firmware: da ${fw_before:-?} a $(du -sxm "$CH/usr/lib/firmware" 2>/dev/null | cut -f1) MiB"
rm -rf "${CH:?}/opt/hifi-media-player" "${CH:?}/opt/hifi-media-player.old"
# L'immagine ha una sola interfaccia: quella Qt. La scelta sta in
# /etc/hifi-player/ui-engine, che su un apparecchio convertito arriva
# dall'overlay del legacy e può dire "electron": chi la legge deve ripiegare
# su qt quando Electron non c'è (api_server.get_ui_engine, hifi-display-mode,
# hifi-ab-firstboot), e qui si semina comunque il valore giusto nel lower.
mkdir -p "$CH/etc/hifi-player"
printf 'qt
' > "$CH/etc/hifi-player/ui-engine"
[ -x "$CH/opt/hifi-qt/hifi-qt" ] || die "manca /opt/hifi-qt/hifi-qt: senza Electron l'immagine resterebbe senza interfaccia"

# ── 6. initrd: overlay/vfat, tutti i moduli, zstd, plymouth ──────────────
log "initrd dell'immagine (MODULES=most, zstd, plymouth)"
# Il repo non conserva i bit di esecuzione (core.filemode=false, file nati su
# Windows): mkinitramfs IGNORA in silenzio gli hook non eseguibili, e gli
# script hifi-* vanno resi eseguibili come fa l'hook 0300 per quelli legacy.
chmod +x "$CH/etc/initramfs-tools/hooks/hifi-state" "$CH/etc/initramfs-tools/scripts/local-bottom/hifi-state" \
    "$SHARE/initramfs/hooks/hifi-ab" "$SHARE/initramfs/scripts/local-premount/hifi-ab-convert"
chmod +x "$CH"/usr/local/sbin/hifi-*.sh "$CH"/usr/local/sbin/hifi-*.py "$CH"/usr/local/bin/*.py 2>/dev/null || true
mkdir -p "$CH/etc/initramfs-tools/conf.d"
cat > "$CH/etc/initramfs-tools/conf.d/hifi-image.conf" <<'CONF'
# Osmium Sound — initrd degli slot immagine: costruito in fabbrica, deve
# avviare qualunque mini PC della flotta (niente MODULES=dep), con overlayfs
# per /etc, vfat per la ESP e plymouth (FRAMEBUFFER=y: in chroot non c'è
# `splash` sulla riga di comando del kernel, e l'hook lo salterebbe).
MODULES=most
COMPRESS=zstd
FRAMEBUFFER=y
CONF
for m in overlay squashfs vfat nls_cp437 nls_ascii nls_utf8 ext4; do
    grep -qx "$m" "$CH/etc/initramfs-tools/modules" 2>/dev/null || echo "$m" >> "$CH/etc/initramfs-tools/modules"
done
# MODULES=most porta dentro quasi tutti i driver e con loro i loro firmware:
# nell'immagine misurata erano 201 MiB su 304 dell'initrd scompattato (80 di
# amdgpu, 63 di nvidia, 25 di netronome). Nell'initrd non servono: lì si deve
# solo montare la root, e le GPU prendono il firmware dal sistema vero dopo il
# pivot. Si tengono i firmware degli Intel (i915/xe: plymouth disegna la
# schermata di avvio con KMS) e tutto il resto se ne va, moduli GPU compresi
# così nessun driver fallisce la sonda per firmware mancante e riprova più
# tardi dalla root vera.
cat > "$CH/usr/share/initramfs-tools/hooks/zz-hifi-slim" <<'HOOK'
#!/bin/sh
# Osmium Sound — trims the initramfs: GPU/server firmware has no job before
# the root is mounted (see build-image.sh). Runs last (zz-) so everything
# else has already been copied in.
PREREQ=""
prereqs() { echo "$PREREQ"; }
case "${1:-}" in prereqs) prereqs; exit 0 ;; esac
. /usr/share/initramfs-tools/hook-functions
for d in amdgpu radeon nvidia amd nouveau; do
    rm -rf "$DESTDIR/usr/lib/firmware/$d" "$DESTDIR/lib/firmware/$d"
done
for m in amdgpu radeon nouveau nvidia; do
    find "$DESTDIR" -name "$m.ko*" -delete 2>/dev/null || true
done
exit 0
HOOK
chmod +x "$CH/usr/share/initramfs-tools/hooks/zz-hifi-slim"

kvers=$(find "$CH/boot" -maxdepth 1 -name 'vmlinuz-*' | sed 's|.*/vmlinuz-||' | sort -V)
KVER=$(printf '%s\n' "$kvers" | tail -n 1)
[ -n "$KVER" ] || die "nessun kernel in $CH/boot"
if [ "$(printf '%s\n' "$kvers" | wc -l)" -gt 1 ]; then
    for k in $kvers; do
        [ "$k" = "$KVER" ] && continue
        log "kernel in più: $k — rimosso dall'immagine"
        in_chroot apt-get -y -q purge "linux-image-$k" >/dev/null 2>&1 || rm -f "$CH/boot/vmlinuz-$k" "$CH/boot/initrd.img-$k"
    done
fi
rm -f "$CH/boot/initrd.img-$KVER"
in_chroot update-initramfs -c -k "$KVER" 2>&1 | tail -n 20 || true
[ -s "$CH/boot/initrd.img-$KVER" ] || die "initrd non prodotto"
ls -la "$CH/boot/"
# L'initrd viene letto dall'HOST (initramfs-tools-core + zstd sull'host di
# build): lsinitramfs dentro il chroot ha dato "unmkinitramfs: zstd failed"
# in CI, e comunque un elenco fatto da fuori è una verifica più onesta.
if command -v lsinitramfs >/dev/null 2>&1; then
    LSINIT="lsinitramfs $CH/boot/initrd.img-$KVER"
else
    LSINIT="in_chroot lsinitramfs /boot/initrd.img-$KVER"
fi
$LSINIT > "$WORK/initrd.list" 2> "$WORK/initrd.err" || { cat "$WORK/initrd.err" >&2; die "impossibile elencare l'initrd"; }
log "initrd: $(wc -l < "$WORK/initrd.list") voci, $(du -h "$CH/boot/initrd.img-$KVER" | cut -f1)"
for must in "scripts/local-bottom/hifi-state" "overlay.ko" "bin/busybox\$" "sbin/e2fsck\$" "bin/plymouth\$"; do
    grep -qE "$must" "$WORK/initrd.list" || { grep -E "hifi|busybox|e2fsck|overlay|plymouth" "$WORK/initrd.list" | head -n 20 >&2; die "l'initrd non contiene $must"; }
done

# ── 7. grub.cfg statico dello slot; fstab; machine-id vuoto ───────────────
log "grub.cfg dello slot (kernel $KVER), fstab, machine-id"
CMDLINE=$(sed -n 's/^GRUB_CMDLINE_LINUX_DEFAULT="\(.*\)"$/\1/p' "$CH/etc/default/grub" | tail -n 1)
[ -n "$CMDLINE" ] || CMDLINE="quiet splash loglevel=0"
mkdir -p "$CH/boot/grub"
sed -e "s|@KVER@|$KVER|g" -e "s|@CMDLINE@|$CMDLINE|g" "$SHARE/slot-grub.cfg.tmpl" > "$CH/boot/grub/grub.cfg"
if command -v grub-script-check >/dev/null 2>&1; then grub-script-check "$CH/boot/grub/grub.cfg" || die "grub.cfg dello slot non valido"; fi
# /vmlinuz e /initrd.img (symlink Debian) restano: comodi per il ramo legacy del selettore
cat > "$CH/etc/fstab" <<'FSTAB'
# /etc/fstab — immagine Osmium Sound (slot A/B, root in sola lettura).
# La root (squashfs, sola lettura), /data (PARTLABEL hifi-data, stesso disco), l'overlay di /etc, i bind
# di /var e /home e la ESP su /boot/efi li monta l'initramfs
# (scripts/local-bottom/hifi-state) PRIMA che parta systemd: qui restano solo
# i punti di montaggio effimeri.
tmpfs  /mnt    tmpfs  mode=0755,nosuid,nodev  0  0
tmpfs  /media  tmpfs  mode=0755,nosuid,nodev  0  0
FSTAB
: > "$CH/etc/machine-id"
rm -f "$CH/var/lib/dbus/machine-id"

# ── 8. pulizia ───────────────────────────────────────────────────────────
log "pulizia (apt, doc/man/info, locale, log)"
in_chroot apt-get clean >/dev/null
rm -rf "$CH"/var/lib/apt/lists/* "$CH"/var/cache/apt/*.bin "$CH"/var/cache/debconf/*-old "$CH"/var/lib/dpkg/*-old
find "$CH/usr/share/doc" -mindepth 2 -type f ! -name copyright -delete 2>/dev/null || true
find "$CH/usr/share/doc" -mindepth 1 -type d -empty -delete 2>/dev/null || true
rm -rf "$CH"/usr/share/man/* "$CH"/usr/share/info/* "$CH"/usr/share/lintian
find "$CH/usr/share/locale" -mindepth 1 -maxdepth 1 -type d ! -name 'en*' ! -name 'it*' -exec rm -rf {} + 2>/dev/null || true
find "$CH/var/log" -type f -exec truncate -s 0 {} + 2>/dev/null || true
rm -rf "$CH"/tmp/* "$CH"/var/tmp/* "$CH"/root/.cache "$CH"/root/.bash_history
rm -f "$CH/usr/sbin/policy-rc.d"
if [ -f "$WORK/resolv.conf.orig" ]; then cp -a "$WORK/resolv.conf.orig" "$CH/etc/resolv.conf"; rm -f "$WORK/resolv.conf.orig"; else rm -f "$CH/etc/resolv.conf"; ln -s /run/NetworkManager/resolv.conf "$CH/etc/resolv.conf"; fi
if [ "${IMAGE_NO_MOUNTS:-0}" != 1 ]; then
    for m in "$CH/run" "$CH/dev" "$CH/sys" "$CH/proc"; do umount -R "$m"; done
fi

used_mib=$(du -sxm "$CH" | cut -f1)
log "contenuto immagine: ${used_mib} MiB"

# ── 9. rootfs.squashfs (sola lettura, gzip) ───────────────────────────────
# Squashfs invece di ext4: la root è comunque in sola lettura e così pesa un
# terzo (slot da 1,75 GiB invece di 4). Il prezzo: ogni aggiornamento è un
# download intero (~1,2 GB, i delta a blocchi non mordono su dati compressi) e
# niente `remount,rw` di prova.
# 🚨 Compressione GZIP, non zstd: il kernel e l'initrd dello slot li legge GRUB
# (`configfile (slot)/boot/grub/grub.cfg` dal selettore sulla ESP) e il modulo
# squash4 di GRUB 2.12 (Debian trixie, 2.12-9+deb13u2) apre solo gzip e xz:
# con zstd o lz4 risponde "unknown filesystem", lo slot non parte mai e il
# selettore ricade sull'altro (visto sul Dell il 2026-09-01, verificato con
# grub-fstest). xz sarebbe più piccolo ma la decompressione a runtime pesa
# troppo sul J4105; gzip -9 costa ~10% di spazio in più di zstd.
log "mksquashfs (gzip -9, blocchi da 256K)"
SQ="$WORK/rootfs.squashfs"
rm -f "$SQ"
SOURCE_DATE_EPOCH="$SOURCE_DATE_EPOCH" mksquashfs "$CH" "$SQ" -comp gzip -Xcompression-level 9 -b 256K \
    -noappend -no-progress -xattrs -no-recovery >/dev/null || die "mksquashfs fallito"
# Prova del nove con lo stesso codice squash4 di GRUB: se grub-fstest non apre
# il grub.cfg dello slot, neanche grubx64.efi lo farà. Id compressione nel
# superblocco (offset 20): 1=gzip 4=xz leggibili; 6=zstd 5=lz4 no.
sq_comp=$(od -An -tu2 -j20 -N2 "$SQ" | tr -d ' ')
case "$sq_comp" in 1|4) ;; *) die "rootfs.squashfs con compressione id=$sq_comp: GRUB squash4 legge solo gzip(1)/xz(4)";; esac
if command -v grub-fstest >/dev/null; then
    grub-fstest "$SQ" cat /boot/grub/grub.cfg 2>&1 | grep -q '^linux ' \
        || die "grub-fstest non legge /boot/grub/grub.cfg dal rootfs.squashfs: GRUB non avvierebbe lo slot"
    log "grub-fstest: il grub.cfg dello slot è leggibile dal squash4 di GRUB"
else
    log "ATTENZIONE: grub-fstest assente sull'host, salto la verifica di lettura GRUB del squashfs"
fi
sq_mib=$(du -m "$SQ" | cut -f1)
budget=$(( SLOT_MIB * 90 / 100 ))
log "rootfs.squashfs: ${sq_mib} MiB (slot minimo ${SLOT_MIB} MiB, tetto ${budget})"
if [ "$sq_mib" -gt "$budget" ]; then
    du -xm --max-depth=2 "$CH" | sort -n | tail -n 15 >&2
    die "l'immagine supera il tetto: ${sq_mib} > ${budget} MiB"
fi

# ── 10. bundle RAUC ─────────────────────────────────────────────────────
log "rauc bundle (verity, adaptive block-hash-index)"
B="$WORK/bundle"; mkdir -p "$B"
sed -e "s|@VERSION@|$VERSION|g" "$SCRIPT_DIR/rauc/manifest.raucm.tmpl" > "$B/manifest.raucm"
install -m 0755 "$SCRIPT_DIR/rauc/hook.sh" "$B/hook.sh"
mv "$SQ" "$B/rootfs.squashfs"
RAUCB="$OUT/hifi-image-${VERSION}.raucb"
rm -f "$RAUCB"
rauc bundle --cert "$CERT" --key "$KEY" --signing-keyring "$KEYRING" "$B" "$RAUCB" || die "rauc bundle fallito"
rauc info --keyring "$KEYRING" "$RAUCB" > "$OUT/hifi-image-${VERSION}.info.txt" || die "il bundle non si verifica con la keyring $KEYRING"
( cd "$OUT" && sha256sum "$(basename "$RAUCB")" > "$(basename "$RAUCB").sha256" )
if [ "$KEEP_EXT4" = 1 ]; then
    cp "$B/rootfs.squashfs" "$OUT/hifi-image-${VERSION}.rootfs.squashfs"
fi
cp "$CH/usr/lib/osmium/BUILD_INFO" "$OUT/hifi-image-${VERSION}.build-info.txt"
log "DONE ✓  $RAUCB"
ls -lh "$OUT"/hifi-image-"${VERSION}".*
head -n 20 "$OUT/hifi-image-${VERSION}.info.txt"
