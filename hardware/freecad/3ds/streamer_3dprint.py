# =====================================================================
#  Scocca Network Streamer HiFi - VERSIONE STAMPA 3D (FDM)
#  -------------------------------------------------------------------
#  Riadattamento del progetto in lamiera (../streamer_sheetmetal.py)
#  per la stampa 3D. La lamiera prende rigidita' dalle PIEGHE, che in
#  plastica non esistono: qui la scocca e' una SCATOLA a 6 pannelli
#  piatti imbullonati + ripiano interno.
#
#  Differenze chiave rispetto alla lamiera:
#    - pareti spesse (wt = 3 mm) invece di 2 mm piegati
#    - giunzioni con INSERTI FILETTATI M3 A CALDO (heat-set) nei
#      montanti d'angolo, NON autofilettanti su lamiera
#    - montanti d'angolo (post) integrati nei fianchi = ossatura
#    - ogni pezzo e' un pannello piatto -> stampa facile sul piano
#
#  Le MISURE FUNZIONALI sono identiche al progetto lamiera:
#    finestra schermo, 4 fori schermo (interasse 152.1 x 113.1),
#    fessura CD, fori connettori posteriori, quota ripiano mini PC.
#  Cambiano solo spessori e sistema di fissaggio.
#
#  Eseguire: FreeCADCmd.exe streamer_3dprint.py
#  Unita': millimetri.
# =====================================================================
import os
import FreeCAD as App
import Part

V = App.Vector
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

# ===================== PARAMETRI STAMPA 3D ==========================
wt      = 3.0     # spessore pareti (FDM): rigido e robusto
post    = 12.0    # lato dei montanti d'angolo (ospitano gli inserti)
ins_d   = 4.0     # foro per inserto M3 a caldo (knurled). Tipico 4.0-4.6:
                  #   PLA/PETG 4.0, ABS 4.2. Regola qui se l'inserto e' diverso.
ins_dep = 7.0     # profondita' foro inserto
clr_d   = 3.4     # foro passante vite M3
screen_hole_d = 5.5   # fori schermo maggiorati (come lamiera, +/-1mm tolleranza)

# ===================== COMPONENTI (invariati) =======================
# Schermo Waveshare 7" (C)
screen_w, screen_h = 164.9, 124.27
view_w, view_h     = 154.21, 85.92
view_offy          = 0.0
# Lettore CD slim
cd_w, cd_d, cd_h = 137.2, 137.2, 15.0
cd_slot_w, cd_slot_h = cd_w + 4, cd_h + 3      # 141.2 x 18
# Mini PC BMAX N100
pc_w, pc_d, pc_h = 120.0, 120.0, 32.0
# margini interni (come lamiera)
air        = 6.0
text_band  = 16.0
top_margin = 8.0
ext_depth  = 220.0

# Interasse fori schermo
screen_mnt_dx, screen_mnt_dy = 152.1, 113.1

# Connettori posteriori (dai datasheet reali)
usb_cut_w, usb_cut_h = 14.0, 16.0
usb_screw_dx, usb_screw_d = 28.0, 3.2
rj45_cut_w, rj45_cut_h = 17.0, 15.0
rj45_screw_dx, rj45_screw_d = 27.1, 3.2
dc_hole_d = 8.0

# ===================== CAVITA' INTERNA ==============================
# Identica al volume utile della versione lamiera (W-2t, Dch, H-2t).
Wi = max(screen_w, cd_w, pc_w) + 2 * air            # 176.9  (larghezza interna)
Di = ext_depth - 2 * 2.0                            # 216.0  (profondita' interna)

# quote verticali (frame cavita': z=0 = faccia interna del fondo)
slot_z0   = 2.0
z_cd_c    = slot_z0 + cd_slot_h / 2.0               # 11.0
screen_z0 = slot_z0 + cd_slot_h + text_band         # 36.0
screen_cz = screen_z0 + screen_h / 2.0              # 98.135
window_cz = screen_cz + view_offy
Hi = screen_z0 + screen_h + top_margin              # 168.27 (altezza interna)

# Esterno totale (con pareti da wt)
Wext, Hext, Dext = Wi + 2 * wt, Hi + 2 * wt, Di + 2 * wt

# Ripiano mini PC (stessa quota della lamiera)
shelf_z   = (2.0 + cd_h + 4.0) - 2.0                # 19.0  (faccia superiore appoggio)
shelf_y0  = 21.0
shelf_len = pc_d + 20.0                             # 140.0
shelf_x0, shelf_x1 = 0.0, Wi
shelf_sy  = [shelf_y0 + 25.0, shelf_y0 + shelf_len - 25.0]   # [46, 136]

# centri montanti d'angolo (nella cavita')
cx = Wi / 2.0
post_xc = [post / 2.0, Wi - post / 2.0]            # [6, 170.9]
post_yc = [post / 2.0, Di - post / 2.0]            # [6, 210]
zc_back = Hi / 2.0

print("Esterno LxHxP ~ %.1f x %.1f x %.1f mm" % (Wext, Hext, Dext))
print("Cavita' interna %.1f x %.1f x %.1f mm" % (Wi, Di, Hi))
print("Fessura CD z=%.1f ; schermo cz=%.1f ; ripiano z=%.1f" % (z_cd_c, screen_cz, shelf_z))

# ===================== UTILITY ======================================
def box(L, Wd, Ht, pos=(0, 0, 0)):
    return Part.makeBox(L, Wd, Ht, V(*pos))

def cyl_x(d, h, x, y, z): return Part.makeCylinder(d / 2.0, h, V(x, y, z), V(1, 0, 0))
def cyl_y(d, h, x, y, z): return Part.makeCylinder(d / 2.0, h, V(x, y, z), V(0, 1, 0))
def cyl_z(d, h, x, y, z): return Part.makeCylinder(d / 2.0, h, V(x, y, z), V(0, 0, 1))

# ===================== MONTANTE D'ANGOLO ============================
def corner_post(xc_, yc_):
    """Montante quadrato full-height con inserti: fondo(+Z), top(-Z),
    e un inserto orizzontale verso il pannello front o back piu' vicino."""
    x0 = xc_ - post / 2.0
    y0 = yc_ - post / 2.0
    s = box(post, post, Hi, (x0, y0, 0))
    # inserti verticali (fondo e coperchio)
    s = s.cut(cyl_z(ins_d, ins_dep, xc_, yc_, 0))
    s = s.cut(cyl_z(ins_d, ins_dep, xc_, yc_, Hi - ins_dep))
    # inserti orizzontali per il pannello front/back vicino (2 quote)
    if yc_ < Di / 2.0:        # montante anteriore -> inserto verso y- (front)
        for z in (35.0, Hi - 35.0):
            s = s.cut(cyl_y(ins_d, ins_dep, xc_, 0.0, z))
    else:                     # montante posteriore -> inserto verso y+ (back)
        for z in (35.0, Hi - 35.0):
            s = s.cut(cyl_y(ins_d, ins_dep, xc_, Di - ins_dep, z))
    return s

# ===================== FIANCHI (con montanti + appoggi ripiano) =====
def make_side(left):
    if left:
        wall = box(wt, Di + 2 * wt, Hi, (-wt, -wt, 0))
        xc_ = post_xc[0]
        ledge_x0 = 0.0
    else:
        wall = box(wt, Di + 2 * wt, Hi, (Wi, -wt, 0))
        xc_ = post_xc[1]
        ledge_x0 = Wi - 16.0
    s = wall
    # 2 montanti (anteriore e posteriore) su questo fianco
    for yc_ in post_yc:
        s = s.fuse(corner_post(xc_, yc_))
    # appoggi ripiano: 2 blocchi con inserto verticale (vite dall'alto)
    for sy in shelf_sy:
        led = box(16.0, 18.0, 8.0, (ledge_x0, sy - 9.0, shelf_z - 8.0))
        s = s.fuse(led)
    s = s.removeSplitter()
    # fori inserto appoggi ripiano (dall'alto, faccia a z=shelf_z)
    lcx = ledge_x0 + 8.0
    for sy in shelf_sy:
        s = s.cut(cyl_z(ins_d, ins_dep, lcx, sy, shelf_z - ins_dep))
    return s

# ===================== FONDO ========================================
def make_bottom():
    s = box(Wext, Dext, wt, (-wt, -wt, -wt))
    # fori passanti verso i 4 montanti (vite dal basso)
    for x in post_xc:
        for y in post_yc:
            s = s.cut(cyl_z(clr_d, wt + 2, x, y, -wt - 1))
    return s

# ===================== COPERCHIO ====================================
def make_lid():
    s = box(Wext, Dext, wt, (-wt, -wt, Hi))
    cuts = []
    # feritoie di ventilazione (sopra il PC)
    for i in range(7):
        cuts.append(box(5, Di * 0.4, wt + 2, (Wi * 0.30 + i * 12, Di * 0.30, Hi - 1)))
    # fori passanti verso i 4 montanti (vite dall'alto)
    for x in post_xc:
        for y in post_yc:
            cuts.append(cyl_z(clr_d, wt + 2, x, y, Hi - 1))
    for c in cuts:
        s = s.cut(c)
    return s

# ===================== FRONTALE =====================================
def make_front():
    s = box(Wi, wt, Hi, (0, -wt, 0))
    cuts = [
        box(view_w, wt + 2, view_h, (cx - view_w / 2, -wt - 1, window_cz - view_h / 2)),
        box(cd_slot_w, wt + 2, cd_slot_h, (cx - cd_slot_w / 2, -wt - 1, z_cd_c - cd_slot_h / 2)),
    ]
    # 4 fori fissaggio schermo (maggiorati, usa rondelle)
    for sx in (cx - screen_mnt_dx / 2, cx + screen_mnt_dx / 2):
        for sz in (screen_cz - screen_mnt_dy / 2, screen_cz + screen_mnt_dy / 2):
            cuts.append(cyl_y(screen_hole_d, wt + 2, sx, -wt - 1, sz))
    # fori passanti verso i montanti anteriori (vite orizzontale)
    for x in post_xc:
        for z in (35.0, Hi - 35.0):
            cuts.append(cyl_y(clr_d, wt + 2, x, -wt - 1, z))
    for c in cuts:
        s = s.cut(c)
    return s

# ===================== RETRO ========================================
def make_back():
    s = box(Wi, wt, Hi, (0, Di, 0))
    z = zc_back
    y0 = Di - 1
    cx_usb, cx_dc, cx_rj = Wi * 0.28, Wi * 0.55, Wi * 0.78
    cuts = [
        box(usb_cut_w, wt + 2, usb_cut_h, (cx_usb - usb_cut_w / 2, y0, z - usb_cut_h / 2)),
        cyl_y(usb_screw_d, wt + 2, cx_usb - usb_screw_dx / 2, y0, z),
        cyl_y(usb_screw_d, wt + 2, cx_usb + usb_screw_dx / 2, y0, z),
        cyl_y(dc_hole_d, wt + 2, cx_dc, y0, z),
        box(rj45_cut_w, wt + 2, rj45_cut_h, (cx_rj - rj45_cut_w / 2, y0, z - rj45_cut_h / 2)),
        cyl_y(rj45_screw_d, wt + 2, cx_rj - rj45_screw_dx / 2, y0, z),
        cyl_y(rj45_screw_d, wt + 2, cx_rj + rj45_screw_dx / 2, y0, z),
    ]
    # fori passanti verso i montanti posteriori (vite orizzontale)
    for x in post_xc:
        for zz in (35.0, Hi - 35.0):
            cuts.append(cyl_y(clr_d, wt + 2, x, y0, zz))
    for c in cuts:
        s = s.cut(c)
    return s

# ===================== RIPIANO MINI PC ==============================
def make_shelf():
    s = box(Wi, shelf_len, wt, (0, shelf_y0, shelf_z))
    cuts = []
    # fori vite verso gli appoggi dei fianchi (vite dall'alto)
    for sy in shelf_sy:
        cuts.append(cyl_z(clr_d, wt + 2, 8.0, sy, shelf_z - 1))
        cuts.append(cyl_z(clr_d, wt + 2, Wi - 8.0, sy, shelf_z - 1))
    # passacavi verso il retro (cavi dal CD sotto al PC sopra)
    cab_w, cab_d = 90.0, 50.0
    cuts.append(box(cab_w, cab_d, wt + 2,
                    (cx - cab_w / 2, shelf_y0 + shelf_len - cab_d - 5, shelf_z - 1)))
    # ventilazione (meta' anteriore, sopra il PC)
    for i in range(5):
        cuts.append(box(4, shelf_len * 0.30, wt + 2,
                        (Wi * 0.35 + i * 12, shelf_y0 + 8, shelf_z - 1)))
    for c in cuts:
        s = s.cut(c)
    return s

# ===================== EXPORT + CHECK ===============================
def main():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    parts = {
        "body-bottom": make_bottom(),
        "lid":         make_lid(),
        "side-left":   make_side(True),
        "side-right":  make_side(False),
        "front":       make_front(),
        "back":        make_back(),
        "shelf":       make_shelf(),
    }
    print("--- check solidi ---")
    for name, shp in parts.items():
        print("  %-12s vol=%.0f mm^3  valido=%s" % (name, shp.Volume, shp.isValid()))
    print("--- check interferenze (mm^3) ---")
    names = list(parts)
    bad = False
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            try:
                v = parts[names[i]].common(parts[names[j]]).Volume
            except Exception:
                v = -1
            if v > 5:
                print("  INTERFERENZA %s/%s = %.1f" % (names[i], names[j], v))
                bad = True
    if not bad:
        print("  nessuna interferenza")
    for name, shp in parts.items():
        shp.exportStep(os.path.join(OUT, "streamer3d-%s.step" % name))
        shp.exportStl(os.path.join(OUT, "streamer3d-%s.stl" % name))
    asm = Part.makeCompound(list(parts.values()))
    asm.exportStep(os.path.join(OUT, "streamer3d-assembly.step"))
    asm.exportStl(os.path.join(OUT, "streamer3d-assembly.stl"))
    print("OK export in", OUT)

main()
