# =====================================================================
#  Verifica Automatica Misure DXF
#  Legge i DXF e controlla che le dimensioni siano corrette
# =====================================================================
import os
import Part
from pathlib import Path

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

# Dimensioni attese
EXPECTED = {
    "bottom": {"W": 186.9, "D": 210.0},
    "side_left": {"W": 210.0, "H": 178.3},
    "side_right": {"W": 210.0, "H": 178.3},
    "front": {"W": 186.9, "H": 178.3},
    "back": {"W": 186.9, "H": 178.3},
    "lid": {"W": 186.9, "D": 210.0},
    "shelf": {"W": 186.9, "D": 140.0},
}

def get_bounds(shape):
    """Estrae i limiti (bounding box) di una forma"""
    bb = shape.BoundBox
    return {
        "x_min": bb.XMin, "x_max": bb.XMax, "y_min": bb.YMin, "y_max": bb.YMax,
        "width": bb.XLength, "depth": bb.YLength, "height": bb.ZLength
    }

def measure_piece(piece_name):
    """Legge il DXF e misura il pezzo"""
    dxf_file = os.path.join(OUT, f"laser-{piece_name}.dxf")

    if not os.path.exists(dxf_file):
        print(f"  {piece_name}: FILE NON TROVATO")
        return False

    try:
        import importDXF
        doc = __import__('FreeCAD').newDocument(f"check_{piece_name}")
        importDXF.read(dxf_file)

        # Prendi il primo oggetto
        if not doc.Objects:
            print(f"  {piece_name}: DXF vuoto")
            return False

        obj = doc.Objects[0]
        shp = obj.Shape if hasattr(obj, 'Shape') else obj
        bounds = get_bounds(shp)

        expected = EXPECTED.get(piece_name, {})

        # Determina che misure controllare in base al pezzo
        if piece_name in ["bottom", "lid", "shelf"]:
            actual_w = bounds["width"]
            actual_d = bounds["depth"]
            exp_w = expected.get("W", 0)
            exp_d = expected.get("D", 0)

            w_ok = abs(actual_w - exp_w) < 1.0
            d_ok = abs(actual_d - exp_d) < 1.0

            status = "✓ OK" if (w_ok and d_ok) else "✗ ERRORE"
            print(f"  {piece_name:15s}: {actual_w:6.1f}×{actual_d:6.1f} mm (atteso {exp_w:.1f}×{exp_d:.1f}) {status}")
            return w_ok and d_ok

        else:  # side_left, side_right, front, back
            actual_w = bounds["width"]
            actual_h = bounds["height"]
            exp_w = expected.get("W", 0)
            exp_h = expected.get("H", 0)

            w_ok = abs(actual_w - exp_w) < 1.0
            h_ok = abs(actual_h - exp_h) < 1.0

            status = "✓ OK" if (w_ok and h_ok) else "✗ ERRORE"
            print(f"  {piece_name:15s}: {actual_w:6.1f}×{actual_h:6.1f} mm (atteso {exp_w:.1f}×{exp_h:.1f}) {status}")
            return w_ok and h_ok

    except Exception as e:
        print(f"  {piece_name:15s}: ERRORE - {e}")
        return False

print("\n=== VERIFICA MISURE DXF ===\n")
print("Formato: larghezza×profondità/altezza (in mm)\n")

pieces = ["bottom", "side_left", "side_right", "front", "back", "lid", "shelf"]
results = {}

for piece in pieces:
    results[piece] = measure_piece(piece)

print("\n" + "="*60)
ok_count = sum(1 for v in results.values() if v)
print(f"Risultato: {ok_count}/{len(pieces)} pezzi OK")

if ok_count == len(pieces):
    print("\n✓ TUTTE LE MISURE SONO CORRETTE - PRONTO PER LASER CUT!")
else:
    print("\n✗ Alcuni pezzi hanno misure sbagliate - VERIFICA!")

