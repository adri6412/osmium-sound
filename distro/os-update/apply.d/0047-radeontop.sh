# shellcheck shell=sh
# 0047 — radeontop for already-installed units.
#
# AMD/ATI counterpart to 0039-intel-gpu-tools.sh: _gpu_busy_pct()
# (api_server.py) and hifi-beta-agent.py's gpu_busy_pct() both shell out to
# radeontop for the GPU% reading on AMD/ATI hardware (Intel iGPUs still use
# intel_gpu_top). Fleet-wide catch-up so existing devices get the binary
# without a reinstall. ensure_pkg is idempotent (no-ops once installed).

ensure_pkg radeontop || true
