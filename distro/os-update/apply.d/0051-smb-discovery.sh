# shellcheck shell=sh
# 0051 — wsdd2, so the Samba shares are visible in Windows' "Network".
#
# The shares served by sources_server.py (0018-samba-internal-shares.sh) could
# only be reached by typing \\<ip>\<share> by hand: no OS browses SMB servers
# over SMB itself. Windows Explorer's "Network" pane has used WS-Discovery since
# it dropped SMB1, and the legacy NetBIOS browse path is gone here anyway —
# 0031-boot-speed-samba.sh masks nmbd (it cost ~64% of userspace boot). wsdd2 is
# the WSD responder that fills that hole, and it answers LLMNR too, so the
# single-label \\hifiplayer resolves again as a side effect. The macOS/Linux
# half of the problem is a Bonjour record instead, published by
# sources_server.py through avahi (already installed) — nothing to install here.
#
# wsdd2, NOT the python wsdd: the latter is absent from trixie (bookworm and
# forky have it, the trixie cycle does not), and this fleet spans both releases.
# wsdd2 is in both, is a small C daemon, and its packaged unit is BindsTo= +
# PartOf= smbd.service, so it follows smbd's lifecycle on its own.
#
# Installed but NOT left running here: like samba itself, discovery only makes
# sense once a disk is adopted, and 0031 exists precisely because a daemon
# idling through boot for nothing is a measurable cost. sources_server.py's
# regen_samba_shares() enables/disables the unit together with smbd on every
# start of hifi-sources, so a device that already has shares converges as soon
# as the matching system bundle lands.
#
# Hence the cleanup below: Debian's postinst enables *and starts* wsdd2, and
# because the unit BindsTo= smbd, starting it drags smbd up with it — on a
# share-less device that would leave both daemons running to announce nothing.
# Gated on there being no share, so it can never fight regen_samba_shares() on a
# device that has one, and on the current unit state, so a second run is a clean
# no-op (the idempotency test asserts changed=0).

ensure_pkg wsdd2 || true

command -v systemctl >/dev/null 2>&1 || return 0

# A share section ("[Musica]") in the generated include = at least one adopted
# disk. Missing file / no section = nothing shared.
if [ -f /etc/samba/hifi-shares.conf ] && grep -q '^\[' /etc/samba/hifi-shares.conf 2>/dev/null; then
    return 0
fi

state=$(systemctl is-enabled wsdd2.service 2>/dev/null) || state=""
case "$state" in
    enabled|enabled-runtime)
        if systemctl disable --now wsdd2.service >/dev/null 2>&1; then
            mark_changed "disabled wsdd2.service (no Samba share to announce yet)"
        fi
        ;;
esac

# And put smbd back down if that install-time start is the only reason it is up.
# `is-enabled` is the safe discriminator: regen_samba_shares() always enables the
# unit when it wants it running, so disabled-but-active can only be this.
if [ "$(systemctl is-enabled smbd.service 2>/dev/null || echo unknown)" = "disabled" ] \
   && systemctl is-active --quiet smbd.service 2>/dev/null; then
    if systemctl stop smbd.service >/dev/null 2>&1; then
        mark_changed "stopped smbd.service (pulled up by the wsdd2 install, no share configured)"
    fi
fi
