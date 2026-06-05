#!/bin/sh
# Run IN-TARGET by the preseed late_command, i.e. on the freshly installed
# system. The Debian installer does not carry over packages that were
# installed via chroot hooks (Lyrion), so we (re)install it here, then apply
# the hidden/branded boot configuration.
set +e

echo "[hifi-finalize] ensuring Lyrion Music Server is installed"
if ! dpkg -s lyrionmusicserver >/dev/null 2>&1; then
    DEB="$(ls /opt/hifi-lyrion/lyrionmusicserver*.deb 2>/dev/null | head -n1)"
    if [ -n "$DEB" ]; then
        apt-get install -y "$DEB"
    else
        # Fallback: download it (the target has working networking at this point)
        curl -fL -o /tmp/lyrion.deb \
          https://downloads.lms-community.org/LyrionMusicServer_v9.1.0/lyrionmusicserver_9.1.0_all.deb \
          && apt-get install -y /tmp/lyrion.deb && rm -f /tmp/lyrion.deb
    fi
    systemctl enable lyrionmusicserver 2>/dev/null
fi
rm -rf /opt/hifi-lyrion

# Apply hidden/branded boot config (GRUB + Plymouth) on the installed system
sh /usr/local/sbin/hifi-finalize-boot.sh
