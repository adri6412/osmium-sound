#!/bin/sh
# HiFi Player appliance — first-boot finalisation on the INSTALLED system.
#
# The debian-installer step /usr/lib/finish-install.d/14remove-live-packages
# (live-installer) runs AFTER preseed/late_command and PURGES packages that were
# added in the live image via chroot hooks — including Lyrion Music Server. So we
# cannot rely on the install carrying Lyrion over; instead we (re)install it here,
# on the first boot of the real system, then self-disable.
#
# Invoked by hifi-firstboot.service (oneshot). Runs only on the installed system
# (the unit has ConditionKernelCommandLine=!boot=live), so it never touches the
# staged .deb while still in the live session (which the installer needs to clone).
set +e

LYRION_DIR=/opt/hifi-lyrion
LYRION_URL=https://downloads.lms-community.org/LyrionMusicServer_v9.1.0/lyrionmusicserver_9.1.0_all.deb

if ! dpkg -s lyrionmusicserver >/dev/null 2>&1; then
    echo "[hifi-firstboot] Lyrion not installed — installing now"
    export DEBIAN_FRONTEND=noninteractive
    DEB="$(ls "$LYRION_DIR"/lyrionmusicserver*.deb 2>/dev/null | head -n1)"
    if [ -n "$DEB" ]; then
        apt-get install -y "$DEB"
    else
        # Fallback: download it (networking is up at this point)
        curl -fL -o /tmp/lyrion.deb "$LYRION_URL" \
            && apt-get install -y /tmp/lyrion.deb
        rm -f /tmp/lyrion.deb
    fi
fi

if dpkg -s lyrionmusicserver >/dev/null 2>&1; then
    echo "[hifi-firstboot] Lyrion present — enabling service and self-disabling"
    # Keep it from being autoremoved and make sure it runs.
    apt-mark manual lyrionmusicserver 2>/dev/null

    # Give the Lyrion service user access to the optical drive so the CD Player
    # plugin can read audio CDs (done before starting the service so it picks up
    # the new group). Skip if Lyrion runs as root.
    LYRION_USER="$(systemctl show -p User --value lyrionmusicserver 2>/dev/null)"
    [ -n "$LYRION_USER" ] || LYRION_USER=squeezeboxserver
    if [ "$LYRION_USER" != "root" ] && id "$LYRION_USER" >/dev/null 2>&1; then
        usermod -aG cdrom "$LYRION_USER" 2>/dev/null \
            && echo "[hifi-firstboot] added $LYRION_USER to cdrom group"
    fi

    systemctl enable --now lyrionmusicserver 2>/dev/null

    # Success: clean up the staged .deb and remove ourselves so we never re-run.
    rm -rf "$LYRION_DIR"
    systemctl disable hifi-firstboot.service 2>/dev/null
    rm -f /etc/systemd/system/hifi-firstboot.service
    systemctl daemon-reload 2>/dev/null
else
    echo "[hifi-firstboot] Lyrion install failed — will retry on next boot" >&2
fi
