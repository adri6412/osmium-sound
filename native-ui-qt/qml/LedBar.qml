// The status plate under the cover ("V3 bis nuova disposizione"): Hi-Res /
// PCM / DSD on the left, the BitPerfect and ReplayGain tiles with their
// labels, then the OSMIUM SOUND mark. PNG layers on one 897x175 canvas: the
// base draws every light off, each "on" layer lights one of them.
//
// 🚨 The artwork has a DSP tile in the fourth slot; it is left out (base
// "senza DSP", no DSP layer) because DSP is not part of this build, and the
// brand mark takes its place.
import QtQuick
import Hifi.Ui

Item {
    id: root
    property bool pcm: Player.qPcm
    property bool hires: Player.qHires
    property bool dsd: Player.qDsd
    property int  mode: Player.ledMode           // 1 BitPerfect, 2 ReplayGain
    property real devScale: 1
    // a tap on the BitPerfect or ReplayGain tile (or its label): "bitperfect"
    // or "replaygain", to open the setting behind that light
    signal openSetting(string which)
    height: width * 175 / 897

    Repeater {
        model: [
            { f: "led-bar-base.png", on: true },
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
    // Tap zones, artwork columns: BitPerfect tile + label 205..420,
    // ReplayGain 430..640, the plate's whole height
    Repeater {
        model: [{ which: "bitperfect", x0: 205, x1: 420 }, { which: "replaygain", x0: 430, x1: 640 }]
        MouseArea {
            required property var modelData
            x: root.width * modelData.x0 / 897; width: root.width * (modelData.x1 - modelData.x0) / 897
            height: root.height
            onClicked: root.openSetting(modelData.which)
        }
    }
    // OSMIUM / SOUND in the free slot, centred on where the DSP tile and its
    // label would be (x 718..799 and y 23..154 of the 897x175 artwork), so it
    // lines up with the column of the BitPerfect and ReplayGain tiles.
    // Body 2.1 % of the width, bold, tracking 0.1 em, line height 1.05.
    Column {
        readonly property real cx: root.width * 758.5 / 897
        readonly property real cy: root.height * 88.5 / 175
        x: cx - width / 2
        y: cy - height / 2
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
