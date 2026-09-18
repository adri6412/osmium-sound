// Now Playing at full screen, opened by the button next to the clock: with
// the VU meters on, the two meters large and centred with only the track's
// title, artist and progress below; with the VU meters off and an animation
// chosen, that animation over the whole screen: the same scene as in the
// panel, only larger.
//
// It lives inside NowPlaying (it slides with it) and covers it; while it is
// open NowPlaying hides its own meters and animation, so only one of each
// ever runs. Like NowPlaying, everything that does not move sits in a layer
// baked once: a frame is one quad plus the needles or the scene.
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    property string mode: ""                     // "" closed, "vu", "anim"
    property real devScale: 1
    property bool shown: false                   // on screen (NowPlaying shown and this open)
    signal close()
    visible: mode !== ""

    // swallow every touch that is not on a control: nothing below reacts
    MouseArea { anchors.fill: parent }

    function fmt(t) {
        t = Math.max(0, Math.floor(t || 0))
        var h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60
        return (h > 0 ? h + ":" + (m < 10 ? "0" : "") : "") + m + ":" + (s < 10 ? "0" : "") + s
    }
    readonly property string sub: [Player.artist, Player.album].filter(function(x) { return !!x }).join(" · ")

    Item {
        id: still
        anchors.fill: parent
        layer.enabled: root.shown
        layer.textureSize: Qt.size(Math.round(width * root.devScale), Math.round(height * root.devScale))
        layer.format: ShaderEffectSource.RGB
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#101010" }
                GradientStop { position: 0.6; color: "#070707" }
                GradientStop { position: 1.0; color: "#000000" }
            }
        }
        // track information: large under the meters, one line under a scene
        Text {
            visible: root.mode === "vu"
            x: 80; width: parent.width - 160; y: parent.height - 122; height: 34
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
            text: Player.title; elide: Text.ElideRight
            color: Theme.white; font.family: Theme.font; font.pixelSize: 26; font.bold: true
        }
        Text {
            visible: root.mode === "vu"
            x: 80; width: parent.width - 160; y: parent.height - 86; height: 24
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
            text: root.sub; elide: Text.ElideRight
            color: Theme.gold; font.family: Theme.font; font.pixelSize: 17
        }
        Text {
            visible: root.mode === "anim"
            x: 80; width: parent.width - 160; y: parent.height - 44; height: 24
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
            // a radio: its station too (Player.stationName is only set for streams)
            text: [Player.title !== Player.stationName ? Player.title : "", Player.artist,
                   Player.album === "" ? Player.stationName : ""].filter(function(x) { return !!x }).join(" · ")
            elide: Text.ElideRight
            color: Theme.silverA(0.75); font.family: Theme.font; font.pixelSize: 15
        }
    }

    // ── the VU meters ──────────────────────────────────────────────────────
    VuPanel {
        x: 40; y: 58; width: parent.width - 80; height: parent.height - 192
        visible: root.mode === "vu"; devScale: root.devScale
    }
    // progress: outside the layer, it changes twice a second
    Item {
        visible: root.mode === "vu"
        x: 112; y: parent.height - 48; width: parent.width - 224; height: 24
        Text { x: -80; width: 68; height: parent.height; horizontalAlignment: Text.AlignRight; verticalAlignment: Text.AlignVCenter
               text: root.fmt(Player.elapsed); color: Theme.silverA(0.7); font.family: Theme.mono; font.pixelSize: 13 }
        Text { x: parent.width + 12; width: 68; height: parent.height; verticalAlignment: Text.AlignVCenter
               text: root.fmt(Player.duration); color: Theme.silverA(0.7); font.family: Theme.mono; font.pixelSize: 13 }
        Rectangle {
            id: bar
            y: 9; width: parent.width; height: 6; radius: 3; color: Theme.wa(0.10)
            Rectangle {
                height: parent.height; radius: 3; color: Theme.gold
                width: Player.duration > 0 ? parent.width * Math.max(0, Math.min(1, Player.elapsed / Player.duration)) : 0
            }
        }
        MouseArea {
            anchors.fill: parent; anchors.topMargin: -10; anchors.bottomMargin: -10
            enabled: Player.duration > 0
            onClicked: (m) => Player.seekFraction(m.x / width)
        }
    }

    // ── the animation ──────────────────────────────────────────────────────
    NpAnimation {
        x: 24; y: 58; width: parent.width - 48; height: parent.height - 110
        kind: root.mode === "anim" ? Player.npAnimation : ""
        active: root.shown && root.mode === "anim"
        devScale: root.devScale
    }

    RoundButton { x: 20; y: 12; width: 38; height: 38; icon: "minimize-2"; iconSize: 20; onClicked: root.close() }
}
