# shellcheck shell=sh
# 0042 — Persistent, unique squeezelite player MAC (-m).
#
# squeezelite has always shipped with no -m flag (see /etc/default/
# squeezelite's baked-in template) and auto-detects its LMS playerid at
# runtime. This appliance talks to LMS over -s 127.0.0.1, so squeezelite
# doesn't always have a real network interface to derive an identity from
# — observed in the field falling back to the placeholder 00:00:00:00:00:00.
# That placeholder is not unique: two Osmium units (or an Osmium and some
# unrelated player, e.g. an AirPlay-to-Squeezebox bridge that ships the same
# kind of fallback) can end up sharing one playerid on the same LMS server.
# Reported symptom: this device's now-playing/cover art briefly flashed to
# another player's track for a couple of seconds right as that other player
# connected, before snapping back — the two were momentarily the same LMS
# player as far as the server was concerned.
#
# Fix: give squeezelite an explicit -m derived from /etc/machine-id, which
# hifi-disk-install.sh regenerates fresh per physical install (never cloned
# from the live image) — unique per device, and stable for the lifetime of
# that install. Hashed and truncated to 6 bytes with the locally-administered
# + unicast bits forced on the first octet, so it can also never collide with
# a real burned-in hardware MAC.
#
# Idempotent: only touches ARGS if it doesn't already contain -m — once
# assigned this must never change again (LMS keys a player's saved settings/
# playback history off its playerid), so a MAC set here, by hand, or by a
# future release is never overwritten. Only restarts squeezelite if ARGS
# actually changed and the service is currently active (brief audio
# interruption, same tradeoff as 0037's DAC-priority change).
#
# The "already has -m" test must accept the opening quote as a word boundary.
# The sed below PREPENDS, so the flag it writes lands immediately after that
# quote — ARGS='-m 02:.. -o ..' — where a plain (^|[[:space:]])-m never
# matched. apply.sh re-runs every migration on every OS update, so the guard
# kept failing and a second (third, ...) identical -m was prepended each time:
# ARGS='-m 02:43:.. -m 02:43:.. -o ..', as reported from the field. The test is
# also scoped to the ARGS= line so a future comment mentioning -m can't disable
# it. 0060-squeezelite-dedup-mac.sh cleans up units that already grew one.

SQ_DEFAULT=/etc/default/squeezelite

if [ -f "$SQ_DEFAULT" ] && grep -q '^ARGS=' "$SQ_DEFAULT" 2>/dev/null \
   && ! grep '^ARGS=' "$SQ_DEFAULT" | grep -qE "(^ARGS=['\"]|[[:space:]])-m[[:space:]]"; then
    _seed="$(cat /etc/machine-id 2>/dev/null)"
    [ -n "$_seed" ] || _seed="$(hostname)-no-machine-id-fallback"
    _hash="$(printf '%s' "$_seed" | md5sum | cut -c1-12)"
    # Drop the hashed first octet, force 02 (locally-administered + unicast).
    _mac_raw="02${_hash#??}"
    _mac="$(printf '%s' "$_mac_raw" | sed 's/\(..\)/\1:/g; s/:$//')"

    _bak="$SQ_DEFAULT.hifi-bak.$$"
    cp -a "$SQ_DEFAULT" "$_bak"
    sed -i "s/^ARGS=\(['\"]\)\(.*\)\1\$/ARGS=\1-m $_mac \2\1/" "$SQ_DEFAULT"

    if grep '^ARGS=' "$SQ_DEFAULT" | grep -qF -- "-m $_mac"; then
        rm -f "$_bak"
        mark_changed "assigned persistent squeezelite MAC $_mac"
    else
        mv -f "$_bak" "$SQ_DEFAULT"
        log_warn "failed to insert -m into $SQ_DEFAULT ARGS, left untouched"
    fi
fi

if migration_changed; then
    if [ "$(systemctl is-active squeezelite.service 2>/dev/null)" = "active" ]; then
        systemctl restart squeezelite.service 2>/dev/null || true
    fi
fi
