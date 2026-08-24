# shellcheck shell=sh
# 0055 — journald: tetti di spazio al journal persistente.
#
# La persistenza del journal è una scelta deliberata (0400 hook in immagine,
# apply.d/0028 in flotta: serve ai support bundle), ma è sempre stata SENZA
# limiti: il default di journald è il 10% del filesystem, e sui dispositivi si
# misurano ~48 MB su disco e ~30 MB di PSS di systemd-journald (i file attivi
# restano mappati in RAM). Un tetto esplicito riporta il costo a pochi MB senza
# rinunciare alla persistenza.
#
# I limiti agiscono alla rotazione, quindi dopo il primo write del drop-in si
# riavvia journald e si fa un vacuum una tantum per applicarli anche ai file
# già esistenti. Il restart di journald è sicuro (i client si riattaccano al
# socket); il vacuum è best-effort.
#
# Stesso contenuto in distro/config/includes.chroot/etc/systemd/journald.conf.d/
# hifi-limits.conf (per le nuove immagini) — tenere allineati.

mkdir -p /etc/systemd/journald.conf.d 2>/dev/null || true

ensure_file_content /etc/systemd/journald.conf.d/hifi-limits.conf 644 root:root <<'EOF'
# HiFi Player — tetti al journal persistente.
#
# La persistenza su disco è voluta (0400 hook / apply.d/0028: serve ai support
# bundle), ma senza limiti journald arriva al default del 10% del filesystem e
# tiene mappati in RAM file di journal grandi (~30 MB di PSS misurati). Questi
# tetti valgono per journald alla rotazione; la migrazione 0055 li applica
# subito anche ai file già esistenti con un vacuum una tantum.
#
# Stesso contenuto in distro/os-update/apply.d/0055-journald-limits.sh —
# tenere allineati.
[Journal]
SystemMaxUse=64M
SystemMaxFileSize=16M
RuntimeMaxUse=32M
EOF

if migration_changed; then
    systemctl restart systemd-journald 2>/dev/null || true
    journalctl --vacuum-size=64M >/dev/null 2>&1 || true
fi
