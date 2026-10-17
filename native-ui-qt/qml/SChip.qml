// What a place is used for (library, shared, playlists, CD rip), as a small
// pill: gold when the place plays that role, grey otherwise.
import QtQuick
import Hifi
import Hifi.Ui

Rectangle {
    id: c
    property string glyph
    property string label
    property bool on: true
    height: 24; radius: 12
    width: row.implicitWidth + 16
    color: on ? Theme.goldA(0.14) : "transparent"
    border.width: 1; border.color: on ? Theme.goldA(0.45) : Theme.wa(0.12)
    Row {
        id: row
        x: 8; anchors.verticalCenter: parent.verticalCenter; spacing: 5
        Icon { anchors.verticalCenter: parent.verticalCenter; name: c.glyph; size: 12; color: c.on ? Theme.gold : Theme.silverA(0.55) }
        Text { anchors.verticalCenter: parent.verticalCenter; text: c.label; color: c.on ? Theme.gold : Theme.silverA(0.55); font.family: Theme.font; font.pixelSize: 11 }
    }
}
