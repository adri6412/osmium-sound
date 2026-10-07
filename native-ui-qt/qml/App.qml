// La tela 1024x600: le due schermate (principale e Now Playing) con la loro
// transizione, e sopra gli strati condivisi nello stesso ordine di app.c:
// coda / timer / salva playlist, dialoghi, avviso USB, aggiornamento,
// copia CD, tastiera a schermo, salvaschermo. Niente filmato d'avvio: lo
// schermo parte con l'interfaccia (il marchio lo mostra già Plymouth).
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: app
    property real devicePixelScale: 1
    property bool expanded: false
    property bool viewVu: Sys.conf("nowplaying-view", "vu") !== "lyrics"
    // the albums of the library as a grid, as Cover Flow or as the discs of
    // the CD changer (a preference of this screen, kept next to the Now
    // Playing view)
    function albumViewOf(v) { return v === "coverflow" || v === "changer" ? v : "grid" }
    property string albumView: albumViewOf(Sys.conf("album-view", "grid"))
    function setAlbumView(v) { albumView = albumViewOf(v); Sys.setConf("album-view", albumView) }

    // ─── the CD changer (albums view ChangerView.qml, scene AnimChanger.qml) ─
    // The discs in the changer, disc 1 first, kept across restarts so the
    // changer still finds them in the same slots. A disc is an album of the
    // library { id, title, art (the cover's id) } or one from an app (Qobuz,
    // Spotify...) put in from its long-press menu { title, artUrl, urls (its
    // tracks' addresses, read when it goes in: stable, unlike the app's item
    // ids, which follow its menus and searches), or failing those url (what
    // Favourites would keep) or cmd + item (the app's own item) }.
    property var changerDiscs: {
        try { var d = JSON.parse(Sys.conf("changer-discs", "[]")); return Array.isArray(d) ? d : [] } catch (e) { return [] }
    }
    // what the scene gets (NpAnimation keys it): the album's name, the cover
    // as a picture's address
    readonly property var changerScene: changerDiscs.map(function(d) {
        return { album: d.title, art: d.artUrl ? d.artUrl : d.art ? Api.lmsBase + "/music/" + d.art + "/cover?size=300" : "" }
    })
    // a disc from a library row { id, text, art } or a disc already
    function changerDiscOf(a) {
        if (!a) return null
        if (a.title !== undefined) return a
        return { id: String(a.id || ""), title: a.text || "", art: a.art || "" }
    }
    // what tells two discs apart
    function changerUid(d) {
        return d.id ? "a:" + d.id : "u:" + (d.urls && d.urls.length ? d.urls[0] : d.url || d.cmd + ":" + d.item)
    }
    // the Lyrion commands that load a disc (the queue replaced) or add it
    function changerCmds(d, load) {
        if (d.id) return [["playlistcontrol", "cmd:" + (load ? "load" : "add"), "album_id:" + d.id]]
        if (d.urls && d.urls.length)
            return d.urls.map(function(u, i) { return ["playlist", load && i === 0 ? "play" : "add", u] })
        if (d.url) return [["playlist", load ? "play" : "add", d.url, d.title]]
        return [[d.cmd, "playlist", load ? "play" : "add", "item_id:" + d.item]]
    }
    // commands one after the other (separate requests could reach Lyrion
    // out of order), then `done`
    function changerRun(cmds, done) {
        var k = 0
        function next() {
            if (k >= cmds.length) { if (done) done(); return }
            Player.query(cmds[k++], function() { next() })
        }
        next()
    }
    function changerSave(discs) {
        changerDiscs = discs
        Sys.setConf("changer-discs", JSON.stringify(discs))
    }
    // Discs put in from an app while the changer was not the one playing:
    // in it, not yet in Lyrion's queue. The next Play plays the changer from
    // disc 1, as Done does in its view (an app has no such button).
    property bool changerPending: Sys.conf("changer-pending", "0") === "1"
    function setChangerPending(on) { changerPending = on; Sys.setConf("changer-pending", on ? "1" : "0") }
    // Every Play goes through here first (mini player, Now Playing, the
    // remote, the scenes' keys): true when it was the changer's to take.
    // Done / Play on the changer: the music starts once the disc sits in the
    // drive (NpAnimation.changerSeated); never stuck waiting if no changer is
    // on screen to say so.
    property bool changerAwaitPlay: false
    onChangerAwaitPlayChanged: if (changerAwaitPlay) changerAwaitLimit.restart(); else changerAwaitLimit.stop()
    Timer {
        id: changerAwaitLimit
        interval: 20000
        onTriggered: if (app.changerAwaitPlay) { app.changerAwaitPlay = false; Player.play(true) }
    }
    // the changer on screen in Now Playing (NpAnimation.changerOnScreen)
    property Item changerScreen: null
    // With it on screen, music chosen anywhere in the interface is queued
    // without playing (Player.cmd) and the changer plays it once the disc is
    // in its drive: Lyrion never starts early, nothing has to be paused.
    Binding { target: Player; property: "holdStarts"; value: app.changerScreen !== null }
    Connections {
        target: Player
        function onStartHeld() { if (app.changerScreen) app.changerScreen.awaitNewDisc() }
    }
    function changerTakesPlay() {
        if (Player.playing) return false
        if (changerPending && changerDiscs.length > 0) {
            changerLoad(changerDiscs)
            return true
        }
        // On screen with its disc not in the drive (in the file, or taken
        // out): Play is its own Play key -- the disc goes in, settles and
        // turns, and only then the music (a plain Play started it at once
        // and the changer could only pause it afterwards).
        var sc = changerScreen ? changerScreen.scene : null
        if (sc && sc.loaded === false && sc.hasTrack) {
            if (sc.power && typeof sc.press === "function") sc.press("play")
            else {
                // in standby its keys do nothing: switch on, and the disc
                // goes in as soon as it is on
                if (!Player.power) Player.cmd(["power", "1"])
                changerAwaitPlay = true
            }
            return true
        }
        return false
    }
    // whether the queue playing is the changer's: the album on air is one of its discs
    function changerPlaying() {
        for (var i = 0; i < changerDiscs.length; i++) if (changerDiscs[i].title === Player.album) return true
        return false
    }
    // Load the chosen discs as discs 1, 2, 3... and play them one after the
    // other, like a changer: the queue is the albums in that order. Discs
    // only added after those the changer is already playing join the end of
    // the queue, the music goes on. The Now Playing opens at full screen on
    // the changer, whatever animation the owner chose (that stays as it is).
    function changerLoad(albums) {
        var discs = []
        for (var i = 0; i < albums.length && discs.length < 101; i++) {
            var d = changerDiscOf(albums[i])
            if (d && (d.id || (d.urls && d.urls.length) || d.url || d.item)) discs.push(d)
        }
        if (!discs.length) return
        var before = changerDiscs, kept = changerPlaying() && before.length <= discs.length
        for (var j = 0; kept && j < before.length; j++) kept = changerUid(before[j]) === changerUid(discs[j])
        changerSave(discs)
        setChangerPending(false)
        // A new load goes into the queue without playing: the music starts
        // when the changer has put disc 1 in its drive (changerAwaitPlay).
        var cmds = kept ? [] : [["playlist", "clear"]]
        for (var k = kept ? before.length : 0; k < discs.length; k++) cmds = cmds.concat(changerCmds(discs[k], false))
        changerRun(cmds, function() {
            changerLearn.restart()
            if (!kept) changerAwaitPlay = true
        })
        setExpanded(true)
        np.openStage("changer")
    }
    // An album from an app, put in from its long-press menu: the next disc.
    // When the changer is the one playing it joins its queue at once;
    // otherwise Done in the CD changer view plays them all.
    // Its tracks' addresses are read first (the app's item, `want_url`).
    function changerPut(d) {
        if (changerDiscs.length >= 101) { toast.show(Tr.t("player.changer.full")); return }
        if (d.cmd && d.item && !d.urls) {
            Player.query([d.cmd, "items", "0", "500", "item_id:" + d.item, "want_url:1"], function(ok, r) {
                var loop = ok && r ? r.loop_loop || r.item_loop || [] : [], urls = []
                for (var i = 0; i < loop.length; i++)
                    if (loop[i].url && (loop[i].isaudio === 1 || loop[i].isaudio === "1" || loop[i].type === "audio")) urls.push(String(loop[i].url))
                app.changerPut(Object.assign({}, d, { urls: urls }))
            })
            return
        }
        var discs = changerDiscs.slice()
        for (var i = 0; i < discs.length; i++) if (changerUid(discs[i]) === changerUid(d)) {
            toast.say("disc-3", Tr.tf("player.changer.putDone", "n", String(i + 1)))
            return
        }
        var playing = changerPlaying()
        discs.push(d)
        changerSave(discs)
        if (playing) {
            changerRun(changerCmds(d, false), function() { changerLearn.restart() })
            toast.say("disc-3", Tr.tf("player.changer.putDone", "n", String(discs.length)))
        } else {
            setChangerPending(true)
            toast.say("disc-3", Tr.tf("player.changer.putWait", "n", String(discs.length)))
        }
    }
    // An app's album may be named in its menu otherwise than its tracks name
    // it ("Artist - Album (2019)"): once loaded, the albums of the queue, in
    // order, give each disc the name the player will show, so the changer
    // knows it as that disc. (A moment after: an app's album expands into
    // its tracks behind the command's answer.)
    Timer {
        id: changerLearn
        interval: 2500
        onTriggered: Player.query(["status", "0", "999", "tags:l"], function(ok, r) {
            var pl = ok && r ? r.playlist_loop || [] : [], seq = []
            for (var i = 0; i < pl.length; i++) if (i === 0 || pl[i].album !== pl[i - 1].album) seq.push(String(pl[i].album || ""))
            if (seq.length !== app.changerDiscs.length) return
            var discs = app.changerDiscs.slice(), changed = false
            for (var j = 0; j < discs.length; j++) if (seq[j] && discs[j].title !== seq[j]) {
                discs[j] = Object.assign({}, discs[j], { title: seq[j] })
                changed = true
            }
            if (changed) app.changerSave(discs)
        })
    }
    // Empty the changer: no discs in it any more, and its queue cleared when
    // it is the one playing (an unrelated queue is left alone).
    function changerClear() {
        if (changerPlaying()) Player.cmd(["playlist", "clear"])
        changerSave([])
        setChangerPending(false)
        changerAwaitPlay = false
    }
    // tempo dell'ultimo tocco (per l'auto-apertura e il salvaschermo)
    readonly property real lastInput: Sys.lastInput
    readonly property bool busyOverlay: dialogs.active || vk.active || ota.active || cdrip.open || tutorial.active || remoteIntro.active || remoteTour.active || remotePair.active

    // ─── principale <-> Now Playing: y:'100%' con molla 200/26 ─────────────
    Spring { id: npSpring; stiffness: 200; damping: 26; rate: Theme.motionRate }
    // The remote's spotlight: opening the player it goes to Play; closing
    // it, back to the box it had in the library if that is still there,
    // else where the library's screen says a spotlight starts.
    property var librarySpot: null
    function setExpanded(on) {
        if (expanded === on) return
        if (on) librarySpot = Nav.item && Nav.isInside(mainScreen, Nav.item) ? Nav.item : null
        expanded = on
        npSpring.to = on ? 0 : 1
        if (on) { autoexpand.armed = false; Nav.land(np, function() { return np.navFirst }) }
        else {
            var keep = librarySpot, l = mainScreen.browser.landing(null)
            Nav.land(l.box, function() { return Nav.usable(keep) ? keep : (l.pick ? l.pick() : null) })
        }
    }
    Component.onCompleted: {
        Ui.app = app; Ui.vk = vk; Ui.dialogs = dialogs; Ui.toast = toast; Ui.overlays = overlays
        Nav.root = app                                     // il telecomando cerca i riquadri da qui
        // and where a spotlight with nowhere to start goes (Nav.focusFirst)
        Nav.rootLanding = function() {
            return app.expanded ? { box: np, pick: function() { return np.navFirst } } : mainScreen.browser.landing(null)
        }
        firstStart = !tutorial.wasShown()                  // before the tour can write its file
        npSpring.set(Sys.startExpanded ? 0 : 1)
        expanded = Sys.startExpanded
        if (tutorialCanStart) tutorialDelay.restart()      // no wizard to wait for
    }

    // Choose the player to drive (#99): the server's list, this device's own
    // first; the choice is not persisted, a reboot starts on our own.
    function openPlayerPicker() {
        Player.players(function(ok, list) {
            if (!ok) return
            list = list || []
            list.sort(function(a, b) { return (b.isOwn ? 1 : 0) - (a.isOwn ? 1 : 0) })
            if (list.length <= 1) { toast.show(Tr.t("player.noOtherPlayers")); return }
            var labels = [], cur = -1
            for (var i = 0; i < list.length; i++) {
                labels.push(list[i].isOwn ? list[i].name + " · " + Tr.t("player.thisDevice") : list[i].name)
                if (list[i].id === Player.playerId) cur = i
            }
            dialogs.pick(Tr.t("player.selectPlayer"), labels, cur, function(i) {
                if (i >= 0 && i < list.length) Player.selectPlayer(list[i].isOwn ? "" : list[i].id, list[i].name)
            })
        })
    }

    // The guided tour (Tutorial.qml): once, when the screen is free for the
    // first time and its "shown" file is missing: after the first wizard on
    // a new appliance, at the first start after the update on an old one.
    readonly property bool tutorialCanStart: !wizard.active && !screensaver.covering && !ota.active && !cdrip.open && !dialogs.active
                                             && !remoteIntro.active && !remoteTour.active && app.lastInput > tutorialGaveUpAt
    property bool tutorialTried: false
    // A tour nobody looked at closes by itself (Tutorial.timedOut) without
    // being marked as shown: it is offered again at the next touch or key,
    // not straight away (that would only reopen it over the empty room and
    // keep the screensaver off again).
    property real tutorialGaveUpAt: -1
    Connections {
        target: tutorial
        function onTimedOut() { app.tutorialGaveUpAt = Sys.now(); app.tutorialTried = false }
    }
    // 🚨 At the end of the first setup both the touch tour and a remote's key
    // map want the screen (a remote paired from the web wizard is already
    // there): the map came first by a few hundred ms and the tour opened on
    // top of it. One after the other: the tour, then the map and the practice.
    readonly property bool tutorialPending: !tutorialTried && !tutorial.wasShown()
    onTutorialCanStartChanged: if (tutorialCanStart && !tutorialTried) tutorialDelay.restart()
    Timer {
        id: tutorialDelay
        interval: 1500
        onTriggered: {
            if (!app.tutorialCanStart || app.tutorialTried) return
            app.tutorialTried = true
            if (!tutorial.wasShown()) tutorial.start()
        }
    }
    function startTutorial() { tutorialTried = true; tutorial.start() }
    // The first start after the setup: the touch tour had not been shown yet
    // when the interface came up (read once — the tour writes its file as it
    // goes, and the remote's practice comes after it).
    property bool firstStart: false
    // 🚨 Trying the remote, one key at a time: ONLY after a known remote's
    // key map at the end of the first setup. Later (a remote paired months
    // after, Settings) it was one more thing in the way: the key map and
    // "Try the keys" are there for that.
    function startRemoteTour(model) { if (firstStart) remoteTour.start(model || "") }
    // the tour's album steps: the list as a grid or as Cover Flow, whatever
    // the owner chose (put back when the tour ends), and the long-press menu
    function tutorialAlbums(mode) { setExpanded(false); albumView = mode; mainScreen.browser.tutorialAlbums(mode) }
    function tutorialListRect() { return mainScreen.browser.tutorialListRect() }
    function tutorialMenuRect() { return mainScreen.browser.tutorialMenuRect() }
    function tutorialRestore() { mainScreen.browser.closeMenu(); albumView = albumViewOf(Sys.conf("album-view", "grid")) }
    // the tour's home steps: the main screen, Music tab, at its home
    function tutorialHome() { setExpanded(false); mainScreen.browser.showMusicTab(); if (mainScreen.browser.view !== LibraryModel.Home) mainScreen.browser.navHome() }

    // Now Playing's artist and album lead to their pages in the library
    function openAlbum(id, title) { if (!id) return; setExpanded(false); mainScreen.browser.openAlbum(id, title) }
    function openArtist(id, name) { if (!id) return; setExpanded(false); mainScreen.browser.openArtist(id, name) }

    // ─── telecomando ───────────────────────────────────────────────────────
    // Da qui passano il telecomando (USB o Bluetooth, letto in remote.cpp) e
    // una tastiera attaccata: Remote traduce i tasti in azioni e questa
    // funzione decide cosa vuol dire ogni azione ADESSO. "Indietro" con un
    // dialogo aperto chiude il dialogo; nella libreria torna di un passo.
    // Le frecce non fanno cose diverse schermata per schermata: muovono il
    // riflettore (Nav.qml), e OK preme dove il riflettore si trova.
    Connections {
        target: Remote
        function onAction(name, repeat) { app.remote(name, repeat) }
    }
    // il dito ha la precedenza: appoggiarlo spegne il riflettore
    Connections { target: Sys; function onPointerTouched() { Nav.hide() } }

    function remote(a, repeat) {
        // col salvaschermo davanti, il primo tasto lo manda via e basta: chi
        // sveglia lo schermo non si aspetta che quel tasto apra anche qualcosa.
        // I tasti di riproduzione, invece, fanno anche il loro mestiere.
        if (screensaver.active) {
            screensaver.hide()
            if (a === "up" || a === "down" || a === "left" || a === "right" || a === "ok" ||
                a === "back" || a === "home" || a === "menu" || a === "standby" ||
                a === "pageUp" || a === "pageDown" || a === "search") return
        }
        // trying the remote: every key is the practice run's, none acts
        if (remoteTour.active) { remoteTour.handle(a); return }
        switch (a) {
        case "up": case "down": case "left": case "right": Nav.move(a); return
        case "pageUp": Nav.page("up"); return
        case "pageDown": Nav.page("down"); return
        case "ok": Nav.activate(false); return
        case "menu": Nav.activate(true); return            // come tenere il dito premuto
        case "back": remoteBack(); return
        case "home": remoteHome(); return
        case "playPause": if (!changerTakesPlay()) Player.togglePlay(); return
        case "play": if (!changerTakesPlay()) Player.play(true); return
        case "pause": Player.play(false); return
        case "stop": Player.cmd(["stop"]); return
        case "next": Player.next(); return
        case "prev": Player.prev(); return
        case "forward": Player.seek(Player.elapsed + 30); return
        case "rewind": Player.seek(Math.max(0, Player.elapsed - 30)); return
        case "volumeUp": remoteVolume(repeat ? 2 : 5); return
        case "volumeDown": remoteVolume(repeat ? -2 : -5); return
        case "mute":
            // volume fisso: toggleMute non fa nulla, e il riquadro mentirebbe
            if (Player.volumeFixed) return
            // toggleMute cambia `muted` subito (ottimista): qui c'e' gia' lo
            // stato NUOVO, e il riquadro dice quello
            Player.toggleMute()
            toast.say(Player.muted ? "volume-x" : "volume-2", Tr.t(Player.muted ? "player.muted" : "player.soundOn"))
            return
        case "nowPlaying": setExpanded(!expanded); return
        // Schermo intero: il player si apre da solo se era chiuso. Senza VU e
        // senza animazione non c'e' niente da mostrare grande, e il tasto tace.
        case "fullScreen":
            if (overlays.busy) overlays.close()
            if (!expanded) setExpanded(true)
            np.toggleStage()
            return
        // il prossimo skin dei VU / la prossima animazione, anche dalla
        // libreria: il riquadro dice il nome di quello che e' venuto su
        case "nextVu": if (Player.isOwn) np.cycleLook("vu"); return
        case "nextAnimation": np.cycleLook("anim"); return
        case "queue": if (overlays.busy) overlays.close(); else overlays.openQueue(); return
        case "search": setExpanded(false); mainScreen.browser.focusSearch(); return
        case "favorite": if (Player.favoritesAvailable) Player.toggleFavorite(); return
        case "openFavorites": remoteHome(); mainScreen.browser.openFavorites(); return
        // the power key: the restart / shut down menu, and pressed again it
        // goes away (the spotlight starts on Cancel: see Dialogs.navFirst)
        case "powerMenu":
            if (dialogs.active && dialogs.kind === 7) { dialogs.backdrop(); return }
            if (vk.active) vk.close(false)
            if (dialogs.active) dialogs.backdrop()
            mainScreen.browser.openPower()
            return
        // the touchscreen "unplugged and plugged back in" (api_server
        // reset_touchscreen): for a panel that stops answering the finger
        case "resetTouch":
            toast.say("refresh-cw", Tr.t("player.touchRestarting"))
            Api.post(Api.apiBase + "/touch/reset", {}, function(ok, d) {
                if (d && d.message) toast.say(ok && d.success !== false ? "check" : "x", d.message)
            }, 15000)
            return
        case "shuffle": Player.cycleShuffle(); return
        case "standby": screensaver.show(true); return
        case "eject": if (cdrip.haveDisc) cdrip.eject(); return
        }
    }
    // Il volume dal telecomando: un passo da 5, piu' corto a tasto tenuto
    // premuto (le ripetizioni arrivano otto al secondo). Il riquadro che
    // compare e' l'unico posto dove si vede il volume da qualunque schermata.
    function remoteVolume(d) {
        if (Player.volumeFixed) return
        var v = Math.max(0, Math.min(100, Player.volume + d))
        Player.setVolume(v)
        toast.say(v === 0 ? "volume-x" : "volume-2", v + "%")
    }
    // "Indietro": chiude quello che c'e' davanti, uno strato per volta
    function remoteBack() {
        if (vk.active) { vk.close(false); return }
        // like Escape and a tap outside: whoever opened the dialog hears it was
        // cancelled (a bare close() left them waiting, and the spotlight lost)
        if (dialogs.active) { dialogs.backdrop(); return }
        if (cdrip.open) { cdrip.close(); return }
        if (tutorial.active) { tutorial.finish(); return }
        if (remoteIntro.active) { remoteIntro.close(); return }
        if (remotePair.active) { remotePair.close(); return }
        if (overlays.busy) { overlays.close(); return }
        if (ota.active) { ota.dismissed = true; return }
        if (mainScreen.browser.menuOpen) { mainScreen.browser.closeMenu(); return }
        if (expanded) { setExpanded(false); return }
        mainScreen.browser.navBack()
    }
    // "Casa": la libreria, com'e' appena accesa
    function remoteHome() {
        if (vk.active) vk.close(false)
        if (dialogs.active) dialogs.close()
        if (overlays.busy) overlays.close()
        setExpanded(false)
        mainScreen.browser.showMusicTab()
        mainScreen.browser.navHome()                      // and the spotlight on the first tile
    }

    // per il canale di collaudo (eval): app.settings.openSection(n) ecc.
    readonly property var settings: Ui.settings
    readonly property var main: mainScreen
    readonly property var nowPlaying: np
    readonly property var dlg: dialogs
    readonly property var keyboard: vk
    readonly property var saver: screensaver
    readonly property var cd: cdrip
    readonly property var toastItem: toast
    readonly property var otaItem: ota
    readonly property var tour: tutorial
    readonly property var remoteMap: remoteIntro
    readonly property var pairWizard: remotePair
    readonly property var practice: remoteTour
    readonly property var nav: Nav                    // il riflettore del telecomando

    MainScreen {
        id: mainScreen
        anchors.fill: parent
        devScale: app.devicePixelScale
        visible: (!app.expanded || npSpring.running) && !wizard.active && !screensaver.covering
        shown: !app.expanded && !screensaver.covering
        onExpand: app.setExpanded(true)
        onOpenQueue: overlays.openQueue()
        onOpenSleep: overlays.openSleep()
        onOpenPlayerPicker: app.openPlayerPicker()
    }
    NowPlaying {
        id: np
        width: parent.width; height: parent.height
        y: npSpring.value * height
        visible: (app.expanded || npSpring.running) && !wizard.active && !screensaver.covering
        shown: app.expanded && !wizard.active && !screensaver.covering
        devScale: app.devicePixelScale
        viewVu: app.viewVu
        onCollapse: app.setExpanded(false)
        onOpenQueue: overlays.openQueue()
        onOpenSleep: overlays.openSleep()
        onOpenPlayerPicker: app.openPlayerPicker()
        onStartScreensaver: screensaver.show(true)
        onToggleView: { app.viewVu = !app.viewVu; Sys.setConf("nowplaying-view", app.viewVu ? "vu" : "lyrics") }
        // the BitPerfect / ReplayGain lights open Settings → Playback on that setting
        onOpenSettings: { app.setExpanded(false); mainScreen.browser.openTab(4) }
        onOpenPlaybackSetting: (which) => {
            app.setExpanded(false)
            mainScreen.browser.openTab(4)
            Ui.settings.openSection("playback", which)
        }
    }
    // Mentre le schermate scorrono i riquadri sotto il dito non sono quelli
    // disegnati: si lascia finire la molla (ui_transition_active).
    MouseArea { anchors.fill: parent; enabled: npSpring.running; onPressed: (m) => m.accepted = true }

    Overlays {
        id: overlays
        covered: screensaver.covering
        anchors.fill: parent
        onSavedPlaylist: { app.setExpanded(false); mainScreen.showPlaylists() }
    }

    // Auto-apertura del player (nowplaying-autoexpand) come main_tick()
    QtObject {
        id: autoexpand
        property bool armed: false
        property string key: ""
        property real since: 0
    }
    Connections {
        target: Player
        function onControlsChanged() {
            if (Player.playing && !autoexpand.armed) { autoexpand.armed = true; autoexpand.key = ""; autoexpand.since = Sys.now() }
            if (!Player.playing) autoexpand.armed = false
        }
        function onMetaChanged() { if (Player.playing) autoexpand.since = Sys.now() }
        function onUsbMounted(label) { if (!wizard.active) toast.show(label) }
    }
    Timer {
        interval: 500; repeat: true
        // only for this device's own playback: a phone across the house
        // changing track is no reason to pop the player open (#99)
        running: Player.autoexpandSecs > 0 && Player.playing && !app.expanded && Player.connected && Player.isOwn && !wizard.active && !tutorial.active
        onTriggered: {
            if (mainScreen.browsing) return
            var key = Player.title + "|" + Player.artist + "|" + Player.album
            if (key === autoexpand.key) return
            var since = Sys.now() - Math.max(autoexpand.since || 0, app.lastInput)
            if (since >= Player.autoexpandSecs * 1000) { autoexpand.key = key; app.setExpanded(true) }
        }
    }

    // ─── strati sovrapposti ────────────────────────────────────────────────
    Wizard { id: wizard; anchors.fill: parent; devScale: app.devicePixelScale }
    Dialogs { id: dialogs; anchors.fill: parent }
    OtaOverlay { id: ota; anchors.fill: parent }
    CdRip { id: cdrip; anchors.fill: parent }
    FolderChooser { id: folderChooser; anchors.fill: parent }
    Tutorial {                                             // the guided tours, over everything but the saver
        id: tutorial; anchors.fill: parent
        onEnded: remoteIntro.check()                       // another known remote may be waiting for its map
    }
    // the key map of a known remote, once, after it is paired
    RemoteIntro {
        id: remoteIntro; anchors.fill: parent
        blocked: wizard.active || screensaver.covering || dialogs.active || vk.active || ota.active || cdrip.open
                 || tutorial.active || remoteTour.active || remotePair.active || app.tutorialPending
        onTourWanted: (m) => app.startRemoteTour(m)
    }
    // "add a remote", from Settings → Remote control
    RemotePairWizard { id: remotePair; anchors.fill: parent }
    // the practice run: every remote key comes here first while it is open
    RemoteTour {
        id: remoteTour; anchors.fill: parent
        onEnded: remoteIntro.check()                       // another known remote may be waiting for its map
    }
    Toast { id: toast; anchors.fill: parent }             // z-[10050]: sopra CD (z-70) e aggiornamento
    VirtualKeyboard { id: vk; anchors.fill: parent }
    Screensaver {
        id: screensaver
        anchors.fill: parent
        // un minuto senza tocchi e niente in riproduzione (era 5, come App.jsx)
        idleMs: 60 * 1000
        lastInput: app.lastInput
        blocked: wizard.active || app.busyOverlay
    }
}
