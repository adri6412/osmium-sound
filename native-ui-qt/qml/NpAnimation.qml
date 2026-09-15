// The Now Playing animation shown in place of the VU meters when they are
// off: a CD, a vinyl record or a cassette (Settings → Animations, read from
// Player.npAnimation). This file only picks the scene and feeds it; each
// scene (AnimCd.qml, AnimVinyl.qml, AnimCassette.qml) is a plain QtQuick
// component with the same inputs, its PNGs in assets/anim/<kind>/.
//
// live: false is the still used by the Settings cards: the scene draws its
// final pose once, with the generic label, and never runs a timer.
//
// The scene is loaded by file name, not by type, so a broken or missing
// scene only leaves this box empty instead of breaking Now Playing.
import QtQuick
import Hifi

Item {
    id: root
    property string kind: ""
    property real devScale: 1
    property bool live: true
    property bool active: false

    readonly property string file: kind === "cd" ? "AnimCd.qml"
                                 : kind === "vinyl" ? "AnimVinyl.qml"
                                 : kind === "cassette" ? "AnimCassette.qml" : ""

    // the kind of the scene loaded now: the pictures' folder follows it, not
    // `kind`, or a change would point the old scene at the new one's folder
    // for an instant before it is replaced
    property string loadedKind: ""

    // what the scene sees; the still preview gets a fixed "playing" state
    readonly property string assetsBase: "file://" + Sys.assets + "/anim/" + loadedKind + "/"
    readonly property bool hasTrack: !live || Player.title !== "" || Player.trackUrl !== ""
    readonly property bool playing: !live || Player.playing
    readonly property real progress: live && Player.duration > 0 ? Math.max(0, Math.min(1, Player.elapsed / Player.duration)) : 0
    readonly property string artwork: live ? Player.artworkUrl : ""
    // The album on the media: a new one takes it out and puts the next one in.
    // Album alone (a compilation keeps its disc while the artist changes); a
    // stream without an album is its station URL, so a radio's songs do not
    // swap the disc every few minutes.
    readonly property string mediaKey: !live ? ""
                                     : Player.album !== "" ? "a" + Player.album
                                     : Player.remote ? "u" + Player.trackUrl
                                     : "t" + Player.artist
    readonly property string title: live ? (Player.album || Player.title) : ""
    readonly property string subtitle: live ? Player.artist : ""

    function inputs() {
        return {
            assetsBase: root.assetsBase, devScale: root.devScale, live: root.live, active: root.active,
            playing: root.playing, hasTrack: root.hasTrack, progress: root.progress, artwork: root.artwork,
            mediaKey: root.mediaKey, title: root.title, subtitle: root.subtitle
        }
    }
    // 🚨 initial properties, not bindings set afterwards: the scenes read
    // `live` when they complete, and a still must never start as a live scene
    function load() {
        loader.source = ""                 // the old scene goes first, untouched
        root.loadedKind = root.file === "" ? "" : root.kind
        if (root.file !== "") loader.setSource(Qt.resolvedUrl(root.file), inputs())
    }
    // a `kind` given at creation also signals a change: load once, when complete
    property bool completed: false
    onFileChanged: if (completed) load()
    Component.onCompleted: { completed = true; load() }

    Loader {
        id: loader
        anchors.fill: parent
        asynchronous: false
        onStatusChanged: if (status === Loader.Error) Sys.log("anim: scene \"" + root.kind + "\" failed to load")
    }

    // afterwards the inputs follow the player
    Binding { when: loader.item !== null; target: loader.item; property: "assetsBase"; value: root.assetsBase }
    Binding { when: loader.item !== null; target: loader.item; property: "devScale"; value: root.devScale }
    Binding { when: loader.item !== null; target: loader.item; property: "active"; value: root.active }
    Binding { when: loader.item !== null; target: loader.item; property: "playing"; value: root.playing }
    Binding { when: loader.item !== null; target: loader.item; property: "hasTrack"; value: root.hasTrack }
    Binding { when: loader.item !== null; target: loader.item; property: "progress"; value: root.progress }
    Binding { when: loader.item !== null; target: loader.item; property: "artwork"; value: root.artwork }
    Binding { when: loader.item !== null; target: loader.item; property: "mediaKey"; value: root.mediaKey }
    Binding { when: loader.item !== null; target: loader.item; property: "title"; value: root.title }
    Binding { when: loader.item !== null; target: loader.item; property: "subtitle"; value: root.subtitle }

    // A scene with working controls (the cassette deck) declares `power`,
    // `volume` and `volumeFixed` and an action(name, value) signal; the
    // others do not get these inputs (no "non-existent property" warnings).
    // A still preview never acts.
    readonly property bool controls: loader.item !== null && loader.item.power !== undefined
    Binding { when: root.controls; target: loader.item; property: "power"; value: !root.live || Player.power }
    Binding { when: root.controls; target: loader.item; property: "volume"; value: root.live ? Player.volume : -1 }
    Binding { when: root.controls; target: loader.item; property: "volumeFixed"; value: root.live && Player.volumeFixed }
    Connections {
        target: root.live ? loader.item : null
        ignoreUnknownSignals: true
        function onAction(name, value) {
            if (name === "prev") Player.prev()
            else if (name === "next") Player.next()
            else if (name === "play") {
                if (!Player.power) Player.cmd(["power", "1"])
                Player.play(true)
            }
            else if (name === "pause") Player.play(false)
            else if (name === "stop" || name === "eject") Player.cmd(["stop"])
            else if (name === "volume") Player.setVolume(value.level, value.final)
            else if (name === "power") Player.cmd(["power", value ? "1" : "0"])
        }
    }
}
