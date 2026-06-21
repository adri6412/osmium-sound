# =====================================================================
#  Export DXF per laser cut - Proiezione ortogonale XY
#  Estrae il profilo 2D dalla proiezione della forma 3D
# =====================================================================
import os
import FreeCAD as App
from FreeCAD import Vector
import Part
import importDXF

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

def get_2d_projection(shape, name):
    """Proietta forma 3D su XY e estrae il contorno"""
    try:
        # Proiezione ortogonale sulla XY (vettore Z=1 per proiettare in basso)
        # direction=(0,0,1) significa proiezione dal basso verso l'alto (view XY)
        proj = shape.project(Vector(0, 0, 1))

        if proj.Wires:
            return proj
        else:
            print(f"  {name}: nessun wire nella proiezione, provo estrazione diretta")
            # Fallback: estrai il contorno direttamente da tutte le facce
            edges = []
            for face in shape.Faces:
                for wire in face.Wires:
                    edges.extend(wire.Edges)
            if edges:
                return Part.makeCompound(edges)
            return None

    except Exception as e:
        print(f"  {name}: errore proiezione - {e}")
        return None

def export_to_dxf(shape_proj, name):
    """Esporta la proiezione 2D come DXF"""
    try:
        # Crea documento
        doc = App.newDocument(f"dxf_{name}")

        # Aggiungi la proiezione
        feat = doc.addObject("Part::Feature", f"proj_{name}")
        feat.Shape = shape_proj
        doc.recompute()

        # Esporta DXF
        dxf_path = os.path.join(OUT, f"laser-{name}.dxf")
        importDXF.export([feat], dxf_path)

        print(f"  {name:15s}: DXF esportato")
        return True

    except Exception as e:
        print(f"  {name:15s}: export DXF fallito - {e}")
        return False

print("=== DXF Export Laser Cut (Proiezione XY) ===\n")

pieces = ["bottom", "side_left", "side_right", "front", "back", "lid", "shelf"]
success = 0

for piece in pieces:
    step_file = os.path.join(OUT, f"wood-{piece}.step")
    print(f"  {piece:15s}: ", end="")

    if not os.path.exists(step_file):
        print(f"STEP non trovato")
        continue

    try:
        # Carica STEP
        shp = Part.Shape()
        shp.read(step_file)

        # Proietta su XY
        proj = get_2d_projection(shp, piece)

        if proj and export_to_dxf(proj, piece):
            success += 1

    except Exception as e:
        print(f"errore {e}")

print(f"\n[DONE] {success}/{len(pieces)} DXF esportati")
