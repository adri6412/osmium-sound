// L'indice alfabetico laterale: 27 lettere, tocca o trascina per saltare.
import QtQuick
import Hifi
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
            color: root.down && root.cur === l ? Theme.gold : (Library.rev, Library.hasLetter(l)) ? Theme.silverA(0.7) : Theme.silverA(0.2)
            font.family: Theme.font; font.pixelSize: 10; font.bold: true
        }
    }
    // The bubble comes up with a scale and rides a spring from one letter to
    // the next instead of jumping.
    property real pop: 0
    Behavior on pop { NumberAnimation { duration: Theme.dur(140); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
    Spring { id: byS; stiffness: 300; damping: 30; rate: Theme.motionRate }
    readonly property real bubbleY: byS.value - 24
    // shadow-lg della bolla (48 px): 0 10px 15px -3px + 0 4px 6px -4px, nero al 10 %
    BoxShadow { visible: root.pop > 0.01; opacity: root.pop; targetX: -56; targetY: root.bubbleY; targetW: 48; targetH: 48; radius: 24; blur: 15; spread: -3; offsetY: 10; color: Theme.blackA(0.1) }
    BoxShadow { visible: root.pop > 0.01; opacity: root.pop; targetX: -56; targetY: root.bubbleY; targetW: 48; targetH: 48; radius: 24; blur: 6; spread: -4; offsetY: 4; color: Theme.blackA(0.1) }
    Rectangle {                                    // la bolla con la lettera
        visible: root.pop > 0.01
        x: -8 - 48; y: root.bubbleY; width: 48; height: 48; radius: 24; color: Theme.gold
        opacity: root.pop; scale: 0.82 + 0.18 * root.pop; transformOrigin: Item.Center
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
        // 🚨 set() and not `to` on the press: otherwise the bubble flies in
        // from whichever letter was touched last time.
        onPressed: (m) => { root.down = true; root.cur = ""; point(m.y); byS.set(root.ratio * root.height); root.pop = 1 }
        onPositionChanged: (m) => { if (pressed) { point(m.y); byS.to = root.ratio * root.height } }
        onReleased: { root.down = false; root.pop = 0 }
        onCanceled: { root.down = false; root.pop = 0 }
    }
}
