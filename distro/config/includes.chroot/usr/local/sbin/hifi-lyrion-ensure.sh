#!/bin/sh
# Osmium Sound — sugli slot immagine, se Lyrion non è ancora su /data lo
# scarica e lo installa con hifi-lyrion-update.sh (stesso .deb e stessa
# versione predefinita di build-distro.sh). Sostituisce hifi-firstboot.sh:
# lì era un `apt-get install` nella root, qui la root è in sola lettura.
set -u
LYRION_URL="${HIFI_LYRION_URL:-https://downloads.lms-community.org/LyrionMusicServer_v9.1.0/lyrionmusicserver_9.1.0_all.deb}"
[ -f /usr/lib/osmium/IMAGE_VERSION ] || exit 0
[ -x /data/lyrion/current/usr/sbin/squeezeboxserver ] && exit 0
ver=$(printf '%s' "$LYRION_URL" | sed -n 's/.*lyrionmusicserver_\([^_]*\)_all\.deb$/\1/p')
exec /usr/local/sbin/hifi-lyrion-update.sh "$LYRION_URL" "${ver:-unknown}"
