# shellcheck shell=sh
# 0045 — pciutils for already-installed units.
#
# hifi-beta-agent.py's gpu_model() and api_server.py's gpu_model() (system
# stats tile) both shell out to lspci to name the iGPU, but pciutils was
# never in the base image (same gap 0039-intel-gpu-tools.sh closed for
# intel_gpu_top -- lspci just went unnoticed longer since a missing binary
# fails silently into "GPU: —" rather than an error). Fleet-wide catch-up so
# existing devices get the binary without a reinstall. ensure_pkg is
# idempotent (no-ops once installed).

ensure_pkg pciutils || true
