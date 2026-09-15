// Now Playing animation "Vinyl": a record on a turntable seen from above.
// Shown in place of the VU meters (NpAnimation.qml picks the scene).
//
// A pure component: QtQuick only, no Hifi singletons, so it can be tried out
// standalone. The look is baked into assets/anim/vinyl/*.png by
// tools/np-anim/vinyl.py; the geometry constants below come from there.
//
// Choreography: the record is lowered onto the platter, the platter spins up
// to 33 1/3 rpm, the tone arm swings from its rest to the groove and the cue
// lowers the stylus; while playing the arm follows the progress from the
// first groove to the last. Pause lifts the arm and spins the platter down.
// A new album (mediaKey) lifts the arm, sends it home and swaps the record.
//
// 🚨 Power: the device is a weak iGPU running all day. The only continuous
// motion is one 30 Hz Timer that turns the label and the strobe dots, and it
// runs only while the platter turns (playing, or still slowing down). The
// record, its sheen, the platter and the spindle are round and lit from a
// fixed light: they never turn, which also keeps the grooves from shimmering.
// Every other movement is a bounded one-shot animation. Paused, stopped,
// hidden or a still preview: nothing runs.
pragma ComponentBehavior: Bound
import QtQuick

Item {
    id: root
    property url assetsBase              // folder with the scene's PNGs, trailing slash
    property real devScale: 1
    property bool live: true             // false: still preview, final pose, nothing ever runs
    property bool active: false          // on screen now; false resets to "no record"
    property bool playing: false
    property bool hasTrack: false
    property real progress: 0            // 0..1 (0 when unknown, e.g. radio)
    property string artwork: ""          // album artwork URL; "" = the generic label
    property string mediaKey: ""         // a new value swaps the record
    property string title: ""            // unused here (the cassette writes it on its label)
    property string subtitle: ""

    // for tests: true while something moves
    readonly property bool ticking: spinTimer.running
    readonly property bool animating: recAnim.running || armSwing.running || armCue.running

    // ─── geometry, base points (520 x 260), from tools/np-anim/vinyl.py ────
    readonly property real s: Math.min(width / 520, height / 260)
    readonly property real ox: (width - 520 * s) / 2
    readonly property real oy: (height - 260 * s) / 2
    // Images are decoded for the width, not the height: on Now Playing the
    // panel keeps its width and changes height with the title's lines, and a
    // new sourceSize would reload every layer (at most 25 % above the shown size)
    readonly property real decodeScale: Math.min(width / 520, s * 1.25) * devScale
    readonly property real centreX: 200
    readonly property real centreY: 128
    readonly property real pivotX: 322.211
    readonly property real pivotY: 71.012
    readonly property real armLen: 146.348          // pivot -> stylus
    readonly property real armDist: 134.844         // pivot -> spindle
    readonly property real grooveStart: 92.6        // radius of the first music groove
    readonly property real grooveEnd: 40.5          // radius of the last one
    readonly property real clearAngle: 15           // arm swing below which it is off the record
    readonly property real rpm: 200                 // 33 1/3 rpm, degrees per second
    readonly property var shadowDir: [0.583, 0.764] // shadow offset per point of height

    // arm swing (degrees clockwise from its rest) that puts the stylus at radius r
    function armFor(r) {
        var toCentre = Math.atan2(centreY - pivotY, centreX - pivotX)
        var inner = Math.acos((armDist * armDist + armLen * armLen - r * r) / (2 * armDist * armLen))
        return (toCentre - inner) * 180 / Math.PI - 90
    }
    function grooveFor(p) {
        var q = Math.max(0, Math.min(1, isFinite(p) ? p : 0))
        return grooveStart - (grooveStart - grooveEnd) * q
    }
    readonly property real playAngle: armFor(grooveFor(live ? progress : 0.32))

    // ─── state ──────────────────────────────────────────────────────────────
    property real recordIn: 0            // 0 away .. 1 on the platter
    property real armAngle: 0            // swing from the rest, degrees clockwise
    property real armLift: 1             // 1 raised (or on its rest) .. 0 stylus in the groove
    property real discAngle: 0           // label and strobe dots
    property real speed: 0               // degrees per second
    property real spinTarget: 0
    property real rampFrom: 0
    property double rampStart: 0
    property real rampDur: 0
    property string recordKey: ""        // the album of the record on the platter
    property string labelArt: ""         // its artwork
    property bool engaged: false         // the arm has been over this record
    property bool waitClear: false       // the record waits for the arm to leave
    property bool artHold: false         // the next record waits for its label (at most 1.5 s)
    property real glideRate: 0           // degrees per second of the arm along the groove

    // nothing is loaded before the scene has a size (a Loader sizes it after
    // it completes): no 1 px decodes followed by the real ones
    function img(n) { return root.s > 0 ? root.assetsBase + n : "" }

    function reset() {
        recAnim.stop(); armSwing.stop(); armCue.stop(); artTimeout.stop()
        recordIn = 0; armAngle = 0; armLift = 1
        speed = 0; spinTarget = 0; rampDur = 0
        engaged = false; waitClear = false; artHold = false
        recordKey = mediaKey; labelArt = artwork
    }
    function still() {
        recAnim.stop(); armSwing.stop(); armCue.stop(); artTimeout.stop()
        recordIn = 1; armAngle = playAngle; armLift = 0
        speed = 0; spinTarget = 0; rampDur = 0
        discAngle = 38
        engaged = true; waitClear = false; artHold = false
        recordKey = mediaKey; labelArt = artwork
    }

    function setSpin(t, hurry) {
        if (t === spinTarget) return
        rampFrom = speed
        rampStart = Date.now()
        spinTarget = t
        rampDur = (t > speed ? 900 : (hurry ? 650 : 1200)) * Math.abs(t - speed) / rpm
    }
    function tick() {
        var now = Date.now()
        var dt = Math.min(0.1, (now - spinTimer.last) / 1000)
        spinTimer.last = now
        var k = rampDur > 0 ? Math.min(1, (now - rampStart) / rampDur) : 1
        var v = k >= 1 ? spinTarget : rampFrom + (spinTarget - rampFrom) * (0.5 - 0.5 * Math.cos(Math.PI * k))
        discAngle = (discAngle + (speed + v) / 2 * dt) % 360
        var reached = v === spinTarget && speed !== spinTarget
        speed = v
        // in the groove the arm glides after the music at the pace of the
        // last progress step (the frame is drawn anyway): no 1 Hz steps
        if (engaged && armLift <= 0 && !armCue.running && !armSwing.running) {
            var e = playAngle - armAngle
            if (Math.abs(e) > 1.5) Qt.callLater(step)
            else if (e !== 0) armAngle += Math.sign(e) * Math.min(Math.abs(e), glideRate * dt)
        }
        if (reached && spinTarget > 0) step()
    }

    function animRecord(to) {
        recAnim.stop()
        var dur = to > 0 ? 750 * (1 - recordIn) : 300 * recordIn
        if (dur < 16) { recordIn = to; Qt.callLater(step); return }
        recAnim.to = to
        recAnim.duration = dur
        recAnim.easing.type = to > 0 ? Easing.OutCubic : Easing.InQuad
        recAnim.start()
    }
    function swing(to, hurry) {
        var d = Math.abs(armAngle - to)
        armSwing.to = to
        armSwing.duration = hurry ? Math.max(220, 560 * d / 49) : Math.max(300, Math.min(1300, 1100 * d / 27))
        armSwing.start()
    }
    function cue(to, hurry) {
        armCue.to = to
        armCue.duration = (to > 0 ? (hurry ? 150 : 300) : 450) * Math.abs(armLift - to)
        armCue.easing.type = to > 0 ? Easing.OutQuad : Easing.OutCubic
        if (armCue.duration < 16) { armLift = to; Qt.callLater(step); return }
        armCue.start()
    }
    function driveArm(ta, tl, hurry) {
        if (armSwing.running) {
            if (Math.abs(armSwing.to - ta) < 1.5) return       // already on its way
            armSwing.stop()
        }
        var d = Math.abs(armAngle - ta)
        // in the groove the arm follows the music (tick() glides it); a jump
        // (seek, next track) lifts it, moves it and lowers it again
        var tracking = armLift <= 0 && !armCue.running && tl === 0
        if (d > (tracking ? 1.5 : 0.3)) {
            if (armLift < 1) {
                if (!(armCue.running && armCue.to === 1)) { armCue.stop(); cue(1, hurry) }
                return
            }
            swing(ta, hurry)
            return
        }
        if (!tracking) armAngle = ta
        if (armCue.running) {
            if (armCue.to === tl) return
            armCue.stop()
        }
        if (armLift !== tl) cue(tl, hurry)
    }

    // The director: compares what is on screen with what should be and starts
    // the next bounded move. Called on every input change and when a move ends.
    function step() {
        if (!live) { still(); return }
        if (!active) { reset(); return }
        var want = hasTrack && recordKey === mediaKey
        var seated = want && recordIn >= 1
        setSpin(seated && playing ? rpm : 0, !want)

        var ta = 0, tl = 1
        if (seated) {
            var atSpeed = spinTarget > 0 && speed >= spinTarget
            if (playing && atSpeed) engaged = true
            if (engaged) { ta = playAngle; tl = playing && atSpeed ? 0 : 1 }
        } else {
            engaged = false
        }
        driveArm(ta, tl, !want)

        waitClear = false
        if (want) {
            if (recordIn < 1 && !(recAnim.running && recAnim.to === 1)) {
                // a new record comes in with its label, not with the old one
                if (recordIn <= 0 && artHold && labelArt !== "" && artNow.status === Image.Loading) return
                if (armAngle <= clearAngle) animRecord(1)
                else waitClear = true
            }
        } else if (recordIn > 0) {
            if (!(recAnim.running && recAnim.to === 0)) {
                if (armAngle <= clearAngle) animRecord(0)
                else waitClear = true
            }
        } else if (recordKey !== mediaKey) {
            // the old record is off: the next one
            recordKey = mediaKey
            artPrev.source = ""
            labelArt = artwork
            artHold = true
            artTimeout.restart()
            if (hasTrack) Qt.callLater(step)
        }
    }
    function syncArt() { if (recordKey === mediaKey) labelArt = artwork }

    onActiveChanged: Qt.callLater(step)
    onLiveChanged: Qt.callLater(step)
    onPlayingChanged: Qt.callLater(step)
    onHasTrackChanged: Qt.callLater(step)
    onMediaKeyChanged: Qt.callLater(step)
    onPlayAngleChanged: {
        glideRate = Math.max(0.02, Math.abs(playAngle - armAngle))
        if (engaged) Qt.callLater(step)
    }
    onArtworkChanged: Qt.callLater(syncArt)
    onArmAngleChanged: if (waitClear && armAngle <= clearAngle) Qt.callLater(step)
    Component.onCompleted: { if (live) reset(); step() }

    NumberAnimation { id: recAnim; target: root; property: "recordIn"; onFinished: Qt.callLater(root.step) }
    NumberAnimation { id: armSwing; target: root; property: "armAngle"; easing.type: Easing.InOutCubic; onFinished: Qt.callLater(root.step) }
    NumberAnimation { id: armCue; target: root; property: "armLift"; onFinished: Qt.callLater(root.step) }
    Timer { id: artTimeout; interval: 1500; onTriggered: { root.artHold = false; Qt.callLater(root.step) } }
    Timer {
        id: spinTimer
        interval: 33; repeat: true
        running: root.live && root.active && (root.spinTarget > 0 || root.speed > 0)
        property double last: 0
        onRunningChanged: if (running) last = Date.now()
        onTriggered: root.tick()
    }

    // ─── drawing ────────────────────────────────────────────────────────────
    // An image placed by its rectangle in base points, decoded at the size it
    // is shown at.
    component Part: Image {
        property real rx: 0
        property real ry: 0
        property real rw: 1
        property real rh: 1
        x: root.ox + rx * root.s
        y: root.oy + ry * root.s
        width: rw * root.s
        height: rh * root.s
        sourceSize.width: Math.max(1, Math.round(rw * root.decodeScale))
        sourceSize.height: Math.max(1, Math.round(rh * root.decodeScale))
        smooth: true
        asynchronous: true
        retainWhileLoading: true     // a resize reloads it: keep the old one meanwhile
    }

    Part { source: root.img("plinth_shadow.png"); rx: 56; ry: -4; rw: 408; rh: 276 }
    Part { source: root.img("plinth.png"); rx: 80; ry: 12; rw: 360; rh: 232 }
    Part { source: root.img("platter.png"); rx: 95.5; ry: 23.5; rw: 209; rh: 209 }
    // strobe dots: they turn while the platter is slow; at speed the eye sees
    // a blurred ring (still), and fine dots stepped at 30 Hz would strobe
    Part {
        id: dots
        source: root.img("dots.png"); rx: 95.5; ry: 23.5; rw: 209; rh: 209
        rotation: root.discAngle
        opacity: 1 - Math.max(0, Math.min(1, (root.speed - 15) / 50))
        visible: opacity > 0
    }
    Part {
        source: root.img("dots_blur.png"); rx: 95.5; ry: 23.5; rw: 209; rh: 209
        opacity: 1 - dots.opacity
        visible: opacity > 0
    }

    // the record's shadow: far and faint while it comes down, then a contact shadow
    Part {
        readonly property real h: 1.4 + 14 * (1 - root.recordIn)
        source: root.img("record_shadow.png")
        rx: 89.5 + root.shadowDir[0] * h; ry: 17.5 + root.shadowDir[1] * h; rw: 221; rh: 221
        visible: root.recordIn > 0
        scale: 1 + 0.10 * (1 - root.recordIn)
        opacity: Math.min(1, root.recordIn * 2) * (0.62 - 0.30 * (1 - root.recordIn))
    }

    // the record, its label and the light on them; flattened into one layer
    // only while it is coming down or going away, so it fades as one piece
    Item {
        id: disc
        x: root.ox + 103 * root.s; y: root.oy + 31 * root.s
        width: 194 * root.s; height: 194 * root.s
        visible: root.recordIn > 0
        scale: 1 + 0.12 * (1 - root.recordIn)
        opacity: Math.min(1, root.recordIn * 3)
        layer.enabled: root.recordIn > 0 && root.recordIn < 1
        layer.smooth: true
        layer.textureSize: Qt.size(Math.max(1, Math.round(width * root.devScale)), Math.max(1, Math.round(height * root.devScale)))

        Item {
            id: label
            x: 64 * root.s; y: 64 * root.s
            width: 66 * root.s; height: 66 * root.s
            rotation: root.discAngle
            readonly property int px: Math.max(1, Math.round(66 * root.decodeScale))
            Image {
                anchors.fill: parent
                source: root.img("label.png")
                sourceSize.width: label.px; sourceSize.height: label.px
                smooth: true; asynchronous: true; retainWhileLoading: true
                visible: root.labelArt === "" || (artNow.status !== Image.Ready && artPrev.status !== Image.Ready)
            }
            // 🚨 two images: radio artwork URLs change every ten seconds; the new
            // one loads hidden and replaces the old one only once it is ready
            Image {
                id: artPrev
                anchors.fill: parent
                fillMode: Image.PreserveAspectCrop
                sourceSize.width: label.px; sourceSize.height: label.px
                smooth: true; asynchronous: false; cache: true
                visible: root.labelArt !== "" && artNow.status !== Image.Ready && status === Image.Ready
            }
            Image {
                id: artNow
                anchors.fill: parent
                source: root.labelArt
                fillMode: Image.PreserveAspectCrop
                sourceSize.width: label.px; sourceSize.height: label.px
                smooth: true; asynchronous: true; cache: true
                visible: root.labelArt !== "" && status === Image.Ready
                onStatusChanged: {
                    if (status === Image.Ready) artPrev.source = source
                    if (status !== Image.Loading && root.artHold) { root.artHold = false; Qt.callLater(root.step) }
                }
            }
        }
        Image {
            x: 64 * root.s; y: 64 * root.s; width: 66 * root.s; height: 66 * root.s
            source: root.img("label_shade.png")
            sourceSize.width: label.px; sourceSize.height: label.px
            smooth: true; asynchronous: true; retainWhileLoading: true
        }
        Image {
            anchors.fill: parent
            source: root.img("record.png")
            sourceSize.width: Math.max(1, Math.round(194 * root.decodeScale))
            sourceSize.height: Math.max(1, Math.round(194 * root.decodeScale))
            smooth: true; asynchronous: true; retainWhileLoading: true
        }
    }
    Part { source: root.img("spindle.png"); rx: 195; ry: 123; rw: 10; rh: 10 }

    // tone arm and its shadow, turning around the pivot; raised it looks a
    // little larger and its shadow falls further away
    Part {
        readonly property real h: 4.2 + 3.4 * root.armLift
        source: root.img("arm_shadow.png")
        rx: root.pivotX - 20 + root.shadowDir[0] * h; ry: root.pivotY - 55 + root.shadowDir[1] * h; rw: 48; rh: 220
        opacity: 0.72 - 0.20 * root.armLift
        transform: [
            Scale { origin.x: 20 * root.s; origin.y: 55 * root.s; xScale: 1 + 0.02 * root.armLift; yScale: 1 + 0.02 * root.armLift },
            Rotation { origin.x: 20 * root.s; origin.y: 55 * root.s; angle: root.armAngle }
        ]
    }
    Part {
        source: root.img("arm.png")
        rx: root.pivotX - 14; ry: root.pivotY - 49; rw: 36; rh: 208
        transform: [
            Scale { origin.x: 14 * root.s; origin.y: 49 * root.s; xScale: 1 + 0.03 * root.armLift; yScale: 1 + 0.03 * root.armLift },
            Rotation { origin.x: 14 * root.s; origin.y: 49 * root.s; angle: root.armAngle }
        ]
    }

    // the LED: lit while the motor runs
    Part {
        id: led
        source: root.img("led_on.png")
        rx: 118; ry: 198.5; rw: 14; rh: 14
        opacity: !root.live || root.spinTarget > 0 ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { enabled: root.live; NumberAnimation { duration: 250 } }
    }
}
