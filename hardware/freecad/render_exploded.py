# =====================================================================
#  Render exploded view ANNOTATO (PNG) dai 5 STL -> out/preview-exploded.png
#  Mostra squadrette a L + assi viti per front/back e viti coperchio.
#  Standalone: numpy-stl + matplotlib (niente FreeCAD GUI).
#  Eseguire: python render_exploded.py
# =====================================================================
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from stl import mesh as stlmesh

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

t = 2.0
lip_w = 12.0
bracket_edge = 10.0
EXP = 150.0   # distanza di esplosione

PARTS = {
    "body":  (np.array([0.,   0.,   0.]), "#9fb6c9"),
    "lid":   (np.array([0.,   0., EXP]),  "#c9b27a"),
    "shelf": (np.array([0.,   0.,  60.]), "#b7c98f"),
    "front": (np.array([0., -EXP,  0.]),  "#d68f8f"),
    "back":  (np.array([0.,  EXP,  0.]),  "#8fb0d6"),
}

def seg(ax, p0, p1, **kw):
    ax.plot([p0[0], p1[0]], [p0[1], p1[1]], [p0[2], p1[2]], **kw)

def main():
    fig = plt.figure(figsize=(11, 9), dpi=130)
    ax = fig.add_subplot(111, projection="3d")
    meshes, allpts = {}, []
    for name, (off, color) in PARTS.items():
        m = stlmesh.Mesh.from_file(os.path.join(OUT, "streamer-%s.stl" % name))
        tris = m.vectors + off
        meshes[name] = (m, off)
        allpts.append(tris.reshape(-1, 3))
        coll = Poly3DCollection(tris, alpha=0.92)
        coll.set_facecolor(color)
        coll.set_edgecolor((0, 0, 0, 0.10))
        coll.set_linewidth(0.12)
        ax.add_collection3d(coll)

    # dimensioni reali dai mesh
    W = meshes["front"][0].vectors[..., 0].max()
    H = meshes["front"][0].vectors[..., 2].max()
    Dch = meshes["body"][0].vectors[..., 1].max()
    bz = [30.0, H - 30.0]
    xw = {"L": t, "R": W - t}          # faccia interna fianco
    xh = {"L": bracket_edge, "R": W - bracket_edge}  # foro vite sul pannello

    # ---- squadrette + viti front/back -------------------------------
    def draw_panel_fix(y_face, y_off, col):
        for side in ("L", "R"):
            for z in bz:
                corner = np.array([xw[side], y_face, z])
                pan_hole = np.array([xh[side], y_face, z])
                # squadretta (L): ala su pannello + ala su fianco
                seg(ax, corner, pan_hole, color="#333", lw=2.2)
                seg(ax, corner, corner + np.array([0, np.sign(0.5 - (y_off < 0)) * 0, 0]),
                    color="#333", lw=0.1)
                leg_dir = 14.0 if y_face < Dch / 2 else -14.0
                seg(ax, corner, corner + np.array([0, leg_dir, 0]), color="#333", lw=2.2)
                # vite Y: dal pannello esploso fino alla squadretta
                seg(ax, pan_hole + np.array([0, y_off, 0]), pan_hole,
                    color=col, lw=1.3, ls=(0, (4, 3)))
                ax.scatter(*(pan_hole + np.array([0, y_off, 0])), color=col, s=14)
                # vite X: dalla squadretta dentro il fianco
                xdir = -10.0 if side == "L" else 10.0
                seg(ax, corner, corner + np.array([xdir, leg_dir * 0.6, 0]),
                    color=col, lw=1.3, ls=(0, (4, 3)))

    draw_panel_fix(0.0, -EXP, "#b03030")     # front  (vite verso +Y)
    draw_panel_fix(Dch, EXP, "#2f5fa0")      # back   (vite verso -Y)

    # ---- viti coperchio sui risvolti --------------------------------
    lid_xs = [t + lip_w / 2.0, W - t - lip_w / 2.0]
    lid_ys = [25.0, Dch / 2.0, Dch - 25.0]
    for x in lid_xs:
        for y in lid_ys:
            top = np.array([x, y, H])
            seg(ax, top + np.array([0, 0, EXP]), top,
                color="#9a7b1e", lw=1.3, ls=(0, (4, 3)))
            ax.scatter(*(top + np.array([0, 0, EXP])), color="#9a7b1e", s=14)
            ax.scatter(*top, color="#9a7b1e", s=10, marker="x")

    # ---- etichette pezzi (fuori sagoma) -----------------------------
    lbl = [
        (W / 2, Dch / 2, H + EXP + 28, "lid  (piatto)\nvite Z sui risvolti"),
        (W / 2, -EXP - 30, H * 0.45, "front (piatto)\n4 viti Y -> squadrette"),
        (W / 2, Dch + EXP + 30, H * 0.6, "back (piatto)\n4 viti Y -> squadrette"),
        (-40, Dch / 2, H * 0.5, "body\nU + 2 risvolti"),
        (W + 30, Dch * 0.35, 70, "shelf"),
    ]
    for x, y, z, s in lbl:
        ax.text(x, y, z, s, fontsize=8.5, color="#111", ha="center",
                va="center", weight="bold")

    # legenda
    ax.text2D(0.02, 0.13,
              "--- vite Y front -> squadretta\n"
              "--- vite Y back  -> squadretta\n"
              "--- vite Z lid   -> risvolto\n"
              "linea nera = squadretta a L (8x)",
              transform=ax.transAxes, fontsize=8, color="#222",
              family="monospace",
              bbox=dict(boxstyle="round", fc="white", ec="#999", alpha=0.9))

    pts = np.vstack(allpts)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    ctr = (lo + hi) / 2.0
    span = (hi - lo).max() / 2.0 * 1.08
    ax.set_xlim(ctr[0] - span, ctr[0] + span)
    ax.set_ylim(ctr[1] - span, ctr[1] + span)
    ax.set_zlim(ctr[2] - span, ctr[2] + span)
    ax.set_box_aspect((1, 1, 1))
    ax.view_init(elev=20, azim=-62)
    ax.set_axis_off()
    ax.set_title("Network Streamer - exploded: fissaggi front/back (squadrette) e lid",
                 fontsize=12, weight="bold")
    fig.tight_layout()
    dst = os.path.join(OUT, "preview-exploded.png")
    fig.savefig(dst, dpi=130, bbox_inches="tight")
    print("OK", dst, "| W=%.1f H=%.1f Dch=%.1f" % (W, H, Dch))

main()
