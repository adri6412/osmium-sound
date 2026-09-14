// Menu contestuale (pressione lunga su un brano): "aggiungi alla coda" e
// "riproduci dopo", come ContextMenu.jsx; scale 0,92 -> 1 con dissolvenza.
import QtQuick
import Hifi.Ui

Item {
    id: root
    property string trackId: ""
    property real f: 0
    visible: false
    anchors.fill: parent
    function open(id, x, y) {
        trackId = id
        var w = 200, h = 12 + 41 * 2
        var px = x - w / 2, py = y - h - 12
        if (py < 8) py = y + 12
        px = Math.max(8, Math.min(parent.width - 8 - w, px))
        py = Math.max(8, Math.min(parent.height - 8 - h, py))
        box.x = px; box.y = py
        visible = true
        f = 0; f = 1
    }
    Behavior on f { NumberAnimation { duration: 150; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
    MouseArea { anchors.fill: parent; onPressed: root.visible = false }
    Rectangle {
        id: box
        width: 200; height: 12 + 41 * 2; radius: 16
        color: Theme.panel; border.width: 1; border.color: Theme.border
        opacity: root.f; scale: 0.92 + 0.08 * root.f
        BoxShadow { z: -1; targetX: 0; targetY: 0; targetW: parent.width; targetH: parent.height; radius: 16; blur: 50; spread: -12; offsetY: 25; color: Theme.blackA(0.25) }   // shadow-2xl
        Column {
            y: 6
            Repeater {
                model: [{ icon: "list-plus", key: "player.addToQueue", mode: "add" }, { icon: "list-start", key: "player.playNext", mode: "insert" }]
                Item {
                    required property var modelData
                    required property int index
                    width: 200; height: 41
                    // active:bg-hifi-light, ritagliato dagli angoli del pannello (overflow-hidden)
                    Rectangle {
                        x: 1; width: parent.width - 2; height: parent.height
                        topLeftRadius: index === 0 ? 15 : 0; topRightRadius: index === 0 ? 15 : 0
                        bottomLeftRadius: index === 1 ? 15 : 0; bottomRightRadius: index === 1 ? 15 : 0
                        color: itemTap.mix(Qt.rgba(42 / 255, 42 / 255, 42 / 255, 0), Theme.light)
                    }
                    Icon { x: 16; anchors.verticalCenter: parent.verticalCenter; name: modelData.icon; size: 16; color: Theme.gold }
                    Text { x: 44; anchors.verticalCenter: parent.verticalCenter; text: Tr.t(modelData.key); color: Theme.white; font.family: Theme.font; font.pixelSize: 14 }
                    Tap { id: itemTap; onClicked: { Player.cmd(["playlistcontrol", "cmd:" + modelData.mode, "track_id:" + root.trackId]); root.visible = false } }
                }
            }
        }
    }
}
