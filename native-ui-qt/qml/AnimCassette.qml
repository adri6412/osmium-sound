// Now Playing animation "Cassette": the front of a cassette deck. The door
// tilts open, a cassette slides down into its holder, the door closes and,
// through the smoked window, the reels turn while playing: the tape moves
// from the left pack to the right one as the track goes on.
//
// A pure scene (no Hifi imports) driven by NpAnimation.qml; the images are
// built by tools/np-anim/cassette.py, whose geometry constants are mirrored
// below. The album title and artist on the label are live text.
//
// The deck's controls work: the transport keys, eject (the cassette comes
// out and stays out until PLAY or playback from elsewhere), the volume
// fader and the power key. The scene only reports them through
// action(name, value); the host (NpAnimation.qml) talks to the player.
//
// 🚨 The kiosk runs on a weak iGPU, 24/7: nothing here loops. The reels (and
// the tape packs following the progress) are one 30 Hz Timer that runs only
// while they turn (playing, or slowing down after a pause); the door, the
// cassette, the label and the keys are bounded animations. Paused, stopped,
// hidden or previewed, the scene is fully idle. Never animate on `progress`
// with a Behavior: the player moves it every half second, so an animation
// restarted on each change never ends and keeps the screen at 60 fps.
import QtQuick

Item {
    id: root
    property url assetsBase              // folder with the scene's PNGs, trailing slash
    property real devScale: 1
    property bool live: true             // false: still preview, final pose, nothing ever runs
    property bool active: false          // on screen now; false resets to "no cassette"
    property bool playing: false
    property bool hasTrack: false
    property real progress: 0            // 0..1 (0 when unknown, e.g. radio)
    property string artwork: ""          // album artwork URL; "" = no picture on the label
    property string mediaKey: ""         // a new value swaps the cassette
    property string title: ""            // album (or track) title, written on the label
    property string subtitle: ""         // artist
    // the deck's controls (optional: without them the display still works)
    property int volume: -1              // 0..100, -1 unknown
    property bool volumeFixed: false     // the volume is not ours to change (fader disabled)
    property bool power: true            // the player is on

    // A key or the fader was used: "prev", "play", "pause", "stop", "next",
    // "eject" (value undefined), "volume" (value {level, final}), "power"
    // (value: the wanted state). Never emitted by a still preview.
    signal action(string name, var value)
    // The tape LCD (LcdTape.qml): the counter follows the time, the level
    // meters this device's audio.
    property real elapsed: 0
    property real duration: 0            // seconds, 0 unknown (a stream)
    property string trackId: ""          // changes with the track
    property real levelL: 0
    property real levelR: 0

    // for tests: true while something moves
    readonly property bool ticking: spinTimer.running
    readonly property bool animating: insertAnim.running || removeAnim.running || closeAnim.running || labelSwap.running || packGlide.running

    // ── design: 520 x 260 points, scaled uniformly and centred ─────────────
    readonly property real s: Math.max(0.01, Math.min(width / 520, height / 260))
    // Images are decoded for the width, not the height: on Now Playing the
    // panel keeps its width and changes height with the title's lines, and a
    // new sourceSize would reload every image (at most 25 % above the shown size)
    readonly property real decodeScale: Math.min(width / 520, s * 1.25) * devScale
    function px(v) { return Math.max(1, Math.round(v * root.decodeScale)) }

    // ── geometry, base points, from tools/np-anim/cassette.py ──────────────
    readonly property real mm: 244 / 100.4             // points per millimetre of a cassette
    readonly property real casX: 47
    readonly property real casY: 32.5
    readonly property real casW: 244
    readonly property real casH: 63.8 * mm
    readonly property real hubY: 31 * mm
    readonly property real hubLX: 28.95 * mm
    readonly property real hubRX: 71.45 * mm
    readonly property real hubR: 10.75 * mm            // an empty pack is the bare hub
    readonly property real packR: 22 * mm              // a full pack
    readonly property real winH: 8.6 * mm              // half height of the label's window
    readonly property real doorX: 18.5
    readonly property real doorY: 15.5
    readonly property real doorW: 301
    readonly property real doorH: 195
    readonly property real doorEdge: 6                 // thickness: its top face shows when open
    readonly property real hingeY: doorY + doorH
    readonly property real openAngle: 34               // degrees the door tilts forward
    readonly property real slide: 62                   // points the cassette travels into the holder

    // ── choreography state ─────────────────────────────────────────────────
    // phase: 0 empty (door closed or closing), 1 inserting, 2 loaded, 3 removing
    property int phase: 0
    property real doorOpen: 0                // 0 closed .. 1 tilted open
    property real casIn: 0                   // 0 lifted out of the holder .. 1 seated
    property real casA: 0                    // cassette opacity
    property real spinF: 0                   // reel speed, 0 .. 1 of the playing speed
    property real angL: 0                    // hub angles, degrees
    property real angR: 0
    property real packP: 0.5                 // tape on the right reel, 0 .. 1, as drawn
    property real packTarget: 0.5            // ... as the progress says
    property real tapeF: 1                   // the tape on the cassette, 0 .. 1 of a full pack, as drawn
    // A new track while winding: the packs first finish the old one (all the
    // tape across: 1 winding forward, 0 back), then move to the new track's
    // position (wrapNext). -1: no such detour.
    property real wrapTo: -1
    property real wrapNext: 0
    property int gapDur: 0
    property int doorDur: 0
    property int holdDur: 0
    property int outDur: 0
    // what the cassette in the deck carries
    property string loadedKey: ""
    property string labelTitle: ""
    property string labelSub: ""
    property string labelArt: ""
    property real labelA: 1

    // tape packs: the tape moves from the left reel to the right one; the
    // area of the two packs together stays the same. A track is the whole
    // tape: at its start all of it is on the left reel, at its end all of it
    // on the right one (fast wind included, see wrapTo).
    // How much tape there is grows with the track: a short song is a thin
    // pack (40 % of a full one), from half an hour on the cassette is full.
    // Unknown (a stream): a full cassette.
    readonly property real tapeTarget: duration > 0 ? Math.min(1, 0.4 + 0.6 * duration / 1800) : 1
    readonly property real rL: Math.sqrt(hubR * hubR + (1 - packP) * tapeF * (packR * packR - hubR * hubR))
    readonly property real rR: Math.sqrt(hubR * hubR + packP * tapeF * (packR * packR - hubR * hubR))
    // constant tape speed, 47.6 mm/s: a reel turns faster the smaller its
    // pack (degrees per second, r in points)
    function omega(r) { return 47.6 * mm / r * 180 / Math.PI }

    // Fast wind: holding ◀◀ or ▶▶ (a tap still skips a track) winds the tape
    // for as long as the key is held: the reels race (backwards for rewind)
    // and the scene asks NpAnimation for a jump every 350 ms ("wind", +1/-1),
    // which crosses into the next or previous track at either end.
    property int windDir: 0
    property var windArea: null              // the key being held
    Timer {
        interval: 350; repeat: true
        running: root.live && root.active && root.windDir !== 0
        // 🚨 never wind on by itself: a release that got lost (a grab taken
        // away, an interrupted touch) must not leave the tape racing
        onTriggered: {
            if (!root.windArea || !root.windArea.pressed) { root.windStop(); return }
            root.action("wind", root.windDir)
        }
    }
    readonly property bool wantSpin: live && active && phase === 2 && (playing || windDir !== 0) && hasTrack && power
    property real spinFrom: 0
    property real spinTo: 0
    property real spinDur: 800
    property double spinT0: 0
    property double lastT: 0

    onWantSpinChanged: {
        spinFrom = spinF
        spinTo = wantSpin ? 1 : 0
        spinDur = phase === 3 ? 350 : 800
        spinT0 = Date.now()
    }

    // The only continuous motion: turns the hubs by real elapsed time.
    Timer {
        id: spinTimer
        interval: 33
        repeat: true
        running: root.live && root.active && (root.wantSpin || root.spinF > 0)
        onRunningChanged: {
            if (running) { root.lastT = Date.now(); packGlide.stop() }
            else root.settlePacks()
        }
        onTriggered: root.tick()
    }
    function tick() {
        var now = Date.now()
        var dt = Math.min(0.1, Math.max(0, (now - lastT) / 1000))
        lastT = now
        var u = Math.min(1, Math.max(0, (now - spinT0) / spinDur))
        var e = u * u * (3 - 2 * u)
        var f = spinFrom + (spinTo - spinFrom) * e
        var k = (spinF + f) * 0.5 * dt
        // Playing, the tape runs left to right along the open bottom edge,
        // past the heads: off the left pack, onto the right one. Seen from
        // the front both reels turn counterclockwise (a negative rotation).
        // Winding is six times faster, held under 1300 degrees a second: at
        // 30 frames a second a hub (six spokes) turning faster would seem to
        // slow down or go backwards.
        var w = windDir > 0 ? 6 : windDir < 0 ? -6 : 1
        var a = angL - k * Math.max(-1300, Math.min(1300, w * omega(rL)))
        var b = angR - k * Math.max(-1300, Math.min(1300, w * omega(rR)))
        angL = a - 360 * Math.floor(a / 360)
        angR = b - 360 * Math.floor(b / 360)
        spinF = (u >= 1 && spinTo === 0) ? 0 : f
        // the packs follow the progress smoothly (a new track: a quick glide)
        var g = packTarget - packP
        if (g !== 0) packP = Math.abs(g) < 0.004 ? packTarget : packP + g * (1 - Math.exp(-dt / 0.28))
        if (wrapTo >= 0) {
            if (packP !== wrapTo) return                    // the old track's tape still going across
            wrapTo = -1
            packTarget = wrapNext
        }
        var h = tapeTarget - tapeF
        if (h !== 0) tapeF = Math.abs(h) < 0.0005 ? tapeTarget : tapeF + h * (1 - Math.exp(-dt / 0.28))
    }
    // the reels stopped with the packs not where they should be (a seek while
    // paused, a pause right after a new track): one bounded glide
    function settlePacks() {
        if (wrapTo >= 0) { wrapTo = -1; packTarget = wrapNext }  // standing still: no detour
        var d = Math.max(Math.abs(packTarget - packP), Math.abs(tapeTarget - tapeF))
        if (!live || !active || phase !== 2 || d < 0.002) {
            packGlide.stop()
            packP = packTarget
            tapeF = tapeTarget
            return
        }
        packAnim.to = packTarget
        tapeAnim.to = tapeTarget
        packGlide.dur = Math.round(300 + 600 * Math.min(1, d * 4))
        packGlide.restart()
    }
    ParallelAnimation {
        id: packGlide
        property int dur: 300
        NumberAnimation { id: packAnim; target: root; property: "packP"; duration: packGlide.dur; easing.type: Easing.InOutQuad }
        NumberAnimation { id: tapeAnim; target: root; property: "tapeF"; duration: packGlide.dur; easing.type: Easing.InOutQuad }
    }

    function stopAll() {
        insertAnim.stop(); removeAnim.stop(); closeAnim.stop()
    }
    // the cassette that goes in: its label and how far its tape is wound
    function takeMedia() {
        labelSwap.stop()
        labelA = 1
        labelTitle = title
        labelSub = subtitle
        if (labelArt !== artwork) { artPrev.source = ""; labelArt = artwork }
        loadedKey = mediaKey
        packGlide.stop()
        packTarget = progress > 0 ? Math.min(1, progress) : 0.5     // unknown (a radio): half and half
        packP = packTarget
        tapeF = tapeTarget
        wrapTo = -1
    }
    // hidden: back to an empty, closed deck, so the next appearance replays
    // the insertion
    function reset() {
        stopAll()
        phase = 0; doorOpen = 0; casIn = 0; casA = 0; spinF = 0
        takeMedia()
    }
    // the still preview: loaded, door closed, the reels part way through
    function pose() {
        stopAll()
        phase = 2; doorOpen = 0; casIn = 1; casA = 1; spinF = 0
        takeMedia()
        angL = 16; angR = 47; packTarget = 0.35; packP = 0.35; tapeF = 1
    }
    // Compares what is in the deck with what should be there. Called late
    // (Qt.callLater) so that inputs changing together, e.g. hasTrack and then
    // mediaKey for the same new album, lead to one decision.
    function sync() {
        if (!live) { pose(); return }
        if (!active) { reset(); return }
        if (wantMedia) {
            if (phase === 0) {
                insert(0)
            } else if ((phase === 1 || phase === 2) && mediaKey !== loadedKey) {
                // a new album: out with the old cassette (its label goes with
                // it), in with the new one; one not yet in sight is just swapped
                if (phase === 1 && casA === 0) takeMedia()
                else remove()
            }
        } else if (phase === 1 || phase === 2) {
            remove()
        }
    }
    function insert(gap) {
        stopAll()
        takeMedia()
        phase = 1
        casIn = 0; casA = 0
        gapDur = gap
        doorDur = Math.round(460 * (1 - doorOpen))
        insertAnim.start()
    }
    function remove() {
        stopAll()
        labelSwap.stop(); labelA = 1
        holdDur = spinF > 0 ? 160 : 0
        phase = 3
        doorDur = Math.round(380 * (1 - doorOpen))
        outDur = Math.round(400 * casIn)
        removeAnim.start()
    }
    function removed() {
        if (active && wantMedia) {
            insert(90)
        } else {
            phase = 0
            closeAnim.start()
        }
    }
    // ── the controls ───────────────────────────────────────────────────────
    // Eject takes the cassette out and it stays out until PLAY is pressed or
    // playback starts from anywhere else. The stop that eject asks for comes
    // back with the next status: until then `playing` is still true and must
    // not count as "playback started" (a give-up after 4 s, if it never does).
    property bool ejected: false
    property bool ejectWait: false
    readonly property bool wantMedia: hasTrack && !ejected
    Timer {
        id: ejectGiveUp
        interval: 4000
        onTriggered: { root.ejectWait = false; if (root.playing) root.ejected = false }
    }
    onPlayingChanged: {
        if (!playing) { ejectWait = false; ejectGiveUp.stop() }
        else if (ejected && !ejectWait) ejected = false
    }
    onEjectedChanged: Qt.callLater(sync)
    // A press is never dropped: during an insertion or a removal the state
    // above changes and sync() takes it from there when the move ends.
    function windStop() {
        windArea = null
        if (windDir === 0) return
        windDir = 0
        action("windStop", true)
    }
    function press(name) {
        if (!live) return
        if (name === "eject") {
            if (!ejected) { ejectWait = playing; ejected = true; if (playing) ejectGiveUp.restart() }
        } else if (name === "play") {
            ejectGiveUp.stop(); ejectWait = false; ejected = false
        }
        action(name, name === "power" ? !power : undefined)
    }

    onMediaKeyChanged: Qt.callLater(sync)
    onActiveChanged: Qt.callLater(sync)
    onHasTrackChanged: Qt.callLater(sync)
    onLiveChanged: Qt.callLater(sync)
    onTitleChanged: Qt.callLater(applyLabel)
    onSubtitleChanged: Qt.callLater(applyLabel)
    onArtworkChanged: Qt.callLater(applyArt)
    // (hidden or empty, nothing is loaded: insert() takes the label of the moment)
    function applyLabel() {
        if (!live) { labelTitle = title; labelSub = subtitle; return }
        if (!active || phase === 0 || phase === 3 || mediaKey !== loadedKey) return
        if (labelTitle === title && labelSub === subtitle) return
        // same cassette, new words (a radio's song): a short fade, not a pop
        if (phase === 2) labelSwap.restart()
        else { labelTitle = title; labelSub = subtitle }
    }
    function applyArt() {
        if (!live || (active && phase !== 0 && phase !== 3 && mediaKey === loadedKey)) labelArt = artwork
    }
    // On the loaded cassette the packs glide to the new position: tick()
    // does it while the reels turn, settlePacks() when they stand still.
    // While a cassette goes in they are set straight away; progress 0 (a
    // stop, a track that has not started) keeps them where they are.
    // a new track, the same cassette: its tape grows or shrinks the same way
    onTapeTargetChanged: {
        if (!live || phase === 3) return
        if (phase !== 2 || !active) { packGlide.stop(); tapeF = tapeTarget }
        else if (!spinTimer.running) settlePacks()
    }
    // Winding into another track: first all the old track's tape across.
    // (Its progress may come before or after the new id: wrapNext takes the
    // latest one either way.)
    onTrackIdChanged: {
        if (!live || phase !== 2 || !active || windDir === 0 || !spinTimer.running) return
        wrapTo = windDir > 0 ? 1 : 0
        wrapNext = progress > 0 ? Math.min(1, progress) : packTarget
        if (windDir > 0 ? wrapNext > 0.5 : wrapNext < 0.5) wrapNext = 1 - wrapTo   // still the old track's
        packTarget = wrapTo
    }
    onProgressChanged: {
        if (!live || phase === 3 || !(progress > 0)) return
        if (wrapTo >= 0) { wrapNext = Math.min(1, progress); return }
        packTarget = Math.min(1, progress)
        if (phase !== 2 || !active) { packGlide.stop(); packP = packTarget }
        else if (!spinTimer.running) settlePacks()
    }
    Component.onCompleted: sync()

    SequentialAnimation {
        id: insertAnim
        PauseAnimation { duration: root.gapDur }
        NumberAnimation { target: root; property: "doorOpen"; to: 1; duration: root.doorDur; easing.type: Easing.OutCubic }
        PauseAnimation { duration: 70 }
        ParallelAnimation {
            NumberAnimation { target: root; property: "casIn"; to: 1; duration: 800; easing.type: Easing.OutCubic }
            NumberAnimation { target: root; property: "casA"; to: 1; duration: 200; easing.type: Easing.OutQuad }
        }
        PauseAnimation { duration: 130 }
        NumberAnimation { target: root; property: "doorOpen"; to: 0; duration: 400; easing.type: Easing.InCubic }
        NumberAnimation { target: root; property: "doorOpen"; to: 0.03; duration: 70; easing.type: Easing.OutQuad }
        NumberAnimation { target: root; property: "doorOpen"; to: 0; duration: 90; easing.type: Easing.InQuad }
        onFinished: root.phase = 2
    }
    SequentialAnimation {
        id: removeAnim
        PauseAnimation { duration: root.holdDur }
        NumberAnimation { target: root; property: "doorOpen"; to: 1; duration: root.doorDur; easing.type: Easing.OutCubic }
        ParallelAnimation {
            NumberAnimation { target: root; property: "casIn"; to: 0; duration: root.outDur; easing.type: Easing.InQuad }
            SequentialAnimation {
                PauseAnimation { duration: Math.round(root.outDur * 0.45) }
                NumberAnimation { target: root; property: "casA"; to: 0; duration: Math.round(root.outDur * 0.55); easing.type: Easing.InQuad }
            }
        }
        onFinished: root.removed()
    }
    SequentialAnimation {
        id: closeAnim
        NumberAnimation { target: root; property: "doorOpen"; to: 0; duration: 420; easing.type: Easing.InCubic }
        NumberAnimation { target: root; property: "doorOpen"; to: 0.03; duration: 70; easing.type: Easing.OutQuad }
        NumberAnimation { target: root; property: "doorOpen"; to: 0; duration: 90; easing.type: Easing.InQuad }
    }
    SequentialAnimation {
        id: labelSwap
        NumberAnimation { target: root; property: "labelA"; to: 0; duration: 160; easing.type: Easing.InQuad }
        ScriptAction { script: { root.labelTitle = root.title; root.labelSub = root.subtitle } }
        NumberAnimation { target: root; property: "labelA"; to: 1; duration: 220; easing.type: Easing.OutQuad }
    }

    // the keys, left to right: image name, action, key and touch area (x)
    readonly property var keys: [
        { name: "rew", action: "prev", x0: 16, x1: 62, h0: 0, h1: 65 },
        { name: "play", action: "play", x0: 68, x1: 114, h0: 65, h1: 117 },
        { name: "ff", action: "next", x0: 120, x1: 166, h0: 117, h1: 169 },
        { name: "stop", action: "stop", x0: 172, x1: 218, h0: 169, h1: 221 },
        { name: "pause", action: "pause", x0: 224, x1: 270, h0: 221, h1: 273 },
        { name: "eject", action: "eject", x0: 276, x1: 322, h0: 273, h1: 330 },
        { name: "power", action: "power", x0: 456, x1: 502, h0: 436, h1: 520 }
    ]

    // ── what the display, the PLAY key and the LED show ────────────────────
    readonly property bool loaded: !live || (phase === 2 && hasTrack && power)
    readonly property bool lit: !live || (loaded && playing)

    // An image placed in base points, decoded at the size it is shown at
    // (dw/dh: the decode size, when the shown size is not the image's own).
    // Nothing is loaded before the scene has a size (a Loader sizes it after
    // it completes): no 1 px decodes followed by the real ones.
    component Pic: Image {
        property string file
        property real dw: width
        property real dh: height
        source: root.width > 0 && root.height > 0 ? root.assetsBase + file : ""
        smooth: true
        asynchronous: true
        sourceSize.width: root.px(dw)
        sourceSize.height: root.px(dh)
    }

    Item {
        id: stage
        width: 520; height: 260
        x: (root.width - 520 * root.s) / 2
        y: (root.height - 260 * root.s) / 2
        scale: root.s
        transformOrigin: Item.TopLeft
        // all at once, not piece by piece while the images decode
        visible: deck.status === Image.Ready && door.status === Image.Ready && shell.status === Image.Ready

        Pic { id: deck; width: 520; height: 260; file: "deck.png" }

        // the door with the holder and the cassette in it, tilting forward on
        // its bottom hinge (Rotation about x projects with a perspective)
        Item {
            id: hinged
            width: 520; height: 260
            transform: Rotation {
                origin.x: root.doorX + root.doorW / 2
                origin.y: root.hingeY
                axis { x: 1; y: 0; z: 0 }
                angle: root.openAngle * root.doorOpen
            }
            readonly property real lift: root.slide * (1 - root.casIn)

            Pic {
                x: root.casX - 16
                y: root.casY - 16 - hinged.lift + 5 * (1 - root.casIn)
                width: root.casW + 32; height: root.casH + 32
                opacity: root.casA * (0.45 + 0.55 * root.casIn)
                visible: opacity > 0.002
                file: "cas-shadow.png"
            }

            Item {
                id: cassette
                x: root.casX
                y: root.casY - hinged.lift
                width: root.casW; height: root.casH
                opacity: root.casA
                visible: opacity > 0.002
                // flattened only while it fades, so it fades as one piece
                layer.enabled: root.casA > 0.002 && root.casA < 1
                layer.smooth: true
                layer.sourceRect: Qt.rect(-2, -2, width + 4, height + 4)     // with the soft edge of cas.png
                layer.textureSize: Qt.size(root.px(width + 4), root.px(height + 4))

                // behind the window: the slip sheet, the two packs, the hubs
                Pic {
                    x: root.hubLX - root.winH - 3; y: root.hubY - root.winH - 3
                    width: root.hubRX - root.hubLX + 2 * (root.winH + 3); height: 2 * (root.winH + 3)
                    file: "cas-back.png"
                }
                Pic {
                    x: root.hubLX - root.packR - 1; y: root.hubY - root.packR - 1
                    width: 2 * root.packR + 2; height: width
                    scale: root.rL / root.packR
                    mipmap: true            // down to half size: no shimmer in the fine rings
                    file: "pack.png"
                }
                Pic {
                    x: root.hubRX - root.packR - 1; y: root.hubY - root.packR - 1
                    width: 2 * root.packR + 2; height: width
                    scale: root.rR / root.packR
                    mipmap: true
                    file: "pack.png"
                }
                Pic {
                    x: root.hubLX - root.hubR - 1; y: root.hubY - root.hubR - 1
                    width: 2 * root.hubR + 2; height: width
                    rotation: root.angL
                    file: "hub.png"
                }
                Pic {
                    x: root.hubRX - root.hubR - 1; y: root.hubY - root.hubR - 1
                    width: 2 * root.hubR + 2; height: width
                    rotation: root.angR
                    file: "hub.png"
                }
                // the light on the hubs stays where it is while they turn
                Pic {
                    x: root.hubLX - root.hubR - 1; y: root.hubY - root.hubR - 1
                    width: 2 * root.hubR + 2; height: width
                    file: "hub-light.png"
                }
                Pic {
                    x: root.hubRX - root.hubR - 1; y: root.hubY - root.hubR - 1
                    width: 2 * root.hubR + 2; height: width
                    file: "hub-light.png"
                }
                Pic {
                    id: shell
                    x: -2; y: -2
                    width: root.casW + 4; height: root.casH + 4
                    file: "cas.png"
                }

                // the label: artwork sticker, title and artist
                Item {
                    id: label
                    x: 10.4 * root.mm; y: 4.4 * root.mm
                    width: 79.6 * root.mm; height: 15.0 * root.mm
                    opacity: root.labelA
                    readonly property bool hasArt: root.labelArt !== "" && (artImg.status === Image.Ready || artPrev.status === Image.Ready)
                    readonly property real side: height - 2 * 1.1 * root.mm

                    Item {
                        id: sticker
                        x: 1.1 * root.mm; y: 1.1 * root.mm
                        width: label.side; height: label.side
                        // artwork arriving late (a radio) fades in, the words make room
                        opacity: label.hasArt ? 1 : 0
                        visible: opacity > 0
                        Behavior on opacity { enabled: root.live && root.phase === 2; NumberAnimation { duration: 250 } }
                        // 🚨 two images (see Cover.qml): radio artwork changes every few
                        // seconds and the new one must load hidden, or the label blinks
                        Image {
                            id: artPrev
                            anchors.fill: parent
                            fillMode: Image.PreserveAspectCrop
                            sourceSize.width: artImg.sourceSize.width
                            sourceSize.height: artImg.sourceSize.height
                            smooth: true; asynchronous: false; cache: true
                            visible: artImg.status !== Image.Ready && status === Image.Ready
                        }
                        Image {
                            id: artImg
                            anchors.fill: parent
                            source: root.labelArt
                            fillMode: Image.PreserveAspectCrop
                            sourceSize.width: root.px(width)
                            sourceSize.height: root.px(height)
                            smooth: true; asynchronous: true; cache: true
                            visible: status === Image.Ready
                            onStatusChanged: if (status === Image.Ready) artPrev.source = source
                        }
                        Rectangle {
                            anchors.fill: parent
                            color: "transparent"
                            border.width: 0.5
                            border.color: "#80000000"
                        }
                    }
                    // nothing written yet (the still preview): two faint ruled lines
                    Rectangle {
                        x: titleText.x; y: 7.4 * root.mm
                        width: titleText.width; height: 0.5
                        color: "#d4af37"; opacity: 0.22
                        visible: root.labelTitle === "" && root.labelSub === ""
                    }
                    Rectangle {
                        x: titleText.x; y: 12.2 * root.mm
                        width: titleText.width * 0.62; height: 0.5
                        color: "#d4af37"; opacity: 0.16
                        visible: root.labelTitle === "" && root.labelSub === ""
                    }
                    Text {
                        id: titleText
                        x: label.hasArt ? sticker.x + sticker.width + 2.4 * root.mm : 2.0 * root.mm
                        Behavior on x { enabled: root.live && root.phase === 2; NumberAnimation { duration: 250; easing.type: Easing.InOutQuad } }
                        y: 1.2 * root.mm
                        width: label.width - x - 2.0 * root.mm
                        height: 6.8 * root.mm
                        verticalAlignment: Text.AlignVCenter
                        text: root.labelTitle
                        elide: Text.ElideRight
                        maximumLineCount: 1
                        color: "#ece3cb"
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                    }
                    Text {
                        x: titleText.x
                        y: titleText.y + titleText.height
                        width: titleText.width
                        height: 5.6 * root.mm
                        verticalAlignment: Text.AlignVCenter
                        text: root.labelSub
                        elide: Text.ElideRight
                        maximumLineCount: 1
                        color: "#a8a398"
                        font.pixelSize: 9
                    }
                }
            }

            // the top face of the door, seen once it leans out: its height in
            // the door's plane is the thickness times tan(angle)
            Pic {
                x: root.doorX; y: root.doorY - height
                width: root.doorW
                height: root.doorEdge * Math.tan(root.openAngle * root.doorOpen * Math.PI / 180)
                dh: root.doorEdge
                visible: height > 0.05
                file: "door-edge.png"
            }
            Pic {
                id: door
                x: root.doorX - 3; y: root.doorY - 3
                width: root.doorW + 6; height: root.doorH + 6
                file: "door.png"
            }
            // leaning out, the door turns away from the light
            Rectangle {
                x: root.doorX; y: root.doorY
                width: root.doorW; height: root.doorH
                radius: 4
                antialiasing: true
                gradient: Gradient {
                    GradientStop { position: 0.0; color: "#000000" }
                    GradientStop { position: 1.0; color: "#99000000" }
                }
                opacity: 0.5 * root.doorOpen
                visible: opacity > 0.002
            }
        }

        // the PLAY key held down while the tape runs
        Pic {
            x: 61; y: 213; width: 60; height: 34
            file: "key-play.png"
            opacity: root.lit ? 1 : 0
            visible: opacity > 0
            Behavior on opacity { enabled: root.live; NumberAnimation { duration: 140 } }
        }

        LcdTape {
            x: 339; y: 20
            base: root.assetsBase + "../lcd/"
            texScale: root.decodeScale
            on: !root.live || root.power
            counter: !root.live ? 142 : root.loaded ? root.elapsed : 0
            play: root.lit
            pause: root.loaded && root.live && !root.playing && root.elapsed > 0
            forward: root.lit
            levelL: !root.live ? 68 : root.lit ? root.levelL : 0
            levelR: !root.live ? 56 : root.lit ? root.levelR : 0
        }

        // the power LED
        Pic {
            x: 430; y: 218; width: 24; height: 24
            file: "led.png"
            opacity: !root.live || root.power ? 1 : 0
            visible: opacity > 0
            Behavior on opacity { enabled: root.live; NumberAnimation { duration: 250 } }
        }

        // ── the controls ───────────────────────────────────────────────────
        // The keys: a pressed image while a finger is on one (and a moment
        // after a quick tap). Touch areas as large as the layout allows: each
        // reaches halfway into the gaps and from the door down past the panel.
        Repeater {
            model: root.keys
            Item {
                id: key
                required property var modelData
                readonly property bool down: area.pressed || flash.running
                Pic {
                    x: key.modelData.x0 - 7; y: 213
                    width: key.modelData.x1 - key.modelData.x0 + 14; height: 34
                    file: "key-" + key.modelData.name + "-down.png"
                    visible: key.down && !(key.modelData.name === "play" && root.lit)   // lit PLAY is down already
                }
                MouseArea {
                    id: area
                    x: key.modelData.h0; y: 214
                    width: key.modelData.h1 - key.modelData.h0; height: 48
                    enabled: root.live
                    // held: ◀◀ / ▶▶ wind instead of skipping (no click follows a hold)
                    pressAndHoldInterval: 450
                    onPressAndHold: {
                        var a = key.modelData.action
                        if (!root.power || root.phase !== 2 || (a !== "next" && a !== "prev")) return
                        root.windArea = area
                        root.windDir = a === "next" ? 1 : -1
                        root.action("wind", root.windDir)
                    }
                    onReleased: { flash.restart(); root.windStop() }
                    onCanceled: root.windStop()
                    onClicked: root.press(key.modelData.action)
                }
                Timer { id: flash; interval: 110 }
            }
        }

        // The volume fader (cassette.py FADER: 0 at x 352, 100 at x 488, slot
        // at y 146). Drag the cap, or touch the slot to send it there; a wheel
        // works too.
        readonly property real faderX0: 352
        readonly property real faderX1: 488
        readonly property real faderLevel: faderArea.level >= 0 ? faderArea.level : Math.max(0, root.volume)
        Pic {
            x: stage.faderX0 + (stage.faderX1 - stage.faderX0) * (!root.live ? 0.7 : stage.faderLevel / 100) - 10
            y: 146 - 14; width: 20; height: 28
            file: "fader.png"
            opacity: root.live && root.volumeFixed ? 0.45 : 1
        }
        MouseArea {
            id: faderArea
            x: stage.faderX0 - 12; y: 146 - 16; width: stage.faderX1 - stage.faderX0 + 24; height: 32
            enabled: root.live && !root.volumeFixed && root.volume >= 0
            property int level: -1               // being dragged to, -1 not dragging
            function at(mx) { return Math.round(Math.max(0, Math.min(100, (mx - 12) * 100 / (stage.faderX1 - stage.faderX0)))) }
            function send(v, fin) {
                if (!fin && v === (level >= 0 ? level : root.volume)) return
                level = v
                root.action("volume", { level: v, final: fin })
            }
            onPressed: (m) => send(at(m.x), false)
            onPositionChanged: (m) => send(at(m.x), false)
            onReleased: { if (level >= 0) root.action("volume", { level: level, final: true }); level = -1 }
            onCanceled: level = -1
            onWheel: (w) => {
                var v = Math.max(0, Math.min(100, root.volume + (w.angleDelta.y > 0 ? 2 : -2)))
                if (v !== root.volume) root.action("volume", { level: v, final: true })
            }
        }
    }
}
