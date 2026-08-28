#!/bin/bash
# avvia/riavvia il finto apparecchio (il pattern di pkill sta qui dentro, non
# nella riga di comando esterna, se no pkill uccide anche la shell chiamante)
SP=${HIFI_DEV_DIR:-/tmp/hifi-qt-dev}; mkdir -p $SP
pkill -f "native-ui-qt/tools/mock-server.py" 2>/dev/null; sleep 0.3
setsid nohup python3 /home/coder/osmium/hifi-media-player/native-ui-qt/tools/mock-server.py > $SP/mock.log 2>&1 < /dev/null &
sleep 0.8
curl -s -m 2 http://127.0.0.1:8000/system_info | head -c 80; echo
