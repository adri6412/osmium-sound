# shellcheck shell=sh
# 0043 — Blacklist the dw_dmac / dw_dmac_core kernel modules (Synopsys
# DesignWare DMA controller, part of this board's Intel LPSS).
#
# Their .shutdown driver hook (dw_shutdown -> do_dw_dma_disable) crashes the
# kernel every time device_shutdown() runs it as part of a reboot/poweroff —
# on this board that shows up as the box hanging forever behind the Plymouth
# splash on every reboot/shutdown, never actually powering off or coming back
# (found via Settings -> Debug -> disable boot splash, which is what let the
# crash text below actually be seen instead of hidden behind the splash):
#
#   kernel_restart -> device_shutdown -> dw_shutdown -> do_dw_dma_disable  (oops)
#
# This is a known issue on Intel LPSS-based Atom/Celeron boards (see e.g. the
# UP-board community forum's identical dw_dmac shutdown hang on the same class
# of hardware). This appliance only ever uses USB (DAC, touch) and HDMI — no
# I2C/SPI/UART peripheral depends on this DMA engine here, so losing it just
# means those controllers fall back to interrupt/PIO-driven I/O, same as any
# board that never had this DMA controller at all.
#
# Blacklisting only prevents the module from loading on the NEXT boot — an
# already-loaded instance on the box applying this update is left alone until
# then, so this migration is safe to run live. No reboot requested here: the
# very next reboot (whenever the owner or a later update step causes one)
# picks it up on its own, which is also the fix actually taking effect.

BLACKLIST=/etc/modprobe.d/hifi-blacklist-dw-dmac.conf

ensure_file_content "$BLACKLIST" 644 <<'EOF'
# Installed by HiFi Player OS migration 0043 — see that script for why.
blacklist dw_dmac
blacklist dw_dmac_core
EOF
