# shellcheck shell=sh
# 0001 — Self-healing kiosk X session.
#
# The kiosk session used to `exec` Electron once; if the Chromium renderer/GPU
# process died after long uptime the main process stayed alive showing a blank
# (white) window and nothing relaunched it. The session installed here wraps the
# app in a restart loop so a full crash relaunches instead of leaving a dead
# screen.
#
# Single source of truth: the desired session is the file shipped at
# files/xsession in this bundle — the SAME file the image build bakes (via
# build-distro.sh → /home/hifi/.xsession). OTA and image can therefore never
# drift, which is what used to force a reboot on every release when the two
# copies differed by even one byte.

HIFI_HOME=/home/hifi
XSESSION="$HIFI_HOME/.xsession"
SRC="$HIFI_PAYLOAD_DIR/files/xsession"

if [ ! -d "$HIFI_HOME" ]; then
    log_info "$HIFI_HOME not present — skipping kiosk session update"
elif [ ! -f "$SRC" ]; then
    log_warn "canonical xsession missing at $SRC — skipping"
else
    ensure_file_content "$XSESSION" 755 hifi:hifi < "$SRC"
    # The new session only takes effect on the next login, so reboot to apply it
    # — but ONLY if we actually changed the file.
    if migration_changed; then
        request_reboot
    fi
fi
