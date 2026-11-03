# shellcheck shell=sh
# 0063 — Il player integrato segue la presenza del DAC USB (pausa su Lyrion).
#
# Problema dal campo (Dell 5070): spegnendo il DAC USB, invece di fermarsi la
# musica usciva dall'altoparlante analogico onboard. Causa: alla scomparsa della
# card scelta, hifi_squeezelite ripiegava su `default` (= codec Realtek onboard).
# Ora ripiega sul device silenzioso `null` (nessun suono) e, subito dopo lo
# start, `hifi_squeezelite.py dac-check` mette in pausa il player su Lyrion; al
# rientro del DAC lo fa ripartire. La regola udev 0062 riavvia il servizio su
# add/remove di una card USB, così il ciclo scatta subito.
#
# Due innesti nella unit, via drop-in (additivo, indipendente dalla versione
# della unit base — su un device aggiornato solo via OS OTA l'ultima a scrivere
# squeezelite.service è 0037, che NON ha l'ExecStartPre `apply`):
#   - ExecStartPre `apply`  → ad ogni (ri)avvio rirende gli ARGS, così alla
#     scomparsa del DAC l'uscita diventa `null` invece di crash-loopare;
#   - ExecStartPost `dac-check` → mette in pausa / fa ripartire il player.
# Si azzera prima ciascuna lista (`ExecStartPre=` / `ExecStartPost=` vuoti) per
# non duplicare le righe quando la unit base le ha già (nuove immagini): il
# risultato è esattamente un `apply` e un `dac-check`, su ogni device.
#
# Idempotente: ensure_file_content è un no-op una volta applicato; daemon-reload
# e un restart (breve interruzione audio, come un cambio DAC) solo se il drop-in
# è cambiato e il servizio è attivo.

mkdir -p /etc/systemd/system/squeezelite.service.d

ensure_file_content /etc/systemd/system/squeezelite.service.d/10-hifi-dac-follow.conf 644 root:root <<'EOF'
# Osmium Sound — GENERATED drop-in (hifi-os-update 0063). Do not edit by hand.
#
# Keep the built-in player following its USB DAC on every start, whatever the
# base unit on this device looks like: re-render the arguments (so a gone DAC
# falls back to the silent `null` device instead of crash-looping or playing
# out of the onboard analog output), then pause/resume the player on Lyrion.
# The empty resets clear any same-named line in the base unit so these run
# exactly once.
[Service]
ExecStartPre=
ExecStartPre=-/usr/bin/python3 /usr/local/bin/hifi_squeezelite.py apply
ExecStartPost=
ExecStartPost=-/usr/bin/python3 /usr/local/bin/hifi_squeezelite.py dac-check
EOF

if migration_changed; then
    systemctl daemon-reload 2>/dev/null || true
    if [ "$(systemctl is-active squeezelite.service 2>/dev/null)" = "active" ]; then
        systemctl restart squeezelite.service 2>/dev/null || true
    fi
fi
