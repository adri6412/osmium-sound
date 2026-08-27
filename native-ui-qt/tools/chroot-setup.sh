#!/bin/bash
# Prepara il chroot trixie con lo stesso Qt del Dell (6.8.2) + Xvfb/Mesa per
# far girare la UI senza schermo.
set -e
R=/srv/trixie
mountpoint -q $R/proc || sudo mount -t proc proc $R/proc
mountpoint -q $R/sys  || sudo mount -t sysfs sys $R/sys
mountpoint -q $R/dev  || sudo mount --bind /dev $R/dev
mountpoint -q $R/dev/pts || sudo mount -t devpts devpts $R/dev/pts
sudo mkdir -p $R/home/coder/osmium
mountpoint -q $R/home/coder/osmium || sudo mount --bind /home/coder/osmium $R/home/coder/osmium
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
  qt6-qpa-plugins libgl1-mesa-dri libegl-mesa0 libgl1 libglx-mesa0 mesa-utils \
  xvfb x11-utils xauth fonts-dejavu-core fonts-dejavu procps curl python3 imagemagick \
  libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xkb1 libxkbcommon0 2>&1 | tail -5
pkg-config --modversion Qt6Quick
ls /usr/lib/x86_64-linux-gnu/qt6/plugins/platforms/
' 2>&1 | tail -15
