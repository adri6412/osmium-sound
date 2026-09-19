// Now Playing animation "CD": a top-loading CD player seen from above. The
// smoked lid slides open under the raised right block, the disc (the album
// artwork printed on it) is lowered onto the turntable, the magnetic clamp
// drops on it, the lid closes and the disc spins while playing. The right
// block is a 90s front panel: the grey-green LCD (LcdCd.qml: track, time,
// music calendar, CD-Text) and four working keys.
//
// A pure scene (no Hifi imports) driven by NpAnimation.qml; the images are
// built by tools/np-anim/cd.py, whose geometry constants are mirrored below.
//
// 🚨 The kiosk runs on a weak iGPU, 24/7: nothing here loops. The spin is one
// 30 Hz Timer that runs only while the disc turns (playing, or slowing down
// after a pause); insertion and removal are bounded animations. Paused,
// stopped, hidden or previewed, the scene is fully idle.
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
    // The LCD and the keys need the queue position, the time and the modes,
    // and the controls NpAnimation feeds to the scenes that declare them.
    property bool power: true
    property int volume: -1
    property bool volumeFixed: false
    property real elapsed: 0
    property int trackIndex: -1
    property int trackTotal: 0
    property int repeatMode: 0
    property int shuffleMode: 0
    property string trackTitle: ""           // CD-Text: the track, not the album
    property string trackArtist: ""
    signal action(string name, var value)

    // ── design: 520 x 260 points, scaled uniformly and centred ─────────────
    readonly property real s: Math.max(0.01, Math.min(width / 520, height / 260))
    // Texture scale in coarse steps: the Now Playing panel changes height by
    // a few points with the title's line count (s between ~0.94 and 1.01),
    // and an exact sourceSize would reload (and blank) every image on those
    // track changes. Above 0.9 the steps are 0.9-1.05-1.2..., below 1/8.
    readonly property real texScale: devScale * (s > 0.9 ? 0.9 + 0.15 * Math.ceil((s - 0.9) / 0.15) : Math.ceil(s * 8) / 8)
    function px(v) { return Math.max(1, Math.round(v * root.texScale)) }

    readonly property real wellX: 134
    readonly property real wellY: 120
    readonly property real discR: 92
    readonly property real lidX: 17          // lid image (3 points of margin round the lid)
    readonly property real lidTravel: 238

    // ── choreography state ─────────────────────────────────────────────────
    // phase: 0 empty (lid closed or closing), 1 inserting, 2 loaded, 3 removing
    property int phase: 0
    property real lidOpen: 0                 // 0 closed .. 1 parked under the right block
    property real discH: 1                   // disc height: 0 on the turntable .. 1 high above
    property real discA: 0                   // disc opacity
    property real puckH: 1
    property real puckA: 0
    property real angle: -24                 // degrees
    property real speed: 0                   // degrees per second
    property string labelArt: ""             // artwork printed on the disc now
    property int lidDur: 0
    property int gapDur: 0                   // beat between the old disc out and the new one in

    readonly property bool wantSpin: live && active && phase === 2 && playing && hasTrack
    property real spinFrom: 0
    property bool spinUp: false
    property real spinDur: 1200
    property double spinT0: 0
    property double lastT: 0
    property real lcdAngle: 0                // the LCD's own spin indicator

    // A real CD turns at constant linear velocity (1.3 m/s): ~500 rpm where
    // the music starts (radius 25 mm) down to ~215 at the edge (58 mm). The
    // pickup's place follows the position on the whole disc, the tracks
    // before plus this one; equal playing time covers equal area.
    function clvRate() {                     // degrees per second
        var f = trackTotal > 0 && trackIndex >= 0 ? Math.max(0, Math.min(1, (trackIndex + progress) / trackTotal)) : 0
        var r = Math.sqrt(25 * 25 + f * (58 * 58 - 25 * 25))
        return 1300 / (2 * Math.PI * r) * 360
    }
    // At 30 frames a second a disc turning 50-100 degrees a frame would
    // stutter and wheel backwards: from ~80 rpm the print melts, gradually,
    // into the rings the eye sees on a real one (the smear below), all
    // rings past ~330 rpm.
    readonly property real blur: Math.max(0, Math.min(1, (speed - 480) / 1500))

    onWantSpinChanged: {
        spinFrom = speed
        spinUp = wantSpin
        // the motor pulls the disc up to speed in about three seconds, as a
        // real player's does (the art can be seen gathering speed for the
        // first two); the brake is quicker, hard before the lid opens
        spinDur = wantSpin ? 3000 : phase === 3 ? 450 : 900
        spinT0 = Date.now()
    }

    // The only continuous motion: advances the angle by real elapsed time.
    Timer {
        id: spinTimer
        interval: 33
        repeat: true
        running: root.live && root.active && (root.wantSpin || root.speed > 0)
        onRunningChanged: if (running) root.lastT = Date.now()
        onTriggered: root.tick()
    }
    function tick() {
        var now = Date.now()
        var dt = Math.min(0.1, Math.max(0, (now - lastT) / 1000))
        lastT = now
        var u = Math.min(1, Math.max(0, (now - spinT0) / spinDur))
        var e = u * u * (3 - 2 * u)
        var to = spinUp ? clvRate() : 0
        var v = spinFrom + (to - spinFrom) * e
        // (fully smeared, the hidden print needs not turn: no frame to draw)
        if (blur < 1) {
            var a = angle + (speed + v) * 0.5 * dt
            angle = a - 360 * Math.floor(a / 360)
        }
        speed = (u >= 1 && !spinUp) ? 0 : v
        // the indicator steps at its own readable pace, not the disc's
        var l = lcdAngle + Math.min(speed, 540) * dt
        lcdAngle = l - 360 * Math.floor(l / 360)
    }

    // The smear: the mean colour of each ring of the print (in linear light,
    // as the eye blends it), laid down as one radial gradient. A 96 x 96
    // sample of the artwork or the generic label is plenty. Drawn once per
    // image (and texture size), and only once the disc gets up to speed.
    function paintSmear() {
        var ctx = smear.getContext("2d")
        var W = smear.width, H = smear.height
        var label = root.assetsBase + "cd-label.png"
        var art = artImg.status === Image.Ready ? artImg : artPrev
        var N = 96
        ctx.reset()
        if (disc.artReady && art.implicitWidth > 0 && art.implicitHeight > 0) {
            var side = Math.min(art.implicitWidth, art.implicitHeight)
            ctx.drawImage(art, (art.implicitWidth - side) / 2, (art.implicitHeight - side) / 2, side, side, 0, 0, N, N)
        } else if (smear.isImageLoaded(label)) {
            ctx.drawImage(label, 0, 0, N, N)
        } else {
            return
        }
        var d = ctx.getImageData(0, 0, N, N).data
        ctx.clearRect(0, 0, W, H)
        var r0 = 34.5, r1 = 89.6, B = 32         // the printed ring (cd.py PRINT_R0/R1)
        var acc = []
        for (var b = 0; b < B; b++) acc.push([0, 0, 0, 0])
        for (var y = 0; y < N; y++) {
            for (var x = 0; x < N; x++) {
                var r = Math.hypot(x + 0.5 - N / 2, y + 0.5 - N / 2) / (N / 2) * discR
                if (r < r0 || r >= r1) continue
                var i = 4 * (y * N + x), a = d[i + 3] / 255
                var k = acc[Math.floor((r - r0) / (r1 - r0) * B)]
                k[0] += a * Math.pow(d[i] / 255, 2.2)
                k[1] += a * Math.pow(d[i + 1] / 255, 2.2)
                k[2] += a * Math.pow(d[i + 2] / 255, 2.2)
                k[3] += a
            }
        }
        function css(k, alpha) {
            function c(v) { return Math.round(255 * Math.pow(k[3] > 0 ? v / k[3] : 0, 1 / 2.2)) }
            return "rgba(" + c(k[0]) + "," + c(k[1]) + "," + c(k[2]) + "," + alpha + ")"
        }
        var g = ctx.createRadialGradient(W / 2, H / 2, 0, W / 2, H / 2, W / 2)
        g.addColorStop((r0 - 0.3) / discR, css(acc[0], 0))
        g.addColorStop(r0 / discR, css(acc[0], 1))
        for (b = 0; b < B; b++)
            g.addColorStop((r0 + (b + 0.5) / B * (r1 - r0)) / discR, css(acc[b], 1))
        g.addColorStop(r1 / discR, css(acc[B - 1], 1))
        g.addColorStop((r1 + 0.3) / discR, css(acc[B - 1], 0))
        ctx.fillStyle = g
        ctx.fillRect(0, 0, W, H)
        smear.stale = false
    }

    function stopAll() {
        insertAnim.stop(); removeAnim.stop(); closeAnim.stop()
    }
    // hidden: back to an empty, closed player, so the next appearance replays
    // the insertion
    function reset() {
        stopAll()
        phase = 0; lidOpen = 0; discH = 1; discA = 0; puckH = 1; puckA = 0; speed = 0
    }
    // the still preview: loaded, lid closed, a pleasant angle
    function pose() {
        stopAll()
        phase = 2; lidOpen = 0; discH = 0; discA = 1; puckH = 0; puckA = 1; speed = 0; angle = 38
        labelArt = artwork
    }
    function sync() {
        if (!live) { pose(); return }
        if (!active) { reset(); return }
        if (hasTrack) {
            if (phase === 0) insert()
        } else if (phase === 1 || phase === 2) {
            remove()
        }
    }
    function insert(gap) {
        stopAll()
        gapDur = gap || 0
        if (labelArt !== artwork) { artPrev.source = ""; labelArt = artwork }
        phase = 1
        discH = 1; discA = 0; puckH = 1; puckA = 0
        lidDur = Math.round(560 * (1 - lidOpen))
        insertAnim.start()
    }
    function remove() {
        stopAll()
        phase = 3
        lidDur = Math.round(400 * (1 - lidOpen))
        removeAnim.start()
    }
    function removed() {
        if (active && hasTrack) {
            insert(160)
        } else {
            phase = 0
            labelArt = artwork
            closeAnim.start()
        }
    }
    // a new album: out with the old disc, in with the new one (the artwork
    // of the old one stays printed on it until it is out of sight)
    onMediaKeyChanged: if (live && active && (phase === 1 || phase === 2)) remove()
    onActiveChanged: sync()
    onHasTrackChanged: sync()
    onLiveChanged: sync()
    onArtworkChanged: Qt.callLater(applyArt)
    // (hidden, nothing is loaded: insert() takes the artwork of the moment)
    function applyArt() {
        if (!live || (active && phase !== 3)) labelArt = artwork
    }
    Component.onCompleted: sync()

    SequentialAnimation {
        id: insertAnim
        PauseAnimation { duration: root.gapDur }
        ParallelAnimation {
            NumberAnimation { target: root; property: "lidOpen"; to: 1; duration: root.lidDur; easing.type: Easing.InOutCubic }
            SequentialAnimation {
                PauseAnimation { duration: Math.round(root.lidDur * 0.55) }
                ParallelAnimation {
                    NumberAnimation { target: root; property: "discA"; to: 1; duration: 220; easing.type: Easing.OutQuad }
                    NumberAnimation { target: root; property: "discH"; to: 0; duration: 1050; easing.type: Easing.InOutCubic }
                }
            }
        }
        PauseAnimation { duration: 90 }
        ParallelAnimation {
            NumberAnimation { target: root; property: "puckA"; to: 1; duration: 160; easing.type: Easing.OutQuad }
            NumberAnimation { target: root; property: "puckH"; to: 0; duration: 380; easing.type: Easing.InQuad }
        }
        NumberAnimation { target: root; property: "puckH"; to: 0.04; duration: 70; easing.type: Easing.OutQuad }
        NumberAnimation { target: root; property: "puckH"; to: 0; duration: 90; easing.type: Easing.InQuad }
        PauseAnimation { duration: 120 }
        NumberAnimation { target: root; property: "lidOpen"; to: 0; duration: 620; easing.type: Easing.InOutCubic }
        onFinished: { root.phase = 2; root.reading = true; readTimer.restart() }
    }
    // the LCD reads the disc for a moment after the lid closes
    property bool reading: false
    Timer { id: readTimer; interval: 1100; onTriggered: root.reading = false }
    SequentialAnimation {
        id: removeAnim
        NumberAnimation { target: root; property: "lidOpen"; to: 1; duration: root.lidDur; easing.type: Easing.InOutCubic }
        ParallelAnimation {
            NumberAnimation { target: root; property: "puckH"; to: 1; duration: 220; easing.type: Easing.OutQuad }
            NumberAnimation { target: root; property: "puckA"; to: 0; duration: 220; easing.type: Easing.InQuad }
            SequentialAnimation {
                PauseAnimation { duration: 60 }
                ParallelAnimation {
                    NumberAnimation { target: root; property: "discH"; to: 1; duration: 320; easing.type: Easing.InOutQuad }
                    NumberAnimation { target: root; property: "discA"; to: 0; duration: 320; easing.type: Easing.InQuad }
                }
            }
        }
        onFinished: root.removed()
    }
    NumberAnimation {
        id: closeAnim
        target: root; property: "lidOpen"; to: 0; duration: 560; easing.type: Easing.InOutCubic
    }

    // ── what the display and the LED show ──────────────────────────────────
    readonly property bool loaded: !live || (phase === 2 && hasTrack)
    readonly property bool lit: !live || (loaded && playing)
    readonly property bool lcdReady: loaded && !reading
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
        // all at once, not piece by piece while the images decode
        visible: base.status === Image.Ready && bridge.status === Image.Ready && lid.status === Image.Ready

        Pic { id: base; width: 520; height: 260; source: root.assetsBase + "cd-base.png" }

        readonly property real dh: root.discH

        // While it is off the turntable the disc is above the whole player:
        // it (and its shadow) passes over the lid that is still parking. It
        // is back under the lid before the lid closes over it (the lid only
        // moves while the disc lies on the turntable or is out of sight).
        Item {
            width: 520; height: 260
            z: stage.dh > 0 ? 10 : 0

            // disc shadows: the far one (soft, wide, faint) gives way to the near
            // one (sharp, dark) as the disc comes down
            Pic {
                width: 244; height: 244
                x: root.wellX - 122 + 1.2 + 15 * stage.dh
                y: root.wellY - 122 + 2.0 + 22 * stage.dh
                scale: 1 + 0.26 * stage.dh
                opacity: root.discA * (1 - Math.pow(1 - stage.dh, 3)) * (1.0 - 0.3 * stage.dh)
                visible: opacity > 0.002
                source: root.assetsBase + "cd-shadow-far.png"
            }
            Pic {
                width: 244; height: 244
                x: root.wellX - 122 + 1.2 + 15 * stage.dh
                y: root.wellY - 122 + 2.0 + 22 * stage.dh
                scale: 1 + 0.26 * stage.dh
                opacity: root.discA * Math.pow(1 - stage.dh, 3)
                visible: opacity > 0.002
                source: root.assetsBase + "cd-shadow-near.png"
            }

            // the print at speed: each ring of the label smeared to its mean
            // colour (drawn once per artwork, it never moves); the sharp print
            // fades out over it as the disc gets up to speed
            Canvas {
                id: smear
                // drawn at texture size, scaled down to the disc
                width: root.px(disc.width); height: root.px(disc.height)
                x: disc.x + (disc.width - width) / 2
                y: disc.y + (disc.height - height) / 2
                scale: disc.scale * disc.width / width
                opacity: root.discA
                visible: root.blur > 0 && opacity > 0.002
                property bool stale: true
                function redraw() { stale = true; if (visible) requestPaint() }
                onVisibleChanged: if (visible && stale) requestPaint()
                onWidthChanged: redraw()
                onAvailableChanged: if (available) loadImage(root.assetsBase + "cd-label.png")
                onImageLoaded: redraw()
                onPaint: root.paintSmear()
            }
            // the disc's print: the generic label or the artwork masked to the
            // printed ring, cooked in one layer that turns as one quad
            Item {
                id: disc
                width: root.discR * 2; height: root.discR * 2
                x: root.wellX - root.discR - 3 * stage.dh
                y: root.wellY - root.discR - 5 * stage.dh
                scale: 1 + 0.22 * stage.dh
                rotation: root.angle + 16 * stage.dh    // a slight twist of the hand while it lowers the disc
                opacity: root.discA * (1 - root.blur)
                visible: opacity > 0.002
                layer.enabled: true
                layer.smooth: true
                layer.textureSize: Qt.size(root.px(width), root.px(height))

                readonly property bool artReady: root.labelArt !== "" && (artImg.status === Image.Ready || artPrev.status === Image.Ready)
                onArtReadyChanged: smear.redraw()

                Pic { anchors.fill: parent; source: root.assetsBase + "cd-label.png" }
                // 🚨 two images (see Cover.qml): radio artwork changes every few
                // seconds and the new one must load hidden, or the label blinks
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
                    onStatusChanged: if (status === Image.Ready) { artPrev.source = source; smear.redraw() }
                }
                Pic {
                    id: printMask
                    anchors.fill: parent
                    visible: false
                    source: root.assetsBase + "cd-mask.png"
                    layer.enabled: true
                    layer.smooth: true
                    layer.textureSize: Qt.size(root.px(width), root.px(height))
                }
                MultiEffect {
                    anchors.fill: parent
                    source: artImg.status === Image.Ready ? artImg : artPrev
                    // a new album's artwork arriving late fades in over the
                    // generic print instead of popping
                    opacity: disc.artReady ? 1 : 0
                    visible: opacity > 0
                    Behavior on opacity { enabled: root.live; NumberAnimation { duration: 250 } }
                    maskEnabled: true
                    maskSource: printMask
                    // a smooth ramp over the mask's alpha (the defaults cut it at
                    // 0, which leaves a jagged print edge)
                    maskThresholdMin: 0.5
                    maskSpreadAtMin: 1.0
                }
            }
            // clear hub, mirror band and rim: round, they need not turn
            Pic {
                width: disc.width; height: disc.height
                x: disc.x; y: disc.y
                scale: disc.scale
                opacity: root.discA
                visible: opacity > 0.002
                source: root.assetsBase + "cd-disc.png"
            }
            // the light on the disc stays where it is while the disc turns
            Pic {
                width: disc.width; height: disc.height
                x: disc.x; y: disc.y
                scale: disc.scale
                opacity: root.discA
                visible: disc.visible
                source: root.assetsBase + "cd-sheen.png"
            }
        }

        // the magnetic clamp
        Pic {
            width: 94; height: 94
            x: root.wellX - 47 + 0.8 + 9 * root.puckH
            y: root.wellY - 47 + 1.4 + 13 * root.puckH
            scale: 1 + 0.45 * root.puckH
            opacity: root.puckA * (0.9 - 0.55 * root.puckH)
            visible: opacity > 0.002
            source: root.assetsBase + "cd-puck-shadow.png"
        }
        Pic {
            width: 64; height: 64
            x: root.wellX - 32 - 2 * root.puckH
            y: root.wellY - 32 - 3 * root.puckH
            scale: 1 + 0.32 * root.puckH
            opacity: root.puckA
            visible: opacity > 0.002
            source: root.assetsBase + "cd-puck.png"
        }

        Pic {
            id: lid
            width: 234; height: 216
            x: root.lidX + root.lidTravel * root.lidOpen
            y: 12
            source: root.assetsBase + "cd-lid.png"
        }
        Pic { id: bridge; x: 244; y: 0; width: 276; height: 260; source: root.assetsBase + "cd-bridge.png" }

        LcdCd {
            x: 286; y: 30
            base: root.assetsBase + "../lcd/"
            texScale: root.texScale
            on: !root.live || root.power
            word: !root.live || root.lcdReady ? ""
                  : root.reading ? "  rEAd"
                  : root.lidOpen > 0 || root.phase === 1 || root.phase === 3 ? "  OPEn"
                  : "no dISC"
            track: root.lcdReady ? root.lcdTrack : 0
            seconds: !root.live ? 167 : root.elapsed
            timeShown: root.lcdReady
            labels: root.lcdReady
            play: root.lcdReady && (root.playing || !root.live)
            pause: root.lcdReady && root.live && !root.playing && root.elapsed > 0
            repeatMode: !root.live ? 2 : root.repeatMode
            random: root.live && root.shuffleMode > 0
            calFrom: root.lcdReady ? root.lcdTrack : 0
            calTo: root.lcdReady ? Math.min(16, root.lcdTotal) : 0
            over: root.lcdReady && root.lcdTotal > 16
            // the indicator turns while the disc does, a step every 45 degrees
            spin: !root.lcdReady ? -1 : root.speed > 0 ? Math.floor(root.lcdAngle / 45) % 8 : 8
            text: (root.lcdReady || !root.live) ? [!root.live ? "Allegro" : root.trackTitle, !root.live ? "Beaux Arts Trio" : root.trackArtist].filter(function(x) { return !!x }).join(" - ") : ""
            scroll: root.live && root.active && root.playing
        }
        // the keys of the front panel: play/pause, stop, skip back, skip forward
        Repeater {
            model: root.live ? [[348, "playpause"], [389.33, "stop"], [430.67, "prev"], [472, "next"]] : []
            MouseArea {
                required property var modelData
                x: modelData[0] - 13; y: 157; width: 26; height: 26
                onClicked: {
                    var k = modelData[1]
                    if (k === "playpause") root.action(root.playing ? "pause" : "play", true)
                    else root.action(k, true)
                }
                Rectangle { anchors.centerIn: parent; width: 19; height: 19; radius: 9.5; color: "black"; opacity: parent.pressed ? 0.4 : 0 }
            }
        }

        Pic {
            x: 291.5; y: 156; width: 28; height: 28
            source: root.assetsBase + "cd-led.png"
            opacity: root.lit ? 1 : 0
            visible: opacity > 0
            Behavior on opacity { enabled: root.live; NumberAnimation { duration: 180 } }
        }
    }
}
