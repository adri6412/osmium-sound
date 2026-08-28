#!/bin/bash
# Compila hifi-qt nel chroot trixie (stesso Qt 6.8 del Dell).
set -e
SRC=/home/coder/osmium/hifi-media-player/native-ui-qt
R=/srv/trixie
sudo mkdir -p $R/build/hifi-qt
sudo rsync -a --delete --exclude build --exclude hifi-qt $SRC/ $R/build/hifi-qt/
sudo mkdir -p $R/build/assets $R/build/locales
sudo rsync -a /home/coder/osmium/hifi-media-player/native-ui/assets/ $R/build/assets/
sudo rsync -a /home/coder/osmium/hifi-media-player/native-ui/locales/ $R/build/locales/
sudo chroot $R /bin/bash -c "cd /build/hifi-qt && make -j8 2>&1 | grep -E 'error|Error|warning: unused|undefined' | head -40; ls -la hifi-qt 2>/dev/null | awk '{print \$5, \$9}'"
