# shellcheck shell=sh
# 0014 — Allow an on-screen mouse pointer (Settings → Mouse pointer).
#
# The kiosk used to start X with `-nocursor`, which hard-disables the hardware
# cursor: no CSS or unclutter trick can bring it back, so a user without a
# touchscreen had no usable pointer. We now drop `-nocursor` and instead hide the
# cursor at the session layer (unclutter, started conditionally by ~/.xsession).
# The API toggle (pointer-enabled flag + live unclutter start/stop) then controls
# visibility at runtime.
#
# The .xsession change itself ships via 0001 (self-healing xsession); this
# migration only fixes the lightdm X-server command on already-installed devices.
# Removing the flag only takes effect on the next X start, so we reboot — but ONLY
# when we actually changed the file (idempotent: a clean no-op once applied).

LIGHTDM_CONF=/etc/lightdm/lightdm.conf.d/99-hifi-autologin.conf

if [ -f "$LIGHTDM_CONF" ] && grep -q -- '-nocursor' "$LIGHTDM_CONF"; then
    # Strip the ` -nocursor` token from the xserver-command line. Empty validator:
    # lightdm has no quick config check, and backup_and_edit restores on sed error.
    if backup_and_edit "$LIGHTDM_CONF" "" 's/ -nocursor//'; then
        log_info "removed -nocursor from $LIGHTDM_CONF"
        request_reboot
    fi
fi

# Make sure the cursor-hider is present so the touchscreen default still hides the
# pointer (it ships in the image's package list; this covers older installs).
ensure_pkg unclutter || true
