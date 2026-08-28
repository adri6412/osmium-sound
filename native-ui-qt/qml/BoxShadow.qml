// `box-shadow: offsetX offsetY blur spread color` di CSS per un rettangolo
// (anche con angoli tondi): un 9-patch pre-sfocato da Sys.boxShadow, stirato
// da BorderImage. Si mette PRIMA dell'elemento nello stesso genitore e si
// passa la geometria dell'elemento (targetX/Y/W/H).
import QtQuick

BorderImage {
    id: root
    property real radius: 12
    property real blur: 20
    property real spread: 0
    property real offsetX: 0
    property real offsetY: 4
    property color color: Qt.rgba(0, 0, 0, 0.5)
    property real targetX: 0
    property real targetY: 0
    property real targetW: 0
    property real targetH: 0
    readonly property int margin: Math.ceil(blur * 1.5) + 1
    readonly property int corner: Math.ceil(Math.max(0, radius + spread)) + margin
    source: Sys.boxShadow(radius, blur, spread, color)
    x: targetX - margin + offsetX
    y: targetY - margin + offsetY
    width: targetW + 2 * margin
    height: targetH + 2 * margin
    border { left: root.corner; right: root.corner; top: root.corner; bottom: root.corner }
    horizontalTileMode: BorderImage.Stretch
    verticalTileMode: BorderImage.Stretch
    smooth: true
}
