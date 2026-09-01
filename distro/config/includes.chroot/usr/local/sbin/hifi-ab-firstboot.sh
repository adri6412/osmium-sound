#!/bin/sh
# Osmium Sound — primo avvio di uno slot immagine su un apparecchio convertito:
# unisce gli account portati da hifi-ab-seed.sh (utente del wizard, hifimusic)
# a quelli dell'immagine, sistema la proprietà dei dati Lyrion (UID fisso 900
# nell'immagine, dinamico sul legacy) e riallinea l'interfaccia scelta.
# Gira PRIMA di sysinit (l'overlay di /etc è già su dall'initramfs); una volta
# sola per partizione dati (marcatore in /data/etc/upper).
set -u
# shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-ab-lib.sh
# shellcheck disable=SC1091  # percorso assoluto, esiste solo sull'apparecchio
. /usr/local/sbin/hifi-ab-lib.sh

D=$AB_DATA_MNT
X=$D/etc/accounts-extra
M=$D/etc/upper/.hifi-accounts-merged
[ -d "$X" ] || exit 0
[ -f "$M" ] && exit 0

merge_users() {  # <passwd|shadow>
    [ -s "$X/$1" ] || return 0
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        name=${line%%:*}
        getent "$1" "$name" >/dev/null 2>&1 && continue
        if [ "$1" = passwd ]; then
            uid=$(printf '%s' "$line" | cut -d: -f3)
            if getent passwd "$uid" >/dev/null 2>&1; then
                # UID già preso da un utente di sistema dell'immagine: se ne prende uno libero
                new=901; while getent passwd "$new" >/dev/null 2>&1; do new=$((new + 1)); done
                ab_warn "UID $uid di $name già in uso nell'immagine: rinumerato a $new"
                line=$(printf '%s' "$line" | awk -F: -v OFS=: -v u="$new" '{ $3 = u; print }')
            fi
        fi
        printf '%s\n' "$line" >> "/etc/$1"
    done < "$X/$1"
}
merge_groups() {  # <group|gshadow>
    [ -s "$X/$1" ] || return 0
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        gname=${line%%:*}
        members=${line##*:}
        if getent "$1" "$gname" >/dev/null 2>&1; then
            [ -n "$members" ] || continue
            for m in $(printf '%s' "$members" | tr ',' ' '); do
                getent passwd "$m" >/dev/null 2>&1 || continue
                if [ "$1" = group ]; then gpasswd -a "$m" "$gname" >/dev/null 2>&1 || true; fi
            done
        else
            printf '%s\n' "$line" >> "/etc/$1"
        fi
    done < "$X/$1"
}
merge_users passwd
merge_groups group
merge_users shadow
merge_groups gshadow
pwck -q -r >/dev/null 2>&1 || ab_warn "pwck segnala anomalie in passwd (non bloccante)"

# proprietà dei dati Lyrion: dall'UID legacy a quello dell'immagine
newuid=$(id -u squeezeboxserver 2>/dev/null || echo 900)
for p in /var/lib/squeezeboxserver /var/lib/lyrionmusicserver /var/log/squeezeboxserver; do
    [ -d "$p" ] && chown -R "$newuid:nogroup" "$p" 2>/dev/null
done
usermod -aG audio,cdrom squeezeboxserver 2>/dev/null || true

# Interface: the image ships the Qt one only (Electron was dropped to make
# room). A converted device brings its own /etc through the overlay, so the
# setting may still say "electron": honour it only if Electron is really
# installed, otherwise rewrite it to qt — leaving it would mean a black screen
# on the first boot of the new system.
eng=$(cat /etc/hifi-player/ui-engine 2>/dev/null || echo qt)
if [ "$eng" = electron ]; then
    if [ -d /opt/hifi-media-player ] && [ -x /usr/local/sbin/hifi-display-mode.sh ]; then
        /usr/local/sbin/hifi-display-mode.sh engine set electron >/dev/null 2>&1 || true
    else
        printf 'qt\n' > /etc/hifi-player/ui-engine
        ab_log "Electron non è nell'immagine: interfaccia riportata a Qt"
    fi
fi

date -u +%Y-%m-%dT%H:%M:%SZ > "$M"
ab_log "account uniti e proprietà sistemate (primo avvio dopo la conversione)"
exit 0
