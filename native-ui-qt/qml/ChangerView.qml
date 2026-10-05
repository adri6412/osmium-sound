// The albums as the discs of a CD changer (Settings → Library, or the button
// in the crumb bar): the discs stand in a row like in the changer's file, the
// one in front facing us with its album printed on the label, the others
// turned edge-on; the changer itself (the Now Playing scene, AnimChanger.qml)
// stands below, live. Flip through with a finger, the wheel, the arrows or
// the remote. The discs already in the changer wear a gold ring and their
// number. A tap on the front disc (OK on the remote) puts it in the changer:
// it flies into the changer's window and becomes the next disc; a tap on a
// loaded one takes it out again. "Done" plays them one after the other
// (App.changerLoad: discs added to those playing join the queue), the Now
// Playing at full screen on the changer; "Clear" empties the changer and its
// queue (App.changerClear). A long press opens the album's menu, as in the
// grid.
//
// Like Cover Flow, only the discs in sight exist and each keeps its album
// while it is in view: a step reloads one picture. Nothing repaints while
// the row stands still.
import QtQuick
import QtQuick.Effects
import Hifi
import Hifi.Ui

Item {
    id: root
    signal rowLongPress(int row, real x, real y)
    property real devScale: 1
    readonly property int count: Library.count
    clip: true
    readonly property string art: "file://" + Sys.assets + "/anim/changer/"
    function srcOf(it) { return it && it.art ? Api.lmsBase + "/music/" + it.art + "/cover?size=" + px : "" }

    // ─── geometry ──────────────────────────────────────────────────────────
    readonly property real cs: Math.max(90, Math.min(Math.round(height * 0.36), Math.round(width * 0.2)))   // the front disc
    readonly property real cx: width / 2
    readonly property real discY: 16 + Math.round(cs * 0.08)        // room for a loaded disc to rise
    readonly property real maxAngle: 74
    readonly property real halfTurned: cs / 2 * Math.cos(maxAngle * Math.PI / 180)
    readonly property real off: cs / 2 + halfTurned + cs * 0.07    // the first turned disc's centre
    readonly property real gap: cs * 0.09                          // between turned discs: a file
    readonly property int side: Math.max(0, Math.min(14, Math.ceil((width / 2 - off + halfTurned) / gap) + 1))
    readonly property int slots: 2 * side + 1
    readonly property int px: Theme.coverPx(cs)
    readonly property real captionY: discY + cs + 8
    // the changer below the row, as large as the rest of the height allows
    readonly property real boxY: captionY + 46
    readonly property rect box: Qt.rect(8, boxY, width - 16, Math.max(40, height - boxY - 6))
    // where its window is, for the discs flying in (AnimChanger: a 600 x 260
    // stage fitted and centred in its box, the window centred at 235.5, 106)
    readonly property real stageS: Math.min(box.width / 600, box.height / 260)
    // the drive's opening at the top of the window, at the loader: where a
    // disc put in reaches the scene, which takes it down into its slot
    // (AnimChanger: loader x 255.5; the disc's centre at dropStart 0.55 of
    // the way up is 94 - 0.55 * 150 into the window, which starts at 25.5)
    readonly property point slotIn: Qt.point(box.x + (box.width - 600 * stageS) / 2 + 255.5 * stageS,
                                             box.y + (box.height - 260 * stageS) / 2 + (25.5 + 94 - 0.55 * 150) * stageS)
    // there it stands nearly edge-on, as the discs at the loader do
    readonly property real slotTurn: 84

    // ─── position (as in Cover Flow: pos in albums, a spring between) ──────
    property real pos: 0
    readonly property int cur: Math.max(0, Math.min(count - 1, Math.round(pos)))
    property bool dragging: false
    Spring { id: sp; stiffness: 170; damping: 24; rate: Theme.motionRate; onValueChanged: if (!root.dragging) root.pos = value }
    function goTo(i, now) {
        i = Math.max(0, Math.min(count - 1, Math.round(i)))
        if (now) { sp.set(i); pos = i } else { if (!dragging) sp.set(pos); sp.to = i }
    }
    function step(d) { goTo((sp.running ? sp.to : cur) + d) }
    function scrollToRow(row) { goTo(row, true) }
    function scrollTop() { goTo(0, true) }
    Connections {
        target: Library
        function onLoaded() { if (root.pos > root.count - 1) root.goTo(0, true) }
        function onCountChanged() { if (root.pos > root.count - 1) root.goTo(Math.max(0, root.count - 1), true) }
        function onFilterChanged() { root.goTo(0, true) }
    }
    // 🚨 see CoverFlow: Library.get() is a call, rev makes the slots read again
    readonly property int rev: Library.rev
    readonly property var curItem: (root.rev, root.count > 0 ? Library.get(root.cur) : null)

    // ─── the discs put in the changer, in order ────────────────────────────
    // [{ id, text, art }]: disc 1 is the first one put in. It starts as what
    // the changer holds (App.changerDiscs) and follows it when that changes;
    // a disc on its way (flying into the window) is in `flights` until it
    // lands.
    property var chosen: []
    function fromChanger() {
        chosen = Ui.app ? Ui.app.changerDiscs.map(function(d) { return { id: d.id, text: d.title, art: d.art || "" } }) : []
    }
    Component.onCompleted: fromChanger()
    Connections {
        target: Ui.app
        function onChangerDiscsChanged() { root.fromChanger() }
    }
    // what Done would change: discs added or taken out since the last load
    readonly property bool changed: {
        var held = Ui.app ? Ui.app.changerDiscs : []
        if (flights.count > 0 || held.length !== chosen.length) return true
        for (var i = 0; i < held.length; i++) if (held[i].id !== chosen[i].id) return true
        return false
    }
    function chosenAt(id) {
        for (var i = 0; i < chosen.length; i++) if (chosen[i].id === id) return i
        return -1
    }
    function flightOf(id) {
        for (var i = 0; i < flights.count; i++) if (flights.get(i).albumId === id) return i
        return -1
    }
    function toggle(k) {
        var it = Library.get(k)
        if (!it || !it.id) return
        var id = String(it.id)
        if (flightOf(id) >= 0) return
        var i = chosenAt(id)
        if (i >= 0) { var c = chosen.slice(); c.splice(i, 1); chosen = c; return }
        if (chosen.length + flights.count >= 101) { Ui.toast.show(Tr.t("player.changer.full")); return }
        // the changer turns its file to the next empty slot while the disc flies
        if (changer.scene && changer.scene.prepare) changer.scene.prepare(chosen.length + flights.count)
        flights.append({ albumId: id, text: it.text, art: it.art || "", sub: it.sub || "" })
    }
    // a disc reached the window: it is in the changer now
    function landed(id) {
        var f = flightOf(id)
        if (f < 0) return
        var it = flights.get(f)
        // first the scene (the slot stays empty until the disc comes down),
        // then the list that puts the album on the disc in that slot
        if (changer.scene && changer.scene.insert) changer.scene.insert(chosen.length)
        var c = chosen.slice()
        c.push({ id: it.albumId, text: it.text, art: it.art, sub: it.sub })
        chosen = c
        flights.remove(f)
        if (doneWanted && flights.count === 0) done()
    }
    // Done: play them, one after the other (the discs still flying first)
    property bool doneWanted: false
    function done() {
        if (flights.count > 0) { doneWanted = true; return }
        doneWanted = false
        if (!chosen.length) return
        if (Ui.app) Ui.app.changerLoad(chosen)
    }
    // Clear: the changer empty, nothing on its way, its queue cleared
    function clearAll() {
        flights.clear()
        doneWanted = false
        chosen = []
        if (Ui.app) Ui.app.changerClear()
    }

    Rectangle { anchors.fill: parent; color: Theme.dark }

    // ─── the changer, live, below the discs ────────────────────────────────
    NpAnimation {
        id: changer
        x: root.box.x; y: root.box.y; width: root.box.width; height: root.box.height
        kind: "changer"
        // the discs as they are put in, not those of the last load; the file
        // holds only real discs, so their empty slots show
        changerDiscs: root.chosen.map(function(d) { return { album: d.text, art: d.art ? Api.lmsBase + "/music/" + d.art + "/cover?size=300" : "" } })
        changerSparse: true
        active: root.visible && !!Ui.app && !Ui.app.expanded
        devScale: root.devScale
    }
    // its top fades into the dark, so the row of discs stands in front
    Rectangle {
        x: 0; y: root.box.y - 1; width: root.width; height: root.box.height * 0.22
        gradient: Gradient {
            GradientStop { position: 0.0; color: Theme.dark }
            GradientStop { position: 1.0; color: "transparent" }
        }
    }

    // one mask for every disc: the printable ring of the label
    Image {
        id: printMask
        width: root.cs; height: root.cs
        visible: false
        source: root.art + "disc-mask.png"
        sourceSize.width: Math.ceil(root.cs * root.devScale); sourceSize.height: Math.ceil(root.cs * root.devScale)
        layer.enabled: true
        layer.smooth: true
        layer.textureSize: Qt.size(Math.ceil(root.cs * root.devScale), Math.ceil(root.cs * root.devScale))
    }
    // a disc: the album on its label (a printed label when it has no cover),
    // the clear hub and rim over it
    component Disc: Item {
        id: d
        property string src: ""
        property int label: 0
        width: root.cs; height: root.cs
        Image {
            anchors.fill: parent
            source: root.art + "disc-lbl-" + d.label + ".png"
            sourceSize.width: root.px; sourceSize.height: root.px
            smooth: true; asynchronous: true
            visible: artImg.status !== Image.Ready
        }
        Image {
            id: artImg
            anchors.fill: parent
            visible: false
            source: d.src
            asynchronous: true; cache: true; smooth: true
            fillMode: Image.PreserveAspectCrop
            sourceSize.width: root.px; sourceSize.height: root.px
            layer.enabled: true
            layer.smooth: true
            layer.textureSize: Qt.size(Math.ceil(root.cs * root.devScale), Math.ceil(root.cs * root.devScale))
        }
        MultiEffect {
            anchors.fill: parent
            source: artImg
            visible: artImg.status === Image.Ready
            maskEnabled: true
            maskSource: printMask
            maskThresholdMin: 0.5
            maskSpreadAtMin: 1.0
        }
        Image {
            anchors.fill: parent
            visible: artImg.status === Image.Ready
            source: root.art + "disc-gloss.png"
            sourceSize.width: root.px; sourceSize.height: root.px
            smooth: true; asynchronous: true
        }
    }

    // ─── the row ───────────────────────────────────────────────────────────
    Item {
        id: flow
        anchors.fill: parent
        Repeater {
            model: root.slots
            Item {
                id: slot
                required property int index
                readonly property int base: Math.round(root.pos) - root.side
                readonly property int k: base + (((index - base) % root.slots) + root.slots) % root.slots
                readonly property real d: k - root.pos
                readonly property real a: Math.max(-1, Math.min(1, d))
                readonly property bool has: k >= 0 && k < root.count
                readonly property var it: (root.rev, has ? Library.get(k) : null)
                readonly property int order: (root.chosen, it ? root.chosenAt(it.id) : -1)
                readonly property bool front: Math.abs(d) < 0.5
                visible: has && Math.abs(d) <= root.side + 0.5
                x: root.cx - root.cs / 2 + (Math.abs(d) < 1 ? d * root.off : (d > 0 ? 1 : -1) * (root.off + (Math.abs(d) - 1) * root.gap))
                // a loaded disc stands a little out of the row
                y: root.discY - (order >= 0 ? Math.round(root.cs * 0.07) : 0)
                Behavior on y { NumberAnimation { duration: Theme.dur(180); easing.type: Easing.OutCubic } }
                width: root.cs; height: root.cs
                z: 100 - Math.abs(d)
                transform: Rotation {
                    origin.x: root.cs / 2; origin.y: root.cs / 2
                    axis { x: 0; y: 1; z: 0 }
                    angle: -slot.a * root.maxAngle
                }
                Disc {
                    src: root.srcOf(slot.it)
                    label: ((slot.k * 7 + 3) % 10 + 10) % 10
                }
                // the turned discs stand in the shade of the file
                Rectangle {
                    anchors.fill: parent; radius: width / 2
                    color: Theme.black
                    opacity: Math.min(0.62, 0.42 * Math.abs(slot.a) + 0.03 * Math.max(0, Math.abs(slot.d) - 1))
                }
                // loaded: a gold ring and its disc number
                Rectangle {
                    visible: slot.order >= 0
                    anchors.fill: parent; anchors.margins: -3; radius: width / 2
                    color: "transparent"; border.width: 2.5; border.color: Theme.gold
                }
                Rectangle {
                    visible: slot.order >= 0
                    x: parent.width * 0.80 - width / 2; y: parent.height * 0.08 - height / 2
                    width: Math.max(24, root.cs * 0.17); height: width; radius: width / 2
                    color: Theme.gold
                    Text {
                        anchors.centerIn: parent
                        text: slot.order + 1
                        color: Theme.black; font.family: Theme.font; font.pixelSize: Math.round(parent.height * 0.52); font.bold: true
                    }
                }
            }
        }
    }

    // ─── touch, mouse and the remote over the row ──────────────────────────
    MouseArea {
        id: area
        x: 0; y: 0; width: root.width; height: root.captionY
        property real x0: 0
        property real pos0: 0
        property bool moved: false
        property real lastX: 0
        property real lastT: 0
        property real vel: 0
        readonly property real dragPx: root.cs * 0.32               // finger travel per disc
        pressAndHoldInterval: 500
        // With the remote this is the front disc: left and right flip, OK
        // loads it (or takes it out), down goes to "Load and play".
        property bool navigable: root.count > 0
        function navKey(dir) {
            if (dir === "left" || dir === "right") { root.step(dir === "left" ? -1 : 1); return true }
            if (dir === "down" && root.chosen.length > 0) { Nav.focus(loadTap); return true }
            return false
        }
        function navOk() { if (root.count > 0) root.toggle(root.cur); return true }
        NavRing {
            fill: false
            radius: root.cs / 2 + 6
            x: root.cx - root.cs / 2 - 6; y: root.discY - 6
            width: root.cs + 12; height: root.cs + 12
        }
        function hit(mx) {
            var u = Math.abs(mx - root.cx), s = mx > root.cx ? 1 : -1
            if (u <= root.cs / 2) return root.cur
            var j = u < root.off + root.halfTurned ? 1 : 2 + Math.floor((u - root.off - root.halfTurned) / root.gap)
            return Math.max(0, Math.min(root.count - 1, root.cur + s * j))
        }
        onPressed: (m) => { moved = false; x0 = m.x; pos0 = root.pos; lastX = m.x; lastT = Sys.now(); vel = 0; sp.set(root.pos) }
        onPositionChanged: (m) => {
            if (!pressed) return
            if (!moved && Math.abs(m.x - x0) > 8) { moved = true; root.dragging = true }
            if (!moved) return
            var t = Sys.now(), dt = t - lastT
            if (dt > 0) { vel = 0.6 * vel + 0.4 * (-(m.x - lastX) / dragPx) * 1000 / dt; lastX = m.x; lastT = t }
            var p = pos0 - (m.x - x0) / dragPx
            if (p < 0) p = p / 3; else if (p > root.count - 1) p = (root.count - 1) + (p - (root.count - 1)) / 3
            root.pos = p
        }
        onReleased: {
            if (!moved) return
            var v = Sys.now() - lastT > 80 ? 0 : vel
            var target = root.pos + v * 0.22
            root.dragging = false
            sp.set(root.pos)
            root.goTo(target)
        }
        onCanceled: if (moved) { root.dragging = false; sp.set(root.pos); root.goTo(root.pos) }
        onClicked: (m) => {
            if (moved || root.count === 0) return
            var k = hit(m.x)
            if (k === root.cur && Math.abs(root.pos - root.cur) < 0.02) root.toggle(k)
            else root.goTo(k)
        }
        onPressAndHold: (m) => { if (!moved && root.count > 0) root.rowLongPress(hit(m.x), m.x, m.y) }
        onWheel: (w) => {
            var dd = w.angleDelta.y !== 0 ? w.angleDelta.y : -w.angleDelta.x
            wheelAcc += dd
            while (wheelAcc >= 120) { wheelAcc -= 120; root.step(-1) }
            while (wheelAcc <= -120) { wheelAcc += 120; root.step(1) }
        }
        property real wheelAcc: 0
    }

    // the arrows at the two ends, held: one disc after another
    Repeater {
        model: 2
        Item {
            id: arrow
            required property int index
            readonly property int dir: index === 0 ? -1 : 1
            readonly property bool can: root.count > 1 && (dir < 0 ? root.cur > 0 : root.cur < root.count - 1)
            x: index === 0 ? 14 : root.width - 14 - width
            y: root.discY + root.cs / 2 - height / 2
            width: 44; height: 44
            z: 200
            opacity: can ? 1 : 0.28
            Rectangle {
                anchors.fill: parent; radius: 22
                color: arrowTap.mix(Theme.wa(0.08), Theme.goldA(0.25))
                border.width: 1; border.color: arrowTap.mix(Theme.wa(0.12), Theme.goldA(0.6))
                scale: arrowTap.tapScale
            }
            Icon { anchors.centerIn: parent; anchors.horizontalCenterOffset: arrow.dir * 1; name: arrow.dir < 0 ? "chevron-left" : "chevron-right"; size: 24; color: Theme.gold; scale: arrowTap.tapScale }
            Tap {
                id: arrowTap; tap: 0.9; grow: 6
                navigable: false
                onClicked: root.step(arrow.dir)
                Timer {
                    running: arrowTap.pressed; repeat: true; interval: 420
                    onTriggered: { interval = 130; root.step(arrow.dir) }
                    onRunningChanged: if (!running) interval = 420
                }
            }
        }
    }

    // ─── under the row: the album in front, what is loaded, Load ───────────
    Item {
        id: caption
        x: 0; y: root.captionY; width: root.width; height: 40
        z: 150
        readonly property real sideW: Math.min(230, (width - 260) / 2)
        Text {
            x: caption.sideW + 12; width: parent.width - 2 * caption.sideW - 24; y: 0; height: 21
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
            text: root.count === 0 && Library.state === 2 ? Tr.t("player.changer.empty") : root.curItem ? root.curItem.text : ""
            elide: Text.ElideRight
            color: Theme.white; font.family: Theme.font; font.pixelSize: 15; font.bold: true
        }
        Text {
            x: caption.sideW + 12; width: parent.width - 2 * caption.sideW - 24; y: 21; height: 17
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
            text: root.curItem ? root.curItem.sub : ""; elide: Text.ElideRight
            color: Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 12
        }
        // left: how many are loaded (or how to load them)
        Text {
            x: 16; width: caption.sideW - 8; y: 0; height: 38
            verticalAlignment: Text.AlignVCenter; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight
            text: root.chosen.length > 0 ? Tr.tf("player.changer.chosen", "count", String(root.chosen.length))
                                         : Tr.t("player.changer.hint")
            color: root.chosen.length > 0 ? Theme.gold : Theme.silverA(0.5)
            font.family: Theme.font; font.pixelSize: root.chosen.length > 0 ? 14 : 11; font.bold: root.chosen.length > 0
        }
        // right: clear, and load and play
        Row {
            anchors.right: parent.right; anchors.rightMargin: 16
            y: 3; height: 32; spacing: 8
            visible: root.chosen.length > 0
            Rectangle {
                width: clearText.implicitWidth + 24; height: 32; radius: 16
                color: clearTap.mix(Theme.wa(0.06), Theme.wa(0.14))
                scale: clearTap.tapScale
                Text { id: clearText; anchors.centerIn: parent; text: Tr.t("player.changer.clear"); color: Theme.silverA(0.8); font.family: Theme.font; font.pixelSize: 12 }
                Tap { id: clearTap; tap: 0.94; onClicked: root.clearAll() }
            }
            Rectangle {
                width: loadRow.implicitWidth + 28; height: 32; radius: 16
                color: loadTap.mix(Theme.gold, Theme.goldA(0.75))
                scale: loadTap.tapScale
                Row {
                    id: loadRow
                    anchors.centerIn: parent; spacing: 6
                    Icon { anchors.verticalCenter: parent.verticalCenter; name: "play"; filled: true; size: 13; color: Theme.black }
                    Text { anchors.verticalCenter: parent.verticalCenter; text: Tr.t("player.changer.done"); color: Theme.black; font.family: Theme.font; font.pixelSize: 13; font.bold: true }
                }
                Tap { id: loadTap; tap: 0.94; onClicked: root.done() }
            }
        }
    }

    // ─── a disc put in: it flies into the changer's window ─────────────────
    // A ListModel, not an array: a new flight must not restart the others.
    ListModel { id: flights }
    onVisibleChanged: if (!visible) { while (flights.count > 0) landed(flights.get(0).albumId) }
                      else fromChanger()
    Repeater {
        model: flights
        Item {
            id: fly
            required property string albumId
            required property string art
            z: 300
            width: root.cs; height: root.cs
            x: root.cx - root.cs / 2; y: root.discY
            property real turn: 0
            transform: Rotation {
                origin.x: root.cs / 2; origin.y: root.cs / 2
                axis { x: 0; y: 1; z: 0 }
                angle: fly.turn
            }
            Disc { src: fly.art ? Api.lmsBase + "/music/" + fly.art + "/cover?size=" + root.px : ""; label: (root.chosen.length + 3) % 10 }
            // up a little out of the row, then to the drive's opening in the
            // window, shrinking to the size of the discs in the file and
            // turning edge-on like them; there the changer takes it down into
            // its slot (the copy goes the moment the scene's disc appears)
            SequentialAnimation {
                running: true
                NumberAnimation { target: fly; property: "y"; to: root.discY - root.cs * 0.12; duration: Theme.dur(160); easing.type: Easing.OutQuad }
                ParallelAnimation {
                    NumberAnimation { target: fly; property: "x"; to: root.slotIn.x - root.cs / 2; duration: Theme.dur(640); easing.type: Easing.InOutCubic }
                    NumberAnimation { target: fly; property: "y"; to: root.slotIn.y - root.cs / 2; duration: Theme.dur(640); easing.type: Easing.InOutQuad }
                    NumberAnimation { target: fly; property: "scale"; to: Math.max(0.1, 128 * root.stageS / root.cs); duration: Theme.dur(640); easing.type: Easing.InOutQuad }
                    NumberAnimation { target: fly; property: "turn"; to: root.slotTurn; duration: Theme.dur(640); easing.type: Easing.InQuad }
                }
                ScriptAction { script: { fly.opacity = 0; Qt.callLater(root.landed, fly.albumId) } }
            }
        }
    }
}
