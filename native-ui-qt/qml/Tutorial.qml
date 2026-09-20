// The guided tour of the interface: a dimmed screen with a spotlight on one
// element at a time and a card that says what it does. It runs once, at
// the end of the first setup wizard, or on an appliance that already had
// the interface when the update bringing the tour arrives; a file under
// /data remembers that it was shown (Settings → System info replays it).
// It drives the app itself (opens Now Playing for the steps that live there)
// and takes every touch until it ends: a tap on the lit element, or
// anywhere else, goes on to the next step.
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    property bool active: false
    property int step: 0
    readonly property int count: steps.length
    visible: active || fade > 0
    anchors.fill: parent
    signal ended()

    // where "already shown" is written: under /data on the appliance (the
    // partition that survives an image update), next to the settings in
    // development
    readonly property string flagPath: Sys.devMode ? Sys.configDir + "/tutorial-shown" : "/data/hifi-tutorial-shown"
    function wasShown() { return Sys.exists(flagPath) }
    function markShown() { if (!Sys.writeLine(flagPath, "1")) Sys.log("tutorial: could not write " + flagPath) }

    readonly property real cw: width
    readonly property real ch: height
    readonly property real leftW: (cw - 40) * 0.44                  // NowPlaying.leftW
    readonly property real npRx: 20 + leftW + 24                    // NowPlaying.rx
    // Each step: the string key, the lit rectangle (null: none), and what
    // the app must show for it. rect() runs at show time, on the canvas size.
    readonly property var steps: [
        { key: "welcome", rect: null, screen: "home" },
        { key: "miniPlayer", rect: function() { return [0, 40, 340, ch - 40] }, screen: "home" },
        { key: "expand", rect: function() { return [284 - 6, 0, 48 + 12, 40] }, screen: "home" },
        { key: "tabs", rect: function() { return [341, 0, cw - 341 - 48, 40] }, screen: "home" },
        { key: "library", rect: function() { return [341 + 12, 83 + 8, cw - 341 - 24, 3 * (117 + Math.max(0, ch - 600) / 3 + 12) + 54] }, screen: "home" },
        { key: "albumList", rect: function() { return Ui.app.tutorialListRect() }, screen: "albums:grid" },
        { key: "longPress", rect: function() { return Ui.app.tutorialMenuRect() }, screen: "albums:grid" },
        { key: "coverFlow", rect: function() { return Ui.app.tutorialListRect() }, screen: "albums:coverflow" },
        { key: "npLeft", rect: function() { return [20 + leftW / 2 - 70, 6, 70 + 10 + 3 * 36 + 2 * 8 + 12, 50] }, screen: "np" },
        { key: "npRight", rect: function() { return [cw - 20 - 34 * 5 - 32 - 6, 6, 34 * 5 + 32 + 12, 50] }, screen: "np" },
        { key: "npInfo", rect: function() { return [npRx - 8, 46, cw - npRx - 20 + 16, 210] }, screen: "np" },
        { key: "npPanel", rect: function() { return [npRx - 8, 300, cw - npRx - 20 + 16, ch - 300 - 12] }, screen: "np" },
        { key: "done", rect: null, screen: "home" }]

    // the lit rectangle glides from one element to the next
    property real hx: 0
    property real hy: 0
    property real hw: 0
    property real hh: 0
    property bool lit: false
    Behavior on hx { enabled: root.lit; NumberAnimation { duration: Theme.dur(340); easing.type: Easing.InOutCubic } }
    Behavior on hy { enabled: root.lit; NumberAnimation { duration: Theme.dur(340); easing.type: Easing.InOutCubic } }
    Behavior on hw { enabled: root.lit; NumberAnimation { duration: Theme.dur(340); easing.type: Easing.InOutCubic } }
    Behavior on hh { enabled: root.lit; NumberAnimation { duration: Theme.dur(340); easing.type: Easing.InOutCubic } }
    property real fade: 0
    Behavior on fade { NumberAnimation { duration: Theme.dur(260); easing.type: Easing.OutCubic } }
    property real cardA: 0
    Behavior on cardA { NumberAnimation { duration: Theme.dur(200) } }

    function start() {
        step = -1
        active = true
        fade = 1
        lit = false
        go(0)
    }
    function show(i) {
        var s = steps[i]
        if (Ui.app) {
            if (s.screen === "np") Ui.app.setExpanded(true)
            else if (s.screen === "albums:grid") Ui.app.tutorialAlbums("grid")
            else if (s.screen === "albums:coverflow") Ui.app.tutorialAlbums("coverflow")
            else Ui.app.tutorialHome()
        }
        var r = s.rect ? s.rect() : null          // null: nothing to light up (a list still loading)
        if (r) {
            var wasLit = lit
            hx = r[0]; hy = r[1]; hw = r[2]; hh = r[3]
            lit = true
            if (!wasLit) { hx = r[0]; hy = r[1]; hw = r[2]; hh = r[3] }
        } else lit = false
        cardA = 1
    }
    // the card swaps with a short dip so the eye follows the spotlight
    function go(i) {
        if (i >= count) { finish(); return }
        cardA = 0
        step = i
        swap.restart()
    }
    Timer { id: swap; interval: 140; onTriggered: root.show(root.step) }
    function next() { go(step + 1) }
    function finish() {
        markShown()
        if (Ui.app) { Ui.app.tutorialRestore(); Ui.app.setExpanded(false) }
        active = false; lit = false; fade = 0; cardA = 0
        ended()
    }

    // the dim: four sheets round the lit rectangle (nothing to shade when none)
    readonly property color dim: Qt.rgba(0, 0, 0, 0.74 * fade)
    Rectangle { x: 0; y: 0; width: root.cw; height: root.lit ? root.hy : root.ch; color: root.dim }
    Rectangle { x: 0; y: root.hy + root.hh; width: root.cw; height: root.ch - y; color: root.dim; visible: root.lit }
    Rectangle { x: 0; y: root.hy; width: root.hx; height: root.hh; color: root.dim; visible: root.lit }
    Rectangle { x: root.hx + root.hw; y: root.hy; width: root.cw - x; height: root.hh; color: root.dim; visible: root.lit }
    Rectangle {
        visible: root.lit
        x: root.hx - 2; y: root.hy - 2; width: root.hw + 4; height: root.hh + 4; radius: 10
        color: "transparent"; border.width: 2; border.color: Theme.gold
        opacity: root.fade
        // a soft breath, so the eye finds it
        SequentialAnimation on scale {
            running: root.active && root.lit && Theme.motionRate > 0; loops: Animation.Infinite
            NumberAnimation { to: 1.012; duration: Theme.dur(900); easing.type: Easing.InOutSine }
            NumberAnimation { to: 1.0; duration: Theme.dur(900); easing.type: Easing.InOutSine }
        }
    }
    MouseArea { anchors.fill: parent; onClicked: root.next() }

    // ─── the card ──────────────────────────────────────────────────────────
    Rectangle {
        id: card
        // beside the lit element: under it when there is room, else above,
        // else at its side (a tall column lights up: the card goes next to
        // it, narrower if it must); centred on the screen when nothing is lit
        readonly property real pad: 22
        readonly property real fullW: Math.min(420, root.cw - 32)
        // 🚨 aside must not look at height: the width depends on it, the text
        // wraps on the width, the height on the text (a binding loop)
        readonly property bool aside: root.lit && root.hh > root.ch * 0.45
        readonly property bool fitsBelow: !aside && root.hy + root.hh + 18 + height <= root.ch - 12
        readonly property bool fitsAbove: !aside && root.hy - 18 - height >= 12
        readonly property bool onRight: aside && (root.cw - (root.hx + root.hw)) >= root.hx     // more room on the right
        readonly property real sideW: onRight ? root.cw - (root.hx + root.hw) - 34 : root.hx - 34
        width: aside ? Math.max(240, Math.min(fullW, sideW)) : fullW
        height: pad + titleText.height + 8 + bodyText.height + 18 + 40 + pad
        radius: 16
        color: Theme.light
        border.width: 1; border.color: Theme.goldA(0.35)
        opacity: root.cardA * root.fade
        // beside the lit element: under it when there is room, else above;
        // centred on the screen when nothing is lit
        x: !root.lit ? (root.cw - width) / 2
         : aside ? (onRight ? root.hx + root.hw + 18 : root.hx - 18 - width)
         : Math.max(16, Math.min(root.cw - 16 - width, root.hx + root.hw / 2 - width / 2))
        y: !root.lit ? (root.ch - height) / 2
         : fitsBelow ? root.hy + root.hh + 18
         : fitsAbove ? root.hy - 18 - height
         : Math.max(12, Math.min(root.ch - 12 - height, root.hy + root.hh / 2 - height / 2))
        Behavior on x { enabled: root.active; NumberAnimation { duration: Theme.dur(300); easing.type: Easing.InOutCubic } }
        Behavior on y { enabled: root.active; NumberAnimation { duration: Theme.dur(300); easing.type: Easing.InOutCubic } }
        BoxShadow { z: -1; targetX: 0; targetY: 0; targetW: parent.width; targetH: parent.height; radius: 16; blur: 40; spread: -10; offsetY: 18; color: Theme.blackA(0.4) }
        MouseArea { anchors.fill: parent }        // taps on the card do not skip ahead

        Text {
            id: titleText
            x: card.pad; y: card.pad; width: parent.width - 2 * card.pad
            text: root.step >= 0 && root.step < root.count ? Tr.t("tutorial." + root.steps[root.step].key + ".title") : ""
            color: Theme.gold; font.family: Theme.font; font.pixelSize: 18; font.bold: true
            wrapMode: Text.Wrap
        }
        Text {
            id: bodyText
            x: card.pad; y: titleText.y + titleText.height + 8; width: parent.width - 2 * card.pad
            text: root.step >= 0 && root.step < root.count ? Tr.t("tutorial." + root.steps[root.step].key + ".body") : ""
            color: Theme.silver; font.family: Theme.font; font.pixelSize: 14
            wrapMode: Text.Wrap; lineHeight: 20; lineHeightMode: Text.FixedHeight
        }
        // skip · step counter · next
        Item {
            x: card.pad; y: bodyText.y + bodyText.height + 18; width: parent.width - 2 * card.pad; height: 40
            Rectangle {
                width: skipText.implicitWidth + 28; height: 40; radius: 8
                visible: root.step < root.count - 1
                color: skipTap.mix(Theme.wa(0.05), Theme.wa(0.12))
                Text { id: skipText; anchors.centerIn: parent; text: Tr.t("tutorial.skip"); color: Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 14 }
                Tap { id: skipTap; onClicked: root.finish() }
            }
            Text {
                anchors.centerIn: parent
                text: (root.step + 1) + " / " + root.count
                color: Theme.silverA(0.4); font.family: Theme.mono; font.pixelSize: 11
            }
            Rectangle {
                anchors.right: parent.right
                width: nextText.implicitWidth + 36; height: 40; radius: 8
                color: nextTap.mix(Theme.gold, "#ca8a04")
                scale: nextTap.tapScale
                Text { id: nextText; anchors.centerIn: parent; text: Tr.t(root.step >= root.count - 1 ? "tutorial.finish" : "tutorial.next"); color: Theme.black; font.family: Theme.font; font.pixelSize: 15; font.bold: true }
                Tap { id: nextTap; tap: 0.96; onClicked: root.next() }
            }
        }
    }
}
