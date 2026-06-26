# shellcheck shell=sh
# 0007 — Faster boot: drop services that needlessly delay startup.
#
# Measured on the x86 mini-PC with `systemd-analyze blame`:
#   • NetworkManager-wait-online.service ~6.5s — blocks boot until the network
#     is "online". A media appliance does not need this: the UI starts and the
#     app connects to Lyrion (with retries) once the LAN is up. Masking it
#     removes the wait entirely; NetworkManager still brings the network up in
#     the background.
#   • e2scrub_reap.service / e2scrub_all.timer ~0.7s — periodic ext4 online
#     fsck plumbing, unnecessary on this appliance.
#
# No reboot is requested — the change takes effect at the next boot.
# Idempotent: each unit is only touched when its current state warrants it, and
# mark_changed fires only on a successful state change (so a second run, and the
# CI idempotency check, report changed=0).

# Mask a unit (works whether it's enabled or static) only if not already masked
# and systemd is actually reachable — so this is a clean no-op in the CI
# container, and mark_changed fires only on a real, successful state change.
mask_unit() {
    u="$1"
    command -v systemctl >/dev/null 2>&1 || return 0
    state=$(systemctl is-enabled "$u" 2>/dev/null) || state=""
    [ -n "$state" ] || return 0           # unknown / absent / unreachable → leave
    [ "$state" = "masked" ] && return 0   # already masked → no-op
    if systemctl mask --now "$u" >/dev/null 2>&1; then
        mark_changed "masked $u"
    fi
}

mask_unit NetworkManager-wait-online.service
mask_unit e2scrub_reap.service
mask_unit e2scrub_all.timer
