#!/bin/sh
# Osmium Sound — make RAUC's HTTP streaming ask for bigger pieces.
#
# RAUC streams a bundle by attaching an NBD device to the URL, and src/nbd.c
# turns EVERY NBD read request into one HTTP Range request of exactly that
# size (start_read() sets CURLOPT_RANGE from request.len). With the kernel
# defaults that means 128 KiB per request, so the transfer is bound by the
# round trip and not by the bandwidth. Measured against our own release
# assets, 128 KiB sequential requests give ~1 MiB/s (≈15 minutes per GiB) on
# both GitHub and R2, while 1 MiB requests give ~5.5 MiB/s on the same
# uncached file.
#
# Two knobs move that: the read-ahead decides how much the kernel asks for in
# one go, and max_sectors_kb caps how large a single request may be. Both are
# raised here on the NBD device and on the dm-verity device RAUC stacks on top
# of it (`rauc-verity-bundle` — the bundle filesystem reads through that one,
# so its read-ahead is what actually drives the request size). A read-ahead
# larger than max_sectors_kb is not wasted: the kernel splits it into several
# requests that RAUC's curl multi handle runs in parallel.
#
#   hifi-stream-tune.sh watch [timeout_s]  wait for RAUC's devices, tune them,
#                                          then report what the transfer did
#   hifi-stream-tune.sh tune <dev>         tune one device now (nbd0, dm-3)
#   hifi-stream-tune.sh stats <dev>        print that device's read counters
#
# HIFI_STREAM_TUNE=0 turns `watch` into measure-only, so the same command
# gives the "before" and the "after" of a change. HIFI_STREAM_READAHEAD_KB
# and HIFI_STREAM_MAX_SECTORS_KB set the two values.
#
# Everything here is best effort: a kernel that refuses a value is logged and
# ignored. An update must never fail because of tuning.
set -u

SYS="${HIFI_SYSFS:-/sys}"
RA_KB="${HIFI_STREAM_READAHEAD_KB:-8192}"
MAX_KB="${HIFI_STREAM_MAX_SECTORS_KB:-2048}"
SUMMARY="${HIFI_STREAM_SUMMARY:-/run/hifi-stream-tune.summary}"
# HIFI_STREAM_TUNE=0 measures without touching anything: that is how you get
# the "before" figure on a device, with the same reporting as the "after".
TUNE="${HIFI_STREAM_TUNE:-1}"
POLL="${HIFI_STREAM_POLL:-2}"

log() { printf 'I: [stream-tune] %s\n' "$*"; }

read_attr() { [ -r "$1" ] && cat "$1" 2>/dev/null; }

# set_attr <file> <value>: writes and says what actually stuck (the kernel
# silently clamps some of these, so the value read back is the truth).
set_attr() {
    _f="$1"; _v="$2"
    [ -f "$_f" ] || { log "$_f: absent, skipped"; return 1; }
    _before=$(read_attr "$_f")
    if ! printf '%s\n' "$_v" > "$_f" 2>/dev/null; then
        log "$_f: refused $_v (was $_before)"
        return 1
    fi
    _after=$(read_attr "$_f")
    log "$(basename "$(dirname "$(dirname "$_f")")")/$(basename "$_f"): $_before -> $_after"
    return 0
}

# raise <file> <wanted> [ceiling]: only ever moves a queue setting UP. The
# kernel already defaults max_sectors_kb to 1280 on an NBD device, so writing
# a smaller "tuned" value would make the requests smaller, not larger.
raise() {
    _f="$1"; _want="$2"; _ceil="${3:-}"
    [ -f "$_f" ] || { log "$_f: absent, skipped"; return 1; }
    case "$_ceil" in
        ''|*[!0-9]*) ;;
        *) [ "$_ceil" -lt "$_want" ] && _want="$_ceil" ;;
    esac
    _cur=$(read_attr "$_f")
    case "$_cur" in
        ''|*[!0-9]*) ;;
        *) if [ "$_cur" -ge "$_want" ]; then
               log "$(basename "$_f"): already $_cur, left alone"
               return 0
           fi ;;
    esac
    set_attr "$_f" "$_want"
}

tune_dev() {
    _dev="$1"
    _q="$SYS/block/$_dev/queue"
    [ -d "$_q" ] || { log "$_dev: no queue directory, skipped"; return 1; }
    # A request can never be larger than what the driver advertises, and
    # writing more than that is simply refused — clamp, so the read-ahead
    # below still gets applied. (The NBD driver allows 32 MiB, so in practice
    # only stacked devices hit this.)
    raise "$_q/max_sectors_kb" "$MAX_KB" "$(read_attr "$_q/max_hw_sectors_kb")"
    # Deliberately larger than one request: the kernel then splits the
    # read-ahead into several requests, which RAUC's curl multi handle runs in
    # parallel — fewer round trips *and* some of them overlapped.
    raise "$_q/read_ahead_kb" "$RA_KB"
}

# All connected NBD devices: a free/disconnected one has size 0.
find_nbd() {
    for _d in "$SYS"/block/nbd*; do
        [ -d "$_d" ] || continue
        _s=$(read_attr "$_d/size")
        case "$_s" in ''|0|*[!0-9]*) continue ;; esac
        basename "$_d"
    done
}

# The dm device stacked on <nbd> (RAUC names it rauc-verity-bundle).
find_dm_on() {
    for _d in "$SYS"/block/dm-*; do
        [ -e "$_d/slaves/$1" ] || continue
        basename "$_d"
    done
}

# Read counters of a block device: "<requests> <sectors>" (fields 1 and 3 of
# /sys/block/<dev>/stat).
stats_of() {
    _st=$(read_attr "$SYS/block/$1/stat") || return 1
    [ -n "$_st" ] || return 1
    printf '%s' "$_st" | awk '{print $1" "$3}'
}

report() {  # <requests> <sectors> <seconds>
    _ios="$1"; _sec="$2"; _el="$3"
    [ "$_ios" -gt 0 ] 2>/dev/null || { log "no read requests seen"; return 0; }
    [ "$_el" -gt 0 ] || _el=1
    _mib=$(( _sec / 2048 ))
    _avg=$(( _sec * 512 / _ios / 1024 ))
    _rate=$(( _mib * 10 / _el ))
    _msg="streaming: $_ios read requests, avg ${_avg} KiB, ${_mib} MiB in ${_el}s ($(( _rate / 10 )).$(( _rate % 10 )) MiB/s)"
    log "$_msg"
    printf '%s\n' "$_msg" > "$SUMMARY" 2>/dev/null || true
}

case "${1:-}" in
tune)
    [ -n "${2:-}" ] || { echo "usage: $0 tune <dev>" >&2; exit 2; }
    tune_dev "$2"
    ;;
stats)
    [ -n "${2:-}" ] || { echo "usage: $0 stats <dev>" >&2; exit 2; }
    stats_of "$2"
    ;;
watch)
    timeout="${2:-900}"
    rm -f "$SUMMARY" 2>/dev/null || true
    t0=$(date +%s)
    nbd=""
    while [ -z "$nbd" ]; do
        nbd=$(find_nbd | head -n 1)
        [ -n "$nbd" ] && break
        if [ $(( $(date +%s) - t0 )) -ge "$timeout" ]; then
            log "no streaming device appeared within ${timeout}s (local bundle?), nothing to tune"
            exit 0
        fi
        sleep 1
    done
    log "RAUC is streaming through /dev/$nbd"
    if [ "$TUNE" = 0 ]; then
        log "HIFI_STREAM_TUNE=0: measuring only, queues left as they are"
    else
        tune_dev "$nbd"
    fi
    # Baseline for the report: the transfer starts the moment RAUC connects
    # the device, so take the counters here and not after waiting for dm.
    base=$(stats_of "$nbd") || base="0 0"
    base_ios=${base%% *}; base_sec=${base##* }
    ts=$(date +%s)
    # dm-verity is set up a moment after the NBD device is connected.
    i=0
    dm=""
    while [ "$i" -lt 30 ]; do
        dm=$(find_dm_on "$nbd" | head -n 1)
        [ -n "$dm" ] && break
        sleep 1
        i=$(( i + 1 ))
    done
    if [ -n "$dm" ]; then
        log "bundle filesystem reads through /dev/$dm"
        [ "$TUNE" = 0 ] || tune_dev "$dm"
    else
        log "no dm device stacked on $nbd (plain bundle?), only the NBD queue was tuned"
    fi
    # From here on we only watch: sample the counters until the device goes
    # away, so the log of every real update says how large the requests ended
    # up being and how fast the transfer ran. That is the measurement, in the
    # field, without anyone having to attach a tracer.
    last_ios=0; last_sec=0
    while :; do
        cur=$(stats_of "$nbd") || break
        [ -n "$cur" ] || break
        last_ios=$(( ${cur%% *} - base_ios ))
        last_sec=$(( ${cur##* } - base_sec ))
        sz=$(read_attr "$SYS/block/$nbd/size")
        case "$sz" in ''|0) break ;; esac
        if [ $(( $(date +%s) - t0 )) -ge "$timeout" ]; then break; fi
        sleep "$POLL"
    done
    report "$last_ios" "$last_sec" "$(( $(date +%s) - ts ))"
    ;;
*)
    grep '^#' "$0" | sed 's/^# \{0,1\}//' >&2
    exit 2
    ;;
esac
