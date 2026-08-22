# shellcheck shell=sh
# 0025 — Display mode (GUI touchscreen kiosk <-> headless) default + reconcile.
#
# Makes the GUI/headless switch available on already-installed units and keeps
# the systemd default target in sync with the user's persisted choice on every
# OS update. The switch itself is exposed by api_server.py (/display_mode) and
# performed by /usr/local/sbin/hifi-display-mode.sh, both delivered via the
# *system* OTA channel; this migration only handles the fleet-wide default and
# the boot-target reconciliation.
#
# FLEET SAFETY: the state file /etc/hifi-player/display-mode defaults to "gui"
# when absent. This migration is cumulative + runs on EVERY OS update forever,
# so it must NEVER flip a configured unit into headless on its own. It seeds
# "gui" only when the file is missing (a fresh/legacy unit), then reconciles the
# default target to whatever the file says — a no-op on the common case (gui +
# image already defaults to graphical.target).
#
# This migration must NOT create any provisioning marker or enable any hotspot/
# webui service — those belong to a later migration shipped together with their
# daemon. Keeping this one narrow keeps the increment self-contained.
#
# Idempotent: seeds the file only if missing; touches systemctl only when the
# current default target differs from the desired one. No reboot is ever
# requested — a boot-target change takes effect naturally at the next boot, and
# live switches only ever happen through the user-facing API (never here, where
# it could yank a screen mid-update).

MODE_FILE=/etc/hifi-player/display-mode

# ── Seed the fleet-safe default (only when the file does not yet exist) ──
if [ ! -f "$MODE_FILE" ]; then
    ensure_file_content "$MODE_FILE" 644 root:root <<'EOF'
gui
EOF
fi

# ── Reconcile the boot target with the persisted choice ──────────────
DESIRED_MODE=gui
if grep -qx 'headless' "$MODE_FILE" 2>/dev/null; then
    DESIRED_MODE=headless
fi
case "$DESIRED_MODE" in
    headless) DESIRED_TARGET=multi-user.target ;;
    *)        DESIRED_TARGET=graphical.target ;;
esac

CURRENT_TARGET="$(systemctl get-default 2>/dev/null || echo unknown)"
if [ "$CURRENT_TARGET" != "unknown" ] && [ "$CURRENT_TARGET" != "$DESIRED_TARGET" ]; then
    if systemctl set-default "$DESIRED_TARGET" >/dev/null 2>&1; then
        mark_changed "set default target to $DESIRED_TARGET (display-mode=$DESIRED_MODE)"
    fi
fi
