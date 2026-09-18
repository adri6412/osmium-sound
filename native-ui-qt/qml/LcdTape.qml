// The grey-green reflective LCD of the 90s cassette deck (AnimCassette.qml,
// full screen): level meters for the left and right channel, the tape
// counter, the transport indicators. A 160 x 58 point panel; the ground with
// every segment faintly visible is one picture, the lit parts are pictures
// laid on it (tools/np-anim/lcd.py, the TAPE constants mirrored below).
//
// The meters follow the audio (VU levels, 0..100) in whole segments: each
// row is one picture cut to length, so a level change moves one edge.
import QtQuick

Item {
    id: root
    width: 160; height: 58
    property url base                     // .../anim/lcd/
    property real texScale: 1
    property bool on: true
    property int counter: 0
    property bool counterShown: true
    property bool play: false
    property bool pause: false
    property bool forward: false
    property real levelL: 0               // 0..100
    property real levelR: 0

    function px(v) { return Math.max(1, Math.round(v * texScale)) }
    function glyph(c) { return c === " " || c === "" ? "" : "d-" + c + ".png" }
    readonly property string digits: {
        var v = String(Math.max(0, Math.floor(counter)) % 10000)
        while (v.length < 4) v = "0" + v
        return v
    }
    readonly property var cx: [100, 113, 126, 139]
    readonly property real k: 0.72
    function segs(level) { return Math.max(0, Math.min(16, Math.round(level / 100 * 16))) }

    component Seg: Image {
        smooth: true
        asynchronous: false
        sourceSize.width: root.px(width)
        sourceSize.height: root.px(height)
    }

    Seg { anchors.fill: parent; source: root.base + "tape-bg.png" }

    Repeater {
        model: 4
        Seg {
            required property int index
            x: root.cx[index] - 2 * root.k; y: 14 - 2 * root.k; width: 22.44 * root.k; height: 32 * root.k
            visible: root.on && root.counterShown
            source: root.base + root.glyph(root.digits[index])
        }
    }

    // the meters: tape-meter.png covers (14, 13, 80, 20); a row is its strip
    Repeater {
        model: 2
        Item {
            required property int index
            readonly property real rowY: index === 0 ? 15 : 25.5
            readonly property int n: root.segs(index === 0 ? root.levelL : root.levelR)
            x: 14; y: rowY - 1.5; height: 5.5 + 3.5
            width: n > 0 ? 2 + n * 4.8 - 0.8 + 1.5 : 0
            visible: root.on && n > 0
            clip: true
            Seg { x: 0; y: 13 - parent.y; width: 80; height: 20; source: root.base + "tape-meter.png" }
        }
    }

    Seg { x: 4.5; y: 1.5; width: 21.44; height: 8.82; visible: root.on && root.play; source: root.base + "i-t-play.png" }
    Seg { x: 32.5; y: 1.5; width: 25.26; height: 8.82; visible: root.on && root.pause; source: root.base + "i-t-pause.png" }
    Seg { x: 64.5; y: 1.5; width: 10.51; height: 8.82; visible: root.on; source: root.base + "i-t-nr.png" }
    Seg { x: 78.5; y: 1.5; width: 29.77; height: 8.82; visible: root.on; source: root.base + "i-t-autorev.png" }
    Seg { x: 4.5; y: 13.1; width: 6.3; height: 9.05; visible: root.on; source: root.base + "i-t-l.png" }
    Seg { x: 4.5; y: 23.6; width: 6.9; height: 9.05; visible: root.on; source: root.base + "i-t-r.png" }
    Seg { x: 12; y: 32; width: 84; height: 7; visible: root.on; source: root.base + "i-t-scale.png" }
    Seg { x: 102.5; y: 36.0; width: 23.77; height: 7.7; visible: root.on; source: root.base + "i-t-counter.png" }
    Seg { x: 4.5; y: 44.5; width: 16.06; height: 8.6; visible: root.on; source: root.base + "i-t-type.png" }
    Seg { x: 31.5; y: 44.5; width: 5.78; height: 8.6; visible: root.on; source: root.base + "i-t-t2.png" }
    Seg { x: 110.5; y: 44.5; width: 6.73; height: 9.72; visible: root.on && root.forward; source: root.base + "i-t-fwd.png" }

    Seg { anchors.fill: parent; source: root.base + "lcd-glass.png" }
}
