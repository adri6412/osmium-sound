// The two analog VU meters. Their look comes from a skin in assets/vu/<id>/
// (shipped) or in Sys.vuStore/<id>/ (downloaded from the VU meter store):
// skin.json, under.png below the needles, over.png above them, needle.png
// for the needle. Picked in Settings → VU meter and read from
// Player.vuStyle. The panel keeps the artwork's shape inside the box; the
// needles follow Vu.left/right (0..100) across the skin's arc.
//
// skin.json "effects" (format 2), all optional and all plain parameters:
//   ballistics  {stiffness, damping, mass}      the needle spring (VuMeter)
//   backlight   {image, off, fadeMs}            full-panel image over under.png,
//                                               fully lit while playing, `off` opacity otherwise
//   peakLamp    {image, at:[[x,y],[x,y]], width, height, threshold, holdMs, layer}
//                                               lights over `threshold` (0..100) for holdMs;
//                                               layer "over" puts it above over.png
//   peakNeedle  {holdMs, fall, + needle keys}   a second needle on the held peak
//                                               (VuMeter.peakLeft/Right), drawn behind the needle
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
    // the audio: the preview in Settings → VU meter draws once and never
    // repaints with the music
    property var levels: null
    readonly property bool live: levels === null

    // The original skin, also the fallback when the chosen one is missing or
    // its skin.json does not parse (a skin removed by an update, a typo).
    readonly property var classic: ({
        id: "classic", base: Sys.assets + "/vu/classic/", size: [1280, 675], under: "under.png", over: "over.png",
        needle: { color: "#111111", width: 3.84, minWidth: 2, height: 275, cap: 17.92, shadow: true },
        meters: [[335, 461], [944, 461]], angles: [-36.4, 37.0], effects: {}
    })
    // file names inside a skin: flat, no path, like the store unpacks them
    function safe(n) { return typeof n === "string" && /^[a-z0-9][a-z0-9._-]*\.(png|jpg)$/.test(n) }
    function read(dir, id) {
        var t = Sys.readFile(dir + "/" + id + "/skin.json")
        return t ? JSON.parse(t) : null
    }
    function load(id) {
        if (!id || !/^[a-z0-9][a-z0-9_-]*$/.test(id)) return classic
        try {
            var s = read(Sys.assets + "/vu", id), base = Sys.assets + "/vu/" + id + "/"
            if (!s && Sys.vuStore) { s = read(Sys.vuStore, id); base = Sys.vuStore + "/" + id + "/" }
            if (!s || !s.size || !s.meters || s.meters.length < 2 || !s.angles || !s.needle
                || !safe(s.under) || !safe(s.over) || (s.needle.image && !safe(s.needle.image))) {
                if (id !== "classic") Sys.log("vu: skin \"" + id + "\" unreadable, using classic")
                return classic
            }
            s.id = id
            s.base = base
            var e = s.effects && typeof s.effects === "object" ? s.effects : {}
            for (var k of ["backlight", "peakLamp", "peakNeedle"])
                if (e[k] && e[k].image !== undefined && !safe(e[k].image)) delete e[k]
            if (e.peakLamp && !(e.peakLamp.at && e.peakLamp.at.length >= 2 && e.peakLamp.image)) delete e.peakLamp
            if (e.backlight && !e.backlight.image) delete e.backlight
            s.effects = e
            return s
        } catch (err) {
            Sys.log("vu: skin \"" + id + "\" unreadable, using classic")
            return classic
        }
    }
    readonly property var skin: load(style)
    readonly property var fx: skin.effects || {}
    readonly property string base: skin.base
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
    function level(i) { return root.live ? (i === 0 ? Vu.left : Vu.right) : root.levels[i] }
    // the preview shows the peak needle a little above the needle
    function peak(i) { return root.live ? (i === 0 ? Vu.peakLeft : Vu.peakRight) : Math.min(100, root.levels[i] + 14) }

    // The meters on screen drive the one VuMeter: spring and peak hold follow
    // the skin. The previews never touch it.
    function applyDynamics() {
        if (!root.live || !root.skin) return
        var f = root.skin.effects || {}
        var b = f.ballistics || {}
        Vu.setBallistics(Number(b.stiffness) || 0, Number(b.damping) || 0, Number(b.mass) || 0)
        var p = f.peakNeedle
        Vu.setPeakHold(p ? (p.holdMs !== undefined ? Number(p.holdMs) : 1500) : 0, p ? Number(p.fall) || 0 : 0)
    }
    onSkinChanged: applyDynamics()
    Component.onCompleted: applyDynamics()

    // One needle: drawn (color/width/height/cap/shadow) or an image turning
    // around pivotX/pivotY inside the sprite.
    component Needle: Item {
        id: nd
        property var n: ({})
        property real deg: 0
        // drawn needle (classic skin): 0.3 % of the artwork, at least 2 points
        Item {
            id: drawn
            visible: !nd.n.image
            width: Math.max(nd.n.minWidth || 0, (nd.n.width || 0) * root.ps)
            height: (nd.n.height || 0) * root.ps
            x: -width / 2; y: -height
            transformOrigin: Item.Bottom
            rotation: nd.deg
            // shadow-[1px_0_3px_rgba(0,0,0,0.6)]: turns with the needle
            BoxShadow { visible: !nd.n.image && !!nd.n.shadow; targetX: 0; targetY: 0; targetW: drawn.width; targetH: drawn.height; radius: 0; blur: 3; offsetX: 1; offsetY: 0; color: Qt.rgba(0, 0, 0, 0.6) }
            Rectangle { anchors.fill: parent; color: nd.n.color || "#111111"; antialiasing: true }
        }
        Rectangle {                              // pivot cap
            visible: !nd.n.image && (nd.n.cap || 0) > 0
            width: (nd.n.cap || 0) * root.ps; height: width
            x: -width / 2; y: -height / 2
            radius: width / 2
            color: nd.n.color || "#111111"
            antialiasing: true
        }
        // image needle, decoded at the size it is shown at, so at 720p the GPU
        // does not sample a four-times-larger texture on every frame
        Image {
            visible: !!nd.n.image
            source: nd.n.image ? root.base + nd.n.image : ""
            width: (nd.n.width || 0) * root.ps
            height: (nd.n.height || 0) * root.ps
            x: -(nd.n.pivotX || 0) * root.ps
            y: -(nd.n.pivotY || 0) * root.ps
            smooth: true; antialiasing: true; asynchronous: true
            sourceSize.width: Math.max(1, Math.round(width * root.devScale))
            sourceSize.height: Math.max(1, Math.round(height * root.devScale))
            transform: Rotation {
                origin.x: (nd.n.pivotX || 0) * root.ps
                origin.y: (nd.n.pivotY || 0) * root.ps
                angle: nd.deg
            }
        }
    }

    // A peak lamp: lights over the threshold and stays lit for holdMs.
    component Lamp: Image {
        id: lamp
        required property int index
        readonly property var cfg: root.fx.peakLamp
        readonly property real lvl: root.level(index)
        property bool lit: false
        onLvlChanged: if (root.live && lvl >= (cfg.threshold !== undefined ? cfg.threshold : 90)) { lit = true; hold.restart() }
        Timer { id: hold; interval: lamp.cfg.holdMs || 800; onTriggered: lamp.lit = false }
        readonly property real cw: (cfg.width || 0) * root.ps
        readonly property real ch: (cfg.height || 0) * root.ps
        x: root.px0 + cfg.at[index][0] * root.ps - cw / 2
        y: root.py0 + cfg.at[index][1] * root.ps - ch / 2
        width: cw; height: ch
        source: root.base + cfg.image
        smooth: true; asynchronous: true
        sourceSize.width: Math.max(1, Math.round(cw * root.devScale)); sourceSize.height: Math.max(1, Math.round(ch * root.devScale))
        opacity: lit ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: lamp.lit ? 60 : 250 } }
    }

    // 🚨 no backdrop rectangle: the classic skin has transparent corners and
    // the Now Playing background must show through them (a skin with a panel
    // of its own, like the modulometer, carries it inside under.png).
    Image {
        x: root.px0; y: root.py0; width: root.pw; height: root.ph
        source: root.base + root.skin.under
        smooth: true; asynchronous: true
        sourceSize.width: Math.round(root.pw * root.devScale); sourceSize.height: Math.round(root.ph * root.devScale)
    }
    // backlight: one fade when playback starts or stops, nothing in between
    Image {
        id: backlight
        readonly property var cfg: root.fx.backlight
        x: root.px0; y: root.py0; width: root.pw; height: root.ph
        source: cfg ? root.base + cfg.image : ""
        smooth: true; asynchronous: true
        sourceSize.width: Math.round(root.pw * root.devScale); sourceSize.height: Math.round(root.ph * root.devScale)
        opacity: !cfg ? 0 : (!root.live || Player.playing) ? 1 : (cfg.off !== undefined ? Number(cfg.off) : 0)
        visible: !!cfg && opacity > 0
        Behavior on opacity { NumberAnimation { duration: backlight.cfg && backlight.cfg.fadeMs !== undefined ? backlight.cfg.fadeMs : 600 } }
    }
    Repeater {
        model: root.fx.peakLamp && root.fx.peakLamp.layer !== "over" ? 2 : 0
        Lamp {}
    }
    Repeater {
        model: 2
        Item {
            id: meter
            required property int index
            x: root.px0 + root.skin.meters[index][0] * root.ps
            y: root.py0 + root.skin.meters[index][1] * root.ps
            Needle {
                visible: !!root.fx.peakNeedle
                n: root.fx.peakNeedle ? Object.assign({ color: "#d32f2f", width: 2, minWidth: 1.5, height: root.skin.needle.height || 300 }, root.fx.peakNeedle) : ({})
                deg: root.fx.peakNeedle ? root.angle(root.peak(meter.index)) : 0
            }
            Needle {
                n: root.skin.needle
                deg: root.angle(root.level(meter.index))
            }
        }
    }
    Image {
        x: root.px0; y: root.py0; width: root.pw; height: root.ph
        source: root.base + root.skin.over
        smooth: true; asynchronous: true
        sourceSize.width: Math.round(root.pw * root.devScale); sourceSize.height: Math.round(root.ph * root.devScale)
    }
    Repeater {
        model: root.fx.peakLamp && root.fx.peakLamp.layer === "over" ? 2 : 0
        Lamp {}
    }
}
