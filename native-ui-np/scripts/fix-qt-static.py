#!/usr/bin/env python3
"""Qt 6.8.2 for WebAssembly (static): libQt6QuickVectorImage.a and
libQt6QuickVectorImageGenerator.a both define the logging category
lcQuickVectorImage(), and wasm-ld has no --allow-multiple-definition. The
generator's copy is renamed (same length, so the archive stays valid): each
library then uses its own, identical, category.

usage: fix-qt-static.py <qt>/6.8.2/wasm_singlethread
"""
import os, sys

lib = os.path.join(sys.argv[1], "lib", "libQt6QuickVectorImageGenerator.a")
data = open(lib, "rb").read()
old, new = b"lcQuickVectorImagev", b"lcQuickVectorImageG"
if old not in data:
    print("fix-qt-static: already applied" if new in data else "fix-qt-static: symbol not found, nothing to do")
    sys.exit(0)
open(lib, "wb").write(data.replace(old, new))
print("fix-qt-static: renamed %d occurrences in %s" % (data.count(old), lib))
