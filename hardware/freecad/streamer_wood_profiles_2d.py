# =====================================================================
#  Scocca Network Streamer - PROFILI 2D PER LASER CUT
#  Genera direttamente i disegni 2D (senza dimensione Z)
#  Con tutti i contorni: esterno + fori + aperture
#
#  Eseguire: FreeCADCmd.exe streamer_wood_profiles_2d.py
# =====================================================================
import os
import FreeCAD as App
import Part
from FreeCAD import Vector as V

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

# ======================= PARAMETRI ==================================
t   = 5.0              # spessore MDF
W   = 186.9            # larghezza totale
H   = 178.3            # altezza totale
Dch = 210.0            # profondità totale (Dch - t)

# Schermo
screen_mnt_dx, screen_mnt_dy = 152.1, 113.1
screen_cz = 89.15 + 0.0  # centro schermo in Z
view_w, view_h = 154.21, 85.92
screen_hole_d = 5.5

# CD
z_cd_c = 16.0
cd_slot_w, cd_slot_h = 141.2, 18.0

# Connettori posteriori
usb_cut_w, usb_cut_h = 14.0, 16.0
usb_screw_dx, usb_screw_d = 28.0, 3.2
rj45_cut_w, rj45_cut_h = 17.0, 15.0
rj45_screw_dx, rj45_screw_d = 27.1, 3.2
dc_hole_d = 8.0

screw_d = 3.2

# ======================= UTILITY ====================================
def rect_wire(x, y, w, h):
    """Crea un rettangolo come wire 2D"""
    pts = [V(x, y, 0), V(x+w, y, 0), V(x+w, y+h, 0), V(x, y+h, 0), V(x, y, 0)]
    return Part.makePolygon(pts)

def circle_edge(cx, cy, r):
    """Crea un cerchio come edge 2D"""
    circle = Part.Circle(V(cx, cy, 0), V(0, 0, 1), r)
    return Part.Edge(circle)

def make_profile_2d(outer_rect, holes_edges):
    """Combina rettangolo esterno + fori come profilo 2D"""
    all_edges = list(outer_rect.Edges)
    all_edges.extend(holes_edges)
    return Part.makeCompound(all_edges)

# ======================= PROFILI 2D ==================================

def profile_bottom():
    """Fondo: rettangolo W x Dch, nessun foro"""
    return rect_wire(0, 0, W, Dch)

def profile_side_left():
    """Fianco sinistro: rettangolo Dch x H, fori per front + back + coperchio + ripiano"""
    outer = rect_wire(0, 0, Dch, H)
    holes = []

    # Fori front (incollato): nessuno

    # Fori back (avvitato): 2 posizioni dietro a SX e DX
    back_y = Dch - 5.0  # Dietro
    holes.append(circle_edge(back_y, 30.0, screw_d/2))     # Basso
    holes.append(circle_edge(back_y, H - 30.0, screw_d/2)) # Alto

    # Fori coperchio: 3 posizioni lungo profondità (Y), in alto
    lid_height = H - 15.0
    for y in [25.0, Dch/2, Dch - 25.0]:
        holes.append(circle_edge(y, lid_height, screw_d/2))

    # Fori ripiano: 2 posizioni SIMMETRICHE al CENTRO del pannello (sia X che Y)
    shelf_center_x = Dch / 2.0  # 105mm profondità
    shelf_offset = 35.0  # distanza dal centro
    shelf_center_z = H / 2.0  # 89mm altezza (CENTRO VERTICALE)
    for y in [shelf_center_x - shelf_offset, shelf_center_x + shelf_offset]:  # [70, 140]
        holes.append(circle_edge(y, shelf_center_z, screw_d/2))

    return make_profile_2d(outer, holes)

def profile_side_right():
    """Fianco destro: simmetrico al sinistro"""
    return profile_side_left()

def profile_front():
    """Pannello frontale: rettangolo W x H con finestra schermo + fessura CD SOLO"""
    outer = rect_wire(0, 0, W, H)
    holes = []

    # Finestra schermo (rettangolare)
    screen_y0 = H/2 - view_h/2
    screen_aperture = Part.Face([
        rect_wire(W/2 - view_w/2, screen_y0, view_w, view_h)
    ])

    # Fessura CD (rettangolare)
    cd_y0 = z_cd_c - cd_slot_h/2
    cd_aperture = Part.Face([
        rect_wire(W/2 - cd_slot_w/2, cd_y0, cd_slot_w, cd_slot_h)
    ])

    # Fori schermo (4 angoli per montaggio)
    for sx in (W/2 - screen_mnt_dx/2, W/2 + screen_mnt_dx/2):
        for sz in (screen_cz - screen_mnt_dy/2, screen_cz + screen_mnt_dy/2):
            holes.append(circle_edge(sx, sz, screen_hole_d/2))

    # Aggiungi contorno della finestra schermo
    all_edges = list(outer.Edges)
    for edge in rect_wire(W/2 - view_w/2, screen_y0, view_w, view_h).Edges:
        all_edges.append(edge)

    # Aggiungi contorno fessura CD
    for edge in rect_wire(W/2 - cd_slot_w/2, cd_y0, cd_slot_w, cd_slot_h).Edges:
        all_edges.append(edge)

    all_edges.extend(holes)
    return Part.makeCompound(all_edges)

def profile_back():
    """Pannello posteriore: rettangolo W x H con aperture connettori SOLO"""
    outer = rect_wire(0, 0, W, H)
    holes = []

    z = H / 2.0

    # USB apertura (rettangolare)
    cx_usb = W * 0.28
    usb_rect = rect_wire(cx_usb - usb_cut_w/2, z - usb_cut_h/2, usb_cut_w, usb_cut_h)

    # RJ45 apertura (rettangolare)
    cx_rj = W * 0.78
    rj_rect = rect_wire(cx_rj - rj45_cut_w/2, z - rj45_cut_h/2, rj45_cut_w, rj45_cut_h)

    # DC jack (cerchio)
    cx_dc = W * 0.55
    holes.append(circle_edge(cx_dc, z, dc_hole_d/2))

    # Fori viti connettori (USB + RJ45)
    holes.append(circle_edge(cx_usb - usb_screw_dx/2, z, usb_screw_d/2))
    holes.append(circle_edge(cx_usb + usb_screw_dx/2, z, usb_screw_d/2))
    holes.append(circle_edge(cx_rj - rj45_screw_dx/2, z, rj45_screw_d/2))
    holes.append(circle_edge(cx_rj + rj45_screw_dx/2, z, rj45_screw_d/2))

    # Fori viti fissaggio ai fianchi (SX e DX) - AVVITATO
    holes.append(circle_edge(5, 30.0, screw_d/2))        # SX basso
    holes.append(circle_edge(5, H - 30.0, screw_d/2))    # SX alto
    holes.append(circle_edge(W - 5, 30.0, screw_d/2))    # DX basso
    holes.append(circle_edge(W - 5, H - 30.0, screw_d/2))  # DX alto

    all_edges = list(outer.Edges)
    all_edges.extend(usb_rect.Edges)
    all_edges.extend(rj_rect.Edges)
    all_edges.extend(holes)

    return Part.makeCompound(all_edges)

def profile_lid():
    """Coperchio: rettangolo W x Dch con fori viti + ventilazione"""
    outer = rect_wire(0, 0, W, Dch - t)
    holes = []

    # Fori viti (M3)
    for y in [25.0, Dch/2, Dch - 25.0]:
        holes.append(circle_edge(t + 5.0, y, screw_d/2))        # SX
        holes.append(circle_edge(W - t - 5.0, y, screw_d/2))    # DX

    # Ventilazione: 3 asole rettangolari
    vent_rects = []
    for i in range(3):
        vent_x = W * 0.30 + i * 20
        vent_rects.append(rect_wire(vent_x, Dch * 0.30, 10, Dch * 0.4))

    all_edges = list(outer.Edges)
    for vent in vent_rects:
        all_edges.extend(vent.Edges)
    all_edges.extend(holes)

    return Part.makeCompound(all_edges)

def profile_shelf():
    """Ripiano: rettangolo con alette laterali, fori, passacavi"""
    shelf_y0 = 21.0
    shelf_len = 140.0

    # Piano principale
    plate = rect_wire(t, shelf_y0, W - 2*t, shelf_len)

    # Alette laterali
    drop = 12.0
    left_flap = rect_wire(t, shelf_y0, t, shelf_len)
    right_flap = rect_wire(W - 2*t, shelf_y0, t, shelf_len)

    holes = []

    # Fori fianchi
    shelf_sy = [shelf_y0 + 25, shelf_y0 + shelf_len - 25]
    for sy in shelf_sy:
        holes.append(circle_edge(t + t/2, sy, screw_d/2))
        holes.append(circle_edge(W - t - t/2, sy, screw_d/2))

    # Passacavi (rettangolare)
    cab_w, cab_d = 90.0, 50.0
    passacavi = rect_wire(
        W/2 - cab_w/2,
        shelf_y0 + shelf_len - cab_d - 5,
        cab_w,
        cab_d
    )

    # Ventilazione (3 asole)
    vents = []
    for i in range(3):
        vents.append(rect_wire(
            W * 0.35 + i * 16,
            shelf_y0 + 8,
            8,
            shelf_len * 0.30
        ))

    all_edges = list(plate.Edges)
    all_edges.extend(left_flap.Edges)
    all_edges.extend(right_flap.Edges)
    all_edges.extend(passacavi.Edges)
    for vent in vents:
        all_edges.extend(vent.Edges)
    all_edges.extend(holes)

    return Part.makeCompound(all_edges)

# ======================= EXPORT ==================================
def main():
    print("\n=== Generazione Profili 2D per Laser Cut ===\n")

    profiles = {
        "bottom":      profile_bottom,
        "side_left":   profile_side_left,
        "side_right":  profile_side_right,
        "front":       profile_front,
        "back":        profile_back,
        "lid":         profile_lid,
        "shelf":       profile_shelf,
    }

    doc = App.newDocument("laser_profiles")
    success = 0

    for name, func in profiles.items():
        try:
            print(f"  {name:15s}: ", end="")
            prof = func()

            # Aggiungi al documento
            feat = doc.addObject("Part::Feature", f"prof_{name}")
            feat.Shape = prof
            doc.recompute()

            # Esporta DXF
            dxf_path = os.path.join(OUT, f"laser-{name}.dxf")
            import importDXF
            importDXF.export([feat], dxf_path)

            print("OK")
            success += 1

        except Exception as e:
            print(f"ERRORE - {e}")
            import traceback
            traceback.print_exc()

    print(f"\n[DONE] {success}/{len(profiles)} DXF generati in {OUT}")
    print("\nPronti per laser cut!")

main()
