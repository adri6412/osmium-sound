// Menu contestuale (pressione lunga su una riga): l'elenco delle voci lo
// passa chi lo apre — coda, preferiti, preselezioni, playlist — come
// ContextMenu.jsx; scale 0,92 -> 1 con dissolvenza.
import QtQuick
import Hifi.Ui

Item {
    id: root
    // [{ icon, label, cb, danger }]
    property var items: []
    property real f: 0
    readonly property int rowH: 41
    readonly property int boxW: 272
    visible: false
    anchors.fill: parent
    function open(list, x, y) {
        items = list || []
        if (!items.length) return
        var w = boxW, h = 12 + rowH * items.length
        var px = x - w / 2, py = y - h - 12
        if (py < 8) py = y + 12
        px = Math.max(8, Math.min(parent.width - 8 - w, px))
        py = Math.max(8, Math.min(parent.height - 8 - h, py))
        box.x = px; box.y = py
        visible = true
        f = 0; f = 1
    }
    function close() { visible = false }
    Behavior on f { NumberAnimation { duration: 150; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
    MouseArea { anchors.fill: parent; onPressed: root.visible = false }
    Rectangle {
        id: box
        width: root.boxW; height: 12 + root.rowH * root.items.length; radius: 16
        color: Theme.panel; border.width: 1; border.color: Theme.border
        opacity: root.f; scale: 0.92 + 0.08 * root.f
        BoxShadow { z: -1; targetX: 0; targetY: 0; targetW: parent.width; targetH: parent.height; radius: 16; blur: 50; spread: -12; offsetY: 25; color: Theme.blackA(0.25) }   // shadow-2xl
        Column {
            y: 6
            Repeater {
                model: root.items
                Item {
                    required property var modelData
                    required property int index
                    readonly property bool last: index === root.items.length - 1
                    width: root.boxW; height: root.rowH
                    // active:bg-hifi-light, ritagliato dagli angoli del pannello (overflow-hidden)
                    Rectangle {
                        x: 1; width: parent.width - 2; height: parent.height
                        topLeftRadius: index === 0 ? 15 : 0; topRightRadius: index === 0 ? 15 : 0
                        bottomLeftRadius: last ? 15 : 0; bottomRightRadius: last ? 15 : 0
                        color: itemTap.mix(Qt.rgba(42 / 255, 42 / 255, 42 / 255, 0), Theme.light)
                    }
                    Icon { x: 16; anchors.verticalCenter: parent.verticalCenter; name: modelData.icon || "music"; size: 16; color: modelData.danger ? Theme.red300 : Theme.gold }
                    Text {
                        x: 44; width: parent.width - 44 - 12; anchors.verticalCenter: parent.verticalCenter
                        text: modelData.label || ""; elide: Text.ElideRight
                        color: modelData.danger ? Theme.red300 : Theme.white; font.family: Theme.font; font.pixelSize: 14
                    }
                    Tap { id: itemTap; onClicked: { root.visible = false; if (modelData.cb) modelData.cb() } }
                }
            }
        }
    }
}
