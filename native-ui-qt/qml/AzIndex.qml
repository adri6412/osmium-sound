// L'indice alfabetico laterale: 27 lettere, tocca o trascina per saltare.
import QtQuick
import Hifi.Ui

Item {
    id: root
    signal letter(string l)
    readonly property string az: "#ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    property bool down: false
    property string cur: ""
    property real ratio: 0
    Repeater {
        model: 27
        Text {
            required property int index
            readonly property string l: root.az.charAt(index)
            x: 16 - width / 2; y: 4 + index * (root.height - 8) / 26 - height / 2
            text: l
            color: root.down && root.cur === l ? Theme.gold : (Library.count, Library.hasLetter(l)) ? Theme.silverA(0.7) : Theme.silverA(0.2)
            font.family: Theme.font; font.pixelSize: 10; font.bold: true
        }
    }
    // shadow-lg della bolla (48 px): 0 10px 15px -3px + 0 4px 6px -4px, nero al 10 %
    BoxShadow { visible: root.down; targetX: -56; targetY: root.ratio * root.height - 24; targetW: 48; targetH: 48; radius: 24; blur: 15; spread: -3; offsetY: 10; color: Theme.blackA(0.1) }
    BoxShadow { visible: root.down; targetX: -56; targetY: root.ratio * root.height - 24; targetW: 48; targetH: 48; radius: 24; blur: 6; spread: -4; offsetY: 4; color: Theme.blackA(0.1) }
    Rectangle {                                    // la bolla con la lettera
        visible: root.down
        x: -8 - 48; y: root.ratio * root.height - 24; width: 48; height: 48; radius: 24; color: Theme.gold
        Text { anchors.centerIn: parent; text: root.cur; color: Theme.black; font.family: Theme.font; font.pixelSize: 20; font.bold: true }
    }
    MouseArea {
        anchors.fill: parent
        function point(y) {
            var r = Math.max(0, Math.min(1, y / root.height))
            var idx = Math.min(26, Math.floor(r * 27))
            root.ratio = (idx + 0.5) / 27
            var l = root.az.charAt(idx)
            if (l !== root.cur) { root.cur = l; root.letter(l) }
        }
        onPressed: (m) => { root.down = true; root.cur = ""; point(m.y) }
        onPositionChanged: (m) => { if (pressed) point(m.y) }
        onReleased: root.down = false
        onCanceled: root.down = false
    }
}
