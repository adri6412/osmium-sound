#!/bin/sh
# Osmium Sound — installa Lyrion Music Server su /data quando manca, e SOLO
# nei casi in cui l'apparecchio ne ha davvero bisogno.
#
# 🚨 Non è un'installazione automatica di primo avvio: quella la decide il
# wizard di configurazione (passo "Lyrion", step-lyrion-install), che chiede
# se il server lo fa questo apparecchio o se ne segue uno già presente in
# rete, e nel primo caso lo installa mostrando canale e avanzamento. Se questo
# script partisse comunque, un apparecchio appena installato si troverebbe il
# server scaricato senza averlo scelto — e chi ha detto "seguo il server di
# un'altra stanza" si sarebbe scaricato 90 MB da buttare.
#
# Resta come rete di sicurezza per un apparecchio GIÀ configurato in modalità
# locale che si ritrova senza server (installazione fallita a metà, o /data
# rimasta senza), e sostituisce hifi-firstboot.sh: lì era un `apt-get install`
# nella root, qui la root è in sola lettura.
set -u
LYRION_URL="${HIFI_LYRION_URL:-https://downloads.lms-community.org/LyrionMusicServer_v9.1.0/lyrionmusicserver_9.1.0_all.deb}"
SQ_DEFAULT="${HIFI_SQ_DEFAULT:-/etc/default/squeezelite}"
CMDLINE="${HIFI_CMDLINE:-/proc/cmdline}"
CONFIG_DIR="${HIFI_CONFIG_DIR:-/etc/hifi-player}"
UPDATER="${HIFI_LYRION_UPDATE:-/usr/local/sbin/hifi-lyrion-update.sh}"

[ -f "${HIFI_IMAGE_VERSION_FILE:-/usr/lib/osmium/IMAGE_VERSION}" ] || exit 0
[ -x "${HIFI_LYRION_CURRENT:-/data/lyrion/current}/usr/sbin/squeezeboxserver" ] && exit 0

# Sessione live ("Prova Osmium Sound"): non c'è niente da conservare e il
# pacchetto finirebbe in memoria. L'unità legacy aveva la stessa guardia.
grep -qw 'boot=live' "$CMDLINE" 2>/dev/null && exit 0

# Configurazione ancora da fare: è il wizard che deve chiedere e installare.
[ -e "$CONFIG_DIR/provisioning-pending" ] && exit 0

# Modalità "segui un altro server": squeezelite punta a un host che non è
# questo (api_server.py get_lms_role legge lo stesso -s). Qui un server locale
# non serve e nessuno lo avvierebbe.
sq_host=$(sed -n "s/^ARGS=.*[[:space:]]-s[[:space:]]\{1,\}\([^[:space:]'\"]\{1,\}\).*/\1/p" \
          "$SQ_DEFAULT" 2>/dev/null | head -n 1)
case "${sq_host:-127.0.0.1}" in
    127.0.0.1|localhost) : ;;
    *) exit 0 ;;
esac

ver=$(printf '%s' "$LYRION_URL" | sed -n 's/.*lyrionmusicserver_\([^_]*\)_all\.deb$/\1/p')
exec "$UPDATER" "$LYRION_URL" "${ver:-unknown}"
