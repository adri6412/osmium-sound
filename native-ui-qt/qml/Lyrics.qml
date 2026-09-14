// I testi del brano (plugin MusicArtistInfo), nel riquadro dei VU quando la
// vista e' "testi": fondo nero/20 r12, testo 14 px interlinea 1,625.
import QtQuick
import Hifi.Ui

Rectangle {
    id: root
    property bool active: false
    property int state_: 0            // 0 non chiesti, 1 in corso, 2 trovati, 3 assenti
    property string key: ""
    property string text: ""
    radius: 12
    color: Theme.blackA(0.2)

    function request() {
        var k = Player.trackId + "|" + Player.artist + "|" + Player.title
        if (k === key && state_ !== 0) return
        key = k
        flick.contentY = 0
        if (!Player.trackId && !(Player.artist && Player.title)) { state_ = 3; text = ""; return }
        state_ = 1
        var mine = k
        Player.lyrics(function(t) {
            if (mine !== root.key) return
            root.text = t
            root.state_ = t ? 2 : 3
        })
    }
    onActiveChanged: if (active) request()
    Connections { target: Player; function onTrackChanged() { if (root.active) { root.state_ = 0; root.request() } } }

    Flickable {
        id: flick
        anchors.fill: parent; anchors.margins: 12; anchors.leftMargin: 16; anchors.rightMargin: 16
        contentHeight: body.height
        clip: true
        visible: root.state_ === 2
        flickDeceleration: 1500; maximumFlickVelocity: 4000
        Text {
            id: body
            width: flick.width
            text: root.text
            color: Theme.wa(0.9); font.family: Theme.font; font.pixelSize: 14
            lineHeight: 1.625
            wrapMode: Text.Wrap
        }
    }
    Text {
        anchors.horizontalCenter: parent.horizontalCenter; y: 16
        visible: root.state_ !== 2
        text: root.state_ === 1 ? Tr.t("common.loading") : Tr.t("player.lyricsNone")
        color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 14
    }
}
