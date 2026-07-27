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

# Bootloader install for the machine's actual firmware (BIOS vs UEFI) is
# CRITICAL, unlike the purely cosmetic boot branding below: if it fails, the
# installed system will not boot at all. Its exit status must therefore
# propagate as a real late_command failure so d-i logs an install error
# instead of silently reporting success on an unbootable disk — a previous
# version piped this straight through `tee`, which under /bin/sh (no
# pipefail) always reports tee's own exit status, masking any real failure
# from hifi-grub-install.sh regardless of what happened; that plus the
# blanket `set +e` here meant a failed bootloader install was completely
# invisible until the box failed to boot after reboot.
sh /usr/local/sbin/hifi-grub-install.sh >>/var/log/hifi-grub-install.log 2>&1
grub_status=$?
if [ "$grub_status" -ne 0 ]; then
    echo "E: [hifi-finalize-install] bootloader install FAILED (exit $grub_status) — see /var/log/hifi-grub-install.log" >&2
    exit 1
fi

# Apply hidden/branded boot config (GRUB + Plymouth) on the installed
# system. Cosmetic only — a hiccup here must never fail an otherwise
# successful, bootable installation.
sh /usr/local/sbin/hifi-finalize-boot.sh
exit 0
