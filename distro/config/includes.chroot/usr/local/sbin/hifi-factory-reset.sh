#!/bin/sh
# shellcheck shell=sh
# HiFi Player — factory reset.
#
# Returns the box to its "first power-on" state and re-arms the first-boot
# provisioning flow (hotspot + wizard), then reboots. This is the ONLY reset
# path for a headless unit (and the only recovery if the web-admin password is
# forgotten), so it is deliberately thorough but bounded: it wipes USER state
# and settings, while preserving the OS-update baseline and the cumulative
# OS-migration ledger (a reset undoes the user's configuration, not the OS
# update history).
#
# Invoked as root by api_server.py (via systemd-run, detached) from:
#   * the kiosk Settings screen (physical access),
#   * the web-admin UI (after re-validating the admin password),
#   * or by hand over SSH for support.
#
# Idempotent enough to re-run safely; ends in `reboot`.
set -u

# shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-log.sh
. /usr/local/sbin/hifi-log.sh
hifi_log_init hifi-factory-reset

log() { echo "I: [hifi-factory-reset] $*"; }

# ── 1) stop services that hold user state ────────────────────────────
log "stopping user-state services"
for unit in smbd nmbd hifi-bluealsa hifi-bt-agent hifi-bt-aplay hifi-bt-watcher \
            bluetooth camilladsp lyrionmusicserver hifi-backup; do
    systemctl stop "$unit" 2>/dev/null || true
done

# Unmount every SMB source (sources_server re-mounts from /etc/hifi-sources.json
# at boot, so dropping the JSON below is what makes them stay gone — there is no
# fstab entry to touch).
for mp in /mnt/hifi-sources/* /mnt/hifi-internal/*; do
    if [ -d "$mp" ]; then
        umount -l "$mp" 2>/dev/null || true
    fi
done

# ── Tailscale: fully sign the box out of the owner's tailnet ──────────
# `tailscale logout` (not just `down`) revokes this node's key with the
# control server, so the appliance actually leaves the owner's tailnet and
# disappears from their admin console, instead of just going offline while
# still counting as an authorized device. A fresh `tailscale up` login is
# required afterwards, exactly like first setup.
if command -v tailscale >/dev/null 2>&1; then
    log "signing out of tailscale"
    tailscale logout 2>/dev/null || true
fi

# ── 2) wipe user state + settings ────────────────────────────────────
log "removing user settings"
# /etc/hifi-player: keep the OTA baseline + public key + channel; drop the rest,
# INCLUDING the web-admin account DB + its per-device cookie signing key.
# github-support-pat is a leftover of the retired vendor remote-support flow
# (nothing re-provisions it any more); wiping it here is just cleanup on
# devices that still have one from an older release.
for f in display-mode ui-resolution pointer-enabled dsp.json dsp-presets.json bluetooth.json \
         samba-cred.json provisioning-state.json webui.db webui-secret.key \
         github-support-pat lyrion-channel lms-skin; do
    rm -f "/etc/hifi-player/$f" 2>/dev/null || true
done
# Reset the OTA channel to the stable default (factory semantics).
printf 'prod\n' > /etc/hifi-player/ota-channel 2>/dev/null || true

# ── SSH/console login ────────────────────────────────────────────────
# The web-admin account is mirrored into a Linux user with full sudo
# (api_server.py set_shell_account). Wiping webui.db above without removing
# that user would leave the previous owner's root-capable login on a device
# that is about to be re-provisioned by someone else. The account name is
# recorded in /etc/hifi-player/shell-account (name only, never a secret).
SHELL_ACCOUNT_FILE=/etc/hifi-player/shell-account
if [ -f "$SHELL_ACCOUNT_FILE" ]; then
    shell_user=$(cat "$SHELL_ACCOUNT_FILE" 2>/dev/null | tr -d '\n\r ')
    case "$shell_user" in
        ''|root|hifi|support|hifimusic) : ;;   # never touch system accounts
        *)
            log "removing SSH login '$shell_user'"
            pkill -KILL -u "$shell_user" 2>/dev/null || true
            userdel -r "$shell_user" 2>/dev/null || true
            ;;
    esac
    rm -f "$SHELL_ACCOUNT_FILE" 2>/dev/null || true
fi
# Back to factory state for the kiosk user: NO password, not the historical
# 'hifi' default — a reset must not reintroduce a known credential.
usermod -p '*' hifi 2>/dev/null || true

# Other config files owned by the appliance.
rm -f /etc/hifi-sources.json /etc/hifi-pairing-tokens.json \
      /etc/samba/hifi-shares.conf /etc/camilladsp/config.yml 2>/dev/null || true

# /var/lib/hifi-player: keep the os-migrations ledger; drop per-user artefacts.
# The whole update/ dir goes too (plan, state, staged payloads): a
# half-finished OTA plan or pending update-mode flag must not resume itself
# or reboot the box a reset owner didn't ask for. /system-update is the
# trigger systemd-system-update-generator(8) looks for at boot — removing it
# here is defensive (api_server.py, which drives a factory reset, never runs
# while it's set), but cheap enough to not skip.
rm -f /var/lib/hifi-player/dsp-target /var/lib/hifi-player/roomcorr-result 2>/dev/null || true
rm -rf /var/lib/hifi-player/update 2>/dev/null || true
rm -f /system-update 2>/dev/null || true

# Stored backup generations (Settings -> Backup e ripristino). These can carry
# the previous owner's Wi-Fi PSK, SMB passwords and web-admin account when
# encrypted — a factory reset that left them in place would hand all of that
# to whoever provisions the device next.
rm -rf /var/lib/hifi-player/backups 2>/dev/null || true
rm -f /etc/hifi-player/backup.json 2>/dev/null || true
systemctl disable --now hifi-backup.timer 2>/dev/null || true

# Saved Wi-Fi networks (forget every SSID/password — the only network
# credential worth resetting; a Wi-Fi profile carries the home network's PSK,
# which the next owner/reinstaller should never be able to recover).
#
# Deliberately NOT touching Ethernet profiles: a wired connection carries no
# secret, just "get an IP via DHCP over this cable" — and this appliance's
# NetworkManager has no-auto-default set, so it never recreates a profile on
# its own once one is deleted. Wiping it here used to strand the box with no
# IP at all after a reset (no path back in except the setup hotspot, which
# isn't always available/wanted). Left alone, the box stays reachable over
# Ethernet immediately after reboot, exactly like it was before the reset.
nmcli -t -f UUID,TYPE connection show 2>/dev/null | while IFS=: read -r uuid type; do
    case "$type" in
        802-11-wireless) nmcli connection delete uuid "$uuid" 2>/dev/null || true ;;
    esac
done

# Defensive: if there is genuinely no Ethernet connection profile (e.g. this
# unit was originally set up over Wi-Fi only, or a profile is missing for any
# other reason), bring one up now so a cable, if plugged in, still gets an IP
# — same mechanism as api_server.py's wired_dhcp(): `nmcli device connect`
# activates the existing profile or auto-creates a fresh DHCP one if none
# exists, for every Ethernet device present.
nmcli -t -f DEVICE,TYPE device status 2>/dev/null | while IFS=: read -r dev dtype; do
    if [ "$dtype" = "ethernet" ]; then
        nmcli device connect "$dev" 2>/dev/null || true
    fi
done

# Bluetooth pairings.
rm -rf /var/lib/bluetooth/* 2>/dev/null || true

# Lyrion Music Server state: preferences (incl. mediadirs written by the
# sources service), library database/cache and user playlists. The server
# binaries stay installed; on next start Lyrion recreates everything from
# scratch, exactly like a fresh install. Both state roots are covered
# (squeezeboxserver = Debian package layout, lyrionmusicserver = newer .debs);
# the service was stopped above so nothing rewrites prefs behind us.
for lyriondir in /var/lib/squeezeboxserver /var/lib/lyrionmusicserver; do
    for sub in prefs cache playlists; do
        rm -rf "${lyriondir:?}/${sub}" 2>/dev/null || true
    done
done

# Electron kiosk localStorage (clears firstSetupComplete so the on-screen wizard
# reappears). userData dir = Electron productName ("Osmium Sound"); wipe a legacy
# name too, defensively.
rm -rf "/home/hifi/.config/Osmium Sound" "/home/hifi/.config/hifi-media-player" 2>/dev/null || true

# ── 3) re-arm first-boot provisioning ────────────────────────────────
log "re-arming first-boot provisioning + graphical target"
printf 'pending\n' > /etc/hifi-player/provisioning-pending
systemctl set-default graphical.target 2>/dev/null || true

# ── 4) reboot into the fresh setup flow ──────────────────────────────
log "rebooting"
sync
systemctl reboot 2>/dev/null || reboot
