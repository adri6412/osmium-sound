# shellcheck shell=sh
# 0003 — Osmium Sound rebranding.
#
# Updates user-visible identity strings on devices already installed from an
# older image. No reboot is needed for squeezelite or GRUB; Plymouth requires
# initramfs regeneration and therefore requests a reboot — but only when the
# logo was actually replaced.
#
# Idempotency:
#   • Each block checks for the OLD value before acting, so a second run is a
#     clean no-op (changed=0, no reboot) — satisfying the CI idempotency test.

# ── 1. Squeezelite player name ──────────────────────────────────────────────
# The player name is visible in the Lyrion Music Server player list.
SQLT_CONF=/etc/default/squeezelite
if [ -f "$SQLT_CONF" ] && grep -q -- '-n HiFiPlayer' "$SQLT_CONF"; then
    backup_and_edit "$SQLT_CONF" "" 's/-n HiFiPlayer/-n OsmiumSound/'
    # Apply live — no reboot needed.
    systemctl restart squeezelite 2>/dev/null || true
fi

# ── 2. GRUB distributor ─────────────────────────────────────────────────────
# Shown as the OS name in GRUB menus (hidden on normal boots, but present in
# the generated grub.cfg).
GRUB_DEFS=/etc/default/grub
if [ -f "$GRUB_DEFS" ] && grep -q 'GRUB_DISTRIBUTOR=.*HiFi' "$GRUB_DEFS"; then
    backup_and_edit "$GRUB_DEFS" "" \
        's/^GRUB_DISTRIBUTOR=.*/GRUB_DISTRIBUTOR="Osmium Sound"/'
    update-grub 2>/dev/null || true
fi

# ── 3. Plymouth boot logo ────────────────────────────────────────────────────
# Replace the Plymouth splash logo with the Osmium Sound artwork shipped in
# files/logo.png. After writing, the initramfs must be regenerated so the new
# image is embedded; Plymouth reads it at early-boot from the initrd, not from
# the live filesystem. A reboot is requested only when the file actually changed.
LOGO_SRC="$HIFI_PAYLOAD_DIR/files/logo.png"
THEME_DIR=/usr/share/plymouth/themes/hifi
LOGO_DEST="$THEME_DIR/logo.png"

if [ -f "$LOGO_SRC" ] && [ -d "$THEME_DIR" ]; then
    ensure_file_content "$LOGO_DEST" 644 < "$LOGO_SRC"
    if migration_changed; then
        update-initramfs -u 2>/dev/null || true
        request_reboot
    fi
elif [ -f "$LOGO_SRC" ] && [ ! -d "$THEME_DIR" ]; then
    log_warn "Plymouth theme dir $THEME_DIR not found — skipping logo update"
fi
