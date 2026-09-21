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
    readonly property bool azShown: hasAz && !list.coverflow      // Cover Flow has its own slider
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
    x: 341; width: parent ? parent.width - 341 : 683; height: parent ? parent.height : 600

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
        { icon: "heart", key: "player.titles.favorites", view: LibraryModel.PluginItems },
        { icon: "user", key: "player.titles.artists", view: LibraryModel.Artists },
        { icon: "disc", key: "player.titles.albums", view: LibraryModel.Albums },
        { icon: "tag", key: "player.titles.genres", view: LibraryModel.Genres },
        { icon: "calendar", key: "player.titles.years", view: LibraryModel.Years },
        { icon: "piano", key: "player.titles.composers", view: LibraryModel.Composers },
        { icon: "sparkles", key: "player.titles.newMusic", view: LibraryModel.NewMusic },
        { icon: "folder", key: "player.titles.folders", view: LibraryModel.Folders },
        { icon: "list-music", key: "player.titles.playlists", view: LibraryModel.Playlists }]

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
        navDir = 1
        search.text = ""; Library.filter = ""
        ctx.close()
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
        navDir = -1
        msearchOpen = false; ctx.close(); search.text = ""
        pageLoader.sourceComponent = null
        appear()
    }
    function navBack() {
        if (nav.length <= 1) return
        var n = nav.slice(); n.pop(); nav = n
        navDir = -1
        msearchOpen = false; search.text = ""; ctx.close()
        loadTop(); appear()
    }
    function navToCrumb(i) {
        if (i >= nav.length - 1) return
        nav = nav.slice(0, i + 1)
        navDir = -1
        msearchOpen = false; search.text = ""; ctx.close()
        loadTop(); appear()
    }
    function openTab(i) {
        navDir = i > tab ? 1 : i < tab ? -1 : 0
        tab = i; ctx.close()
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
    function showMusicTab() { if (tab !== 0) { navDir = -1; tab = 0; ctx.close() } }
    function openAlbum(id, title) { if (!id) return; showMusicTab(); goView(LibraryModel.AlbumPage, title, String(id)) }
    function openArtist(id, name) { if (!id) return; showMusicTab(); goView(LibraryModel.ArtistPage, name, String(id)) }
    function openPerson(mbid, name) { if (!mbid) return; showMusicTab(); goView(LibraryModel.ArtistPage, name, "", "mbid:" + mbid) }
    function openMenu(items, x, y) { ctx.open(items, x, y) }
    function closeMenu() { ctx.close() }
    // The guided tour: the album list (grid or Cover Flow), and the menu a
    // long press opens, on the first album, so it can be seen. Rectangles
    // in canvas coordinates (this panel starts at x 341, its content at
    // contentTop), null when there is nothing to light up yet.
    function tutorialAlbums(mode) {
        showMusicTab(); closeMenu()
        if (view !== LibraryModel.Albums) { navHome(); goView(LibraryModel.Albums, Tr.t("player.titles.albums")) }
    }
    function tutorialListRect() {
        var top = (cdBanner.visible ? 48 : 0)
        return [x + list.x, contentTop + top + list.y, list.width, list.height]
    }
    function tutorialMenuRect() {
        if (view !== LibraryModel.Albums || Library.state !== 2 || Library.count < 1 || list.coverflow) return null
        var cw = list.cardW, top = (cdBanner.visible ? 48 : 0)
        ctx.open(ctxItems(0), list.x + cw / 2, list.y + cw / 2 + top)
        if (!ctx.visible) return null
        // the card and its menu together
        var x0 = Math.min(list.x, ctx.boxX), y0 = Math.min(list.y + top, ctx.boxY)
        var x1 = Math.max(list.x + cw, ctx.boxX + ctx.boxW), y1 = Math.max(list.y + top + cw + 48, ctx.boxY + ctx.boxH)
        return [x + x0 - 6, contentTop + y0 - 6, x1 - x0 + 12, y1 - y0 + 12]
    }
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

    // The content fades in and slides 12 points the way one is going: from
    // the right going in, from the left coming back.
    // (not while the Cover Flow's cover flies to the album page: the page
    // must come up under it without the whole panel blinking)
    property bool quietNav: false
    property int navDir: 0
    function appear() {
        if (quietNav) { quietNav = false; return }
        slideAnim.stop()
        pane.opacity = 0
        pane.x = Theme.lushMotion ? navDir * 12 : 0
        navDir = 0
        // 🚨 Not in this frame: this is the one where the new page is built,
        // and a page never shown before (Settings: 23 cards with a shadow and
        // an icon each) can cost several. Starting together, the animation is
        // already half way through at its first step and one sees it snap.
        // One turn of FrameAnimation waits for the frame to be drawn, and the
        // movement starts after it.
        paintGate.restart()
    }
    // the gate: it fires on a drawn frame, not at the end of the event loop
    // (Qt.callLater would still be inside the same frame)
    FrameAnimation {
        id: paintGate
        running: false
        onTriggered: { stop(); slideAnim.start() }
    }
    ParallelAnimation {
        id: slideAnim
        NumberAnimation { target: pane; property: "opacity"; to: 1; duration: Theme.dur(160); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut }
        NumberAnimation { target: pane; property: "x"; to: 0; duration: Theme.dur(180); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut }
    }
    // 🚨 appear() comes twice, once on the navigation and once when the data
    // lands: with the fade alone it did not show, with the slide it would be a
    // jolt. The second is dropped while the first is still running.
    Connections { target: Library; function onLoaded() { if (!slideAnim.running && !paintGate.running) root.appear() } }

    // ─── barra dei tab ─────────────────────────────────────────────────────
    Rectangle {
        id: tabBar
        width: parent.width; height: 40; color: Theme.panelA(0.5)
        Rectangle { y: 39; width: parent.width; height: 1; color: Theme.border }
        // the Osmium Sound mark and, in the corner, the power button. The
        // "update available" badge makes room for them: the full words, the
        // short one, or just a gold dot on the gear. The words go when the
        // tabs need their space; the power button always stays.
        Item {
            id: brandMark
            width: 16 + brandText.width + 4; height: 40
            x: netIcon.x - width
            visible: tabRow.width <= x
            Row {
                id: brandText
                x: 16; anchors.verticalCenter: parent.verticalCenter
                spacing: 6
                // two-tone like the status plate: SOUND in gold
                Text { text: "OSMIUM"; color: Theme.silverA(0.8); font.family: Theme.font; font.pixelSize: 11; font.bold: true; font.letterSpacing: 2 }
                Text { text: "SOUND"; color: Theme.gold; font.family: Theme.font; font.pixelSize: 11; font.bold: true; font.letterSpacing: 2 }
            }
        }
        // the connection, as an OS's tray shows it: the link's shape (Wi-Fi
        // or cable) when the internet answers, the same with a gold dot when
        // only the home network does, the "off" shape when nothing does. A
        // touch says it in words. Hidden until the service has answered once.
        Item {
            id: netIcon
            readonly property string st: Player.netState
            readonly property bool wifi: Player.netType === "wireless"
            readonly property bool off: st === "offline"
            readonly property string icon: off ? (wifi ? "wifi-off" : "unplug") : (wifi ? "wifi" : "network")
            visible: st !== "unknown"
            width: visible ? 32 : 0; height: 40
            x: powerBtn.x - width
            Icon {
                anchors.centerIn: parent; name: netIcon.icon; size: 16
                color: netTap.mix(netIcon.off ? Theme.red400 : Theme.silverA(0.6), Theme.white)
                scale: netTap.tapScale
            }
            Rectangle { visible: netIcon.st === "lan"; x: 19; y: 21; width: 7; height: 7; radius: 3.5; color: Theme.gold; border.width: 1; border.color: Theme.panel }
            Tap {
                id: netTap; tap: 0.9
                onClicked: {
                    var k = netIcon.off ? "offline" : netIcon.st + (netIcon.wifi ? "Wifi" : "Wired")
                    Ui.toast.say(netIcon.icon, Tr.tf("connectivity." + k, "ssid", Player.netSsid))
                }
            }
        }
        Item {
            id: powerBtn
            width: 40; height: 40
            x: parent.width - width - 4
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
        // The underline, one for the whole bar. Outside the Row: inside, the
        // positioner would lay it out in line with the tabs.
        property real uX: 8
        property real uW: 0
        property bool uPrimed: false
        function uGo() {
            // on the first frame the text widths can still be 0: it arms
            // itself on a real measurement, or the bar flies in from x=0
            if (!uPrimed) { uxS.set(uX); uwS.set(uW); uPrimed = uW > 0 }
            else { uxS.to = uX; uwS.to = uW }
        }
        // 🚨 Qt.callLater and not a direct call: uX and uW arrive from TWO
        // separate Bindings, and setting off on the first write the spring
        // aims for one frame at the new position with the old width. Between
        // the labelled tabs the widths are alike and it does not show; going
        // to Settings, the one that is an icon alone, it snapped. callLater
        // folds the two writes into a single update.
        onUXChanged: Qt.callLater(uGo)
        onUWChanged: Qt.callLater(uGo)
        Spring { id: uxS; stiffness: 220; damping: 26; rate: Theme.motionRate }
        Spring { id: uwS; stiffness: 220; damping: 26; rate: Theme.motionRate }
        Rectangle {
            visible: uwS.value > 1
            x: tabRow.x + uxS.value; y: 38; width: Math.max(0, uwS.value); height: 2
            topLeftRadius: 2; topRightRadius: 2; color: Theme.gold      // rounded-t-sm
        }
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
                    // 🚨 the underline no longer lives here: there is one,
                    // in tabBar, and it slides from tab to tab. The delegate
                    // only says where the active one is, and it writes
                    // UPWARD: nothing in the chain that decides the tabs'
                    // widths reads uX/uW, so there is no loop.
                    Binding { target: tabBar; property: "uX"; value: tabItem.x + 8;      when: tabItem.active; restoreMode: Binding.RestoreNone }
                    Binding { target: tabBar; property: "uW"; value: tabItem.width - 16; when: tabItem.active; restoreMode: Binding.RestoreNone }
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
            id: backBtn
            visible: root.nav.length > 1
            x: parent.width - 12 - width; y: 21.5 - 11; width: backText.implicitWidth + 24; height: 22; radius: 8
            color: backTap.mix(Theme.wa(0.05), Theme.wa(0.1))
            Text { id: backText; anchors.centerIn: parent; text: Tr.t("common.back"); color: Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 12 }
            Tap { id: backTap; onClicked: root.navBack() }
        }
        // the albums as a grid or as Cover Flow (also in Settings → Library)
        Rectangle {
            visible: list.grid && !root.isPage
            readonly property bool flow: list.coverflow
            x: (backBtn.visible ? backBtn.x : parent.width - 12) - 8 - width; y: 21.5 - 11; width: 22 + 8 + viewText.implicitWidth + 12; height: 22; radius: 8
            color: viewTap.mix(flow ? Theme.goldA(0.15) : Theme.wa(0.05), Theme.wa(0.12))
            Icon { x: 8; anchors.verticalCenter: parent.verticalCenter; name: parent.flow ? "layout-grid" : "gallery-horizontal"; size: 13; color: parent.flow ? Theme.gold : Theme.silverA(0.7) }
            Text { id: viewText; x: 8 + 13 + 6; anchors.verticalCenter: parent.verticalCenter; text: Tr.t(parent.flow ? "player.view.grid" : "player.view.coverflow"); color: parent.flow ? Theme.gold : Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 12 }
            Tap { id: viewTap; onClicked: Ui.app.setAlbumView(parent.flow ? "grid" : "coverflow") }
        }
    }

    // ─── contenuto ─────────────────────────────────────────────────────────
    Item {
        id: content
        y: root.contentTop; width: parent.width; height: root.height - y
        clip: true
        // 🚨 The long-press menu stays OUTSIDE this box: the page slides,
        // not the menu standing over it.
        Item {
            id: pane
            anchors.fill: parent
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
                            // + 2 di bordo = 117: misurato 140 px a 720p in Electron (113 era 4 in meno).
                            // A taller canvas (16:10: 640) shares its extra height among the rows.
                            readonly property real th: 117 + Math.max(0, root.height - 600) / 3
                            x: 16 + (index % 3) * (tw + 12); y: 62 + Math.floor(index / 3) * (th + 12)
                            width: tw; height: th; radius: 12
                            color: tileTap.mix(Theme.surface, Theme.light); border.width: 1; border.color: Theme.border
                            Icon { anchors.horizontalCenter: parent.horizontalCenter; y: 29 + (th - 117) / 2; name: modelData.icon; size: 30; color: Theme.silver }
                            Text { anchors.horizontalCenter: parent.horizontalCenter; y: 69 + (th - 117) / 2; height: 20; verticalAlignment: Text.AlignVCenter; text: Tr.t(modelData.key); color: Theme.white; font.family: Theme.font; font.pixelSize: 14 }
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
                                Icon { anchors.centerIn: parent; name: "x"; size: 14; color: xTap.mix(Theme.silverA(0.5), Theme.white) }   // active:text-white
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
                        width: (root.azShown ? root.width - 32 - 12 : root.width - 12) - 12
                        height: root.height - root.contentTop - y - 12
                        visible: Library.state === 2 && Library.count > 0 && !root.isPage
                        onRowTap: (row, onPlay) => root.rowTap(row, onPlay)
                        // list.y gia' comprende le barre di ricerca; la fascia del CD sposta tutto il contenitore
                        onRowLongPress: (row, x, y) => ctx.open(root.ctxItems(row), list.x + x, list.y + y + (cdBanner.visible ? 48 : 0))
                        onExpandAlbum: (row, x, y, size, src) => hero.fly(row, list.x + x, list.y + y, size, src)
                    }
                    // The album that opens from Cover Flow: a copy of its cover
                    // swells over the row, then settles where the page keeps its
                    // own, and stays on top until that one has loaded.
                    Item {
                        id: hero
                        visible: false
                        z: 50
                        property int row: -1
                        property real radiusV: 0
                        property bool settled: false
                        readonly property real bigS: Math.min(parent.width, parent.height) * 0.84
                        readonly property bool landed: settled && root.isPage && !!root.pageItem && !!root.pageItem.coverReady
                        onLandedChanged: if (landed) fadeOut.restart()
                        function fly(r, x0, y0, s0, src) {
                            swell.stop(); fadeOut.stop()
                            row = r; heroImg.source = src
                            x = x0; y = y0; width = s0; height = s0; radiusV = 0; opacity = 1; settled = false
                            visible = true
                            giveUp.restart(); swell.restart()
                        }
                        // 🚨 not a Cover: its sourceSize follows the width, and an
                        // item that grows every frame would reload the picture every
                        // frame and never show it. Fixed textures, scaled by the GPU.
                        Image {
                            id: heroImg
                            anchors.fill: parent; visible: false
                            readonly property int px: Theme.coverPx(200)
                            asynchronous: true; cache: true; smooth: true
                            fillMode: Image.PreserveAspectCrop
                            sourceSize.width: px; sourceSize.height: px
                            layer.enabled: true; layer.smooth: true
                            layer.textureSize: Qt.size(px, px)
                        }
                        Rectangle {
                            id: heroMask
                            anchors.fill: parent; visible: false
                            radius: hero.radiusV
                            layer.enabled: true; layer.smooth: true
                            layer.textureSize: Qt.size(512, 512)
                        }
                        ShaderImage { anchors.fill: parent; source: heroImg; mask: heroMask; visible: heroImg.status === Image.Ready }
                        DiagonalFallback { anchors.fill: parent; radius: hero.radiusV; visible: heroImg.status !== Image.Ready
                                           Icon { anchors.centerIn: parent; name: "disc"; size: 40; color: Theme.silverA(0.2) } }
                        SequentialAnimation {
                            id: swell
                            ParallelAnimation {
                                NumberAnimation { target: hero; property: "x"; to: (hero.parent.width - hero.bigS) / 2; duration: Theme.dur(480); easing.type: Easing.OutCubic }
                                NumberAnimation { target: hero; property: "y"; to: (hero.parent.height - hero.bigS) / 2; duration: Theme.dur(480); easing.type: Easing.OutCubic }
                                NumberAnimation { target: hero; property: "width"; to: hero.bigS; duration: Theme.dur(480); easing.type: Easing.OutCubic }
                                NumberAnimation { target: hero; property: "height"; to: hero.bigS; duration: Theme.dur(480); easing.type: Easing.OutCubic }
                                NumberAnimation { target: hero; property: "radiusV"; to: 12; duration: Theme.dur(480) }
                            }
                            PauseAnimation { duration: Theme.dur(90) }
                            ScriptAction { script: { root.quietNav = true; root.rowTap(hero.row, false) } }
                            ParallelAnimation {
                                NumberAnimation { target: hero; property: "x"; to: 16; duration: Theme.dur(440); easing.type: Easing.InOutCubic }
                                NumberAnimation { target: hero; property: "y"; to: 16; duration: Theme.dur(440); easing.type: Easing.InOutCubic }
                                NumberAnimation { target: hero; property: "width"; to: 164; duration: Theme.dur(440); easing.type: Easing.InOutCubic }
                                NumberAnimation { target: hero; property: "height"; to: 164; duration: Theme.dur(440); easing.type: Easing.InOutCubic }
                            }
                            ScriptAction { script: hero.settled = true }
                        }
                        // gone once the page shows its own cover, or after a while regardless
                        Timer { id: giveUp; interval: 2500; onTriggered: if (hero.visible) fadeOut.restart() }
                        NumberAnimation { id: fadeOut; target: hero; property: "opacity"; to: 0; duration: Theme.dur(160); onFinished: hero.visible = false }
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
                        visible: root.azShown
                        x: root.width - 32; y: parent.listY; width: 32; height: root.height - root.contentTop - y
                        onLetter: (l) => { var r = Library.letterFirst(l); if (r >= 0) list.scrollToRow(r) }
                    }
                }
            }
        }
        ContextMenu { id: ctx }
    }
}
