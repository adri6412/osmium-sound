#!/bin/bash
set -e

echo "=== Building HiFi Media Player Debian App ==="
# Clean precedenti build
rm -rf dist/

# Install dipendenze
npm ci

# Genera il file .deb dell'app tramite electron-builder
npm run package -- --linux deb

# Verifica che il pacchetto sia stato generato
DEB_FILE=$(ls dist/*.deb 2>/dev/null | head -n 1)

if [ -z "$DEB_FILE" ]; then
    echo "Errore: Nessun pacchetto .deb generato in dist/"
    exit 1
fi

echo "Pacchetto trovato: $DEB_FILE"

echo "=== Setup Live-Build Environment ==="

# Copia il pacchetto .deb nella directory per i pacchetti extra locali chroot di live-build
mkdir -p live-build-config/config/packages.chroot/
cp "$DEB_FILE" live-build-config/config/packages.chroot/

echo "=== Building Debian ISO ==="
# Avvia la creazione dell'ISO tramite lb build all'interno della directory di config
cd live-build-config

# Pulizia precedente se esiste l'ambiente
if [ -d ".build" ]; then
    sudo lb clean
fi

sudo lb config
sudo lb build

# Sposta l'ISO generata nella cartella principale
mv live-image-amd64.hybrid.iso ../hifi-player-installer.iso

echo "=== Build Complete! ==="
echo "La tua ISO si trova in ./hifi-player-installer.iso"
