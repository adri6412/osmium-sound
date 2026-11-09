// Il pannello di destra: barra dei tab, briciole e contenuto (griglia della
// home oppure le liste della libreria), come draw_right in screen_main.c.
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    property real devScale: 1
    property int tab: 0                       // 0 musica 1 app 2 scopri 3 impostazioni
    // Pseudo-view (not in LibraryModel's C++ enum): the root of the Music tab,
    // the tiles of the music sources (Qobuz/Tidal/Spotify/Radio/Local library).
    // A large number so it never collides with a real LibraryModel.View value.
    readonly property int sourcesRoot: 1000
    property var nav: [{ view: sourcesRoot, title: Tr.t("player.titles.sources"), p1: "", p2: "", input: "" }]
    // where the last long-press menu opened, so a second-level menu (the native
    // plugin context menu) can reopen in the same spot
    property real menuX: 0
    property real menuY: 0
    readonly property var cur: nav[nav.length - 1]
    readonly property int view: cur.view
    readonly property bool hasCrumbs: tab !== 3 && tab !== 2
    readonly property real contentTop: hasCrumbs ? 83 : 40
    readonly property bool hasSearch: tab === 0 && (view === LibraryModel.Artists || view === LibraryModel.Albums || view === LibraryModel.Composers)
    readonly property bool hasAz: hasSearch
    readonly property bool azShown: hasAz && !list.coverflow && !list.changer   // Cover Flow has its own slider, the changer its file
    readonly property bool browsing: tab === 0 && view !== LibraryModel.Home && view !== sourcesRoot
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

    // ─── copertina del CD scaricata dalla rete ──────────────────────────────
    // Il plugin CDplayer non allega la copertina all'album della sua browse; il
    // backend pero' conosce il release MusicBrainz del disco (/api/cd/info) e la
    // scarica da Cover Art Archive (/api/cd/cover). Quando si entra nella vista
    // CDplayer chiediamo l'info e teniamo l'URL, che LibraryList usa per l'album.
    readonly property bool inCdPlayer: view === LibraryModel.PluginItems && String(cur.p1) === "cdplayer"
    // The whole CD section: the CDplayer menu list and the CD album page reached
    // from it (both carry cur.p1 === "cdplayer"). While we are in it we keep an
    // eye on the drive, so a disc swapped or taken out by hand updates the view.
    readonly property bool inCdSection: String(cur.p1) === "cdplayer"
                                        && (view === LibraryModel.PluginItems || view === LibraryModel.AlbumPage)
    property string cdCoverUrl: ""
    // the disc id the CD view is drawn for, so a swap/removal can be told apart
    // from the same disc still sitting in the drive (CdRip owns the polling).
    property string cdDiscId: ""
    onInCdSectionChanged: refreshCdInfo()
    // One /api/cd/info on entry: the cover (the CDplayer plugin ships none) and
    // the current disc id as our baseline. CdRip already polls the drive every
    // few seconds when one is present, so we do NOT start a second poll here
    // (every /api/cd/info spins cd-discid — see CdRip.qml).
    function refreshCdInfo() {
        if (!inCdSection) { cdCoverUrl = ""; cdDiscId = ""; return }
        Api.get(Api.srcBase + "/api/cd/info", function(ok, d) {
            if (!root.inCdSection) return
            var has = ok && d && typeof d === "object" && !d.no_disc
            root.cdDiscId = has ? String(d.discid || "") : ""
            if (has && d.cover) root.cdCoverUrl = Api.srcBase + String(d.cover)
            else if (has && d.mbid) root.cdCoverUrl = Api.srcBase + "/api/cd/cover?release=" + encodeURIComponent(String(d.mbid))
            else root.cdCoverUrl = ""
        })
    }
    // React to the disc being swapped or removed while we sit in the CD section.
    // CdRip (Ui.cdrip) keeps `discid` fresh from its own drive poll: a disc gone
    // sends us to the Music root (never a dead CD page), a new disc reloads the
    // CD view so it shows the one now in the drive instead of the old/empty one.
    Connections {
        target: Ui.cdrip
        function onDiscidChanged() {
            if (!root.inCdSection || !Ui.cdrip) return
            var id = String(Ui.cdrip.discid)
            if (id === root.cdDiscId) return
            root.cdDiscId = id
            if (id === "") { root.navSources(); return }
            root.refreshCdInfo()
            if (root.view === LibraryModel.AlbumPage) root.navBack()   // menu reloads and shows the new disc
            else root.loadTop()
        }
    }

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
        { icon: "music", key: "player.tabs.music" },
        { icon: "app-window", key: "player.tabs.apps" }, { icon: "compass", key: "player.tabs.discover" },
        { icon: "settings", key: "" }]
    // Home tiles: 3 columns on a normal canvas, 5 on ultrawide, one row of 9 on a very long bar
    readonly property int homeCols: width >= 2700 ? 9 : width >= 1500 ? 5 : 3
    readonly property int homeRows: Math.ceil(9 / homeCols)
    readonly property real homeTw: (width - 32 - 12 * (homeCols - 1)) / homeCols
    // 117 is the tile of the classic 3 rows; with fewer rows they share the height (up to 200)
    readonly property real homeTh: homeRows === 3 ? 117 + Math.max(0, height - 600) / 3
                                                  : Math.min(200, (height - 83 - 62 - 12 - 12 * (homeRows - 1)) / homeRows)
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

    // ─── tessere delle sorgenti (radice del tab Musica) ─────────────────────
    // "Libreria locale" (le tessere qui sopra) e "Radio" sono sempre presenti;
    // i servizi di streaming (Qobuz/Tidal/Spotify) compaiono solo se il plugin
    // e' installato, scoperti dalla lista `apps` di Lyrion. Ogni tessera porta:
    //  - library → la home della libreria (le 9 tessere);
    //  - radio   → l'elenco delle stazioni;
    //  - app     → la radice del servizio (PluginItems con il suo `cmd`).
    property var sourceTiles: []
    property bool sourcesProbed: false
    // whether the CDplayer plugin is loaded (a home-menu plugin, not an app):
    // when true the Music root shows a CD tile. Probed with the `can` command.
    property bool cdAvailable: false
    // login state of the streaming services (key -> {available, loggedIn}),
    // fetched from the backend; and the reverse map plugin cmd -> service key,
    // so a service opened from its tile knows whether it still needs a login.
    property var svcStatus: ({})
    property var svcByCmd: ({})
    // the streaming services we promote to a tile, matched case-insensitively
    // on the app's name (Spotty is the Spotify bridge plugin). `key` is the
    // backend's service id for /services/* (login state + login flows).
    // Osmium-drawn marks for the services (icons/svc-*.svg), so the Music root
    // looks like Osmium and not Lyrion's default theme (the `srvIcon` images
    // Lyrion ships are no longer shown on these tiles — see the tile below).
    readonly property var sourceServices: [
        { label: "Qobuz", key: "qobuz", match: ["qobuz"], icon: "svc-qobuz" },
        { label: "Tidal", key: "tidal", match: ["tidal", "wimp"], icon: "svc-tidal" },
        { label: "Spotify", key: "spotty", match: ["spotify", "spotty"], icon: "svc-spotify" },
        { label: "Deezer", key: "deezer", match: ["deezer"], icon: "svc-deezer" }]
    function rebuildSources(apps) {
        var out = []
        var byCmd = {}
        // Favourites and the local library come first, then the streaming
        // services, then radio. "favorites" is the global Lyrion favourites
        // menu (opened as a plugin item with cmd "favorites").
        out.push({ kind: "favorites", label: Tr.t("player.titles.favorites"), icon: "heart", srvIcon: "", cmd: "favorites" })
        out.push({ kind: "library", label: Tr.t("player.titles.localLibrary"), icon: "library", srvIcon: "", cmd: "" })
        // streaming services, in the order declared, only if available
        for (var s = 0; s < sourceServices.length; s++) {
            var svc = sourceServices[s]
            for (var i = 0; i < apps.length; i++) {
                var nm = String(apps[i].name || "").toLowerCase()
                var hit = false
                for (var m = 0; m < svc.match.length; m++) if (nm.indexOf(svc.match[m]) >= 0) { hit = true; break }
                if (hit) { out.push({ kind: "app", key: svc.key, label: svc.label || apps[i].name, icon: svc.icon, srvIcon: apps[i].icon || "", cmd: apps[i].id }); byCmd[String(apps[i].id)] = svc.key; break }
            }
        }
        // the CD player, if the plugin is installed (opened as a plugin item
        // with cmd "cdplayer", i.e. the home-menu `go` action ['cdplayer','items'])
        if (root.cdAvailable)
            out.push({ kind: "cd", label: Tr.t("player.titles.cdPlayer"), icon: "disc", srvIcon: "", cmd: "cdplayer" })
        out.push({ kind: "radio", label: Tr.t("player.titles.radio"), icon: "radio", srvIcon: "", cmd: "" })
        sourceTiles = out
        svcByCmd = byCmd
    }
    function loadSources() {
        if (!Player.connected) return
        sourcesProbed = true
        Player.query(["apps", "0", "9999"], function(ok, r) {
            var apps = []
            if (ok && r) {
                var loop = r.appss_loop || r.apps_loop || r.item_loop || []
                for (var i = 0; i < loop.length; i++) apps.push({ name: loop[i].name, id: loop[i].cmd, icon: loop[i].icon })
            }
            // the CD player is a home-menu plugin, not an app: probe it with
            // `can` (drive-free) so the tile only appears when it is loaded.
            Player.query(["can", "cdplayer", "items", "?"], function(ok2, r2) {
                root.cdAvailable = !!(ok2 && r2 && r2._can)
                root.rebuildSources(apps)
                root.loadServiceStatus()
            })
        })
    }
    // login state of Qobuz/Tidal/Spotify, from the backend (never secrets)
    function loadServiceStatus() {
        Api.get(Api.apiBase + "/services/status", function(ok, d) {
            if (ok && d && d.services) root.svcStatus = d.services
        })
    }
    // the service key of the plugin currently open (empty if not a known
    // streaming service), its label, and whether its root still needs a login
    readonly property string curSvcKey: view === LibraryModel.PluginItems ? (svcByCmd[String(cur.p1)] || "") : ""
    readonly property string curSvcLabel: {
        for (var i = 0; i < sourceServices.length; i++) if (sourceServices[i].key === curSvcKey) return sourceServices[i].label
        return ""
    }
    readonly property bool curSvcNeedsLogin: curSvcKey !== "" && String(cur.p2 || "") === ""
                                             && !!svcStatus[curSvcKey] && svcStatus[curSvcKey].loggedIn === false
    // ─── accesso ai servizi di streaming dal kiosk ──────────────────────────
    // Qobuz: box utente+password (il plugin fa lui l'md5). Tidal/Spotify:
    // approvazione da telefono (QR del link + polling finche' il servizio
    // conferma). Tutta l'autenticazione vive nei plugin, pilotata dal backend.
    function serviceLogin(key, label) {
        if (key === "qobuz") qobuzLogin(label, "")
        // Spotify sign-in changes too often to drive from here; just point the
        // user at the Spotty plugin in Lyrion, where the account is set up.
        else if (key === "spotty") Ui.dialogs.notice(Tr.t("services.spotty.pluginOnly"))
        else deviceLogin(key, label)
    }
    function qobuzLogin(label, error) {
        Ui.dialogs.login(Tr.tf("services.signInTitle", "name", label), Tr.t("services.qobuz.hint"),
                         "", error, function(u, p) {
            if (u === null) return
            Api.post(Api.apiBase + "/services/qobuz/login", { username: u, password: p }, function(ok, d) {
                if (ok && d && d.success) root.afterServiceLogin()
                else root.qobuzLogin(label, Tr.t("services.loginFailed"))
            }, 40000)
        })
    }
    function deviceLogin(key, label) {
        // Spotty signs in over Spotify Connect (pick a device in the Spotify
        // app), the others via a QR link: the opening hint differs
        var hint = key === "spotty" ? Tr.t("services.spotty.preparing") : Tr.t("services.device.scanHint")
        Ui.dialogs.deviceAuth(Tr.tf("services.signInTitle", "name", label), hint,
                              function(ok) { root._stopSvcPoll() })
        Api.post(Api.apiBase + "/services/" + key + "/auth/start", {}, function(ok, d) {
            if (!Ui.dialogs.active || Ui.dialogs.kind !== 8) return
            if (!ok || !d || !d.success) { Ui.dialogs.deviceAuthError(Tr.t("services.loginFailed")); return }
            if (d.connect) Ui.dialogs.deviceAuthConnect(d.device || "")       // Spotify Connect
            else if (d.link) Ui.dialogs.deviceAuthUpdate(d.link, d.deviceCode || "", d.qr || "")
            else { Ui.dialogs.deviceAuthError(Tr.t("services.loginFailed")); return }
            root._startSvcPoll(key, d.deviceCode || "")
        }, 30000)
    }
    function _startSvcPoll(key, code) { svcPoll.stop(); svcPoll.svcKey = key; svcPoll.devCode = code || ""; svcPoll.start() }
    function _stopSvcPoll() { svcPoll.stop() }
    function afterServiceLogin() {
        _stopSvcPoll()
        if (Ui.dialogs.active) Ui.dialogs.close()
        loadServiceStatus()
        loadTop()
    }
    Timer {
        id: svcPoll
        property string svcKey: ""
        property string devCode: ""
        interval: 3000; repeat: true; running: false
        onTriggered: {
            if (!Ui.dialogs.active || Ui.dialogs.kind !== 8) { stop(); return }
            var url = Api.apiBase + "/services/" + svcKey + "/auth/poll"
            if (devCode !== "") url += "?deviceCode=" + encodeURIComponent(devCode)
            Api.get(url, function(ok, d) { if (ok && d && Number(d.hasCredentials) === 1) root.afterServiceLogin() }, 12000)
        }
    }
    Component.onCompleted: { rebuildSources([]); if (Player.connected) loadSources() }
    Connections { target: Player; function onConnectedChanged() { if (Player.connected) root.loadSources() } }
    // a new Lyrion (multiroom follow / external server) has its own apps
    Connections { target: Api; function onLmsBaseChanged() { root.sourcesProbed = false; root.loadSources() } }

    // ─── navigazione ───────────────────────────────────────────────────────
    function loadTop() {
        if (cur.view === LibraryModel.Home || cur.view === root.sourcesRoot) return
        if (cur.view === LibraryModel.AlbumPage || cur.view === LibraryModel.ArtistPage) {
            // a fresh page every time, also from one album page to another
            pageLoader.sourceComponent = null
            pageLoader.sourceComponent = cur.view === LibraryModel.AlbumPage ? albumPageComp : artistPageComp
            return
        }
        pageLoader.sourceComponent = null
        Library.request(cur.view, cur.p1, cur.p2, cur.input)
        // back to a list we had scrolled (cur.scroll, set in goView): restore
        // it once the rows land (onLoaded below); a fresh view starts at the top
        if (cur.scroll) pendingScroll = cur.scroll
        else { pendingScroll = null; list.scrollTop() }
    }
    // the scroll position of the list we are leaving, waiting to be put back
    property var pendingScroll: null
    function goView(view, title, p1, p2, input, replace, cover) {
        var n = nav.slice()
        // remember where this list was before we dive into an album/artist, so
        // Back lands us there instead of at the top (#…)
        if (!replace && !isPage && view !== LibraryModel.Home && n.length && n[n.length - 1].view !== LibraryModel.Home)
            n[n.length - 1].scroll = list.scrollAnchor()
        // `cover` carries a plugin album's cover URL to AlbumPage (local albums
        // build theirs from album_id, so it stays empty for them)
        var e = { view: view, title: title || "…", p1: p1 || "", p2: p2 || "", input: input || "", cover: cover || "" }
        if (replace) n[n.length - 1] = e; else { if (n.length >= 16) return; n.push(e) }
        nav = n
        navDir = 1
        search.text = ""; Library.filter = ""
        ctx.close()
        if (!(replace && msearchOpen)) msearchOpen = false
        loadTop()
        appear()
        landNav(null)
    }
    // Where the remote's spotlight lands when this panel shows a new screen
    // (Nav.land): the content, never the bars above it. `from` is the entry
    // one came back from, so the home lights the tile that had been opened.
    function landing(from) {
        if (tab === 3) return { box: settingsTab, pick: null }
        if (tab === 2) return { box: discoverTab, pick: null }
        if (view === root.sourcesRoot) return { box: sourcesBox, pick: function() { return sourcesBox.tileFor(from) } }
        if (view === LibraryModel.Home) return { box: tilesBox, pick: function() { return tilesBox.tileFor(from) } }
        if (isPage) return { box: pageLoader, pick: function() { return pageLoader.item ? pageLoader.item.navFirst : null } }
        return { box: list, pick: null }
    }
    function landNav(from) { var l = landing(from); Nav.land(l.box, l.pick) }
    // 🚨 Se l'apparecchio passa a un altro Lyrion (multiroom "segui", o server
    // esterno), quello che si sta guardando e' l'elenco del server di prima:
    // si riparte dalla radice delle sorgenti del nuovo.
    Connections { target: Api; function onLmsBaseChanged() { root.navSources() } }

    // the Music tab's root: the source tiles, above the library home
    function navSources() {
        nav = [{ view: root.sourcesRoot, title: Tr.t("player.titles.sources"), p1: "", p2: "", input: "" }]
        navDir = -1
        msearchOpen = false; ctx.close(); search.text = ""
        pageLoader.sourceComponent = null
        appear()
        landNav(null)
    }
    // the library home (the 9 tiles), one level under the sources root so Back
    // from it returns to the tiles
    function navHome() {
        var from = nav.length > 2 ? nav[2] : null
        nav = [{ view: root.sourcesRoot, title: Tr.t("player.titles.sources"), p1: "", p2: "", input: "" },
               { view: LibraryModel.Home, title: Tr.t("player.titles.localLibrary"), p1: "", p2: "", input: "" }]
        navDir = -1
        msearchOpen = false; ctx.close(); search.text = ""
        pageLoader.sourceComponent = null
        appear()
        landNav(from)
    }
    function navBack() {
        // in Settings the remote's Back steps up its own levels first
        if (tab === 3 && settingsTab.backStep()) return
        if (nav.length <= 1) return
        var from = nav[nav.length - 1]
        var n = nav.slice(); n.pop(); nav = n
        navDir = -1
        msearchOpen = false; search.text = ""; ctx.close()
        loadTop(); appear()
        landNav(from)
    }
    function navToCrumb(i) {
        if (i >= nav.length - 1) return
        var from = nav[i + 1]
        nav = nav.slice(0, i + 1)
        navDir = -1
        msearchOpen = false; search.text = ""; ctx.close()
        loadTop(); appear()
        landNav(from)
    }
    function openTab(i) {
        navDir = i > tab ? 1 : i < tab ? -1 : 0
        tab = i; ctx.close()
        if (i === 1) {
            // "Apps · CD": the Jive home menu stands as its own root
            nav = [{ view: LibraryModel.MenuHome, title: Tr.t("player.titles.apps"), p1: "", p2: "", input: "" }]
            navDir = -1; msearchOpen = false; search.text = ""; pageLoader.sourceComponent = null
            loadTop()
        }
        else if (i === 0) {
            // back to Music: keep a library view in place, otherwise show the
            // sources root (never land on a service/apps plugin view)
            var v = view
            if (!(v === root.sourcesRoot || v === LibraryModel.Home || v === LibraryModel.Artists || v === LibraryModel.Albums || v === LibraryModel.Tracks ||
                  v === LibraryModel.Folders || v === LibraryModel.Playlists || v === LibraryModel.PlaylistTracks ||
                  v === LibraryModel.Genres || v === LibraryModel.Years || v === LibraryModel.Composers ||
                  v === LibraryModel.NewMusic || v === LibraryModel.Search || v === LibraryModel.AlbumPage || v === LibraryModel.ArtistPage)) navSources()
        } else if (i === 3) settingsTab.enter()
        else if (i === 2) discoverTab.enter()
        appear()
        landNav(null)
    }
    function showPlaylists() { tab = 0; navHome(); goView(LibraryModel.Playlists, Tr.t("player.titles.playlists")) }
    // the album and artist pages, from anywhere (library, search, Now Playing,
    // credits); a person known only to MusicBrainz opens the artist page by mbid
    function showMusicTab() { if (tab !== 0) { navDir = -1; tab = 0; ctx.close() } }
    // restart / shut down: the ⏻ button of the tab bar, and a remote's power key
    function openPower() {
        Ui.dialogs.power(function(act) {
            if (!act) return
            Api.post(Api.apiBase + "/" + act, {}, function() {}, 12000)
            Ui.toast.say(act === "reboot" ? "rotate-cw" : "power",
                         Tr.t(act === "reboot" ? "settings.msg.rebooting" : "settings.msg.shuttingDown"))
        })
    }
    // the Favourites list straight away (a remote key): the same list the
    // tile on the library home opens, with Back leading to that home
    function openFavorites() {
        showMusicTab(); navHome()
        goView(LibraryModel.PluginItems, Tr.t("player.titles.favorites"), "favorites")
    }
    function openAlbum(id, title) { if (!id) return; showMusicTab(); goView(LibraryModel.AlbumPage, title, String(id)) }
    // a plugin album opens the same AlbumPage as a local one, but in plugin mode:
    // p1 = plugin command, p2 = item id (marks plugin mode), cover = its artwork.
    // The page drills [cmd,"items",…,"item_id:"+item] for the tracks (AlbumPage.qml).
    function openPluginAlbum(cmd, item, title, cover, favUrl) {
        if (!cmd || !item) return
        // favUrl rides in `input` (an album page has no search input of its own)
        showMusicTab(); goView(LibraryModel.AlbumPage, title, String(cmd), String(item), favUrl || "", false, cover || "")
    }
    function openArtist(id, name) { if (!id) return; showMusicTab(); goView(LibraryModel.ArtistPage, name, String(id)) }
    function openPerson(mbid, name) { if (!mbid) return; showMusicTab(); goView(LibraryModel.ArtistPage, name, "", "mbid:" + mbid) }
    function openMenu(items, x, y) { ctx.open(items, x, y) }

    // ── db: library favorites ─────────────────────────────────────────────
    // Lyrion saves an album/artist/genre favorite as a `db:` query URL
    // (e.g. db:album.title=X&contributor.name=Y), not a playable stream. The
    // plain `favorites items`/`favorites playlist play` path drills into
    // nothing and refuses to play it ("Cannot request non-HTTP URL db:…"); only
    // menu mode would expand it, which is how Material shows it. Rather than
    // teach the whole plugin browser menu mode, we resolve such a favorite back
    // to the real library object and reuse the album/artist page and
    // playlistcontrol, which work. (issue #125)
    function dbFavField(url, key) {
        var m = String(url).match(new RegExp("(?:^db:|&)" + key + "=([^&]*)"))
        return m ? decodeURIComponent(m[1].replace(/\+/g, " ")) : ""
    }
    function dbFavKind(url) {
        if (String(url).indexOf("db:") !== 0) return ""
        if (dbFavField(url, "album\\.title")) return "album"
        if (dbFavField(url, "contributor\\.name")) return "artist"
        return ""                                   // genre/year/…: leave as is
    }
    // resolve the db: query to an id, then act: mode "open" navigates to the
    // page, "load"/"add"/"insert" feed the queue through playlistcontrol.
    function dbFavAct(it, mode) {
        var url = it.url, kind = dbFavKind(url)
        if (!kind) return false
        var feed = function(type, id) {
            if (!id) { say("alert-triangle", "player.queueFailed"); return }
            if (mode === "open") { if (type === "album_id") openAlbum(id, it.text); else openArtist(id, it.text); return }
            Player.query(["playlistcontrol", "cmd:" + mode, type + ":" + id], function(ok) {
                Player.refresh()
                if (!ok) say("alert-triangle", "player.queueFailed")
                else if (mode === "add") say("list-plus", "player.addedToQueue")
                else if (mode === "insert") say("list-start", "player.playingNext")
            })
        }
        if (kind === "album") {
            var at = dbFavField(url, "album\\.title"), aa = dbFavField(url, "contributor\\.name")
            Player.query(["albums", "0", "20", "search:" + at, "tags:la"], function(ok, r) {
                var loop = (ok && r) ? r.albums_loop : null, pick = ""
                for (var i = 0; loop && i < loop.length; i++) {
                    if (!pick) pick = String(loop[i].id)
                    if (aa && String(loop[i].artist || "").toLowerCase() === aa.toLowerCase()) { pick = String(loop[i].id); break }
                }
                feed("album_id", pick)
            })
        } else {
            var cn = dbFavField(url, "contributor\\.name")
            Player.query(["artists", "0", "20", "search:" + cn], function(ok, r) {
                var loop = (ok && r) ? r.artists_loop : null, pick = ""
                for (var i = 0; loop && i < loop.length; i++) {
                    if (!pick) pick = String(loop[i].id)
                    if (String(loop[i].artist || "").toLowerCase() === cn.toLowerCase()) { pick = String(loop[i].id); break }
                }
                feed("artist_id", pick)
            })
        }
        return true
    }
    function closeMenu() { ctx.close() }
    readonly property bool menuOpen: ctx.visible
    // Il tasto "cerca" del telecomando: il campo di questa schermata se ce
    // n'e' uno (il filtro di artisti e album), altrimenti quello della
    // libreria, che sta nella home.
    function focusSearch() {
        showMusicTab()
        if (view === LibraryModel.Home) { homeSearch.takeFocus(); return }
        if (hasSearch) { search.takeFocus(); return }
        navHome()
        // la home compare adesso: il campo puo' prendere il fuoco al giro dopo
        searchDelay.restart()
    }
    Timer { id: searchDelay; interval: 60; onTriggered: homeSearch.takeFocus() }
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
        if (view !== LibraryModel.Albums || Library.state !== 2 || Library.count < 1 || list.coverflow || list.changer) return null
        var cw = list.cardW, top = (cdBanner.visible ? 48 : 0)
        menuX = list.x + cw / 2; menuY = list.y + cw / 2 + top
        ctx.open(ctxItems(0), menuX, menuY)
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
    // The native context menu of a plugin item (Qobuz, Tidal...): Material's
    // "more". A plugin item carries no favorites_url of its own, so the only way
    // to add a Qobuz album/track to favourites — or jump to its artist/credits —
    // is to ask the plugin for the item's context menu (`isContextMenu:1`), which
    // returns rows whose `go` action does the deed. `nextWindow:"parent"` (and
    // kin) means the action is a one-shot (add to favourites) and leaves the list
    // where it is; anything else drills into a submenu, so we browse into it.
    function openNativeCtx(cmd, id) {
        Player.query([cmd, "items", "0", "100", "item_id:" + id, "isContextMenu:1", "menu:" + cmd], function(ok, r) {
            if (!ok || !r) { say("alert-triangle", "player.ctxError"); return }
            var loop = r.item_loop || r.loop_loop || [], items = []
            for (var i = 0; i < loop.length; i++) {
                var it = loop[i], a = it.actions
                if (!a || !a.go || !a.go.cmd || !a.go.params || !a.go.params.item_id) continue
                var iid = String(a.go.params.item_id), label = String(it.text || "").split("\n")[0]
                if (!label) continue
                var nw = String(a.go.nextWindow || "")
                var terminal = nw === "parent" || nw === "grandparent" || nw === "refresh" || nw === "refreshOrigin" || nw === "home"
                var isFav = /favor/i.test(label)
                var ic = isFav ? "heart" : /artist/i.test(label) ? "user" : terminal ? "list-plus" : "chevron-right"
                items.push((function(c, i2, lab, term, fav) { return { icon: ic, label: lab, cb: function() {
                    if (term) Player.query([c, "items", "0", "10", "item_id:" + i2, "menu:" + c], function(ok2) {
                        // plugin native ctx (Qobuz/Tidal…) → the service's own My Favourites
                        say(fav ? "heart" : "check", ok2 ? (fav ? "player.addedToStreamingServiceFavorites" : "player.actionDone") : "player.favoriteError")
                        if (ok2 && fav && cur.view === LibraryModel.PluginItems && cur.p1 === "favorites") loadTop()
                    })
                    else root.goView(LibraryModel.PluginItems, lab, c, i2)
                } } })(cmd, iid, label, terminal, isFav))
            }
            if (!items.length) { say("info", "player.noActions"); return }
            ctx.open(items, root.menuX, root.menuY)
        })
    }
    function favoriteMenu(it, row) {
        var L = []
        // un preferito e' musica quanto la riga da cui e' nato: stessa coda,
        // piu' le voci che valgono solo qui (rinomina, sposta, togli)
        var isDir = it.hasItems && !it.isAudio
        if (it.isAudio || isDir) {
            // a db: library favorite is resolved to its object; the plugin's own
            // `favorites playlist add` cannot queue a db: query (issue #125)
            if (dbFavKind(it.url)) {
                L.push({ icon: "list-plus", label: Tr.t("player.addToQueue"), cb: function() { dbFavAct(it, "add") } })
                L.push({ icon: "list-start", label: Tr.t("player.playNext"), cb: function() { dbFavAct(it, "insert") } })
            } else pluginQueueItems(L, "favorites", it.id)
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
            // an album of an app (Qobuz, Spotify...): it can go into the CD
            // changer like one of the library (App.changerPut). Lyrion marks
            // one a "playlist" with items, often playable as a whole too
            // (isaudio): Qobuz's have no favourites URL, so the disc keeps the
            // app's item.
            if (!it.hasInput && it.ptype === "playlist" && it.hasItems)
                L.push({ icon: "disc-3", label: Tr.t("player.changer.putIn"), cb: function() {
                    Ui.app.changerPut({ title: it.text, artUrl: list.iconUrl(it.icon), url: it.favUrl, cmd: cur.p1, item: it.id })
                } })
            // the plugin's own context menu (Material's "more"): add to the
            // service's favourites, go to the artist, credits... Shown for real
            // music items (an album, a track) since navigation nodes have none.
            if (!it.hasInput && (it.isAudio || it.ptype === "playlist"))
                L.push({ icon: "list", label: Tr.t("player.moreActions"), cb: function() { root.openNativeCtx(cur.p1, it.id) } })
            break
        case LibraryModel.MenuHome: case LibraryModel.Menu:
            // i menu Jive portano le proprie azioni: `add` accoda, `add-hold`
            // fa suonare dopo
            if (it.addact && it.addact.length) L.push({ icon: "list-plus", label: Tr.t("player.addToQueue"), cb: function() { Player.cmd(it.addact) } })
            if (it.addhold && it.addhold.length) L.push({ icon: "list-start", label: Tr.t("player.playNext"), cb: function() { Player.cmd(it.addhold) } })
            // an app's album in a Jive menu (Apps -> Qobuz...): a "playlist"
            // that plays as a whole; it goes into the CD changer by the app's
            // command and item, which App.changerPut turns into its tracks'
            // addresses (its text is "Album\nArtist")
            if (!it.hasInput && it.ptype === "playlist" && it.play && it.play.length) {
                var item = ""
                for (var pi = 1; pi < it.play.length; pi++) if (String(it.play[pi]).indexOf("item_id:") === 0) item = String(it.play[pi]).slice(8)
                if (item !== "")
                    L.push({ icon: "disc-3", label: Tr.t("player.changer.putIn"), cb: function() {
                        Ui.app.changerPut({ title: String(it.text).split("\n")[0], artUrl: list.iconUrl(it.icon), cmd: String(it.play[0]), item: item })
                    } })
            }
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
            // a db: library favorite is resolved to its real object (issue #125)
            if (cmd === "favorites" && dbFavKind(it.url) && dbFavAct(it, onPlay ? "load" : "open")) break
            if (!onPlay && it.hasInput) {          // nodo di ricerca del plugin: si chiede il testo
                msearchOpen = true; msearch.text = ""
                msearchTitle = it.text || Tr.t("player.titles.search")
                msearchGo = []; msearchPlugin = { cmd: cmd, item: it.id }
                msearch.takeFocus()
            }
            // in an album list (grid / Cover Flow / changer) a tap on an album
            // container opens the same AlbumPage as the local library, in plugin
            // mode; otherwise a container drills further into the plugin menu
            // an album/playlist container (type set, not a plain track) with a
            // real cover: a streaming album is flagged isaudio too, so key on
            // the type + cover, not on isAudio, exactly like the C++ heuristic.
            else if (!onPlay && Library.pluginAlbumList && it.hasItems && it.ptype
                     && it.ptype !== "audio" && list.isRemoteCover(it.icon))
                openPluginAlbum(cmd, it.id, it.text, list.iconUrl(it.icon), it.favUrl)
            // the CD disc is an album: its cover rides in cdCoverUrl (not in the
            // item icon), so open the same AlbumPage with that cover
            else if (!onPlay && root.inCdPlayer && it.hasItems)
                openPluginAlbum(cmd, it.id, it.text, root.cdCoverUrl, it.favUrl)
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
    Connections { target: Library; function onLoaded() {
        // the rows are in: put the list back where it was before we dived in
        if (root.pendingScroll) { var a = root.pendingScroll; root.pendingScroll = null; list.restoreAnchor(a) }
        if (!slideAnim.running && !paintGate.running) root.appear()
    } }

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
            width: 16 + brandText.implicitWidth + 4; height: 40
            x: netIcon.x - width
            visible: tabRow.width <= x
            BrandMark { id: brandText; x: 16; anchors.verticalCenter: parent.verticalCenter; cap: 8 }
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
                color: netIcon.off ? Theme.red400 : Theme.silverA(0.6)
                pressColor: Theme.white; press: netTap.pressAnim
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
                color: Theme.gold
                pressColor: Theme.white; press: powerTap.pressAnim
                scale: powerTap.tapScale
            }
            Tap {
                id: powerTap; tap: 0.9
                onClicked: root.openPower()
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
                    // l'icona non prende `c` (animato): due strati, vedi Icon.qml
                    Icon { x: 16; anchors.verticalCenter: parent.verticalCenter; name: tabItem.modelData.icon; size: 14
                           color: tabItem.active ? Theme.white : Theme.silverA(0.5); pressColor: Theme.white; press: tabItem.active ? 0 : tabTap.pressAnim }
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
            Tap { onClicked: root.tab === 1 ? root.openTab(1) : root.navSources() }
        }
        // the trail stops short of the buttons on the right and keeps its end
        // in view, so a long chain of pages never runs under "Back"
        Item {
            id: crumbClip
            // anchor the right edge straight to whichever button sits on the
            // right, so the trail is always clipped before it instead of
            // running over "Back" (issue #113); x-arithmetic got this wrong.
            anchors.left: parent.left; anchors.leftMargin: 43
            anchors.right: viewPick.visible ? viewPick.left : backBtn.visible ? backBtn.left : parent.right
            anchors.rightMargin: 8
            height: parent.height; clip: true
            visible: root.nav.length > 1
        Row {
            id: crumbRow
            x: Math.min(0, crumbClip.width - width); height: parent.height
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
        }
        Rectangle {                                     // "Indietro"
            id: backBtn
            visible: root.nav.length > 1
            anchors.right: parent.right; anchors.rightMargin: 12
            y: 21.5 - 11; width: backText.implicitWidth + 24; height: 22; radius: 8
            color: backTap.mix(Theme.wa(0.05), Theme.wa(0.1))
            Text { id: backText; anchors.centerIn: parent; text: Tr.t("common.back"); color: Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 12 }
            Tap { id: backTap; onClicked: root.navBack() }
        }
        // the albums as a grid, Cover Flow or the CD changer (also in
        // Settings → Library): the view on screen, a tap drops the list down
        Rectangle {
            id: viewPick
            visible: list.albumGrid && !root.isPage
            readonly property string view: Ui.app ? Ui.app.albumView : "grid"
            readonly property var views: [{ id: "grid", icon: "layout-grid", label: "player.view.grid" },
                                          { id: "coverflow", icon: "gallery-horizontal", label: "player.view.coverflow" },
                                          { id: "changer", icon: "disc-3", label: "player.view.changer" }]
            readonly property var cur: views[Math.max(0, ["grid", "coverflow", "changer"].indexOf(view))]
            anchors.right: backBtn.visible ? backBtn.left : parent.right
            anchors.rightMargin: backBtn.visible ? 8 : 12
            y: 21.5 - 11
            width: 8 + 13 + 6 + viewText.implicitWidth + 6 + 12 + 8; height: 22; radius: 8
            color: viewTap.mix(view !== "grid" ? Theme.goldA(0.15) : Theme.wa(0.05), Theme.wa(0.12))
            Icon { x: 8; anchors.verticalCenter: parent.verticalCenter; name: viewPick.cur.icon; size: 13; color: viewPick.view !== "grid" ? Theme.gold : Theme.silverA(0.7) }
            Text { id: viewText; x: 8 + 13 + 6; anchors.verticalCenter: parent.verticalCenter; text: Tr.t(viewPick.cur.label); color: viewPick.view !== "grid" ? Theme.gold : Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 12 }
            Icon { x: parent.width - 8 - 12; anchors.verticalCenter: parent.verticalCenter; name: "chevron-down"; size: 12; color: Theme.silverA(0.7) }
            Tap {
                id: viewTap
                onClicked: {
                    var L = viewPick.views.map(function(v) {
                        return { icon: v.id === viewPick.view ? "check" : v.icon, label: Tr.t(v.label), cb: function() { Ui.app.setAlbumView(v.id) } }
                    })
                    var p = viewPick.mapToItem(ctx.parent, viewPick.width / 2, viewPick.height)
                    ctx.open(L, Math.max(p.x, ctx.parent.width - 8 - 136), p.y)
                }
            }
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
            SettingsTab { id: settingsTab; anchors.fill: parent; visible: root.tab === 3; devScale: root.devScale }
            DiscoverTab { id: discoverTab; anchors.fill: parent; visible: root.tab === 2; devScale: root.devScale }

            Item {
                id: libArea
                anchors.fill: parent
                visible: root.tab !== 3 && root.tab !== 2

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
                // la radice delle sorgenti: le tessere dei servizi, della radio e
                // della libreria locale (dove si atterra aprendo il tab Musica)
                Item {
                    anchors.fill: parent
                    anchors.topMargin: cdBanner.visible ? 48 : 0
                    visible: root.view === root.sourcesRoot && Player.connected
                    Item {
                        id: sourcesBox
                        anchors.fill: parent
                        // the tile the spotlight returns to, coming back from `e`
                        function tileFor(e) {
                            if (!e) return null
                            for (var i = 0; i < children.length; i++) {
                                var c = children[i]; var m = c.modelData
                                if (!m) continue
                                if (m.kind === "library" && e.view === LibraryModel.Home) return c.navTap
                                if (m.kind === "radio" && e.view === LibraryModel.Radios) return c.navTap
                                if (m.kind === "favorites" && e.view === LibraryModel.PluginItems && String(e.p1) === "favorites") return c.navTap
                                if (m.kind === "app" && e.view === LibraryModel.PluginItems && String(e.p1) === String(m.cmd)) return c.navTap
                                if (m.kind === "cd" && e.view === LibraryModel.PluginItems && String(e.p1) === "cdplayer") return c.navTap
                            }
                            return null
                        }
                        Repeater {
                            model: root.sourceTiles
                            Rectangle {
                                required property var modelData
                                required property int index
                                property alias navTap: srcTap
                                readonly property real tw: root.homeTw
                                readonly property real th: root.homeTh
                                // a streaming service whose account is not set up yet
                                readonly property bool notConnected: modelData.kind === "app" && !!modelData.key
                                                                     && !!root.svcStatus[modelData.key]
                                                                     && root.svcStatus[modelData.key].loggedIn === false
                                x: 16 + (index % root.homeCols) * (tw + 12); y: 62 + Math.floor(index / root.homeCols) * (th + 12)
                                width: tw; height: th; radius: 12
                                color: srcTap.mix(Theme.surface, Theme.light); border.width: 1; border.color: Theme.border
                                // always the Osmium mark (icons/*.svg), never the
                                // image Lyrion's default theme ships for the service
                                Icon { anchors.horizontalCenter: parent.horizontalCenter; y: 29 + (parent.th - 117) / 2; name: modelData.icon; size: 30; color: Theme.silver }
                                Text { anchors.horizontalCenter: parent.horizontalCenter; y: 69 + (parent.th - 117) / 2; height: 20; verticalAlignment: Text.AlignVCenter; text: modelData.label; color: Theme.white; font.family: Theme.font; font.pixelSize: 14 }
                                // badge "non connesso": pallino muto + etichetta
                                Rectangle {
                                    visible: parent.notConnected
                                    x: parent.width - width - 10; y: 10
                                    width: ncRow.width + 14; height: 20; radius: 10
                                    color: Theme.wa(0.08)
                                    Row {
                                        id: ncRow; anchors.centerIn: parent; spacing: 5
                                        Rectangle { width: 7; height: 7; radius: 3.5; color: Theme.silverA(0.55); anchors.verticalCenter: parent.verticalCenter }
                                        Text { text: Tr.t("services.notConnected"); color: Theme.silverA(0.75); font.family: Theme.font; font.pixelSize: 10; anchors.verticalCenter: parent.verticalCenter }
                                    }
                                }
                                Tap {
                                    id: srcTap
                                    onClicked: {
                                        if (modelData.kind === "library") root.goView(LibraryModel.Home, Tr.t("player.titles.localLibrary"))
                                        else if (modelData.kind === "radio") root.goView(LibraryModel.Radios, Tr.t("player.titles.radio"))
                                        else if (modelData.kind === "favorites") root.goView(LibraryModel.PluginItems, Tr.t("player.titles.favorites"), "favorites")
                                        else root.goView(LibraryModel.PluginItems, modelData.label, modelData.cmd)
                                    }
                                }
                            }
                        }
                    }
                }
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
                    // the tiles: where the spotlight lands on the home (Nav.land)
                    Item {
                        id: tilesBox
                        anchors.fill: parent
                        // the tile that opens `e` (a nav entry): coming back,
                        // the spotlight returns to the one that was opened
                        function tileFor(e) {
                            if (!e) return null
                            for (var i = 0; i < children.length; i++) {
                                var c = children[i]
                                if (!c.modelData || c.modelData.view !== e.view) continue
                                if (e.view === LibraryModel.PluginItems && e.p1 !== "favorites") continue
                                return c.navTap
                            }
                            return null
                        }
                        Repeater {
                            model: root.tiles
                            Rectangle {
                                required property var modelData
                                required property int index
                                property alias navTap: tileTap
                                readonly property real tw: root.homeTw
                                // py-7 (28) + icona 30 + mb-2.5 (10) + riga text-sm (20) + py-7 (28)
                                // + 2 di bordo = 117: misurato 140 px a 720p in Electron (113 era 4 in meno).
                                // A taller canvas (16:10: 640) shares its extra height among the rows.
                                readonly property real th: root.homeTh
                                x: 16 + (index % root.homeCols) * (tw + 12); y: 62 + Math.floor(index / root.homeCols) * (th + 12)
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
                }

                // il resto: barre di ricerca + lista + indice A-Z
                Item {
                    anchors.fill: parent
                    anchors.topMargin: cdBanner.visible ? 48 : 0
                    visible: root.view !== LibraryModel.Home && root.view !== root.sourcesRoot && Player.connected
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
                                Icon { anchors.centerIn: parent; name: "x"; size: 14; color: Theme.silverA(0.5); pressColor: Theme.white; press: xTap.pressAnim }   // active:text-white
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
                        // plugin album: p2 is the item id (marks plugin mode),
                        // p1 the plugin command; a local album has p1 = album_id
                        AlbumPage {
                            browser: root; devScale: root.devScale
                            albumId: String(root.cur.p2) !== "" ? "" : String(root.cur.p1)
                            pluginCmd: String(root.cur.p2) !== "" ? String(root.cur.p1) : ""
                            pluginItemId: String(root.cur.p2 || "")
                            pluginCover: String(root.cur.cover || "")
                            pluginFavUrl: String(root.cur.input || "")
                            pluginTitle: root.cur.title === "…" ? "" : String(root.cur.title || "")
                        }
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
                        // a plugin grid has no A-Z strip, but still reserve the
                        // same 32 px gutter the alphabet uses in the library so a
                        // plugin tile comes out the exact same cardW (same columns,
                        // same shape) as a local-library tile — not wider.
                        width: ((root.azShown || list.grid) ? root.width - 32 - 12 : root.width - 12) - 12
                        height: root.height - root.contentTop - y - 12
                        // navigation menus (radio, app, plugin nodes, Jive menus)
                        // use the same wide icon+label tile as the local-library
                        // home, so a plugin menu matches it in shape and size.
                        menuTileH: root.homeTh
                        visible: Library.state === 2 && Library.count > 0 && !root.isPage && !root.curSvcNeedsLogin
                        cdCoverUrl: root.inCdPlayer ? root.cdCoverUrl : ""
                        inCdPlayer: root.inCdPlayer
                        onRowTap: (row, onPlay) => root.rowTap(row, onPlay)
                        // list.y gia' comprende le barre di ricerca; la fascia del CD sposta tutto il contenitore
                        onRowLongPress: (row, x, y) => { root.menuX = list.x + x; root.menuY = list.y + y + (cdBanner.visible ? 48 : 0); ctx.open(root.ctxItems(row), root.menuX, root.menuY) }
                        onExpandAlbum: (row, x, y, size, src) => hero.fly(row, list.x + x, list.y + y, size, src)
                    }
                    // il riquadro "Accedi" quando si apre un servizio di streaming
                    // senza account (al posto della sola riga "richiede credenziali")
                    Rectangle {
                        visible: root.curSvcNeedsLogin && !root.isPage
                        x: 12; y: parent.listY + 4
                        width: (root.width - 12) - 12; height: 132; radius: 12
                        color: Theme.surface; border.width: 1; border.color: Theme.border
                        Column {
                            anchors.centerIn: parent; spacing: 12; width: parent.width - 48
                            Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap
                                   text: Tr.tf("services.signInTitle", "name", root.curSvcLabel)
                                   color: Theme.white; font.family: Theme.font; font.pixelSize: 17; font.bold: true }
                            Rectangle {
                                anchors.horizontalCenter: parent.horizontalCenter
                                width: 176; height: 46; radius: 8; color: accTap.mix(Theme.gold, "#ca8a04")
                                Text { anchors.centerIn: parent; text: Tr.t("services.signIn"); color: "#1a1a1a"; font.family: Theme.font; font.pixelSize: 15; font.bold: true }
                                Tap { id: accTap; onClicked: root.serviceLogin(root.curSvcKey, root.curSvcLabel) }
                            }
                        }
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
                        visible: Library.state === 2 && Library.count === 0 && !root.isPage && !root.curSvcNeedsLogin
                        x: list.x; y: list.y + 32; width: list.width; horizontalAlignment: Text.AlignHCenter
                        text: Tr.t("common.noResults"); color: Theme.silverA(0.4); font.family: Theme.font; font.pixelSize: 14
                    }
                    // indice A-Z (w-8)
                    AzIndex {
                        visible: root.azShown
                        x: root.width - 32; y: parent.listY; width: 32; height: root.height - root.contentTop - y
                        onLetter: (l) => { var r = Library.letterFirst(l); if (r >= 0) list.scrollToRow(r) }
                        // the letter's first entry sits at the top of the list: the
                        // row (or card) closest to its top-left corner
                        onNavLeave: { var p = Nav.onCanvas(list, 60, 30, 0, 0); Nav.focusIn(list, Qt.rect(p.x, p.y, 0, 0)) }
                    }
                }
            }
        }
        ContextMenu { id: ctx }
    }
}
