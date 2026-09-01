#!/bin/bash
# Prepara il chroot trixie con lo stesso Qt del Dell (6.8.2) + Xvfb/Mesa per
# far girare la UI senza schermo.
set -e
R=/srv/trixie
# Se il chroot non esiste ancora: `sudo apt-get install debootstrap` e poi
#   sudo debootstrap --variant=minbase --include=ca-certificates trixie /srv/trixie http://deb.debian.org/debian
# 🚨 I mount qui sotto sono facoltativi: questa macchina di sviluppo e' a sua
# volta un contenitore senza il privilegio di montare (mount: permission
# denied), e apt, make, Xvfb e la UI funzionano lo stesso senza /proc e /sys.
# Con `set -e` un mount fallito fermava tutto prima di installare Qt.
m() { mountpoint -q "$1" 2>/dev/null || sudo mount "${@:2}" "$1" 2>/dev/null || echo "I: mount di $1 non permesso, si prosegue senza"; }
m $R/proc -t proc proc
m $R/sys  -t sysfs sys
m $R/dev  --bind /dev
m $R/dev/pts -t devpts devpts
sudo mkdir -p $R/home/coder/osmium
m $R/home/coder/osmium --bind /home/coder/osmium
sudo cp /etc/resolv.conf $R/etc/resolv.conf
echo 'deb http://deb.debian.org/debian trixie main contrib non-free-firmware' | sudo tee $R/etc/apt/sources.list >/dev/null
sudo chroot $R /bin/bash -c '
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  build-essential pkg-config make g++ \
  qt6-base-dev qt6-declarative-dev qt6-declarative-private-dev qt6-svg-dev \
  qml6-module-qtquick qml6-module-qtquick-window qml6-module-qtqml qml6-module-qtqml-workerscript \
  qml6-module-qtquick-effects qml6-module-qtquick-vectorimage qml6-module-qtquick-shapes \
  qml6-module-qtquick-layouts qml6-module-qtquick-templates qml6-module-qt-labs-folderlistmodel \
  libqt6svg6 libqt6quick6 libqt6quickshapes6 \
  libdrm-dev ffmpeg \
  qt6-qpa-plugins libgl1-mesa-dri libegl-mesa0 libgl1 libglx-mesa0 mesa-utils \
  xvfb x11-utils xauth fonts-dejavu-core fonts-dejavu procps curl python3 imagemagick \
  libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xkb1 libxkbcommon0 2>&1 | tail -5
pkg-config --modversion Qt6Quick
ls /usr/lib/x86_64-linux-gnu/qt6/plugins/platforms/
' 2>&1 | tail -15
