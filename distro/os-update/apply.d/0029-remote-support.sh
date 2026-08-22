# shellcheck shell=sh
# 0029 — Remote-support prerequisites (Tailscale APT repo + 'support' user).
#
# Companion to the support-bundle logging migration (0028). Ships the
# fleet-wide prerequisites for the "remote support" button in Settings
# (api_server.py set_remote_support): the Tailscale installation path used by
# the OTA update (via the official install script, which handles the repo and
# signing key automatically) and a dedicated unprivileged 'support' system
# user (the SSH login target — Tailscale SSH authenticates by Tailscale
# identity/ACL, not a local password, so this account is created locked, no
# password ever set).
#
# The package is installed here during OS updates so the Settings toggle can
# work immediately once the device has been updated, without relying on a
# runtime apt install from the web UI.
#
# Idempotent + CI-safe: the keyring is fetched only once (skipped entirely
# under HIFI_OS_NO_APT=1, same guard as 0015-camilladsp.sh); ensure_file_content
# and the `id support` check are no-ops once applied. Never reboots.

if [ "${HIFI_OS_NO_APT:-0}" != 1 ] && ! command -v tailscale >/dev/null 2>&1; then
    if curl -fsSL https://tailscale.com/install.sh | sh; then
        mark_changed "installed tailscale"
    else
        log_warn "could not install tailscale via official installer (will retry next update)"
    fi
fi

if ! id support >/dev/null 2>&1; then
    if useradd --system --create-home --shell /bin/bash \
            --groups adm,systemd-journal support 2>/dev/null; then
        passwd -l support >/dev/null 2>&1 || true
        mark_changed "created 'support' system user"
    else
        log_warn "could not create 'support' user (will retry next update)"
    fi
fi
