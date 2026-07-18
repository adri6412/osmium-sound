# shellcheck shell=sh
# 0023 — guided room-correction prerequisites.
#
# The measurement worker (/usr/local/sbin/hifi-room-measure.py, delivered by
# the *system* OTA channel) needs only tools that already ship with the image:
#   • alsa-utils    — aplay/arecord for the sweep playback + mic capture
#   • python3-numpy — FFT deconvolution and FIR generation
# Both are in hifi.list.chroot, but ensure them here so devices installed from
# very old ISOs (or with manually slimmed package sets) still get the feature.
#
# Idempotent (ensure_pkg no-ops when present) and non-fatal.

ensure_pkg alsa-utils || true
ensure_pkg python3-numpy || true
