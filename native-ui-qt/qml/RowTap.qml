// The Tap of the rows and cards inside a ListView / GridView / Flickable.
//
// 🚨 It NEVER touches the grab: `preventStealing` stays false, as issue #100
// demands (a child that keeps the grab on the first move takes the scrolling
// away from the Flickable for good, and setting it back to false afterwards
// does not help). Here it only watches: the moment the gesture turns out to
// be a scroll, `held` drops and the pressed box fades away by itself.
//
// 🚨 The recognition lives in a Connections and not in `onPressed:`: a
// delegate declaring its own `onPressed:` on the instance would replace the
// one written here, and the row would stay lit while scrolling.
import QtQuick
import Hifi
import Hifi.Ui

Tap {
    id: ma
    property Flickable flick: null     // the view that holds us (optional)
    property int  slop: 10             // points past which it is a scroll
    property bool holdRing: false      // the long-press ring
    property real pressX: 0
    property real pressY: 0
    property bool moved: false
    signal longPress(real x, real y)

    readonly property bool scrolling: !!flick && (flick.dragging || flick.flicking)
    held: pressed && !moved && !scrolling
    hoverTint: false                   // inside a list the mouse passing by does not tint
    pressAndHoldInterval: 500

    property real hold: 0              // 0..1, how full the ring is
    onHeldChanged: if (!held) { holdAnim.stop(); hold = 0 }

    Connections {
        target: ma
        function onPressed(m) { ma.moved = false; ma.pressX = m.x; ma.pressY = m.y }
        function onPositionChanged(m) {
            if (ma.moved) return
            if (Math.abs(m.x - ma.pressX) > ma.slop || Math.abs(m.y - ma.pressY) > ma.slop) ma.moved = true
        }
        // the ring has done its job: the menu is out, it goes
        function onPressAndHold(m) { if (!ma.held) return; holdAnim.stop(); ma.hold = 0; ma.longPress(m.x, m.y) }
    }

    // 🚨 A Timer waiting does not keep the drawing loop turning, a paused
    // animation does: the ring is born after 180 ms, so an ordinary touch
    // does not cost a single frame more. `running` follows `held`, so it
    // never stays on.
    Timer {
        id: holdDelay
        interval: 180
        running: ma.holdRing && ma.held && Theme.lushMotion
        onTriggered: holdAnim.start()
    }
    NumberAnimation {
        id: holdAnim
        target: ma; property: "hold"; from: 0; to: 1
        duration: Math.max(1, Theme.dur(ma.pressAndHoldInterval - holdDelay.interval))
    }
    // the ring stays inside the row: the delegate does not clip, and centred
    // on a finger at the edge it would spill onto the row next door
    Loader {
        active: ma.hold > 0.001
        width: 44; height: 44
        x: Math.max(0, Math.min(ma.width - width, ma.pressX - width / 2))
        y: Math.max(0, Math.min(ma.height - height, ma.pressY - height / 2))
        sourceComponent: HoldRing { progress: ma.hold }
    }
}
