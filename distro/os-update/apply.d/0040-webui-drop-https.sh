# shellcheck shell=sh
# 0040 — webui: drop HTTPS, plain HTTP only.
#
# webui_server.py no longer generates or loads a TLS cert (self-signed certs
# meant every browser had to click through a "connection not private"
# warning on first visit — worse UX than plain HTTP for a LAN/Tailscale-only
# admin panel). It now always serves plain HTTP on :80 instead of :443.
# The per-device cert/key from before this change are dead weight now that
# nothing reads them; remove them so a factory reset / support bundle
# doesn't carry them around for no reason. Idempotent: rm -f on files that
# may already be gone.

if [ -f /etc/hifi-player/webui-cert.pem ] || [ -f /etc/hifi-player/webui-key.pem ]; then
    rm -f /etc/hifi-player/webui-cert.pem /etc/hifi-player/webui-key.pem
    mark_changed "removed orphaned webui TLS cert/key"
fi

# hifi-webui.service picks up the new plain-HTTP code from the OTA'd
# webui_server.py on its own next restart (apply.sh restarts services it
# touched); nothing else to reconcile here.
