# shellcheck shell=sh
# 0015 — CamillaDSP engine (optional DSP/parametric EQ, OFF by default).
#
# Sets up everything the Settings → DSP toggle needs, but never enables it:
#   • snd-aloop  — kernel loopback that bridges squeezelite → CamillaDSP.
#   • camilladsp — the DSP binary (downloaded + sha256-verified; x86_64).
#   • a default (empty/passthrough) config + a DISABLED systemd unit.
#
# The toggle (api_server.py set_dsp) redirects squeezelite to the loopback,
# writes the real config and starts the unit only when the user opts in; OFF
# restores the exact bit-perfect squeezelite args. So this migration is inert
# audio-wise — it just makes the option available.
#
# Idempotent: the binary is fetched only if missing, files written only on a
# real diff, and the unit is never enabled here. Non-fatal: a failed/unverified
# download just leaves DSP "unavailable" (the toggle checks for the binary), so
# it never blocks the rest of the OS update.

CDSP_BIN=/usr/local/bin/camilladsp
CDSP_VER=v4.1.3
CDSP_URL="https://github.com/HEnquist/camilladsp/releases/download/${CDSP_VER}/camilladsp-linux-amd64.tar.gz"
CDSP_SHA=55f5ec2ed80fcc79a543672f9f89ace4557d290d80584ef31ee0442111bd0b11

# 1) snd-aloop loopback (load now + on every boot).
ensure_file_content /etc/modules-load.d/hifi-aloop.conf 644 root:root <<'EOF'
# Loopback used by the optional DSP engine (squeezelite -> CamillaDSP).
snd-aloop
EOF
modprobe snd-aloop 2>/dev/null || true

# 2) CamillaDSP binary — download + verify (skipped offline / if already there).
if [ ! -x "$CDSP_BIN" ] && [ "${HIFI_OS_NO_APT:-0}" != 1 ]; then
    tmp=$(mktemp -d 2>/dev/null) || tmp=""
    if [ -n "$tmp" ]; then
        if curl -fsSL "$CDSP_URL" -o "$tmp/c.tgz" 2>/dev/null; then
            got=$(sha256sum "$tmp/c.tgz" 2>/dev/null | cut -d' ' -f1)
            if [ "$got" = "$CDSP_SHA" ]; then
                if tar xzf "$tmp/c.tgz" -C "$tmp" camilladsp 2>/dev/null; then
                    install -m 0755 "$tmp/camilladsp" "$CDSP_BIN" \
                        && mark_changed "installed CamillaDSP $CDSP_VER"
                else
                    log_warn "CamillaDSP extract failed"
                fi
            else
                log_warn "CamillaDSP checksum mismatch (got '$got') — not installing"
            fi
        else
            log_warn "CamillaDSP download failed (will retry next update)"
        fi
        rm -rf "$tmp"
    fi
fi

# 3) Config dir + a harmless default config — created only if absent, so a
#    user's saved EQ (written by the API) is never clobbered on update.
mkdir -p /etc/camilladsp /etc/hifi-player /var/lib/hifi-player 2>/dev/null || true
if [ ! -f /etc/camilladsp/config.yml ]; then
    ensure_file_content /etc/camilladsp/config.yml 644 root:root <<'EOF'
devices:
  samplerate: 48000
  chunksize: 1024
  enable_rate_adjust: true
  target_level: 512
  capture:
    type: Alsa
    channels: 2
    device: "hw:CARD=Loopback,DEV=1"
    format: S32_LE
  playback:
    type: Alsa
    channels: 2
    device: "hw:CARD=Loopback,DEV=1"
    format: S32_LE
filters: {}
mixers: {}
pipeline: []
EOF
fi

# 4) systemd unit — installed but NOT enabled (the toggle starts it on demand).
UNIT=/etc/systemd/system/camilladsp.service
ensure_file_content "$UNIT" 644 root:root <<EOF
[Unit]
Description=CamillaDSP engine (optional DSP/EQ)
After=sound.target

[Service]
Type=simple
ExecStart=$CDSP_BIN /etc/camilladsp/config.yml
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

if migration_changed; then
    systemctl daemon-reload 2>/dev/null || true
fi
