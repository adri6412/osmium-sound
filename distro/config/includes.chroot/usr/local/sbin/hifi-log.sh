# shellcheck shell=sh
# HiFi Player — shared log-redirect helper for one-shot admin/OTA shell
# scripts (sourced, never executed directly).
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
