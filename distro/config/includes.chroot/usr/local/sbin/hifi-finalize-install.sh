#!/bin/sh
# Run IN-TARGET by the preseed late_command, i.e. on the freshly installed
# system, to (1) actually install/configure the bootloader — d-i's own
# grub-installer step is disabled, see hifi-grub-install.sh for why — and
# (2) apply the hidden/branded boot configuration (the bootloader
# reconfiguration in step 1 regenerates GRUB and would otherwise overwrite it).
#
# NOTE: Lyrion Music Server is deliberately NOT (re)installed here. The
# debian-installer step finish-install.d/14remove-live-packages (live-installer)
# runs AFTER this late_command and purges packages added via chroot hooks, so
# anything installed here would be removed again. Lyrion is instead installed on
# the first boot of the real system by hifi-firstboot.service, which is why the
# staged /opt/hifi-lyrion .deb must survive (do NOT remove it here).
set +e

# Explicit, deterministic bootloader install for the machine's actual
# firmware (BIOS vs UEFI). Logged (not just discarded) because — unlike the
# purely cosmetic boot branding below — a failure here means the installed
# system may not boot at all; the log survives on the target for a rescue
# chroot to inspect if that happens.
sh /usr/local/sbin/hifi-grub-install.sh 2>&1 | tee -a /var/log/hifi-grub-install.log

# Apply hidden/branded boot config (GRUB + Plymouth) on the installed system.
sh /usr/local/sbin/hifi-finalize-boot.sh
