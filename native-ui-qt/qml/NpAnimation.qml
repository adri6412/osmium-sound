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
//
// A kind that is not built in comes from the animation store: its folder
// Sys.animStore/<id>/ holds anim.json (naming the scene file) and the
// scene's QML and images; the scene gets that folder as assetsBase and the
// same inputs as the built-in ones (the contract is ANIM_SCENE_FORMAT 1 in
// api_server.py and anim-store/README.md).
import QtQuick
import Hifi

Item {
    id: root
    property string kind: ""
    property real devScale: 1
    property bool live: true
    property bool active: false

    readonly property var builtin: ({ cd: "AnimCd.qml", cdfront: "AnimCdFront.qml", vinyl: "AnimVinyl.qml", cassette: "AnimCassette.qml" })
    // a store scene: anim.json's `scene`, a flat .qml name inside its folder
    function storeScene(k) {
        if (!/^[a-z0-9][a-z0-9_-]{0,40}$/.test(k)) return ""
        try {
            var meta = JSON.parse(Sys.readFile(Sys.animStore + "/" + k + "/anim.json") || "null")
            if (meta && typeof meta.scene === "string" && /^[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.qml$/.test(meta.scene))
                return "file://" + Sys.animStore + "/" + k + "/" + meta.scene
        } catch (e) {}
        return ""
    }
    readonly property bool fromStore: kind !== "" && kind !== "none" && builtin[kind] === undefined
    readonly property string file: kind === "" || kind === "none" ? ""
                                 : builtin[kind] !== undefined ? builtin[kind]
                                 : storeScene(kind)

    // the kind of the scene loaded now: the pictures' folder follows it, not
    // `kind`, or a change would point the old scene at the new one's folder
    // for an instant before it is replaced
    property string loadedKind: ""
    property bool loadedStore: false

    // what the scene sees; the still preview gets a fixed "playing" state
    readonly property string assetsBase: loadedStore ? "file://" + Sys.animStore + "/" + loadedKind + "/"
                                                     : "file://" + Sys.assets + "/anim/" + loadedKind + "/"
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
    // An internet radio has no album: its station takes the album's place
    // (the cassette's label: the station, then "artist - song"), and the
    // song keeps the display. A title that is only the station's name again
    // (no song information yet) is not repeated.
    readonly property string station: live && Player.remote && Player.album === "" ? Player.stationName : ""
    readonly property string song: Player.title !== root.station ? Player.title : ""
    readonly property string title: !live ? "" : Player.album || root.station || Player.title
    readonly property string subtitle: !live ? "" : root.station !== "" ? [Player.artist, root.song].filter(function(x) { return !!x }).join(" - ")
                                                                        : Player.artist
    // the CD-Text: the song and its artist, then the station
    readonly property string trackTitle: !live ? "" : root.song || root.station
    readonly property string trackArtist: !live ? "" : root.song !== "" ? [Player.artist, root.station].filter(function(x) { return !!x }).join(" - ")
                                                                        : Player.artist

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
        root.loadedStore = root.fromStore
        if (root.file !== "") loader.setSource(root.fromStore ? root.file : Qt.resolvedUrl(root.file), inputs())
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
    // A scene with a display (the CD players' LCD) also declares the queue
    // position, the time and the repeat / random modes.
    readonly property bool display: loader.item !== null && loader.item.trackIndex !== undefined
    Binding { when: loader.item !== null && loader.item.elapsed !== undefined; target: loader.item; property: "elapsed"; value: root.live ? Player.elapsed : 0 }
    // the track's length in seconds, 0 unknown (a stream): a longer track,
    // more tape on the cassette
    Binding { when: loader.item !== null && loader.item.duration !== undefined; target: loader.item; property: "duration"; value: root.live ? Math.max(0, Player.duration) : 0 }
    // which track: the cassette finishes winding one before starting the next
    Binding { when: loader.item !== null && loader.item.trackId !== undefined; target: loader.item; property: "trackId"; value: root.live ? Player.trackId : "" }
    // the cassette deck's level meters: this device's own audio (Vu is kept
    // running for them by NowPlaying while that scene is on screen)
    Binding { when: loader.item !== null && loader.item.levelL !== undefined; target: loader.item; property: "levelL"; value: root.live ? Vu.left : 0 }
    Binding { when: loader.item !== null && loader.item.levelR !== undefined; target: loader.item; property: "levelR"; value: root.live ? Vu.right : 0 }
    Binding { when: root.display; target: loader.item; property: "trackIndex"; value: root.live ? Player.index : -1 }
    Binding { when: root.display; target: loader.item; property: "trackTotal"; value: root.live ? Player.total : 0 }
    Binding { when: root.display; target: loader.item; property: "repeatMode"; value: root.live ? Player.repeat : 0 }
    Binding { when: root.display; target: loader.item; property: "shuffleMode"; value: root.live ? Player.shuffle : 0 }
    Binding { when: root.display; target: loader.item; property: "trackTitle"; value: root.trackTitle }
    Binding { when: root.display; target: loader.item; property: "trackArtist"; value: root.trackArtist }
    // Fast wind on the cassette deck: a jump of windStep seconds per call.
    // Past the end it moves on to the next track, before the start to the end
    // of the previous one. After a track change nothing moves until the new
    // track is really there (Player.elapsed is the old one's until then, and
    // would skip a second track).
    readonly property real windStep: 8
    property string windWait: ""
    property bool windToEnd: false
    function wind(dir) {
        if (Player.duration <= 0) return                        // a stream: nothing to wind
        if (windWait !== "") {
            if (Player.trackId === windWait) return
            windWait = ""
            if (windToEnd) { windToEnd = false; Player.seek(Math.max(0, Player.duration - 6)); return }
        }
        var t = Player.elapsed + dir * windStep
        if (dir > 0 && t >= Player.duration - 1) { windWait = Player.trackId; Player.next(); return }
        if (dir < 0 && t <= 0) {
            if (Player.elapsed > 1.5) { Player.seek(0); return }
            windWait = Player.trackId; windToEnd = true; Player.prev(); return
        }
        Player.seek(t)
    }
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
            else if (name === "wind") root.wind(value)
            else if (name === "track") Player.cmd(["playlist", "index", String(value - 1)])
            else if (name === "windStop") { root.windWait = ""; root.windToEnd = false }
            else if (name === "repeat") Player.cycleRepeat()
            else if (name === "random") Player.cycleShuffle()
        }
    }
}
