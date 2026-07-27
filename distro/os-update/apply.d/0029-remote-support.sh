# shellcheck shell=sh
# 0029 — Remote-support prerequisites (Tailscale APT repo + 'support' user).
#
# Companion to the support-bundle logging migration (0028). Ships the
# fleet-wide prerequisites for the "remote support" button in Settings
# (api_server.py set_remote_support): the Tailscale APT repo (so `apt-get
# install tailscale` works instantly on demand, without configuring an
# external repo at request time) and a dedicated unprivileged 'support' system
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

KEYRING=/usr/share/keyrings/tailscale-archive-keyring.gpg

if [ ! -s "$KEYRING" ] && [ "${HIFI_OS_NO_APT:-0}" != 1 ]; then
    mkdir -p /usr/share/keyrings 2>/dev/null || true
    if curl -fsSL https://pkgs.tailscale.com/stable/debian/bookworm.noarmor.gpg \
            -o "$KEYRING.tmp" 2>/dev/null; then
        mv -f "$KEYRING.tmp" "$KEYRING"
        mark_changed "installed Tailscale APT keyring"
    else
        rm -f "$KEYRING.tmp"
        log_warn "Tailscale keyring download failed (will retry next update)"
    fi
fi

ensure_file_content /etc/apt/sources.list.d/tailscale.list 644 root:root <<'EOF'
deb [signed-by=/usr/share/keyrings/tailscale-archive-keyring.gpg] https://pkgs.tailscale.com/stable/debian bookworm main
EOF

if migration_changed && [ "${HIFI_OS_NO_APT:-0}" != 1 ]; then
    apt-get update 2>/dev/null || true
fi

if [ "${HIFI_OS_NO_APT:-0}" != 1 ] && ! command -v tailscale >/dev/null 2>&1; then
    if DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tailscale 2>/dev/null; then
        mark_changed "installed tailscale"
    else
        log_warn "could not install tailscale (will retry next update)"
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
