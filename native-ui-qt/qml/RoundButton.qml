// Pulsante tondo dell'intestazione (ui_round_button): fondo bianco/10 che
// va a bianco/20 al tocco, icona centrata.
import QtQuick
import Hifi.Ui

Item {
    id: root
    property string icon
    property real iconSize: 18
    property color bg: Theme.wa(0.10)
    property color bgPress: Theme.wa(0.20)
    property color fg: Theme.white
    property int grow: 0
    signal clicked()
    width: 38; height: 38
    Rectangle {
        anchors.fill: parent
        radius: width / 2
        color: tap.mix(root.bg, root.bgPress)
    }
    Icon { anchors.centerIn: parent; name: root.icon; size: root.iconSize; color: root.fg }
    Tap { id: tap; grow: root.grow; onClicked: root.clicked() }
}
