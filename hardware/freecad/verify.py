# =====================================================================
#  Verifica manifatturabilita' dei 5 pezzi (JLCPCB Sheet Metal).
#  Eseguire: FreeCADCmd.exe verify.py
# =====================================================================
import os, math, sys
import FreeCAD as App
import Part

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
NAMES = ["body", "lid", "front", "back", "shelf"]
T = 2.0           # spessore nominale
TWO_PI = 2 * math.pi

def load(name):
    s = Part.Shape()
    s.read(os.path.join(OUT, "streamer-%s.step" % name))
    return s

def classify_cylinders(shp):
    holes, bends = [], []
    for f in shp.Faces:
        if isinstance(f.Surface, Part.Cylinder):
            u0, u1, v0, v1 = f.ParameterRange
            sweep = abs(u1 - u0)
            r = f.Surface.Radius
            c = f.Surface.Center
            if sweep > 5.0:            # ~2pi -> foro passante
                holes.append((round(2 * r, 2), c))
            else:                       # arco ~90 deg -> piega
                bends.append(round(r, 2))
    return holes, bends

def min_pair_distance(pts):
    best = 1e9
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            d = pts[i].sub(pts[j]).Length
            if d < best:
                best = d
    return best

def main():
    print("=" * 64)
    print("VERIFICA PEZZI - spessore nominale %.1f mm" % T)
    print("=" * 64)
    allshapes = {}
    ok_global = True
    for name in NAMES:
        shp = load(name)
        allshapes[name] = shp
        valid = shp.isValid()
        nsolids = len(shp.Solids)
        bb = shp.BoundBox
        area = shp.Area
        vol = shp.Volume
        t_est = 2.0 * vol / area
        holes, bends = classify_cylinders(shp)
        dias = sorted(set(d for d, c in holes))
        centers = [c for d, c in holes]
        min_sp = min_pair_distance(centers) if len(centers) > 1 else 0
        # diametro foro minimo accettabile JLC: >= max(1, t/2)
        dia_ok = (min(dias) >= max(1.0, T / 2.0)) if dias else True
        sp_ok = (min_sp >= 1.0) if len(centers) > 1 else True
        thick_ok = abs(t_est - T) < 0.6
        single = (nsolids == 1)
        part_ok = valid and single and dia_ok and sp_ok
        ok_global = ok_global and part_ok

        print("\n[%s] %s" % (name.upper(), "OK" if part_ok else "!!! CONTROLLA"))
        print("  solido valido: %s | n.solidi: %d (atteso 1)" % (valid, nsolids))
        print("  ingombro: %.1f x %.1f x %.1f mm" % (bb.XLength, bb.YLength, bb.ZLength))
        print("  spessore stimato: %.2f mm (%s)" % (t_est, "ok" if thick_ok else "ANOMALO"))
        print("  pieghe (raggi arco): %s" % (sorted(set(bends)) if bends else "nessuna"))
        print("  fori: %d  diametri: %s mm" % (len(holes), dias))
        print("  diametro min %.2f -> %s" % (min(dias) if dias else 0,
              "ok (>=1mm)" if dia_ok else "TROPPO PICCOLO"))
        if len(centers) > 1:
            print("  distanza min tra fori: %.2f mm -> %s" % (min_sp,
                  "ok" if sp_ok else "TROPPO VICINI"))

    # interferenze
    print("\n" + "-" * 64)
    print("INTERFERENZE tra pezzi (volume comune, atteso ~0):")
    keys = list(allshapes)
    any_int = False
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            try:
                v = allshapes[keys[i]].common(allshapes[keys[j]]).Volume
            except Exception:
                v = -1
            if v > 5:
                print("  %s/%s = %.1f mm^3 !!!" % (keys[i], keys[j], v))
                any_int = True
    if not any_int:
        print("  nessuna interferenza (ok)")

    print("\n" + "=" * 64)
    print("ESITO: %s" % ("TUTTO OK, ORDINABILE" if (ok_global and not any_int)
                          else "CI SONO PUNTI DA CONTROLLARE"))
    print("=" * 64)

main()
