// Now Playing animation "CD changer": a late-90s champagne file-type
// CD changer seen from the front. Behind its smoked window the discs stand
// in a rotating file of 101 slots; each album has its own slot. A new album
// sends the disc in the drive back down into its slot, turns the file until
// the new album's disc (its artwork printed on the label) reaches the
// loader, and the loader lifts it up into the drive, the LEDs lighting the
// empty slot. The fluorescent display counts the slots going past, then
// shows disc, track and time. The keys work: standby, play/pause, stop,
// skip (held: search), open/close and unload (the disc goes back into the
// file until play), random, repeat, and the level knob is the volume.
//
// The albums loaded from the albums view "CD changer" (ChangerView.qml) are
// `discs`: disc 1, 2, 3... in the order they were chosen, each with its
// artwork on the label; any other album gets a slot of its own among the
// rest.
//
// A pure scene (no Hifi imports) driven by NpAnimation.qml, like the others;
// the images are built by tools/np-anim/changer.py, whose geometry constants
// are mirrored below.
//
// 🚨 Weak iGPU, 24/7: the file turns and the loader moves only while a disc
// changes; playing, only the seconds change. Paused, stopped, hidden or
// previewed the scene is idle.
import QtQuick
import QtQuick.Effects

Item {
    id: root
    property url assetsBase
    property real devScale: 1
    property bool live: true
    property bool active: false
    property bool playing: false
    property bool hasTrack: false
    property real progress: 0
    property string artwork: ""
    property string mediaKey: ""
    property string title: ""
    property string subtitle: ""
    property bool power: true
    property int volume: -1
    property bool volumeFixed: false
    property real elapsed: 0
    property int trackIndex: -1
    property int trackTotal: 0
    property int repeatMode: 0
    property int shuffleMode: 0
    // the albums loaded in the changer, disc 1 first: [{ key, art }], key as
    // mediaKey (NpAnimation.albumKey)
    property var discs: []
    signal action(string name, var value)

    // ── design: 600 x 260 points, scaled uniformly and centred ─────────────
    readonly property real s: Math.max(0.01, Math.min(width / 600, height / 260))
    readonly property real texScale: devScale * (s > 0.9 ? 0.9 + 0.15 * Math.ceil((s - 0.9) / 0.15) : Math.ceil(s * 8) / 8)
    function px(v) { return Math.max(1, Math.round(v * root.texScale)) }

    // changer.py: GLASS, LOADER_X, DISC_D, KEYS, ROUND, KNOB
    readonly property var glass: [127, 25.5, 344, 187.5]
    readonly property real winW: glass[2] - glass[0]
    readonly property real winH: glass[3] - glass[1]
    readonly property real loaderX: 255.5 - glass[0]          // in the window
    readonly property real axisX: winW / 2                    // the file's axis
    readonly property real radius: 190                       // to the discs' centres
    readonly property real discD: 128
    readonly property real discY: 94                         // their centres, at rest
    readonly property real eyeY: 80
    readonly property real focal: 520
    readonly property real liftTravel: 150
    readonly property int slots: 101
    readonly property real pitch: 360 / slots
    readonly property real loaderPhi: Math.asin((loaderX - axisX) / radius) * 180 / Math.PI
    readonly property int places: 37                         // discs drawn: those within sight

    readonly property var keys: ({
        power: [34, 119.5, 64, 134.5], access: [37.5, 167, 66.5, 181], slplay: [69.5, 167, 98.5, 181],
        random: [447.5, 112, 483.5, 121], repeat: [447.5, 131, 483.5, 140],
        best: [495, 112, 531, 121], previous: [533, 112, 569.5, 121],
        discm: [495, 131, 530, 140], discp: [532.5, 131, 568.5, 140],
        eject: [371, 169.5, 401, 184.5], unload: [404, 169.5, 434, 184.5],
        play: [445, 165.5, 489, 185.5], stop: [491.5, 165.5, 514.5, 185.5],
        prev: [517, 165.5, 539.5, 185.5], next: [542, 165.5, 564.5, 185.5],
        mode: [383.3, 110.3, 391.7, 118.7], hilite: [410.8, 110.3, 419.2, 118.7],
        clear: [383.3, 129.8, 391.7, 138.2], program: [410.8, 129.8, 419.2, 138.2]
    })
    readonly property var keyNames: ["power", "access", "slplay", "random", "repeat", "best", "previous", "discm", "discp",
                                     "eject", "unload", "play", "stop", "prev", "next", "mode", "hilite", "clear", "program"]
    readonly property var knob: [548, 227.5]

    // ── the mechanism ──────────────────────────────────────────────────────
    // drumAngle: the file's turn, in degrees; slot n is at the loader when
    // drumAngle is n * pitch (plus whole turns)
    property real drumAngle: 0
    property int atSlot: 0                   // the slot at the loader (file at rest)
    property real lift: 0                    // the loader: 0 the disc in its slot .. 1 in the drive
    property int outSlot: -1                 // the disc the loader holds
    property string outKey: ""               // ... and the album it is
    property int artSlot: -1                 // the disc printed with the artwork
    property string artUrl: ""
    property bool turning: false
    property bool moving: false              // lifting or putting back
    property bool ejected: false             // open/close or unload: back in the file until play
    property string word: ""                 // the display's word during the moves

    readonly property bool busy: turning || moving

    // each album its own slot: the loaded discs in order, then any other
    // album always in the same place among the slots left
    function discIndex(key) {
        for (var i = 0; i < discs.length; i++) if (discs[i] && discs[i].key === key) return i
        return -1
    }
    function slotFor(key) {
        var d = discIndex(key)
        if (d >= 0) return d
        var h = 7
        for (var i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) % 1000003
        var free = slots - Math.min(discs.length, slots - 1)
        return slots - free + h % free
    }
    // the artwork printed on a slot's disc: a loaded album's, or the album
    // playing when it is none of those
    function artFor(no) {
        if (no < discs.length) return discs[no] ? discs[no].art || "" : ""
        return no === artSlot ? artUrl : ""
    }
    function stopAll() {
        turnAnim.stop(); liftAnim.stop()
        turning = false; moving = false
    }
    function pose() {
        stopAll()
        atSlot = 36; drumAngle = 36 * pitch
        outSlot = 36; outKey = ""; artSlot = -1; artUrl = ""
        lift = 0.42; word = ""
    }
    function sync() {
        if (!live) { pose(); return }
        if (!active) {
            // off screen: the disc goes back, the file stays where it is
            stopAll()
            lift = 0; outSlot = -1; outKey = ""; word = ""
            return
        }
        Qt.callLater(step)
    }
    // one move at a time; each one's end comes back here
    function step() {
        if (!live || !active || busy) return
        var want = power && hasTrack && !ejected && mediaKey !== ""
        var tgt = want ? slotFor(mediaKey) : -1
        if (lift > 0.0001 && (!want || outKey !== mediaKey || outSlot !== tgt)) {
            word = "UnLd"
            moving = true
            liftAnim.to = 0
            liftAnim.duration = Math.round(1400 * lift)
            liftAnim.start()
            return
        }
        if (lift <= 0.0001) { outSlot = -1; outKey = "" }
        if (tgt < 0) { word = ""; return }
        if (artSlot !== tgt) { artSlot = tgt; artUrl = artwork }
        if (atSlot !== tgt) {
            var fwd = ((tgt - atSlot) % slots + slots) % slots
            var n = fwd <= 60 ? fwd : fwd - slots            // the target comes in from the right, mostly
            word = ""
            turning = true
            turnAnim.from = drumAngle
            turnAnim.to = drumAngle + n * pitch
            turnAnim.duration = Math.min(3800, 700 + 42 * Math.abs(n))
            turnAnim.target_ = tgt
            turnAnim.start()
            return
        }
        if (lift < 0.9999) {
            outSlot = tgt; outKey = mediaKey
            word = "LOAd"
            moving = true
            liftAnim.to = 1
            liftAnim.duration = Math.round(1700 * (1 - lift))
            liftAnim.start()
            return
        }
        word = ""
    }
    onMediaKeyChanged: if (live) Qt.callLater(step)
    onDiscsChanged: if (live) Qt.callLater(step)        // a new load: the album may sit elsewhere now
    onHasTrackChanged: if (live) Qt.callLater(step)
    onPowerChanged: if (live) Qt.callLater(step)
    onActiveChanged: sync()
    onLiveChanged: sync()
    onPlayingChanged: if (live && playing && ejected) { ejected = false; Qt.callLater(step) }
    onArtworkChanged: if (live && artSlot >= 0 && artSlot === slotFor(mediaKey) && (lift <= 0.0001 || outKey === mediaKey)) artUrl = artwork
    Component.onCompleted: sync()

    NumberAnimation {
        id: turnAnim
        property int target_: 0
        target: root; property: "drumAngle"
        easing.type: Easing.InOutQuad
        onFinished: {
            root.atSlot = target_
            root.drumAngle = target_ * root.pitch
            root.turning = false
            Qt.callLater(root.step)
        }
    }
    NumberAnimation {
        id: liftAnim
        target: root; property: "lift"
        easing.type: Easing.InOutSine
        onFinished: {
            root.moving = false
            if (root.lift <= 0.0001) { root.outSlot = -1; root.outKey = "" }
            root.word = ""
            Qt.callLater(root.step)
        }
    }

    // the LEDs at the loader: lit while it holds a disc, blinking while the
    // file turns
    property bool blink: true
    Timer {
        interval: 280; repeat: true
        running: root.live && root.active && root.turning
        onTriggered: root.blink = !root.blink
        onRunningChanged: root.blink = true
    }
    readonly property bool ledsOn: !live || (power && (lift > 0.0001 || (turning && blink) || moving))

    // ── the display ────────────────────────────────────────────────────────
    readonly property int passing: ((Math.round(drumAngle / pitch) % slots) + slots) % slots
    function pad(n, w, c) { var t = String(n); while (t.length < w) t = c + t; return t }
    readonly property bool loaded: lift >= 0.9999 && !moving && outKey !== "" && outKey === mediaKey
    readonly property bool timeShown: !live || (loaded && hasTrack && word === "")
    // nine cells: disc (3), track (2), minutes, seconds
    readonly property string cells: {
        if (!live) return " 37" + "03" + "0247"
        if (!power) return ""
        var disc = turning ? passing : outSlot >= 0 ? outSlot : atSlot
        var d = pad(disc + 1, 3, " ")
        if (turning) return d + "--" + "    "
        if (word !== "") return d + "--" + word
        if (timeShown) {
            var t = Math.max(0, Math.floor(elapsed))
            return d + pad(Math.max(1, trackIndex + 1) % 100, 2, "0") + pad(Math.min(99, Math.floor(t / 60)), 2, "0") + pad(t % 60, 2, "0")
        }
        return d + "--" + "    "
    }
    function glyph(ch) {
        if (ch === "O") return "0"
        if (ch >= "0" && ch <= "9") return ch
        if (ch === "-") return "dash"
        return (ch === ch.toUpperCase() ? "u" : "l") + ch.toLowerCase()
    }
    readonly property var cellX: [446, 453, 460, 476, 483, 501, 508, 519, 526]

    component Pic: Image {
        smooth: true
        asynchronous: true
        sourceSize.width: root.px(width)
        sourceSize.height: root.px(height)
    }

    // the label's printable ring: one mask for every disc (all the same size)
    Pic {
        id: printMask
        width: root.discD; height: root.discD
        visible: false
        source: root.assetsBase + "disc-mask.png"
        layer.enabled: true
        layer.smooth: true
        layer.textureSize: Qt.size(root.px(root.discD), root.px(root.discD))
    }
    // an album's artwork printed on a disc's label, with the clear hub and rim
    // over it. 🚨 Two images (see Cover.qml): a new artwork loads hidden while
    // the one before stays.
    component DiscArt: Item {
        id: da
        property string url: ""
        readonly property bool ready: artImg.status === Image.Ready || artPrev.status === Image.Ready
        Image {
            id: artPrev
            anchors.fill: parent
            visible: false
            asynchronous: false
            smooth: true
            fillMode: Image.PreserveAspectCrop
            sourceSize.width: root.px(root.discD); sourceSize.height: root.px(root.discD)
            layer.enabled: true
            layer.smooth: true
        }
        Image {
            id: artImg
            anchors.fill: parent
            visible: false
            asynchronous: true
            smooth: true
            fillMode: Image.PreserveAspectCrop
            source: da.url
            sourceSize.width: root.px(root.discD); sourceSize.height: root.px(root.discD)
            layer.enabled: true
            layer.smooth: true
            onStatusChanged: if (status === Image.Ready) artPrev.source = source
        }
        MultiEffect {
            anchors.fill: parent
            source: artImg.status === Image.Ready ? artImg : artPrev
            visible: da.ready
            maskEnabled: true
            maskSource: printMask
            maskThresholdMin: 0.5
            maskSpreadAtMin: 1.0
        }
        Pic {
            anchors.fill: parent
            visible: da.ready
            source: root.assetsBase + "disc-gloss.png"
        }
    }

    Item {
        id: stage
        width: 600; height: 260
        x: (root.width - 600 * root.s) / 2
        y: (root.height - 260 * root.s) / 2
        scale: root.s
        transformOrigin: Item.TopLeft
        visible: base.status === Image.Ready

        // ── behind the glass ───────────────────────────────────────────────
        Item {
            id: win
            x: root.glass[0]; y: root.glass[1]
            width: root.winW; height: root.winH
            clip: true

            Pic { anchors.fill: parent; source: root.assetsBase + "interior.png" }
            // the LEDs light the back of the cabinet and the empty slot
            Pic {
                x: root.loaderX - 32; y: 123.5 - root.glass[1] - 32; width: 64; height: 64
                source: root.assetsBase + "led-glow.png"
                visible: root.ledsOn
            }
            Pic {
                x: root.loaderX - 4; y: 111 - root.glass[1]; width: 8; height: 26
                source: root.assetsBase + "led-dots.png"
                visible: root.ledsOn
            }

            // the file: the discs within sight of the window, nearest on top.
            // Each of the 37 places keeps the same disc while it is in view (the
            // nearest slot congruent to its index), so a step of the file moves
            // one place from one end to the other and no artwork reloads.
            Item {
                id: file
                anchors.fill: parent
                Repeater {
                    model: root.places
                    Item {
                        id: slot
                        required property int index
                        readonly property int base: Math.round(root.drumAngle / root.pitch) - (root.places - 1) / 2
                        readonly property int n: base + (((index - base) % root.places) + root.places) % root.places
                        readonly property int no: ((n % root.slots) + root.slots) % root.slots
                        readonly property real phi: n * root.pitch - root.drumAngle + root.loaderPhi
                        readonly property real rad: phi * Math.PI / 180
                        readonly property real sc: root.focal / (root.focal + root.radius * (1 - Math.cos(rad)))
                        readonly property real side: Math.abs(Math.sin(rad))
                        readonly property bool out: no === root.outSlot
                        readonly property real up: out ? root.lift * root.liftTravel : 0
                        readonly property real cx: root.axisX + root.radius * Math.sin(rad) * sc
                        readonly property real cy: root.eyeY + (root.discY - root.eyeY) * sc - up * sc
                        // the album printed on this disc's label, if it is one we know
                        readonly property string art: root.artFor(no)
                        visible: Math.abs(phi) < 62
                        z: 100 - Math.abs(phi)
                        // the face: the labels look right, the shiny sides left
                        Item {
                            x: slot.cx - root.discD / 2; y: slot.cy - root.discD / 2
                            width: root.discD; height: root.discD
                            visible: slot.side > 0.02
                            transform: Scale {
                                origin.x: root.discD / 2; origin.y: root.discD / 2
                                xScale: slot.side * slot.sc; yScale: slot.sc
                            }
                            Pic {
                                anchors.fill: parent
                                sourceSize.width: root.px(root.discD); sourceSize.height: root.px(root.discD)
                                source: root.assetsBase + (slot.phi < 0 ? "disc-data.png" : "disc-lbl-" + ((slot.no * 7 + 3) % 10) + ".png")
                            }
                            // the artwork, cut to the printable ring (only on discs
                            // that have one: the masking costs a pass each)
                            Loader {
                                anchors.fill: parent
                                active: slot.art !== "" && slot.phi >= 0
                                sourceComponent: DiscArt { url: slot.art }
                            }
                        }
                        // its edge, edge-on
                        Rectangle {
                            x: slot.cx - 0.75 * slot.sc; y: slot.cy - root.discD / 2 * slot.sc
                            width: 1.5 * slot.sc; height: root.discD * slot.sc
                            radius: width / 2
                            color: "#9aa1a8"
                            opacity: Math.max(0, 1 - slot.side * 9)
                            visible: opacity > 0.01
                        }
                    }
                }
            }

            // the drive's housing up top: the lifted disc goes in behind it
            Item {
                width: parent.width; height: 16.2
                clip: true
                Pic { width: root.winW; height: root.winH; source: root.assetsBase + "interior.png" }
            }
            // the turntable's rim across the bottom: the discs stand in it
            Pic { x: 0; y: 140; width: root.winW; height: root.winH - 140; source: root.assetsBase + "lip.png" }
            // a little of the LEDs' light on the discs' edges
            Pic {
                x: root.loaderX - 32; y: 123.5 - root.glass[1] - 32; width: 64; height: 64
                source: root.assetsBase + "led-glow.png"
                visible: root.ledsOn
                opacity: 0.35
            }
            Pic { anchors.fill: parent; source: root.assetsBase + "glass.png" }
        }

        Pic { id: base; width: 600; height: 260; source: root.assetsBase + "base.png" }

        Pic {
            x: 30; y: 99.5; width: 36; height: 10
            source: root.assetsBase + "led-standby.png"
            visible: root.live && !root.power
        }

        // ── the fluorescent display ────────────────────────────────────────
        Item {
            visible: !root.live || root.power
            Pic { x: 375; y: 41; width: 197; height: 57.5; source: root.assetsBase + "vfd-panel.png" }
            Repeater {
                model: 9
                Pic {
                    required property int index
                    readonly property string ch: root.cells.length === 9 ? root.cells.charAt(index) : " "
                    x: root.cellX[index] - 1; y: 59; width: 8; height: 12
                    visible: ch !== " "
                    source: ch === " " ? "" : root.assetsBase + "g-" + root.glyph(ch) + ".png"
                }
            }
            Pic { x: 514.5; y: 59; width: 3; height: 12; source: root.assetsBase + "g-colon.png"; visible: root.timeShown }
            Pic {
                x: 444.5; y: 72.4; width: 6.5; height: 6.5; source: root.assetsBase + "ind-play.png"
                visible: root.timeShown && (root.playing || !root.live)
            }
            Pic {
                x: 451.5; y: 72.4; width: 6.5; height: 6.5; source: root.assetsBase + "ind-pause.png"
                visible: root.timeShown && root.live && !root.playing && root.elapsed > 0
            }
            Pic { x: 499; y: 73.6; width: 12.83; height: 4.17; source: root.assetsBase + "ind-repeat.png"; visible: root.repeatMode > 0 || !root.live }
            Pic { x: 512; y: 73.6; width: 7.33; height: 4.17; source: root.assetsBase + "ind-all.png"; visible: root.repeatMode === 2 || !root.live }
            Pic { x: 512; y: 73.5; width: 3.67; height: 4.33; source: root.assetsBase + "ind-one.png"; visible: root.live && root.repeatMode === 1 }
            Pic { x: 521; y: 73.6; width: 14.17; height: 4.17; source: root.assetsBase + "ind-random.png"; visible: root.live && root.shuffleMode > 0 }
        }

        // ── the level knob: the volume ─────────────────────────────────────
        Pic {
            id: knobPic
            x: root.knob[0] - 7.4; y: root.knob[1] - 7.4; width: 14.8; height: 14.8
            source: root.assetsBase + "knob.png"
            rotation: -135 + 270 * (knobArea.level >= 0 ? knobArea.level : root.volume >= 0 ? root.volume : 40) / 100
            opacity: root.live && root.volumeFixed ? 0.6 : 1
        }
        MouseArea {
            id: knobArea
            x: root.knob[0] - 12; y: root.knob[1] - 12; width: 24; height: 24
            enabled: root.live && !root.volumeFixed && root.volume >= 0 && root.power
            property int level: -1
            property real fromY: 0
            property int fromLevel: 0
            onPressed: (m) => { fromY = m.y; fromLevel = root.volume; level = root.volume }
            onPositionChanged: (m) => {
                var v = Math.max(0, Math.min(100, Math.round(fromLevel + (fromY - m.y) * 2.5)))
                if (v === level) return
                level = v
                root.action("volume", { level: v, final: false })
            }
            onReleased: { if (level >= 0) root.action("volume", { level: level, final: true }); level = -1 }
            onCanceled: level = -1
            onWheel: (w) => {
                var v = Math.max(0, Math.min(100, root.volume + (w.angleDelta.y > 0 ? 2 : -2)))
                if (v !== root.volume) root.action("volume", { level: v, final: true })
            }
        }

        // ── the keys: a press darkens the cap for a moment ────────────────
        Repeater {
            model: root.keyNames
            Item {
                id: key
                required property string modelData
                readonly property var r: root.keys[modelData]
                readonly property bool round: ["mode", "hilite", "clear", "program"].indexOf(modelData) >= 0
                readonly property bool skip: modelData === "prev" || modelData === "next"
                x: r[0]; y: r[1]; width: r[2] - r[0]; height: r[3] - r[1]
                Rectangle {
                    anchors.fill: parent
                    radius: key.round ? width / 2 : 0.9
                    color: "black"
                    opacity: kArea.pressed ? 0.28 : 0
                }
                MouseArea {
                    id: kArea
                    anchors.fill: parent
                    anchors.margins: key.round ? -2 : -1.5
                    enabled: root.live
                    onPressed: if (key.skip) root.skipStart(key.modelData === "next" ? 1 : -1, kArea)
                    onReleased: if (key.skip) root.skipEnd(true)
                    onCanceled: if (key.skip) root.skipEnd(false)
                    onClicked: if (!key.skip) root.press(key.modelData)
                }
            }
        }
    }

    // ⏮ / ⏭: a touch skips, held they search (NpAnimation's "wind")
    property int skipDir: 0
    property var skipArea: null
    property bool searching: false
    function skipStart(dir, area) {
        if (!power) return
        skipDir = dir; skipArea = area; searching = false
        holdTimer.restart()
    }
    function skipEnd(released) {
        if (skipDir === 0) return
        holdTimer.stop()
        if (searching) root.action("windStop", true)
        else if (released) root.action(skipDir > 0 ? "next" : "prev", true)
        skipDir = 0; skipArea = null; searching = false
    }
    Timer {
        id: holdTimer
        interval: 450
        onTriggered: {
            if (!root.skipArea || !root.skipArea.pressed || !root.loaded) return
            root.searching = true
            root.action("wind", root.skipDir)
        }
    }
    Timer {
        interval: 350; repeat: true
        running: root.live && root.active && root.searching
        // 🚨 never on by itself: a release that got lost stops it here
        onTriggered: {
            if (!root.skipArea || !root.skipArea.pressed) { root.skipEnd(false); return }
            root.action("wind", root.skipDir)
        }
    }

    function press(k) {
        if (k === "power") { root.action("power", !power); return }
        if (!power) return
        if (k === "play" || k === "slplay") {
            if (ejected || !playing) { ejected = false; Qt.callLater(step); root.action("play", true) }
            else root.action("pause", true)
        }
        else if (k === "stop") root.action("stop", true)
        else if (k === "eject" || k === "unload") {
            if (k === "eject" && ejected) { ejected = false; Qt.callLater(step); return }
            ejected = true
            root.action("stop", true)
            Qt.callLater(step)
        }
        else if (k === "random") root.action("random", true)
        else if (k === "repeat") root.action("repeat", true)
    }
}
