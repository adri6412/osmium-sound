# =====================================================================
#  Render isolato di ogni singolo pezzo (PNG) dai 5 STL -> out/part-*.png
#  Stessa vista isometrica/stile di preview-exploded.png, un pezzo per
#  immagine (nessun altro pezzo visibile, nessuna esplosione).
#  Standalone: numpy-stl + matplotlib (niente FreeCAD GUI).
#  Eseguire: python render_parts.py
# =====================================================================
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from stl import mesh as stlmesh

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

PARTS = {
    "body":  ("#9fb6c9", (20, -62)),
    "lid":   ("#c9b27a", (80, -90)),
    "front": ("#d68f8f", (10, -88)),
    "back":  ("#8fb0d6", (10, -88)),
    "shelf": ("#b7c98f", (35, -50)),
}

def render_one(name, color_hex, view):
    m = stlmesh.Mesh.from_file(os.path.join(OUT, "streamer-%s.stl" % name))
    tris = m.vectors

    fig = plt.figure(figsize=(6, 5), dpi=150)
    ax = fig.add_subplot(111, projection="3d")

    # alpha=1.0 (colore pieno): con alpha<1 i tanti triangoli sovrapposti della
    # mesh STL (raccordi/pieghe) si sommano in trasparenza e sembrano ombre finte.
    coll = Poly3DCollection(tris, alpha=1.0)
    coll.set_facecolor(color_hex)
    coll.set_edgecolor((0, 0, 0, 0.15))
    coll.set_linewidth(0.12)
    ax.add_collection3d(coll)

    pts = tris.reshape(-1, 3)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    ctr = (lo + hi) / 2.0
    span = (hi - lo).max() / 2.0 * 1.15
    ax.set_xlim(ctr[0] - span, ctr[0] + span)
    ax.set_ylim(ctr[1] - span, ctr[1] + span)
    ax.set_zlim(ctr[2] - span, ctr[2] + span)
    ax.set_box_aspect((1, 1, 1))
    elev, azim = view
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()

    dims = (hi - lo)
    ax.set_title("%s  —  %.1f x %.1f x %.1f mm" % (name, dims[0], dims[1], dims[2]),
                 fontsize=10, weight="bold")

    fig.patch.set_facecolor("#fafaf8")
    fig.tight_layout()
    dst = os.path.join(OUT, "part-%s.png" % name)
    fig.savefig(dst, dpi=150, facecolor="#fafaf8", bbox_inches="tight")
    plt.close(fig)
    print("OK", dst)

def render_assembly():
    fig = plt.figure(figsize=(7, 6), dpi=150)
    ax = fig.add_subplot(111, projection="3d")
    allpts = []
    for name, (color, _view) in PARTS.items():
        m = stlmesh.Mesh.from_file(os.path.join(OUT, "streamer-%s.stl" % name))
        tris = m.vectors
        allpts.append(tris.reshape(-1, 3))
        coll = Poly3DCollection(tris, alpha=1.0)
        coll.set_facecolor(color)
        coll.set_edgecolor((0, 0, 0, 0.12))
        coll.set_linewidth(0.1)
        ax.add_collection3d(coll)
    pts = np.vstack(allpts)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    ctr = (lo + hi) / 2.0
    span = (hi - lo).max() / 2.0 * 1.1
    ax.set_xlim(ctr[0] - span, ctr[0] + span)
    ax.set_ylim(ctr[1] - span, ctr[1] + span)
    ax.set_zlim(ctr[2] - span, ctr[2] + span)
    ax.set_box_aspect((1, 1, 1))
    ax.view_init(elev=22, azim=-55)
    ax.set_axis_off()
    ax.set_title("Assieme completo (chiuso)", fontsize=11, weight="bold")
    fig.patch.set_facecolor("#fafaf8")
    fig.tight_layout()
    dst = os.path.join(OUT, "part-assembly.png")
    fig.savefig(dst, dpi=150, facecolor="#fafaf8", bbox_inches="tight")
    plt.close(fig)
    print("OK", dst)

def main():
    for name, (color, view) in PARTS.items():
        render_one(name, color, view)
    render_assembly()

main()
