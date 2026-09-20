// The album page: cover and details, play / shuffle / queue / favourite, the
// tracks, the credits and what Wikipedia says about the album.
// The tracks and the credits written in the files come from Lyrion and work
// offline; performers with their instruments, production, studios, the first
// release and the description come from the metadata service (MusicBrainz and
// Wikipedia, /api/meta/album), which may still be looking them up: then the
// page asks again every two seconds for a while.
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    property var browser: null
    property string albumId: ""
    property real devScale: 1

    property int state_: 0              // 0 loading 2 ready 3 error
    property var album: ({})
    property var tracks: []             // [{id, n, disc, title, dur, sub, url}]
    property real totalDur: 0
    property string chip: ""
    property var localCredits: []
    property var meta: null
    property string metaStatus: ""      // "", pending, ok, nomatch, offline, disabled, error
    property int metaTries: 0
    property bool aboutOpen: false
    property bool byTrack: false
    readonly property int discs: Math.max(1, Number(album.disccount || 1))
    // the cover is on screen: the Cover Flow's flying copy can go (Browser)
    readonly property bool coverReady: state_ === 2 && cover.ready
    readonly property bool metaOk: meta !== null && !!meta.release

    function load() {
        state_ = 0; meta = null; metaStatus = ""; metaTries = 0; aboutOpen = false; byTrack = false
        // the album first: the tracks' second line compares with its artist
        Player.query(["albums", "0", "1", "album_id:" + albumId, "tags:alyqwaaSSjW"], function(ok, r) {
            if (!root) return          // the page was closed meanwhile
            var a = ok && r && r.albums_loop && r.albums_loop.length ? r.albums_loop[0] : null
            if (!a) { root.state_ = 3; return }
            root.album = a
            if (root.browser) root.browser.setPageTitle(LibraryModel.AlbumPage, root.albumId, String(a.album || ""))
            Player.query(["titles", "0", "999", "album_id:" + albumId, "tags:dtiqASeoTIu", "sort:tracknum"], function(ok2, r2) {
                if (!root) return          // the page was closed meanwhile
                if (ok2 && r2) parseTracks(r2.titles_loop || [])
                root.state_ = ok2 && r2 ? 2 : 3
            })
        })
        loadMeta()
    }
    function loadMeta() {
        Api.get(Meta.url("/album?album_id=" + albumId), function(ok, d) {
            if (!root) return          // the page was closed meanwhile
            if (!ok || !d || typeof d !== "object") { root.metaStatus = "error"; return }
            root.metaStatus = String(d.status || "error")
            // "pending" may already carry the release and its credits while the
            // Wikipedia text or the composers are still on their way
            if ((d.status === "ok" || d.status === "pending") && d.release) root.meta = d
            if (d.status === "pending" && root.metaTries++ < 45) metaPoll.restart()
        }, 15000)
    }
    Timer { id: metaPoll; interval: 2000; onTriggered: root.loadMeta() }
    Component.onCompleted: load()

    // the roles written in the files, per track (Lyrion tags A + S)
    readonly property var knownRoles: ["composer", "conductor", "band", "trackartist", "albumartist", "artist"]
    function parseTracks(loop) {
        var out = [], total = 0, roles = {}, albumArtist = String(album.artist || "")
        for (var i = 0; i < loop.length; i++) {
            var t = loop[i], tr = { id: String(t.id), n: Number(t.tracknum || 0), disc: Number(t.disc || 1), title: String(t.title || ""),
                                    dur: Number(t.duration || 0), url: String(t.url || ""), sub: "" }
            total += tr.dur
            var keys = Object.keys(t)
            for (var k = 0; k < keys.length; k++) {
                var key = keys[k]
                if (knownRoles.indexOf(key) < 0 && t[key + "_ids"] === undefined) continue
                if (key === "artist" || key === "albumartist") continue
                var ppl = Meta.people(t[key], t[key + "_ids"])
                if (!roles[key]) roles[key] = {}
                for (var p = 0; p < ppl.length; p++) {
                    var nm = ppl[p].name
                    if (key === "trackartist" && nm === albumArtist) continue
                    if (!roles[key][nm]) roles[key][nm] = { person: ppl[p], tracks: [] }
                    roles[key][nm].tracks.push([tr.disc, tr.n])
                }
            }
            // second line: the track's own artist on compilations, else its composer
            var ta = String(t.trackartist || "")
            if (ta && ta !== albumArtist) tr.sub = ta
            else if (t.composer && String(t.composer) !== albumArtist) tr.sub = String(t.composer)
            out.push(tr)
        }
        tracks = out; totalDur = total
        var c = []
        var order = ["composer", "conductor", "band", "trackartist"].concat(Object.keys(roles).filter(function(r) { return knownRoles.indexOf(r) < 0 }))
        for (var o = 0; o < order.length; o++) {
            var byName = roles[order[o]]
            if (!byName) continue
            var names = Object.keys(byName)
            if (!names.length) continue
            // one entry per role and set of tracks: people credited on the same
            // tracks share a line, "Composer: A (tracks 1-3)" / "B (4-6)" get their own
            var bySet = {}, sets = []
            for (var n = 0; n < names.length; n++) {
                var e = byName[names[n]]
                var trk = e.tracks.length === out.length ? null : e.tracks
                var sk = JSON.stringify(trk)
                if (!bySet[sk]) { bySet[sk] = { group: order[o] === "composer" ? "composition" : (knownRoles.indexOf(order[o]) >= 0 ? "performer" : "other"),
                                                role: order[o], attr: "", people: [], tracks: trk }; sets.push(bySet[sk]) }
                bySet[sk].people.push({ name: names[n], id: e.person.id })
            }
            c = c.concat(sets)
        }
        localCredits = c
        var f = loop.length ? loop[0] : null
        if (f && f.type) {
            var s = String(f.type).toUpperCase()
            if (Number(f.samplesize)) s += " · " + Number(f.samplesize) + "bit"
            if (Number(f.samplerate)) s += " · " + Math.round(Number(f.samplerate) / 1000) + "kHz"
            chip = s
        } else chip = ""
    }

    // the album's artists (tags aa + SS), each leading to its page
    readonly property var artists: {
        var p = Meta.people(album.artists || album.artist, album.artist_ids || album.artist_id)
        return p.length ? p : (album.artist ? [{ name: String(album.artist), id: String(album.artist_id || "") }] : [])
    }
    function openPerson(p) {
        var id = String(p.artist_id || p.id || "")
        if (id && browser) browser.openArtist(id, String(p.name || ""))
        else if (p.mbid && browser) browser.openPerson(String(p.mbid), String(p.name || ""))
    }
    function play(mode, index) {
        var c = ["playlistcontrol", "cmd:" + mode, "album_id:" + albumId]
        if (index !== undefined && index >= 0) c.push("play_index:" + index)
        Player.cmd(c)
    }
    function shuffle() { if (browser) browser.loadShuffled("album_id", albumId) }
    function trackMenu(i, x, y) {
        var t = tracks[i]
        if (!t || !browser) return
        var L = [
            { icon: "list-plus", label: Tr.t("player.addToQueue"), cb: function() { Player.cmd(["playlistcontrol", "cmd:add", "track_id:" + t.id]) } },
            { icon: "list-start", label: Tr.t("player.playNext"), cb: function() { Player.cmd(["playlistcontrol", "cmd:insert", "track_id:" + t.id]) } }
        ]
        if (t.url) L.push({ icon: "heart", label: Tr.t("player.addToFavorites"), cb: function() { browser.addFavorite(t.url, t.title, "audio") } })
        browser.openMenu(L, x, y)
    }

    readonly property string metaLine: {
        var parts = []
        var y = metaOk && meta.release ? Meta.year(meta.release.first_release_date || meta.release.date) : ""
        if (!y && Number(album.year)) y = String(album.year)
        if (y) parts.push(y)
        parts.push(tracks.length === 1 ? Tr.t("player.page.oneTrack") : Tr.tf("player.page.tracksCount", "count", String(tracks.length)))
        if (totalDur > 0) parts.push(Meta.dur(totalDur))
        return parts.join(" · ")
    }
    readonly property string releaseLine: {
        if (!metaOk || !meta.release) return ""
        var r = meta.release, parts = []
        if (r.first_release_date && r.date && r.first_release_date !== r.date) parts.push(Tr.tf("player.page.firstRelease", "date", Meta.date(r.first_release_date)))
        var labs = (r.labels || []).map(function(l) { return l.catno ? l.name + " " + l.catno : l.name }).filter(function(x) { return !!x })
        if (labs.length) parts.push(labs.join(", "))
        if (r.country) parts.push(r.country)
        return parts.join(" · ")
    }

    // for the test channel (eval app.main.browser.pageItem.scrollTo(900))
    function scrollTo(y) { page.contentY = Math.max(0, Math.min(page.contentHeight - page.height, y)) }
    Flickable {
        id: page
        anchors.fill: parent
        contentHeight: col.height + 32
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickDeceleration: 1500; maximumFlickVelocity: 4000
        visible: root.state_ === 2

        Column {
            id: col
            x: 16; y: 16; width: page.width - 32

            // ── header ─────────────────────────────────────────────────────
            Item {
                width: parent.width; height: Math.max(cover.height, info.height)
                Cover {
                    id: cover
                    width: 164; height: 164; radius: 12; devScale: root.devScale
                    source: root.album.artwork_track_id ? Api.lmsBase + "/music/" + root.album.artwork_track_id + "/cover?size=" + Theme.coverPx(164 * 2) : ""
                }
                Column {
                    id: info
                    x: 180; width: parent.width - 180
                    Text {
                        width: parent.width; text: String(root.album.album || "")
                        color: Theme.white; font.family: Theme.font; font.pixelSize: 20; font.bold: true
                        wrapMode: Text.Wrap; maximumLineCount: 3; elide: Text.ElideRight
                        lineHeight: 26; lineHeightMode: Text.FixedHeight
                    }
                    Item { width: 1; height: 4 }
                    Flow {
                        width: parent.width; spacing: 6
                        Repeater {
                            model: root.artists
                            Text {
                                required property var modelData
                                required property int index
                                // a long credit ("Choir, Orchestra, conductor…") wraps instead of running off
                                width: Math.min(implicitWidth, info.width)
                                wrapMode: Text.Wrap; maximumLineCount: 3; elide: Text.ElideRight
                                text: modelData.name + (index < root.artists.length - 1 ? "," : "")
                                color: aTap.mix(Theme.gold, Theme.white); font.family: Theme.font; font.pixelSize: 15
                                Tap { id: aTap; grow: 4; enabled: modelData.id !== ""; onClicked: root.openPerson(modelData) }
                            }
                        }
                    }
                    Item { width: 1; height: 6 }
                    Text { width: parent.width; text: root.metaLine; color: Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 12; elide: Text.ElideRight }
                    Item { width: 1; height: root.releaseLine ? 4 : 0 }
                    Text { visible: root.releaseLine !== ""; width: parent.width; text: root.releaseLine; color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 12; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight }
                    Item { width: 1; height: root.chip ? 8 : 0 }
                    Rectangle {
                        visible: root.chip !== ""
                        width: chipText.implicitWidth + 16; height: 22; radius: 4
                        color: Theme.wa(0.05); border.width: 1; border.color: Theme.wa(0.05)
                        Text { id: chipText; anchors.centerIn: parent; text: root.chip; color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 11; font.letterSpacing: 0.3 }
                    }
                }
            }
            Item { width: 1; height: 14 }
            Row {
                spacing: 10
                PageButton { icon: "play"; filled: true; primary: true; label: Tr.t("player.page.play"); onClicked: root.play("load") }
                PageButton { icon: "shuffle"; label: Tr.t("player.page.shuffle"); onClicked: root.shuffle() }
                PageButton { icon: "list-plus"; onClicked: root.play("add") }
                PageButton { icon: "list-start"; onClicked: root.play("insert") }
                PageButton { id: favBtn; icon: "heart"; visible: !!root.album.favorites_url; onClicked: { burst(); if (root.browser) root.browser.addFavorite(String(root.album.favorites_url), String(root.album.album || ""), "playlist") } }
            }

            // ── state of the online lookup ─────────────────────────────────
            Item { width: 1; height: statusText.visible ? 10 : 0 }
            Text {
                id: statusText
                visible: text !== ""
                width: parent.width; wrapMode: Text.Wrap
                text: root.metaStatus === "pending" && !root.metaOk ? Tr.t("player.page.lookingUp")
                    : root.metaStatus === "offline" ? Tr.t("player.page.offline")
                    : root.metaStatus === "nomatch" ? Tr.t("player.page.noMatch") : ""
                color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 12
            }

            // ── tracks ─────────────────────────────────────────────────────
            SectionTitle { text: Tr.t("player.page.tracks") }
            Repeater {
                model: root.tracks
                Column {
                    id: trow
                    required property var modelData
                    required property int index
                    readonly property bool newDisc: root.discs > 1 && (index === 0 || root.tracks[index - 1].disc !== modelData.disc)
                    readonly property bool current: Player.trackId === modelData.id
                    width: col.width
                    Text {
                        visible: trow.newDisc
                        width: parent.width; height: 30; verticalAlignment: Text.AlignBottom; bottomPadding: 6
                        text: Tr.tf("player.page.disc", "n", String(trow.modelData.disc)); color: Theme.gold
                        font.family: Theme.font; font.pixelSize: 12; font.bold: true
                    }
                    Item {
                        width: parent.width; height: trow.modelData.sub ? 52 : 44
                        // the scale goes on the drawing, not on the delegate (see LibraryList)
                        Item {
                            id: trSkin
                            anchors.fill: parent
                            scale: trTap.tapScale
                            Rectangle {
                                anchors.fill: parent; anchors.bottomMargin: 4; radius: 8
                                color: trTap.mix(trow.current ? Theme.goldA(0.12) : Theme.surface, Theme.light)
                                border.width: trow.current ? 1 : 0; border.color: Theme.goldA(0.3)
                            }
                            Text {
                                x: 8; width: 30; height: parent.height - 4; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignRight
                                text: trow.current ? "▶" : (trow.modelData.n > 0 ? String(trow.modelData.n) : "")
                                color: trow.current ? Theme.gold : Theme.silverA(0.45); font.family: Theme.mono; font.pixelSize: 12
                            }
                            Text {
                                x: 50; y: trow.modelData.sub ? 7 : 0; width: parent.width - 50 - 64
                                height: trow.modelData.sub ? 20 : parent.height - 4; verticalAlignment: Text.AlignVCenter
                                text: trow.modelData.title; elide: Text.ElideRight
                                color: Theme.white; font.family: Theme.font; font.pixelSize: 14; font.bold: trow.current
                            }
                            Text {
                                visible: trow.modelData.sub !== ""
                                x: 50; y: 27; width: parent.width - 50 - 64; height: 16; verticalAlignment: Text.AlignVCenter
                                text: trow.modelData.sub; elide: Text.ElideRight
                                color: Theme.silverA(0.55); font.family: Theme.font; font.pixelSize: 11
                            }
                            Text {
                                anchors.right: parent.right; anchors.rightMargin: 12; height: parent.height - 4; verticalAlignment: Text.AlignVCenter
                                text: trow.modelData.dur > 0 ? Meta.dur(trow.modelData.dur) : ""
                                color: Theme.silverA(0.5); font.family: Theme.mono; font.pixelSize: 12
                            }
                        }
                        RowTap {
                            id: trTap
                            flick: page; tap: 0.98; holdRing: true
                            onClicked: root.play("load", trow.index)
                            onLongPress: (x, y) => { var p = mapToItem(root, x, y); root.trackMenu(trow.index, p.x, p.y) }
                        }
                    }
                }
            }

            // ── credits ────────────────────────────────────────────────────
            readonly property var credits: root.metaOk && root.meta.credits && root.meta.credits.length ? root.meta.credits : root.localCredits
            Item { width: 1; height: col.credits.length || (root.metaOk && (root.meta.places || []).length) ? 12 : 0 }
            SectionTitle { visible: col.credits.length > 0 || (root.metaOk && (root.meta.places || []).length > 0); text: Tr.t("player.page.credits") }
            CreditRows {
                width: col.width
                credits: col.credits
                places: root.metaOk ? (root.meta.places || []) : []
                discs: root.discs
                onPerson: (p) => root.openPerson(p)
            }
            // per-track detail, on request (a big box set has hundreds of lines)
            Item {
                visible: root.metaOk && (root.meta.tracks || []).some(function(t) { return t.credits && t.credits.length })
                width: col.width; height: visible ? 44 : 0
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: (root.byTrack ? "− " : "+ ") + Tr.t("player.page.creditsByTrack")
                    color: btTap.mix(Theme.gold, Theme.white); font.family: Theme.font; font.pixelSize: 13
                    Tap { id: btTap; grow: 8; onClicked: root.byTrack = !root.byTrack }
                }
            }
            Repeater {
                model: root.byTrack && root.metaOk ? (root.meta.tracks || []).filter(function(t) { return t.credits && t.credits.length }) : []
                Column {
                    required property var modelData
                    width: col.width
                    Text {
                        width: parent.width; height: 26; verticalAlignment: Text.AlignBottom; bottomPadding: 4; elide: Text.ElideRight
                        text: (root.discs > 1 ? modelData.disc + "." : "") + modelData.n + "  " + modelData.title
                        color: Theme.white; font.family: Theme.font; font.pixelSize: 13; font.bold: true
                    }
                    CreditRows { width: parent.width; credits: modelData.credits; grouped: false; discs: root.discs; onPerson: (p) => root.openPerson(p) }
                }
            }

            // ── about (Wikipedia) ──────────────────────────────────────────
            readonly property var about: root.metaOk ? root.meta.about : null
            Item { width: 1; height: col.about ? 16 : 0 }
            Rectangle {
                visible: !!col.about
                width: col.width; height: 44 + aboutText.height + 36; radius: 12
                color: Theme.surface; border.width: 1; border.color: Theme.border
                Icon { x: 16; y: 18; name: "scroll-text"; size: 15; color: Theme.gold }
                Text { x: 40; y: 16; height: 20; width: parent.width - 90; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; text: Tr.t("player.page.about"); color: Theme.white; font.family: Theme.font; font.pixelSize: 14 }
                Text { anchors.right: parent.right; anchors.rightMargin: 16; y: 16; height: 20; verticalAlignment: Text.AlignVCenter; text: Tr.t(root.aboutOpen ? "player.page.less" : "player.page.more"); color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 11 }
                Text {
                    id: aboutText
                    x: 16; y: 44; width: parent.width - 32; wrapMode: Text.Wrap
                    text: col.about ? String(col.about.text || "") : ""
                    color: Theme.silverA(0.85); font.family: Theme.font; font.pixelSize: 13
                    lineHeight: 20; lineHeightMode: Text.FixedHeight
                    maximumLineCount: root.aboutOpen ? 400 : 5; elide: Text.ElideRight
                }
                Text {
                    x: 16; y: aboutText.y + aboutText.height + 8; width: parent.width - 32; height: 16; elide: Text.ElideRight
                    text: col.about ? Tr.tf("player.page.fromWikipedia", "license", String(col.about.license || "CC BY-SA")) + (col.about.url ? " · " + String(col.about.url).replace(/^https?:\/\//, "") : "") : ""
                    color: Theme.silverA(0.4); font.family: Theme.font; font.pixelSize: 10
                }
                Tap { onClicked: root.aboutOpen = !root.aboutOpen }
            }

            // ── sources and the edition ────────────────────────────────────
            Item { width: 1; height: 16 }
            Text {
                visible: root.metaOk
                width: col.width; height: 18; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
                text: Tr.t("player.page.creditsSource") + (root.metaOk && root.meta.edited ? ", " + Tr.t("player.page.edited") : "")
                      + (root.metaOk && root.meta.release && root.meta.release.date ? " · " + Tr.tf("player.page.edition", "date", Meta.date(root.meta.release.date)) : "")
                color: Theme.silverA(0.4); font.family: Theme.font; font.pixelSize: 11
            }
            Item {
                visible: root.metaOk || root.metaStatus === "nomatch"
                width: col.width; height: visible ? 36 : 0
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: Tr.t("player.page.chooseEdition")
                    color: edTap.mix(Theme.gold, Theme.white); font.family: Theme.font; font.pixelSize: 13
                    Tap { id: edTap; grow: 8; onClicked: picker.open(root.albumId) }
                }
            }
        }
    }
    ScrollBar_ { flick: page; x: page.width - 3 }

    Spinner { visible: root.state_ === 0; active: visible && root.visible; radius: 20; anchors.horizontalCenter: parent.horizontalCenter; y: 60 }
    Column {
        visible: root.state_ === 3
        anchors.horizontalCenter: parent.horizontalCenter; y: 60; spacing: 12
        Icon { anchors.horizontalCenter: parent.horizontalCenter; name: "alert-circle"; size: 40; color: Theme.red400 }
        Text { anchors.horizontalCenter: parent.horizontalCenter; text: Tr.t("player.connectionErrorTitle"); color: Theme.white; font.family: Theme.font; font.pixelSize: 16; font.bold: true }
    }
    EditionPicker { id: picker; onPicked: { root.metaTries = 0; root.meta = null; root.metaStatus = "pending"; metaPoll.restart() } }
}
