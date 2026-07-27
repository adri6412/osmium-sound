#!/bin/sh
# shellcheck shell=sh
# HiFi Player — display-mode switch (GUI touchscreen kiosk <-> headless).
#
# The appliance ships GUI-first: the default systemd target is graphical.target,
# which pulls in LightDM -> autologin -> the Electron kiosk. "Headless" here is a
# real, persisted software mode: the box runs on multi-user.target with no X
# server, controlled remotely (companion app, Lyrion :9000, sources :8080). All
# hifi-* daemons + squeezelite + Lyrion are WantedBy=multi-user.target, so they
# keep running in BOTH modes — only the on-screen GUI stack differs.
#
# State lives in /etc/hifi-player/display-mode ("gui" | "headless"). ABSENT means
# gui — that default is the fleet-safety invariant: an existing configured unit
# that never wrote the file must never drift into headless on an OS update.
#
# We switch by flipping the default target (systemctl set-default). We do NOT
# enable/disable lightdm directly: lightdm is only ever pulled in by
# graphical.target, so changing the default target is sufficient and never
# fights the build-time enable or an OS-OTA migration.
#
# Usage:
#   hifi-display-mode.sh get                 -> prints "gui" or "headless"
#   hifi-display-mode.sh set gui|headless [--live]
#
# --live also switches the RUNNING session (systemctl isolate) after a short
# delay, so a caller (api_server.py) can flush its HTTP response before X dies.
# Without --live the change only takes effect at the next boot.

set -eu

# NOTE: deliberately NOT redirected to /var/log/hifi via hifi-log.sh — this
# script's stdout IS its data channel (api_server.py's get_display_mode()
# captures and parses the "gui"/"headless" line straight from subprocess
# stdout), not just diagnostic chatter. Redirecting it would silently break
# the display-mode toggle.
MODE_FILE=/etc/hifi-player/display-mode

die() { echo "$1" >&2; exit 1; }

target_for() {
    case "$1" in
        gui)      echo graphical.target ;;
        headless) echo multi-user.target ;;
        *)        die "invalid mode: $1" ;;
    esac
}

get_mode() {
    if [ -f "$MODE_FILE" ] && [ "$(cat "$MODE_FILE" 2>/dev/null)" = headless ]; then
        echo headless
    else
        echo gui
    fi
}

case "${1:-}" in
    get)
        get_mode
        ;;
    set)
        MODE="${2:-}"
        [ "$MODE" = gui ] || [ "$MODE" = headless ] || die "usage: $0 set gui|headless [--live]"
        LIVE=0
        [ "${3:-}" = "--live" ] && LIVE=1
        TARGET="$(target_for "$MODE")"

        # Persist atomically (tmp + mv), same pattern as pointer-enabled.
        mkdir -p "$(dirname "$MODE_FILE")"
        tmp="${MODE_FILE}.tmp.$$"
        printf '%s\n' "$MODE" > "$tmp"
        mv -f "$tmp" "$MODE_FILE"

        # Persisted boot target.
        if [ "$(systemctl get-default 2>/dev/null)" != "$TARGET" ]; then
            systemctl set-default "$TARGET" >/dev/null 2>&1 || true
        fi

        if [ "$LIVE" = 1 ]; then
            # Isolate the target in a detached one-shot AFTER a short delay, so
            # the caller's HTTP response is flushed before the GUI (which hosts
            # the very UI that issued this request) is torn down. Best-effort:
            # if systemd-run is unavailable the boot target change still applies
            # at the next reboot.
            if command -v systemd-run >/dev/null 2>&1; then
                # Auto-generated transient unit name (no fixed --unit) so back-to-
                # back switches can't collide on an already-existing unit.
                systemd-run --collect --description="HiFi display-mode live switch" \
                    /bin/sh -c "sleep 1; systemctl isolate $TARGET" >/dev/null 2>&1 || true
            fi
        fi

        echo "$MODE"
        ;;
    *)
        die "usage: $0 get | set gui|headless [--live]"
        ;;
esac
