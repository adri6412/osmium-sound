// The content's scrollbar (content-scrollbar: 3 px, #333). It shows itself
// while the content moves and fades after a moment of quiet: when it is
// needed it says where one is, when it is not it does not clutter the page.
import QtQuick
import Hifi.Ui

Rectangle {
    id: root
    property Flickable flick
    readonly property bool can: flick && flick.contentHeight > flick.height
    property bool shown: false
    // with the movement off it stays as it was: always there while
    // there is something to scroll
    opacity: (shown || Theme.motionRate === 0) ? 1 : 0
    visible: can && opacity > 0.01
    Behavior on opacity { NumberAnimation { duration: Theme.dur(Theme.tPanel) } }
    x: flick.width - 3; width: 3; radius: 2; color: "#333333"
    height: flick ? Math.max(20, flick.height * flick.height / Math.max(1, flick.contentHeight)) : 0
    y: flick ? (flick.height - height) * Math.max(0, Math.min(1, flick.contentY / Math.max(1, flick.contentHeight - flick.height))) : 0

    function bump() { if (!root.can) return; root.shown = true; hideT.restart() }
    // 🚨 one shot, re-armed on every movement: no `repeat`, and it only starts
    // once something has moved — at rest nothing is running
    Timer { id: hideT; interval: 800; onTriggered: root.shown = false }
    Connections { target: root.flick; function onContentYChanged() { root.bump() } }
    // the first time there is something to scroll it shows itself: it is the
    // only sign that there is more below
    onCanChanged: if (can) bump()
}
