# shellcheck shell=sh
# 0012 — Hibernate (suspend-to-disk / S4) so the appliance RESUMES instead of
# cold-booting.
#
# Why not S3 (suspend-to-RAM): the physical power button is unreachable (the
# mini-PC lives inside a wooden cabinet), so the box is powered off from the UI and
# the mains plug is then pulled; on re-plug the BIOS "restore on AC power loss"
# brings it back. Pulling the plug wipes RAM, so S3 is useless here. Hibernate
# writes RAM to a swapfile on the SSD and powers fully off, so re-plugging resumes
# the saved session (UI + playback state) in ~10-11s instead of a ~17s cold boot.
#
# Provisioned WITHOUT touching the bootloader (any GRUB OTA bricks the headless
# fleet — see the no-bootloader rule). The Debian initramfs resume path is fed the
# swap device + offset purely via /etc/initramfs-tools/conf.d/resume, which
# mkinitramfs copies into the initrd; at boot `init` maps RESUME→resume and reads
# resume_offset from the same conf (verified on the box: init lines 130-134/205,
# premount script honours resume_offset). No kernel cmdline / GRUB change.
#
# The UI "shutdown" action (api_server.py) is what actually calls
# `systemctl hibernate`; this migration only makes hibernation possible.
#
# Verified on the box: S4 supported (/sys/power/disk=platform), lockdown=none,
# Secure Boot disabled, /sys/power/resume_offset present, root=ext4 4096b, no swap.
#
# Idempotent: the swapfile is (re)created only if missing/too small; the resume
# conf is written only on a diff; the initrd is regenerated only when the conf
# changed. No reboot is requested — hibernation takes effect from the next
# UI-shutdown onward. Skipped under the CI idempotency run (HIFI_OS_NO_APT).

SWAPFILE=/swapfile
# RAM is ~3.5 GiB total; size swap a touch above it so a full-RAM image always
# fits with margin.
SWAP_MB=4608   # 4.5 GiB

# The CI idempotency container has no usable swap/fallocate and must not write a
# multi-GB file — bail cleanly (matches 0008's HIFI_OS_NO_APT guard).
[ "${HIFI_OS_NO_APT:-0}" = 1 ] && { log_info "skip hibernate setup (CI / no-apt)"; return 0; }
command -v mkswap >/dev/null 2>&1   || { log_warn "mkswap missing — skip hibernate setup";   return 0; }
command -v filefrag >/dev/null 2>&1 || { log_warn "filefrag missing — skip hibernate setup"; return 0; }

# ── 1. swapfile ≥ RAM ────────────────────────────────────────────────
need_swap=0
if [ ! -f "$SWAPFILE" ]; then
    need_swap=1
else
    cur_mb=$(( $(stat -c %s "$SWAPFILE" 2>/dev/null || echo 0) / 1048576 ))
    [ "$cur_mb" -lt "$SWAP_MB" ] && need_swap=1
fi

if [ "$need_swap" = 1 ]; then
    swapoff "$SWAPFILE" 2>/dev/null || true
    rm -f "$SWAPFILE"
    # Prefer fallocate (instant); fall back to dd if the fs rejects it. Either way
    # we end with a fully-provisioned file (swap can't use a sparse/holey file).
    if ! fallocate -l "${SWAP_MB}M" "$SWAPFILE" 2>/dev/null; then
        dd if=/dev/zero of="$SWAPFILE" bs=1M count="$SWAP_MB" status=none 2>/dev/null || {
            log_warn "could not allocate $SWAPFILE — skip hibernate setup"
            rm -f "$SWAPFILE"; return 0
        }
    fi
    chmod 600 "$SWAPFILE"
    if ! mkswap "$SWAPFILE" >/dev/null 2>&1; then
        log_warn "mkswap failed — skip hibernate setup"; rm -f "$SWAPFILE"; return 0
    fi
    swapon "$SWAPFILE" 2>/dev/null || true
    mark_changed "created $SWAPFILE (${SWAP_MB} MiB)"
fi

# Activate the swap on every boot — the kernel reads the hibernation image from
# active swap at resume.
if ! grep -qE "^[[:space:]]*${SWAPFILE}[[:space:]]" /etc/fstab; then
    printf '%s none swap sw 0 0\n' "$SWAPFILE" >> /etc/fstab
    mark_changed "added $SWAPFILE to /etc/fstab"
fi

# ── 2. resume target: root-fs UUID + swapfile physical offset (no bootloader) ─
ROOT_DEV=$(findmnt -no SOURCE / 2>/dev/null)
ROOT_UUID=$(blkid -s UUID -o value "$ROOT_DEV" 2>/dev/null)
# Physical block offset of the swapfile's first extent, in fs-block units (= page
# size, 4096) — the kernel needs it to find the swap header at resume.
OFFSET=$(filefrag -v "$SWAPFILE" 2>/dev/null | awk '$1=="0:"{sub(/\.\..*/,"",$4); print $4; exit}')

if [ -n "$ROOT_UUID" ] && [ -n "$OFFSET" ]; then
    ensure_file_content /etc/initramfs-tools/conf.d/resume 644 <<EOF
# HiFi Player appliance — hibernate resume target. Points the Debian initramfs
# resume script at the swapfile (root-fs UUID + physical offset) so the box resumes
# the saved image at boot. Set HERE, not on the kernel cmdline, to avoid any
# GRUB/bootloader change. Managed by the OS-update channel (apply.d/0012-hibernate.sh).
RESUME=UUID=$ROOT_UUID
resume_offset=$OFFSET
EOF
    if migration_changed && command -v update-initramfs >/dev/null 2>&1; then
        # The build-time hook warns "no matching swap device" because the target is
        # a swapFILE (not a /dev swap partition) — that warning is expected and
        # harmless; the conf is still baked into the initrd.
        log_info "regenerating initramfs with hibernate resume target…"
        update-initramfs -u >/dev/null 2>&1 || log_warn "update-initramfs failed — old initrd kept"
    fi
else
    log_warn "could not determine root UUID ($ROOT_UUID) / offset ($OFFSET) — resume NOT configured"
fi
