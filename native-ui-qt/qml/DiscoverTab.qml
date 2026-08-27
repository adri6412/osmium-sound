// La scheda "Scopri" (Discover.jsx / screen_discover.c): mix infiniti con il
// filtro dei generi e i preset, "continua con musica simile", artisti simili
// e biografia dell'artista in riproduzione. Ogni blocco sparisce se il plugin
// che serve non c'e'.
import QtQuick
import Hifi.Ui

Item {
    id: root
    property real devScale: 1
    readonly property string presetFile: Sys.configDir + "/mix-genre-presets.json"
    property string dstmProvider: ""
    property bool dstmProbed: false
    property bool dstmAvailable: false
    property string dstmLast: ""
    property var genres: []            // [{name, included}]
    property int genState: 0           // 0 mai letti 1 in corso 2 pronti 3 errore
    property var similar: []           // [{name, id}]
    property string bio: ""
    property string bioArtist: ""
    property bool genrePanel: false
    property bool bioOpen: false
    property string msg: ""
    property var presets: []           // [{name, genres:[]}]
    property string presetDraft: ""
    property int presetDel: -1

    function enter() { if (bioArtist !== Player.artist) requestContext() }
    Connections { target: Player; function onTrackChanged() { if (root.visible && root.bioArtist !== Player.artist) root.requestContext() } }
    Component.onCompleted: {
        try { var p = JSON.parse(Sys.readFile(presetFile) || "[]"); presets = p.filter(function(x) { return x && x.name }) } catch (e) { presets = [] }
    }
    function savePresets() { Sys.writeLine(presetFile, JSON.stringify(presets)) }

    function stripHtml(s) { return String(s || "").replace(/<[^>]*>/g, "") }
    function requestContext() {
        var artist = Player.artist
        bioArtist = artist; bioOpen = false; similar = []; bio = ""
        if (!dstmProbed) {
            dstmProbed = true
            Player.query(["playerpref", "plugin.dontstopthemusic:provider", "?"], function(ok, r) {
                var v = ok && r ? (r._p2 !== undefined ? r._p2 : r.value) : undefined
                if (v !== undefined && v !== null) { dstmAvailable = true; dstmProvider = String(v) }
            })
        }
        if (!artist) return
        Player.query(["musicartistinfo", "similarartists", "artist:" + artist], function(ok, r) {
            if (!ok || !r || artist !== root.bioArtist) return
            var loop = r.similarartists_loop && r.similarartists_loop.length ? r.similarartists_loop : (r.item_loop || [])
            var out = []
            for (var i = 0; i < loop.length && out.length < 12; i++) { var nm = loop[i].name || loop[i].artist; if (nm) out.push({ name: String(nm), id: "" }) }
            if (!out.length) { similar = []; return }
            Player.query(["artists", "0", "9999"], function(ok2, r2) {
                if (ok2 && r2 && r2.artists_loop)
                    for (var i = 0; i < out.length; i++)
                        for (var j = 0; j < r2.artists_loop.length; j++)
                            if (String(r2.artists_loop[j].artist).toLowerCase() === out[i].name.toLowerCase()) { out[i].id = String(r2.artists_loop[j].id); break }
                if (artist === root.bioArtist) similar = out
            })
        })
        Player.query(["musicartistinfo", "biography", "artist:" + artist], function(ok, r) {
            if (!ok || !r || artist !== root.bioArtist) return
            var b = r.biography || r.biography_text || (r.item_loop && r.item_loop[0] ? r.item_loop[0].name : "")
            bio = stripHtml(b)
        })
    }
    function loadGenres() {
        genState = 1
        Player.query(["randomplaygenrelist", "0", "999"], function(ok, r) {
            if (!ok || !r) { genState = 3; return }
            // 🚨 il vero elenco di randomplaygenrelist ha `text` e `checkbox`;
            // le prime due voci ("Selezionare tutto"/"Deselezionare tutto") non
            // hanno checkbox e vanno scartate (come lyrionApi.getRandomPlayGenres)
            var loop = r.item_loop || []
            var out = []
            for (var i = 0; i < loop.length; i++) {
                var it = loop[i]
                if (it.checkbox === undefined || !it.text) continue
                out.push({ name: String(it.text), included: Number(it.checkbox) === 1 })
            }
            genres = out; genState = out.length ? 2 : 3
        })
    }
    function setGenre(i, on) { var g = genres.slice(); g[i] = { name: g[i].name, included: on }; genres = g; Player.cmd(["randomplaychoosegenre", g[i].name, on ? "1" : "0"]) }
    readonly property int includedCount: genres.filter(function(g) { return g.included }).length

    component Pill: Rectangle {
        property string label: ""
        property real px: 12
        property color fg: Theme.silver
        property real padX: 12
        property string icon: ""
        signal clicked()
        width: pillText.implicitWidth + padX * 2 + (icon ? 8 : 0); height: 28; radius: height / 2
        Icon { visible: !!parent.icon; x: 8; anchors.verticalCenter: parent.verticalCenter; name: parent.icon; size: 10; color: Theme.gold; filled: true }
        Text { id: pillText; x: parent.padX + (parent.icon ? 8 : 0); anchors.verticalCenter: parent.verticalCenter; text: parent.label; color: parent.fg; font.family: Theme.font; font.pixelSize: parent.px }
        Tap { onClicked: parent.clicked() }
    }

    Flickable {
        id: page
        anchors.fill: parent
        contentHeight: col.height + 32
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickDeceleration: 1500; maximumFlickVelocity: 4000
        Column {
            id: col
            x: 16; y: 16; width: parent.width - 32
            spacing: 0
            // ── Mix infiniti ────────────────────────────────────────────────
            Item {
                width: parent.width; height: 16
                Text { anchors.verticalCenter: parent.verticalCenter; text: Tr.up("player.discover.mixes"); color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 12; font.bold: true; font.letterSpacing: 0.6 }
                Item {
                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    width: filterRow.implicitWidth; height: 16
                    readonly property bool filtered: root.genState === 2 && root.includedCount < root.genres.length
                    Row {
                        id: filterRow
                        spacing: 4; height: parent.height
                        Icon { name: "sliders"; size: 13; color: filterRow.parent.filtered ? Theme.gold : Theme.silverA(0.6); anchors.verticalCenter: parent.verticalCenter }
                        Text { anchors.verticalCenter: parent.verticalCenter; color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 11
                               text: filterRow.parent.filtered ? Tr.tf("player.discover.genresCount", "count", String(root.includedCount)).replace("{total}", String(root.genres.length)) : Tr.t("player.discover.genresAll") }
                    }
                    Tap { grow: 8; onClicked: { root.genrePanel = !root.genrePanel; if (root.genrePanel && root.genState === 0) root.loadGenres() } }
                }
            }
            Item { width: 1; height: 8 }
            // pannello dei generi
            Rectangle {
                visible: root.genrePanel
                width: parent.width; height: gcol.height + 24; radius: 12; color: "transparent"; border.width: 1; border.color: Theme.border
                Column {
                    id: gcol
                    x: 12; y: 12; width: parent.width - 24; spacing: 12
                    Text { visible: root.genState !== 2; height: 16; verticalAlignment: Text.AlignVCenter; text: Tr.t(root.genState === 3 ? "player.discover.genresError" : "player.discover.genresLoading"); color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 11 }
                    Row {
                        visible: root.genState === 2; spacing: 8
                        Pill { label: Tr.t("player.discover.genresSelectAll"); px: 11; padX: 8; height: 24; color: Theme.dark; onClicked: { Player.cmd(["randomplaygenreselectall", "1"]); root.genres = root.genres.map(function(g) { return { name: g.name, included: true } }) } }
                        Pill { label: Tr.t("player.discover.genresSelectNone"); px: 11; padX: 8; height: 24; color: Theme.dark; onClicked: { Player.cmd(["randomplaygenreselectall", "0"]); root.genres = root.genres.map(function(g) { return { name: g.name, included: false } }) } }
                    }
                    Flow {
                        visible: root.genState === 2 && root.presets.length > 0
                        width: parent.width; spacing: 8
                        Repeater {
                            model: root.presets
                            Rectangle {
                                required property var modelData
                                required property int index
                                width: ptext.implicitWidth + 24 + 18; height: 28; radius: 14; color: Theme.dark
                                Text { id: ptext; x: 12; anchors.verticalCenter: parent.verticalCenter; text: modelData.name; color: Theme.silver; font.family: Theme.font; font.pixelSize: 12 }
                                Icon { x: parent.width - 18; anchors.verticalCenter: parent.verticalCenter; name: "trash-2"; size: 12; color: Theme.silverA(0.5) }
                                Tap {
                                    onClicked: (m) => {
                                        if (m.x > width - 20) { root.presetDel = index; return }
                                        Player.cmd(["randomplaygenreselectall", "0"])
                                        for (var j = 0; j < modelData.genres.length; j++) Player.cmd(["randomplaychoosegenre", modelData.genres[j], "1"])
                                        root.genres = root.genres.map(function(g) { return { name: g.name, included: modelData.genres.indexOf(g.name) >= 0 } })
                                    }
                                }
                            }
                        }
                    }
                    Rectangle {
                        visible: root.genState === 2 && root.presetDel >= 0 && root.presetDel < root.presets.length
                        width: parent.width; height: 32; radius: 8; color: Theme.dark
                        Text { x: 8; width: parent.width - 128; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; color: Theme.white; font.family: Theme.font; font.pixelSize: 12
                               text: root.presetDel >= 0 && root.presetDel < root.presets.length ? Tr.tf("player.discover.genresPresetDeleteConfirm", "name", root.presets[root.presetDel].name) : "" }
                        Text { anchors.right: parent.right; anchors.rightMargin: 30; anchors.verticalCenter: parent.verticalCenter; text: Tr.t("player.discover.genresPresetDelete"); color: Theme.red300; font.family: Theme.font; font.pixelSize: 12
                               Tap { grow: 8; onClicked: { var p = root.presets.slice(); p.splice(root.presetDel, 1); root.presets = p; root.presetDel = -1; root.savePresets() } } }
                    }
                    Flow {
                        visible: root.genState === 2
                        width: parent.width; spacing: 6
                        Repeater {
                            model: root.genres
                            Pill {
                                required property var modelData
                                required property int index
                                label: modelData.name; fg: modelData.included ? Theme.gold : Theme.silverA(0.7)
                                color: modelData.included ? Theme.goldA(0.2) : Theme.dark
                                border.width: modelData.included ? 1 : 0; border.color: Theme.gold
                                onClicked: root.setGenre(index, !modelData.included)
                            }
                        }
                    }
                    Row {
                        visible: root.genState === 2
                        width: parent.width; spacing: 8
                        TextField_ {
                            id: draft
                            width: parent.width - saveBtn.width - 8; height: 34; textSize: 12; padding: 12
                            color: Theme.surface; restBorder: Theme.accent
                            text: root.presetDraft; placeholder: Tr.t("player.discover.genresPresetNamePlaceholder")
                            onTextEdited: (t) => root.presetDraft = t
                        }
                        Rectangle {
                            id: saveBtn
                            width: saveText.implicitWidth + 24; height: 34; radius: 8; color: svTap.mix(Theme.light, Theme.accent)
                            Text { id: saveText; anchors.centerIn: parent; text: Tr.t("player.discover.genresPresetSaveAs"); color: Theme.white; font.family: Theme.font; font.pixelSize: 12 }
                            Tap { id: svTap; onClicked: {
                                if (!root.presetDraft || root.presets.length >= 8) return
                                var gs = root.genres.filter(function(g) { return g.included }).map(function(g) { return g.name }).slice(0, 16)
                                if (gs.length) { var p = root.presets.slice(); p.push({ name: root.presetDraft, genres: gs }); root.presets = p; root.savePresets() }
                                root.presetDraft = ""; draft.text = ""
                            } }
                        }
                    }
                }
            }
            Item { width: 1; height: root.genrePanel ? 12 : 0 }
            // i tre mix
            Row {
                width: parent.width; spacing: 12
                Repeater {
                    model: [{ icon: "shuffle", key: "player.discover.mixTracks", mode: "tracks" }, { icon: "disc", key: "player.discover.mixAlbums", mode: "albums" }, { icon: "user", key: "player.discover.mixArtists", mode: "contributors" }]
                    Rectangle {
                        required property var modelData
                        width: (parent.width - 24) / 3; height: 88; radius: 12
                        color: mxTap.mix(Theme.surface, Theme.light); border.width: 1; border.color: Theme.border
                        Icon { anchors.horizontalCenter: parent.horizontalCenter; y: 16; name: modelData.icon; size: 24; color: Theme.gold }
                        Text { anchors.horizontalCenter: parent.horizontalCenter; y: 48; height: 16; verticalAlignment: Text.AlignVCenter; text: Tr.t(modelData.key); color: Theme.white; font.family: Theme.font; font.pixelSize: 12 }
                        Tap { id: mxTap; onClicked: { Player.cmd(["randomplay", modelData.mode]); root.msg = Tr.t("player.discover.mixStarted") } }
                    }
                }
            }
            Text { visible: root.msg !== ""; width: parent.width; height: 24; verticalAlignment: Text.AlignVCenter; text: root.msg; color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 11 }
            Item { width: 1; height: 20 }
            // ── Don't Stop The Music ────────────────────────────────────────
            Rectangle {
                visible: root.dstmAvailable
                width: parent.width; height: 56; radius: 12; color: Theme.surface; border.width: 1; border.color: Theme.border
                readonly property bool on: root.dstmProvider !== ""
                Icon { x: 16; anchors.verticalCenter: parent.verticalCenter; name: "repeat"; size: 18; color: parent.on ? Theme.gold : Theme.silverA(0.5) }
                Text { x: 46; y: 10; height: 20; width: parent.width - 116; verticalAlignment: Text.AlignVCenter; text: Tr.t("player.discover.dstm"); color: Theme.white; font.family: Theme.font; font.pixelSize: 14; elide: Text.ElideRight }
                Text { x: 46; y: 30; height: 16; width: parent.width - 116; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 11
                       text: parent.on ? Tr.tf("player.discover.dstmOn", "provider", root.dstmProvider) : Tr.t("player.discover.dstmOff") }
                Rectangle {
                    x: parent.width - 60; anchors.verticalCenter: parent.verticalCenter; width: 44; height: 24; radius: 12
                    color: parent.on ? Theme.gold : Theme.wa(0.15)
                    Rectangle { x: parent.parent.on ? 22 : 2; y: 2; width: 20; height: 20; radius: 10; color: Theme.white; Behavior on x { NumberAnimation { duration: 120 } } }
                    Tap { grow: 8; onClicked: {
                        if (root.dstmProvider) { root.dstmLast = root.dstmProvider; Player.cmd(["playerpref", "plugin.dontstopthemusic:provider", ""]); root.dstmProvider = "" }
                        else if (root.dstmLast) { Player.cmd(["playerpref", "plugin.dontstopthemusic:provider", root.dstmLast]); root.dstmProvider = root.dstmLast }
                    } }
                }
            }
            Item { width: 1; height: root.dstmAvailable ? 20 : 0 }
            // ── Artisti simili ──────────────────────────────────────────────
            Column {
                visible: root.similar.length > 0
                width: parent.width
                Text { height: 16; verticalAlignment: Text.AlignVCenter; text: Tr.tf("player.discover.similarTo", "artist", root.bioArtist).toUpperCase(); color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 12; font.bold: true; font.letterSpacing: 0.6 }
                Item { width: 1; height: 8 }
                Flow {
                    width: parent.width; spacing: 8
                    Repeater {
                        model: root.similar
                        Pill {
                            required property var modelData
                            readonly property bool has: modelData.id !== ""
                            label: modelData.name; height: 32; icon: has ? "play" : ""; padX: 12
                            fg: has ? Theme.white : Theme.silverA(0.6)
                            color: has ? Theme.surface : Theme.wa(0.05); border.width: has ? 1 : 0; border.color: Theme.border
                            onClicked: if (has) Player.cmd(["playlistcontrol", "cmd:load", "artist_id:" + modelData.id])
                        }
                    }
                }
                Item { width: 1; height: 6 }
                Text { height: 14; verticalAlignment: Text.AlignVCenter; text: Tr.t("player.discover.similarHint"); color: Theme.silverA(0.4); font.family: Theme.font; font.pixelSize: 10 }
                Item { width: 1; height: 20 }
            }
            // ── Biografia ───────────────────────────────────────────────────
            Rectangle {
                visible: root.bio !== ""
                width: parent.width; height: 44 + bioText.height + 16; radius: 12; color: Theme.surface; border.width: 1; border.color: Theme.border
                Icon { x: 16; y: 18; name: "scroll-text"; size: 15; color: Theme.gold }
                Text { x: 40; y: 16; height: 20; width: parent.width - 80; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; text: Tr.tf("player.discover.bio", "artist", root.bioArtist); color: Theme.white; font.family: Theme.font; font.pixelSize: 14 }
                Text { anchors.right: parent.right; anchors.rightMargin: 16; y: 16; height: 20; verticalAlignment: Text.AlignVCenter; text: root.bioOpen ? "−" : "+"; color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 11 }
                Text { id: bioText; x: 16; y: 44; width: parent.width - 32; wrapMode: Text.Wrap; text: root.bio; color: Theme.silverA(0.8); font.family: Theme.font; font.pixelSize: 12; lineHeight: 18; lineHeightMode: Text.FixedHeight
                       maximumLineCount: root.bioOpen ? 1000 : 3; elide: Text.ElideRight }
                Tap { onClicked: root.bioOpen = !root.bioOpen }
            }
            Text { visible: root.similar.length === 0 && root.bio === ""; width: parent.width; wrapMode: Text.Wrap; maximumLineCount: 3; text: Tr.t("player.discover.hint"); color: Theme.silverA(0.4); font.family: Theme.font; font.pixelSize: 11 }
        }
        ScrollBar_ { flick: page; x: page.width - 3 }
    }
}
