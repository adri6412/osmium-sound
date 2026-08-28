// "Salva come playlist": max-w-sm (384) p-5, campo di testo con bordo oro.
import QtQuick
import Hifi.Ui

Rectangle {
    id: root
    property string name: ""
    property string msg: ""
    signal cancel()
    signal saved()
    width: 384
    height: 20 + 17 + 12 + 46 + 16 + 40 + 20
    radius: 16; color: Theme.panel; border.width: 1; border.color: Theme.border
    BoxShadow { z: -1; targetX: 0; targetY: 0; targetW: parent.width; targetH: parent.height; radius: 16; blur: 50; spread: -12; offsetY: 25; color: Theme.blackA(0.25) }   // shadow-2xl
    MouseArea { anchors.fill: parent }
    onVisibleChanged: if (visible) field.takeFocus()

    function doSave() {
        var nm = name.trim()
        if (!nm) return
        Player.query(["playlist", "save", nm], function(ok, r) {
            if (!ok || (r && (r.writeError || r.error))) { root.msg = Tr.t("player.saveError"); return }
            root.saved()
        })
    }

    Text { x: 20; y: 20; height: 17; verticalAlignment: Text.AlignVCenter; text: Tr.t("player.saveAsPlaylist"); color: Theme.white; font.family: Theme.font; font.pixelSize: 14; font.bold: true }
    TextField_ {
        id: field
        x: 20; y: 49; width: parent.width - 40; height: 46
        text: root.name
        placeholder: Tr.t("player.playlistNamePlaceholder")
        focusBorder: true; restBorder: Theme.accent          // border-hifi-accent a riposo
        onTextEdited: (t) => { root.name = t; root.msg = "" }
        onAccepted: root.doSave()
    }
    Text {
        x: 20; y: 97; width: parent.width - 40; horizontalAlignment: Text.AlignHCenter
        text: root.msg; visible: root.msg !== ""
        color: Theme.red300; font.family: Theme.font; font.pixelSize: 12
    }
    Rectangle {
        x: 20; y: 111; width: (384 - 40 - 8) / 2; height: 40; radius: 8
        color: cancelTap.mix(Theme.light, Theme.accent)
        Text { anchors.centerIn: parent; text: Tr.t("common.cancel"); color: Theme.white; font.family: Theme.font; font.pixelSize: 14 }
        Tap { id: cancelTap; onClicked: root.cancel() }
    }
    Rectangle {
        x: 196; y: 111; width: (384 - 40 - 8) / 2; height: 40; radius: 8
        color: root.name.trim() ? Theme.gold : Theme.goldA(0.4)
        // disabled:opacity-40 sull'intero pulsante: anche il testo nero va al 40 %
        Text { anchors.centerIn: parent; text: Tr.t("common.confirm"); color: root.name.trim() ? Theme.black : Theme.blackA(0.4); font.family: Theme.font; font.pixelSize: 14; font.bold: true }
        Tap { enabled: root.name.trim() !== ""; onClicked: root.doSave() }
    }
}
