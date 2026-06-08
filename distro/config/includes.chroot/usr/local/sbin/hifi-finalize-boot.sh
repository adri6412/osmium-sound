#!/bin/sh
# Apply the silent/branded boot configuration (GRUB hidden + Plymouth splash).
# Run both in the live chroot AND on the installed system (via preseed
# late_command), because the Debian installer regenerates GRUB on the target
# and would otherwise overwrite these settings.
set -e

GRUB=/etc/default/grub
if [ -f "$GRUB" ]; then
    sed -i 's/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=0/' "$GRUB"
    sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT=.*/GRUB_CMDLINE_LINUX_DEFAULT="quiet splash loglevel=0 vt.global_cursor_default=0 rd.udev.log_level=3 udev.log_priority=3"/' "$GRUB"
    if grep -q '^GRUB_TIMEOUT_STYLE=' "$GRUB"; then
        sed -i 's/^GRUB_TIMEOUT_STYLE=.*/GRUB_TIMEOUT_STYLE=hidden/' "$GRUB"
    else
        echo 'GRUB_TIMEOUT_STYLE=hidden' >> "$GRUB"
    fi
    grep -q '^GRUB_DISTRIBUTOR='       "$GRUB" && sed -i 's/^GRUB_DISTRIBUTOR=.*/GRUB_DISTRIBUTOR="HiFi Player"/' "$GRUB" || echo 'GRUB_DISTRIBUTOR="HiFi Player"' >> "$GRUB"
    grep -q '^GRUB_DISABLE_OS_PROBER='  "$GRUB" || echo 'GRUB_DISABLE_OS_PROBER=true'  >> "$GRUB"
    grep -q '^GRUB_RECORDFAIL_TIMEOUT=' "$GRUB" || echo 'GRUB_RECORDFAIL_TIMEOUT=0'    >> "$GRUB"

    # ── Make GRUB itself invisible (no menu, no "Loading Linux…" text) ──
    # Use a black graphical terminal so nothing GRUB prints is ever visible,
    # and disable the boot beep / submenu.
    grep -q '^GRUB_TERMINAL_OUTPUT=' "$GRUB" \
        && sed -i 's/^GRUB_TERMINAL_OUTPUT=.*/GRUB_TERMINAL_OUTPUT="gfxterm"/' "$GRUB" \
        || echo 'GRUB_TERMINAL_OUTPUT="gfxterm"' >> "$GRUB"
    grep -q '^GRUB_GFXMODE='         "$GRUB" || echo 'GRUB_GFXMODE=auto'          >> "$GRUB"
    grep -q '^GRUB_GFXPAYLOAD_LINUX=' "$GRUB" || echo 'GRUB_GFXPAYLOAD_LINUX=keep' >> "$GRUB"
    grep -q '^GRUB_DISABLE_SUBMENU='  "$GRUB" || echo 'GRUB_DISABLE_SUBMENU=y'     >> "$GRUB"
    grep -q '^GRUB_INIT_TUNE='        "$GRUB" || echo 'GRUB_INIT_TUNE=""'          >> "$GRUB"
    # Pure-black GRUB background → the "Loading…" echoes (if any) blend in.
    grep -q '^GRUB_BACKGROUND=' "$GRUB" || echo 'GRUB_BACKGROUND=/boot/grub/hifi-bg.png' >> "$GRUB"
fi

# Solid black GRUB background image (so the graphical terminal shows nothing).
if command -v convert >/dev/null 2>&1; then
    convert -size 1920x1080 xc:black /boot/grub/hifi-bg.png 2>/dev/null || true
fi

# Silence the "Loading Linux …" / "Loading initial ramdisk …" messages that
# GRUB's /etc/grub.d/10_linux emits into grub.cfg. Once the menu is hidden,
# these are the only visible text. We do NOT delete structural lines (that
# would break $message); instead we blank the printed strings so the generated
# `echo` produces nothing. Idempotent and safe across grub package updates
# (the finalize/OTA path re-runs this).
if [ -f /etc/grub.d/10_linux ]; then
    sed -i \
        -e 's/Loading Linux %s \.\.\./ /g' \
        -e 's/Loading Linux \.\.\./ /g' \
        -e 's/Loading initial ramdisk \.\.\./ /g' \
        /etc/grub.d/10_linux 2>/dev/null || true
fi

# Quiet the kernel console too
mkdir -p /etc/sysctl.d
echo 'kernel.printk = 3 3 3 3' > /etc/sysctl.d/20-quiet-printk.conf

# Branded splash
if command -v plymouth-set-default-theme >/dev/null 2>&1; then
    plymouth-set-default-theme hifi || true
fi

# Regenerate initramfs (embed splash) and grub.cfg. Allowed to fail in the
# live chroot (no real disk); succeeds on the installed target.
update-initramfs -u 2>/dev/null || true
update-grub 2>/dev/null || true
