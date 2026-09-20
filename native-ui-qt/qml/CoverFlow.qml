// Cover Flow for the albums (Settings → Library, or the button in the crumb
// bar): the covers stand in a row, the current one facing us, the others
// turned away in perspective and mirrored on the floor, like the iPod's.
// Drag with a finger or the mouse, turn the wheel, tap a side cover, hold
// the two arrows or slide the knob under the row; a tap on the front cover
// opens the album, its play button plays it, a long press opens the menu.
//
// Only a handful of slots exist (the covers that fit on screen, plus one):
// each slot keeps the same album while it is in view, so a step reloads
// ONE picture, not all of them. Nothing repaints while the row stands
// still: the spring stops by itself.
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    signal rowTap(int row, bool onPlay)
    signal rowLongPress(int row, real x, real y)
    // the front cover was tapped: the row makes way while the owner flies a
    // copy of the cover (x, y, size in our coordinates) to the album page
    signal expand(int row, real x, real y, real size, string src)
    property real devScale: 1
    readonly property int count: Library.count
    clip: true
    property bool opening: false
    onVisibleChanged: if (visible) opening = false
    function srcOf(it) { return it && it.art ? Api.lmsBase + "/music/" + it.art + "/cover?size=" + px : "" }

    // ─── geometry ──────────────────────────────────────────────────────────
    // the front cover's side, from the height (cover + reflection + the
    // title block) and the width (room for the turned covers)
    readonly property real cs: Math.max(120, Math.min(Math.round((height - 96) / 1.22), Math.round(width * 0.36)))
    readonly property real cx: width / 2
    readonly property real coverY: 18
    readonly property real maxAngle: 60
    readonly property real halfTurned: cs / 2 * Math.cos(maxAngle * Math.PI / 180)   // a turned cover's projected half width
    readonly property real off: cs / 2 + halfTurned          // the first turned cover's centre
    readonly property real gap: cs * 0.2                     // between turned covers
    readonly property int side: Math.max(0, Math.min(9, Math.ceil((width / 2 - off + halfTurned) / gap) + 1))   // turned covers per side
    readonly property int slots: 2 * side + 1
    readonly property int px: Theme.coverPx(cs)

    // ─── position ──────────────────────────────────────────────────────────
    // pos runs in albums: whole numbers at rest, fractions while dragging
    // or between two. cur is the album in front.
    property real pos: 0
    readonly property int cur: Math.max(0, Math.min(count - 1, Math.round(pos)))
    property bool dragging: false
    // the spring drives pos except under the finger (a Binding with `when`
    // would put the old value back each time the finger takes over)
    Spring { id: sp; stiffness: 170; damping: 24; onValueChanged: if (!root.dragging) root.pos = value }
    function goTo(i, now) {
        i = Math.max(0, Math.min(count - 1, Math.round(i)))
        if (now) { sp.set(i); pos = i } else { if (!dragging) sp.set(pos); sp.to = i }
    }
    function step(d) { goTo((sp.running ? sp.to : cur) + d) }
    function scrollToRow(row) { goTo(row, true) }
    function scrollTop() { goTo(0, true) }
    // a new list starts at its first album; a shorter one keeps us inside
    property int gen: 0
    Connections {
        target: Library
        function onLoaded() { root.gen++; root.opening = false; if (root.pos > root.count - 1) root.goTo(0, true) }
        function onCountChanged() { if (root.pos > root.count - 1) root.goTo(Math.max(0, root.count - 1), true) }
    }

    // the album in front: its title and artist under the row
    readonly property var curItem: (root.gen, root.count > 0 ? Library.get(root.cur) : null)

    Rectangle { anchors.fill: parent; color: Theme.dark }

    // ─── the covers ────────────────────────────────────────────────────────
    Item {
        id: flow
        anchors.fill: parent
        Repeater {
            model: root.slots
            Item {
                id: slot
                required property int index
                // the album this slot shows: the one nearest to pos among
                // those congruent to the slot's index, so a step moves one
                // slot from the far end to the other and nothing else reloads
                readonly property int base: Math.round(root.pos) - root.side
                readonly property int k: base + (((index - base) % root.slots) + root.slots) % root.slots
                readonly property real d: k - root.pos
                readonly property real a: Math.max(-1, Math.min(1, d))            // -1..1: how far turned
                readonly property bool has: k >= 0 && k < root.count
                readonly property var it: (root.gen, has ? Library.get(k) : null)
                readonly property bool front: Math.abs(d) < 0.5
                visible: has && Math.abs(d) <= root.side + 0.5 && opacity > 0.002
                // the row makes way for the album that opens (the flying
                // copy covers the front one from the first frame)
                opacity: root.opening ? 0 : 1
                Behavior on opacity { NumberAnimation { duration: 220; easing.type: Easing.OutQuad } }
                x: root.cx - root.cs / 2 + (Math.abs(d) < 1 ? d * root.off : (d > 0 ? 1 : -1) * (root.off + (Math.abs(d) - 1) * root.gap))
                y: root.coverY
                width: root.cs; height: root.cs
                z: 100 - Math.abs(d)
                transform: Rotation {
                    origin.x: root.cs / 2; origin.y: root.cs / 2
                    axis { x: 0; y: 1; z: 0 }
                    angle: -slot.a * root.maxAngle
                }
                readonly property string src: root.srcOf(it)

                // the cover
                DiagonalFallback {
                    anchors.fill: parent; radius: 0
                    visible: art.status !== Image.Ready
                    Icon { anchors.centerIn: parent; name: "disc"; size: root.cs * 0.25; color: Theme.silverA(0.2) }
                    Text {
                        visible: slot.it && !slot.it.art
                        anchors.horizontalCenter: parent.horizontalCenter; y: parent.height * 0.66
                        width: parent.width - 24; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight
                        text: slot.it ? slot.it.text : ""; color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 12
                    }
                }
                Image {
                    id: art
                    anchors.fill: parent
                    source: slot.src
                    asynchronous: true; cache: true; smooth: true
                    fillMode: Image.PreserveAspectCrop
                    // decoded at the size Lyrion serves, once for cover and reflection
                    sourceSize.width: root.px; sourceSize.height: root.px
                }
                // the reflection: the same picture upside down, fading into
                // the floor (the same texture, drawn a second time)
                Image {
                    y: root.cs + 1
                    width: root.cs; height: root.cs
                    source: slot.src
                    asynchronous: true; cache: true; smooth: true
                    fillMode: Image.PreserveAspectCrop
                    sourceSize.width: root.px; sourceSize.height: root.px
                    transform: Scale { origin.y: root.cs / 2; yScale: -1 }
                    visible: art.status === Image.Ready
                }
                Rectangle {
                    y: root.cs + 1
                    width: root.cs; height: root.cs
                    gradient: Gradient {
                        GradientStop { position: 0.0; color: Qt.rgba(0.039, 0.039, 0.039, 0.62) }
                        GradientStop { position: 0.42; color: Theme.dark }
                        GradientStop { position: 1.0; color: Theme.dark }
                    }
                }
                // the turned covers stand in the shade
                Rectangle {
                    anchors.fill: parent
                    color: Theme.black
                    opacity: Math.min(0.6, 0.35 * Math.abs(slot.a) + 0.04 * Math.max(0, Math.abs(slot.d) - 1))
                }
                Rectangle { anchors.fill: parent; color: "transparent"; border.width: 1; border.color: Theme.wa(0.12) }
                // the play button of the front cover (the grid's, same spot)
                Rectangle {
                    visible: slot.front
                    x: parent.width - 8 - 34; y: parent.height - 8 - 34; width: 34; height: 34; radius: 17
                    color: root.playPressed && slot.front ? Theme.gold : Theme.blackA(0.6)
                    opacity: 1 - Math.abs(slot.d) * 1.6
                    Icon { anchors.centerIn: parent; anchors.horizontalCenterOffset: 2; name: "play"; filled: true; size: 15; color: root.playPressed && slot.front ? Theme.black : Theme.white }
                }
            }
        }
    }

    // ─── touch and mouse over the row ──────────────────────────────────────
    property bool playPressed: false
    MouseArea {
        id: area
        x: 0; y: 0; width: parent.width; height: root.coverY + root.cs * 1.3
        property real x0: 0
        property real pos0: 0
        property bool moved: false
        property real lastX: 0
        property real lastT: 0
        property real vel: 0                     // albums per second, from the last moves
        readonly property real dragPx: root.cs * 0.45   // finger travel per album
        pressAndHoldInterval: 500
        // which album is under x: the front cover, or a turned one by the
        // strip of it that stays uncovered by the nearer ones
        function hit(mx) {
            var u = Math.abs(mx - root.cx), s = mx > root.cx ? 1 : -1
            if (u <= root.cs / 2) return root.cur
            var j = u < root.off + root.halfTurned ? 1 : 2 + Math.floor((u - root.off - root.halfTurned) / root.gap)
            return Math.max(0, Math.min(root.count - 1, root.cur + s * j))
        }
        function onPlay(mx, my) {
            var bx = root.cx + root.cs / 2 - 8 - 17, by = root.coverY + root.cs - 8 - 17
            return Math.abs(mx - bx) <= 20 && Math.abs(my - by) <= 20
        }
        onPressed: (m) => {
            moved = false; x0 = m.x; pos0 = root.pos; lastX = m.x; lastT = Sys.now(); vel = 0
            sp.set(root.pos)
            root.playPressed = onPlay(m.x, m.y) && hit(m.x) === root.cur
        }
        onPositionChanged: (m) => {
            if (!pressed) return
            if (!moved && Math.abs(m.x - x0) > 8) { moved = true; root.dragging = true; root.playPressed = false }
            if (!moved) return
            var t = Sys.now(), dt = t - lastT
            if (dt > 0) { vel = 0.6 * vel + 0.4 * (-(m.x - lastX) / dragPx) * 1000 / dt; lastX = m.x; lastT = t }
            var p = pos0 - (m.x - x0) / dragPx
            // past the ends the row gives a little, then holds
            if (p < 0) p = p / 3; else if (p > root.count - 1) p = (root.count - 1) + (p - (root.count - 1)) / 3
            root.pos = p
        }
        onReleased: (m) => {
            root.playPressed = false
            if (!moved) return
            var v = Sys.now() - lastT > 80 ? 0 : vel
            var target = root.pos + v * 0.22
            root.dragging = false
            sp.set(root.pos)
            root.goTo(target)
        }
        onCanceled: { root.playPressed = false; if (moved) { root.dragging = false; sp.set(root.pos); root.goTo(root.pos) } }
        onClicked: (m) => {
            if (moved || root.count === 0) return
            var k = hit(m.x)
            if (k === root.cur && Math.abs(root.pos - root.cur) < 0.02) {
                if (onPlay(m.x, m.y)) root.rowTap(k, true)
                else if (!root.opening) { root.opening = true; root.expand(k, root.cx - root.cs / 2, root.coverY, root.cs, root.srcOf(Library.get(k))) }
            } else root.goTo(k)
        }
        onPressAndHold: (m) => { if (!moved && root.count > 0) root.rowLongPress(hit(m.x), m.x, m.y) }
        onWheel: (w) => {
            var d = w.angleDelta.y !== 0 ? w.angleDelta.y : -w.angleDelta.x
            wheelAcc += d
            while (wheelAcc >= 120) { wheelAcc -= 120; root.step(-1) }
            while (wheelAcc <= -120) { wheelAcc += 120; root.step(1) }
        }
        property real wheelAcc: 0
    }

    // ─── the arrows: glass discs at the two ends, hold to keep going ───────
    Repeater {
        model: 2
        Item {
            id: arrow
            required property int index
            readonly property int dir: index === 0 ? -1 : 1
            readonly property bool can: root.count > 1 && (dir < 0 ? root.cur > 0 : root.cur < root.count - 1)
            x: index === 0 ? 14 : root.width - 14 - width
            y: root.coverY + root.cs / 2 - height / 2
            width: 48; height: 48
            z: 200
            opacity: root.opening ? 0 : (can ? 1 : 0.28)
            Behavior on opacity { NumberAnimation { duration: 200 } }
            Rectangle {
                anchors.fill: parent; radius: 24
                color: arrowTap.mix(Theme.wa(0.08), Theme.goldA(0.25))
                border.width: 1; border.color: arrowTap.mix(Theme.wa(0.12), Theme.goldA(0.6))
                scale: arrowTap.tapScale
            }
            Icon { anchors.centerIn: parent; anchors.horizontalCenterOffset: arrow.dir * 1; name: arrow.dir < 0 ? "chevron-left" : "chevron-right"; size: 26; color: Theme.gold; scale: arrowTap.tapScale }
            Tap {
                id: arrowTap; tap: 0.9; grow: 6
                onClicked: root.step(arrow.dir)
                // held down: one album after another, faster after a moment
                Timer {
                    running: arrowTap.pressed; repeat: true; interval: 420
                    onTriggered: { interval = 130; root.step(arrow.dir) }
                    onRunningChanged: if (!running) interval = 420
                }
            }
        }
    }

    // ─── the title block and the slider ────────────────────────────────────
    Item {
        id: caption
        x: 0; y: root.coverY + root.cs + Math.round(root.cs * 0.32)
        width: root.width; height: root.height - y
        z: 150
        opacity: root.opening ? 0 : 1
        Behavior on opacity { NumberAnimation { duration: 220 } }
        Text {
            x: 24; width: parent.width - 48; y: 0; height: 22
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
            text: root.curItem ? root.curItem.text : ""; elide: Text.ElideRight
            color: Theme.white; font.family: Theme.font; font.pixelSize: 16; font.bold: true
        }
        Text {
            x: 24; width: parent.width - 48; y: 22; height: 18
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
            text: root.curItem ? root.curItem.sub : ""; elide: Text.ElideRight
            color: Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 13
        }
        // the slider: a hairline with a gold knob, the letter of the album
        // above it while it is dragged (the fast way through a long library)
        Item {
            id: slider
            x: 24; width: parent.width - 48 - 60
            y: parent.height - 30; height: 30
            visible: root.count > 1
            readonly property real frac: root.count > 1 ? Math.max(0, Math.min(1, root.pos / (root.count - 1))) : 0
            Rectangle { x: 0; y: 14; width: parent.width; height: 2; radius: 1; color: Theme.wa(0.12) }
            Rectangle { x: 0; y: 14; width: parent.width * slider.frac; height: 2; radius: 1; color: Theme.goldA(0.5) }
            Rectangle {
                x: parent.width * slider.frac - 7; y: 8; width: 14; height: 14; radius: 7
                color: Theme.gold
                scale: sliderArea.pressed ? 1.4 : 1
                Behavior on scale { NumberAnimation { duration: 120 } }
            }
            Rectangle {
                visible: sliderArea.pressed
                x: Math.max(0, Math.min(parent.width - width, parent.width * slider.frac - width / 2)); y: -40
                width: 44; height: 34; radius: 8
                color: Theme.gold
                Text { anchors.centerIn: parent; text: root.count > 0 ? Library.letterOf(root.cur) : ""; color: Theme.black; font.family: Theme.font; font.pixelSize: 18; font.bold: true }
            }
            MouseArea {
                id: sliderArea
                anchors.fill: parent; anchors.topMargin: -10; anchors.bottomMargin: -6
                function at(mx) { return Math.max(0, Math.min(root.count - 1, (mx / slider.width) * (root.count - 1))) }
                onPressed: (m) => { root.dragging = true; root.pos = Math.round(at(m.x)) }
                onPositionChanged: (m) => { if (pressed) root.pos = Math.round(at(m.x)) }
                onReleased: { root.dragging = false; sp.set(root.pos); root.goTo(root.pos) }
                onCanceled: { root.dragging = false; sp.set(root.pos); root.goTo(root.pos) }
            }
        }
        Text {
            x: parent.width - 24 - 56; width: 56; y: parent.height - 30; height: 30
            horizontalAlignment: Text.AlignRight; verticalAlignment: Text.AlignVCenter
            visible: root.count > 1
            text: (root.cur + 1) + " / " + root.count
            color: Theme.silverA(0.45); font.family: Theme.mono; font.pixelSize: 11
        }
    }
}
