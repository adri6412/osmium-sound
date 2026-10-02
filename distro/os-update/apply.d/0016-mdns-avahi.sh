# shellcheck shell=sh
# 0016 — mDNS/Bonjour (avahi-daemon).
#
# The only migration that installs avahi on devices set up from an ISO that
# predates it in the package list: \\hifiplayer.local and the SMB share
# discovery (0041, 0051) both rely on it, so it must stay even though the
# optional receiver it was first added for has been dropped.
#
# That receiver left a disabled systemd unit behind on devices that ran an
# older version of this migration; it is removed here. Idempotent: avahi is
# installed only if missing, the unit is deleted only if still present.

ensure_pkg avahi-daemon || true

UNIT=/etc/systemd/system/tidal-connect.service
if [ -f "$UNIT" ]; then
    systemctl disable --now tidal-connect.service >/dev/null 2>&1 || true
    rm -f "$UNIT"
    mark_changed "removed $UNIT"
    systemctl daemon-reload 2>/dev/null || true
fi
