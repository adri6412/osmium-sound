# =====================================================================
#  Verifica Automatica Misure DXF (Parser semplice)
# =====================================================================
import os
import re

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

EXPECTED = {
    "bottom": {"W": 186.9, "D": 210.0},
    "side_left": {"W": 210.0, "H": 178.3},
    "side_right": {"W": 210.0, "H": 178.3},
    "front": {"W": 186.9, "H": 178.3},
    "back": {"W": 186.9, "H": 178.3},
    "lid": {"W": 186.9, "D": 210.0},
    "shelf": {"W": 186.9, "D": 140.0},
}

def parse_dxf_bounds(dxf_file):
    """Estrae i limiti di un DXF leggendo le coordinate"""
    try:
        with open(dxf_file, 'r') as f:
            content = f.read()

        # Estrai coordinate X e Y dal DXF
        # Nel DXF, le coordinate sono precedute da 10 (X) e 20 (Y)
        x_coords = []
        y_coords = []

        lines = content.split('\n')
        i = 0
        while i < len(lines):
            if lines[i].strip() == '10':  # Codice X
                try:
                    x_coords.append(float(lines[i+1].strip()))
                    i += 2
                except:
                    i += 1
            elif lines[i].strip() == '20':  # Codice Y
                try:
                    y_coords.append(float(lines[i+1].strip()))
                    i += 2
                except:
                    i += 1
            else:
                i += 1

        if not x_coords or not y_coords:
            return None

        x_min, x_max = min(x_coords), max(x_coords)
        y_min, y_max = min(y_coords), max(y_coords)

        return {
            "x_min": x_min, "x_max": x_max, "y_min": y_min, "y_max": y_max,
            "width": x_max - x_min, "depth": y_max - y_min
        }
    except Exception as e:
        print(f"Errore parsing: {e}")
        return None

def measure_piece(piece_name):
    """Misura un pezzo DXF"""
    dxf_file = os.path.join(OUT, f"laser-{piece_name}.dxf")

    if not os.path.exists(dxf_file):
        print(f"  {piece_name}: FILE NON TROVATO")
        return False

    bounds = parse_dxf_bounds(dxf_file)
    if not bounds:
        print(f"  {piece_name}: Non riesco a leggere il DXF")
        return False

    expected = EXPECTED.get(piece_name, {})

    # Determina tipo di pezzo
    if piece_name in ["bottom", "lid", "shelf"]:
        actual_w = bounds["width"]
        actual_d = bounds["depth"]
        exp_w = expected.get("W", 0)
        exp_d = expected.get("D", 0)

        w_ok = abs(actual_w - exp_w) < 1.0
        d_ok = abs(actual_d - exp_d) < 1.0
        status = "[OK]" if (w_ok and d_ok) else "[NO]"

        print(f"  {piece_name:15s}: {actual_w:6.1f}x{actual_d:6.1f} mm (atteso {exp_w:.1f}x{exp_d:.1f}) {status}")
        return w_ok and d_ok

    else:  # side, front, back
        actual_w = bounds["width"]
        actual_h = bounds["depth"]  # Nel DXF 2D la "depth" è l'altezza
        exp_w = expected.get("W", 0)
        exp_h = expected.get("H", 0)

        w_ok = abs(actual_w - exp_w) < 1.0
        h_ok = abs(actual_h - exp_h) < 1.0
        status = "[OK]" if (w_ok and h_ok) else "[NO]"

        print(f"  {piece_name:15s}: {actual_w:6.1f}x{actual_h:6.1f} mm (atteso {exp_w:.1f}x{exp_h:.1f}) {status}")
        return w_ok and h_ok

print("\n=== VERIFICA MISURE DXF ===\n")

pieces = ["bottom", "side_left", "side_right", "front", "back", "lid", "shelf"]
results = {}

for piece in pieces:
    results[piece] = measure_piece(piece)

print("\n" + "="*70)
ok_count = sum(1 for v in results.values() if v)
print(f"Risultato: {ok_count}/{len(pieces)} pezzi OK")

if ok_count == len(pieces):
    print("\n[OK] TUTTE LE MISURE SONO CORRETTE - PRONTO PER LASER CUT!")
else:
    print("\n[NO] Alcuni pezzi hanno misure sbagliate - VERIFICA!")
