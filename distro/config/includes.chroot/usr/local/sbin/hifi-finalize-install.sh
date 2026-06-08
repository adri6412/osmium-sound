#!/bin/sh
# Run IN-TARGET by the preseed late_command, i.e. on the freshly installed
# system, to apply the hidden/branded boot configuration (the installer
# regenerates GRUB and would otherwise overwrite it).
#
# NOTE: Lyrion Music Server is deliberately NOT (re)installed here. The
# debian-installer step finish-install.d/14remove-live-packages (live-installer)
# runs AFTER this late_command and purges packages added via chroot hooks, so
# anything installed here would be removed again. Lyrion is instead installed on
# the first boot of the real system by hifi-firstboot.service, which is why the
# staged /opt/hifi-lyrion .deb must survive (do NOT remove it here).
set +e

# Apply hidden/branded boot config (GRUB + Plymouth) on the installed system.
sh /usr/local/sbin/hifi-finalize-boot.sh
