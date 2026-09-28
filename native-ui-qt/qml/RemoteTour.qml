// "Try the remote": a practice run, one key at a time. Each step asks for a
// command ("move the spotlight with the arrows", "press ≡"), a small scene on
// the card shows what it does, and the next step comes only once the right
// key has been pressed. A wrong key says what it was and what to look for.
//
// While it runs every remote action comes here first (App.remote) and none
// reaches the interface: practising play/pause must not stop the music, nor
// the volume step blast it.
//
// 🚨 The key names follow what the keys do NOW on the remote in hand: a
// known model's keys (modelKeys, named in tutorialRemote.keyNames.<model>)
// are looked up through Remote.actionFor, so a key the owner gave another job
// is named for that job — the tour said "press ≡" for the menu while ≡ had
// become something else. A step no key can do any more is left out. Remotes
// that are not a known model get generic words (tutorialRemote.keys.generic).
//
// Started only after a known remote's key map at the end of the first setup
// (App.startRemoteTour). Only short, one-off animations: this GPU is weak.
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    property bool active: false
    property string model: ""
    visible: active || fade > 0
    anchors.fill: parent
    signal ended()

    property real fade: 0
    Behavior on fade { NumberAnimation { duration: Theme.dur(240); easing.type: Easing.OutCubic } }

    // want: the actions that pass the step; all: every one of them, not any.
    // needs: a key that generic remotes may lack — skipped without a model.
    readonly property var allSteps: [
        { key: "welcome", want: ["ok"] },
        { key: "arrows", want: ["up", "down", "left", "right"], all: true, scene: "grid" },
        { key: "ok", want: ["ok"], scene: "grid" },
        { key: "menu", want: ["menu"], scene: "grid" },
        { key: "back", want: ["back"], scene: "crumbs" },
        // the album grid and Cover Flow, as the library behaves: these pass
        // on what the scene reached, not on one key (see reached())
        { key: "albums", want: ["up", "down", "left", "right"], scene: "albums" },
        { key: "az", want: ["up", "down", "left", "right"], scene: "albums" },
        { key: "coverflow", want: ["left", "right"], all: true, scene: "coverflow" },
        { key: "coverflowPlay", want: ["down"], scene: "coverflow" },
        { key: "home", want: ["home"], scene: "home" },
        { key: "volume", want: ["volumeUp", "volumeDown"], scene: "volume" },
        { key: "play", want: ["playPause", "play", "pause"], scene: "play" },
        { key: "player", want: ["nowPlaying"], scene: "player", needs: true },
        { key: "done", want: ["ok"] }]
    property var steps: []
    property int step: 0
    readonly property var cur: step >= 0 && step < steps.length ? steps[step] : null
    property var pressed: ({})          // for an "all" step: which ones were done
    property bool passed: false         // the step is done, the next is coming
    property string wrong: ""           // what the last wrong key was

    function start(m) {
        model = m || ""
        device = model ? Remote.deviceOfModel(model) : ""
        steps = allSteps.filter(function(s) {
            if (s.needs && root.model === "") return false
            // what no key does any more cannot be practised
            return s.all ? s.want.every(root.canDo) : s.want.some(root.canDo)
        })
        step = 0
        reset()
        active = true
        fade = 1
        Nav.hide()
    }
    function finish() {
        active = false
        fade = 0
        next.stop()
        ended()
    }
    function reset() {
        pressed = ({})
        passed = false
        wrong = ""
        gx = 0; gy = 0; opened = false; menuOpen = false
        crumbs = 3; homeLit = false; playing = true; big = false
        albF = 0; albCard = 1; letter = 0; letterMoved = false; cfPos = 3; cfDown = false
    }

    // ─── the keys ──────────────────────────────────────────────────────────
    // Every key of each known model (the names Remote.keyName gives), the
    // usual one for a job first: where two keys do the same thing (G20S:
    // ↩ and DEL, ⌂ and 0) the tour names the first.
    readonly property var modelKeys: ({
        firetv: ["KEY_KPENTER", "KEY_BACK", "KEY_HOMEPAGE", "KEY_MENU", "KEY_PLAYPAUSE", "KEY_PROGRAM",
                 "KEY_REWIND", "KEY_FASTFORWARD", "KEY_MUTE", "KEY_VOLUMEUP", "KEY_VOLUMEDOWN", "KEY_SEARCH",
                 "APP_PRIME_VIDEO", "APP_NETFLIX", "APP_DISNEY_PLUS", "APP_AMAZON_MUSIC", "KEY_POWER",
                 "KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT"],
        g20s: ["KEY_SELECT", "KEY_BACK", "KEY_HOMEPAGE", "KEY_COMPOSE", "KEY_PLAYPAUSE", "KEY_1", "KEY_2", "KEY_3",
               "KEY_4", "KEY_5", "KEY_6", "KEY_7", "KEY_8", "KEY_9", "KEY_0", "KEY_PREVIOUSSONG", "KEY_NEXTSONG",
               "KEY_VOLUMEUP", "KEY_VOLUMEDOWN", "KEY_MUTE", "KEY_PAGEUP", "KEY_PAGEDOWN", "KEY_VOICECOMMAND",
               "KEY_BACKSPACE", "KEY_POWER", "KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT"],
        xiaomi: ["KEY_SELECT", "KEY_BACK", "KEY_HOMEPAGE", "KEY_APPSELECT", "KEY_VIDEO", "KEY_GREEN",
                 "KEY_VOLUMEUP", "KEY_VOLUMEDOWN", "KEY_VOICECOMMAND", "KEY_POWER",
                 "KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT"]
    })
    // the device the model is connected as: assignments are kept per device
    property string device: ""
    readonly property var jobOf: ({ ok: ["ok"], back: ["back"], home: ["home"], menu: ["menu"],
                                    play: ["playPause", "play", "pause"], player: ["nowPlaying"] })
    // the first key of the remote in hand that does one of these actions now
    function keyFor(actions) {
        var keys = modelKeys[model]
        if (!keys || !device) return ""
        for (var i = 0; i < keys.length; i++) {
            var code = Remote.codeForName(keys[i])
            if (code && actions.indexOf(Remote.actionFor(code, device)) >= 0) return keys[i]
        }
        return ""
    }
    function canDo(a) { return !modelKeys[model] || !device || keyFor([a]) !== "" }
    function keyName(what) {
        if (modelKeys[model] && device) {
            var k = keyFor(jobOf[what] || [what])
            if (k) return Tr.t("tutorialRemote.keyNames." + model + "." + k)
        }
        return Tr.t("tutorialRemote.keys.generic." + what)
    }
    function fill(text) {
        var names = ["ok", "back", "home", "menu", "play", "player"]
        for (var i = 0; i < names.length; i++)
            text = text.split("{" + names[i] + "Key}").join(keyName(names[i]))
        return text
    }
    function wantName(s) {
        if (!s) return ""
        var a = s.want[0]
        return a === "ok" ? keyName("ok") : a === "back" ? keyName("back") : a === "home" ? keyName("home")
             : a === "menu" ? keyName("menu") : a === "nowPlaying" ? keyName("player")
             : a === "playPause" ? keyName("play") : Tr.t("settings.remote.actions." + a)
    }

    // Every remote action while the practice runs. Always true: nothing else
    // gets it.
    function handle(a) {
        if (!cur || passed) return true
        var s = cur
        // the scene reacts to what it knows, right key or not
        if (s.scene === "grid") {
            if (a === "left") gx = Math.max(0, gx - 1)
            else if (a === "right") gx = Math.min(3, gx + 1)
            else if (a === "up") gy = Math.max(0, gy - 1)
            else if (a === "down") gy = Math.min(1, gy + 1)
        } else if (s.scene === "albums") {
            // card -> its play button -> the A-Z index, and back with left;
            // up and down change letter once on the index
            if (a === "right") albF = Math.min(s.key === "albums" ? 1 : 2, albF + 1)
            else if (a === "left") { if (albF > 0) albF--; else albCard = Math.max(0, albCard - 1) }
            else if ((a === "up" || a === "down") && albF === 2) {
                letter = Math.max(0, Math.min(7, letter + (a === "down" ? 1 : -1)))
                letterMoved = true
            }
        } else if (s.scene === "coverflow") {
            if (a === "left" || a === "right") { cfPos = Math.max(0, Math.min(9, cfPos + (a === "right" ? 1 : -1))); cfDown = false }
            else if (a === "down") cfDown = true
            else if (a === "up") cfDown = false
        }
        var custom = reached(s)
        if (custom !== undefined) {
            if (!custom) {
                var arrowKey = a === "up" || a === "down" || a === "left" || a === "right"
                if (!arrowKey) wrong = Tr.t("settings.remote.actions." + a)
                else wrong = ""
                return true
            }
            wrong = ""
            passed = true
            next.restart()
            return true
        }
        if (s.want.indexOf(a) < 0) {
            // on the little grid the arrows just move its spotlight: not wrong
            var arrow = a === "up" || a === "down" || a === "left" || a === "right"
            if (!((s.scene === "grid" || s.scene === "coverflow") && arrow)) wrong = Tr.t("settings.remote.actions." + a)
            return true
        }
        wrong = ""
        if (s.all) {
            var p = Object.assign({}, pressed); p[a] = true; pressed = p
            for (var i = 0; i < s.want.length; i++) if (!pressed[s.want[i]]) return true
        }
        // what the key does, played out in the scene
        if (s.key === "ok") opened = true
        else if (s.key === "menu") menuOpen = true
        else if (s.key === "back") crumbs = 2
        else if (s.key === "home") homeLit = true
        else if (s.key === "volume") volume = Math.max(0, Math.min(100, volume + (a === "volumeUp" ? 10 : -10)))
        else if (s.key === "play") playing = !playing
        else if (s.key === "player") big = true
        if (s.key === "welcome") { go(); return true }
        if (s.key === "done") { finish(); return true }
        passed = true
        next.restart()
        return true
    }
    // steps that pass on where the scene got to; undefined = on the key
    function reached(s) {
        if (s.key === "albums") return albF === 1
        if (s.key === "az") return albF === 2 && letterMoved
        return undefined
    }
    function go() {
        if (step + 1 >= steps.length) { finish(); return }
        var scene = cur ? cur.scene : ""
        var keep = { gx: gx, gy: gy, albF: albF, albCard: albCard, letter: letter, cfPos: cfPos, cfDown: cfDown }
        step++
        reset()
        // the same scene carries on where it was (the spotlight does not jump back)
        if (scene && cur.scene === scene) {
            gx = keep.gx; gy = keep.gy; albF = keep.albF; albCard = keep.albCard
            letter = keep.letter; cfPos = keep.cfPos; cfDown = keep.cfDown
        }
    }
    Timer { id: next; interval: 1100; onTriggered: root.go() }

    // ─── the scenes' state ─────────────────────────────────────────────────
    property int gx: 0
    property int gy: 0
    property bool opened: false
    property bool menuOpen: false
    property int crumbs: 3
    property bool homeLit: false
    property int volume: 40
    property bool playing: true
    property bool big: false
    property int albF: 0                 // 0 the card, 1 its play button, 2 the A-Z index
    property int albCard: 1
    property int letter: 0
    property bool letterMoved: false
    property int cfPos: 3                // the album in front of Cover Flow
    property bool cfDown: false          // on its play button

    Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0, 0, 0.78 * root.fade) }
    MouseArea { anchors.fill: parent; enabled: root.active }       // nothing underneath takes a touch

    Rectangle {
        id: card
        readonly property real pad: 22
        width: Math.min(root.width - 32, 640)
        height: Math.min(root.height - 32, 470)
        x: (root.width - width) / 2; y: (root.height - height) / 2
        radius: 16
        color: Theme.light
        border.width: 1; border.color: Theme.goldA(0.35)
        opacity: root.fade
        MouseArea { anchors.fill: parent }

        Text {
            id: counter
            x: card.pad; y: card.pad
            text: Tr.t("tutorialRemote.title") + "  ·  " + (root.step + 1) + " / " + root.steps.length
            color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 12; font.letterSpacing: 1
        }
        Text {
            id: title
            x: card.pad; y: counter.y + counter.height + 6; width: parent.width - 2 * card.pad
            text: root.cur ? Tr.t("tutorialRemote.steps." + root.cur.key + ".title") : ""
            color: Theme.gold; font.family: Theme.font; font.pixelSize: 20; font.bold: true
            wrapMode: Text.Wrap
        }
        Text {
            id: body
            x: card.pad; y: title.y + title.height + 8; width: parent.width - 2 * card.pad
            text: root.cur ? root.fill(Tr.t("tutorialRemote.steps." + root.cur.key + ".body")) : ""
            color: Theme.silver; font.family: Theme.font; font.pixelSize: 15
            wrapMode: Text.Wrap; lineHeight: 21; lineHeightMode: Text.FixedHeight
        }

        // ─── the scene ─────────────────────────────────────────────────────
        Item {
            id: stage
            x: card.pad; y: body.y + body.height + 14
            width: parent.width - 2 * card.pad
            height: foot.y - 12 - y
            readonly property string scene: root.cur && root.cur.scene ? root.cur.scene : ""

            // a small library grid with its own spotlight
            Item {
                visible: stage.scene === "grid"
                readonly property real tw: 78
                readonly property real th: 54
                width: 4 * tw + 3 * 10; height: 2 * th + 10
                anchors.centerIn: parent
                Repeater {
                    model: 8
                    Rectangle {
                        required property int index
                        readonly property int cx: index % 4
                        readonly property int cy: Math.floor(index / 4)
                        readonly property bool lit: cx === root.gx && cy === root.gy
                        x: cx * (parent.tw + 10); y: cy * (parent.th + 10)
                        width: parent.tw; height: parent.th; radius: 8
                        color: lit && root.opened ? Theme.goldA(0.55) : Theme.surface
                        Behavior on color { ColorAnimation { duration: Theme.dur(220) } }
                        border.width: 1; border.color: Theme.border
                        Icon { anchors.centerIn: parent; name: "disc"; size: 18; color: Theme.silverA(0.5) }
                        Rectangle {                          // the spotlight, as NavRing draws it
                            anchors.fill: parent; visible: parent.lit; radius: 8
                            color: "transparent"; border.width: 2; border.color: Theme.gold
                            Rectangle { anchors.fill: parent; anchors.margins: 2; radius: 6; color: "transparent"; border.width: 2; border.color: Theme.dark }
                        }
                    }
                }
                // the menu that the menu key opens, beside the chosen tile
                Rectangle {
                    visible: root.menuOpen
                    x: Math.min(parent.width - width, root.gx * (parent.tw + 10) + parent.tw - 10)
                    y: root.gy * (parent.th + 10) + 10
                    width: 150; height: 3 * 26 + 12; radius: 8
                    color: Theme.gray; border.width: 1; border.color: Theme.goldA(0.4)
                    Column {
                        x: 10; y: 6
                        Repeater {
                            model: ["player.addToQueue", "player.playNext", "player.addToFavorites"]
                            Text { required property string modelData; height: 26; verticalAlignment: Text.AlignVCenter
                                   text: Tr.t(modelData); color: Theme.white; font.family: Theme.font; font.pixelSize: 12 }
                        }
                    }
                }
            }
            // the four arrows of the arrows step, lit as they are pressed
            Row {
                visible: root.cur && root.cur.key === "arrows"
                anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom
                spacing: 10
                Repeater {
                    model: [["up", "arrow-up"], ["down", "arrow-down"], ["left", "chevron-left"], ["right", "chevron-right"]]
                    Rectangle {
                        required property var modelData
                        readonly property bool done: !!root.pressed[modelData[0]]
                        width: 44; height: 34; radius: 8
                        color: done ? Theme.gold : Theme.surface
                        Behavior on color { ColorAnimation { duration: Theme.dur(160) } }
                        border.width: 1; border.color: done ? Theme.gold : Theme.border
                        Icon { anchors.centerIn: parent; name: parent.modelData[1]; size: 16; color: parent.done ? Theme.black : Theme.silver }
                    }
                }
            }
            // the album grid: three cards, their play buttons and the A-Z index
            Item {
                visible: stage.scene === "albums"
                readonly property real cw: 100
                width: 3 * cw + 2 * 14 + 30 + 40; height: cw + 34
                anchors.centerIn: parent
                Repeater {
                    model: 3
                    Item {
                        required property int index
                        x: index * (parent.cw + 14); width: parent.cw; height: parent.height
                        readonly property bool here: index === root.albCard
                        Rectangle {
                            width: parent.width; height: parent.width; radius: 10
                            color: Theme.surface; border.width: 1; border.color: Theme.border
                            Icon { anchors.centerIn: parent; name: "disc"; size: 30; color: Theme.silverA(0.35) }
                            Rectangle {                      // the play button
                                id: pb
                                x: parent.width - 34; y: parent.height - 34; width: 28; height: 28; radius: 14
                                color: parent.parent.here && root.albF === 1 && root.passed ? Theme.gold : Theme.blackA(0.6)
                                Icon { anchors.centerIn: parent; anchors.horizontalCenterOffset: 1; name: "play"; filled: true; size: 12; color: Theme.white }
                                Rectangle { anchors.fill: parent; anchors.margins: -4; radius: 18; color: "transparent"; border.width: 2; border.color: Theme.gold
                                            visible: parent.parent.parent.here && root.albF === 1 }
                            }
                            Rectangle { anchors.fill: parent; radius: 10; color: "transparent"; border.width: 2; border.color: Theme.gold
                                        visible: parent.parent.here && root.albF === 0 }
                        }
                        Text { y: parent.width + 8; width: parent.width; elide: Text.ElideRight
                               text: "Album " + (index + 1); color: Theme.silver; font.family: Theme.font; font.pixelSize: 12 }
                    }
                }
                Column {                                     // the index
                    x: parent.width - 30; y: 0
                    Repeater {
                        model: 8
                        Item {
                            required property int index
                            width: 26; height: (parent.parent.height) / 8
                            Rectangle { anchors.centerIn: parent; width: 22; height: parent.height - 2; radius: 6; color: "transparent"
                                        border.width: 2; border.color: Theme.gold; visible: root.albF === 2 && index === root.letter }
                            Text { anchors.centerIn: parent; text: "ABCDEFGH".charAt(index); font.family: Theme.font; font.pixelSize: 11; font.bold: true
                                   color: root.albF === 2 && index === root.letter ? Theme.gold : Theme.silverA(0.6) }
                        }
                    }
                }
            }
            // Cover Flow: the album in front, its neighbours turned aside
            Item {
                visible: stage.scene === "coverflow"
                width: parent.width; height: parent.height
                clip: true
                readonly property real cs: Math.min(110, height - 36)
                Repeater {
                    model: 10
                    Rectangle {
                        required property int index
                        readonly property int d: index - root.cfPos
                        readonly property bool front: d === 0
                        visible: Math.abs(d) <= 3
                        width: parent.cs; height: parent.cs; radius: 6
                        x: parent.width / 2 - width / 2 + (front ? 0 : (d < 0 ? -1 : 1) * (parent.cs * 0.62 + (Math.abs(d) - 1) * parent.cs * 0.22))
                        Behavior on x { NumberAnimation { duration: Theme.dur(220); easing.type: Easing.OutCubic } }
                        y: 4
                        z: 10 - Math.abs(d)
                        scale: front ? 1 : 0.8
                        Behavior on scale { NumberAnimation { duration: Theme.dur(220) } }
                        color: Qt.rgba(0.12 + 0.02 * index, 0.12, 0.13, 1)
                        border.width: 1; border.color: Theme.wa(0.12)
                        opacity: front ? 1 : 0.55
                        Icon { anchors.centerIn: parent; name: "disc"; size: 28; color: Theme.silverA(0.4) }
                        Rectangle { visible: parent.front; anchors.fill: parent; anchors.margins: -4; radius: 9; color: "transparent"
                                    border.width: 2; border.color: Theme.gold; opacity: root.cfDown ? 0 : 1 }
                        Rectangle {                          // the front cover's play button
                            visible: parent.front
                            x: parent.width - 32; y: parent.height - 32; width: 26; height: 26; radius: 13
                            color: root.cfDown && root.passed ? Theme.gold : Theme.blackA(0.6)
                            Icon { anchors.centerIn: parent; anchors.horizontalCenterOffset: 1; name: "play"; filled: true; size: 11; color: Theme.white }
                            Rectangle { anchors.fill: parent; anchors.margins: -4; radius: 17; color: "transparent"; border.width: 2; border.color: Theme.gold; visible: root.cfDown }
                        }
                    }
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter; y: parent.cs + 12
                    text: "Album " + (root.cfPos + 1) + "  ·  " + (root.cfPos + 1) + " / 10"
                    color: Theme.white; font.family: Theme.font; font.pixelSize: 13; font.bold: true
                }
            }
            // a breadcrumb trail that loses its last step
            Row {
                visible: stage.scene === "crumbs"
                anchors.centerIn: parent; spacing: 8
                Repeater {
                    model: root.crumbs
                    Row {
                        required property int index
                        spacing: 8
                        Icon { visible: index > 0; anchors.verticalCenter: parent.verticalCenter; name: "chevron-right"; size: 14; color: Theme.silverA(0.4) }
                        Text {
                            text: [Tr.t("tutorialRemote.scene.home"), Tr.t("tutorialRemote.scene.albums"), "Toto"][index]
                            color: index === root.crumbs - 1 ? Theme.white : Theme.silverA(0.6)
                            font.family: Theme.font; font.pixelSize: 18
                        }
                    }
                }
            }
            // the library's home
            Icon {
                visible: stage.scene === "home"
                anchors.centerIn: parent; name: "home"; size: 56
                color: root.homeLit ? Theme.gold : Theme.silverA(0.5)
            }
            // a volume bar
            Item {
                visible: stage.scene === "volume"
                width: Math.min(parent.width, 360); height: 40; anchors.centerIn: parent
                Icon { anchors.verticalCenter: parent.verticalCenter; name: "volume-2"; size: 22; color: Theme.silver }
                Rectangle { x: 36; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 36 - 44; height: 4; radius: 2; color: Theme.wa(0.12)
                    Rectangle { width: parent.width * root.volume / 100; height: 4; radius: 2; color: Theme.gold
                                Behavior on width { NumberAnimation { duration: Theme.dur(200) } } } }
                Text { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; text: root.volume; color: Theme.silver; font.family: Theme.mono; font.pixelSize: 14 }
            }
            // play and pause
            Rectangle {
                visible: stage.scene === "play"
                anchors.centerIn: parent; width: 72; height: 72; radius: 36; color: Theme.gold
                Icon { anchors.centerIn: parent; anchors.horizontalCenterOffset: root.playing ? 0 : 2; name: root.playing ? "pause" : "play"; filled: true; size: 30; color: Theme.black }
            }
            // the mini player growing into the full one
            Rectangle {
                visible: stage.scene === "player"
                anchors.centerIn: parent
                width: root.big ? Math.min(parent.width, 300) : 150; height: root.big ? parent.height - 8 : 46
                Behavior on width { NumberAnimation { duration: Theme.dur(320); easing.type: Easing.OutCubic } }
                Behavior on height { NumberAnimation { duration: Theme.dur(320); easing.type: Easing.OutCubic } }
                radius: 10; color: Theme.surface; border.width: 1; border.color: Theme.goldA(root.big ? 0.6 : 0.25)
                Row { anchors.centerIn: parent; spacing: 10
                    Icon { anchors.verticalCenter: parent.verticalCenter; name: "music"; size: 18; color: Theme.gold }
                    Text { anchors.verticalCenter: parent.verticalCenter; text: "Hold the Line"; color: Theme.white; font.family: Theme.font; font.pixelSize: 13 } }
            }
        }

        // ─── the foot: what happened, and the way out ──────────────────────
        Item {
            id: foot
            x: card.pad; width: parent.width - 2 * card.pad; height: 40
            y: card.height - card.pad - height
            Row {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8
                visible: root.passed || root.wrong !== ""
                Icon { anchors.verticalCenter: parent.verticalCenter; name: root.passed ? "check-circle" : "info"; size: 18; color: root.passed ? Theme.emerald : Theme.silverA(0.7) }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    width: foot.width - 26 - skipBtn.width - 16
                    text: root.passed ? Tr.t("tutorialRemote.done")
                                      : Tr.tf("tutorialRemote.wrong", "got", root.wrong).split("{want}").join(root.wantName(root.cur))
                    color: root.passed ? Theme.emerald : Theme.silverA(0.8); font.family: Theme.font; font.pixelSize: 13
                    wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight
                }
            }
            // by touch only: with the remote the way through is the keys
            Rectangle {
                id: skipBtn
                anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                width: skipText.implicitWidth + 28; height: 40; radius: 8
                color: skipTap.mix(Theme.wa(0.05), Theme.wa(0.12))
                Text { id: skipText; anchors.centerIn: parent; text: Tr.t("tutorial.skip"); color: Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 14 }
                Tap { id: skipTap; navigable: false; onClicked: root.finish() }
            }
        }
    }
}
