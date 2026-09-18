// Now Playing animation "CD player": a 90s black front-loading CD player seen
// from the front, a little from above. A new album opens the drawer, the old
// disc comes out, the new one (the album artwork printed on it) goes in, the
// drawer closes and the LCD reads the disc, then shows track and time, the
// music calendar and the turning-disc indicator. The keys work: open/close,
// play, pause, stop, skip, repeat, random, power.
//
// A pure scene (no Hifi imports) driven by NpAnimation.qml; the images are
// built by tools/np-anim/cdfront.py (the player) and lcd.py (the LCD), whose
// geometry constants are mirrored below. The disc is the one of the CD scene
// (assets/anim/cd/).
//
// 🚨 Weak iGPU, 24/7: nothing here runs at frame rate. While playing only the
// seconds and the disc indicator change (4 steps a second); the drawer moves
// only when a disc goes in or out. Paused, stopped, hidden or previewed, the
// scene is fully idle.
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
    property bool vintage: true              // always a 90s front panel
    // controls (NpAnimation feeds these to scenes that declare them)
    property bool power: true
    property int volume: -1
    property bool volumeFixed: false
    property real elapsed: 0
    property int trackIndex: -1              // 0-based position in the queue
    property int trackTotal: 0
    property int repeatMode: 0
    property int shuffleMode: 0
    property string trackTitle: ""           // CD-Text: the track, not the album
    property string trackArtist: ""
    signal action(string name, var value)

    // ── design: 520 x 260 points, scaled uniformly and centred ─────────────
    readonly property real s: Math.max(0.01, Math.min(width / 520, height / 260))
    // coarse texture steps, like the CD scene: a few points of panel height
    // must not reload every picture
    readonly property real texScale: devScale * (s > 0.9 ? 0.9 + 0.15 * Math.ceil((s - 0.9) / 0.15) : Math.ceil(s * 8) / 8)
    function px(v) { return Math.max(1, Math.round(v * root.texScale)) }

    readonly property real drawerX: 25
    readonly property real drawerY: 33
    readonly property real drawerW: 240
    readonly property real drawerH: 24
    readonly property real slotBottom: 60
    readonly property real travel: 106
    readonly property real bedH: 124
    readonly property real bedDiscX: 120
    readonly property real bedDiscY: 86
    readonly property real discRx: 98
    readonly property real squash: 34 / 102        // the disc seen at a grazing angle
    readonly property var keys: ({
        power: [24, 64], repeat: [176, 204], random: [212, 240],
        eject: [290, 320], play: [326, 356], pause: [362, 392],
        stop: [398, 428], prev: [434, 464], next: [470, 500]
    })
    readonly property real keyY0: 184
    readonly property real keyY1: 202

    // ── choreography ───────────────────────────────────────────────────────
    // phase: 0 empty and closed, 1 loading, 2 loaded, 3 unloading, 4 open with
    // the disc (the owner pressed open/close)
    property int phase: 0
    property real trayOut: 0                 // 0 closed .. 1 fully out
    property real discA: 0
    property real discUp: 1                  // 0 on the bed .. 1 lifted away
    property string word: ""                 // what the LCD spells during the moves
    property string labelArt: ""
    property int trayDur: 0
    property int gapDur: 0

    function stopAll() { loadAnim.stop(); unloadAnim.stop(); closeAnim.stop(); openAnim.stop(); readTimer.stop() }
    function reset() {
        stopAll()
        phase = 0; trayOut = 0; discA = 0; discUp = 1; word = ""
    }
    function pose() {
        stopAll()
        phase = 2; trayOut = 0; discA = 1; discUp = 0; word = ""
        labelArt = artwork
    }
    function sync() {
        if (!live) { pose(); return }
        if (!active) { reset(); return }
        if (hasTrack) {
            if (phase === 0) load()
        } else if (phase === 1 || phase === 2 || phase === 4) {
            unload()
        }
    }
    function load(gap) {
        stopAll()
        gapDur = gap || 0
        if (labelArt !== artwork) { artPrev.source = ""; labelArt = artwork }
        phase = 1
        discA = 0; discUp = 1
        trayDur = Math.round(650 * (1 - trayOut))
        loadAnim.start()
    }
    function unload() {
        stopAll()
        phase = 3
        trayDur = Math.round(650 * (1 - trayOut))
        unloadAnim.start()
    }
    function unloaded() {
        if (active && hasTrack) {
            load(150)
        } else {
            phase = 0
            labelArt = artwork
            closeAnim.start()
        }
    }
    function loaded() {
        phase = 2
        word = "  rEAd"
        readTimer.restart()
    }
    // open/close key: out with the disc still on the bed, or back in
    function toggleTray() {
        if (phase === 4 || (phase === 0 && trayOut > 0)) {
            closeTray()
        } else if (phase === 2 || phase === 0) {
            stopAll()
            phase = hasTrack ? 4 : 0
            trayDur = Math.round(650 * (1 - trayOut))
            openAnim.start()
            if (hasTrack) root.action("eject", true)
        }
    }
    function closeTray() {
        stopAll()
        if (phase === 4) {
            phase = 1
            closeAnim.start()
        } else {
            phase = 0
            closeAnim.start()
        }
    }
    onMediaKeyChanged: if (live && active && (phase === 1 || phase === 2)) unload()
    onActiveChanged: sync()
    onHasTrackChanged: sync()
    onLiveChanged: sync()
    // playback started from anywhere closes an open drawer
    onPlayingChanged: if (live && active && playing && phase === 4) closeTray()
    onArtworkChanged: Qt.callLater(applyArt)
    function applyArt() {
        if (!live || (active && phase !== 3)) labelArt = artwork
    }
    Component.onCompleted: sync()

    SequentialAnimation {
        id: loadAnim
        PauseAnimation { duration: root.gapDur }
        PropertyAction { target: root; property: "word"; value: "  OPEn" }
        NumberAnimation { target: root; property: "trayOut"; to: 1; duration: root.trayDur; easing.type: Easing.InOutCubic }
        ParallelAnimation {
            NumberAnimation { target: root; property: "discA"; to: 1; duration: 200; easing.type: Easing.OutQuad }
            NumberAnimation { target: root; property: "discUp"; to: 0; duration: 420; easing.type: Easing.OutCubic }
        }
        PauseAnimation { duration: 260 }
        PropertyAction { target: root; property: "word"; value: "" }
        NumberAnimation { target: root; property: "trayOut"; to: 0; duration: 650; easing.type: Easing.InOutCubic }
        ScriptAction { script: root.loaded() }
    }
    SequentialAnimation {
        id: unloadAnim
        PropertyAction { target: root; property: "word"; value: "  OPEn" }
        NumberAnimation { target: root; property: "trayOut"; to: 1; duration: root.trayDur; easing.type: Easing.InOutCubic }
        ParallelAnimation {
            NumberAnimation { target: root; property: "discUp"; to: 1; duration: 340; easing.type: Easing.InCubic }
            NumberAnimation { target: root; property: "discA"; to: 0; duration: 340; easing.type: Easing.InQuad }
        }
        ScriptAction { script: root.unloaded() }
    }
    SequentialAnimation {
        id: openAnim
        PropertyAction { target: root; property: "word"; value: "  OPEn" }
        NumberAnimation { target: root; property: "trayOut"; to: 1; duration: root.trayDur; easing.type: Easing.InOutCubic }
    }
    SequentialAnimation {
        id: closeAnim
        PropertyAction { target: root; property: "word"; value: "" }
        NumberAnimation { target: root; property: "trayOut"; to: 0; duration: Math.round(650 * root.trayOut); easing.type: Easing.InOutCubic }
        ScriptAction { script: if (root.phase === 1) root.loaded() }
    }
    Timer { id: readTimer; interval: 1100; onTriggered: root.word = "" }

    // the disc indicator: turns while playing, 4 steps a second
    property int spinStep: 0
    Timer {
        interval: 250; repeat: true
        running: root.live && root.active && root.power && root.phase === 2 && root.playing && root.word === ""
        onTriggered: root.spinStep = (root.spinStep + 1) % 8
    }

    // ── what the LCD shows ─────────────────────────────────────────────────
    readonly property bool ready: phase === 2 && word === "" && (hasTrack || !live)
    readonly property string lcdWord: !live ? ""
                                    : word !== "" ? word
                                    : phase === 0 && trayOut === 0 ? "no dISC"
                                    : phase === 0 || phase === 4 ? "  OPEn"
                                    : ""
    readonly property int lcdTrack: !live ? 3 : trackIndex >= 0 ? trackIndex + 1 : 1
    readonly property int lcdTotal: !live ? 12 : Math.max(trackTotal, lcdTrack)

    component Pic: Image {
        smooth: true
        asynchronous: true
        sourceSize.width: root.px(width)
        sourceSize.height: root.px(height)
    }

    Item {
        id: stage
        width: 520; height: 260
        x: (root.width - 520 * root.s) / 2
        y: (root.height - 260 * root.s) / 2
        scale: root.s
        transformOrigin: Item.TopLeft
        visible: base.status === Image.Ready && drawer.status === Image.Ready

        Pic { id: base; width: 520; height: 260; source: root.assetsBase + "cdf-base.png" }

        LcdCd {
            x: 294; y: 33
            base: root.assetsBase + "../lcd/"
            texScale: root.texScale
            on: !root.live || root.power
            word: root.lcdWord
            track: root.ready ? root.lcdTrack : 0
            seconds: !root.live ? 167 : root.elapsed
            timeShown: root.ready
            labels: root.ready
            play: root.ready && (root.playing || !root.live)
            pause: root.ready && root.live && !root.playing && root.elapsed > 0
            repeatMode: !root.live ? 2 : root.repeatMode
            random: root.live && root.shuffleMode > 0
            calFrom: root.ready ? root.lcdTrack : 0
            calTo: root.ready ? Math.min(16, root.lcdTotal) : 0
            over: root.ready && root.lcdTotal > 16
            spin: !root.ready ? -1 : (root.playing && root.live) ? root.spinStep : 8
            text: (root.ready || !root.live) ? [!root.live ? "Allegro" : root.trackTitle, !root.live ? "Beaux Arts Trio" : root.trackArtist].filter(function(x) { return !!x }).join(" - ") : ""
            scroll: root.live && root.active && root.playing
        }

        Pic {
            x: 67; y: 186; width: 14; height: 14
            source: root.assetsBase + (root.power || !root.live ? "cdf-led-green.png" : "cdf-led-red.png")
        }

        // the drawer: its bed (with the disc) shows between the slot and the
        // drawer front as it comes out
        readonly property real frontY: root.drawerY + root.travel * root.trayOut
        Item {
            x: root.drawerX; y: root.slotBottom - 2
            width: root.drawerW; height: Math.max(0, stage.frontY - y)
            clip: true
            visible: root.trayOut > 0.001
            Item {
                y: stage.frontY - root.bedH - parent.y
                width: root.drawerW; height: root.bedH
                Pic { anchors.fill: parent; source: root.assetsBase + "cdf-bed.png" }
                // the disc, flattened by the viewing angle
                Item {
                    id: disc
                    width: root.discRx * 2; height: root.discRx * 2
                    x: root.bedDiscX - root.discRx
                    y: root.bedDiscY - root.discRx - 26 * root.discUp / root.squash
                    opacity: root.discA
                    visible: opacity > 0.002
                    transform: Scale { origin.x: root.discRx; origin.y: root.discRx; yScale: root.squash }
                    layer.enabled: true
                    layer.smooth: true
                    layer.textureSize: Qt.size(root.px(width), root.px(height * root.squash) * 2)

                    readonly property bool artReady: root.labelArt !== "" && (artImg.status === Image.Ready || artPrev.status === Image.Ready)

                    Pic { anchors.fill: parent; source: root.assetsBase + "../cd/cd-label.png" }
                    // 🚨 two images (see Cover.qml): a new artwork loads hidden
                    Image {
                        id: artPrev
                        anchors.fill: parent
                        visible: false
                        asynchronous: false
                        smooth: true
                        fillMode: Image.PreserveAspectCrop
                        sourceSize.width: artImg.sourceSize.width
                        sourceSize.height: artImg.sourceSize.height
                        layer.enabled: true
                        layer.smooth: true
                        layer.textureSize: artImg.layer.textureSize
                    }
                    Image {
                        id: artImg
                        anchors.fill: parent
                        visible: false
                        asynchronous: true
                        smooth: true
                        fillMode: Image.PreserveAspectCrop
                        source: root.labelArt
                        sourceSize.width: root.px(width)
                        sourceSize.height: root.px(height)
                        layer.enabled: true
                        layer.smooth: true
                        layer.textureSize: Qt.size(root.px(width), root.px(height))
                        onStatusChanged: if (status === Image.Ready) artPrev.source = source
                    }
                    Pic {
                        id: printMask
                        anchors.fill: parent
                        visible: false
                        source: root.assetsBase + "../cd/cd-mask.png"
                        layer.enabled: true
                        layer.smooth: true
                        layer.textureSize: Qt.size(root.px(width), root.px(height))
                    }
                    MultiEffect {
                        anchors.fill: parent
                        source: artImg.status === Image.Ready ? artImg : artPrev
                        visible: disc.artReady
                        maskEnabled: true
                        maskSource: printMask
                        maskThresholdMin: 0.5
                        maskSpreadAtMin: 1.0
                    }
                    Pic { anchors.fill: parent; source: root.assetsBase + "../cd/cd-disc.png" }
                }
            }
        }
        Pic {
            x: root.drawerX - 8; y: stage.frontY + 20       // cdfront.py: DRAWER y1 - 4 - y0
            width: 256; height: 24
            visible: root.trayOut > 0.001
            opacity: Math.min(1, root.trayOut * 3)
            source: root.assetsBase + "cdf-drawer-sh.png"
        }
        Pic {
            id: drawer
            x: root.drawerX - 1; y: stage.frontY - 1
            width: root.drawerW + 2; height: root.drawerH + 2
            source: root.assetsBase + "cdf-drawer.png"
        }

        // the keys: a press darkens the cap for a moment
        Repeater {
            model: ["power", "repeat", "random", "eject", "play", "pause", "stop", "prev", "next"]
            Item {
                id: key
                required property string modelData
                readonly property var r: root.keys[modelData]
                x: r[0]; y: root.keyY0; width: r[1] - r[0]; height: root.keyY1 - root.keyY0
                Rectangle { anchors.fill: parent; radius: 2.2; color: "black"; opacity: kArea.pressed ? 0.45 : 0 }
                MouseArea {
                    id: kArea
                    anchors.fill: parent; anchors.margins: -3
                    enabled: root.live
                    onClicked: root.press(key.modelData)
                }
            }
        }
    }

    function press(k) {
        if (k === "power") { root.action("power", !power); return }
        if (!power && k !== "eject") return
        if (k === "eject") toggleTray()
        else if (k === "play") { if (phase === 4) closeTray(); root.action("play", true) }
        else if (k === "pause") root.action(playing ? "pause" : "play", true)
        else if (k === "stop") root.action("stop", true)
        else if (k === "prev") root.action("prev", true)
        else if (k === "next") root.action("next", true)
        else if (k === "repeat") root.action("repeat", true)
        else if (k === "random") root.action("random", true)
    }
}
