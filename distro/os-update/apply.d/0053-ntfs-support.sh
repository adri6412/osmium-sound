# shellcheck shell=sh
# 0053 — ntfs-3g for already-installed units.
#
# Adopted internal/USB disks formatted NTFS were already mountable via the
# in-kernel ntfs3 driver (_fs_mount_type() in sources_server.py), but ntfs3
# is younger and less forgiving than ntfs-3g about the NTFS quirks real
# Windows-formatted drives show up with (a dirty $LogFile from an unclean
# Windows shutdown, older/unusual NTFS versions, ...) — that showed up as
# music sources -> a drive stuck on "mount error" with no way to recover
# short of reformatting. sources_server.py now retries with ntfs-3g when the
# ntfs3 mount fails; this is what puts the binary on disk so that fallback
# has something to run. Fleet-wide catch-up so existing devices get it
# without a reinstall. ensure_pkg is idempotent (no-ops once installed).

ensure_pkg ntfs-3g || true
