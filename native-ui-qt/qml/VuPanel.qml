// The two analog VU meters. Their look comes from a skin in assets/vu/<id>/
// (skin.json, under.png below the needles, over.png above them, needle.png
// for the needle), picked in Settings → Playback and read from
// Player.vuStyle. The panel keeps the artwork's shape inside the box; the
// needles follow Vu.left/right (0..100) across the skin's arc.
//
// Skins are built with tools/vu-skin-build.py. "classic" is the original
// look (AnalogVUMeter.jsx / vu.c): its needle is drawn, not an image.
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    property real devScale: 1
    property string style: Player.vuStyle
    // [left, right] (0..100) holds the needles still instead of following
    // the audio: the preview in Settings → Playback draws once and never
    // repaints with the music
    property var levels: null

    // The original skin, also the fallback when the chosen one is missing or
    // its skin.json does not parse (a skin removed by an update, a typo).
    readonly property var classic: ({
        id: "classic", size: [1280, 675], under: "under.png", over: "over.png",
        needle: { color: "#111111", width: 3.84, minWidth: 2, height: 275, cap: 17.92, shadow: true },
        meters: [[335, 461], [944, 461]], angles: [-36.4, 37.0]
    })
    function load(id) {
        if (!id || !/^[a-z0-9][a-z0-9_-]*$/.test(id)) return classic
        try {
            var s = JSON.parse(Sys.readFile(Sys.assets + "/vu/" + id + "/skin.json"))
            if (!s.size || !s.meters || s.meters.length < 2 || !s.angles || !s.needle) return classic
            s.id = id
            return s
        } catch (e) {
            Sys.log("vu: skin \"" + id + "\" unreadable, using classic")
            return classic
        }
    }
    readonly property var skin: load(style)
    readonly property string base: Sys.assets + "/vu/" + skin.id + "/"
    readonly property real sw: skin.size[0]
    readonly property real sh: skin.size[1]
    readonly property real ps: Math.min(width / sw, height / sh)
    readonly property real pw: sw * ps
    readonly property real ph: sh * ps
    readonly property real px0: (width - pw) / 2
    readonly property real py0: (height - ph) / 2
    readonly property real a0: skin.angles[0]
    readonly property real a1: skin.angles[1]
    function angle(level) { return a0 + (a1 - a0) * Math.max(0, Math.min(100, level)) / 100 }

    // 🚨 no backdrop rectangle: the classic skin has transparent corners and
    // the Now Playing background must show through them (a skin with a panel
    // of its own, like the modulometer, carries it inside under.png).
    Image {
        x: root.px0; y: root.py0; width: root.pw; height: root.ph
        source: root.base + root.skin.under
        smooth: true; asynchronous: true
        sourceSize.width: Math.round(root.pw * root.devScale); sourceSize.height: Math.round(root.ph * root.devScale)
    }
    Repeater {
        model: 2
        Item {
            id: meter
            required property int index
            readonly property var n: root.skin.needle
            readonly property real deg: root.angle(root.levels ? root.levels[index] : index === 0 ? Vu.left : Vu.right)
            x: root.px0 + root.skin.meters[index][0] * root.ps
            y: root.py0 + root.skin.meters[index][1] * root.ps

            // drawn needle (classic skin): 0.3 % of the artwork, at least 2 points
            Item {
                id: drawn
                visible: !meter.n.image
                width: Math.max(meter.n.minWidth || 0, (meter.n.width || 0) * root.ps)
                height: (meter.n.height || 0) * root.ps
                x: -width / 2; y: -height
                transformOrigin: Item.Bottom
                rotation: meter.deg
                // shadow-[1px_0_3px_rgba(0,0,0,0.6)]: turns with the needle
                BoxShadow { visible: !!meter.n.shadow; targetX: 0; targetY: 0; targetW: drawn.width; targetH: drawn.height; radius: 0; blur: 3; offsetX: 1; offsetY: 0; color: Qt.rgba(0, 0, 0, 0.6) }
                Rectangle { anchors.fill: parent; color: meter.n.color || "#111111"; antialiasing: true }
            }
            Rectangle {                              // pivot cap
                visible: !meter.n.image && (meter.n.cap || 0) > 0
                width: (meter.n.cap || 0) * root.ps; height: width
                x: -width / 2; y: -height / 2
                radius: width / 2
                color: meter.n.color || "#111111"
                antialiasing: true
            }

            // image needle: turns around its pivot (pivotX/pivotY inside the
            // sprite), decoded at the size it is shown at, so at 720p the GPU
            // does not sample a four-times-larger texture on every frame
            Image {
                visible: !!meter.n.image
                source: meter.n.image ? root.base + meter.n.image : ""
                width: (meter.n.width || 0) * root.ps
                height: (meter.n.height || 0) * root.ps
                x: -(meter.n.pivotX || 0) * root.ps
                y: -(meter.n.pivotY || 0) * root.ps
                smooth: true; antialiasing: true; asynchronous: true
                sourceSize.width: Math.max(1, Math.round(width * root.devScale))
                sourceSize.height: Math.max(1, Math.round(height * root.devScale))
                transform: Rotation {
                    origin.x: (meter.n.pivotX || 0) * root.ps
                    origin.y: (meter.n.pivotY || 0) * root.ps
                    angle: meter.deg
                }
            }
        }
    }
    Image {
        x: root.px0; y: root.py0; width: root.pw; height: root.ph
        source: root.base + root.skin.over
        smooth: true; asynchronous: true
        sourceSize.width: Math.round(root.pw * root.devScale); sourceSize.height: Math.round(root.ph * root.devScale)
    }
}
