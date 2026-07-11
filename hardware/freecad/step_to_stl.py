# =====================================================================
#  Riesporta gli STL a partire dagli STEP correnti in out/ (che possono
#  essere stati modificati a mano in FreeCAD, non solo generati dallo
#  script parametrico). Da eseguire ogni volta che uno STEP viene
#  aggiornato manualmente, prima di rilanciare render_parts.py.
#  Eseguire: FreeCADCmd.exe step_to_stl.py
# =====================================================================
import os
import FreeCAD as App
import Part

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
NAMES = ["body", "lid", "front", "back", "shelf"]

for name in NAMES:
    step_path = os.path.join(OUT, "streamer-%s.step" % name)
    stl_path = os.path.join(OUT, "streamer-%s.stl" % name)
    shape = Part.Shape()
    shape.read(step_path)
    shape.exportStl(stl_path)
    bb = shape.BoundBox
    print("OK %-6s  %.1f x %.1f x %.1f mm  -> %s" % (
        name, bb.XLength, bb.YLength, bb.ZLength, stl_path))
