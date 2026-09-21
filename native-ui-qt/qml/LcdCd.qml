// The display of the 90s CD players: the grey-green reflective LCD of the
// top loader (assets/anim/lcd/) or, with `base` on assets/anim/vfd/, the
// blue-green fluorescent display of the front-loading player (AnimCdFront.qml).
// A 196 x 100 point panel: the ground with every segment faintly visible is
// one picture, the lit segments are small pictures laid on it
// (tools/np-anim/lcd.py [--vfd]; the layout below mirrors that tool's
// constants, the same for both).
//
// The bottom row is the CD-Text line: sixteen 14-segment characters with the
// track's title and artist, upper case like the real displays, scrolling
// one character at a time while `scroll` is on (the disc playing).
//
// Nothing else moves by itself: the scene sets what to show. Only `spin`
// changes on a timer, a few times a second while the disc turns.
import QtQuick

Item {
    id: root
    width: 196; height: 100
    property url base                     // .../anim/lcd/
    property real texScale: 1             // pixels per point of the pictures
    property bool on: true                // powered: without it the panel is blank

    // what the six big characters show: a word over track + time ("no dISC",
    // "  OPEn", "  rEAd"), or, with word empty, the track and the time
    property string word: ""
    property int track: 0                 // 1-based, 0 = none
    property real seconds: 0
    property bool timeShown: true
    // indicators
    property bool play: false
    property bool pause: false
    property int repeatMode: 0            // 0 off, 1 one track, 2 all
    property bool random: false
    property bool labels: false           // TRACK / MIN / SEC
    // the music calendar: numbers calFrom..calTo lit (the played ones go out)
    property int calFrom: 0
    property int calTo: 0
    property bool over: false
    // the disc indicator: -1 off, 8 all lit, 0-7 that segment dark
    property int spin: -1
    // CD-Text
    property string text: ""
    property bool scroll: false

    // what the 14-segment line can spell (tools/np-anim/lcd.py TEXT_CHARS)
    readonly property string textSet: " !\"&'()*+,-./0123456789:=?ABCDEFGHIJKLMNOPQRSTUVWXYZ[]_"
    function norm(v) {
        var t = String(v || "").toUpperCase()
        try { t = t.normalize("NFD").replace(/[\u0300-\u036f]/g, "") } catch (e) {}
        t = t.replace(/ß/g, "SS").replace(/Æ/g, "AE").replace(/Œ/g, "OE").replace(/Ø/g, "O")
             .replace(/[\u2018\u2019`]/g, "'").replace(/[\u201c\u201d]/g, "\"").replace(/[\u2013\u2014]/g, "-")
        var out = ""
        for (var i = 0; i < t.length; i++) out += textSet.indexOf(t[i]) >= 0 ? t[i] : " "
        return out.replace(/ +/g, " ").trim()
    }
    readonly property string textFull: on ? norm(text) : ""
    // one cell per character; a point lights on the cell before it, like
    // the real displays ("56.3" takes three cells, not four)
    function cells(t) {
        var out = []
        for (var i = 0; i < t.length; i++) {
            if (t[i] === "." && out.length && !out[out.length - 1].dp && out[out.length - 1].c !== " ") out[out.length - 1].dp = true
            else out.push({ c: t[i], dp: false })
        }
        return out
    }
    readonly property var textCells: cells(textFull)
    readonly property bool textLong: textCells.length > 16
    readonly property var textLoop: textCells.concat(cells("    "))
    property int textOffset: 0
    property int textHold: 0
    onTextFullChanged: { textOffset = 0; textHold = 0 }
    readonly property var textShown: !textLong ? textCells
                                   : textLoop.concat(textLoop).slice(textOffset % textLoop.length, textOffset % textLoop.length + 16)
    Timer {
        interval: 300; repeat: true
        running: root.on && root.scroll && root.textLong && root.visible
        onTriggered: {
            // a breath at the start of every pass, like the real ones
            if (root.textOffset === 0 && root.textHold < 5) { root.textHold++; return }
            root.textHold = 0
            root.textOffset = (root.textOffset + 1) % root.textLoop.length
        }
    }
    function textGlyph(c) {
        if (!c || c === " ") return ""
        var h = c.charCodeAt(0).toString(16)
        return "t-" + (h.length < 2 ? "0" + h : h) + ".png"
    }

    function px(v) { return Math.max(1, Math.round(v * texScale)) }
    function glyph(c) {
        if (c === " " || c === "") return ""
        if (/[0-9-]/.test(c)) return "d-" + c + ".png"
        return (c === c.toUpperCase() ? "d-u" : "d-l") + c + ".png"
    }
    readonly property var chars: {
        if (!on) return ["", "", "", "", "", ""]
        if (word !== "") {
            var w = (word + "      ").slice(0, 6)
            return w.split("")
        }
        var t = track > 0 ? String(Math.min(99, track)) : ""
        var tt = track > 0 ? (t.length < 2 ? " " + t : t) : "  "
        if (!timeShown) return [tt[0], tt[1], "", "", "", ""]
        var s = Math.max(0, Math.floor(seconds))
        var m = Math.min(99, Math.floor(s / 60)), ss = s % 60
        var ms = m < 10 ? " " + m : String(m)
        return [tt[0], tt[1], ms[0], ms[1], String(Math.floor(ss / 10)), String(ss % 10)]
    }
    readonly property var xs: [8, 26, 60, 78, 105, 123]

    component Seg: Image {
        smooth: true
        asynchronous: false
        sourceSize.width: root.px(width)
        sourceSize.height: root.px(height)
    }

    Seg { anchors.fill: parent; source: root.base + "lcd-bg.png" }
    Repeater {
        model: 6
        Seg {
            required property int index
            readonly property string f: root.glyph(root.chars[index])
            x: root.xs[index] - 2; y: 16; width: 22.44; height: 32
            visible: f !== ""
            source: f !== "" ? root.base + f : ""
        }
    }
    Seg { x: 95.5; y: 16; width: 9; height: 32; visible: root.on && root.word === "" && root.timeShown; source: root.base + "colon.png" }

    // indicators (boxes printed by lcd.py)
    Seg { x: 6.5; y: 2.5; width: 24.28; height: 9.72; visible: root.on && root.play; source: root.base + "i-play.png" }
    Seg { x: 38.5; y: 2.5; width: 28.69; height: 9.72; visible: root.on && root.pause; source: root.base + "i-pause.png" }
    Seg { x: 84.5; y: 2.5; width: 26.89; height: 9.72; visible: root.on && root.repeatMode > 0; source: root.base + "i-repeat.png" }
    Seg { x: 111.0; y: 2.5; width: 6.34; height: 9.72; visible: root.on && root.repeatMode === 1; source: root.base + "i-one.png" }
    Seg { x: 119.5; y: 2.5; width: 30.0; height: 9.72; visible: root.on && root.random; source: root.base + "i-random.png" }
    Seg { x: 6.5; y: 47.0; width: 21.2; height: 8.82; visible: root.on && root.labels; source: root.base + "i-track.png" }
    Seg { x: 62.5; y: 47.0; width: 12.53; height: 8.82; visible: root.on && root.labels && root.timeShown; source: root.base + "i-min.png" }
    Seg { x: 108.5; y: 47.0; width: 13.69; height: 8.82; visible: root.on && root.labels && root.timeShown; source: root.base + "i-sec.png" }
    Seg { x: 135.5; y: 70.5; width: 23.55; height: 9.05; visible: root.on && root.over; source: root.base + "i-over.png" }

    Repeater {
        model: 16
        Seg {
            required property int index
            readonly property int n: index + 1
            x: 8 + (index % 8) * 16 - 1.5; y: 60 + Math.floor(index / 8) * 12 - 1.5; width: 16; height: 12.5
            visible: root.on && n >= root.calFrom && n <= root.calTo
            source: root.base + "cal-" + n + ".png"
        }
    }

    // eight pictures kept loaded, one shown at a time: the step changes a
    // few times a second and must not decode anything
    Repeater {
        model: 8
        Seg {
            required property int index
            x: 155.5; y: 17.5; width: 29; height: 29
            visible: root.on && root.spin === index
            source: root.base + "spin-" + index + ".png"
        }
    }
    Seg { x: 155.5; y: 17.5; width: 29; height: 29; visible: root.on && root.spin === 8; source: root.base + "spin-all.png" }
    Seg { x: 166.5; y: 28.5; width: 7; height: 7; visible: root.on && root.spin >= 0; source: root.base + "i-disc.png" }

    Repeater {
        model: 16
        Seg {
            required property int index
            readonly property var cell: index < root.textShown.length ? root.textShown[index] : null
            readonly property string f: cell ? root.textGlyph(cell.c) : ""
            x: 8 + index * 11.25 - 1.5; y: 85 - 1.5; width: 12.47; height: 15
            visible: f !== ""
            source: f !== "" ? root.base + f : ""
        }
    }
    Repeater {
        model: 16
        Seg {
            required property int index
            x: 8 + index * 11.25 - 1.5; y: 85 - 1.5; width: 12.47; height: 15
            visible: index < root.textShown.length && root.textShown[index].dp
            source: root.base + "t-2e.png"
        }
    }

    Seg { anchors.fill: parent; source: root.base + "lcd-glass.png" }
}
