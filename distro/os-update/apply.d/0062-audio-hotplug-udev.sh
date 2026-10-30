# shellcheck shell=sh
# 0062 — Segui il DAC USB collegato o scollegato a caldo.
#
# squeezelite sceglie l'uscita solo all'avvio del servizio (ExecStartPre
# hifi_squeezelite.py apply) e non segue l'hotplug: un DAC USB collegato dopo il
# boot non viene preso, e il DAC in uso che viene staccato lascia il player in
# restart-loop su un device che non c'è più (hifi_squeezelite ora ripiega su
# `default`, ma solo al render successivo). Un utente l'ha segnalato dal campo
# (bundle 2026-10-30): oltre 4000 restart di squeezelite dopo aver staccato il
# DAC "Lite".
#
# La regola udev riavvia il player su add/remove di una card audio USB, così
# l'uscita viene rivalutata subito. Limitata a USB (SUBSYSTEMS=="usb"): codec
# onboard, HDMI/DisplayPort e il Loopback snd-aloop non fanno hotplug e
# riavviarli al coldplug del boot sarebbe inutile.
#
# Stesso contenuto in distro/config/includes.chroot/etc/udev/rules.d/
# 62-hifi-audio-hotplug.rules (per le nuove immagini) — tenere allineati.

ensure_file_content /etc/udev/rules.d/62-hifi-audio-hotplug.rules 644 root:root <<'EOF'
# Osmium Sound — follow a USB DAC that is plugged in or out at runtime.
#
# squeezelite's output device is chosen only when the service starts
# (hifi_squeezelite.py apply, the ExecStartPre of squeezelite.service): it does
# not follow a live hotplug. Without this rule, plugging a USB DAC after boot
# leaves the player on the onboard jack, and unplugging the DAC it was using
# leaves it crash-looping on a device that is no longer there (hifi_squeezelite
# now falls back to `default`, but only at its next render).
#
# Restart the player on a USB sound card add/remove so the output is
# re-evaluated at once: a DAC that just appeared is picked up, a DAC that
# vanished falls back to `default`. Scoped to USB (SUBSYSTEMS=="usb") on
# purpose — the onboard HDA codec, HDMI/DisplayPort and the snd-aloop Loopback
# never hotplug, and matching them would restart the player for nothing during
# boot coldplug. card[0-9]* fires once per card, not for every control/pcm
# node; --no-block so udev does not wait on systemd; try-restart so a player
# that is stopped stays stopped.
ACTION=="add|remove", SUBSYSTEM=="sound", KERNEL=="card[0-9]*", SUBSYSTEMS=="usb", \
    RUN+="/usr/bin/systemctl --no-block try-restart squeezelite.service"
EOF

# Carica la nuova regola senza reboot: vale dal prossimo hotplug.
if migration_changed; then
    udevadm control --reload-rules 2>/dev/null || true
fi
