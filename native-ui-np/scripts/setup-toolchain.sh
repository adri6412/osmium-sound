#!/bin/bash
# The toolchain of the kiosk's WebAssembly build: emsdk 3.1.56 (what Qt 6.8
# is built with) and Qt 6.8.2 (the appliance's version), host tools plus
# wasm_singlethread, into TOOLCHAIN (default ~/osmium/toolchain).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
TOOLCHAIN=${TOOLCHAIN:-$HOME/osmium/toolchain}
mkdir -p "$TOOLCHAIN" && cd "$TOOLCHAIN"
[ -d emsdk ] || git clone -q --depth 1 https://github.com/emscripten-core/emsdk.git
./emsdk/emsdk install 3.1.56 >/dev/null
./emsdk/emsdk activate 3.1.56 >/dev/null
[ -d venv ] || python3 -m venv venv
venv/bin/pip -q install aqtinstall
[ -d qt/6.8.2/gcc_64 ] || venv/bin/aqt install-qt linux desktop 6.8.2 linux_gcc_64 -O qt -m qtshadertools >/dev/null
[ -d qt/6.8.2/wasm_singlethread ] || venv/bin/aqt install-qt all_os wasm 6.8.2 wasm_singlethread -O qt -m qtshadertools >/dev/null
chmod +x qt/6.8.2/wasm_singlethread/bin/qt-cmake*
python3 "$HERE/fix-qt-static.py" qt/6.8.2/wasm_singlethread
echo "toolchain ready in $TOOLCHAIN"
