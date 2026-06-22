# shellcheck shell=sh
# 0003 — Audio fixes for already-installed devices (idempotent, NO reboot).
#
# Mirrors what the UI/System update does going forward, but applies to the
# existing /etc/default/squeezelite so users don't have to re-run anything.
# Restarts squeezelite only when something actually changed.

SQ=/etc/default/squeezelite
if [ -f "$SQ" ] && grep -q '^ARGS=' "$SQ"; then
    sq_changed=0

    # a) Enable bit-perfect DSD (DoP). Without -D squeezelite downconverts DSD to
    #    PCM. Insert it right after the -o device token if not already present.
    if ! grep '^ARGS=' "$SQ" | grep -q -- ' -D'; then
        sed -i "/^ARGS=/ s/\(-o[[:space:]]\{1,\}[^ ']\{1,\}\)/\1 -D/" "$SQ"
        mark_changed "enabled DSD (-D) in $SQ"
        sq_changed=1
    fi

    # b) Migrate a number-based output device (-o hw:N,M) to the stable card name
    #    (-o hw:CARD=<name>,DEV=M). Card numbers reorder across reboots, which is
    #    why the selected DAC reverted to the onboard card; the name is stable.
    o=$(grep '^ARGS=' "$SQ" | sed -n "s/.*-o[[:space:]]\{1,\}\([^ ']\{1,\}\).*/\1/p")
    case "$o" in
        hw:[0-9]*,[0-9]*)
            cardnum=${o#hw:}; cardnum=${cardnum%%,*}
            devnum=${o##*,}
            name=$(aplay -l 2>/dev/null | sed -n "s/^card ${cardnum}: \([^ ]*\) .*/\1/p" | head -n1)
            if [ -n "$name" ]; then
                sed -i "/^ARGS=/ s#-o[[:space:]]\{1,\}${o}#-o hw:CARD=${name},DEV=${devnum}#" "$SQ"
                mark_changed "migrated output device ${o} -> hw:CARD=${name},DEV=${devnum}"
                sq_changed=1
            fi
            ;;
    esac

    if [ "$sq_changed" = 1 ]; then
        systemctl restart squeezelite 2>/dev/null || true
    fi
fi
