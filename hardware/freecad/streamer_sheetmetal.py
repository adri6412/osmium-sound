# =====================================================================
#  Scocca Network Streamer HiFi - LAMIERA PIEGATA (JLCPCB Sheet Metal)
#  -------------------------------------------------------------------
#  Layout: frontale VERTICALE, scocca COMPATTA.
#    - lettore CD slim in basso (dietro la fessura frontale)
#    - mini PC su un RIPIANO sopra il CD (impilati)
#    - schermo Waveshare 7" (C) sul frontale, in alto
#    - retro: doppia USB-A a vite, jack DC, RJ45
#
#  Pezzi (tutti lamiera Alluminio 5052, 2 mm):
#    body  - profilo a U (fondo + 2 fianchi + 2 risvolti)
#    lid   - coperchio
#    front - frontale (vaschetta) con finestra schermo + fessura CD
#    back  - retro (vaschetta) con porte
#    shelf - ripiano interno per il mini PC
#
#  Eseguire: FreeCADCmd.exe streamer_sheetmetal.py
#  Unitá: millimetri.
# =====================================================================
import os
import FreeCAD as App
import Part

V = App.Vector
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

# ======================= PARAMETRI ==================================
t   = 2.0
ri  = 2.0
ro  = ri + t
lip = 16.0
fl  = 18.0
relief = 2.0          # >= t : cava di sfogo piega a norma DFM (storico)
air = 6.0
lip_w = 12.0          # risvolto superiore dei fianchi: il coperchio ci si avvita (vite Z)
bracket_edge = 10.0   # rientro dei fori squadretta dai bordi laterali di front/back
lid_drop = 12.0       # (storico) non piu' usato: coperchio ora PIATTO, fissato su front/back

# Schermo Waveshare 7" (C)
screen_w, screen_h = 164.9, 124.27
view_w, view_h     = 154.21, 85.92
view_offy          = 0.0        # area attiva centrata sui fori (regolabile +/-5 mm)
screen_gap         = 6.6        # spazio display<->scheda (dato misurato)

# Lettore CD slim (fessura/cassetto frontale)
cd_w, cd_d, cd_h = 137.2, 137.2, 15.0
cd_slot_w, cd_slot_h = cd_w + 4, cd_h + 3
cd_feet = 0.0                   # CD appoggiato sul fondo (fissato con biadesivo)

# Mini PC BMAX N100
pc_w, pc_d, pc_h = 120.0, 120.0, 32.0     # da sito (modello corretto)

text_band  = 16.0    # spazio serigrafia tra fessura e schermo
top_margin = 8.0

clear_d = 3.4
tap_d   = 2.6

# CD e mini PC: fissati con biadesivo (nessun foro)
# Schermo: interasse dei 4 fori di fissaggio
screen_mnt_dx, screen_mnt_dy = 152.1, 113.1
screen_hole_d = 5.5     # foro schermo maggiorato -> tolleranza +/-1mm (usa rondelle)

# Profondita' esterna totale richiesta (22 cm)
ext_depth = 220.0

# --- Connettori posteriori (dai datasheet reali) ---
# USB doppia USB-A impilata: 2 viti M3 ORIZZONTALI, interasse 28 mm
usb_cut_w, usb_cut_h = 14.0, 16.0   # apertura 2x USB-A impilate (VERIFICA)
usb_screw_dx, usb_screw_d = 28.0, 3.2
# RJ45 panel-mount: 2 viti M3 orizzontali, interasse 27.1 mm
rj45_cut_w, rj45_cut_h = 17.0, 15.0
rj45_screw_dx, rj45_screw_d = 27.1, 3.2
# Jack DC barrel panel-mount standard "DC-022" -> foro 8 mm
dc_hole_d = 8.0

# ======================= DIMENSIONI SCOCCA ==========================
W   = max(screen_w, cd_w, pc_w) + 2 * air + 2 * t
Dch = ext_depth - 2 * t
slot_z0   = t + 2
z_cd_c    = slot_z0 + cd_slot_h / 2
screen_z0 = slot_z0 + cd_slot_h + text_band
screen_cz = screen_z0 + screen_h / 2
window_cz = screen_cz + view_offy
H = screen_z0 + screen_h + top_margin + t

# ripiano mini PC
shelf_top = t + cd_feet + cd_h + 4          # sopra il CD
shelf_z = shelf_top                          # quota faccia inferiore ripiano
# ripiano SOLO davanti (copre il PC); dietro resta libero per i cavi
shelf_y0 = fl + 3
shelf_len = pc_d + 20
shelf_sy = [shelf_y0 + 25, shelf_y0 + shelf_len - 25]

# posizioni viti condivise
zs = [30.0, H / 2.0, H - 30.0]
xs = [30.0, W / 2.0, W - 30.0]
ys_lid = [25.0, Dch / 2.0, Dch - 25.0]
y_front = fl / 2.0
y_back = Dch - fl / 2.0
# fissaggi nuovi (front/back PIATTI + coperchio su risvolti)
bz = [zs[0], zs[2]]                                   # 2 livelli squadrette per lato
lid_xs = [t + lip_w / 2.0, W - t - lip_w / 2.0]       # assi viti coperchio (sui risvolti)
lid_ys = [25.0, Dch / 2.0, Dch - 25.0]

print("Esterno LxHxP ~ %.1f x %.1f x %.1f mm" % (W, H, Dch + 2 * t))
print("Fessura CD centro z = %.1f ; ripiano PC z = %.1f" % (z_cd_c, shelf_z))

# ======================= UTILITY ====================================
def box(L, Wd, Ht, pos=(0, 0, 0)):
    return Part.makeBox(L, Wd, Ht, V(*pos))

def cyl_x(d, h, x, y, z): return Part.makeCylinder(d / 2.0, h, V(x, y, z), V(1, 0, 0))
def cyl_y(d, h, x, y, z): return Part.makeCylinder(d / 2.0, h, V(x, y, z), V(0, 1, 0))
def cyl_z(d, h, x, y, z): return Part.makeCylinder(d / 2.0, h, V(x, y, z), V(0, 0, 1))

def try_fillet(shape, targets, radius):
    edges = []
    for e in shape.Edges:
        if len(e.Vertexes) != 2:
            continue
        p1, p2 = e.Vertexes[0].Point, e.Vertexes[1].Point
        d = p2.sub(p1)
        if abs(d.x) < 1e-6 and abs(d.z) < 1e-6 and abs(d.y) > 1e-6:
            mx, mz = (p1.x + p2.x) / 2.0, (p1.z + p2.z) / 2.0
            for (tx, tz) in targets:
                if abs(mx - tx) < 0.4 and abs(mz - tz) < 0.4:
                    edges.append(e)
    if not edges:
        return shape
    try:
        return shape.makeFillet(radius, edges)
    except Exception as ex:
        print("  fillet r=%.1f saltato: %s" % (radius, ex))
        return shape

# ======================= CORPO =====================================
def make_body():
    # U a 2 pieghe + RISVOLTO SUPERIORE su ciascun fianco (piega parallela alla base,
    # estremi liberi -> nessun angolo chiuso, nessuna saldatura: 4 pieghe tutte
    # formabili al press-brake). I risvolti reggono il coperchio (vite in Z).
    base  = box(W, Dch, t, (0, 0, 0))
    left  = box(t, Dch, H - t, (0, 0, 0))
    right = box(t, Dch, H - t, (W - t, 0, 0))
    s = base.fuse(left).fuse(right).removeSplitter()
    s = try_fillet(s, [(t, t), (W - t, t)], ri)
    s = try_fillet(s, [(0, 0), (W, 0)], ro)
    s = s.removeSplitter()
    # risvolti superiori interni (uno per fianco), su tutta la profondita'
    lipL = box(lip_w, Dch, t, (t,            0, H - 2 * t))
    lipR = box(lip_w, Dch, t, (W - t - lip_w, 0, H - 2 * t))
    s = s.fuse(lipL).fuse(lipR).removeSplitter()

    holes = []
    # fori squadrette front/back: clearance nei fianchi (vite in X verso la squadretta)
    for z in bz:
        for y in (y_front, y_back):
            holes.append(cyl_x(clear_d, t + 2, -1, y, z))
            holes.append(cyl_x(clear_d, t + 2, W - t - 1, y, z))
    # fori coperchio: tap sui risvolti superiori (vite in Z dal coperchio)
    for x in lid_xs:
        for y in lid_ys:
            holes.append(cyl_z(tap_d, t + 2, x, y, H - 2 * t - 1))
    # CD fissato con biadesivo: nessun foro sul fondo
    # fori per le alette del ripiano (sui fianchi) - passante in X
    for sy in shelf_sy:
        holes.append(cyl_x(clear_d, t + 2, -1, sy, shelf_z - 8))
        holes.append(cyl_x(clear_d, t + 2, W - t - 1, sy, shelf_z - 8))
    for h in holes:
        s = s.cut(h)
    return s

# ======================= COPERCHIO =================================
def make_lid():
    # COPERCHIO PIATTO: nessuna piega -> solo taglio laser, zero supplemento bending.
    # Si avvita (vite in Z) sui RISVOLTI superiori dei fianchi del corpo.
    s = box(W, Dch, t, (0, 0, H - t))
    cuts = []
    # ventilazione: 3 asole larghe (meno pierce/tempo laser, no supplemento feature sottili)
    for i in range(3):
        cuts.append(box(10, Dch * 0.4, t + 2, (W * 0.30 + i * 20, Dch * 0.30, H - t - 1)))
    # fissaggio ai risvolti superiori dei fianchi (vite in Z) - fori passanti
    for x in lid_xs:
        for y in lid_ys:
            cuts.append(cyl_z(clear_d, t + 2, x, y, H - t - 1))
    for c in cuts:
        s = s.cut(c)
    return s

# ======================= PANNELLO PIATTO ===========================
def flat_panel(sgn):
    # Pannello PIATTO: solo taglio laser, ZERO pieghe -> ZERO saldatura.
    # Fissato ai fianchi del corpo con squadrette ad L interne (vedi BOM):
    # una vite in Y entra dal pannello nella squadretta, una vite in X la lega al fianco.
    if sgn > 0:
        plate_y0, yscrew = -t, -t - 1       # front: pannello esterno davanti
    else:
        plate_y0, yscrew = Dch, Dch - 1     # back:  pannello esterno dietro
    s = box(W, t, H, (0, plate_y0, 0))
    holes = []
    for z in bz:
        for x in (bracket_edge, W - bracket_edge):
            holes.append(cyl_y(tap_d, t + 2, x, yscrew, z))
    for h in holes:
        s = s.cut(h)
    return s

def make_front():
    s = flat_panel(+1)
    cuts = [
        box(view_w, t + 2, view_h, (W / 2 - view_w / 2, -t - 1, window_cz - view_h / 2)),
        box(cd_slot_w, t + 2, cd_slot_h, (W / 2 - cd_slot_w / 2, -t - 1, z_cd_c - cd_slot_h / 2)),
    ]
    # fori fissaggio schermo attorno alla finestra (maggiorati per tolleranza)
    for sx in (W / 2 - screen_mnt_dx / 2, W / 2 + screen_mnt_dx / 2):
        for sz in (screen_cz - screen_mnt_dy / 2, screen_cz + screen_mnt_dy / 2):
            cuts.append(cyl_y(screen_hole_d, t + 2, sx, -t - 1, sz))
    for c in cuts:
        s = s.cut(c)
    return s

def make_back():
    s = flat_panel(-1)
    z = H / 2.0
    y0 = Dch - 1
    cx_usb, cx_dc, cx_rj = W * 0.28, W * 0.55, W * 0.78
    cuts = [
        # USB doppia (USB-A impilate) - viti orizzontali 28 mm
        box(usb_cut_w, t + 2, usb_cut_h, (cx_usb - usb_cut_w / 2, y0, z - usb_cut_h / 2)),
        cyl_y(usb_screw_d, t + 2, cx_usb - usb_screw_dx / 2, y0, z),
        cyl_y(usb_screw_d, t + 2, cx_usb + usb_screw_dx / 2, y0, z),
        # jack DC barrel (mini PC)
        cyl_y(dc_hole_d, t + 2, cx_dc, y0, z),
        # RJ45 - viti orizzontali 27.1 mm
        box(rj45_cut_w, t + 2, rj45_cut_h, (cx_rj - rj45_cut_w / 2, y0, z - rj45_cut_h / 2)),
        cyl_y(rj45_screw_d, t + 2, cx_rj - rj45_screw_dx / 2, y0, z),
        cyl_y(rj45_screw_d, t + 2, cx_rj + rj45_screw_dx / 2, y0, z),
    ]
    for c in cuts:
        s = s.cut(c)
    return s

# ======================= RIPIANO MINI PC ===========================
def make_shelf():
    # piano SOLO davanti (copre il PC) + alette laterali, UN SOLO solido
    drop = 12.0
    plate = box(W - 2 * t, shelf_len, t, (t, shelf_y0, shelf_z))             # piano tra i fianchi
    aL = box(t, shelf_len, drop + t, (t,         shelf_y0, shelf_z - drop))  # aletta sx (sovrapposta al piano)
    aR = box(t, shelf_len, drop + t, (W - 2 * t, shelf_y0, shelf_z - drop))  # aletta dx
    s = plate.fuse(aL).fuse(aR).removeSplitter()
    cuts = []
    # fori alette -> fianchi (vite in X) allineati al corpo
    for sy in shelf_sy:
        cuts.append(cyl_x(tap_d, t + 2, t - 1, sy, shelf_z - 8))
        cuts.append(cyl_x(tap_d, t + 2, W - 2 * t - 1, sy, shelf_z - 8))
    # mini PC fissato con biadesivo: nessun foro sul ripiano
    # PASSACAVI: apertura verso il retro per i cavi dal lettore CD (sotto) al PC (sopra)
    cab_w, cab_d = 90.0, 50.0
    cuts.append(box(cab_w, cab_d, t + 2,
                    (W / 2 - cab_w / 2, shelf_y0 + shelf_len - cab_d - 5, shelf_z - 1)))
    # ventilazione (nella meta' anteriore, sopra il PC): asole piu' larghe, meno tagli
    for i in range(3):
        cuts.append(box(8, shelf_len * 0.30, t + 2,
                        (W * 0.35 + i * 16, shelf_y0 + 8, shelf_z - 1)))
    for c in cuts:
        s = s.cut(c)
    return s

# ======================= EXPORT + CHECK ============================
def main():
    parts = {
        "body": make_body(), "lid": make_lid(),
        "front": make_front(), "back": make_back(), "shelf": make_shelf(),
    }
    print("--- check interferenze (mm^3) ---")
    names = list(parts)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = parts[names[i]], parts[names[j]]
            try:
                v = a.common(b).Volume
            except Exception:
                v = -1
            if v > 5:
                print("  %s/%s = %.1f" % (names[i], names[j], v))
    for name, shp in parts.items():
        shp.exportStep(os.path.join(OUT, "streamer-%s.step" % name))
        shp.exportStl(os.path.join(OUT, "streamer-%s.stl" % name))
    asm = Part.makeCompound(list(parts.values()))
    asm.exportStep(os.path.join(OUT, "streamer-assembly.step"))
    asm.exportStl(os.path.join(OUT, "streamer-assembly.stl"))
    print("OK export in", OUT)

main()
