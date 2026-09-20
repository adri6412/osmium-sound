#!/bin/sh
# Osmium Sound — BlueALSA launcher (A2DP source role).
#
# Started by hifi-bluealsa.service. A wrapper rather than a plain ExecStart
# for two reasons:
#
#   * the daemon was renamed `bluealsa` -> `bluealsad` upstream (Debian 13
#     still ships `bluealsa`), so the binary is resolved at run time instead
#     of being frozen into a unit file that travels inside an OTA payload;
#
#   * the optional A2DP codecs (AAC, aptX, aptX-HD, LDAC) are NOT enabled by
#     default — BlueALSA starts with SBC alone unless each one is asked for
#     with -c. Which ones exist depends on how the distribution compiled the
#     package, so ask the binary itself and enable what it admits to having.
#     Asking for a codec that was not compiled in makes the daemon exit, which
#     would leave the owner with no Bluetooth at all rather than with SBC.
set -eu

BIN=$(command -v bluealsad 2>/dev/null || command -v bluealsa 2>/dev/null || true)
if [ -z "$BIN" ]; then
    echo "[hifi-bluealsa] bluealsa is not installed" >&2
    exit 1
fi

# `--help` lists the compiled-in codecs under "Available BT audio codecs".
# Failure here is not fatal: SBC is mandatory and always present.
HELP=$("$BIN" --help 2>&1 || true)
CODECS=""
for c in AAC aptX aptX-HD LDAC; do
    case "$HELP" in
        *"$c"*) CODECS="$CODECS -c $c" ;;
    esac
done

# --keep-alive: squeezelite closes the PCM after its idle timeout (-C) and
# reopens it on the next track. Holding the Bluetooth transport open for a few
# seconds turns that into a gapless resume instead of a fresh A2DP handshake,
# which on most speakers costs a good second of silence.
#
# 🚨 Asked for the same way as the codecs, and for the same reason: the option
# only exists from BlueALSA 4.0, and a device that came up through the OTA
# path rather than the image can still be on 3.x. An option the daemon does
# not know makes it exit on the spot — and since the unit restarts it for
# ever, what the owner would get is not "no gapless resume" but every speaker
# dropping out every three seconds, with nothing in the UI to explain it.
KEEPALIVE=""
case "$HELP" in
    *keep-alive*) KEEPALIVE="--keep-alive=10" ;;
esac

# shellcheck disable=SC2086  # both are deliberate lists of arguments
exec "$BIN" -p a2dp-source $KEEPALIVE $CODECS "$@"
