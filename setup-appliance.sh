#!/bin/bash
set -e

# setup-appliance.sh
# Esegui questo script come 'root' su un'installazione pulita di Debian Minimal (CLI-only)
# Esempio d'uso: sudo ./setup-appliance.sh path/to/hifi-media-player.deb

if [ "$EUID" -ne 0 ]; then
  echo "Per favore, esegui come root (usa sudo)."
  exit 1
fi

DEB_FILE="$1"

if [ -z "$DEB_FILE" ] || [ ! -f "$DEB_FILE" ]; then
  echo "Errore: devi specificare il percorso del pacchetto .deb."
  echo "Uso: sudo ./setup-appliance.sh <percorso-pacchetto.deb>"
  exit 1
fi

echo "=== 1. Installazione dipendenze minime ==="
# xserver-xorg-video-all e xserver-xorg-input-all servono per la compatibilita hardware
# lightdm e nodm servono come display manager per l'autologin
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  xserver-xorg-core \
  xserver-xorg-video-all \
  xserver-xorg-input-all \
  x11-xserver-utils \
  lightdm \
  alsa-utils \
  sudo \
  curl

echo "=== 2. Creazione utente 'hifi' ==="
if ! id "hifi" >/dev/null 2>&1; then
    useradd -m -G audio,video,plugdev,netdev -s /bin/bash hifi
    echo "hifi:live" | chpasswd
    echo "Utente 'hifi' creato con successo (password: live)."
fi

echo "=== 3. Configurazione Boot Silenzioso (Professional Box) ==="
# Rimuovi messaggi di boot testuali, cursori lampeggianti ecc.
sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT=.*/GRUB_CMDLINE_LINUX_DEFAULT="quiet splash loglevel=0 vt.global_cursor_default=0"/' /etc/default/grub
sed -i 's/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=0/' /etc/default/grub
update-grub

echo "=== 4. Installazione App HiFi Media Player ==="
# Installiamo il deb ignorando le dipendenze grafiche intere e poi facciamo un apt --fix-broken install
dpkg -i "$DEB_FILE" || apt-get install -f -y

echo "=== 5. Configurazione Kiosk e Autologin (LightDM) ==="
mkdir -p /etc/lightdm/lightdm.conf.d/
cat <<EOF > /etc/lightdm/lightdm.conf.d/99-hifi-autologin.conf
[Seat:*]
autologin-user=hifi
autologin-user-timeout=0
user-session=hifi-kiosk
xserver-command=X -s 0 -dpms -nocursor
EOF

# Creiamo una xsession personalizzata per bypassare un Desktop Environment intero
mkdir -p /usr/share/xsessions
cat <<EOF > /usr/share/xsessions/hifi-kiosk.desktop
[Desktop Entry]
Name=HiFi Kiosk
Comment=Start HiFi Media Player Appliance Mode
Exec=/home/hifi/.xsession
Type=Application
EOF

# Script Xsession per l'utente hifi
cat <<EOF > /home/hifi/.xsession
#!/bin/sh
# Disabilita il salvaschermo e il risparmio energetico
xset s off
xset -dpms
xset s noblank

# Assicuriamoci che l'audio non sia mutato (ALSA)
amixer -q sset Master unmute || true

# Avvia l'app in modalita' kiosk
exec /opt/hifi-media-player/hifi-media-player --no-sandbox --disable-dev-shm-usage --enable-features=UseOzonePlatform --ozone-platform=x11
EOF
chmod +x /home/hifi/.xsession
chown hifi:hifi /home/hifi/.xsession

echo "=== 6. Cleanup ==="
apt-get autoremove -y
apt-get clean

echo "=== Setup Completato! ==="
echo "La tua installazione Debian Minimal e' ora configurata come un appliance."
echo "Al prossimo riavvio, non vedrai alcun testo e il sistema fara' il boot direttamente nell'app."
echo ""
echo "Per testare subito, esegui: systemctl restart lightdm"
