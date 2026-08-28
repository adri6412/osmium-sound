// Un'icona lucide, quella vera in SVG (stessa versione di Electron), tinta
// del colore voluto e disegnata come VETTORE direttamente in pixel veri.
//
// 🚨 Niente texture intermedia, niente effetto. Prima l'icona passava da
// VectorImage -> layer (texture) -> MultiEffect (tintura) -> schermo: a 720p
// la tela e' scalata 1,2 e 60 icone su 74 finiscono a misure NON intere
// (16 -> 19,2 px, 18 -> 21,6, 24 -> 28,8...), quindi la texture veniva
// ricampionata con uno sfasamento frazionario — mezzo pixel di sfocatura su
// tratti spessi 2,4 px, visibile. Chromium disegna il tracciato SVG in pixel
// veri, senza passaggi: cosi' fa ora anche questa. In piu': niente memoria
// video per le texture e niente passata di effetto.
// La tintura la fa Sys.tintedIcon (SVG con il colore gia' dentro, in cache).
import QtQuick
import QtQuick.VectorImage

Item {
    id: root
    property string name
    property color color: "#ffffff"
    property real size: 20
    property bool filled: false
    width: size
    height: size
    VectorImage {
        anchors.fill: parent
        source: root.name ? Sys.tintedIcon(root.name + (root.filled ? "-fill" : ""), root.color) : ""
        preferredRendererType: VectorImage.CurveRenderer
        fillMode: VectorImage.PreserveAspectFit
    }
}
