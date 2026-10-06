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
//
// 🚨 `color` NON si anima: ogni tinta intermedia e' un SVG nuovo scritto e
// riletto sul thread della UI (con Tap.mix erano ~18 per tocco). Il colore al
// tocco si da' con `pressColor` + `press` (0..1, di solito tap.pressAnim): due
// strati gia' tinti, quello premuto sopra con opacita' `press` — per colori
// pieni e' esattamente la mescolanza di Theme.mix, e costa un'opacita'.
import QtQuick
import QtQuick.VectorImage

Item {
    id: root
    property string name
    property color color: "#ffffff"
    property real size: 20
    property bool filled: false
    // il colore a tocco pieno (meglio se pieno, senza trasparenza) e quanto
    // e' premuto; press 0 = il secondo strato non c'e' nemmeno
    property color pressColor: color
    property real press: 0
    width: size
    height: size
    readonly property string file: name ? name + (filled ? "-fill" : "") : ""
    VectorImage {
        anchors.fill: parent
        source: root.file ? Sys.tintedIcon(root.file, root.color) : ""
        preferredRendererType: VectorImage.CurveRenderer
        fillMode: VectorImage.PreserveAspectFit
    }
    // creato al primo tocco e poi tenuto: un'icona mai toccata non paga nulla
    property bool pressUsed: false
    onPressChanged: if (press > 0) pressUsed = true
    Loader {
        anchors.fill: parent
        active: root.pressUsed && root.file !== ""
        visible: root.press > 0
        opacity: root.press
        sourceComponent: VectorImage {
            source: Sys.tintedIcon(root.file, root.pressColor)
            preferredRendererType: VectorImage.CurveRenderer
            fillMode: VectorImage.PreserveAspectFit
        }
    }
}
