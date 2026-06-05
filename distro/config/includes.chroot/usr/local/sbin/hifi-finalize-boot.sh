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
