# shellcheck shell=sh
# 0030 — prerequisites for the GitHub-Actions-mediated remote-support key
# minting (replaces the old design: a single static, reusable Tailscale
# auth key published at a public URL, which leaked twice and — being
# reusable — gave anyone who found it standing access to the tailnet).
#
# See api_server.py (_dispatch_mint_workflow/_remote_support_worker) and
# .github/workflows/remote-support-mint.yml for the new flow: the device
# asks that workflow to mint a fresh, single-use, 5-minute Tailscale key,
# gated behind a human reviewer, and gets it back encrypted (age) to a
# one-time key it generates per request.
#
# Two things a device needs for that:
#   - the `age` binary (Debian bookworm main, apt-installable)
#   - a low-value GitHub PAT (repo-scoped, Actions read/write only — can
#     only enqueue a request that a human must approve, nothing more) to
#     call the GitHub API. It is NEVER committed to this repo: it's
#     materialized into files/github-support-pat.txt by the release
#     pipeline (.github/workflows/build-ui-ota.yml) from a GitHub secret,
#     the same way OTA_SIGNING_KEY is handled — see that workflow.
#
# Idempotent + CI-safe: ensure_pkg/ensure_file_content are no-ops once
# applied (same conventions as 0029-remote-support.sh). Never reboots.

ensure_pkg age

if [ -f "$HIFI_PAYLOAD_DIR/files/github-support-pat.txt" ]; then
    ensure_file_content /etc/hifi-player/github-support-pat 600 root:root \
        < "$HIFI_PAYLOAD_DIR/files/github-support-pat.txt"
else
    log_warn "files/github-support-pat.txt not present in this payload — remote-support toggle will stay unavailable until a release ships it"
fi
