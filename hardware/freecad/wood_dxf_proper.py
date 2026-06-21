# =====================================================================
#  Export DXF per laser cut - Proiezione 2D corretta
#  Usa Draft.makeShape2D() per piattare i pezzi 3D
# =====================================================================
import os
import FreeCAD as App
from FreeCAD import Vector, Placement, Rotation
import Part
import Draft

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

def export_to_dxf_proper(shape, name):
    """Converte forma 3D a 2D via Draft.makeShape2D e esporta DXF"""
    try:
        # Crea documento
        doc = App.newDocument(f"dxf_{name}")

        # Aggiungi la forma 3D
        feat = doc.addObject("Part::Feature", f"part_{name}")
        feat.Shape = shape
        doc.recompute()

        # Converti a 2D tramite Draft.makeShape2D
        # Questo proietta la forma sulla XY
        shape_2d = Draft.makeShape2D(shape, 1.0)

        if shape_2d:
            # Aggiungi al documento
            dxf_obj = doc.addObject("Part::Feature", f"2d_{name}")
            dxf_obj.Shape = shape_2d
            doc.recompute()

            # Esporta come DXF
            dxf_path = os.path.join(OUT, f"laser-{name}.dxf")
            import importDXF
            importDXF.export([dxf_obj], dxf_path)

            print(f"  {name:15s}: OK")
            return True
        else:
            print(f"  {name:15s}: shape2d vuoto")
            return False

    except Exception as e:
        print(f"  {name:15s}: {type(e).__name__}: {e}")
        return False

print("=== DXF Export Laser Cut (Proiezione 2D) ===\n")

pieces = ["bottom", "side_left", "side_right", "front", "back", "lid", "shelf"]
success = 0

for piece in pieces:
    step_file = os.path.join(OUT, f"wood-{piece}.step")
    if os.path.exists(step_file):
        try:
            shp = Part.Shape()
            shp.read(step_file)
            if export_to_dxf_proper(shp, piece):
                success += 1
        except Exception as e:
            print(f"  {piece:15s}: lettura STEP fallita - {e}")
    else:
        print(f"  {piece:15s}: STEP non trovato")

print(f"\n[DONE] {success}/{len(pieces)} DXF esportati in {OUT}")
