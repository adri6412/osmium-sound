#!/bin/bash
# Sul Dell: manda comandi al canale di collaudo di hifi-qt uno alla volta,
# aspettando che ognuno sia consumato (se no il successivo lo sovrascrive).
#   devcmd.sh "eval app.setExpanded(true)" "sleep 2" "shot /tmp/hq-x.png" "cpu 10"
# "cpu N" misura per N secondi watt di pacchetto, CPU del processo e fps.
S() { echo "${SUDOPASS:-ssh123456}" | sudo -S -p "" "$@"; }
PID=$(pgrep -x hifi-qt | head -1)
send() { echo "$1" > /tmp/hifi-qt.cmd; for i in $(seq 1 40); do sleep 0.05; [ -f /tmp/hifi-qt.cmd ] || return 0; done; }
for c in "$@"; do
  case "$c" in
    sleep*) sleep ${c#sleep } ;;
    cpu*) N=${c#cpu }; N=${N:-10}; a=$(S cat /sys/class/powercap/intel-rapl:0/energy_uj); t0=$(S cat /proc/$PID/stat | awk '{print $14+$15}'); f0=$(grep -c "fps:" /tmp/hifi-qt.log); sleep $N; b=$(S cat /sys/class/powercap/intel-rapl:0/energy_uj); t1=$(S cat /proc/$PID/stat | awk '{print $14+$15}')
          echo "$(( (b-a)/(N*1000000) )).$(( ((b-a)/(N*100000))%10 )) W, cpu $(( (t1-t0)*100/(N*100) ))%, $(grep "fps:" /tmp/hifi-qt.log | tail -n +$((f0+1)) | tr '\n' ' ')" ;;
    eval*) S rm -f /tmp/hifi-qt.out; send "$c"; sleep 0.4; echo "$(S cat /tmp/hifi-qt.out 2>/dev/null | tr -d '\n') <- ${c#eval }" ;;
    shot*) P=${c#shot }; P=${P:-/tmp/hifi-qt.png}; S rm -f "$P"; send "shot $P"; for i in $(seq 1 30); do sleep 0.1; [ -f "$P" ] && break; done; sleep 0.3; S chmod 644 "$P"; echo "shot -> $P" ;;
    *) send "$c" ;;
  esac
done
