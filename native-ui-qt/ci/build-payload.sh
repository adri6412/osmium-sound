#!/bin/bash
# Costruisce il pacchetto dell'interfaccia Qt: compila il binario in un
# contenitore Debian 13 (la stessa base dell'apparecchio) e mette insieme
# programma, QML, icone, immagini e traduzioni nella cartella passata come
# primo argomento (predefinita: qtui/).
#
# 🚨 Sorgente unica per DUE catene: l'aggiornamento OTA (build-ui-ota.yml) e
# l'immagine ISO (build-iso.yml). Se cambia qualcosa qui, cambia per entrambe:
# e' il motivo per cui questo non sta dentro un workflow.
#
# Richiede docker sul runner (il lavoro che lo chiama NON deve girare dentro un
# contenitore) piu' node per le note di terze parti.
set -euo pipefail
cd "$(dirname "$0")/../.."

set -e
docker run --rm -v "$PWD:/w" -w /w debian:trixie bash -eu -c '
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y --no-install-recommends \
    build-essential pkg-config qt6-base-dev qt6-declarative-dev libdrm-dev ffmpeg > /dev/null
  cd native-ui-qt && make -j"$(nproc)"
'
ls -l native-ui-qt/hifi-qt


set -e
QT="${1:-qtui}"
case "$QT" in /*) echo "la cartella va indicata relativa alla radice del progetto" >&2; exit 2 ;; esac
rm -rf "$QT"
mkdir -p "$QT/qml" "$QT/icons" "$QT/assets/intro" "$QT/locales"
install -m755 native-ui-qt/hifi-qt "$QT/hifi-qt"
cp native-ui-qt/qml/*.qml "$QT/qml/"
MISSING=0
for n in $(grep -ohE '"[a-z0-9][a-z0-9-]*"' native-ui-qt/qml/*.qml | tr -d '"' | sort -u); do
  if [ -f "native-ui-qt/icons/$n.svg" ]; then
    cp "native-ui-qt/icons/$n.svg" "$QT/icons/"
    [ -f "native-ui-qt/icons/$n-fill.svg" ] && cp "native-ui-qt/icons/$n-fill.svg" "$QT/icons/"
  fi
done
# ogni `name:`/`icon:` del QML deve avere il suo file
for n in $(grep -ohE '(name|icon):\s*"[a-z0-9][a-z0-9-]*"' native-ui-qt/qml/*.qml \
           | grep -oE '"[a-z0-9][a-z0-9-]*"' | tr -d '"' | sort -u); do
  if [ ! -f "$QT/icons/$n.svg" ] && [ -f "native-ui-qt/icons/$n.svg" ]; then
    cp "native-ui-qt/icons/$n.svg" "$QT/icons/"
  fi
done
cp src/assets/vu-meter-dials.png src/assets/vu-meter-bezel.png "$QT/assets/"
cp src/assets/ledbar/*.png "$QT/assets/"
docker run --rm -e QT="$QT" -v "$PWD:/w" -w /w debian:trixie bash -eu -c '
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq && apt-get install -y --no-install-recommends ffmpeg > /dev/null
  ffmpeg -nostdin -loglevel error -i src/assets/intro.mp4 \
    -vf "fps=15,scale=960:-2" -q:v 4 "$QT"/assets/intro/%03d.jpg
'
cp src/i18n/locales/en.json src/i18n/locales/it.json "$QT/locales/"
# le note di terze parti sono un array JS: lo stesso elenco che
# Settings.jsx rende in Electron, riusato senza duplicarlo
QT="$QT" node -e '
  const fs = require("fs");
  const src = fs.readFileSync("src/data/thirdPartyNotices.js", "utf8")
    .replace(/^export const thirdPartyNotices =/m, "module.exports =");
  fs.writeFileSync("/tmp/tpn.cjs", src);
  fs.writeFileSync(process.env.QT + "/locales/third_party.json", JSON.stringify(require("/tmp/tpn.cjs")));
'
test -s "$QT/locales/third_party.json"
test "$(ls "$QT/assets/intro" | wc -l)" -gt 50 || { echo "::error::intro frames missing"; exit 1; }
# 🚨 Ponte per gli apparecchi fermi alla 2.5.24-dev.4: la loro verifica di
# staging pretende ancora un file `hifi-media-player` e senza di esso rifiuta
# il pacchetto, bloccando tutto l'aggiornamento. Chi installa guarda `hifi-qt`
# per primo, quindi il contenuto finisce comunque in /opt/hifi-qt.
cat > "$QT/hifi-media-player" <<'SHIM'
#!/bin/sh
# Ponte di compatibilita': questa e' l'interfaccia Qt, non l'app Electron.
exec "$(dirname "$0")/hifi-qt" "$@"
SHIM
chmod 755 "$QT/hifi-media-player"

du -sh "$QT"; ls "$QT/icons" | wc -l



