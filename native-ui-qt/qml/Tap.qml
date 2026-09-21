// Touch feedback, in the two shapes of the Electron UI: the hover /
// transition-colors tint (150 ms) and the whileTap scale (a spring). It goes
// inside the control, filling it; `grow` widens the touch area past the
// drawing.
// 🚨 Inside a list this is not the one to use but RowTap.qml, which drops
// `held` as soon as the gesture turns into a scroll.
import QtQuick
import Hifi
import Hifi.Ui

MouseArea {
    id: ma
    property real tap: 1.0            // scale at full press (0.9, 0.95...)
    property int  grow: 0
    // Who is holding the finger down. Normally `pressed`; RowTap drops it when
    // the finger starts to scroll, so the box fades away instead of staying
    // lit under a moving list.
    property bool held: pressed
    // The tint on mouse-over too: it goes off inside the lists.
    property bool hoverTint: true
    // 0..1: how "pressed" it is for the tint (mouse-over included)
    readonly property real press: held || (hoverEnabled && hoverTint && containsMouse) ? 1 : 0
    property real pressAnim: press
    // the current scale, to use in the drawing's `scale`. With the movement
    // turned off there is no scale at all: a 2 % jump with no travel is only
    // a defect.
    readonly property real tapScale: Theme.motionRate > 0 ? 1 + (tap - 1) * sp.value : 1
    anchors.fill: parent
    anchors.margins: -grow
    hoverEnabled: Sys.pointerEnabled
    Behavior on pressAnim { NumberAnimation { duration: Theme.dur(Theme.tTap); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
    // 🚨 `to` is a binding now, no longer an onPressedChanged: RowTap changes
    // `held` even when `pressed` does not (the finger starts scrolling).
    Spring { id: sp; stiffness: 550; damping: 30; rate: Theme.motionRate; to: ma.held ? 1 : 0 }
    // tint between rest and pressed
    function mix(rest, pressedColor) { return Theme.mix(rest, pressedColor, pressAnim) }
}
