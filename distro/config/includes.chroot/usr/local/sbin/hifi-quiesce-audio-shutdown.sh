#!/bin/sh
# shellcheck shell=sh
# HiFi Player — quiesce audio before ANY shutdown/reboot/halt/kexec.
#
# Mitigates a kernel panic in the DesignWare DMA driver (dw_dmac_core:
# dw_shutdown -> do_dw_dma_disable) seen on this appliance's hardware
# (Intel Braswell) during device_shutdown() when the system reboots/powers
# off while a DMA channel is actively driving audio playback. Not a fix for
# the kernel bug itself (needs an upstream/kernel fix); just gives the
# hardware a moment to go idle first. Confirmed via real device logs to be
# tied to squeezelite's ALSA output generally (present even with CamillaDSP
# off), not just the DSP engine specifically.
#
# This used to be handled ad hoc by whichever script/endpoint triggered the
# reboot (api_server.py's reboot/shutdown, the OS-update REBOOT handling) —
# but ANY OTHER way to reboot bypassed both: `sudo reboot`/`sudo shutdown`
# at a shell (hifi's sudoers grants these NOPASSWD), `systemctl reboot` /
# `shutdown -r now` via logind/polkit, a factory reset, a physical power
# button via ACPI+logind. Each of those was a fresh place to forget this.
#
# Hooking systemd's own shutdown.target instead makes it unconditional: this
# unit runs before EVERY halt/poweroff/reboot/kexec, however it was
# triggered, with no per-caller cooperation required (see the .service file
# for the Before=/Conflicts=shutdown.target ordering that guarantees this).
set -eu

# Capture wherever playback currently is (playing/paused/stopped, track,
# position) so the next boot can restore it — see
# hifi-capture-playback-state.py and api_server.py's
# _resume_playback_after_boot for the read side. Must run BEFORE squeezelite
# (and LMS, via the unit's Before=lyrionmusicserver.service) get stopped
# below, while a live status is still there to query. Best-effort: a failure
# here (LMS unreachable, nothing playing) just means no resume next boot,
# same as before this existed — never worth delaying a shutdown over.
python3 /usr/local/sbin/hifi-capture-playback-state.py 2>/dev/null || true

if [ "$(systemctl is-active camilladsp.service 2>/dev/null)" = "active" ] \
        || [ "$(systemctl is-active squeezelite.service 2>/dev/null)" = "active" ]; then
    systemctl stop camilladsp.service squeezelite.service 2>/dev/null || true
    sleep 2
fi
exit 0
