#!/bin/sh
# Osmium Sound — one line of memory state every few minutes, plus the biggest
# processes, into /var/log/hifi/memory.log (collected by the support bundle).
#
# A box that runs out of memory stalls journald together with everything else,
# so the minutes before a freeze leave no trace in the journal. This file does:
# it shows which process grew and how fast, which is the one thing a support
# bundle could not tell after the 2026-09-24 freeze (radio on for 15 h).
#
# Kept small on purpose: rotated to memory.log.1 past 512 KB (≈ 10 days).
LOG=/var/log/hifi/memory.log
MAX=524288

mkdir -p /var/log/hifi
if [ -f "$LOG" ] && [ "$(stat -c %s "$LOG" 2>/dev/null || echo 0)" -gt "$MAX" ]; then
    mv -f "$LOG" "$LOG.1"
fi

{
    # avail/swap in MB; psi = share of the last 10 s that some/all tasks
    # waited for memory
    awk -v t="$(date '+%F %T')" '
        /^MemTotal:/     { tot = $2 }
        /^MemAvailable:/ { av = $2 }
        /^SwapTotal:/    { st = $2 }
        /^SwapFree:/     { sf = $2 }
        END { printf "%s avail=%dM/%dM swap_used=%dM/%dM", t, av/1024, tot/1024, (st-sf)/1024, st/1024 }
    ' /proc/meminfo
    awk '/^some/ { split($2, a, "="); s = a[2] } /^full/ { split($2, b, "="); f = b[2] }
         END { printf " psi_some=%s psi_full=%s\n", s, f }' /proc/pressure/memory 2>/dev/null || echo
    # the six biggest by resident memory (MB), with their service
    ps -eo rss=,pid=,comm= --sort=-rss 2>/dev/null | head -6 | while read -r rss pid comm; do
        unit=$(sed -n 's|^0::.*/\([^/]*\.service\).*|\1|p' "/proc/$pid/cgroup" 2>/dev/null)
        printf '    %6dM %-16s %s\n' "$((rss / 1024))" "$comm" "${unit:--}"
    done
} >> "$LOG" 2>/dev/null
exit 0
