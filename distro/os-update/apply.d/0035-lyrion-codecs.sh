# shellcheck shell=sh
# 0035 — Codec helper binaries for Lyrion Music Server transcoding.
#
# Lyrion's own conversion pipeline (convert.conf) shells out to external CLI
# tools to transcode between formats — it does NOT reuse squeezelite's
# playback libraries (libmad/libmpg123/libfaad2/libavcodec, pulled in as
# squeezelite's own Depends) for that job. Without these binaries on PATH,
# Lyrion can only serve formats it can pass through untouched, which in
# practice meant only FLAC played — MP3/AAC/etc. silently failed to
# transcode.
#
#   • lame  — MP3 encoder (also used as a decoder frontend by some convert.conf rows)
#   • faad  — AAC/MP4 decoder
#   • sox   — sample-rate/format conversion, resampling
#   • wavpack — WavPack (.wv) encode/decode (provides wvunpack)
#   • ffmpeg  — catch-all for everything else Lyrion's convert.conf can route through it
#
# flac itself already ships (0022-cd-rip.sh, for CD ripping), so it's not
# repeated here. All five packages are in Debian main on bookworm — no
# archive-area change needed.
#
# Idempotent: ensure_pkg installs only if missing. Non-fatal: an offline
# device just retries on the next OS update.

ensure_pkg lame || true
ensure_pkg faad || true
ensure_pkg sox || true
ensure_pkg wavpack || true
ensure_pkg ffmpeg || true
