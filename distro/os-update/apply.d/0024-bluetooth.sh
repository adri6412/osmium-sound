# shellcheck shell=sh
# 0024 — Bluetooth audio prerequisites, for devices still on the legacy
# (non-image) layout.
#
# 🚨 The role changed. This migration used to set the appliance up as a
# Bluetooth *speaker* (A2DP sink: a phone streams into the DAC). It is now an
# A2DP *source* — it plays out to Bluetooth speakers and headphones, and each
# paired one becomes a squeezelite player of its own in Lyrion, the way
# piCorePlayer does it. The sink units are stopped and disabled here so the
# two designs can't both hold the adapter on a device that is mid-conversion.
#
# What this migration still owns: packages, and turning OFF what must not run.
# It no longer writes any unit file — hifi-bluealsa.service,
# hifi-bt-agent.service, hifi-bt-out.service and hifi-bt-player@.service all
# ship in the image and in the system OTA payload, which is applied BEFORE
# this one (fixed order: system → os), so the files are already in place and
# current by the time this runs. Writing them here as well would only give the
# two channels a chance to disagree.
#
# What it no longer owns either: whether Bluetooth is running. That is
# hifi-bt-out.service's job now, driven by /etc/hifi-player/bluetooth.json —
# see that unit for why the choice cannot be an enable symlink any more. All
# this does is make sure the supervisor itself is enabled.
#
# Idempotent: packages via ensure_pkg, and every systemctl call is guarded by
# the state it would change. Non-fatal throughout: an offline device just
# keeps Bluetooth unavailable until the packages land on a later run.

ensure_pkg bluez || true
ensure_pkg bluez-tools || true
ensure_pkg bluez-alsa-utils || true
# The ALSA PCM plugin squeezelite opens as bluealsa:DEV=<MAC>. Without it
# there is a BlueALSA daemon but no way for a player to reach a speaker.
ensure_pkg libasound2-plugin-bluez || true

# ── Neutralise units that would fight ours ───────────────────────────
# Debian's own bluealsa units (auto-enabled by the package), and the two units
# from the old sink design, whose files may still exist from an earlier run.
for u in bluealsa.service bluealsa-aplay.service \
         hifi-bt-aplay.service hifi-bt-watcher.service; do
    state=$(systemctl is-enabled "$u" 2>/dev/null) || state=""
    if [ -n "$state" ] && [ "$state" != "disabled" ] && [ "$state" != "masked" ]; then
        systemctl disable --now "$u" >/dev/null 2>&1 && mark_changed "disabled $u"
    elif [ "$(systemctl is-active "$u" 2>/dev/null)" = "active" ]; then
        systemctl stop "$u" >/dev/null 2>&1 && mark_changed "stopped $u"
    fi
done

# ── The supervisor, which applies the owner's choice from here on ────
# Enabled whether Bluetooth is on or off: with the choice off it starts
# nothing and leaves the adapter powered down, and having it already running
# is what lets the choice take effect without a reboot.
if [ -f /etc/systemd/system/hifi-bt-out.service ]; then
    systemctl daemon-reload 2>/dev/null || true
    if [ "$(systemctl is-enabled hifi-bt-out.service 2>/dev/null)" != "enabled" ]; then
        systemctl enable --now hifi-bt-out.service >/dev/null 2>&1 \
            && mark_changed "enabled hifi-bt-out.service"
    elif [ "$(systemctl is-active hifi-bt-out.service 2>/dev/null)" != "active" ]; then
        systemctl start hifi-bt-out.service >/dev/null 2>&1 || true
    fi
fi

# 0009-faster-boot-2.sh blacklists btusb and masks bluetooth.service on every
# run, which is the right default for a device whose owner never asked for
# Bluetooth. It is NOT undone here: hifi-bt-out.py unmasks the unit and loads
# the module itself, but only when the choice is actually on — so a device
# with Bluetooth off keeps 0009's faster boot exactly as before.
