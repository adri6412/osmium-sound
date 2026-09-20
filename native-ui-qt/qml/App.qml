// La tela 1024x600: le due schermate (principale e Now Playing) con la loro
// transizione, e sopra gli strati condivisi nello stesso ordine di app.c:
// coda / timer / salva playlist, intro di avvio, dialoghi, avviso USB,
// aggiornamento, copia CD, tastiera a schermo, salvaschermo.
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: app
    property real devicePixelScale: 1
    property bool expanded: false
    property bool viewVu: Sys.conf("nowplaying-view", "vu") !== "lyrics"
    // the albums of the library as a grid or as Cover Flow (a preference of
    // this screen, kept next to the Now Playing view)
    property string albumView: Sys.conf("album-view", "grid") === "coverflow" ? "coverflow" : "grid"
    function setAlbumView(v) { albumView = v === "coverflow" ? "coverflow" : "grid"; Sys.setConf("album-view", albumView) }
    // tempo dell'ultimo tocco (per l'auto-apertura e il salvaschermo)
    readonly property real lastInput: Sys.lastInput
    readonly property bool busyOverlay: dialogs.active || vk.active || ota.active || cdrip.open || tutorial.active

    // ─── principale <-> Now Playing: y:'100%' con molla 200/26 ─────────────
    Spring { id: npSpring; stiffness: 200; damping: 26 }
    function setExpanded(on) {
        if (expanded === on) return
        expanded = on
        npSpring.to = on ? 0 : 1
        if (on) autoexpand.armed = false
    }
    Component.onCompleted: {
        Ui.app = app; Ui.vk = vk; Ui.dialogs = dialogs; Ui.toast = toast; Ui.overlays = overlays
        npSpring.set(Sys.startExpanded ? 0 : 1)
        expanded = Sys.startExpanded
        if (tutorialCanStart) tutorialDelay.restart()      // no intro or wizard to wait for
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
    readonly property bool tutorialCanStart: !wizard.active && !intro.active && !screensaver.covering && !ota.active && !cdrip.open && !dialogs.active
    property bool tutorialTried: false
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
    // the tour's album steps: the list as a grid or as Cover Flow, whatever
    // the owner chose (put back when the tour ends), and the long-press menu
    function tutorialAlbums(mode) { setExpanded(false); albumView = mode; mainScreen.browser.tutorialAlbums(mode) }
    function tutorialListRect() { return mainScreen.browser.tutorialListRect() }
    function tutorialMenuRect() { return mainScreen.browser.tutorialMenuRect() }
    function tutorialRestore() { mainScreen.browser.closeMenu(); albumView = Sys.conf("album-view", "grid") === "coverflow" ? "coverflow" : "grid" }
    // the tour's home steps: the main screen, Music tab, at its home
    function tutorialHome() { setExpanded(false); mainScreen.browser.showMusicTab(); if (mainScreen.browser.view !== LibraryModel.Home) mainScreen.browser.navHome() }

    // Now Playing's artist and album lead to their pages in the library
    function openAlbum(id, title) { if (!id) return; setExpanded(false); mainScreen.browser.openAlbum(id, title) }
    function openArtist(id, name) { if (!id) return; setExpanded(false); mainScreen.browser.openArtist(id, name) }

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
    Tutorial { id: tutorial; anchors.fill: parent }       // the guided tour, over everything but the saver and the intro
    Toast { id: toast; anchors.fill: parent }             // z-[10050]: sopra CD (z-70) e aggiornamento
    VirtualKeyboard { id: vk; anchors.fill: parent }
    Screensaver {
        id: screensaver
        anchors.fill: parent
        // 5 minuti senza tocchi e niente in riproduzione (App.jsx)
        idleMs: 5 * 60 * 1000
        lastInput: app.lastInput
        blocked: wizard.active || app.busyOverlay
    }
    BootIntro { id: intro; anchors.fill: parent; devScale: app.devicePixelScale }
}
