// La fascia dorata "CD rilevato" in cima alla scheda Musica.
import QtQuick
import Hifi.Ui

Item {
    id: root
    readonly property var cd: Ui.cdrip
    visible: cd && cd.bannerVisible
    height: visible ? 48 : 0
    Rectangle {
        x: 12; y: 8; width: parent.width - 24; height: 40; radius: 8
        color: Theme.goldA(0.1); border.width: 1; border.color: Theme.goldA(0.3)
        Icon { x: 12; anchors.verticalCenter: parent.verticalCenter; name: "disc"; size: 18; color: Theme.gold }
        Text { x: 42; y: 4; height: 18; width: ripBtn.x - 50; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; text: Tr.t("player.cd.detected"); color: Theme.white; font.family: Theme.font; font.pixelSize: 14 }
        Text { x: 42; y: 22; height: 16; width: ripBtn.x - 50; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; text: (root.cd ? root.cd.artist : "") + " — " + (root.cd ? root.cd.album : ""); color: Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 12 }
        Rectangle {
            id: ripBtn
            x: parent.width - 12 - 20 - 8 - width; anchors.verticalCenter: parent.verticalCenter; width: ripText.implicitWidth + 24; height: 26; radius: 8
            color: rTap.mix(Theme.gold, "#ca8a04")
            Text { id: ripText; anchors.centerIn: parent; text: Tr.t(root.cd && root.cd.ripping ? "player.cd.ripProgressShort" : "player.cd.rip"); color: Theme.black; font.family: Theme.font; font.pixelSize: 12; font.bold: true }
            Tap { id: rTap; onClicked: root.cd.openDialog() }
        }
        Item {
            x: parent.width - 12 - 20; anchors.verticalCenter: parent.verticalCenter; width: 20; height: 20
            Icon { anchors.centerIn: parent; name: "x"; size: 14; color: Theme.silverA(0.5) }
            Tap { grow: 6; onClicked: root.cd.dismissBanner() }
        }
    }
}
