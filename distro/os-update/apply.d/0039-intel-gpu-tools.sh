# shellcheck shell=sh
# 0039 — intel-gpu-tools for already-installed units.
#
# get_system_stats() (api_server.py) shells out to intel_gpu_top for the
# dashboard's GPU% tile, but the package was never in the base image before
# 0026-provisioning-webui.sh-era installs picked up the updated package list
# (0400-...-hook.chroot only affects fresh ISO builds). Fleet-wide catch-up so
# existing devices get the binary without a reinstall. ensure_pkg is
# idempotent (no-ops once installed).

ensure_pkg intel-gpu-tools || true
