// Rilevamento del CD e copia su disco (CdRip.jsx / cdrip.c): lo stato e la
// finestra stanno qui; la fascia in cima alla scheda Musica e' CdBanner.
// A disc that goes in is asked about once, in a large Yes / No window over
// everything (`asking`); Yes opens the rip window, No leaves the disc alone.
// From then on the rip is in Settings → CD ripping (ripNow()), always.
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
    // the disc's track numbers, beside `tracks`, and which of them get ripped
    // (all of them for a new disc; untick the ones to leave out)
    property var nums: []
    property var picked: []
    readonly property int pickedCount: { var n = 0; for (var i = 0; i < picked.length; i++) if (picked[i]) n++; return n }
    function togglePick(i) { var p = picked.slice(); p[i] = !p[i]; picked = p }
    function pickAll(on) { picked = tracks.map(function() { return on }) }
    // the MusicBrainz releases the disc may be (/api/cd/info `releases`), the
    // one in use and the one picked by hand; picking refills artist, album and
    // titles from that release
    property var releases: []
    property string release: ""
    property string pickedRelease: ""
    property bool refill: false
    property var dests: []              // [{id,name}]
    property int destSel: 0
    // the folder picked in the browser below (absolute); "" = dests[destSel]
    property string destPath: ""
    property string defaultTargetPath: ""
    property string state: ""
    property string msg: ""
    property int progress: 0
    property int curTrack: 0
    property int total: 0
    property bool ripping: false
    property string err: ""
    property bool open: false
    property bool closing: false
    // Settings → CD ripping → Enable: off, the disc is ignored altogether
    property bool enabled: true
    // the Yes / No question for a disc that just went in
    property bool asking: false
    // set by App.qml: the first-run wizard, a tour or an update is on screen
    property bool blocked: false
    property string autoStart: "off"
    property string mbid: ""
    // sources_server starts this one by itself (cd_monitor): nothing to ask
    readonly property bool autoWillStart: autoStart === "always" || (autoStart === "if_tags" && mbid !== "")
    // 🚨 Once per insertion: `dismissed` takes the disc as soon as it is
    // asked about, and is cleared only when the drive reports no disc — not
    // on a failed poll, or a hiccup would ask again.
    readonly property bool wantAsk: haveDisc && enabled && discid !== "" && discid !== dismissed && !ripping
                                    && !autoWillStart && !open && !blocked && (state === "" || state === "idle")
    onWantAskChanged: if (wantAsk) ask()
    onHaveDiscChanged: if (!haveDisc && asking) close()
    // the strip on the Music tab: only while a rip runs, or to eject after it
    // (its own close, `bannerClosed`, is only for that last case)
    property string bannerClosed: ""
    readonly property bool bannerVisible: enabled && (ripping || (haveDisc && discid !== bannerClosed
                                          && (state === "done" || state === "error" || state === "cancelled")))
    // where the remote's spotlight starts: on Yes
    readonly property Item navFirst: asking ? yesTap : null
    anchors.fill: parent
    visible: open
    // il telecomando resta qui dentro finche' questo strato e' aperto
    NavScope { active: root.open && !root.closing }
    Component.onCompleted: Ui.cdrip = root

    Spring { id: sc; stiffness: 550; damping: 30; rate: Theme.motionRate }
    property real fade: 0
    Behavior on fade { NumberAnimation { duration: Theme.dur(300); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
    property real closeScale: 1
    Behavior on closeScale { NumberAnimation { duration: Theme.dur(200) } }

    function loadInfo() {
        Api.get(Api.srcBase + "/api/cd/info" + (pickedRelease ? "?release=" + encodeURIComponent(pickedRelease) : ""), function(ok, d) {
            // disco tolto: lo stato della copia precedente non vale piu', e il
            // prossimo disco dev'essere trattato come nuovo
            if (!ok || !d || typeof d !== "object" || d.no_disc) {
                if (ok && d && d.no_disc) root.dismissed = ""
                root.haveDisc = false
                if (!root.ripping) { root.discid = ""; root.state = ""; root.msg = "" }
                return
            }
            var id = String(d.discid || "")
            if (id !== root.discid && root.discid !== "") root.pickedRelease = ""
            root.releases = d.releases || []
            if (id !== root.discid || root.refill) {
                root.refill = false
                root.discid = id
                root.release = String(d.mbid || "")
                root.artist = String(d.artist || ""); root.album = String(d.album || "")
                root.tracks = (d.tracks || []).map(function(t) { return String(t.title || "") }).slice(0, 40)
                root.nums = (d.tracks || []).map(function(t, i) { return Number(t.num || (i + 1)) }).slice(0, 40)
                root.pickAll(true)
                root.destSel = 0
                // 🚨 disco NUOVO: si azzera l'esito della copia precedente. Senza
                // questo, dopo una copia riuscita lo stato restava "done" per
                // sempre (l'interrogazione si ferma a fine copia) e cambiando CD
                // compariva la schermata "gia' copiato" invece dell'elenco brani.
                root.state = ""; root.msg = ""; root.progress = 0; root.curTrack = 0; root.total = 0
                root.ripping = false
            }
            // the folder from Settings → CD ripping first, then the writable sources
            var dl = (d.destinations || []).map(function(x) { return { id: String(x.source_id || ""), name: String(x.name || ""), path: String(x.path || "") } })
            if (d.default_target && d.default_target.path) dl.unshift({ id: "__default__", name: String(d.default_target.name || d.default_target.path) })
            root.dests = dl
            root.defaultTargetPath = d.default_target && d.default_target.path ? String(d.default_target.path) : ""
            root.enabled = d.enabled !== false
            root.autoStart = String(d.auto_start || "off")
            root.mbid = String(d.mbid || "")
            root.haveDisc = true
            if (d.ripping) root.ripping = true
        }, 5000)
    }
    function loadStatus() {
        Api.get(Api.srcBase + "/api/cd/rip/status", function(ok, d) {
            if (!ok || !d || typeof d !== "object") { root.ripping = false; return }
            root.state = String(d.state || "idle"); root.msg = String(d.message || "")
            root.progress = Number(d.progress || 0); root.curTrack = Number(d.track || 0); root.total = Number(d.total || 0)
            root.ripping = root.state !== "done" && root.state !== "error" && root.state !== "idle" && root.state !== "cancelled"
        }, 5000)
    }
    // 🚨 Ogni /api/cd/info fa girare cd-discid: senza lettore (quasi tutti gli
    // apparecchi) non si chiede nulla. Il lettore si guarda da qui, con una
    // stat di /dev/cdrom (il link della regola udev 99-hifi-cdrom, lo stesso
    // che usa sources_server) a ogni giro: uno USB attaccato dopo si vede da
    // solo. La partenza automatica la fa sources_server (cd_monitor): qui
    // arriva come `ripping` alla prima interrogazione.
    property bool hasDrive: false
    function checkDrive() {
        hasDrive = Sys.exists("/dev/cdrom") || Sys.exists("/dev/sr0")
        // lettore staccato: il disco non c'e' piu'
        if (!hasDrive && haveDisc) {
            haveDisc = false; dismissed = ""
            if (!ripping) { discid = ""; state = ""; msg = "" }
        }
        return hasDrive
    }
    Timer { interval: 7000; repeat: true; running: true; triggeredOnStart: true; onTriggered: if (root.checkDrive() || root.ripping) root.loadInfo() }
    Timer { interval: 2000; repeat: true; running: root.ripping; onTriggered: root.loadStatus() }

    function openDialog() { open = true; closing = false; sc.set(0.94); sc.to = 1; closeScale = 1; fade = 1 }
    function close() { if (!open || closing) return; closing = true; closeScale = 0.94; fade = 0 }
    Timer { interval: 40; repeat: true; running: root.closing; onTriggered: if (root.fade === 0) { root.open = false; root.closing = false; root.asking = false } }
    function dismissBanner() { bannerClosed = discid }
    function ask() { dismissed = discid; asking = true; openDialog() }
    // Settings → CD ripping → "Rip the CD": the rip window for the disc in the
    // drive, whatever was answered when it went in. cb(result): "ok",
    // "noDrive", "noDisc" or "disabled".
    function ripNow(cb) {
        if (!checkDrive()) { if (cb) cb("noDrive"); return }
        if (ripping) { asking = false; openDialog(); if (cb) cb("ok"); return }
        Api.get(Api.srcBase + "/api/cd/info", function(ok, d) {
            if (!ok || !d || typeof d !== "object" || d.no_disc) { if (cb) cb("noDisc"); return }
            if (d.enabled === false) { if (cb) cb("disabled"); return }
            root.dismissed = String(d.discid || "")
            root.loadInfo()
            root.asking = false
            root.openDialog()
            if (cb) cb("ok")
        }, 5000)
    }
    // ── the destination: the kiosk's folder chooser (FolderChooser.qml), the
    // same navigator Music sources and the playlist folder use ─────────────
    function openBrowser() {
        var start = destPath || defaultTargetPath
        if (!start) for (var i = 0; i < dests.length; i++) if (dests[i].path) { start = dests[i].path; break }
        if (Ui.folderChooser) Ui.folderChooser.openAt(start, Tr.t("sources.useThisFolder"), function(p) { root.destPath = p })
    }
    // Cancel: the worker stops, removes what it had read, and the disc can be ejected
    function cancelRip() { Api.post(Api.srcBase + "/api/cd/cancel", {}, function() { root.loadStatus() }) }
    function eject() { Api.post(Api.srcBase + "/api/cd/eject", {}, function() { root.loadStatus() }); haveDisc = false; state = ""; close() }
    function releaseLabel(r) {
        if (!r) return ""
        return [Meta.date(r.date), r.country, [r.label, r.catno].filter(function(x) { return !!x }).join(" "),
                r.track_count ? Tr.tf("player.page.editionTracks", "count", String(r.track_count)) : "",
                Number(r.disc_count) > 1 ? Tr.tf("player.cd.editionDisc", "n", String(r.disc_position)).replace("{total}", String(r.disc_count)) : ""]
               .filter(function(x) { return !!x }).join(" · ")
    }
    function pickRelease() {
        var cur = -1
        for (var i = 0; i < releases.length; i++) if (String(releases[i].mbid) === release) cur = i
        Ui.dialogs.pick(Tr.t("player.cd.edition"), releases.map(function(r) { return (r.title || "") + " — " + releaseLabel(r) }), cur, function(i) {
            if (i < 0 || i >= root.releases.length) return
            root.pickedRelease = String(root.releases[i].mbid)
            root.refill = true
            root.loadInfo()
        })
    }
    function startRip() {
        if ((!dests.length && !destPath) || !pickedCount) return
        var sel = []
        for (var i = 0; i < nums.length; i++) if (picked[i]) sel.push(nums[i])
        var body = { artist: artist, album: album, tracks: tracks, selected: sel }
        if (destPath) body.target = destPath
        else body.source_id = dests[destSel].id
        if (release) body.release = release
        Api.post(Api.srcBase + "/api/cd/rip", body, function() { root.loadStatus() })
        state = "starting"; ripping = true; total = sel.length
    }

    Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0, 0, 0.7 * root.fade); MouseArea { anchors.fill: parent; onClicked: if (!root.ripping) root.close() } }
    // ── the question, when a disc goes in ─────────────────────────────────
    Rectangle {
        id: askCard
        visible: root.asking
        width: Math.min(560, root.width - 48); height: askCol.implicitHeight + 64
        anchors.centerIn: parent
        radius: 16; color: Theme.panel; border.width: 1; border.color: Theme.border
        opacity: root.fade; scale: sc.value * root.closeScale
        BoxShadow { z: -1; targetX: 0; targetY: 0; targetW: parent.width; targetH: parent.height; radius: 16; blur: 50; spread: -12; offsetY: 25; color: Theme.blackA(0.25) }
        MouseArea { anchors.fill: parent }
        Column {
            id: askCol
            x: 32; y: 32; width: parent.width - 64; spacing: 16
            Icon { anchors.horizontalCenter: parent.horizontalCenter; name: "disc"; size: 56; color: Theme.gold }
            Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; text: Tr.t("player.cd.askTitle"); color: Theme.white; font.family: Theme.font; font.pixelSize: 22; font.bold: true }
            Text {
                width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight
                text: root.artist || root.album ? [root.artist, root.album].filter(function(x) { return !!x }).join(" — ")
                                                : Tr.tf("player.cd.askTracks", "count", String(root.tracks.length))
                color: Theme.silver; font.family: Theme.font; font.pixelSize: 16
            }
            Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; text: Tr.t("player.cd.askQuestion"); color: Theme.white; font.family: Theme.font; font.pixelSize: 18 }
            Item { width: 1; height: 4 }
            Row {
                width: parent.width; spacing: 12
                Rectangle {
                    width: (parent.width - 12) / 2; height: 56; radius: 10; color: noTap.mix(Theme.accent, Theme.dark)
                    Text { anchors.centerIn: parent; text: Tr.t("player.cd.askNo"); color: Theme.white; font.family: Theme.font; font.pixelSize: 18 }
                    Tap { id: noTap; onClicked: root.close() }
                }
                Rectangle {
                    width: (parent.width - 12) / 2; height: 56; radius: 10; color: yesTap.mix(Theme.gold, "#ca8a04")
                    Text { anchors.centerIn: parent; text: Tr.t("player.cd.askYes"); color: Theme.black; font.family: Theme.font; font.pixelSize: 18; font.bold: true }
                    Tap { id: yesTap; onClicked: root.asking = false }
                }
            }
            Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; text: Tr.t("player.cd.askLater"); color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 12 }
        }
    }
    Rectangle {
        id: card
        visible: !root.asking
        width: Math.min(512, root.width - 48); height: root.height * 0.85
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
            Text { visible: root.state === "error" || root.state === "cancelled"; x: 24; y: parent.cy + 16; width: parent.width - 48; wrapMode: Text.Wrap; maximumLineCount: 2; horizontalAlignment: Text.AlignHCenter; text: root.state === "cancelled" ? Tr.t("player.cd.cancelled") : (root.msg || Tr.t("player.cd.ripError")); color: root.state === "cancelled" ? Theme.silver : Theme.red300; font.family: Theme.font; font.pixelSize: 14 }
            // Eject after the rip, however it ended: a drive without its own
            // button has no other way to give the disc back after a failure
            Rectangle {
                visible: root.state === "done" || root.state === "error" || root.state === "cancelled"
                x: 20; y: parent.height - 20 - 42; width: parent.width - 40; height: 42; radius: 8; color: ejTap.mix(Theme.gold, "#ca8a04")
                Text { anchors.centerIn: parent; text: Tr.t("player.cd.eject"); color: Theme.black; font.family: Theme.font; font.pixelSize: 14; font.bold: true }
                Tap { id: ejTap; onClicked: root.eject() }
            }
            Rectangle {
                visible: root.ripping
                x: 20; y: parent.height - 20 - 42; width: parent.width - 40; height: 42; radius: 8; color: cxTap.mix(Theme.light, Theme.accent)
                Text { anchors.centerIn: parent; text: Tr.t("player.cd.cancel"); color: Theme.white; font.family: Theme.font; font.pixelSize: 14 }
                Tap { id: cxTap; onClicked: root.cancelRip() }
            }
        }
        // ── impostazione ────────────────────────────────────────────────────
        Item {
            visible: !card.busyView
            anchors.fill: parent
            readonly property real foot: 20 + 42 + 12 + (root.dests.length ? 40 : 24)
            TextField_ { x: 20; y: 52; width: (parent.width - 40 - 8) / 2; height: 36; textSize: 14; padding: 12; restBorder: Theme.accent; text: root.artist; placeholder: Tr.t("player.cd.artist"); onTextEdited: (t) => root.artist = t }
            TextField_ { x: 20 + (parent.width - 40 - 8) / 2 + 8; y: 52; width: (parent.width - 40 - 8) / 2; height: 36; textSize: 14; padding: 12; restBorder: Theme.accent; text: root.album; placeholder: Tr.t("player.cd.album"); onTextEdited: (t) => root.album = t }
            // which edition the tags come from, when MusicBrainz knows more than one
            Rectangle {
                id: relRow
                visible: root.releases.length > 1
                x: 20; y: 96; width: parent.width - 40; height: 34; radius: 8
                color: Theme.dark; border.width: 1; border.color: Theme.accent
                Text { id: relLab; x: 10; anchors.verticalCenter: parent.verticalCenter; text: Tr.t("player.cd.edition"); color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 12 }
                Text {
                    x: relLab.x + relLab.implicitWidth + 8; width: parent.width - x - 30; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight
                    text: { for (var i = 0; i < root.releases.length; i++) if (String(root.releases[i].mbid) === root.release) return root.releaseLabel(root.releases[i]); return "" }
                    color: Theme.white; font.family: Theme.font; font.pixelSize: 12
                }
                Icon { x: parent.width - 24; anchors.verticalCenter: parent.verticalCenter; name: "chevron-down"; size: 16; color: Theme.silver }
                Tap { onClicked: root.pickRelease() }
            }
            // how many are ticked, and one tap to tick or untick them all
            Item {
                id: pickRow
                x: 20; y: relRow.visible ? 138 : 96; width: parent.width - 40; height: 28
                Text { anchors.verticalCenter: parent.verticalCenter; text: Tr.tf("player.cd.pickedCount", "n", String(root.pickedCount)).replace("{total}", String(root.tracks.length)); color: Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 12 }
                Text {
                    id: pickAllText
                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    text: Tr.t(root.pickedCount === root.tracks.length ? "player.cd.pickNone" : "player.cd.pickAll")
                    color: Theme.gold; font.family: Theme.font; font.pixelSize: 12; font.bold: true
                    Tap { grow: 8; onClicked: root.pickAll(root.pickedCount !== root.tracks.length) }
                }
            }
            ListView {
                id: trackList
                x: 20; y: pickRow.y + pickRow.height + 4; width: parent.width - 40; height: parent.height - y - parent.foot
                clip: true; model: root.tracks.length
                boundsBehavior: Flickable.StopAtBounds
                delegate: Item {
                    required property int index
                    width: trackList.width; height: 32
                    readonly property bool on: !!root.picked[index]
                    // the tick: the track is ripped
                    Rectangle {
                        x: 0; y: 4; width: 20; height: 20; radius: 4
                        color: parent.on ? Theme.gold : "transparent"; border.width: 1; border.color: parent.on ? Theme.gold : Theme.silverA(0.4)
                        Icon { anchors.centerIn: parent; visible: parent.parent.on; name: "check"; size: 14; color: Theme.black }
                        Tap { grow: 6; onClicked: root.togglePick(index) }
                    }
                    Text { x: 24; width: 22; height: 28; horizontalAlignment: Text.AlignRight; verticalAlignment: Text.AlignVCenter; text: String(root.nums[index] || index + 1); color: Theme.silverA(parent.on ? 0.5 : 0.25); font.family: Theme.mono; font.pixelSize: 11 }
                    TextField_ {
                        x: 52; width: parent.width - 52; height: 28; radius: 4; textSize: 12; padding: 8; restBorder: Theme.border
                        opacity: parent.on ? 1 : 0.4
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
                    Text { x: 10; width: parent.width - 38; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideMiddle; text: root.destPath || (root.dests.length ? root.dests[root.destSel].name : ""); color: Theme.white; font.family: Theme.font; font.pixelSize: 14 }
                    Icon { x: parent.width - 24; anchors.verticalCenter: parent.verticalCenter; name: "folder"; size: 16; color: Theme.silver }
                    Tap { onClicked: root.openBrowser() }
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
                opacity: root.dests.length && root.pickedCount ? 1 : 0.4   // disabled:opacity-40 su tutto, testo compreso
                Text { anchors.centerIn: parent; text: Tr.t("player.cd.start"); color: Theme.black; font.family: Theme.font; font.pixelSize: 14; font.bold: true }
                Tap { id: stTap; enabled: root.dests.length > 0 && root.pickedCount > 0; onClicked: root.startRip() }
            }
        }
    }
}
