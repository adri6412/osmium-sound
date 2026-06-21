# =====================================================================
#  Scocca Network Streamer HiFi - LEGNO/MDF LASER CUT
#  -------------------------------------------------------------------
#  6 pezzi piatti (spessore 5mm) con giunzioni incollate (lati/retro)
#  e viti (coperchio/frontale). DXF pronti per laser cut.
#
#  Componenti interni: lettore CD slim, mini PC, schermo Waveshare 7"
#  Montaggio: frontale con viti + incastri, coperchio con viti
#
#  Eseguire: FreeCADCmd.exe streamer_wood_lasercut.py
#  Unitá: millimetri.
# =====================================================================
import os
import FreeCAD as App
import Part
from Part import Face, Wire, Edge
import Draft

V = App.Vector
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

# ======================= PARAMETRI ==================================
t   = 5.0              # spessore MDF (5mm)
slot_depth = t / 2.0   # profondità incastri (metà spessore)
slot_w = 12.0          # larghezza incastri

# Schermo Waveshare 7" (C)
screen_w, screen_h = 164.9, 124.27
view_w, view_h     = 154.21, 85.92
view_offy          = 0.0
screen_gap         = 6.6
screen_mnt_dx, screen_mnt_dy = 152.1, 113.1
screen_hole_d = 5.5

# Lettore CD slim
cd_w, cd_d, cd_h = 137.2, 137.2, 15.0
cd_slot_w, cd_slot_h = cd_w + 4, cd_h + 3
cd_feet = 0.0

# Mini PC BMAX N100
pc_w, pc_d, pc_h = 120.0, 120.0, 32.0

text_band  = 16.0
top_margin = 8.0

# Connettori posteriori
usb_cut_w, usb_cut_h = 14.0, 16.0
usb_screw_dx = 28.0
rj45_cut_w, rj45_cut_h = 17.0, 15.0
rj45_screw_dx = 27.1
dc_hole_d = 8.0

air = 6.0
ext_depth = 220.0

# ======================= DIMENSIONI SCOCCA ==========================
W   = max(screen_w, cd_w, pc_w) + 2 * air + 2 * t
Dch = ext_depth - 2 * t
slot_z0   = t + 2
z_cd_c    = slot_z0 + cd_slot_h / 2
screen_z0 = slot_z0 + cd_slot_h + text_band
screen_cz = screen_z0 + screen_h / 2
window_cz = screen_cz + view_offy
H = screen_z0 + screen_h + top_margin + t

# Ripiano mini PC
shelf_top = t + cd_feet + cd_h + 4
shelf_z = shelf_top
shelf_y0 = 18.0 + 3
shelf_len = pc_d + 20
shelf_sy = [shelf_y0 + 25, shelf_y0 + shelf_len - 25]

# Posizioni viti (shared)
zs = [30.0, H / 2.0, H - 30.0]
xs = [30.0, W / 2.0, W - 30.0]
ys_lid = [25.0, Dch / 2.0, Dch - 25.0]

screw_d = 3.2

print("=== LASER CUT WOOD VERSION ===")
print("Esterno LxHxP ~ %.1f x %.1f x %.1f mm" % (W, H, Dch + 2 * t))
print("Fessura CD centro z = %.1f ; ripiano PC z = %.1f" % (z_cd_c, shelf_z))

# ======================= UTILITY ====================================
def box(L, Wd, Ht, pos=(0, 0, 0)):
    return Part.makeBox(L, Wd, Ht, V(*pos))

def cyl_z(d, h, x, y, z):
    return Part.makeCylinder(d / 2.0, h, V(x, y, z), V(0, 0, 1))

def cyl_x(d, h, x, y, z):
    return Part.makeCylinder(d / 2.0, h, V(x, y, z), V(1, 0, 0))

def cyl_y(d, h, x, y, z):
    return Part.makeCylinder(d / 2.0, h, V(x, y, z), V(0, 1, 0))

def make_rect_face(width, depth, pos=(0, 0)):
    """Crea rettangolo 2D per DXF export"""
    x0, y0 = pos
    pts = [V(x0, y0), V(x0 + width, y0), V(x0 + width, y0 + depth), V(x0, y0 + depth), V(x0, y0)]
    wire = Part.makePolygon(pts)
    return wire

def add_slot(shape, x, y, width, depth, slot_depth):
    """Sottrae uno slot (incastro) da una forma 2D"""
    try:
        slot_box = box(width, depth, t + 2, (x, y, -1))
        return shape.cut(slot_box)
    except Exception as e:
        print(f"    WARNING: slot fallito at ({x},{y}): {e}")
        return shape

# ======================= PEZZI LASER CUT ============================

def make_bottom():
    """Fondo: rettangolo W x Dch con incastri sui 4 lati"""
    s = box(W, Dch, t, (0, 0, 0))

    # Incastri per fianchi SX (x=0)
    for y in [30, Dch/2, Dch - 30]:
        s = add_slot(s, -0.5, y - slot_w/2, slot_depth + 1, slot_w, slot_depth)

    # Incastri per fianchi DX (x=W-t)
    for y in [30, Dch/2, Dch - 30]:
        s = add_slot(s, W - slot_depth - 0.5, y - slot_w/2, slot_depth + 1, slot_w, slot_depth)

    # Incastri per frontale (y=0)
    for x in [30, W/2, W - 30]:
        s = add_slot(s, x - slot_w/2, -0.5, slot_w, slot_depth + 1, slot_depth)

    # Incastri per posteriore (y=Dch-t)
    for x in [30, W/2, W - 30]:
        s = add_slot(s, x - slot_w/2, Dch - slot_depth - 0.5, slot_w, slot_depth + 1, slot_depth)

    return s

def make_side_left():
    """Fianco sinistro: altezza H, profondità Dch-t"""
    s = box(t, Dch - t, H, (0, 0, 0))

    # Incastri con fondo
    for x in [30, W/2, W - 30]:
        s = add_slot(s, -0.5, x - slot_w/2 - t, slot_depth + 1, slot_w, slot_depth)

    # Incastri con coperchio (alto)
    for x in [30, W/2, W - 30]:
        s = add_slot(s, -0.5, x - slot_w/2 - t, slot_depth + 1, slot_w, slot_depth)

    # Fori per viti coperchio (M3, passanti)
    for z in ys_lid:
        s = s.cut(cyl_y(screw_d, t + 2, -1, z, H - t - 15))

    # Fori per viti frontale (M3, passanti)
    for z in zs:
        s = s.cut(cyl_y(screw_d, t + 2, -1, 18, z))
        s = s.cut(cyl_y(screw_d, t + 2, -1, Dch - 18, z))

    return s

def make_side_right():
    """Fianco destro: simmetrico al sinistro"""
    s = box(t, Dch - t, H, (0, 0, 0))

    # Incastri con fondo
    for x in [30, W/2, W - 30]:
        s = add_slot(s, -0.5, x - slot_w/2 - t, slot_depth + 1, slot_w, slot_depth)

    # Incastri con coperchio (alto)
    for x in [30, W/2, W - 30]:
        s = add_slot(s, -0.5, x - slot_w/2 - t, slot_depth + 1, slot_w, slot_depth)

    # Fori per viti coperchio
    for z in ys_lid:
        s = s.cut(cyl_y(screw_d, t + 2, -1, z, H - t - 15))

    # Fori per viti frontale
    for z in zs:
        s = s.cut(cyl_y(screw_d, t + 2, -1, 18, z))
        s = s.cut(cyl_y(screw_d, t + 2, -1, Dch - 18, z))

    return s

def make_front():
    """Pannello frontale: finestra schermo + fessura CD + fori viti"""
    s = box(W, t, H, (0, 0, 0))

    # Finestra schermo
    s = s.cut(box(view_w, t + 2, view_h,
                  (W/2 - view_w/2, -t-1, window_cz - view_h/2)))

    # Fessura CD (slot orizzontale)
    s = s.cut(box(cd_slot_w, t + 2, cd_slot_h,
                  (W/2 - cd_slot_w/2, -t-1, z_cd_c - cd_slot_h/2)))

    # Fori fissaggio schermo (rondelle 5.5mm per tolleranza)
    for sx in (W/2 - screen_mnt_dx/2, W/2 + screen_mnt_dx/2):
        for sz in (screen_cz - screen_mnt_dy/2, screen_cz + screen_mnt_dy/2):
            s = s.cut(cyl_x(screen_hole_d, t + 2, sx, -t-1, sz))

    # Fori viti sui fianchi (M3)
    for z in zs:
        s = s.cut(cyl_z(screw_d, t + 2, 30, -1, z))
        s = s.cut(cyl_z(screw_d, t + 2, W - 30, -1, z))
        s = s.cut(cyl_z(screw_d, t + 2, W/2, -1, z))

    # Incastri sui fianchi
    for z in [30, H/2, H - 30]:
        s = add_slot(s, -0.5, -0.5, slot_depth + 1, slot_w, slot_depth)  # SX basso

    return s

def make_back():
    """Pannello posteriore: aperture connettori + fori viti"""
    s = box(W, t, H, (0, 0, 0))

    z = H / 2.0
    y0 = -1

    # USB doppia
    cx_usb = W * 0.28
    s = s.cut(box(usb_cut_w, t + 2, usb_cut_h,
                  (cx_usb - usb_cut_w/2, y0, z - usb_cut_h/2)))
    s = s.cut(cyl_x(screw_d, t + 2, cx_usb - usb_screw_dx/2, y0, z))
    s = s.cut(cyl_x(screw_d, t + 2, cx_usb + usb_screw_dx/2, y0, z))

    # Jack DC
    cx_dc = W * 0.55
    s = s.cut(cyl_x(dc_hole_d, t + 2, cx_dc, y0, z))

    # RJ45
    cx_rj = W * 0.78
    s = s.cut(box(rj45_cut_w, t + 2, rj45_cut_h,
                  (cx_rj - rj45_cut_w/2, y0, z - rj45_cut_h/2)))
    s = s.cut(cyl_x(screw_d, t + 2, cx_rj - rj45_screw_dx/2, y0, z))
    s = s.cut(cyl_x(screw_d, t + 2, cx_rj + rj45_screw_dx/2, y0, z))

    # Fori viti sui fianchi
    for z in zs:
        s = s.cut(cyl_z(screw_d, t + 2, 30, -1, z))
        s = s.cut(cyl_z(screw_d, t + 2, W - 30, -1, z))
        s = s.cut(cyl_z(screw_d, t + 2, W/2, -1, z))

    return s

def make_lid():
    """Coperchio: rettangolo W x Dch con fori viti"""
    s = box(W, Dch - t, t, (0, 0, 0))

    # Fori per viti (filettati o con inserti) verso i fianchi
    for y in ys_lid:
        s = s.cut(cyl_z(screw_d, t + 2, t + 5, y, -1))      # SX
        s = s.cut(cyl_z(screw_d, t + 2, W - t - 5, y, -1))  # DX

    # Ventilazione: 3 asole (incisioni 1mm)
    for i in range(3):
        s = s.cut(box(10, Dch * 0.4, 1, (W * 0.30 + i * 20, Dch * 0.30, -0.5)))

    # Incastri con fondo
    for x in [30, W/2, W - 30]:
        s = add_slot(s, x - slot_w/2, -0.5, slot_w, slot_depth + 1, slot_depth)

    return s

def make_shelf():
    """Ripiano interno: piano + alette laterali"""
    plate = box(W - 2*t, shelf_len, t, (t, shelf_y0, 0))
    drop = 12.0
    aL = box(t, shelf_len, drop, (t,     shelf_y0, -drop))
    aR = box(t, shelf_len, drop, (W-2*t, shelf_y0, -drop))
    s = plate.fuse(aL).fuse(aR).removeSplitter()

    # Fori per incastri verticali sui fianchi
    for sy in shelf_sy:
        s = s.cut(cyl_x(screw_d, t + 2, -1, sy, -8))
        s = s.cut(cyl_x(screw_d, t + 2, W - t - 1, sy, -8))

    # Passacavi
    cab_w, cab_d = 90.0, 50.0
    s = s.cut(box(cab_w, cab_d, t + 2,
                  (W/2 - cab_w/2, shelf_y0 + shelf_len - cab_d - 5, -1)))

    # Ventilazione
    for i in range(3):
        s = s.cut(box(8, shelf_len * 0.30, 1,
                      (W * 0.35 + i * 16, shelf_y0 + 8, -0.5)))

    return s

# ======================= EXPORT ==================================
def main():
    print("\n--- Creazione pezzi ---")
    parts = {}

    piece_funcs = {
        "bottom":      make_bottom,
        "side_left":   make_side_left,
        "side_right":  make_side_right,
        "front":       make_front,
        "back":        make_back,
        "lid":         make_lid,
        "shelf":       make_shelf,
    }

    for name, func in piece_funcs.items():
        try:
            print(f"  {name}...", end=" ")
            shp = func()
            parts[name] = shp
            print("OK")
        except Exception as e:
            print(f"ERRORE: {e}")
            import traceback
            traceback.print_exc()
            continue

    print("\n--- Esportazione STEP + STL ---")
    for name, shp in parts.items():
        try:
            step_file = os.path.join(OUT, f"wood-{name}.step")
            stl_file  = os.path.join(OUT, f"wood-{name}.stl")
            shp.exportStep(step_file)
            shp.exportStl(stl_file)
            print(f"  {name}: OK")
        except Exception as e:
            print(f"  {name}: ERRORE EXPORT - {e}")

    if parts:
        try:
            asm = Part.makeCompound(list(parts.values()))
            asm.exportStep(os.path.join(OUT, "wood-assembly.step"))
            print("\n✓ Assembly esportato")
        except Exception as e:
            print(f"Assembly fallito: {e}")

    print(f"\n[OK] Export completato in {OUT}")

main()
