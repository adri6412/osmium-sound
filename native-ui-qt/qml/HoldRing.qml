// The ring that fills while a row is held down: it says the long press is on
// its way, instead of leaving the finger in the dark until the menu appears.
// It neither spins nor blinks: whoever uses it moves `progress`, and the ring
// exists only while the finger is there (RowTap makes it with a Loader), so at
// rest there is nothing at all — the trap in Spinner.qml does not come back.
import QtQuick
import QtQuick.Shapes
import Hifi.Ui

Item {
    id: root
    property real progress: 0
    property real thickness: 2
    property color color: Theme.goldA(0.75)
    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: root.color; strokeWidth: root.thickness; fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc {
                centerX: root.width / 2; centerY: root.height / 2
                radiusX: root.width / 2 - root.thickness / 2
                radiusY: root.height / 2 - root.thickness / 2
                startAngle: -90; sweepAngle: 360 * Math.max(0, Math.min(1, root.progress))
            }
        }
    }
}
