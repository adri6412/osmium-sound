#!/bin/sh
# Osmium Sound — porta lo stato dell'apparecchio dalla root legacy (in uso) alla
# partizione dati, nella forma che gli slot immagine si aspettano:
#   /data/etc/upper/…        upper dell'overlay di /etc (file di stato)
#   /data/etc/accounts-extra utenti/gruppi da unire a quelli dell'immagine
#                            (li unisce hifi-ab-firstboot.sh al primo avvio)
#   /data/var/…              stato in /var (Lyrion, hifi-player, samba, bluetooth)
#   /data/home/…             /home/hifi/.config e le home degli utenti del wizard
#   /data/lyrion/<ver>/…     Lyrion installato con dpkg, copiato tale e quale
# Ripetibile (cp -au): si esegue prima di `rauc install` e di nuovo un attimo
# prima del riavvio, così lo stato è quello dell'ultimo momento.
set -u
# shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-ab-lib.sh
# shellcheck disable=SC1091  # percorso assoluto, esiste solo sull'apparecchio
. /usr/local/sbin/hifi-ab-lib.sh

ab_is_image && { ab_warn "sono già un'immagine: niente da seminare"; exit 0; }
ab_mount_data || { ab_warn "/data non montabile"; exit 1; }
D=$AB_DATA_MNT
U=$D/etc/upper
mkdir -p "$U" "$D/etc/work" "$D/etc/accounts-extra" "$D/var/lib" "$D/var/log" "$D/home" "$D/lyrion" "$D/rauc"

copy_etc() {  # <percorso relativo a /etc> (file, dir o symlink)
    [ -e "/etc/$1" ] || [ -L "/etc/$1" ] || return 0
    mkdir -p "$U/$(dirname "$1")"
    cp -au "/etc/$1" "$U/$(dirname "$1")/" 2>/dev/null || ab_warn "copia di /etc/$1 incompleta"
}
for f in hifi-player hifi-sources.json hifi-pairing-tokens.json \
         NetworkManager/system-connections hostname hosts machine-id \
         timezone localtime default/squeezelite \
         samba/hifi-shares.conf avahi/services/hifi-smb.service camilladsp; do
    copy_etc "$f"
done
for k in /etc/ssh/ssh_host_*; do
    [ -e "$k" ] && copy_etc "ssh/$(basename "$k")"
done
# /etc/squeezeboxserver e /etc/default/lyrionmusicserver NON vanno nell'upper:
# nell'immagine sono symlink verso /data/lyrion/current (copiati là sotto).
# I marcatori di versione legacy non hanno senso su un'immagine (li legge
# /usr/lib/osmium/IMAGE_VERSION) e ombreggerebbero: via dall'upper.
rm -f "$U/hifi-player/OS_VERSION" "$U/hifi-player/SYSTEM_VERSION" "$U/hifi-player/UI_VERSION"
# L'upper NON deve portare la chiave ota-pubkey del legacy né system.conf: l'immagine ha i propri.
rm -rf "$U/rauc"

# ── account: utenti del wizard (UID >= 1000, non hifi) e hifimusic ────────
: > "$D/etc/accounts-extra/passwd"; : > "$D/etc/accounts-extra/shadow"
: > "$D/etc/accounts-extra/group";  : > "$D/etc/accounts-extra/gshadow"
users=""
# shellcheck disable=SC2094  # si legge /etc/passwd e si scrive su un altro file
while IFS=: read -r name _ uid _ _ _ _; do
    if { [ "$uid" -ge 1000 ] && [ "$uid" -lt 60000 ] && [ "$name" != hifi ]; } || [ "$name" = hifimusic ]; then
        users="$users $name"
        grep "^$name:" /etc/passwd >> "$D/etc/accounts-extra/passwd"
        grep "^$name:" /etc/shadow >> "$D/etc/accounts-extra/shadow" 2>/dev/null || true
    fi
done < /etc/passwd
# gruppi: quelli propri di questi utenti e quelli di cui sono membri
# shellcheck disable=SC2094  # idem per /etc/group
while IFS=: read -r gname _ _ members; do
    keep=0
    for u in $users; do
        [ "$gname" = "$u" ] && keep=1
        case ",$members," in *",$u,"*) keep=1 ;; esac
    done
    [ "$keep" = 1 ] || continue
    grep "^$gname:" /etc/group >> "$D/etc/accounts-extra/group"
    grep "^$gname:" /etc/gshadow >> "$D/etc/accounts-extra/gshadow" 2>/dev/null || true
done < /etc/group
chmod 600 "$D/etc/accounts-extra/shadow" "$D/etc/accounts-extra/gshadow"
printf '%s\n' "$(id -u squeezeboxserver 2>/dev/null || echo 103)" > "$D/etc/accounts-extra/legacy-squeezeboxserver-uid"

# ── /var ──────────────────────────────────────────────────────────────
for d in lib/hifi-player lib/squeezeboxserver lib/lyrionmusicserver lib/bluetooth lib/samba lib/NetworkManager log/hifi; do
    [ -d "/var/$d" ] || continue
    mkdir -p "$D/var/$d"
    cp -au "/var/$d/." "$D/var/$d/" 2>/dev/null || ab_warn "copia di /var/$d incompleta"
done
rm -rf "$D/var/lib/hifi-player/update" 2>/dev/null || true
# nessun marcatore: al primo avvio l'initramfs aggiunge (senza sovrascrivere)
# la /var dell'immagine — dpkg, systemd, cache — a quella seminata qui

# ── /home: la .config di hifi (stato Electron) e le home degli utenti wizard ──
if [ -d /home/hifi/.config ]; then
    mkdir -p "$D/home/hifi/.config"
    cp -au /home/hifi/.config/. "$D/home/hifi/.config/" 2>/dev/null || true
    chown -R 1000:1000 "$D/home/hifi" 2>/dev/null || true
fi
for u in $users; do
    h=$(getent passwd "$u" | cut -d: -f6)
    if [ -z "$h" ] || [ ! -d "$h" ] || [ "${h#/home/}" = "$h" ]; then continue; fi
    mkdir -p "$D/home/$(basename "$h")"
    cp -au "$h/." "$D/home/$(basename "$h")/" 2>/dev/null || true
done

# ── Lyrion: l'albero installato con dpkg, così com'è, sotto /data/lyrion/<ver> ──
if dpkg -s lyrionmusicserver >/dev/null 2>&1; then
    ver=$(dpkg-query -W -f='${Version}' lyrionmusicserver 2>/dev/null || echo unknown)
    L="$D/lyrion/$ver"
    mkdir -p "$L"
    dpkg -L lyrionmusicserver | while IFS= read -r p; do
        case "$p" in /usr/share/doc/*|/usr/share/lintian/*|/.|/usr|/usr/share|/usr/sbin|/etc|/lib|/lib/systemd|/lib/systemd/system|/etc/default|/etc/init.d|/etc/logrotate.d) continue ;; esac
        if [ -d "$p" ] && [ ! -L "$p" ]; then
            mkdir -p "$L$p"
        elif [ -e "$p" ] || [ -L "$p" ]; then
            mkdir -p "$L$(dirname "$p")"
            cp -au "$p" "$L$(dirname "$p")/" 2>/dev/null || true
        fi
    done
    # /etc/squeezeboxserver è conffile: la versione viva (magari modificata) vince
    [ -d /etc/squeezeboxserver ] && { mkdir -p "$L/etc"; cp -au /etc/squeezeboxserver "$L/etc/"; }
    printf '%s\n' "$ver" > "$L/VERSION"
    ln -sfn "$ver" "$D/lyrion/current"
    ab_log "Lyrion $ver copiato in $L"
fi

date -u +%Y-%m-%dT%H:%M:%SZ > "$D/.seeded-from-legacy"
sync
ab_log "semina di /data completata (utenti extra:${users:- nessuno})"
exit 0
