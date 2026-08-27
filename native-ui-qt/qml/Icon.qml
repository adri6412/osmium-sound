// Un'icona lucide, quella vera in SVG (stessa versione di Electron), tinta
// del colore voluto. VectorImage la trasforma in geometria per la scheda
// video: resta nitida a qualunque risoluzione.
import QtQuick
import QtQuick.Effects
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
        id: img
        anchors.fill: parent
        source: root.name ? "../icons/" + root.name + (root.filled ? "-fill" : "") + ".svg" : ""
        preferredRendererType: VectorImage.CurveRenderer
        fillMode: VectorImage.PreserveAspectFit
        visible: false
    }
    MultiEffect {
        anchors.fill: parent
        source: img
        colorization: 1.0
        colorizationColor: root.color
        opacity: root.color.a
    }
}
