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
    // tempo dell'ultimo tocco (per l'auto-apertura e il salvaschermo)
    readonly property real lastInput: Sys.lastInput
    readonly property bool busyOverlay: dialogs.active || vk.active || ota.active || cdrip.open

    // ─── principale <-> Now Playing: y:'100%' con molla 200/26 ─────────────
    Spring { id: npSpring; stiffness: 200; damping: 26 }
    function setExpanded(on) {
        if (expanded === on) return
        expanded = on
        npSpring.to = on ? 0 : 1
        if (on) autoexpand.armed = false
    }
    Component.onCompleted: {
        Ui.app = app; Ui.vk = vk; Ui.dialogs = dialogs; Ui.toast = toast
        npSpring.set(Sys.startExpanded ? 0 : 1)
        expanded = Sys.startExpanded
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

    MainScreen {
        id: mainScreen
        anchors.fill: parent
        devScale: app.devicePixelScale
        visible: (!app.expanded || npSpring.running) && !wizard.active && !screensaver.covering
        shown: !app.expanded && !screensaver.covering
        onExpand: app.setExpanded(true)
        onOpenQueue: overlays.openQueue()
        onOpenSleep: overlays.openSleep()
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
        onStartScreensaver: screensaver.show(true)
        onToggleView: { app.viewVu = !app.viewVu; Sys.setConf("nowplaying-view", app.viewVu ? "vu" : "lyrics") }
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
        running: Player.autoexpandSecs > 0 && Player.playing && !app.expanded && Player.connected && !wizard.active
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
