// Il pannello di sinistra della schermata principale (w-[340px] bg-hifi-panel
// in LyrionServer.jsx, draw_left in screen_main.c): intestazione, copertina
// 250, info, avanzamento, trasporto, comandi secondari, volume.
import QtQuick
import QtQuick.Effects
import Hifi.Ui

Item {
    id: root
    property real devScale: 1
    signal expand()
    signal openQueue()
    signal openSleep()
    width: 340; height: 600

    Rectangle { anchors.fill: parent; color: Theme.panel }

    // ─── intestazione h-10 ──────────────────────────────────────────────────
    Item {
        width: 340; height: 40
        Rectangle { y: 39; width: 340; height: 1; color: Theme.borderA(0.6) }
        Rectangle { id: dotGlow; x: 16; y: 16; width: 8; height: 8; radius: 4; color: Theme.goldA(0.8); visible: false; layer.enabled: true }
        MultiEffect { source: dotGlow; x: 16; y: 16; width: 8; height: 8; blurEnabled: true; blur: 0.5; blurMax: 12; autoPaddingEnabled: true }
        Rectangle { x: 16; y: 16; width: 8; height: 8; radius: 4; color: Theme.gold }
        Text {
            x: 32; anchors.verticalCenter: parent.verticalCenter
            text: "OSMIUM SOUND"; color: Theme.silverA(0.8)
            font.family: Theme.font; font.pixelSize: 11; font.bold: true; font.letterSpacing: 2
        }
        Text {
            x: 174; width: 90; height: 40; horizontalAlignment: Text.AlignRight; verticalAlignment: Text.AlignVCenter
            visible: Player.connected
            text: Player.playerName; elide: Text.ElideLeft
            color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 10
        }
        Rectangle { x: 272; y: 17; width: 6; height: 6; radius: 3; color: Player.connected ? Theme.emerald : Theme.redA(0.7) }
        RoundButton { x: 286; y: 1; width: 38; height: 38; icon: "chevron-up"; iconSize: 22; visible: Player.connected; onClicked: root.expand() }
    }

    // ─── il blocco centrale, centrato in verticale come nel JSX ────────────
    readonly property bool hasAlbum: Player.album !== ""
    readonly property bool hasChip: Player.chip !== ""
    readonly property real infoH: titleText.lineCount * 19 + 2 + 16 + (hasAlbum ? 15 : 0) + (hasChip ? 20 : 0) + 4
    readonly property real total: 270 + infoH + 25 + 64 + 32 + 32
    readonly property real y0: 40 + (600 - 40 - total) / 2

    // copertina 250 con ombra 0 8px 40px rgba(0,0,0,.7)
    Rectangle { id: shadowSrc; x: 45; y: root.y0 + 8 + 8; width: 250; height: 250; radius: 16; color: Qt.rgba(0, 0, 0, 0.7); visible: false; layer.enabled: true }
    MultiEffect { source: shadowSrc; x: shadowSrc.x; y: shadowSrc.y; width: 250; height: 250; blurEnabled: true; blur: 1.0; blurMax: 40; autoPaddingEnabled: true }
    Cover {
        id: art
        x: 45; y: root.y0 + 8; width: 250; height: 250
        source: Player.artworkUrl; radius: 16; devScale: root.devScale; border: Theme.wa(0.05)
        Tap { enabled: Player.connected; onClicked: root.expand() }
    }

    Column {
        id: info
        x: 16; y: root.y0 + 270; width: 308
        Text {
            id: titleText
            width: parent.width
            text: Player.title || Tr.t("player.noTrack")
            color: Theme.white; font.family: Theme.font; font.pixelSize: 15; font.bold: true
            wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight
            lineHeight: 19; lineHeightMode: Text.FixedHeight
        }
        Item { width: 1; height: 2 }
        Text {
            width: parent.width; height: 16; verticalAlignment: Text.AlignVCenter
            text: Player.artist || Tr.t("player.unknownArtist")
            color: Theme.gold; font.family: Theme.font; font.pixelSize: 13; elide: Text.ElideRight
        }
        Text {
            width: parent.width; height: 15; visible: root.hasAlbum; verticalAlignment: Text.AlignVCenter
            text: Player.album; color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 12; elide: Text.ElideRight
        }
        Item { width: 1; height: 4; visible: root.hasChip }
        Rectangle {
            visible: root.hasChip
            width: chipText.implicitWidth + 16; height: 16; radius: 4
            color: Theme.wa(0.05); border.width: 1; border.color: Theme.wa(0.05)
            Text { id: chipText; anchors.centerIn: parent; text: Player.chip; color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 10; font.letterSpacing: 0.3 }
        }
        Item { width: 1; height: 4 }
        Item { width: 1; height: 4 }
        Item {                                         // tempi
            width: parent.width; height: 12
            Text { anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; text: Player.formatTime(Player.elapsed); color: Theme.silverA(0.5); font.family: Theme.mono; font.pixelSize: 10 }
            Text { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; text: Player.formatTime(Player.duration); color: Theme.silverA(0.5); font.family: Theme.mono; font.pixelSize: 10 }
        }
        Item { width: 1; height: 4 }
        Item {                                         // barra
            id: bar
            width: parent.width; height: 3
            Rectangle { anchors.fill: parent; radius: 2; color: Theme.wa(0.12) }
            Item {
                width: Player.duration > 0 ? parent.width * Math.max(0, Math.min(1, Player.elapsed / Player.duration)) : 0
                height: parent.height; clip: true
                Rectangle {
                    width: bar.width; height: parent.height; radius: 2
                    gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: Theme.gold } GradientStop { position: 1; color: Theme.yellow400 } }
                }
            }
            MouseArea { anchors.fill: parent; anchors.topMargin: -10; anchors.bottomMargin: -10; onClicked: (m) => Player.seekFraction(m.x / width) }
        }
        Item { width: 1; height: 2 }
    }

    // ─── trasporto: prev 40, play 52 (alone 0 0 18px), next 40 ───────────
    Item {
        id: transport
        y: info.y + info.height + 6; width: 340; height: 52
        readonly property real cy: 26
        Item {
            x: 92; y: 6; width: 40; height: 40
            Icon { anchors.centerIn: parent; name: "skip-back"; size: 19; color: Theme.silver; scale: prevTap.tapScale }
            Tap { id: prevTap; tap: 0.88; onClicked: Player.prev() }
        }
        Item {
            x: 144; y: 0; width: 52; height: 52
            Rectangle { id: glowSrc; anchors.fill: parent; radius: 26; color: Theme.goldA(0.35); visible: false; layer.enabled: true }
            MultiEffect { source: glowSrc; anchors.fill: parent; blurEnabled: true; blur: 0.5; blurMax: 24; autoPaddingEnabled: true }
            Rectangle { anchors.fill: parent; radius: 26; color: Theme.gold; scale: playTap.tapScale }
            Icon {
                anchors.centerIn: parent; anchors.horizontalCenterOffset: Player.playing ? 0 : 1
                name: Player.playing ? "pause" : "play"; filled: true; size: 20; color: Theme.black; scale: playTap.tapScale
            }
            Tap { id: playTap; tap: 0.94; grow: 4; onClicked: Player.togglePlay() }
        }
        Item {
            x: 208; y: 6; width: 40; height: 40
            Icon { anchors.centerIn: parent; name: "skip-forward"; size: 19; color: Theme.silver; scale: nextTap.tapScale }
            Tap { id: nextTap; tap: 0.88; onClicked: Player.next() }
        }
    }

    // ─── comandi secondari 28x28 a passo 48 ──────────────────────────────
    Item {
        id: secondary
        y: transport.y + 52 + 6; width: 340; height: 32
        Item {
            x: 84; width: 28; height: 28
            Icon { anchors.centerIn: parent; name: "shuffle"; size: 16; color: Player.shuffle > 0 ? Theme.gold : shTap.mix(Theme.silverA(0.5), Theme.white) }
            Tap { id: shTap; onClicked: Player.cycleShuffle() }
        }
        Item {
            x: 132; width: 28; height: 28
            Icon { anchors.centerIn: parent; name: Player.repeat === 1 ? "repeat-1" : "repeat"; size: 16; color: Player.repeat > 0 ? Theme.gold : rpTap.mix(Theme.silverA(0.5), Theme.white) }
            Tap { id: rpTap; onClicked: Player.cycleRepeat() }
        }
        Item {
            x: 180; width: 28; height: 28
            Icon { anchors.centerIn: parent; name: "list-music"; size: 16; color: qTap.mix(Theme.silverA(0.5), Theme.white) }
            Tap { id: qTap; onClicked: root.openQueue() }
        }
        Item {
            x: 228; width: 28; height: 28
            Icon { anchors.centerIn: parent; name: "moon"; size: 16; color: Player.sleepSecs > 0 ? Theme.gold : slTap.mix(Theme.silverA(0.5), Theme.white) }
            Tap { id: slTap; onClicked: root.openSleep() }
        }
    }

    // ─── volume ───────────────────────────────────────────────────────────
    Item {
        id: volume
        y: secondary.y + 32; width: 340; height: 32
        readonly property real frac: Math.max(0, Math.min(100, Player.volume)) / 100
        Item {
            x: 11; y: 4; width: 24; height: 24
            Icon { anchors.centerIn: parent; name: Player.volume === 0 ? "volume-x" : "volume-2"; size: 14; color: Player.volumeFixed ? Theme.silverA(0.18) : Theme.silverA(0.6) }
            Tap { onClicked: Player.toggleMute() }
        }
        Item {
            id: volBar
            x: 38; y: 14.5; width: 254; height: 3
            Rectangle { anchors.fill: parent; radius: 2; color: Theme.border }
            Rectangle { x: parent.width * volume.frac - 6.5; y: -5; width: 13; height: 13; radius: 6.5; color: Player.volumeFixed ? Theme.silverA(0.3) : Theme.gold }
            MouseArea {
                anchors.fill: parent; anchors.margins: -12
                enabled: !Player.volumeFixed
                function vol(m) { return Math.round((m.x - 12) * 100 / volBar.width) }
                onPressed: (m) => Player.setVolume(vol(m), false)
                onPositionChanged: (m) => { if (pressed) Player.setVolume(vol(m), false) }
                onReleased: (m) => Player.setVolume(vol(m), true)
            }
        }
        Text {
            x: 300; y: 8; width: 24; height: 16; horizontalAlignment: Text.AlignRight; verticalAlignment: Text.AlignVCenter
            text: String(Math.max(0, Math.min(100, Player.volume))); color: Theme.silverA(0.4); font.family: Theme.mono; font.pixelSize: 10
        }
    }
}
