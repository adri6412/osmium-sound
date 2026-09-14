// Feedback al tocco, nelle due forme della UI Electron: la tinta di hover /
// transition-colors (150 ms) e la scala whileTap (molla). Si mette dentro il
// controllo, riempiendolo; `grow` allarga l'area sensibile oltre il disegno.
import QtQuick
import Hifi
import Hifi.Ui

MouseArea {
    id: ma
    property real tap: 1.0            // scala a fondo corsa (0.9, 0.95...)
    property int  grow: 0
    // 0..1: quanto e' "premuto" per la tinta (anche al passaggio del mouse)
    readonly property real press: pressed || (hoverEnabled && containsMouse) ? 1 : 0
    property real pressAnim: press
    // scala corrente, da usare in `scale` del disegno
    readonly property real tapScale: 1 + (tap - 1) * sp.value
    anchors.fill: parent
    anchors.margins: -grow
    hoverEnabled: Sys.pointerEnabled
    Behavior on pressAnim { NumberAnimation { duration: 150; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
    Spring { id: sp; stiffness: 550; damping: 30 }
    onPressedChanged: sp.to = pressed ? 1 : 0
    // tinta fra riposo e premuto
    function mix(rest, pressedColor) { return Theme.mix(rest, pressedColor, pressAnim) }
}
