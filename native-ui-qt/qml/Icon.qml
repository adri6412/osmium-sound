// Un'icona lucide, quella vera in SVG (stessa versione di Electron), tinta
// del colore voluto. VectorImage la trasforma in geometria per la scheda
// video: resta nitida a qualunque risoluzione.
import QtQuick
import QtQuick.Effects
import QtQuick.VectorImage
import Hifi.Ui

Item {
    id: root
    property string name
    property color color: "#ffffff"
    property real size: 20
    property bool filled: false
    width: size
    height: size
    VectorImage {
        id: img
        anchors.fill: parent
        source: root.name ? "../icons/" + root.name + (root.filled ? "-fill" : "") + ".svg" : ""
        preferredRendererType: VectorImage.CurveRenderer
        fillMode: VectorImage.PreserveAspectFit
        visible: false
        // 🚨 MultiEffect ha bisogno della sorgente come texture, e se non gliela
        // si misura la fa grande quanto l'icona in punti: a 4K veniva disegnata
        // 20x20 e poi ingrandita 3,6 volte — icone sgranate. La geometria del
        // VectorImage e' nitida a qualunque misura, e' il passaggio per
        // l'effetto (che serve a tingerla) a perdere la risoluzione.
        layer.enabled: true
        layer.smooth: true
        layer.textureSize: Qt.size(Math.ceil(root.size * Theme.dpr),
                                   Math.ceil(root.size * Theme.dpr))
    }
    MultiEffect {
        anchors.fill: parent
        source: img
        colorization: 1.0
        colorizationColor: root.color
        opacity: root.color.a
    }
}
