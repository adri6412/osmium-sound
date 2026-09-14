#!/bin/bash
# Avvia hifi-qt sul Dell al posto della UI in C (collaudo). Opzioni:
#   MODE=720|1080   modo video via QT_QPA_EGLFS_KMS_CONFIG (default: nativo)
#   ARGS="..."      argomenti aggiuntivi (--expanded, --wizard setup ...)
#   SECONDS=N       esce da solo dopo N secondi
# Ferma con: tools/devrun.sh stop   (ripristina hifi-native-ui)
set -u
cd /home/ssh/native-ui-qt
# sudo senza terminale: la password dell'utente di collaudo (SUDOPASS)
SUDOPASS=${SUDOPASS:-ssh123456}
S() { echo "$SUDOPASS" | sudo -S -p "" "$@"; }
if [ "${1:-}" = "stop" ]; then
    S pkill -f "./hifi-qt --assets" 2>/dev/null; sleep 1
    S systemctl start hifi-native-ui
    echo "hifi-qt fermato, UI in C ripristinata"; exit 0
fi
S systemctl stop hifi-native-ui 2>/dev/null
S pkill -f "./hifi-qt --assets" 2>/dev/null; sleep 0.8
export QT_QPA_PLATFORM=eglfs QT_QPA_EGLFS_ALWAYS_SET_MODE=1
export QT_QPA_EGLFS_HIDECURSOR=1
if [ -n "${MODE:-}" ]; then
    # nome del connettore come lo vuole Qt (HDMI1, DP1, eDP1), non come sysfs (HDMI-A-1)
    CONN=$(for c in /sys/class/drm/card*-*; do [ "$(cat $c/status 2>/dev/null)" = connected ] && basename $c | sed 's/^card[0-9]*-//; s/-A-/-/; s/-//g'; done | head -1)
    case "$MODE" in 720) M="1280x720";; 1080) M="1920x1080";; *) M="$MODE";; esac
    printf '{"device":"/dev/dri/card0","outputs":[{"name":"%s","mode":"%s"}]}\n' "$CONN" "$M" > /tmp/kms.json
    export QT_QPA_EGLFS_KMS_CONFIG=/tmp/kms.json
fi
export HIFI_DEV=1
[ -n "${SECONDS_RUN:-}" ] && export HIFI_QT_SECONDS=$SECONDS_RUN
rm -f /tmp/hifi-qt.cmd /tmp/hifi-qt.png
echo "$SUDOPASS" | sudo -S -p "" -E env "PATH=$PATH" QT_QPA_PLATFORM=eglfs QT_QPA_EGLFS_ALWAYS_SET_MODE=1 QT_QPA_EGLFS_HIDECURSOR=1 ${QT_QPA_EGLFS_KMS_CONFIG:+QT_QPA_EGLFS_KMS_CONFIG=$QT_QPA_EGLFS_KMS_CONFIG} HIFI_DEV=1 QSG_INFO=1 ${HIFI_CONFIG_DIR:+HIFI_CONFIG_DIR=$HIFI_CONFIG_DIR} ${HIFI_QT_SECONDS:+HIFI_QT_SECONDS=$HIFI_QT_SECONDS} \
    ./hifi-qt --assets /opt/hifi-native-ui/assets --locales /opt/hifi-native-ui/locales ${ARGS:-} > /tmp/hifi-qt.log 2>&1 &
sleep ${WAIT:-4}
pgrep -f "hifi-qt --assets" >/dev/null && echo "hifi-qt in esecuzione" || { echo "NON PARTITO:"; head -30 /tmp/hifi-qt.log; }
