# =====================================================================
#  Unfold (sviluppo lamiera) -> DXF per ogni pezzo piegato.
#  Usa l'addon SheetMetal (new unfolder). K-factor 0.38.
#  Eseguire: FreeCADCmd.exe unfold.py
# =====================================================================
import os, sys
import FreeCAD as App
import Part
import importDXF

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
MOD = os.path.join(os.environ["APPDATA"], "FreeCAD", "Mod", "SheetMetal")
if MOD not in sys.path:
    sys.path.append(MOD)

from SheetMetalNewUnfolder import getUnfold, BendAllowanceCalculator

def biggest_planar_face(shape):
    best, area = -1, -1.0
    for i, f in enumerate(shape.Faces):
        if isinstance(f.Surface, Part.Plane) and f.Area > area:
            area, best = f.Area, i
    return best

def main():
    doc = App.newDocument("unfold")
    bac = BendAllowanceCalculator.from_single_value(0.38, "ansi")
    for name in ["body", "front", "back", "shelf", "lid"]:
        path = os.path.join(OUT, "streamer-%s.step" % name)
        shp = Part.Shape()
        shp.read(path)
        feat = doc.addObject("Part::Feature", "p_" + name)
        feat.Shape = shp
        doc.recompute()
        fi = biggest_planar_face(shp)
        try:
            rootf, unfolded, bend_lines, root_normal, info = getUnfold(
                bac, feat, "Face%d" % (fi + 1))
            fidx = biggest_planar_face(unfolded)
            flatface = unfolded.Faces[fidx]
            edges = []
            for w in flatface.Wires:
                edges += w.Edges
            try:
                edges += bend_lines.Edges
            except Exception:
                pass
            comp = Part.makeCompound(edges)
            o = doc.addObject("Part::Feature", "u_" + name)
            o.Shape = comp
            doc.recompute()
            importDXF.export([o], os.path.join(OUT, "unfold-%s.dxf" % name))
            print("  unfold %-6s OK  (%d edges)" % (name, len(edges)))
        except Exception as ex:
            # pezzo piatto o non sviluppabile: esporto il profilo cosi' com'e'
            fidx = biggest_planar_face(shp)
            flatface = shp.Faces[fidx]
            edges = []
            for w in flatface.Wires:
                edges += w.Edges
            comp = Part.makeCompound(edges)
            o = doc.addObject("Part::Feature", "f_" + name)
            o.Shape = comp
            doc.recompute()
            importDXF.export([o], os.path.join(OUT, "unfold-%s.dxf" % name))
            print("  unfold %-6s piatto/fallback: %s" % (name, type(ex).__name__))
    print("DXF in", OUT)

main()
