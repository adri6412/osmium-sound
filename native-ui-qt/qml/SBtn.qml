// A button of the Music sources pages: gold when it is the step forward,
// dark otherwise, red for what takes something away. `small` for the ones
// inside a card or a row.
import QtQuick
import Hifi
import Hifi.Ui

Rectangle {
    id: b
    signal clicked()
    property string label
    property string glyph: ""
    property bool lead: false
    property bool danger: false
    property bool small: false
    property bool on: true              // false: drawn faded, does nothing
    height: small ? 32 : 42; radius: small ? 8 : 10
    width: row.implicitWidth + (small ? 22 : 32)
    color: lead ? tap.mix(Theme.gold, "#ca8a04") : danger ? tap.mix(Theme.redA(0.16), Theme.redA(0.28)) : tap.mix(Theme.light, Theme.accent)
    opacity: on ? 1 : 0.4
    Row {
        id: row
        anchors.centerIn: parent; spacing: 7
        Icon { visible: !!b.glyph; anchors.verticalCenter: parent.verticalCenter; name: b.glyph; size: b.small ? 13 : 15; color: b.lead ? Theme.black : b.danger ? Theme.red300 : Theme.white }
        Text { anchors.verticalCenter: parent.verticalCenter; text: b.label; color: b.lead ? Theme.black : b.danger ? Theme.red300 : Theme.white; font.family: Theme.font; font.pixelSize: b.small ? 12 : 14; font.bold: b.lead }
    }
    Tap { id: tap; enabled: b.on; grow: b.small ? 4 : 0; onClicked: b.clicked() }
}
