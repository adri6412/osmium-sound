# shellcheck shell=sh
# HiFi Player — shared helpers for one-shot admin/OTA shell scripts (sourced,
# never executed directly): log-redirection (hifi_log_init) and a
# progress-reporting curl wrapper (hifi_curl_progress).
#
# These scripts today only echo to stdout/stderr, which journald alone does
# not persist across a reboot on this image, and several of them run under an
# auto-generated transient systemd-run unit (no stable `-u` name), making
# `journalctl` after the fact impractical. hifi_log_init redirects the rest of
# the calling script's stdout+stderr into a size-rotated file under
# /var/log/hifi/ (rotation: /etc/logrotate.d/hifi) instead, which the
# support-bundle endpoint (api_server.py) picks up automatically.
#
# Usage (as the very first executable line, after any `set` options):
#   . /usr/local/sbin/hifi-log.sh
#   hifi_log_init hifi-factory-reset

hifi_log_init() {
    _hli_name="$1"
    _hli_dir=/var/log/hifi
    mkdir -p "$_hli_dir" 2>/dev/null || true
    _hli_file="$_hli_dir/$_hli_name.log"
    printf '\n===== %s: run started %s (pid %s) =====\n' \
        "$_hli_name" "$(date -Is 2>/dev/null || date)" "$$" >> "$_hli_file" 2>/dev/null || true
    exec >> "$_hli_file" 2>&1
}

# hifi_curl_progress <url> <outfile> <progress_lo> <progress_hi> <label> [extra curl args...]
#
# Downloads url -> outfile in the background and polls the growing file size
# every 2s to call the CALLER's own `write_status` (downloading, a percentage
# scaled between progress_lo/progress_hi, "<label> (X MB / Y MB)") — every
# hifi-*-update.sh used to run curl in the foreground and report a single
# fixed percentage for the whole download step, so the UI status looked
# frozen for however long the transfer took (most visible on the ~130 MB UI
# bundle). Falls back to reporting bytes-only, no percent/total, if a HEAD
# request can't get a Content-Length (some CDNs/redirects don't offer one).
# Requires the caller to have already defined `write_status`.
hifi_curl_progress() {
    _hcp_url="$1"; _hcp_out="$2"; _hcp_lo="$3"; _hcp_hi="$4"; _hcp_label="$5"
    shift 5   # remaining args, if any, are extra curl flags (e.g. --proto '=https')

    _hcp_total=$(curl -fsIL "$_hcp_url" 2>/dev/null | tr -d '\r' | tr '[:upper:]' '[:lower:]' \
        | awk -F': ' '$1=="content-length"{v=$2} END{print v}')
    case "$_hcp_total" in ''|*[!0-9]*) _hcp_total='' ;; esac

    curl -fL --retry 3 "$@" -o "$_hcp_out" "$_hcp_url" &
    _hcp_pid=$!

    while kill -0 "$_hcp_pid" 2>/dev/null; do
        _hcp_done=0
        if [ -f "$_hcp_out" ]; then
            _hcp_done=$(wc -c < "$_hcp_out" 2>/dev/null) || _hcp_done=0
        fi
        _hcp_mb=$(( _hcp_done / 1048576 ))
        if [ -n "$_hcp_total" ] && [ "$_hcp_total" -gt 0 ]; then
            _hcp_tmb=$(( _hcp_total / 1048576 ))
            _hcp_pct=$(( _hcp_lo + (_hcp_hi - _hcp_lo) * _hcp_done / _hcp_total ))
            if [ "$_hcp_pct" -gt "$_hcp_hi" ]; then _hcp_pct=$_hcp_hi; fi
            if [ "$_hcp_pct" -lt "$_hcp_lo" ]; then _hcp_pct=$_hcp_lo; fi
            write_status downloading "$_hcp_pct" "$_hcp_label (${_hcp_mb} MB / ${_hcp_tmb} MB)"
        else
            write_status downloading "$_hcp_lo" "$_hcp_label (${_hcp_mb} MB)"
        fi
        sleep 2
    done
    wait "$_hcp_pid"
}
