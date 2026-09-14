// Timer di spegnimento: max-w-xs (320) p-5, sei scelte 15..120 minuti e "off".
import QtQuick
import Hifi.Ui

Rectangle {
    id: root
    signal done()
    readonly property bool activeTimer: Player.sleepSecs > 0
    readonly property var mins: [15, 30, 45, 60, 90, 120]
    width: 320
    height: 20 + 16 + 12 + (activeTimer ? 15 + 12 : 0) + 2 * 40 + 8 + 12 + 40 + 20
    radius: 16; color: Theme.panel; border.width: 1; border.color: Theme.border
    BoxShadow { z: -1; targetX: 0; targetY: 0; targetW: parent.width; targetH: parent.height; radius: 16; blur: 50; spread: -12; offsetY: 25; color: Theme.blackA(0.25) }   // shadow-2xl
    MouseArea { anchors.fill: parent }          // non chiudere toccando il dialogo
    Icon { x: 20; y: 20; name: "moon"; size: 16; color: Theme.gold }
    Text { x: 44; y: 20; height: 16; verticalAlignment: Text.AlignVCenter; text: Tr.t("player.sleep"); color: Theme.white; font.family: Theme.font; font.pixelSize: 14; font.bold: true }
    Text {
        x: 20; y: 48; height: 15; visible: root.activeTimer; verticalAlignment: Text.AlignVCenter
        text: Tr.tf("player.sleepActive", "min", String(Math.floor((Player.sleepSecs + 59) / 60)))
        color: Theme.gold; font.family: Theme.font; font.pixelSize: 12
    }
    Grid {
        x: 20; y: 48 + (root.activeTimer ? 27 : 0)
        columns: 3; columnSpacing: 8; rowSpacing: 8
        Repeater {
            model: root.mins
            Rectangle {
                required property int modelData
                width: (280 - 16) / 3; height: 40; radius: 8
                color: optTap.mix(Theme.surface, Theme.light); border.width: 1; border.color: Theme.border
                Text { anchors.centerIn: parent; text: modelData + "m"; color: Theme.white; font.family: Theme.font; font.pixelSize: 14 }
                Tap { id: optTap; onClicked: { Player.setSleep(modelData * 60); root.done() } }
            }
        }
    }
    Rectangle {
        x: 20; y: root.height - 20 - 40; width: 280; height: 40; radius: 8
        color: Theme.redA(0.1); border.width: 1; border.color: Theme.redA(0.2)
        Text { anchors.centerIn: parent; text: Tr.t("player.sleepOff"); color: Theme.red300; font.family: Theme.font; font.pixelSize: 14 }
        Tap { onClicked: { Player.setSleep(0); root.done() } }
    }
}
