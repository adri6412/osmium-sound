// Rilevamento del CD e copia su disco (CdRip.jsx / cdrip.c): lo stato e la
// finestra stanno qui; la fascia in cima alla scheda Musica e' CdBanner.
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    property bool haveDisc: false
    property string discid: ""
    property string dismissed: ""
    property string artist: ""
    property string album: ""
    property var tracks: []
    property var dests: []              // [{id,name}]
    property int destSel: 0
    property string state: ""
    property string msg: ""
    property int progress: 0
    property int curTrack: 0
    property int total: 0
    property bool ripping: false
    property string err: ""
    property bool open: false
    property bool closing: false
    readonly property bool bannerVisible: haveDisc && discid !== dismissed
    anchors.fill: parent
    visible: open
    Component.onCompleted: Ui.cdrip = root

    Spring { id: sc; stiffness: 550; damping: 30 }
    property real fade: 0
    Behavior on fade { NumberAnimation { duration: 300; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
    property real closeScale: 1
    Behavior on closeScale { NumberAnimation { duration: 200 } }

    function loadInfo() {
        Api.get(Api.srcBase + "/api/cd/info", function(ok, d) {
            // disco tolto: lo stato della copia precedente non vale piu', e il
            // prossimo disco dev'essere trattato come nuovo
            if (!ok || !d || typeof d !== "object" || d.no_disc) {
                root.haveDisc = false
                if (!root.ripping) { root.discid = ""; root.state = ""; root.msg = "" }
                return
            }
            var id = String(d.discid || "")
            if (id !== root.discid) {
                root.discid = id
                root.artist = String(d.artist || ""); root.album = String(d.album || "")
                root.tracks = (d.tracks || []).map(function(t) { return String(t.title || "") }).slice(0, 40)
                root.destSel = 0
                // 🚨 disco NUOVO: si azzera l'esito della copia precedente. Senza
                // questo, dopo una copia riuscita lo stato restava "done" per
                // sempre (l'interrogazione si ferma a fine copia) e cambiando CD
                // compariva la schermata "gia' copiato" invece dell'elenco brani.
                root.state = ""; root.msg = ""; root.progress = 0; root.curTrack = 0; root.total = 0
                root.ripping = false
            }
            root.dests = (d.destinations || []).map(function(x) { return { id: String(x.source_id || ""), name: String(x.name || "") } })
            root.haveDisc = true
            if (d.ripping) root.ripping = true
        }, 5000)
    }
    function loadStatus() {
        Api.get(Api.srcBase + "/api/cd/rip/status", function(ok, d) {
            if (!ok || !d || typeof d !== "object") { root.ripping = false; return }
            root.state = String(d.state || "idle"); root.msg = String(d.message || "")
            root.progress = Number(d.progress || 0); root.curTrack = Number(d.track || 0); root.total = Number(d.total || 0)
            root.ripping = root.state !== "done" && root.state !== "error" && root.state !== "idle"
        }, 5000)
    }
    Timer { interval: 7000; repeat: true; running: true; triggeredOnStart: true; onTriggered: root.loadInfo() }
    Timer { interval: 2000; repeat: true; running: root.ripping; onTriggered: root.loadStatus() }

    function openDialog() { open = true; closing = false; sc.set(0.94); sc.to = 1; closeScale = 1; fade = 1 }
    function close() { if (!open || closing) return; closing = true; closeScale = 0.94; fade = 0 }
    Timer { interval: 40; repeat: true; running: root.closing; onTriggered: if (root.fade === 0) { root.open = false; root.closing = false } }
    function dismissBanner() { dismissed = discid }
    function eject() { Api.post(Api.srcBase + "/api/cd/eject", {}, function() { root.loadStatus() }); haveDisc = false; state = ""; close() }
    function startRip() {
        if (!dests.length) return
        Api.post(Api.srcBase + "/api/cd/rip", { source_id: dests[destSel].id, artist: artist, album: album, tracks: tracks }, function() { root.loadStatus() })
        state = "starting"; ripping = true; total = tracks.length
    }

    Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0, 0, 0.7 * root.fade); MouseArea { anchors.fill: parent; onClicked: if (!root.ripping) root.close() } }
    Rectangle {
        id: card
        width: Math.min(512, 1024 - 48); height: 600 * 0.85
        anchors.centerIn: parent
        radius: 16; color: Theme.panel; border.width: 1; border.color: Theme.border
        opacity: root.fade; scale: sc.value * root.closeScale
        BoxShadow { z: -1; targetX: 0; targetY: 0; targetW: parent.width; targetH: parent.height; radius: 16; blur: 50; spread: -12; offsetY: 25; color: Theme.blackA(0.25) }   // shadow-2xl
        MouseArea { anchors.fill: parent }
        Icon { x: 20; y: 22; name: "disc"; size: 16; color: Theme.gold }
        Text { x: 44; y: 16; height: 28; verticalAlignment: Text.AlignVCenter; text: Tr.t("player.cd.ripTitle"); color: Theme.white; font.family: Theme.font; font.pixelSize: 14; font.bold: true }
        Item {
            visible: !root.ripping
            x: parent.width - 20 - 28; y: 16; width: 28; height: 28
            Icon { anchors.centerIn: parent; name: "x"; size: 16; color: Theme.silverA(0.6) }
            Tap { grow: 6; onClicked: root.close() }
        }
        readonly property bool busyView: root.state !== "" && root.state !== "idle"
        // ── avanzamento / esito ────────────────────────────────────────────
        Item {
            visible: card.busyView
            anchors.fill: parent
            readonly property real cy: height / 2
            // in Electron e' l'icona Disc di lucide (40 px, oro) che gira in 2 s, non un anello
            Icon {
                visible: root.ripping; x: parent.width / 2 - 20; y: parent.cy - 100; name: "disc"; size: 40; color: Theme.gold
                RotationAnimation on rotation { from: 0; to: 360; duration: 2000; loops: Animation.Infinite; running: root.open && root.ripping }
            }
            Text { x: 24; y: parent.cy - 30; width: parent.width - 48; height: 36; wrapMode: Text.Wrap; maximumLineCount: 2; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; text: root.msg; color: Theme.white; font.family: Theme.font; font.pixelSize: 14 }
            Rectangle {
                visible: root.ripping
                x: 40; y: parent.cy + 16; width: parent.width - 80; height: 8; radius: 4; color: Theme.wa(0.1)
                Rectangle { width: parent.width * Math.max(0, Math.min(100, root.progress)) / 100; height: 8; radius: 4
                            gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: Theme.gold } GradientStop { position: 1; color: Theme.yellow400 } } }   // from-hifi-gold to-yellow-400
            }
            Text { visible: root.ripping; width: parent.width; y: parent.cy + 32; height: 18; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; text: Tr.tf("player.cd.ripProgress", "track", String(root.curTrack)).replace("{total}", String(root.total)); color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 12 }
            Text { visible: root.state === "done"; width: parent.width; y: parent.cy + 16; height: 24; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; text: Tr.t("player.cd.ripDone"); color: "#34d399"; font.family: Theme.font; font.pixelSize: 14 }
            Text { visible: root.state === "error"; x: 24; y: parent.cy + 16; width: parent.width - 48; wrapMode: Text.Wrap; maximumLineCount: 2; horizontalAlignment: Text.AlignHCenter; text: root.msg || Tr.t("player.cd.ripError"); color: Theme.red300; font.family: Theme.font; font.pixelSize: 14 }
            Rectangle {
                visible: root.state === "done"
                x: 20; y: parent.height - 20 - 42; width: parent.width - 40; height: 42; radius: 8; color: ejTap.mix(Theme.gold, "#ca8a04")
                Text { anchors.centerIn: parent; text: Tr.t("player.cd.eject"); color: Theme.black; font.family: Theme.font; font.pixelSize: 14; font.bold: true }
                Tap { id: ejTap; onClicked: root.eject() }
            }
        }
        // ── impostazione ────────────────────────────────────────────────────
        Item {
            visible: !card.busyView
            anchors.fill: parent
            readonly property real foot: 20 + 42 + 12 + (root.dests.length ? 40 : 24)
            TextField_ { x: 20; y: 52; width: (parent.width - 40 - 8) / 2; height: 36; textSize: 14; padding: 12; restBorder: Theme.accent; text: root.artist; placeholder: Tr.t("player.cd.artist"); onTextEdited: (t) => root.artist = t }
            TextField_ { x: 20 + (parent.width - 40 - 8) / 2 + 8; y: 52; width: (parent.width - 40 - 8) / 2; height: 36; textSize: 14; padding: 12; restBorder: Theme.accent; text: root.album; placeholder: Tr.t("player.cd.album"); onTextEdited: (t) => root.album = t }
            ListView {
                id: trackList
                x: 20; y: 96; width: parent.width - 40; height: parent.height - 96 - parent.foot
                clip: true; model: root.tracks.length
                boundsBehavior: Flickable.StopAtBounds
                delegate: Item {
                    required property int index
                    width: trackList.width; height: 32
                    Text { width: 24; height: 28; horizontalAlignment: Text.AlignRight; verticalAlignment: Text.AlignVCenter; text: String(index + 1); color: Theme.silverA(0.5); font.family: Theme.mono; font.pixelSize: 11 }
                    TextField_ {
                        x: 32; width: parent.width - 32; height: 28; radius: 4; textSize: 12; padding: 8; restBorder: Theme.border
                        text: root.tracks[index] || ""
                        onTextEdited: (t) => { var tr = root.tracks.slice(); tr[index] = t; root.tracks = tr }
                    }
                }
            }
            Text { visible: !root.dests.length; x: 20; y: parent.height - parent.foot + 4; height: 36; verticalAlignment: Text.AlignVCenter; text: Tr.t("player.cd.noDestination"); color: Qt.rgba(252 / 255, 211 / 255, 77 / 255, 0.9); font.family: Theme.font; font.pixelSize: 12 }
            Item {
                visible: root.dests.length > 0
                x: 20; y: parent.height - parent.foot + 4; width: parent.width - 40; height: 36
                Icon { x: 0; anchors.verticalCenter: parent.verticalCenter; name: "hard-drive"; size: 14; color: Theme.silverA(0.6) }
                Rectangle {
                    x: 22; width: parent.width - 22; height: 36; radius: 8; color: Theme.dark; border.width: 1; border.color: Theme.accent
                    Text { x: 10; width: parent.width - 38; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; text: root.dests.length ? root.dests[root.destSel].name : ""; color: Theme.white; font.family: Theme.font; font.pixelSize: 14 }
                    Icon { x: parent.width - 24; anchors.verticalCenter: parent.verticalCenter; name: "chevron-down"; size: 16; color: Theme.silver }
                    Tap { onClicked: Ui.dialogs.pick(Tr.t("player.cd.ripTitle"), root.dests.map(function(d) { return d.name }), root.destSel, function(i) { if (i >= 0) root.destSel = i }) }
                }
            }
            Text { visible: root.err !== ""; x: 20; y: parent.height - parent.foot + 42; height: 16; text: root.err; color: Theme.red300; font.family: Theme.font; font.pixelSize: 12 }
            Rectangle {
                id: ejectBtn
                x: 20; y: parent.height - 20 - 42; width: ejText.implicitWidth + 32; height: 42; radius: 8; color: ejTap2.mix(Theme.light, Theme.accent)
                Text { id: ejText; anchors.centerIn: parent; text: Tr.t("player.cd.eject"); color: Theme.white; font.family: Theme.font; font.pixelSize: 14 }
                Tap { id: ejTap2; onClicked: { Api.post(Api.srcBase + "/api/cd/eject", {}); root.haveDisc = false; root.close() } }
            }
            Rectangle {
                x: ejectBtn.x + ejectBtn.width + 8; y: ejectBtn.y; width: parent.width - 20 - x; height: 42; radius: 8
                color: stTap.mix(Theme.gold, "#ca8a04")
                opacity: root.dests.length ? 1 : 0.4              // disabled:opacity-40 su tutto, testo compreso
                Text { anchors.centerIn: parent; text: Tr.t("player.cd.start"); color: Theme.black; font.family: Theme.font; font.pixelSize: 14; font.bold: true }
                Tap { id: stTap; enabled: root.dests.length > 0; onClicked: root.startRip() }
            }
        }
    }
}
