# =====================================================================
#  Export DXF per laser cut legno (5mm MDF)
#  Estrae la proiezione 2D (vista dall'alto) di ogni pezzo
#
#  Eseguire: FreeCADCmd.exe wood_export_dxf.py
# =====================================================================
import os, sys
import FreeCAD as App
import Part
import importDXF

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

def export_piece_dxf(doc, part_name, step_file):
    """Importa STEP, estrae contorno 2D, esporta DXF"""
    try:
        # Importa il file STEP
        shp = Part.Shape()
        shp.read(step_file)

        # Aggiungi oggetto al documento
        feat = doc.addObject("Part::Feature", part_name)
        feat.Shape = shp
        doc.recompute()

        # Estrai la faccia superiore (proiezione Z) per il DXF
        # Cerchiamo la faccia più grande sul piano XY
        best_face = None
        max_area = 0
        for face in shp.Faces:
            if isinstance(face.Surface, Part.Plane):
                # Controlla se è orizzontale (normale Z)
                normal = face.Surface.Axis
                if abs(normal.z) > 0.9:  # Quasi parallela a Z
                    if face.Area > max_area:
                        max_area = face.Area
                        best_face = face

        if best_face is None:
            print(f"  {part_name}: nessuna faccia orizzontale trovata, salto")
            return False

        # Estrai i contorni (wires) dalla faccia
        edges = []
        for w in best_face.Wires:
            edges += w.Edges

        if not edges:
            print(f"  {part_name}: nessun edge trovato")
            return False

        # Crea compound di edges
        comp = Part.makeCompound(edges)
        o = doc.addObject("Part::Feature", f"dxf_{part_name}")
        o.Shape = comp
        doc.recompute()

        # Esporta DXF
        dxf_file = os.path.join(OUT, f"laser-{part_name}.dxf")
        importDXF.export([o], dxf_file)
        print(f"  {part_name}: OK ({len(edges)} edges) -> {dxf_file}")
        return True

    except Exception as ex:
        print(f"  {part_name}: ERRORE - {type(ex).__name__}: {ex}")
        return False

def main():
    doc = App.newDocument("wood_laser_cut")

    pieces = ["bottom", "side_left", "side_right", "front", "back", "lid", "shelf"]

    print("=== DXF Export Laser Cut ===\n")
    success = 0
    for piece in pieces:
        step_file = os.path.join(OUT, f"wood-{piece}.step")
        if os.path.exists(step_file):
            if export_piece_dxf(doc, piece, step_file):
                success += 1
        else:
            print(f"  {piece}: file non trovato ({step_file})")

    print(f"\n[OK] Esportati {success}/{len(pieces)} pezzi")
    print(f"DXF in: {OUT}")
    print("\nProssimi step:")
    print("  1. Upload DXF al servizio laser cut (es. xTool, Faber)")
    print("  2. Scegli: MDF 5mm naturale o verniciato nero")
    print("  3. Colla PVA per lati/retro, viti M3 per coperchio/frontale")

if __name__ == "__main__":
    main()
