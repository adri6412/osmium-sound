// Heading of a block on the album and artist pages, like the ones in Discover.
import QtQuick
import Hifi.Ui

Item {
    property string text: ""
    width: parent ? parent.width : 0; height: 34
    Text {
        anchors.bottom: parent.bottom; anchors.bottomMargin: 8
        width: parent.width; elide: Text.ElideRight
        text: parent.text.toUpperCase(); color: Theme.silverA(0.6)
        font.family: Theme.font; font.pixelSize: 12; font.bold: true; font.letterSpacing: 0.6
    }
}
