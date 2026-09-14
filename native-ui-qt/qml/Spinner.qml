// La rotellina di Tailwind animate-spin: anello oro con un quarto trasparente,
// un giro al secondo. Gira solo mentre e' visibile.
import QtQuick
import QtQuick.Shapes
import Hifi.Ui

Item {
    id: root
    property real radius: 18
    property real thickness: 4
    property color color: Theme.gold
    // 🚨 le animazioni girano anche negli elementi nascosti dagli antenati:
    // chi mette la rotellina in un sottoalbero che si nasconde deve legare
    // `active` alla condizione vera, se no la scena si ridisegna a 60 fps
    // per sempre (misurato: 21 % di CPU a riposo sul Dell)
    property bool active: true
    width: radius * 2; height: radius * 2
    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: root.color; strokeWidth: root.thickness; fillColor: "transparent"
            capStyle: ShapePath.FlatCap
            PathAngleArc { centerX: root.radius; centerY: root.radius; radiusX: root.radius - root.thickness / 2; radiusY: root.radius - root.thickness / 2; startAngle: 0; sweepAngle: 270 }
        }
        RotationAnimation on rotation { from: 0; to: 360; duration: 1000; loops: Animation.Infinite; running: root.visible && root.active }
    }
}
