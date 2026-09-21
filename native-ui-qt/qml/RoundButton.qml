// Pulsante tondo dell'intestazione (ui_round_button): fondo bianco/10 che
// va a bianco/20 al tocco, icona centrata.
import QtQuick
import Hifi.Ui

Item {
    id: root
    property string icon
    property bool filled: false
    property real iconSize: 18
    property color bg: Theme.wa(0.10)
    property color bgPress: Theme.wa(0.20)
    property color fg: Theme.white
    property int grow: 0
    // 🚨 The scale is not a flourish: on several of these (VU meters,
    // animations, player picker, sleep timer) `bg` and `bgPress` are the same
    // colour once they are on, and without it a press did not show at all.
    property real tap: 0.92
    signal clicked()
    width: 38; height: 38
    Rectangle {
        anchors.fill: parent
        radius: width / 2
        color: tapArea.mix(root.bg, root.bgPress)
        scale: tapArea.tapScale
    }
    Icon { anchors.centerIn: parent; name: root.icon; filled: root.filled; size: root.iconSize; color: root.fg; scale: tapArea.tapScale }
    Tap { id: tapArea; tap: root.tap; grow: root.grow; onClicked: root.clicked() }
}
