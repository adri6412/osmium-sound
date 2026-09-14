#!/bin/sh
# HiFi Player — fotografia della RAM di un dispositivo, per confronti
# prima/dopo (tuning, release). Pensato per girare SUL dispositivo:
#
#   sudo sh mem-report.sh          # completo (smaps_rollup richiede root)
#   sh mem-report.sh               # degradato: solo i processi leggibili
#
# Copre entrambe le interfacce su schermo: quella Qt (hifi-qt, un processo
# solo) e quella Electron tenuta come ripiego (più processi Chromium).
#
# Usa la PSS (proportional set size), non la RSS: i processi Chromium
# condividono molte pagine e la RSS le conta piene in ognuno — la somma delle
# PSS invece è confrontabile con MemTotal. Output ordinato e stabile, adatto a
# diff tra due esecuzioni.

set -eu

MIN_KB="${MIN_KB:-2048}"   # non elencare processi sotto questa PSS

echo "== mem-report $(date -u '+%Y-%m-%dT%H:%M:%SZ') $(hostname 2>/dev/null || true) =="

echo
echo "-- /proc/meminfo (chiavi) --"
grep -E '^(MemTotal|MemAvailable|Shmem|Slab|SwapTotal|SwapFree):' /proc/meminfo

echo
echo "-- PSS per processo (KB), soglia ${MIN_KB} KB --"
total_kb=0
list="$(
    for p in /proc/[0-9]*; do
        [ -r "$p/smaps_rollup" ] || continue
        pss="$(awk '/^Pss:/{print $2; exit}' "$p/smaps_rollup" 2>/dev/null)" || continue
        [ -n "$pss" ] || continue
        comm="$(cat "$p/comm" 2>/dev/null || echo '?')"
        printf '%s %s %s\n' "$pss" "$comm" "${p#/proc/}"
    done | sort -rn
)"
if [ -z "$list" ]; then
    echo "(nessun processo leggibile — rilanciare con sudo)"
else
    echo "$list" | awk -v min="$MIN_KB" '
        { tot += $1; if ($1 >= min) print }
        END { printf "TOTALE PSS user-space: %d KB (%.0f MB)\n", tot, tot/1024 }'
fi

echo
echo "-- MemoryCurrent dei servizi (byte) --"
for u in hifi-api hifi-webui hifi-sources hifi-vumeter hifi-qt squeezelite \
         lyrionmusicserver logitechmediaserver tailscaled lightdm \
         systemd-journald; do
    v="$(systemctl show -p MemoryCurrent "$u.service" 2>/dev/null | cut -d= -f2)"
    case "$v" in ''|'[not set]'|18446744073709551615) continue ;; esac
    echo "$u: $v"
done

echo
echo "-- journal --"
journalctl --disk-usage 2>/dev/null || true

echo
echo "-- processo Qt del kiosk (hifi-qt) --"
qt_list="$(
    for p in /proc/[0-9]*; do
        [ "$(cat "$p/comm" 2>/dev/null || echo '?')" = "hifi-qt" ] || continue
        pid="${p#/proc/}"
        if [ -r "$p/smaps_rollup" ]; then
            awk -v pid="$pid" '
                /^Pss:/ { pss = $2 }
                /^Rss:/ { rss = $2 }
                END { printf "%s hifi-qt PSS=%d KB RSS=%d KB\n", pid, pss, rss }
            ' "$p/smaps_rollup" 2>/dev/null || true
        else
            # Senza root la PSS non è leggibile, la RSS di /proc/PID/status sì.
            awk -v pid="$pid" '
                /^VmRSS:/ {
                    printf "%s hifi-qt PSS=n/d (serve sudo) RSS=%d KB\n", pid, $2
                }
            ' "$p/status" 2>/dev/null || true
        fi
    done | sort -n
)"
if [ -z "$qt_list" ]; then
    echo "(nessun processo hifi-qt in esecuzione)"
else
    echo "$qt_list"
fi

echo
echo "-- processi Chromium del kiosk (tipo) --"
ps -eo pid=,args= 2>/dev/null | grep 'hifi-media-playe[r]' | \
    sed 's/\(--type=[a-zA-Z-]*\).*/\1/;s{^ *\([0-9]*\) .*/hifi-media-player{\1 hifi-media-player{' || true
