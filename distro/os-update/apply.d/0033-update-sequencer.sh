# shellcheck shell=sh
# 0033 — Enable the OTA update sequencer's boot-time stage-resume unit.
#
# Multi-component updates used to be sequenced by whichever client started them
# (kiosk, web-admin, companion): apply one component, poll its /run status file,
# apply the next. Any event that killed the client killed the rest of the
# sequence, which is how appliances ended up with, say, the OS updated and the
# UI still on the old version. The worst case was an OS payload that reboots:
# /run is a tmpfs, so the status file vanished, the client waited for a `done`
# that could never arrive, and the remaining steps were simply lost.
#
# The plan is now persisted at /var/lib/hifi-player/update/plan and, in two
# phases: hifi-update-stage-runner.sh downloads and verifies every component
# (nothing applied yet, the box stays fully live), then reboots into an
# isolated system-update.target session where hifi-update-apply-runner.sh
# applies everything with nothing else running. This migration enables
# hifi-update-stage-resume.service, the boot-time oneshot that picks a STAGE
# plan back up after an unrelated reboot interrupts a download (the apply half
# needs no resume unit — system-update.target re-enters on its own after a
# crash, and every apply step is idempotent).
#
# The unit file and the runner scripts are delivered by the *system* OTA
# channel; this migration only sets the enable state. If they have not landed
# yet (system bundle applied after this OS bundle), the enable is a guarded
# no-op and takes effect on the next update run — the OS payload is
# cumulative. The system updater performs the same guarded enable, so a device
# that only ever receives system bundles is covered too; both are idempotent.
#
# Idempotent: acts only when the unit exists and is not already enabled.
# Never reboots.

RESUME_UNIT=/etc/systemd/system/hifi-update-stage-resume.service
if [ -f "$RESUME_UNIT" ]; then
    state=$(systemctl is-enabled hifi-update-stage-resume.service 2>/dev/null) || state=""
    if [ "$state" != "enabled" ]; then
        systemctl daemon-reload 2>/dev/null || true
        if systemctl enable hifi-update-stage-resume.service >/dev/null 2>&1; then
            mark_changed "enabled hifi-update-stage-resume.service"
        else
            log_warn "could not enable hifi-update-stage-resume.service (will retry next update)"
        fi
    fi
else
    log_info "hifi-update-stage-resume.service not present yet (system bundle pending) — skipping"
fi

APPLY_UNIT=/etc/systemd/system/hifi-update-apply.service
if [ -f "$APPLY_UNIT" ]; then
    state=$(systemctl is-enabled hifi-update-apply.service 2>/dev/null) || state=""
    if [ "$state" != "enabled" ]; then
        systemctl daemon-reload 2>/dev/null || true
        if systemctl enable hifi-update-apply.service >/dev/null 2>&1; then
            mark_changed "enabled hifi-update-apply.service"
        else
            log_warn "could not enable hifi-update-apply.service (will retry next update)"
        fi
    fi
else
    log_info "hifi-update-apply.service not present yet (system bundle pending) — skipping"
fi
