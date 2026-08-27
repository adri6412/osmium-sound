#!/bin/bash
# Installa la UI Qt sul dispositivo in /opt/hifi-qt e registra l'unita'
# systemd. Senza argomenti NON tocca le altre unita': si avvia e si ferma a
# mano, e si torna alla UI in C (o a Electron) con un comando.
#
#   install.sh          installa soltanto
#   install.sh --boot   installa E rende la UI Qt quella di avvio
#                       (abilita hifi-qt, disabilita hifi-native-ui e lightdm)
set -euo pipefail
BOOT=0
[ "${1:-}" = "--boot" ] && BOOT=1
DEST=/opt/hifi-qt
SRC=/home/ssh/native-ui-qt
# Struttura identica a quella che arriva con l'aggiornamento di sistema:
# /opt/hifi-qt si basta da sé (binario, qml, icone, asset, traduzioni), così
# l'interfaccia Qt non dipende da un'altra installata di fianco.
ASSETS="$DEST/assets"
LOCALES="$DEST/locales"
ASSETS_SRC=${ASSETS_SRC:-/opt/hifi-native-ui/assets}
LOCALES_SRC=${LOCALES_SRC:-/opt/hifi-native-ui/locales}

sudo mkdir -p "$DEST"/{qml,icons,assets,locales}
sudo install -m755 "$SRC/hifi-qt" "$DEST/hifi-qt"
sudo cp "$SRC"/qml/*.qml "$DEST/qml/"
sudo cp "$SRC"/icons/*.svg "$DEST/icons/"
[ -d "$ASSETS_SRC" ] || { echo "mancano gli asset in $ASSETS_SRC (ASSETS_SRC=... per indicarli altrove)"; exit 1; }
sudo cp -r "$ASSETS_SRC"/. "$ASSETS/"
sudo cp "$LOCALES_SRC"/*.json "$LOCALES/"

sudo tee /etc/systemd/system/hifi-qt.service >/dev/null <<UNIT
[Unit]
Description=Osmium Sound — interfaccia Qt (DRM/KMS, eglfs)
After=hifi-api.service hifi-vumeter.service
After=systemd-user-sessions.service plymouth-quit-wait.service
Conflicts=lightdm.service hifi-native-ui.service

[Service]
Type=simple
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
StandardInput=tty-fail
StandardOutput=journal
StandardError=journal
WorkingDirectory=$DEST
Environment=QT_QPA_PLATFORM=eglfs
Environment=QT_QPA_EGLFS_ALWAYS_SET_MODE=1
Environment=QT_LOGGING_RULES=qt.qpa.input=false
ExecStartPre=/usr/bin/chvt 1
ExecStart=$DEST/hifi-qt --assets $ASSETS --locales $LOCALES
Restart=on-failure
RestartSec=3
Nice=-5

[Install]
WantedBy=graphical.target
UNIT

sudo systemctl daemon-reload

if [ "$BOOT" = "1" ]; then
    sudo systemctl disable --now hifi-native-ui 2>/dev/null || true
    # La scelta fra le due interfacce la fa hifi-display-mode.sh: scrive
    # /etc/hifi-player/ui-engine e abilita/disabilita le unità di conseguenza,
    # così la pagina di amministrazione web vede lo stato vero.
    if [ -x /usr/local/sbin/hifi-display-mode.sh ]; then
        sudo /usr/local/sbin/hifi-display-mode.sh engine set qt --live
    else
        sudo systemctl disable --now lightdm 2>/dev/null || true
        sudo systemctl enable --now hifi-qt
    fi
    echo "installata in $DEST — e' l'interfaccia di avvio"
    echo "  ritorno alla UI in C: sudo systemctl disable --now hifi-qt && sudo systemctl enable --now hifi-native-ui"
else
    echo "installata in $DEST"
    echo "  avvio:  sudo systemctl stop hifi-native-ui && sudo systemctl start hifi-qt"
    echo "  ritorno: sudo systemctl stop hifi-qt && sudo systemctl start hifi-native-ui"
    echo "  all'avvio: sudo bash install.sh --boot"
fi
