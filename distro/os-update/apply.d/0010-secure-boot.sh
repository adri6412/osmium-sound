# shellcheck shell=sh
# 0010 — Secure Boot enablement: DISABLED (do nothing).
#
# IMPORTANT: do NOT re-enable bootloader changes from this OS-update channel.
#
# A previous version of this migration installed Debian's signed boot chain
# (shim-signed / grub-efi-amd64-signed) and re-ran `grub-install
# --uefi-secure-boot` on the running device. On a headless appliance with NO SSH
# by default that turned out to be UNRECOVERABLE: reinstalling the EFI bootloader
# in place could leave the box dropping to the bare `grub>` rescue prompt after a
# reboot, with no way back in. (Note: even just `apt-get install
# grub-efi-amd64-signed` is dangerous here — its postinst runs grub-install.)
#
# Lesson: the bootloader must NOT be rewritten by an OTA on this fleet. Secure
# Boot support, if wanted, belongs at IMAGE BUILD time (fresh installs ship the
# signed chain from the start) where a bad result is caught before flashing — not
# pushed live to already-deployed devices that can't be recovered remotely.
#
# This file is intentionally kept (the OS channel is cumulative — files are
# appended, never deleted) but is now a hard no-op so the dangerous behaviour can
# never run again. Recovery for a device already broken by the old 0010 is manual
# (boot the kernel from the grub> prompt, then `grub-install` + `update-grub`).
return 0
