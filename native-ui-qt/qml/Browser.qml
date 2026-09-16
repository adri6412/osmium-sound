// Il pannello di destra: barra dei tab, briciole e contenuto (griglia della
// home oppure le liste della libreria), come draw_right in screen_main.c.
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    property real devScale: 1
    property int tab: 0                       // 0 musica 1 radio 2 app 3 scopri 4 impostazioni
    property var nav: [{ view: LibraryModel.Home, title: Tr.t("player.titles.home"), p1: "", p2: "", input: "" }]
    readonly property var cur: nav[nav.length - 1]
    readonly property int view: cur.view
    readonly property bool hasCrumbs: tab !== 4 && tab !== 3
    readonly property real contentTop: hasCrumbs ? 83 : 40
    readonly property bool hasSearch: tab === 0 && (view === LibraryModel.Artists || view === LibraryModel.Albums || view === LibraryModel.Composers)
    readonly property bool hasAz: hasSearch
    readonly property bool browsing: tab === 0 && view !== LibraryModel.Home
    // the album and artist pages load their own data (AlbumPage.qml, ArtistPage.qml)
    readonly property bool isPage: view === LibraryModel.AlbumPage || view === LibraryModel.ArtistPage
    property bool msearchOpen: false
    property string msearchTitle: ""
    property var msearchGo: []
    property var msearchPlugin: null      // { cmd, item } quando la ricerca e' di un plugin (Radio/App)
    property alias settingsTab: settingsTab
    property alias discoverTab: discoverTab
    readonly property var pageItem: pageLoader.item       // the album/artist page on screen, if any
    x: 341; width: 1024 - 341; height: 600

    // ─── "Aggiornamento disponibile" sul tab delle impostazioni ────────────
    // Come nel kiosk Electron: si guardano i tre componenti (interfaccia,
    // sistema, sistema operativo) ogni quarto d'ora — non piu' spesso, perche'
    // ogni giro passa da GitHub — e si rispetta l'interruttore "controlla
    // aggiornamenti automaticamente".
    property bool updateAvailable: false
    property var updSeen: [false, false, false]
    function checkUpdates() {
        if (Sys.conf("ota-autocheck", "1") === "0") { updateAvailable = false; return }
        var paths = ["/app_update/check", "/system_update/check", "/os_update/check"]
        for (var i = 0; i < 3; i++) (function(i) {
            Api.get(Api.apiBase + paths[i], function(ok, d) {
                if (!ok || !d) return
                var u = root.updSeen.slice()
                u[i] = !!d.update_available
                root.updSeen = u
                root.updateAvailable = u[0] || u[1] || u[2]
            }, 60000)       // the image check alone can outlast 15 s (manifest + sha256 with retries)
        })(i)
    }
    Timer { interval: 15 * 60 * 1000; repeat: true; triggeredOnStart: true; running: true; onTriggered: root.checkUpdates() }

    readonly property var tabs: [
        { icon: "music", key: "player.tabs.music" }, { icon: "radio", key: "player.tabs.radio" },
        { icon: "app-window", key: "player.tabs.apps" }, { icon: "compass", key: "player.tabs.discover" },
        { icon: "settings", key: "" }]
    readonly property var tiles: [
        { icon: "user", key: "player.titles.artists", view: LibraryModel.Artists },
        { icon: "disc", key: "player.titles.albums", view: LibraryModel.Albums },
        { icon: "tag", key: "player.titles.genres", view: LibraryModel.Genres },
        { icon: "calendar", key: "player.titles.years", view: LibraryModel.Years },
        { icon: "piano", key: "player.titles.composers", view: LibraryModel.Composers },
        { icon: "sparkles", key: "player.titles.newMusic", view: LibraryModel.NewMusic },
        { icon: "folder", key: "player.titles.folders", view: LibraryModel.Folders },
        { icon: "list-music", key: "player.titles.playlists", view: LibraryModel.Playlists },
        { icon: "heart", key: "player.titles.favorites", view: LibraryModel.PluginItems }]

    // ─── navigazione ───────────────────────────────────────────────────────
    function loadTop() {
        if (cur.view === LibraryModel.Home) return
        if (cur.view === LibraryModel.AlbumPage || cur.view === LibraryModel.ArtistPage) {
            // a fresh page every time, also from one album page to another
            pageLoader.sourceComponent = null
            pageLoader.sourceComponent = cur.view === LibraryModel.AlbumPage ? albumPageComp : artistPageComp
            return
        }
        pageLoader.sourceComponent = null
        Library.request(cur.view, cur.p1, cur.p2, cur.input)
        list.scrollTop()
    }
    function goView(view, title, p1, p2, input, replace) {
        var n = nav.slice()
        var e = { view: view, title: title || "…", p1: p1 || "", p2: p2 || "", input: input || "" }
        if (replace) n[n.length - 1] = e; else { if (n.length >= 16) return; n.push(e) }
        nav = n
        search.text = ""; Library.filter = ""
        ctx.visible = false
        if (!(replace && msearchOpen)) msearchOpen = false
        loadTop()
        appear()
    }
    // 🚨 Se l'apparecchio passa a un altro Lyrion (multiroom "segui", o server
    // esterno), quello che si sta guardando e' l'elenco del server di prima:
    // si riparte dalla home di quello nuovo.
    Connections { target: Api; function onLmsBaseChanged() { root.navHome() } }

    function navHome() {
        nav = [{ view: LibraryModel.Home, title: Tr.t("player.titles.home"), p1: "", p2: "", input: "" }]
        msearchOpen = false; ctx.visible = false; search.text = ""
        pageLoader.sourceComponent = null
        appear()
    }
    function navBack() {
        if (nav.length <= 1) return
        var n = nav.slice(); n.pop(); nav = n
        msearchOpen = false; search.text = ""; ctx.visible = false
        loadTop(); appear()
    }
    function navToCrumb(i) {
        if (i >= nav.length - 1) return
        nav = nav.slice(0, i + 1)
        msearchOpen = false; search.text = ""; ctx.visible = false
        loadTop(); appear()
    }
    function openTab(i) {
        tab = i; ctx.visible = false
        if (i === 1) { navHome(); goView(LibraryModel.Radios, Tr.t("player.titles.radio")) }
        else if (i === 2) { navHome(); goView(LibraryModel.MenuHome, Tr.t("player.titles.apps")) }
        else if (i === 0) {
            var v = view
            if (!(v === LibraryModel.Home || v === LibraryModel.Artists || v === LibraryModel.Albums || v === LibraryModel.Tracks ||
                  v === LibraryModel.Folders || v === LibraryModel.Playlists || v === LibraryModel.PlaylistTracks ||
                  v === LibraryModel.Genres || v === LibraryModel.Years || v === LibraryModel.Composers ||
                  v === LibraryModel.NewMusic || v === LibraryModel.Search || v === LibraryModel.AlbumPage || v === LibraryModel.ArtistPage)) navHome()
        } else if (i === 4) settingsTab.enter()
        else if (i === 3) discoverTab.enter()
        appear()
    }
    function showPlaylists() { tab = 0; navHome(); goView(LibraryModel.Playlists, Tr.t("player.titles.playlists")) }
    // the album and artist pages, from anywhere (library, search, Now Playing,
    // credits); a person known only to MusicBrainz opens the artist page by mbid
    function showMusicTab() { if (tab !== 0) { tab = 0; ctx.visible = false } }
    function openAlbum(id, title) { if (!id) return; showMusicTab(); goView(LibraryModel.AlbumPage, title, String(id)) }
    function openArtist(id, name) { if (!id) return; showMusicTab(); goView(LibraryModel.ArtistPage, name, String(id)) }
    function openPerson(mbid, name) { if (!mbid) return; showMusicTab(); goView(LibraryModel.ArtistPage, name, "", "mbid:" + mbid) }
    function openMenu(items, x, y) { ctx.open(items, x, y) }
    // a page opened without its title (from a track's menu) names its crumb once loaded
    function setPageTitle(view, id, title) {
        if (!title || cur.view !== view || String(cur.p1) !== String(id)) return
        var n = nav.slice(); n[n.length - 1] = Object.assign({}, cur, { title: title }); nav = n
    }
    // shuffle on first, then load: Lyrion shuffles what it loads (two separate
    // requests could arrive in either order)
    function loadShuffled(type, id) {
        Player.query(["playlist", "shuffle", "1"], function() { Player.cmd(["playlistcontrol", "cmd:load", type + ":" + id]) })
    }
    function playItem(type, id, mode) { Player.cmd(["playlistcontrol", "cmd:" + mode, type + ":" + id]) }
    // la ricerca nella libreria (Lyrion `search`): dalla home, oppure da una
    // pagina di risultati per cercare di nuovo
    function submitLibrarySearch(text) {
        var t = (text || "").trim()
        if (t.length < 2) return
        var same = cur.view === LibraryModel.Search
        goView(LibraryModel.Search, Tr.t("player.titles.search") + ": " + t, "", "", t, same)
    }

    // ─── menu a pressione lunga: preferiti, playlist ─────────────────────
    function say(icon, key) { Ui.toast.say(icon, Tr.t(key)) }
    function addFavorite(url, title, type) {
        if (!url) return
        Player.favoriteExists(url, function(ex) {
            if (ex) { say("heart", "player.alreadyFavorite"); return }
            Player.favoriteAdd(url, title, type || "audio", "", function(ok) {
                say("heart", ok ? "player.addedToFavorites" : "player.favoriteError")
                if (ok && cur.view === LibraryModel.PluginItems && cur.p1 === "favorites") loadTop()
            })
        })
    }
    function renamePlaylist(it) {
        Ui.overlays.prompt(Tr.t("player.renameTitle"), it.text, function(name) {
            if (!name || name === it.text) return
            // prova a vuoto prima: rinominare su un nome esistente sovrascriverebbe l'altra playlist
            Player.query(["playlists", "rename", "playlist_id:" + it.id, "newname:" + name, "dry_run:1"], function(ok, r) {
                if (ok && r && r.overwritten_playlist_id !== undefined) { say("alert-triangle", "player.playlistExists"); return }
                Player.query(["playlists", "rename", "playlist_id:" + it.id, "newname:" + name], function(ok2) {
                    if (ok2) loadTop(); else say("alert-triangle", "player.saveError")
                })
            })
        })
    }
    function deletePlaylist(it) {
        Ui.dialogs.confirm(Tr.tf("player.playlistDeleteConfirm", "name", it.text), Tr.t("player.delete"), true, function(ok) {
            if (!ok) return
            Player.query(["playlists", "delete", "playlist_id:" + it.id], function() { loadTop() })
        })
    }
    function removeFromPlaylist(row) {
        Player.query(["playlists", "edit", "cmd:delete", "playlist_id:" + cur.p1, "index:" + row], function() { loadTop() })
    }
    // preferiti: la posizione e' l'id della voce ("3", oppure "1.2" in una cartella)
    function favSibling(id, delta) {
        var parts = String(id).split("."), n = parseInt(parts[parts.length - 1], 10) + delta
        if (isNaN(n) || n < 0) return ""
        parts[parts.length - 1] = String(n)
        return parts.join(".")
    }
    // dentro un'app o un plugin la coda si comanda col plugin stesso
    // (`<cmd> playlist add|insert item_id:…`), non con playlistcontrol: gli id
    // sono del plugin, non della libreria. Su un contenitore Lyrion prende
    // tutto quello che c'e' sotto, come fa la sua interfaccia.
    function pluginQueueItems(L, cmd, id) {
        function q(mode) { return function() { Player.cmd([cmd, "playlist", mode, "item_id:" + id]) } }
        L.push({ icon: "list-plus", label: Tr.t("player.addToQueue"), cb: q("add") })
        L.push({ icon: "list-start", label: Tr.t("player.playNext"), cb: q("insert") })
    }
    function favoriteMenu(it, row) {
        var L = []
        // un preferito e' musica quanto la riga da cui e' nato: stessa coda,
        // piu' le voci che valgono solo qui (rinomina, sposta, togli)
        var isDir = it.hasItems && !it.isAudio
        if (it.isAudio || isDir) {
            pluginQueueItems(L, "favorites", it.id)
            L.push({ icon: "pencil", label: Tr.t("player.rename"), cb: function() {
                Ui.overlays.prompt(Tr.t("player.renameTitle"), it.text, function(name) {
                    if (!name || name === it.text) return
                    Player.query(["favorites", "rename", "item_id:" + it.id, "title:" + name], function() { loadTop() })
                })
            } })
        }
        if (row > 0) L.push({ icon: "arrow-up", label: Tr.t("player.moveUp"), cb: function() {
            Player.query(["favorites", "move", "from_id:" + it.id, "to_id:" + favSibling(it.id, -1)], function() { loadTop() })
        } })
        if (row < Library.count - 1) L.push({ icon: "arrow-down", label: Tr.t("player.moveDown"), cb: function() {
            Player.query(["favorites", "move", "from_id:" + it.id, "to_id:" + favSibling(it.id, 1)], function() { loadTop() })
        } })
        L.push({ icon: "trash-2", label: Tr.t("player.removeFromFavorites"), danger: true, cb: function() {
            Ui.dialogs.confirm(Tr.tf("player.favoriteDeleteConfirm", "name", it.text), Tr.t("player.delete"), true, function(ok) {
                if (ok) Player.favoriteDelete(it.id, function() { loadTop() })
            })
        } })
        return L
    }
    // le voci del menu per la riga `it` della vista corrente
    function ctxItems(row) {
        var it = Library.get(row), v = view, L = []
        function q(type, mode) { return function() { playItem(type, it.id, mode) } }
        function queueItems(type) {
            L.push({ icon: "list-plus", label: Tr.t("player.addToQueue"), cb: q(type, "add") })
            L.push({ icon: "list-start", label: Tr.t("player.playNext"), cb: q(type, "insert") })
        }
        function fav(url, type) { if (url) L.push({ icon: "heart", label: Tr.t("player.addToFavorites"), cb: function() { addFavorite(url, it.text, type) } }) }
        switch (v) {
        case LibraryModel.Tracks: case LibraryModel.PlaylistTracks:
            queueItems("track_id"); fav(it.favUrl, "audio")
            if (it.albumId) L.push({ icon: "disc", label: Tr.t("player.page.goToAlbum"), cb: function() { openAlbum(it.albumId, "") } })
            if (it.artistId) L.push({ icon: "user", label: Tr.t("player.page.goToArtist"), cb: function() { openArtist(it.artistId, it.sub) } })
            if (v === LibraryModel.PlaylistTracks) L.push({ icon: "list-x", label: Tr.t("player.removeFromPlaylist"), danger: true, cb: function() { removeFromPlaylist(row) } })
            break
        case LibraryModel.Folders:
            if (it.isDir) queueItems("folder_id"); else queueItems("track_id")
            break
        case LibraryModel.Albums: case LibraryModel.NewMusic:
            queueItems("album_id"); fav(it.favUrl, "playlist")
            if (it.artistId) L.push({ icon: "user", label: Tr.t("player.page.goToArtist"), cb: function() { openArtist(it.artistId, it.sub) } })
            break
        case LibraryModel.Artists: case LibraryModel.Composers:
            queueItems("artist_id"); fav(it.favUrl, "playlist"); break
        case LibraryModel.Genres: queueItems("genre_id"); fav(it.favUrl, "playlist"); break
        case LibraryModel.Years: queueItems("year"); fav(it.favUrl, "playlist"); break
        case LibraryModel.Playlists:
            queueItems("playlist_id"); fav(it.favUrl, "playlist")
            L.push({ icon: "pencil", label: Tr.t("player.rename"), cb: function() { renamePlaylist(it) } })
            L.push({ icon: "trash-2", label: Tr.t("player.delete"), danger: true, cb: function() { deletePlaylist(it) } })
            break
        case LibraryModel.Search:
            if (it.kind === 0) queueItems("artist_id"); else if (it.kind === 1) queueItems("album_id"); else queueItems("track_id")
            break
        case LibraryModel.PluginItems:
            if (cur.p1 === "favorites") return favoriteMenu(it, row)
            // musica vera: un brano o una stazione (isAudio), un contenitore
            // che Lyrion marca "playlist" (album, playlist), o una voce a cui
            // ha attaccato un favorites_url. I nodi di navigazione e la
            // ricerca non hanno niente di tutto questo e restano come erano.
            if (!it.hasInput && (it.isAudio || it.ptype === "playlist" || it.favUrl)) pluginQueueItems(L, cur.p1, it.id)
            fav(it.favUrl, it.isAudio ? "audio" : "playlist")
            break
        case LibraryModel.MenuHome: case LibraryModel.Menu:
            // i menu Jive portano le proprie azioni: `add` accoda, `add-hold`
            // fa suonare dopo
            if (it.addact && it.addact.length) L.push({ icon: "list-plus", label: Tr.t("player.addToQueue"), cb: function() { Player.cmd(it.addact) } })
            if (it.addhold && it.addhold.length) L.push({ icon: "list-start", label: Tr.t("player.playNext"), cb: function() { Player.cmd(it.addhold) } })
            // una voce che si suona e non si apre e' un brano o una stazione
            fav(it.favUrl, (it.play && it.play.length && !(it.go && it.go.length)) ? "audio" : "playlist")
            break
        }
        return L
    }

    function menuItemTap(it) {
        if (it.hasInput && it.go && it.go.length) {
            msearchOpen = true; msearch.text = ""
            msearchTitle = it.text || Tr.t("player.titles.search")
            msearchGo = it.go; msearchPlugin = null
            msearch.takeFocus()
        } else if (it.go && it.go.length) goView(LibraryModel.Menu, it.text, it.go)
        else if (it.play && it.play.length) Player.cmd(it.play)
        else if (it.doact && it.doact.length) Player.cmd(it.doact)
    }
    function submitMsearch() {
        if (!msearchOpen || !msearch.text) return
        if (msearchPlugin) {                       // ricerca dentro un plugin (Radio/App)
            var sameP = cur.view === LibraryModel.PluginItems && cur.p1 === msearchPlugin.cmd && cur.p2 === msearchPlugin.item
            goView(LibraryModel.PluginItems, msearchTitle, msearchPlugin.cmd, msearchPlugin.item, msearch.text, sameP)
            msearchOpen = true
            return
        }
        var same = cur.view === LibraryModel.Menu && JSON.stringify(cur.p1) === JSON.stringify(msearchGo)
        goView(LibraryModel.Menu, msearchTitle, msearchGo, "", msearch.text, same)
        msearchOpen = true
    }
    function rowTap(row, onPlay) {
        if (Library.state !== 2) return
        var it = Library.get(row)
        switch (view) {
        case LibraryModel.Artists: case LibraryModel.Composers: if (onPlay) playItem("artist_id", it.id, "load"); else openArtist(it.id, it.text); break
        case LibraryModel.Albums: case LibraryModel.NewMusic: if (onPlay) playItem("album_id", it.id, "load"); else openAlbum(it.id, it.text); break
        case LibraryModel.Genres: if (onPlay) playItem("genre_id", it.id, "load"); else goView(LibraryModel.Albums, it.text, "", "genre_id:" + it.id); break
        case LibraryModel.Years: if (onPlay) playItem("year", it.id, "load"); else goView(LibraryModel.Albums, it.text, "", "year:" + it.id); break
        case LibraryModel.Search:
            if (it.kind === 0) { if (onPlay) playItem("artist_id", it.id, "load"); else openArtist(it.id, it.text) }
            else if (it.kind === 1) { if (onPlay) playItem("album_id", it.id, "load"); else openAlbum(it.id, it.text) }
            else playItem("track_id", it.id, "load")
            break
        case LibraryModel.Tracks: case LibraryModel.PlaylistTracks: playItem("track_id", it.id, "load"); break
        case LibraryModel.Playlists: if (onPlay) playItem("playlist_id", it.id, "load"); else goView(LibraryModel.PlaylistTracks, it.text, it.id); break
        case LibraryModel.Folders:
            if (onPlay) playItem(it.isDir ? "folder_id" : "track_id", it.id, "load")
            else if (it.isDir) goView(LibraryModel.Folders, it.text, it.id)
            else playItem("track_id", it.id, "load")
            break
        case LibraryModel.Radios: case LibraryModel.Apps: goView(LibraryModel.PluginItems, it.text, it.id); break
        case LibraryModel.MenuHome: case LibraryModel.Menu:
            if (onPlay && it.play && it.play.length) Player.cmd(it.play); else menuItemTap(it); break
        case LibraryModel.PluginItems: {
            var cmd = cur.p1
            if (!onPlay && it.hasInput) {          // nodo di ricerca del plugin: si chiede il testo
                msearchOpen = true; msearch.text = ""
                msearchTitle = it.text || Tr.t("player.titles.search")
                msearchGo = []; msearchPlugin = { cmd: cmd, item: it.id }
                msearch.takeFocus()
            }
            else if (!onPlay && it.hasItems) goView(LibraryModel.PluginItems, it.text, cmd, it.id)
            else if (it.isAudio || onPlay) Player.cmd([cmd, "playlist", "play", "item_id:" + it.id])
            break
        }
        }
    }

    // il contenuto compare in dissolvenza (0,12 s) a ogni cambio
    function appear() { fadeAnim.restart() }
    NumberAnimation { id: fadeAnim; target: content; property: "opacity"; from: 0; to: 1; duration: 120; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut }
    Connections { target: Library; function onLoaded() { root.appear() } }

    // ─── barra dei tab ─────────────────────────────────────────────────────
    Rectangle {
        id: tabBar
        width: parent.width; height: 40; color: Theme.panelA(0.5)
        Rectangle { y: 39; width: parent.width; height: 1; color: Theme.border }
        // the power button and the Osmium Sound mark, top right. The "update
        // available" badge makes room for them: the full words, the short
        // one, or just a gold dot on the gear. The words go when the tabs
        // need their space; the power button always stays.
        Item {
            id: brandMark
            width: 34 + brandText.implicitWidth + 16; height: 40
            x: parent.width - width
            visible: tabRow.width <= x
            Text {
                id: brandText
                x: 34; anchors.verticalCenter: parent.verticalCenter
                text: "OSMIUM SOUND"; color: Theme.silverA(0.8)
                font.family: Theme.font; font.pixelSize: 11; font.bold: true; font.letterSpacing: 2
            }
        }
        Item {
            id: powerBtn
            width: 40; height: 40
            x: brandMark.visible ? brandMark.x : parent.width - width
            Icon {
                anchors.centerIn: parent; name: "power"; size: 16
                color: powerTap.mix(Theme.gold, Theme.white)
                scale: powerTap.tapScale
            }
            Tap {
                id: powerTap; tap: 0.9
                onClicked: Ui.dialogs.power(function(act) {
                    if (!act) return
                    Api.post(Api.apiBase + "/" + act, {}, function() {}, 12000)
                    Ui.toast.say(act === "reboot" ? "rotate-cw" : "power",
                                 Tr.t(act === "reboot" ? "settings.msg.rebooting" : "settings.msg.shuttingDown"))
                })
            }
        }
        // the tabs as they are without the badge, measured apart so the
        // badge's length can depend on them without a binding loop
        Row {
            id: tabMeasure
            visible: false
            Repeater {
                model: root.tabs
                Item {
                    required property var modelData
                    width: 46 + (modelData.key ? 6 + mText.implicitWidth : 0); height: 1
                    Text { id: mText; text: modelData.key ? Tr.t(modelData.key) : ""; font.family: Theme.font; font.pixelSize: 12 }
                }
            }
        }
        TextMetrics { id: updFull; font.family: Theme.font; font.pixelSize: 12; font.bold: true; text: Tr.t("settings.updates.available") }
        TextMetrics { id: updShortM; font.family: Theme.font; font.pixelSize: 12; font.bold: true; text: Tr.t("settings.updates.availableShort") }
        // 0 full words, 1 short word, 2 dot only
        readonly property int updMode: tabMeasure.width + 6 + updFull.advanceWidth <= brandMark.x ? 0
                                     : tabMeasure.width + 6 + updShortM.advanceWidth <= brandMark.x ? 1 : 2
        Row {
            id: tabRow
            Repeater {
                model: root.tabs
                Item {
                    id: tabItem
                    required property var modelData
                    required property int index
                    readonly property bool active: root.tab === index
                    readonly property string label: modelData.key ? Tr.t(modelData.key) : ""
                    readonly property bool badge: modelData.icon === "settings" && root.updateAvailable
                    width: 46 + (label ? 6 + tabText.implicitWidth : 0) + (badge && updText.visible ? 6 + updText.implicitWidth : 0); height: 40
                    readonly property color c: active ? Theme.white : tabTap.mix(Theme.silverA(0.5), Theme.white)
                    Icon { x: 16; anchors.verticalCenter: parent.verticalCenter; name: tabItem.modelData.icon; size: 14; color: tabItem.c }
                    Rectangle { visible: tabItem.badge && tabBar.updMode === 2; x: 26; y: 10; width: 7; height: 7; radius: 3.5; color: Theme.gold; border.width: 1; border.color: Theme.panel }
                    Text { id: tabText; x: 36; anchors.verticalCenter: parent.verticalCenter; text: tabItem.label; color: tabItem.c; font.family: Theme.font; font.pixelSize: 12 }
                    Text {
                        id: updText
                        visible: tabItem.badge && tabBar.updMode < 2
                        x: 36 + (tabItem.label ? tabText.implicitWidth + 6 : 0)
                        anchors.verticalCenter: parent.verticalCenter
                        text: Tr.t(tabBar.updMode === 1 ? "settings.updates.availableShort" : "settings.updates.available"); color: Theme.gold
                        font.family: Theme.font; font.pixelSize: 12; font.bold: true
                    }
                    // rounded-t-sm: 2 px solo sui due angoli in alto
                    Rectangle { visible: tabItem.active; x: 8; y: 38; width: parent.width - 16; height: 2; topLeftRadius: 2; topRightRadius: 2; color: Theme.gold }
                    Tap { id: tabTap; onClicked: root.openTab(tabItem.index) }
                }
            }
        }
    }

    // ─── briciole ──────────────────────────────────────────────────────────
    Rectangle {
        y: 40; width: parent.width; height: 43; color: Theme.panelA(0.4)
        visible: root.hasCrumbs
        Rectangle { y: 42; width: parent.width; height: 1; color: Theme.borderA(0.5) }
        Item {
            x: 12; y: 8; width: 27; height: 27
            Icon { anchors.centerIn: parent; name: "home"; size: 15; color: Theme.silverA(0.6) }
            Tap { onClicked: root.navHome() }
        }
        Row {
            x: 43; height: parent.height
            visible: root.nav.length > 1
            Repeater {
                model: root.nav.length
                Item {
                    id: crumb
                    required property int index
                    readonly property bool last: index === root.nav.length - 1
                    width: (index > 0 ? 14 : 0) + Math.min(100, crumbText.implicitWidth) + 4; height: 43
                    Icon { visible: crumb.index > 0; x: 14 - 9 - 5.5; anchors.verticalCenter: parent.verticalCenter; name: "chevron-right"; size: 11; color: Theme.silverA(0.3) }
                    Text {
                        id: crumbText
                        x: crumb.index > 0 ? 14 : 0; anchors.verticalCenter: parent.verticalCenter
                        width: Math.min(100, implicitWidth); elide: Text.ElideRight
                        text: root.nav[crumb.index].title
                        color: crumb.last ? Theme.white : Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 12
                    }
                    Tap { enabled: !crumb.last; onClicked: root.navToCrumb(crumb.index) }
                }
            }
        }
        Rectangle {                                     // "Indietro"
            visible: root.nav.length > 1
            x: parent.width - 12 - width; y: 21.5 - 11; width: backText.implicitWidth + 24; height: 22; radius: 8
            color: backTap.mix(Theme.wa(0.05), Theme.wa(0.1))
            Text { id: backText; anchors.centerIn: parent; text: Tr.t("common.back"); color: Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 12 }
            Tap { id: backTap; onClicked: root.navBack() }
        }
    }

    // ─── contenuto ─────────────────────────────────────────────────────────
    Item {
        id: content
        y: root.contentTop; width: parent.width; height: 600 - y
        clip: true
        SettingsTab { id: settingsTab; anchors.fill: parent; visible: root.tab === 4; devScale: root.devScale }
        DiscoverTab { id: discoverTab; anchors.fill: parent; visible: root.tab === 3; devScale: root.devScale }

        Item {
            id: libArea
            anchors.fill: parent
            visible: root.tab !== 4 && root.tab !== 3

            // non ancora collegati a Lyrion (LyrionServer.jsx:1267)
            Column {
                id: connCol
                anchors.centerIn: parent; spacing: 16
                visible: !Player.connected
                // 🚨 col server spento l'attesa non finisce mai: passato questo
                // tempo la rotellina si ferma, se no la scena si ridisegna a ogni
                // vsync all'infinito (il costo misurato sta in Spinner.qml)
                property bool waiting: true
                Timer { interval: 10000; running: connCol.visible && connCol.waiting; onTriggered: connCol.waiting = false }
                Connections { target: Player; function onConnectedChanged() { if (Player.connected) connCol.waiting = true } }
                Spinner { anchors.horizontalCenter: parent.horizontalCenter; radius: 24; visible: connCol.waiting; active: connCol.waiting && !Player.connected && root.visible && !(Ui.app && Ui.app.expanded) }
                Text { anchors.horizontalCenter: parent.horizontalCenter; text: Tr.t(connCol.waiting ? "player.connecting" : "player.connectError"); color: Theme.silver; font.family: Theme.font; font.pixelSize: 14 }
            }

            // fascia "CD rilevato" in cima alla scheda Musica
            CdBanner { id: cdBanner; visible: root.tab === 0 && Ui.cdrip && Ui.cdrip.bannerVisible; width: parent.width }
            // la home: ricerca in tutta la libreria, poi le tessere
            Item {
                anchors.fill: parent
                anchors.topMargin: cdBanner.visible ? 48 : 0
                visible: root.view === LibraryModel.Home && Player.connected
                TextField_ {
                    id: homeSearch
                    x: 12; y: 12; width: parent.width - 24 - 8 - 38; height: 38
                    textSize: 14; padding: 16; restBorder: Theme.accent
                    placeholder: Tr.t("player.librarySearchPlaceholder")
                    acceptOnVkConfirm: true
                    onAccepted: root.submitLibrarySearch(homeSearch.text)
                }
                Rectangle {
                    x: parent.width - 12 - 38; y: 12; width: 38; height: 38; radius: 10
                    color: homeSearch.text.trim().length >= 2 ? Theme.goldA(0.2) : Theme.goldA(0.08)
                    Icon { anchors.centerIn: parent; name: "search"; size: 16; color: homeSearch.text.trim().length >= 2 ? Theme.gold : Theme.goldA(0.4) }
                    Tap { onClicked: root.submitLibrarySearch(homeSearch.text) }
                }
                Repeater {
                    model: root.tiles
                    Rectangle {
                        required property var modelData
                        required property int index
                        readonly property real tw: (root.width - 32 - 24) / 3
                        // py-7 (28) + icona 30 + mb-2.5 (10) + riga text-sm (20) + py-7 (28)
                        // + 2 di bordo = 117: misurato 140 px a 720p in Electron (113 era 4 in meno)
                        x: 16 + (index % 3) * (tw + 12); y: 62 + Math.floor(index / 3) * (117 + 12)
                        width: tw; height: 117; radius: 12
                        color: tileTap.mix(Theme.surface, Theme.light); border.width: 1; border.color: Theme.border
                        Icon { anchors.horizontalCenter: parent.horizontalCenter; y: 29; name: modelData.icon; size: 30; color: Theme.silver }
                        Text { anchors.horizontalCenter: parent.horizontalCenter; y: 69; height: 20; verticalAlignment: Text.AlignVCenter; text: Tr.t(modelData.key); color: Theme.white; font.family: Theme.font; font.pixelSize: 14 }
                        Tap {
                            id: tileTap
                            onClicked: {
                                if (modelData.view === LibraryModel.PluginItems) root.goView(LibraryModel.PluginItems, Tr.t(modelData.key), "favorites")
                                else root.goView(modelData.view, Tr.t(modelData.key))
                            }
                        }
                    }
                }
            }

            // il resto: barre di ricerca + lista + indice A-Z
            Item {
                anchors.fill: parent
                anchors.topMargin: cdBanner.visible ? 48 : 0
                visible: root.view !== LibraryModel.Home && Player.connected
                property real y0: 0
                // ricerca dei menu Jive (Cerca…)
                Rectangle {
                    id: msearchRow
                    visible: root.msearchOpen
                    width: parent.width; height: 47; color: Theme.panelA(0.4)
                    Rectangle { y: 46; width: parent.width; height: 1; color: Theme.borderA(0.5) }
                    Icon { x: 12; anchors.verticalCenter: parent.verticalCenter; name: "search"; size: 15; color: Theme.silverA(0.5) }
                    TextField_ {
                        id: msearch
                        x: 35; y: 8; width: parent.width - 35 - 8 - 29 - 8 - 29 - 12; height: 31
                        textSize: 14; padding: 12
                        placeholder: root.msearchTitle || Tr.t("player.searchPlaceholder")
                        acceptOnVkConfirm: true
                        onAccepted: root.submitMsearch()
                    }
                    Rectangle {
                        x: parent.width - 12 - 29 - 8 - 29; y: 9; width: 29; height: 29; radius: 8
                        color: msearch.text ? Theme.goldA(0.2) : Theme.goldA(0.08)
                        Icon { anchors.centerIn: parent; name: "search"; size: 15; color: msearch.text ? Theme.gold : Theme.goldA(0.4) }
                        Tap { onClicked: root.submitMsearch() }
                    }
                    Item {
                        x: parent.width - 12 - 29; y: 9; width: 29; height: 29
                        Icon { anchors.centerIn: parent; name: "x"; size: 15; color: Theme.silverA(0.6) }
                        Tap { onClicked: root.msearchOpen = false }
                    }
                }
                // filtro artisti/album
                Item {
                    id: searchRow
                    visible: root.hasSearch
                    y: root.msearchOpen ? 47 : 0; width: parent.width; height: 50
                    TextField_ {
                        id: search
                        x: 12; y: 6; width: parent.width - 24; height: 38
                        textSize: 14; padding: 16; restBorder: Theme.accent
                        placeholder: Tr.t(root.view === LibraryModel.Albums ? "player.filterAlbumsPlaceholder" : "player.filterArtistsPlaceholder")
                        onTextEdited: debounce.restart()
                        Timer { id: debounce; interval: 200; onTriggered: Library.filter = search.text }
                        Item {
                            visible: search.text !== ""
                            x: parent.width - 30; y: 7; width: 24; height: 24
                            Icon { anchors.centerIn: parent; name: "x"; size: 14; color: xTap.pressed ? Theme.white : Theme.silverA(0.5) }   // active:text-white
                            Tap { id: xTap; grow: 6; onClicked: { search.text = ""; Library.filter = "" } }
                        }
                    }
                }
                readonly property real listY: (root.msearchOpen ? 47 : 0) + (root.hasSearch ? 50 : 0)
                // the album or artist page, in place of the list
                Loader {
                    id: pageLoader
                    anchors.fill: parent
                    visible: root.isPage
                }
                Component {
                    id: albumPageComp
                    AlbumPage { browser: root; albumId: String(root.cur.p1); devScale: root.devScale }
                }
                Component {
                    id: artistPageComp
                    ArtistPage {
                        browser: root; devScale: root.devScale
                        artistId: String(root.cur.p1 || "")
                        mbid: String(root.cur.p2 || "").indexOf("mbid:") === 0 ? String(root.cur.p2).substring(5) : ""
                        name: root.cur.title === "…" ? "" : root.cur.title
                    }
                }
                LibraryList {
                    id: list
                    x: 12; y: parent.listY + 4
                    width: (root.hasAz ? root.width - 32 - 12 : root.width - 12) - 12
                    height: 600 - root.contentTop - y - 12
                    visible: Library.state === 2 && Library.count > 0 && !root.isPage
                    onRowTap: (row, onPlay) => root.rowTap(row, onPlay)
                    // list.y gia' comprende le barre di ricerca; la fascia del CD sposta tutto il contenitore
                    onRowLongPress: (row, x, y) => ctx.open(root.ctxItems(row), list.x + x, list.y + y + (cdBanner.visible ? 48 : 0))
                }
                Spinner { visible: Library.state === 1 && !root.isPage; active: visible && root.visible && !(Ui.app && Ui.app.expanded); radius: 20; x: list.x + list.width / 2 - 20; y: list.y + 60 - 20 }   // w-10 h-10
                Column {
                    visible: Library.state === 3 && !root.isPage
                    x: list.x; y: list.y + 40; width: list.width; spacing: 12
                    Icon { anchors.horizontalCenter: parent.horizontalCenter; name: "alert-circle"; size: 40; color: Theme.red400 }
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: Tr.t("player.connectionErrorTitle"); color: Theme.white; font.family: Theme.font; font.pixelSize: 16; font.bold: true }
                }
                Text {
                    visible: Library.state === 2 && Library.count === 0 && !root.isPage
                    x: list.x; y: list.y + 32; width: list.width; horizontalAlignment: Text.AlignHCenter
                    text: Tr.t("common.noResults"); color: Theme.silverA(0.4); font.family: Theme.font; font.pixelSize: 14
                }
                // indice A-Z (w-8)
                AzIndex {
                    visible: root.hasAz
                    x: root.width - 32; y: parent.listY; width: 32; height: 600 - root.contentTop - y
                    onLetter: (l) => { var r = Library.letterFirst(l); if (r >= 0) list.scrollToRow(r) }
                }
            }
        }
        ContextMenu { id: ctx }
    }
}
