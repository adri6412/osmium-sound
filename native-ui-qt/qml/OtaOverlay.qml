// L'overlay a schermo intero durante un aggiornamento (Settings.jsx:4420):
// rotellina / spunta / triangolo, titolo, messaggio, barra e percentuale.
// Lo stato arriva da Player (/update/status ogni 3 s), da qualunque schermata.
import QtQuick
import Hifi.Ui

Item {
    id: root
    property bool dismissed: false
    property string lastState: ""
    readonly property bool busy: Player.otaState !== "" && Player.otaState !== "idle"
    readonly property bool active: busy && !dismissed
    readonly property bool done: Player.otaState === "done" || Player.otaState === "success"
    readonly property bool error: Player.otaState === "error" || Player.otaState === "failed"
    visible: active
    anchors.fill: parent
    Connections { target: Player; function onOtaChanged() { if (root.busy && Player.otaState !== root.lastState) root.dismissed = false; root.lastState = Player.otaState } }
    MouseArea { anchors.fill: parent }
    Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0, 0, 0.9) }
    Item {
        anchors.fill: parent
        readonly property real cx: width / 2
        readonly property real cy: height / 2
        Spinner { visible: !root.done && !root.error; active: root.active; x: parent.cx - 32; y: parent.cy - 120 - 32; radius: 32; thickness: 6 }
        Icon { visible: root.done; x: parent.cx - 32; y: parent.cy - 120 - 32; name: "check-circle"; size: 64; color: Theme.green500 }
        Icon { visible: root.error; x: parent.cx - 32; y: parent.cy - 120 - 32; name: "alert-triangle"; size: 64; color: Theme.red500 }
        Text {
            width: parent.width; y: parent.cy - 56; height: 36; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
            text: root.done ? Tr.t("settings.updates.overlay.done")
                : Tr.t(Player.otaKind === "ui" ? "settings.updates.overlay.titleUi" : Player.otaKind === "system" ? "settings.updates.overlay.titleSystem"
                     : Player.otaKind === "os" ? "settings.updates.overlay.titleOs" : Player.otaKind === "lyrion" ? "settings.updates.overlay.titleLyrion" : "settings.updates.overlay.titleAll")
            color: Theme.white; font.family: Theme.font; font.pixelSize: 30; font.bold: true
        }
        Text { x: parent.cx - 300; y: parent.cy - 12; width: 600; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight; horizontalAlignment: Text.AlignHCenter; text: Player.otaMessage; color: Theme.wa(0.9); font.family: Theme.font; font.pixelSize: 18 }
        Rectangle {
            visible: !root.done && !root.error
            x: parent.cx - 224; y: parent.cy + 56; width: 448; height: 12; radius: 6; color: Theme.gray
            Rectangle { width: parent.width * Math.max(0, Math.min(100, Player.otaPercent)) / 100; height: 12; radius: 6; color: Theme.gold
                        Behavior on width { NumberAnimation { duration: 400; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } } }
        }
        Text { visible: !root.done && !root.error && Player.otaPercent > 0; width: parent.width; y: parent.cy + 80; height: 32; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; text: Player.otaPercent + "%"; color: Theme.accent; font.family: Theme.font; font.pixelSize: 24; font.bold: true }
        Rectangle {
            visible: root.done || root.error
            x: parent.cx - width / 2; y: parent.cy + 96; width: dismissText.implicitWidth + 64; height: 46; radius: 8; color: dTap.mix(Theme.accent, Theme.light)
            Text { id: dismissText; anchors.centerIn: parent; text: Tr.t("settings.updates.overlay.dismiss"); color: Theme.white; font.family: Theme.font; font.pixelSize: 16 }
            Tap { id: dTap; onClicked: root.dismissed = true }
        }
        Text { visible: !root.done && !root.error; width: parent.width; y: parent.cy + 116; height: 24; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; text: Tr.t("settings.updates.overlay.keepPowered"); color: Theme.wa(0.5); font.family: Theme.font; font.pixelSize: 14 }
    }
}
