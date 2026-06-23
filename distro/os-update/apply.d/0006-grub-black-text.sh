# shellcheck shell=sh
# 0006 — Hide GRUB's built-in "Booting `<title>'" message (black on black).
#
# Even with the menu hidden (migration 0005), GRUB prints its OWN built-in
# line — `Booting '<entry title>'` — to the terminal right after auto-selecting
# the default entry. With GRUB_DISTRIBUTOR="Osmium Sound" the title is
# "Osmium Sound GNU/Linux", so the user sees "Booting Osmium Sound GNU/Linux"
# for a moment before the kernel/Plymouth take over. That message is emitted by
# GRUB core, not by 10_linux, so blanking the "Loading…" echoes (0005) doesn't
# remove it and there is no config option to silence it.
#
# Fix: render the GRUB terminal's normal text colour black-on-black via a
# grub.d generator snippet. On the black GRUB background every raw GRUB string
# (Booting/Loading/errors) becomes invisible. Using a generator snippet (not a
# grub.cfg edit) means it survives future update-grub runs (e.g. kernel
# upgrades). Idempotent: the file is only (re)written on a content diff.

SNIPPET=/etc/grub.d/09_hifi_silent

if [ -d /etc/grub.d ]; then
    ensure_file_content "$SNIPPET" 755 <<'EOF'
#!/bin/sh
# HiFi Player — hide all raw GRUB terminal text (Booting/Loading/errors) by
# drawing it black-on-black against the black GRUB background. Emitted near the
# top of grub.cfg so it applies before any menuentry runs.
# Managed by OS migration 0006-grub-black-text — do not edit by hand.
exec cat <<'CFG'
set color_normal=black/black
set color_highlight=black/black
CFG
EOF

    if migration_changed; then
        update-grub 2>/dev/null || update-grub2 2>/dev/null || true
    fi
fi
