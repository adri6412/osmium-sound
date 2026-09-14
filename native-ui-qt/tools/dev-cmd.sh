#!/bin/bash
# Manda comandi al canale di collaudo dentro il chroot e recupera la foto.
#   dev-cmd.sh "tap 100 200" "sleep 0.5" "shot" [OUT=nome.png]
# "sleep N" viene eseguito qui (non dall'app), "shot" produce $OUT (default shot.png).
SP=${HIFI_DEV_DIR:-/tmp/hifi-qt-dev}; mkdir -p $SP
R=/srv/trixie
OUT=${OUT:-shot.png}
send() { printf '%s\n' "$1" | sudo tee $R/tmp/hifi-qt.cmd >/dev/null; for i in $(seq 1 40); do sleep 0.05; [ -f $R/tmp/hifi-qt.cmd ] || break; done; }
for c in "$@"; do
  case "$c" in
    sleep*) sleep ${c#sleep } ;;
    shot*)
      sudo rm -f $R/tmp/hifi-qt.png; send "shot"
      for i in $(seq 1 40); do sleep 0.1; [ -f $R/tmp/hifi-qt.png ] && break; done; sleep 0.2
      sudo cp $R/tmp/hifi-qt.png $SP/$OUT 2>/dev/null && sudo chown coder $SP/$OUT && echo "shot -> $OUT" ;;
    eval*) sudo rm -f $R/tmp/hifi-qt.out; send "$c"; for i in $(seq 1 20); do sleep 0.1; [ -f $R/tmp/hifi-qt.out ] && break; done; sudo cat $R/tmp/hifi-qt.out 2>/dev/null ;;
    *) send "$c" ;;
  esac
done
[ -n "$LOGN" ] && sudo grep -v "locale\|UTF-8\|reconfigure\|information" $R/tmp/hifi-qt.log | tail -n $LOGN
exit 0
