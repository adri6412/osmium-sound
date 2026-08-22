# shellcheck shell=sh
# 0038 — Self-heal a missing /etc/hosts entry for the appliance's own hostname.
#
# distro/config/hooks/normal/0100-system-setup.hook.chroot is supposed to bake
# "127.0.1.1 hifiplayer" into the image at ISO-build time, but real devices
# have been observed with a COMPLETELY EMPTY /etc/hosts (0 bytes — not even a
# 127.0.0.1 localhost line), despite /etc/hostname correctly reading
# "hifiplayer". Root cause: the ISO's bootappend-live carries a
# `hostname=hifiplayer` parameter for live-config's own runtime hostname
# component, and live-build's chroot/binary pipeline appears to leave
# /etc/hosts empty at build time to defer population to that component — which
# never actually runs on a disk-installed device (no `boot=live` at normal
# boot), so the file stays permanently empty. Every `sudo` invocation on an
# affected box then prints "unable to resolve host hifiplayer": cosmetic, but
# noisy in every log and every command whose stderr surfaces to the UI
# (Settings -> SSH, backup/restore, etc).
#
# Append-only, never a wholesale overwrite: a device could plausibly have
# picked up extra LAN host entries by hand, and this only needs to guarantee
# the two lines the box itself depends on.

HOSTS=/etc/hosts
HOST=$(cat /etc/hostname 2>/dev/null || echo hifiplayer)

changed=0
if ! grep -Eq '^[[:space:]]*127\.0\.0\.1[[:space:]]' "$HOSTS" 2>/dev/null; then
    printf '127.0.0.1\tlocalhost\n' >> "$HOSTS"
    changed=1
fi
if ! grep -Eq "^[[:space:]]*127\.0\.1\.1[[:space:]]" "$HOSTS" 2>/dev/null; then
    printf '127.0.1.1\t%s\n' "$HOST" >> "$HOSTS"
    changed=1
fi

if [ "$changed" = 1 ]; then
    mark_changed "populated $HOSTS for $HOST"
fi
