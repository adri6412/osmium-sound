// The Now Playing animation shown in place of the VU meters when they are
// off: a CD, a CD changer, a vinyl record or a cassette (Settings →
// Animations, read from Player.npAnimation). This file only picks the scene
// and feeds it; each scene (AnimCd.qml, AnimVinyl.qml, ...) is a plain QtQuick
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
import Hifi.Ui

Item {
    id: root
    property string kind: ""
    property real devScale: 1
    property bool live: true
    property bool active: false
    // the CD changer in the albums view (ChangerView): its own list of discs
    // in place of App.changerScene ([{ album, art }]), the file holding only
    // those, and the scene itself to put discs in (prepare / insert)
    property var changerDiscs: null
    property bool changerSparse: false
    readonly property Item scene: loader.item

    readonly property var builtin: ({ cd: "AnimCd.qml", cdfront: "AnimCdFront.qml", changer: "AnimChanger.qml", vinyl: "AnimVinyl.qml", cassette: "AnimCassette.qml" })
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
                                     : Player.album !== "" ? albumKey(Player.album)
                                     : Player.remote ? "u" + Player.trackUrl
                                     : "t" + Player.artist
    // an album's key (the \u0001 has been part of it from the start: kept, so
    // nothing that compares keys changes)
    function albumKey(album) { return "a\u0001" + album }
    // An internet radio has no album: its station takes the album's place
    // (the cassette's label: the station, then "artist - song"), and the
    // song keeps the display. A title that is only the station's name again
    // (no song information yet) is not repeated.
    readonly property string station: live && Player.remote && Player.album === "" ? Player.stationName : ""
    readonly property string song: Player.title !== root.station ? Player.title : ""
    readonly property string title: !live ? "" : Player.album || root.station || Player.title
    // the names that are there, each once (a radio may send the same one as
    // artist and title)
    function names(list) { return list.filter(function(x, i) { return !!x && list.indexOf(x) === i }) }
    readonly property string subtitle: !live ? "" : root.station !== "" ? names([Player.artist, root.song]).join(" - ")
                                                                        : Player.artist
    // the CD-Text: the song and its artist, then the station
    readonly property string trackTitle: !live ? "" : root.song || root.station
    readonly property string trackArtist: !live ? "" : root.song !== "" ? names([Player.artist !== root.song ? Player.artist : "", root.station]).join(" - ")
                                                                        : Player.artist

    function inputs() {
        var o = {
            assetsBase: root.assetsBase, devScale: root.devScale, live: root.live, active: root.active,
            playing: root.playing, hasTrack: root.hasTrack, progress: root.progress, artwork: root.artwork,
            mediaKey: root.mediaKey, title: root.title, subtitle: root.subtitle
        }
        // The CD changer places the disc playing in its drive as it is
        // created: it must know its discs (which slot holds the album) and
        // the power from the start. Given only by the bindings below, a
        // moment later, the disc went into the wrong slot first -- coming
        // back to the changer it was taken out and loaded again, or sat in
        // the drive with another slot's empty label (a plain white disc).
        if (root.loadedKind === "changer") {
            o.discs = root.sceneDiscs()
            o.sparse = root.live && root.changerSparse
            o.power = !root.live || Player.power
        }
        return o
    }
    // the changer's discs as the scene keys them
    function sceneDiscs() {
        return !root.live ? [] : (root.changerDiscs !== null ? root.changerDiscs : Ui.app ? Ui.app.changerScene : [])
                                   .map(function(d) { return { key: root.albumKey(d.album), art: d.art } })
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
    // the track playing, not the album: the CD players' display shows it, the
    // cassette writes it on its label (so any scene declaring it gets it)
    Binding { when: loader.item !== null && loader.item.trackTitle !== undefined; target: loader.item; property: "trackTitle"; value: root.trackTitle }
    Binding { when: loader.item !== null && loader.item.trackArtist !== undefined; target: loader.item; property: "trackArtist"; value: root.trackArtist }
    // the CD changer: the albums loaded from the albums view, disc 1 first
    // (App.changerScene), keyed like mediaKey; a still has none
    Binding {
        when: loader.item !== null && loader.item.discs !== undefined; target: loader.item; property: "discs"
        value: root.sceneDiscs()
    }
    Binding { when: loader.item !== null && loader.item.sparse !== undefined; target: loader.item; property: "sparse"; value: root.live && root.changerSparse }
    // Fast wind on the cassette deck: a jump of windStep seconds per call.
    // Past the end it moves on to the next track, before the start to the end
    // of the previous one. After a track change nothing moves until the new
    // track is really there (Player.elapsed is the old one's until then, and
    // would skip a second track).
    // The CD changer's DISC -/+ (value -1/+1): the first track of the album
    // before or after the one playing, in the queue; past the last one it
    // goes round to the first, like a changer's discs.
    function changeDisc(dir) {
        Player.query(["status", "0", "999", "tags:l"], function(ok, r) {
            var pl = ok && r ? r.playlist_loop || [] : []
            var starts = []
            for (var i = 0; i < pl.length; i++) if (i === 0 || pl[i].album !== pl[i - 1].album) starts.push(i)
            if (starts.length < 2) return
            var cur = Math.max(0, Math.min(pl.length - 1, Player.index)), k = 0
            for (var j = 0; j < starts.length; j++) if (starts[j] <= cur) k = j
            var to = String(starts[((k + dir) % starts.length + starts.length) % starts.length])
            if (root.loadedKind !== "changer") { Player.cmd(["playlist", "index", to]); return }
            root.changerJump(to)
        })
    }
    // The changer to another disc: the music waits for it. Lyrion's jump
    // plays at once when it is playing, and an earlier pause could reach it
    // after the jump: so the pause first, then the jump without playing
    // (`noplay`), in that order; the music comes back once the disc sits in
    // the drive (changerSeated).
    function changerJump(to) {
        var was = Player.playing
        Player.query(["pause", "1"], function() {
            Player.query(["playlist", "index", String(to), "0", "1"], function() {
                if (was) { root.discPlayWait = true; discPlayLimit.restart() }
            })
        })
    }
    // The end of a disc: Lyrion would go on to the next album by itself and
    // the changer could only pause it once heard. On the last track of a disc
    // (the next one in the queue is another album) the changer takes over a
    // moment before its end, as with DISC +. Not in random order: the next
    // track is not known.
    readonly property bool changerLive: live && active && loadedKind === "changer" && changerDiscs === null
    property bool lastOfDisc: false
    readonly property string curTrack: changerLive ? Player.trackId + "#" + Player.index : ""
    onCurTrackChanged: {
        lastOfDisc = false
        if (curTrack === "" || Player.shuffle !== 0) return
        var at = Player.index, want = curTrack
        Player.query(["status", String(at), "2", "tags:l"], function(ok, r) {
            var pl = ok && r ? r.playlist_loop || [] : []
            root.lastOfDisc = root.curTrack === want && pl.length === 2 && pl[0].album !== pl[1].album
        })
    }
    // Player.elapsed moves in half-second steps: the place in the track is
    // the last step plus the time since it
    readonly property real elapsedNow: Player.elapsed
    property double elapsedAt: 0
    onElapsedNowChanged: elapsedAt = Date.now()
    Timer {
        interval: 100; repeat: true
        running: root.changerLive && root.lastOfDisc && Player.playing && Player.duration > 0
        onTriggered: {
            var at = root.elapsedNow + Math.max(0, (Date.now() - root.elapsedAt) / 1000)
            if (Player.duration - at <= 0.3) {
                root.lastOfDisc = false
                root.changerJump(Player.index + 1)
            }
        }
    }
    // The wait for the new disc begins once the new album has reached the
    // scene: armed earlier, the scene would still hold the old disc as the
    // one in place and the music would start at once.
    property bool discPlayWait: false
    function armDiscPlay() {
        if (!discPlayWait) return
        discPlayWait = false
        discPlayLimit.stop()
        if (Ui.app) Ui.app.changerAwaitPlay = true
    }
    onMediaKeyChanged: if (discPlayWait) Qt.callLater(armDiscPlay)
    // other music queued without playing (Player.startHeld): play it once its
    // disc is in the drive
    function awaitNewDisc() { discPlayWait = true; discPlayLimit.restart() }
    Timer { id: discPlayLimit; interval: 5000; onTriggered: root.armDiscPlay() }
    // A disc of the CD changer sits in the drive: the music the owner is
    // waiting for starts now (App.changerAwaitPlay: Done, Play on the
    // changer). Also when the wait begins with the disc already there.
    function changerSeated() {
        if (!Ui.app || !Ui.app.changerAwaitPlay) return
        Ui.app.changerAwaitPlay = false
        Player.play(true)
    }
    // The changer playing in Now Playing (not the albums view's, which has
    // discs of its own): App.changerTakesPlay() sends every Play through it,
    // so the music waits for the disc to go in, as with the changer's own key.
    readonly property bool changerOnScreen: live && active && loadedKind === "changer" && changerDiscs === null
                                            && loader.item !== null
    onChangerOnScreenChanged: {
        if (!Ui.app) return
        if (changerOnScreen) Ui.app.changerScreen = root
        else if (Ui.app.changerScreen === root) Ui.app.changerScreen = null
    }
    Component.onDestruction: if (Ui.app && Ui.app.changerScreen === root) Ui.app.changerScreen = null
    Connections {
        target: root.live && root.active && Ui.app ? Ui.app : null
        function onChangerAwaitPlayChanged() {
            if (Ui.app.changerAwaitPlay && loader.item && loader.item.loaded === true) root.changerSeated()
        }
    }
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
                // discs waiting in the CD changer: its Play is Done
                if (!(Ui.app && Ui.app.changerTakesPlay())) Player.play(true)
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
            else if (name === "disc") root.changeDisc(value)
            // the CD changer: the music waits for its disc to be in the drive
            else if (name === "playSeated") {
                if (!Player.power) Player.cmd(["power", "1"])
                if (Ui.app) Ui.app.changerAwaitPlay = true
            }
            else if (name === "seated") root.changerSeated()
        }
    }
}
