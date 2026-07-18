# shellcheck shell=sh
# 0022 — CD ripping prerequisites.
#
# The rip feature (sources_server.py /api/cd/* + /usr/local/sbin/hifi-rip-cd.py,
# both delivered by the *system* OTA channel) needs an encoder and TOC tools on
# top of the cdparanoia that already ships with the image:
#   • flac      — encoder + tagger (FLAC with embedded cover art)
#   • cd-discid — TOC/disc-id read, used for the MusicBrainz lookup
#   • eject     — open the tray from the touchscreen when the rip is done
#
# Idempotent: packages are installed only if missing (ensure_pkg). Non-fatal:
# offline devices just keep the rip UI hidden until the next online update.

ensure_pkg flac || true
ensure_pkg cd-discid || true
ensure_pkg eject || true
