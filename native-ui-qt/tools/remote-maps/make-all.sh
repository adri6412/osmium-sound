#!/bin/bash
# Renders every remote key map (three models, it + en) as the interface shows
# them and writes them where the kiosk and the web admin read them.
# Needs python3 with Pillow (python3 -m venv v && v/bin/pip install pillow).
set -e
cd "$(dirname "$0")"
PY=${PY:-python3}
OUT=$(mktemp -d)
for m in firetv g20s xiaomi; do
  for l in it en; do
    $PY remote-map.py "$m-photo.jpg" "${m}_keys.py" "$l" "$OUT/$m-$l.png" "" --ui
    $PY -c "from PIL import Image; im = Image.open('$OUT/$m-$l.png').convert('RGB'); [im.save(d + '/$m-$l.jpg', quality=86, optimize=True, progressive=True) for d in ('../../assets/remotes', '../../../admin-webui/public/remotes')]"
  done
done
rm -rf "$OUT"
