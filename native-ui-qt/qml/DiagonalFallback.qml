// `bg-gradient-to-br from-hifi-gray to-hifi-dark`: il riquadro di ripiego
// delle copertine, con il gradiente in DIAGONALE (Rectangle sa fare solo
// verticale/orizzontale) e gli angoli tondi.
import QtQuick
import QtQuick.Shapes
import Hifi.Ui

Item {
    id: root
    property real radius: 12
    property color from: Theme.gray
    property color to: Theme.dark
    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeWidth: -1
            fillGradient: LinearGradient {
                x1: 0; y1: 0; x2: root.width; y2: root.height
                GradientStop { position: 0; color: root.from }
                GradientStop { position: 1; color: root.to }
            }
            startX: root.radius; startY: 0
            PathLine { x: root.width - root.radius; y: 0 }
            PathArc { x: root.width; y: root.radius; radiusX: root.radius; radiusY: root.radius }
            PathLine { x: root.width; y: root.height - root.radius }
            PathArc { x: root.width - root.radius; y: root.height; radiusX: root.radius; radiusY: root.radius }
            PathLine { x: root.radius; y: root.height }
            PathArc { x: 0; y: root.height - root.radius; radiusX: root.radius; radiusY: root.radius }
            PathLine { x: 0; y: root.radius }
            PathArc { x: root.radius; y: 0; radiusX: root.radius; radiusY: root.radius }
        }
    }
}
