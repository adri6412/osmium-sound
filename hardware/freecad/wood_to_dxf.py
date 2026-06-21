# =====================================================================
#  Export DXF semplificato per laser cut legno
#  Proietta ogni pezzo su XY e esporta il contorno
# =====================================================================
import os
import FreeCAD as App
from FreeCAD import Vector
import Part
import Draft

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

def export_to_dxf(shape, name):
    """Estrae il contorno e lo esporta come DXF"""
    try:
        # Crea documento
        doc = App.newDocument(f"dxf_{name}")

        # Aggiungi la forma
        feat = doc.addObject("Part::Feature", f"part_{name}")
        feat.Shape = shape

        # Estrai il maggiore contorno (wires)
        wires = shape.Wires
        if not wires:
            print(f"  {name}: nessuna Wire trovata")
            return False

        # Crea compound di edges (contorno completo)
        edges = []
        for wire in wires:
            edges.extend(wire.Edges)

        if edges:
            comp = Part.makeCompound(edges)
            doc_obj = doc.addObject("Part::Feature", f"edges_{name}")
            doc_obj.Shape = comp

            # Esporta come DXF
            dxf_path = os.path.join(OUT, f"laser-{name}.dxf")
            import importDXF
            importDXF.export([doc_obj], dxf_path)

            print(f"  {name}: DXF OK")
            return True
        else:
            print(f"  {name}: nessun edge")
            return False

    except Exception as e:
        print(f"  {name}: ERRORE - {type(e).__name__}: {e}")
        return False

print("=== DXF Export per Laser Cut ===\n")

pieces = ["bottom", "side_left", "side_right", "front", "back", "lid", "shelf"]
success = 0

for piece in pieces:
    step_file = os.path.join(OUT, f"wood-{piece}.step")
    if os.path.exists(step_file):
        try:
            shp = Part.Shape()
            shp.read(step_file)
            if export_to_dxf(shp, piece):
                success += 1
        except Exception as e:
            print(f"  {piece}: errore lettura STEP - {e}")
    else:
        print(f"  {piece}: file STEP non trovato")

print(f"\n[OK] {success}/{len(pieces)} DXF esportati")
