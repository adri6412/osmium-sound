#!/bin/bash
# Builds the "Now Playing only" interface into build/np/, to be installed on the
# appliance (at /opt/hifi-np) and served by webui_server.py at /np. Same
# Qt->WebAssembly pipeline as scripts/build-site.sh, but with HIFI_NP_BUILD=1 so
# qt/prepare.py and scripts/build-payload.py produce the single-screen variant:
# only the Now Playing screen, with the controls that leave it removed, and the
# three backend services reached same-origin through the device's own proxy
# (/device/{api,src,lms}) instead of the demo's in-browser mocks.
#
#   build/np/
#     index.html          np.html: the full-screen Now Playing page (no discovery)
#     client/np-device.js the host bridge: live VU levels (SSE) + language
#     hifi-qt.{js,wasm}    the interface (Qt for WebAssembly)
#     app.pack.N          its QML (NP-patched), icons, VU looks, translations, fonts
#
#   OSMIUM     the Osmium checkout to build the interface from; defaults to the
#              sibling hifi-media-player working tree (the device's real code),
#              so the build tracks what actually ships, not the demo's pinned SHA.
#   TOOLCHAIN  see scripts/build-qt.sh
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
OUT=build/np
export HIFI_NP_BUILD=1
export OSMIUM=${OSMIUM:-$(cd "$ROOT/../hifi-media-player" && pwd)}
echo "== Osmium (Now Playing build): $OSMIUM"

rm -rf "$OUT"
mkdir -p "$OUT/client"

echo "== interface (Qt for WebAssembly)"
./scripts/build-qt.sh
cp build/qt-build/hifi-qt.js build/qt-build/hifi-qt.wasm build/qt-build/qtloader.js "$OUT/"
python3 scripts/build-payload.py "$OSMIUM" "$OUT"

echo "== page and client"
cp site/np.html "$OUT/index.html"
cp client/np-device.js "$OUT/client/"
cp "$OSMIUM/website/favicon.svg" "$OUT/favicon.svg"
# PWA: installable as an app. The icon is the SVG mark (no rasteriser needed;
# browsers accept an SVG icon with sizes "any" for install).
cp site/manifest.webmanifest site/sw.js "$OUT/"

du -sh "$OUT"; du -sh "$OUT"/*
