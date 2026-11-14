# shellcheck shell=sh
# 0064 — Recommended albums: switch the scheduled job on.
#
# New images enable hifi-recommend.timer from the build hook
# (0400-enable-services). A device that gets the feature by update receives
# the unit files and the runner with the System bundle (which is applied
# before the OS migrations) but nothing enables the timer there: this does.
#
# The owner's choice wins. Settings → Recommended writes
# /etc/hifi-player/recommend.json and, through the API, the timer drop-in
# (hifi-recommend.timer.d/schedule.conf): when that file says the feature is
# off, or that it runs by hand only, the timer is left alone. With no file
# the defaults hold (on, every day at 18:00, a missed run caught up at the
# next power-on) and the timer is enabled.
#
# The model and onnxruntime come with the image, not from here: a device
# without them computes with the tag-vector fallback (see hifi_recommend.py).
#
# Idempotent: nothing to do once the timer is enabled.

REC_TIMER=/etc/systemd/system/hifi-recommend.timer
REC_SETTINGS=/etc/hifi-player/recommend.json

mkdir -p /var/lib/hifi-player/recommend

if [ -f "$REC_TIMER" ]; then
    rec_want=1
    if [ -f "$REC_SETTINGS" ]; then
        if grep -q '"enabled"[[:space:]]*:[[:space:]]*false' "$REC_SETTINGS" 2>/dev/null \
           || grep -q '"mode"[[:space:]]*:[[:space:]]*"manual"' "$REC_SETTINGS" 2>/dev/null; then
            rec_want=0
        fi
    fi
    if [ "$rec_want" = 1 ]; then
        rec_state=$(systemctl is-enabled hifi-recommend.timer 2>/dev/null) || rec_state=""
        if [ "$rec_state" != "enabled" ]; then
            systemctl daemon-reload 2>/dev/null || true
            systemctl enable --now hifi-recommend.timer >/dev/null 2>&1 \
                && mark_changed "enabled hifi-recommend.timer (recommended albums)"
        fi
    fi
fi
