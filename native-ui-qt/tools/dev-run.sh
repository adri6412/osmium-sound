#!/bin/bash
# Avvia (o riavvia) il finto apparecchio sull'host e hifi-qt dentro il chroot
# sotto Xvfb. Log in $SP/run.log. Opzioni: MODE=WxH (default 1280x720),
# ARGS="--expanded" ecc.
SP=${HIFI_DEV_DIR:-/tmp/hifi-qt-dev}; mkdir -p $SP
R=/srv/trixie
MODE=${MODE:-1280x720}
curl -s -m 1 http://127.0.0.1:8000/vu_meter >/dev/null || { setsid nohup python3 /home/coder/osmium/hifi-media-player/native-ui-qt/tools/mock-server.py >$SP/mock.log 2>&1 < /dev/null & sleep 0.7; }
sudo pkill -f "[h]ifi-qt --assets" 2>/dev/null; sudo pkill -f "[X]vfb :99" 2>/dev/null; sleep 0.3
sudo mkdir -p $R/tmp/hifi-conf; echo it | sudo tee $R/tmp/hifi-conf/ui-language >/dev/null; echo 1 | sudo tee $R/tmp/hifi-conf/pointer-enabled >/dev/null
sudo rm -f $R/tmp/hifi-qt.cmd $R/tmp/hifi-qt.png
sudo chroot $R /bin/bash -c "export LC_ALL=C; Xvfb :99 -screen 0 ${MODE}x24 -nolisten tcp >/tmp/xvfb.log 2>&1 & sleep 0.8;
  cd /build/hifi-qt && DISPLAY=:99 QT_QPA_PLATFORM=xcb LIBGL_ALWAYS_SOFTWARE=1 HIFI_DEV=1 HIFI_CONFIG_DIR=/tmp/hifi-conf HIFI_WINDOW=$MODE \
  QT_LOGGING_RULES='qt.qml.binding.removal.info=false' nohup ./hifi-qt --assets /build/assets --locales /build/locales $ARGS >/tmp/hifi-qt.log 2>&1 &
  sleep ${WAIT:-3}; cat /tmp/hifi-qt.log"
