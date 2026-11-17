#!/bin/bash
# Builds the kiosk interface for the browser into build/qt-out/.
#   OSMIUM   Osmium Sound checkout to take the interface from (default build/osmium)
#   TOOLCHAIN folder with emsdk/ and qt/6.8.2/{gcc_64,wasm_singlethread}
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
OSMIUM=${OSMIUM:-$ROOT/build/osmium}
TOOLCHAIN=${TOOLCHAIN:-$HOME/osmium/toolchain}
source "$TOOLCHAIN/emsdk/emsdk_env.sh" >/dev/null 2>&1
QT=$TOOLCHAIN/qt/6.8.2
python3 qt/prepare.py "$OSMIUM" build/qt-src
bash "$QT/wasm_singlethread/bin/qt-cmake" -S qt -B build/qt-build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DQT_HOST_PATH="$QT/gcc_64" \
  -DOSMIUM_SRC="$ROOT/build/qt-src" -DOSMIUM_QML="$OSMIUM/native-ui-qt/qml"
cmake --build build/qt-build -j"$(nproc)"
