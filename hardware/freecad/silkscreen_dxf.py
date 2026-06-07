# =====================================================================
#  Serigrafia frontale -> DXF (contorni del testo) per JLCPCB Silk Screen.
#  Eseguire: FreeCADCmd.exe silkscreen_dxf.py
# =====================================================================
import os
import FreeCAD as App
import Part
import importDXF

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
TEXT = "HIFI STREAMER"
FONT = "C:/Windows/Fonts/arialbd.ttf"   # Arial Bold
SIZE = 8.0                               # altezza caratteri (mm)
TRACK = 1.0                              # spaziatura extra tra lettere

def main():
    doc = App.newDocument("silk")
    try:
        import Draft
        ss = Draft.make_shapestring(String=TEXT, FontFile=FONT, Size=SIZE, Tracking=TRACK)
        doc.recompute()
        shp = ss.Shape.copy()
        doc.removeObject(ss.Name)
    except Exception as ex:
        print("Draft.make_shapestring fallito:", ex)
        # fallback: contorni via Part.makeWireString
        wires = Part.makeWireString(TEXT, FONT, SIZE, TRACK)
        edges = []
        for letter in wires:
            for w in letter:
                edges += w.Edges
        shp = Part.makeCompound(edges)

    # centra il testo attorno all'origine
    bb = shp.BoundBox
    shp.translate(App.Vector(-(bb.XMin + bb.XLength / 2.0),
                             -(bb.YMin + bb.YLength / 2.0), 0))
    o = doc.addObject("Part::Feature", "silk")
    o.Shape = shp
    doc.recompute()
    out = os.path.join(OUT, "silkscreen-front.dxf")
    importDXF.export([o], out)
    print("OK ->", out, "  size testo: %.1f x %.1f mm" % (bb.XLength, bb.YLength))

main()
