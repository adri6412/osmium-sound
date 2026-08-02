# shellcheck shell=sh
# 0033 — Enable the OTA update sequencer's boot-time resume unit.
#
# Multi-component updates used to be sequenced by whichever client started them
# (kiosk, web-admin, companion): apply one component, poll its /run status file,
# apply the next. Any event that killed the client killed the rest of the
# sequence, which is how appliances ended up with, say, the OS updated and the
# UI still on the old version. The worst case was an OS payload that reboots:
# /run is a tmpfs, so the status file vanished, the client waited for a `done`
# that could never arrive, and the remaining steps were simply lost.
#
# The plan is now persisted at /var/lib/hifi-player/update-plan and executed by
# hifi-update-runner.sh under its own transient systemd unit. This migration
# enables hifi-update-resume.service, the boot-time oneshot that picks a plan
# back up after the reboot an OS payload asked for.
#
# The unit file and the runner script are delivered by the *system* OTA channel;
# this migration only sets the enable state. If they have not landed yet (system
# bundle applied after this OS bundle), the enable is a guarded no-op and takes
# effect on the next update run — the OS payload is cumulative. The system
# updater performs the same guarded enable, so a device that only ever receives
# system bundles is covered too; both are idempotent.
#
# Idempotent: acts only when the unit exists and is not already enabled.
# Never reboots.

RESUME_UNIT=/etc/systemd/system/hifi-update-resume.service
if [ -f "$RESUME_UNIT" ]; then
    state=$(systemctl is-enabled hifi-update-resume.service 2>/dev/null) || state=""
    if [ "$state" != "enabled" ]; then
        systemctl daemon-reload 2>/dev/null || true
        if systemctl enable hifi-update-resume.service >/dev/null 2>&1; then
            mark_changed "enabled hifi-update-resume.service"
        else
            log_warn "could not enable hifi-update-resume.service (will retry next update)"
        fi
    fi
else
    log_info "hifi-update-resume.service not present yet (system bundle pending) — skipping"
fi
