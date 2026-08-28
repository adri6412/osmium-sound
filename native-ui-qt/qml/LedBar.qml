// La targa dei LED (LedBar.jsx / ledbar.c): sette strati PNG sovrapposti, si
// accendono quelli dello stato corrente, e le scritte OSMIUM / SOUND.
import QtQuick
import Hifi.Ui

Item {
    id: root
    property bool pcm: Player.qPcm
    property bool hires: Player.qHires
    property bool dsd: Player.qDsd
    property int  mode: Player.ledMode           // 1 BitPerfect, 2 ReplayGain
    property real devScale: 1
    height: width * 175 / 897

    Repeater {
        model: [
            { f: "led-bar-base.png", on: true },
            { f: "led-bar-off.png", on: true },
            { f: "led-bar-hires.png", on: root.hires },
            { f: "led-bar-pcm.png", on: root.pcm },
            { f: "led-bar-dsd.png", on: root.dsd },
            { f: "led-bar-bitperfect.png", on: root.mode === 1 },
            { f: "led-bar-replaygain.png", on: root.mode === 2 },
        ]
        Image {
            required property var modelData
            anchors.fill: parent
            source: Sys.assets + "/" + modelData.f
            visible: modelData.on
            asynchronous: true
            smooth: true
            mipmap: true
            sourceSize.width: Math.round(root.width * root.devScale)
            sourceSize.height: Math.round(root.height * root.devScale)
        }
    }
    // OSMIUM / SOUND: riquadro a 81 % / 49 %, 12,82 % x 28,57 %, corpo 2,1 %
    // della larghezza, grassetto, tracking 0,1 em, interlinea 1,05
    Column {
        x: root.width * 0.81 + (root.width * 0.1282 - width) / 2
        y: root.height * 0.49 + (root.height * 0.2857 - height) / 2
        property real px: Math.max(5, root.width * 0.021)
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "OSMIUM"; color: Theme.wa(0.9)
            font.family: Theme.font; font.bold: true; font.pixelSize: parent.px; font.letterSpacing: parent.px * 0.1
            lineHeight: 1.05
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "SOUND"; color: Theme.gold
            font.family: Theme.font; font.bold: true; font.pixelSize: parent.px; font.letterSpacing: parent.px * 0.1
            lineHeight: 1.05
        }
    }
}
