// A button of the album and artist pages: icon and optional label, gold for
// the main action (Play), dark for the others; an icon-only one is round.
import QtQuick
import Hifi.Ui

Rectangle {
    id: root
    property string icon: ""
    property bool filled: false
    property string label: ""
    property bool primary: false
    property bool dim: false
    signal clicked()
    readonly property bool round: label === ""
    width: round ? 38 : Math.max(38, row.implicitWidth + 28); height: 38; radius: 19
    color: primary ? tap.mix(Theme.gold, Theme.mix(Theme.gold, Theme.white, 0.25)) : tap.mix(Theme.surface, Theme.light)
    border.width: primary ? 0 : 1; border.color: Theme.border
    opacity: dim ? 0.4 : 1
    scale: tap.tapScale
    Row {
        id: row
        anchors.centerIn: parent; spacing: 8
        Icon { visible: root.icon !== ""; anchors.verticalCenter: parent.verticalCenter; name: root.icon; filled: root.filled; size: 15; color: root.primary ? Theme.black : Theme.gold }
        Text {
            visible: !root.round; anchors.verticalCenter: parent.verticalCenter
            text: root.label; color: root.primary ? Theme.black : Theme.white
            font.family: Theme.font; font.pixelSize: 13; font.bold: root.primary
        }
    }
    Tap { id: tap; tap: 0.95; enabled: !root.dim; onClicked: root.clicked() }
}
