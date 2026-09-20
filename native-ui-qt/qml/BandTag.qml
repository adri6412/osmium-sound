// Etichetta della banda accanto al nome di una rete Wi-Fi ("2.4 GHz", "5 GHz").
// Compare solo quando lo stesso nome e' trasmesso su piu' bande: e' l'unica
// cosa che distingue due righe altrimenti identiche. L'unita' non si traduce,
// si scrive cosi' sull'etichetta di qualsiasi router.
import QtQuick
import Hifi.Ui

Rectangle {
    id: root
    property string band: ""
    property bool on: false
    visible: band !== ""
    width: visible ? label.implicitWidth + 12 : 0
    height: 18
    radius: 4
    color: "transparent"
    border.width: 1
    border.color: root.on ? Theme.goldA(0.45) : Theme.wa(0.15)
    Text {
        id: label
        anchors.centerIn: parent
        text: root.band + " GHz"
        color: root.on ? Theme.goldA(0.9) : Theme.silverA(0.7)
        font.family: Theme.font; font.pixelSize: 10
    }
}
