// The artist page: name and details, play / shuffle / queue / favourite, the
// biography, the members of a group, the albums of the library by role
// (as artist, with the band, as composer, as conductor, appearing on), the
// other albums where the metadata service found a credit, similar artists.
// With `mbid` and no `artistId` it is a person known only to MusicBrainz
// (a producer, a session player): details and biography, no library.
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    property var browser: null
    property string artistId: ""
    property string mbid: ""
    property string name: ""
    property real devScale: 1

    property string portrait: ""
    property string favUrl: ""
    property var sections: []           // [{title, albums: [{id, album, year, art}]}]
    property int albumsState: 0         // 0 loading 2 ready
    property var meta: null
    property string metaStatus: ""
    property int metaTries: 0
    property var creditedAll: []        // [{album_id, title, artist, artwork_track_id, roles}]
    // minus the albums already in a block above (the two lists arrive in any order)
    readonly property var credited: {
        var shown = {}
        for (var i = 0; i < sections.length; i++)
            for (var j = 0; j < sections[i].albums.length; j++) shown[sections[i].albums[j].id] = true
        return creditedAll.filter(function(a) { return !shown[String(a.album_id)] })
    }
    property var similar: []            // [{name, id}]
    property bool bioOpen: false
    readonly property bool person: artistId === ""
    readonly property bool metaOk: meta !== null && !!meta.artist
    readonly property var art: metaOk ? (meta.artist || {}) : ({})
    readonly property var bio: metaOk ? meta.bio : null

    Component.onCompleted: load()
    function load() {
        loadMeta()
        if (person) { albumsState = 2; return }
        Player.query(["artists", "0", "1", "artist_id:" + artistId, "tags:s4"], function(ok, r) {
            if (!root) return          // the page was closed meanwhile
            var a = ok && r && r.artists_loop && r.artists_loop.length ? r.artists_loop[0] : null
            if (!a) return
            if (!root.name) {
                root.name = String(a.artist || "")
                if (root.browser) root.browser.setPageTitle(LibraryModel.ArtistPage, root.artistId, root.name)
            }
            root.favUrl = String(a.favorites_url || "")
            root.portrait = a.portraitid ? String(a.portraitid) : ""
            loadSimilar()
        })
        loadAlbums()
    }
    function loadMeta() {
        var path = person ? "/person?mbid=" + encodeURIComponent(mbid) : "/artist?artist_id=" + artistId
        Api.get(Meta.url(path), function(ok, d) {
            if (!root) return          // the page was closed meanwhile
            if (!ok || !d || typeof d !== "object") { root.metaStatus = "error"; return }
            root.metaStatus = String(d.status || "error")
            if ((d.status === "ok" || d.status === "pending") && d.artist) root.meta = d
            if (d.status === "ok") {
                var m = d.artist && d.artist.mbid ? String(d.artist.mbid) : root.mbid
                if (m) loadCredited(m)
            } else if (d.status === "pending" && root.metaTries++ < 45) metaPoll.restart()
        }, 15000)
    }
    Timer { id: metaPoll; interval: 2000; onTriggered: root.loadMeta() }

    // The library's albums for each role the artist has, in this order; an
    // album already shown in an earlier block is not repeated.
    function loadAlbums() {
        var blocks = [
            { roles: "ARTIST,ALBUMARTIST", key: "player.page.albums" },
            { roles: "BAND", key: "player.page.asBand" },
            { roles: "COMPOSER", key: "player.page.asComposer" },
            { roles: "CONDUCTOR", key: "player.page.asConductor" },
            { roles: "TRACKARTIST", key: "player.page.appearsOn" }]
        Player.query(["roles", "0", "50", "artist_id:" + artistId, "tags:t"], function(ok, r) {
            if (!root) return          // the page was closed meanwhile
            var have = {}
            var loop = ok && r ? (r.roles_loop || []) : []
            for (var i = 0; i < loop.length; i++) have[String(loop[i].role_name || "").toUpperCase()] = true
            // user-defined roles (Lyrion settings) get a block of their own, under their name
            for (var j = 0; j < loop.length; j++) {
                var rn = String(loop[j].role_name || "")
                if (["ARTIST", "ALBUMARTIST", "BAND", "COMPOSER", "CONDUCTOR", "TRACKARTIST"].indexOf(rn.toUpperCase()) < 0 && rn)
                    blocks.push({ roles: rn, title: Meta.humanize(rn.toLowerCase()) })
            }
            // a server that does not answer `roles`: just the albums
            if (!loop.length) have = { ARTIST: true }
            var wanted = blocks.filter(function(b) { return b.roles.split(",").some(function(x) { return have[x] }) })
            var results = new Array(wanted.length), left = wanted.length
            if (!left) { root.sections = []; root.albumsState = 2; return }
            for (var w = 0; w < wanted.length; w++) (function(w) {
                Player.query(["albums", "0", "500", "artist_id:" + artistId, "role_id:" + wanted[w].roles, "tags:alyjS", "sort:yearalbum"], function(ok2, r2) {
                    if (!root) return          // the page was closed meanwhile
                    results[w] = ok2 && r2 ? (r2.albums_loop || []) : []
                    if (--left) return
                    var seen = {}, out = []
                    for (var k = 0; k < wanted.length; k++) {
                        var al = []
                        for (var n = 0; n < results[k].length; n++) {
                            var x = results[k][n], id = String(x.id)
                            if (seen[id]) continue
                            seen[id] = true
                            al.push({ id: id, album: String(x.album || ""), year: Number(x.year || 0), art: String(x.artwork_track_id || ""), artist: String(x.artist || "") })
                        }
                        if (al.length) out.push({ title: wanted[k].title || Tr.t(wanted[k].key), albums: al })
                    }
                    root.sections = out
                    root.albumsState = 2
                })
            })(w)
        })
    }
    // albums of the library where this person has a credit (from what the
    // metadata service has already looked up)
    function loadCredited(m) {
        Api.get(Meta.url("/appearances?mbid=" + encodeURIComponent(m)), function(ok, d) {
            if (!root) return          // the page was closed meanwhile
            if (ok && d && d.status === "ok") root.creditedAll = d.albums || []
        })
    }
    function loadSimilar() {
        var nm = root.name
        if (!nm) return
        Player.query(["musicartistinfo", "similarartists", "artist:" + nm], function(ok, r) {
            if (!root) return          // the page was closed meanwhile
            if (!ok || !r) return
            var loop = r.similarartists_loop && r.similarartists_loop.length ? r.similarartists_loop : (r.item_loop || [])
            var out = []
            for (var i = 0; i < loop.length && out.length < 12; i++) { var s = loop[i].name || loop[i].artist; if (s) out.push({ name: String(s), id: "" }) }
            if (!out.length) return
            Player.query(["artists", "0", "9999"], function(ok2, r2) {
                if (!root) return          // the page was closed meanwhile
                if (ok2 && r2 && r2.artists_loop)
                    for (var i = 0; i < out.length; i++)
                        for (var j = 0; j < r2.artists_loop.length; j++)
                            if (String(r2.artists_loop[j].artist).toLowerCase() === out[i].name.toLowerCase()) { out[i].id = String(r2.artists_loop[j].id); break }
                root.similar = out.filter(function(x) { return x.id !== "" })
            })
        })
    }

    function play(mode) { if (!person) Player.cmd(["playlistcontrol", "cmd:" + mode, "artist_id:" + artistId]) }
    function openPerson(p) {
        var id = String(p.artist_id || p.id || "")
        if (id && browser) browser.openArtist(id, String(p.name || ""))
        else if (p.mbid && browser) browser.openPerson(String(p.mbid), String(p.name || ""))
    }

    readonly property string detailLine: {
        var a = art, parts = []
        var t = String(a.type || "")
        if (t === "group") parts.push(Tr.t("player.page.typeGroup"))
        else if (t === "orchestra") parts.push(Tr.t("player.page.typeOrchestra"))
        else if (t === "choir") parts.push(Tr.t("player.page.typeChoir"))
        if (a.begin || a.end) {
            if (t === "person") {
                if (a.begin) parts.push(Tr.tf("player.page.born", "date", Meta.date(a.begin)))
                if (a.end) parts.push(Tr.tf("player.page.died", "date", Meta.date(a.end)))
            } else if (a.begin && a.end) parts.push(Tr.tf("player.page.active", "from", Meta.year(a.begin)).replace("{to}", Meta.year(a.end)))
            else if (a.begin) parts.push(Tr.tf("player.page.activeSince", "from", Meta.year(a.begin)))
        }
        var place = String(a.begin_area || "")
        if (a.area && a.area !== place) place = place ? place + ", " + a.area : String(a.area)
        if (place) parts.push(place)
        if (a.disambiguation) parts.push(String(a.disambiguation))
        return parts.join(" · ")
    }
    function memberLine(m) {
        // "original" and "eponymous" say how, not what: only instruments and voices are listed
        var bits = (m.attrs || []).filter(function(x) { return x !== "original" && x !== "eponymous" }).map(function(x) { return Meta.tt("meta.instrument." + x, Meta.humanize(x)) })
        var yrs = (m.spans || [m]).map(function(p) {
            var b = Meta.year(p.begin), e = p.ended || p.end ? Meta.year(p.end) : ""
            return !b && !e ? "" : b && b === e ? b : b + "–" + e       // 1960–1960 is just 1960
        })
                                  .filter(function(x, i, all) { return !!x && all.indexOf(x) === i }).join(", ")
        return [bits.join(", "), yrs].filter(function(x) { return !!x }).join(" · ")
    }
    // one card per person: someone who left and came back (Richard Wright,
    // 1965–1981 and 1987–2008) has two memberships in MusicBrainz
    function mergeMembers(list) {
        var out = [], byKey = {}
        for (var i = 0; i < (list || []).length; i++) {
            var m = list[i], key = m.mbid || m.name
            if (!byKey[key]) {
                byKey[key] = { name: m.name, mbid: m.mbid, artist_id: m.artist_id, attrs: [], spans: [] }
                out.push(byKey[key])
            }
            var e = byKey[key]
            for (var j = 0; j < (m.attrs || []).length; j++) if (e.attrs.indexOf(m.attrs[j]) < 0) e.attrs.push(m.attrs[j])
            e.spans.push({ begin: m.begin, end: m.end, ended: m.ended })
            if (!e.artist_id && m.artist_id) e.artist_id = m.artist_id
        }
        return out
    }

    // the album covers: the same card as the library grid, lighter (one mask)
    readonly property real cardW: Math.floor((width - 32 - 24) / 3)
    Rectangle {
        id: artMask
        width: Math.max(1, root.cardW); height: Math.max(1, root.cardW)
        visible: false; radius: 12
        layer.enabled: true; layer.smooth: true
        layer.textureSize: Qt.size(Math.max(1, Math.ceil(root.cardW * root.devScale)), Math.max(1, Math.ceil(root.cardW * root.devScale)))
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 12 }
    }
    // 🚨 an inline component does not see this file's ids: size, mask and the
    // tap all come in as properties
    component AlbumCard: Item {
        id: card
        property string albumId: ""
        property string title: ""
        property string sub: ""
        property string art: ""
        property real cw: 100
        property real devScale: 1
        property var mask: null
        signal open(string id, string title)
        width: cw; height: cw + 48
        Rectangle { anchors.fill: parent; radius: 12; color: cTap.pressed ? Theme.mix(Theme.surface, Theme.wa(0.05), 1) : Theme.surface; border.width: 1; border.color: Theme.border }
        DiagonalFallback {
            width: card.cw; height: card.cw; radius: 12; visible: cImg.status !== Image.Ready
            Icon { anchors.centerIn: parent; name: "disc"; size: 40; color: Theme.silverA(0.2) }
        }
        Image {
            id: cImg; width: card.cw; height: card.cw; visible: false
            readonly property int px: Theme.coverPx(card.cw)
            source: card.art ? Api.lmsBase + "/music/" + card.art + "/cover?size=" + px : ""
            asynchronous: true; cache: true; fillMode: Image.PreserveAspectCrop; smooth: true
            sourceSize.width: px; sourceSize.height: px
            layer.enabled: true; layer.smooth: true
            layer.textureSize: Qt.size(Math.ceil(card.cw * card.devScale), Math.ceil(card.cw * card.devScale))
        }
        ShaderImage { width: card.cw; height: card.cw; source: cImg; mask: card.mask; visible: cImg.status === Image.Ready }
        Text { x: 8; y: card.cw + 8; width: parent.width - 16; height: 16; verticalAlignment: Text.AlignVCenter; text: card.title; elide: Text.ElideRight; color: Theme.white; font.family: Theme.font; font.pixelSize: 12 }
        Text { x: 8; y: card.cw + 24; width: parent.width - 16; height: 16; verticalAlignment: Text.AlignVCenter; text: card.sub; elide: Text.ElideRight; color: Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 12 }
        Tap { id: cTap; onClicked: card.open(card.albumId, card.title) }
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

        Column {
            id: col
            x: 16; y: 16; width: page.width - 32

            // ── header ─────────────────────────────────────────────────────
            Item {
                width: parent.width; height: Math.max(112, head.height)
                Item {
                    id: avatar
                    width: 112; height: 112
                    Rectangle { anchors.fill: parent; radius: 56; color: Theme.light; visible: pImg.status !== Image.Ready }
                    Icon { anchors.centerIn: parent; visible: pImg.status !== Image.Ready; name: root.art.type === "group" || root.art.type === "orchestra" || root.art.type === "choir" ? "users" : "user"; size: 44; color: Theme.silverA(0.5) }
                    Image {
                        id: pImg; anchors.fill: parent; visible: false
                        source: root.portrait ? Api.lmsBase + "/contributor/" + root.portrait + "/image_" + Theme.coverPx(112) + "x" + Theme.coverPx(112) + "_f" : ""
                        asynchronous: true; cache: true; fillMode: Image.PreserveAspectCrop; smooth: true
                        sourceSize.width: Theme.coverPx(112); sourceSize.height: Theme.coverPx(112)
                        layer.enabled: true; layer.smooth: true
                        layer.textureSize: Qt.size(Math.ceil(112 * root.devScale), Math.ceil(112 * root.devScale))
                    }
                    Rectangle { id: roundMask; anchors.fill: parent; radius: 56; visible: false; layer.enabled: true; layer.smooth: true
                                layer.textureSize: Qt.size(Math.ceil(112 * root.devScale), Math.ceil(112 * root.devScale)) }
                    ShaderImage { anchors.fill: parent; source: pImg; mask: roundMask; visible: pImg.status === Image.Ready }
                }
                Column {
                    id: head
                    x: 128; width: parent.width - 128
                    Item { width: 1; height: 8 }
                    Text {
                        width: parent.width; text: root.name || String(root.art.name || "")
                        color: Theme.white; font.family: Theme.font; font.pixelSize: 22; font.bold: true
                        wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight
                        lineHeight: 28; lineHeightMode: Text.FixedHeight
                    }
                    Item { width: 1; height: root.detailLine ? 4 : 0 }
                    Text { visible: root.detailLine !== ""; width: parent.width; text: root.detailLine; color: Theme.silverA(0.65); font.family: Theme.font; font.pixelSize: 12; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight }
                    Item { width: 1; height: root.person ? 4 : 0 }
                    Text { visible: root.person; width: parent.width; text: Tr.t("player.page.notInLibrary"); color: Theme.silverA(0.45); font.family: Theme.font; font.pixelSize: 12 }
                    Item { width: 1; height: 12 }
                    Row {
                        visible: !root.person
                        spacing: 10
                        PageButton { icon: "play"; filled: true; primary: true; label: Tr.t("player.page.play"); onClicked: root.play("load") }
                        PageButton { icon: "shuffle"; label: Tr.t("player.page.shuffle"); onClicked: if (root.browser) root.browser.loadShuffled("artist_id", root.artistId) }
                        PageButton { icon: "list-plus"; onClicked: root.play("add") }
                        PageButton { icon: "heart"; visible: root.favUrl !== ""; onClicked: if (root.browser) root.browser.addFavorite(root.favUrl, root.name, "playlist") }
                    }
                }
            }
            Item { width: 1; height: statusText.visible ? 12 : 0 }
            Text {
                id: statusText
                visible: text !== ""
                width: parent.width; wrapMode: Text.Wrap
                text: root.metaStatus === "pending" && !root.metaOk ? Tr.t("player.page.lookingUp")
                    : root.metaStatus === "offline" ? Tr.t("player.page.offline")
                    : root.metaStatus === "nomatch" && root.person ? Tr.t("player.page.noMatchArtist") : ""
                color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 12
            }

            // ── biography ──────────────────────────────────────────────────
            Item { width: 1; height: root.bio ? 16 : 0 }
            Rectangle {
                visible: !!root.bio
                width: col.width; height: 44 + bioText.height + 36; radius: 12
                color: Theme.surface; border.width: 1; border.color: Theme.border
                Icon { x: 16; y: 18; name: "scroll-text"; size: 15; color: Theme.gold }
                Text { x: 40; y: 16; height: 20; width: parent.width - 90; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; text: Tr.t("player.page.bio"); color: Theme.white; font.family: Theme.font; font.pixelSize: 14 }
                Text { anchors.right: parent.right; anchors.rightMargin: 16; y: 16; height: 20; verticalAlignment: Text.AlignVCenter; text: Tr.t(root.bioOpen ? "player.page.less" : "player.page.more"); color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 11 }
                Text {
                    id: bioText
                    x: 16; y: 44; width: parent.width - 32; wrapMode: Text.Wrap
                    text: root.bio ? String(root.bio.text || "") : ""
                    color: Theme.silverA(0.85); font.family: Theme.font; font.pixelSize: 13
                    lineHeight: 20; lineHeightMode: Text.FixedHeight
                    maximumLineCount: root.bioOpen ? 400 : 5; elide: Text.ElideRight
                }
                Text {
                    x: 16; y: bioText.y + bioText.height + 8; width: parent.width - 32; height: 16; elide: Text.ElideRight
                    text: root.bio ? Tr.tf("player.page.fromWikipedia", "license", String(root.bio.license || "CC BY-SA")) + (root.bio.url ? " · " + String(root.bio.url).replace(/^https?:\/\//, "") : "") : ""
                    color: Theme.silverA(0.4); font.family: Theme.font; font.pixelSize: 10
                }
                Tap { onClicked: root.bioOpen = !root.bioOpen }
            }

            // ── members / member of ────────────────────────────────────────
            Repeater {
                model: [{ key: "player.page.members", list: root.mergeMembers(root.art.members) }, { key: "player.page.memberOf", list: root.mergeMembers(root.art.member_of) }]
                Column {
                    required property var modelData
                    visible: modelData.list.length > 0
                    width: col.width
                    Item { width: 1; height: 8 }
                    SectionTitle { text: Tr.t(modelData.key) }
                    Flow {
                        width: parent.width; spacing: 8
                        Repeater {
                            model: modelData.list
                            Rectangle {
                                required property var modelData
                                readonly property string libId: String(modelData.artist_id || "")
                                readonly property string line: root.memberLine(modelData)
                                width: Math.min(col.width, Math.max(mName.implicitWidth, mSub.implicitWidth) + 28); height: line ? 50 : 34; radius: 10
                                color: mTap.pressed ? Theme.light : Theme.surface; border.width: 1; border.color: Theme.border
                                Text { id: mName; x: 14; y: line ? 8 : 0; height: line ? 18 : parent.height; width: parent.width - 28; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
                                       text: String(modelData.name || ""); color: libId ? Theme.white : Theme.silverA(0.9); font.family: Theme.font; font.pixelSize: 13 }
                                Text { id: mSub; visible: !!line; x: 14; y: 27; height: 15; width: parent.width - 28; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
                                       text: line; color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 11 }
                                Tap { id: mTap; enabled: !!(libId || modelData.mbid); onClicked: root.openPerson(modelData) }
                            }
                        }
                    }
                }
            }

            // ── the library's albums, by role ──────────────────────────────
            Repeater {
                model: root.sections
                Column {
                    required property var modelData
                    width: col.width
                    Item { width: 1; height: 8 }
                    SectionTitle { text: modelData.title + "  ·  " + modelData.albums.length }
                    Flow {
                        width: parent.width; spacing: 12
                        Repeater {
                            model: modelData.albums
                            AlbumCard {
                                required property var modelData
                                albumId: modelData.id; title: modelData.album; art: modelData.art
                                sub: modelData.year > 0 ? String(modelData.year) : ""
                                cw: root.cardW; devScale: root.devScale; mask: artMask
                                onOpen: (id, title) => { if (root.browser) root.browser.openAlbum(id, title) }
                            }
                        }
                    }
                }
            }
            Text {
                visible: !root.person && root.albumsState === 2 && root.sections.length === 0
                width: col.width; height: 40; verticalAlignment: Text.AlignVCenter
                text: Tr.t("player.page.noAlbums"); color: Theme.silverA(0.45); font.family: Theme.font; font.pixelSize: 13
            }

            // ── other albums where this person is credited ─────────────────
            Column {
                visible: root.credited.length > 0
                width: col.width
                Item { width: 1; height: 8 }
                SectionTitle { text: Tr.t("player.page.creditedOn") }
                Repeater {
                    model: root.credited
                    Item {
                        required property var modelData
                        width: col.width; height: 56
                        Rectangle { anchors.fill: parent; anchors.bottomMargin: 4; radius: 8; color: crTap.pressed ? Theme.light : Theme.surface }
                        Text { x: 14; y: 7; width: parent.width - 28; height: 20; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
                               text: String(modelData.title || "") + (modelData.artist ? " — " + modelData.artist : ""); color: Theme.white; font.family: Theme.font; font.pixelSize: 14 }
                        Text { x: 14; y: 28; width: parent.width - 28; height: 16; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
                               text: (modelData.roles || []).map(function(r) { return Meta.roleLabel(r) }).join(", "); color: Theme.silverA(0.55); font.family: Theme.font; font.pixelSize: 11 }
                        Tap { id: crTap; onClicked: if (root.browser) root.browser.openAlbum(String(modelData.album_id), String(modelData.title || "")) }
                    }
                }
            }

            // ── similar artists (Music & Artist Information, when installed) ─
            Column {
                visible: root.similar.length > 0
                width: col.width
                Item { width: 1; height: 8 }
                SectionTitle { text: Tr.t("player.page.similar") }
                Flow {
                    width: parent.width; spacing: 8
                    Repeater {
                        model: root.similar
                        Rectangle {
                            required property var modelData
                            width: sName.implicitWidth + 28; height: 32; radius: 16
                            color: sTap.pressed ? Theme.light : Theme.surface; border.width: 1; border.color: Theme.border
                            Text { id: sName; anchors.centerIn: parent; text: modelData.name; color: Theme.white; font.family: Theme.font; font.pixelSize: 12 }
                            Tap { id: sTap; onClicked: if (root.browser) root.browser.openArtist(modelData.id, modelData.name) }
                        }
                    }
                }
            }

            Item { width: 1; height: root.metaOk ? 16 : 0 }
            Text {
                visible: root.metaOk
                width: col.width; height: 18; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
                text: Tr.t("player.page.creditsSource"); color: Theme.silverA(0.4); font.family: Theme.font; font.pixelSize: 11
            }
        }
    }
    ScrollBar_ { flick: page; x: page.width - 3 }
}
