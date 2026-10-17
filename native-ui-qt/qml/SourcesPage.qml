// Settings → Music sources, redrawn around the PLACES the music lives in
// (the file-manager ideas of 2026-10-17): this appliance's system disk and
// its second disk, the USB sticks, the network shares. One card per place
// says whether it works, how much room is left and what it is used for —
// library, shared on the network, playlists, CD rips — instead of four bands
// that each told a piece of it. A card opens the page of its place, where
// every one of those uses is changed; "Add music" opens the wizard
// (AddMusicWizard.qml), a USB stick the copy wizard (ImportWizard.qml).
// Only what is connected and mounted is listed. Data and actions are the
// sources_server ones the old bands used.
import QtQuick
import Hifi
import Hifi.Ui

Rectangle {
    id: root
    color: Theme.dark
    signal back()

    // ── data ──────────────────────────────────────────────────────────────
    property var srcs: []           // /api/sources
    property var libPaths: []       // the folders Lyrion scans
    property var usbBad: []         // USB disks that could not be mounted
    property var disks: []          // internal disks (adopted or not)
    property var shares: []         // [{name, mountpoint, type, source_id}]
    property string smbHost: ""; property string smbIp: ""; property string smbUser: ""; property string smbPass: ""
    property string pldir: ""
    property var cd: ({})           // CD rip settings
    property var roots: []          // /api/local/list top level
    property string fmtState: ""; property string fmtMsg: ""; property int fmtPct: 0
    property int albums: -1; property int songs: -1
    property bool loaded: false
    property var places: []
    // a copy started from here and left running (ImportWizard)
    property string jobId: ""; property var job: null

    // ── navigation ────────────────────────────────────────────────────────
    property string view: "home"    // home | place | files
    property string placeKey: ""
    readonly property var cur: placeOf(placeKey)
    property bool showPw: false

    Component.onCompleted: Ui.sources = root
    onVisibleChanged: if (visible) { view = "home"; load() }

    function lt(it, en) { return I18n.lang === "it" ? it : en }
    function su(p) { return Api.srcBase + p }
    function under(p, r) { p = String(p || ""); r = String(r || ""); return !!r && (p === r || p.indexOf(r + "/") === 0) }
    function gb(n) {
        var v = Number(n) || 0
        if (v >= 1099511627776) return (v / 1099511627776).toFixed(1).replace(".", ",") + " TB"
        if (v >= 10 * 1073741824) return Math.round(v / 1073741824) + " GB"
        if (v >= 1073741824) return (v / 1073741824).toFixed(1).replace(".", ",") + " GB"
        return Math.round(v / 1048576) + " MB"
    }
    function placeOf(k) { for (var i = 0; i < places.length; i++) if (places[i].key === k) return places[i]; return null }
    function say(t) { if (Ui.toast) Ui.toast.say("info", t) }
    function fail(d, fallback) { say((d && d.message) ? String(d.message) : fallback) }

    function load() {
        var left = 8
        function done() { if (--left === 0) { loaded = true; rebuild() } }
        function get(path, fn) {
            Api.get(su(path), function(ok, d) { if (ok && d && typeof d === "object") { try { fn(d) } catch (e) { Sys.log("sources: " + path + ": " + e) } } done() }, 8000)
        }
        get("/api/sources", function(d) { srcs = d.sources || []; libPaths = (d.paths || []).map(String) })
        get("/api/usb", function(d) { usbBad = d.disks || [] })
        get("/api/internal/disks", function(d) {
            var out = []
            for (var i = 0; i < (d.disks || []).length; i++) {
                var k = d.disks[i], path = String(k.path || "")
                // not disks music can go on: the eMMC boot areas, the RAM swap, anything tiny
                if (path.indexOf("boot0") >= 0 || path.indexOf("boot1") >= 0 || path.indexOf("/dev/zram") === 0 || path.indexOf("/dev/loop") === 0
                    || String(k.fstype || "") === "swap" || Number(k.size || 0) < 1000000000) continue
                var parts = []
                for (var j = 0; j < (k.partitions || []).length; j++) {
                    var p = k.partitions[j]
                    if (p.fstype) parts.push({ path: String(p.path || ""), fs: String(p.fstype), label: String(p.label || "") })
                }
                out.push({ path: path, model: String(k.model || ""), confirm: String(k.confirm || ""), size: Number(k.size || 0),
                           adopted: !!k.adopted, hasData: !!k.has_data, parts: parts })
            }
            disks = out
        })
        get("/api/internal/smb", function(d) {
            smbHost = String(d.host || ""); smbIp = String(d.ip || ""); smbUser = String(d.username || ""); smbPass = String(d.password || "")
            shares = (d.shares || []).map(function(s) { return typeof s === "string" ? { name: s, mountpoint: "" } : { name: String(s.name || ""), mountpoint: String(s.mountpoint || ""), type: String(s.type || "") } })
        })
        get("/api/playlistdir", function(d) { pldir = String(d.path || "") })
        get("/api/cd/settings", function(d) { cd = d.settings || {} })
        get("/api/local/list?path=", function(d) { roots = d.entries || [] })
        get("/api/internal/format/status", function(d) { fmtState = String(d.state || ""); fmtMsg = String(d.message || ""); fmtPct = Number(d.progress !== undefined ? d.progress : (d.percent || 0)) })
        Player.queryServer(["info", "total", "albums", "?"], function(ok, r) { if (ok && r && r._albums !== undefined) albums = Number(r._albums) })
        Player.queryServer(["info", "total", "songs", "?"], function(ok, r) { if (ok && r && r._songs !== undefined) songs = Number(r._songs) })
    }
    // a stick plugged in, a NAS coming back: the page follows by itself
    Timer { interval: 5000; repeat: true; running: root.visible || (Ui.addMusic && Ui.addMusic.visible) || (Ui.importMusic && Ui.importMusic.visible); onTriggered: root.load() }

    // One place per disk or share: the system disk always, then each mounted
    // second disk, USB stick and network share; the local folders go to the
    // place they sit on.
    function rebuild() {
        var out = [], musicRoot = "", musicUsage = null, i
        for (i = 0; i < roots.length; i++) if (String(roots[i].kind) === "music") { musicRoot = String(roots[i].path); musicUsage = roots[i].usage || null }
        function mk(key, group, glyph, name, kind, root) {
            return { key: key, group: group, glyph: glyph, name: name, kind: kind, root: root, ok: true, rw: true, usage: null, src: null,
                     locals: [], lib: false, shared: false, playlist: false, rip: false, error: "", removable: false }
        }
        var sys = mk("sys", "dev", "hard-drive", lt("Disco di sistema", "System disk"), lt("Qui è installato Osmium", "Osmium is installed here"), musicRoot)
        sys.usage = musicUsage
        out.push(sys)
        var internals = srcs.filter(function(s) { return s.type === "internal" })
        for (i = 0; i < internals.length; i++) {
            var s = internals[i]
            var nm = internals.length === 1 ? lt("Secondo disco", "Second disk") : lt("Disco «", "Disk «") + (s.label || s.name) + "»"
            var p = mk(String(s.id), "dev", "hard-drive", nm, (s.model ? String(s.model) + " · " : "") + lt("montato dentro l'apparecchio", "mounted inside the appliance"), String(s.mountpoint || ""))
            p.src = s; p.ok = !!s.mounted; p.usage = s.usage || null; p.removable = true
            if (!p.ok) p.error = lt("Non montato", "Not mounted")
            out.push(p)
        }
        for (i = 0; i < srcs.length; i++) {
            var u = srcs[i]
            if (u.type !== "usb") continue
            var pu = mk(String(u.id), "usb", "usb", String(u.label || u.name || "USB"), lt("Chiavetta o disco USB", "USB stick or disk"), String(u.mountpoint || ""))
            pu.src = u; pu.ok = !!u.mounted; pu.usage = u.usage || null; pu.removable = true
            if (!pu.ok) continue                // not connected: it does not exist here
            out.push(pu)
        }
        for (i = 0; i < srcs.length; i++) {
            var n = srcs[i]
            if (n.type !== "smb") continue
            var pn = mk(String(n.id), "net", "network", String(n.server || "") + " › " + String(n.share || ""),
                        lt("Cartella di rete", "Network folder") + " · //" + n.server + "/" + n.share, String(n.mountpoint || ""))
            pn.src = n; pn.ok = !!n.mounted; pn.usage = n.usage || null; pn.rw = !!n.rw; pn.removable = true
            if (!pn.ok) pn.error = n.mount_error && n.mount_error.message ? String(n.mount_error.message) : lt("Non risponde: è acceso e sulla stessa rete?", "Not answering: is it on, and on the same network?")
            out.push(pn)
        }
        // local folders: on the place that holds them, else the system disk
        for (i = 0; i < srcs.length; i++) {
            var l = srcs[i]
            if (l.type !== "local") continue
            var host = sys
            for (var k = 1; k < out.length; k++) if (under(l.path, out[k].root)) host = out[k]
            host.locals.push(l)
        }
        // what each place is used for
        var ripTarget = String((cd && cd.target) || "")
        for (i = 0; i < out.length; i++) {
            var q = out[i]
            q.lib = q.locals.length > 0 || libPaths.some(function(x) { return under(x, q.root) })
            q.shared = shares.some(function(x) { return under(x.mountpoint, q.root) }) || q.locals.some(function(x) { return !!x.samba })
        }
        function owner(path) {
            if (!path) return sys
            for (var j = out.length - 1; j >= 1; j--) if (under(path, out[j].root)) return out[j]
            return sys
        }
        owner(pldir).playlist = true
        owner(ripTarget).rip = true
        places = out
    }

    // ── actions ───────────────────────────────────────────────────────────
    function post(path, body, msg, then) {
        Api.post(su(path), body || {}, function(ok, d) {
            if (ok && d && d.success !== false) { if (msg) say(msg); if (then) then(d) }
            else fail(d, lt("Non è riuscito", "That did not work"))
            load()
        }, 60000)
    }
    function removePlace(p) {
        if (!p || !p.src) return
        Ui.dialogs.confirm(lt("Togliere «" + p.name + "» dalla musica? I file restano dove sono.",
                             "Remove «" + p.name + "» from your music? The files stay where they are."),
                           lt("Togli", "Remove"), true, function(ok) {
            if (!ok) return
            Api.send("DELETE", su("/api/sources/" + p.src.id), {}, function() { root.view = "home"; root.load() }, 12000)
        })
    }
    function removeLocal(s) {
        Ui.dialogs.confirm(lt("Togliere questa cartella dalla libreria? I file restano dove sono.", "Take this folder out of the library? The files stay where they are."),
                           lt("Togli", "Remove"), true, function(ok) {
            if (ok) Api.send("DELETE", su("/api/sources/" + s.id), {}, function() { root.load() }, 12000)
        })
    }
    function pick(start, label, fn) { if (Ui.folderChooser) Ui.folderChooser.openAt(start || "", label, fn) }
    function addFolderHere(p, samba) {
        pick(p.root, samba ? lt("Condividi questa cartella", "Share this folder") : lt("Aggiungi alla libreria", "Add to the library"), function(path) {
            post("/api/sources/local", { path: path, samba: !!samba }, samba ? lt("Cartella condivisa", "Folder shared") : lt("Aggiunta alla libreria", "Added to the library"))
        })
    }
    function onlyOneFolder(p) {
        pick(p.root, lt("Usa solo questa cartella", "Use only this folder"), function(path) {
            var rel = path === p.root ? "" : path.slice(p.root.length + 1)
            post("/api/sources/" + p.src.id + "/subpath", { subpath: rel }, lt("Fatto", "Done"))
        })
    }
    function playlistsHere(p) {
        pick(p.root, lt("Salva qui le playlist", "Keep playlists here"), function(path) { post("/api/playlistdir", { path: path }, lt("Le playlist si salvano qui", "Playlists are kept here")) })
    }
    function ripHere(p) {
        pick(p.root, lt("Salva qui i CD rippati", "Keep ripped CDs here"), function(path) { post("/api/cd/settings", { target: path }, lt("I CD rippati finiscono qui", "Ripped CDs go here")) })
    }
    function adoptDisk(d) {
        var dev = d.parts.length === 1 ? d.parts[0].path : d.path
        post("/api/internal/adopt", { device: dev }, lt("Preparo il disco…", "Setting the disk up…"))
    }
    function formatDisk(d) {
        Ui.dialogs.format(d.path, d.model, d.size, d.confirm, function(device, fs, lbl) {
            Api.post(su("/api/internal/format"), { device: device, fs: fs, label: lbl, confirm: d.confirm }, function() { fmtWatch.start() }, 12000)
        })
    }
    Timer { id: fmtWatch; interval: 2000; repeat: true
        onTriggered: Api.get(root.su("/api/internal/format/status"), function(ok, d) {
            if (!ok || !d) return
            root.fmtState = String(d.state || ""); root.fmtMsg = String(d.message || ""); root.fmtPct = Number(d.progress !== undefined ? d.progress : (d.percent || 0))
            if (Ui.dialogs) Ui.dialogs.formatStatus(root.fmtState, root.fmtMsg, root.fmtPct)
            if (root.fmtState === "done" || root.fmtState === "error" || !Ui.dialogs.active) { fmtWatch.stop(); root.load() }
        }, 5000) }
    // the copy left running: its line on the first page
    Timer { interval: 1000; repeat: true; running: !!root.jobId
        onTriggered: Api.get(root.su("/api/local/job?id=" + root.jobId), function(ok, d) {
            if (!ok || !d) { root.jobId = ""; return }
            root.job = d
            if (d.state === "done" || d.state === "error") { root.jobId = ""; root.load() }
        }, 5000) }

    // ── the pages ─────────────────────────────────────────────────────────
    // header: back arrow + title, like the other sections
    Item {
        x: 32; y: 32; width: parent.width - 64; height: 36
        Item {
            width: 44; height: 36
            Icon { anchors.verticalCenter: parent.verticalCenter; name: "chevron-left"; size: 32; color: Theme.gold }
            Tap { grow: 8; onClicked: { if (root.view === "home") root.back(); else if (root.view === "files") root.view = root.placeKey ? "place" : "home"; else root.view = "home" } }
        }
        Text {
            x: 44; width: parent.width - 44 - (addBtn.visible ? addBtn.width + 12 : 0); height: 36; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
            text: root.view === "home" ? root.lt("La tua musica", "Your music") : root.cur ? root.cur.name : ""
            color: Theme.white; font.family: Theme.font; font.pixelSize: 30; font.bold: true
        }
        SBtn { id: addBtn; visible: root.view === "home"; x: parent.width - width; anchors.verticalCenter: parent.verticalCenter; lead: true; glyph: "plus"; label: root.lt("Aggiungi musica", "Add music")
               onClicked: if (Ui.addMusic) Ui.addMusic.open() }
    }

    // ── first page: one card per place ────────────────────────────────────
    Flickable {
        id: home
        visible: root.view === "home"
        x: 0; y: 84; width: parent.width; height: parent.height - y
        contentHeight: homeCol.height + 24; clip: true; boundsBehavior: Flickable.StopAtBounds
        Column {
            id: homeCol
            x: 32; width: parent.width - 64; spacing: 10
            // the one-line answer to "is my music all there?"
            Rectangle {
                width: parent.width; height: 58; radius: 14; color: Theme.panel; border.width: 1; border.color: Theme.border
                readonly property int bad: root.places.filter(function(p) { return !p.ok }).length
                Rectangle { x: 0; y: 13; width: 3; height: 32; radius: 2; color: parent.bad ? Theme.yellow400 : Theme.emerald }
                Text { x: 18; y: 10; width: parent.width - 36; elide: Text.ElideRight
                       text: !root.loaded ? root.lt("Guardo dove sta la musica…", "Looking where the music is…")
                             : root.albums >= 0 ? root.lt(root.albums + " album nella libreria", root.albums + " albums in the library") + (root.songs >= 0 ? " · " + root.songs + root.lt(" brani", " tracks") : "")
                             : root.lt("La libreria", "The library")
                       color: Theme.white; font.family: Theme.font; font.pixelSize: 15; font.bold: true }
                Text { x: 18; y: 33; width: parent.width - 36; elide: Text.ElideRight
                       text: parent.bad ? root.lt("Un posto non risponde: la sua musica torna quando si riaccende.", "One place is not answering: its music comes back when it is on again.")
                                        : root.lt("Tutto funziona · la musica sta in ", "All working · the music is in ") + root.places.length + root.lt(root.places.length === 1 ? " posto" : " posti", root.places.length === 1 ? " place" : " places")
                       color: Theme.silverA(0.65); font.family: Theme.font; font.pixelSize: 12 }
            }
            // a copy still going
            Rectangle {
                visible: !!root.jobId && !!root.job
                width: parent.width; height: 52; radius: 12; color: Theme.panel; border.width: 1; border.color: Theme.goldA(0.4)
                Icon { x: 14; anchors.verticalCenter: parent.verticalCenter; name: "copy"; size: 17; color: Theme.gold }
                Text { x: 42; y: 9; width: parent.width - 60; elide: Text.ElideRight; text: root.lt("Sto copiando… ", "Copying… ") + (root.job ? (root.job.progress || 0) + "%" : ""); color: Theme.white; font.family: Theme.font; font.pixelSize: 13; font.bold: true }
                Text { x: 42; y: 28; width: parent.width - 60; elide: Text.ElideMiddle; text: root.job ? String(root.job.current || "") : ""; color: Theme.silverA(0.55); font.family: Theme.font; font.pixelSize: 11 }
                Tap { onClicked: if (Ui.importMusic) Ui.importMusic.follow(root.jobId) }
            }
            // what needs a hand: a new disk inside, a USB disk that could not be read, a format going
            Repeater {
                model: root.disks.filter(function(d) { return !d.adopted })
                delegate: Rectangle {
                    required property var modelData
                    width: homeCol.width; height: 92; radius: 14; color: Theme.panel; border.width: 1; border.color: Qt.rgba(0.98, 0.8, 0.08, 0.45)
                    Icon { x: 16; y: 16; name: "hard-drive"; size: 20; color: Theme.yellow400 }
                    Text { x: 46; y: 13; width: parent.width - 60; elide: Text.ElideRight; text: root.lt("Un disco nuovo dentro l'apparecchio", "A new disk inside the appliance") + " · " + (modelData.model || modelData.path) + " · " + root.gb(modelData.size); color: Theme.white; font.family: Theme.font; font.pixelSize: 14; font.bold: true }
                    Text { x: 46; y: 34; width: parent.width - 60; elide: Text.ElideRight; text: modelData.hasData ? root.lt("Ha già dei file: puoi usarlo così, o prepararlo da capo (cancella tutto).", "It already has files: use it as it is, or set it up from scratch (erases everything).") : root.lt("È vuoto: va preparato prima di usarlo.", "It is empty: it needs setting up first."); color: Theme.silverA(0.65); font.family: Theme.font; font.pixelSize: 12 }
                    Row { x: 46; y: 54; spacing: 8
                        SBtn { small: true; visible: modelData.parts.length > 0; label: root.lt("Usalo così", "Use it as it is"); onClicked: root.adoptDisk(modelData) }
                        SBtn { small: true; danger: true; label: root.lt("Preparalo (cancella tutto)", "Set it up (erases everything)"); onClicked: root.formatDisk(modelData) } }
                }
            }
            Repeater {
                model: root.usbBad
                delegate: Rectangle {
                    required property var modelData
                    width: homeCol.width; height: 70; radius: 14; color: Theme.panel; border.width: 1; border.color: Qt.rgba(0.98, 0.8, 0.08, 0.45)
                    Icon { x: 16; y: 16; name: "usb"; size: 20; color: Theme.yellow400 }
                    Text { x: 46; y: 13; width: parent.width - 170; elide: Text.ElideRight; text: String(modelData.label || modelData.model || "USB") + (modelData.size ? " · " + modelData.size : ""); color: Theme.white; font.family: Theme.font; font.pixelSize: 14; font.bold: true }
                    Text { x: 46; y: 36; width: parent.width - 170; elide: Text.ElideRight; text: modelData.needs_format ? root.lt("Non la so leggere: va formattata da un computer.", "I cannot read it: it needs formatting on a computer.") : root.lt("Non si è montata: ", "It did not mount: ") + String(modelData.error || ""); color: Theme.silverA(0.65); font.family: Theme.font; font.pixelSize: 12 }
                    SBtn { visible: !modelData.needs_format; small: true; x: parent.width - 14 - width; anchors.verticalCenter: parent.verticalCenter; label: root.lt("Riprova", "Try again")
                           onClicked: root.post("/api/usb/adopt", { device: String(modelData.path || modelData.id || "") }, root.lt("Riprovo…", "Trying again…")) }
                }
            }
            Rectangle {
                visible: root.fmtState !== "" && root.fmtState !== "idle" && root.fmtState !== "done"
                width: parent.width; height: 44; radius: 12; color: Theme.panel; border.width: 1; border.color: Theme.border
                Text { x: 16; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 32; elide: Text.ElideRight; text: root.fmtMsg + (root.fmtPct > 0 ? " (" + root.fmtPct + "%)" : ""); color: Theme.silver; font.family: Theme.font; font.pixelSize: 13 }
            }
            // the cards, by group
            Repeater {
                model: [["dev", root.lt("Questo apparecchio", "This appliance")], ["usb", root.lt("Collegati via USB", "Connected over USB")], ["net", root.lt("In rete", "On the network")]]
                delegate: Column {
                    id: grp
                    required property var modelData
                    readonly property var items: root.places.filter(function(p) { return p.group === modelData[0] })
                    visible: items.length > 0
                    width: homeCol.width; spacing: 8
                    Text { text: grp.modelData[1]; height: 22; verticalAlignment: Text.AlignBottom; color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 10; font.bold: true; font.capitalization: Font.AllUppercase; font.letterSpacing: 1 }
                    Flow {
                        width: parent.width; spacing: 10
                        Repeater {
                            model: grp.items
                            delegate: PlaceCard { required property var modelData; place: modelData; width: (homeCol.width - 10) / 2 }
                        }
                    }
                }
            }
            // what the uses mean
            Rectangle {
                width: parent.width; height: 70; radius: 14; color: "transparent"; border.width: 1; border.color: Theme.wa(0.12)
                Grid {
                    x: 16; y: 12; columns: 2; columnSpacing: 22; rowSpacing: 8
                    Repeater {
                        model: [["music", root.lt("Libreria", "Library"), root.lt("compare in Musica", "shows in Music")],
                                ["share-2", root.lt("Condivisa", "Shared"), root.lt("la vedi dal computer", "you see it from a computer")],
                                ["list-music", root.lt("Playlist", "Playlists"), root.lt("qui si salvano le playlist", "playlists are kept here")],
                                ["disc", root.lt("Rip CD", "CD rip"), root.lt("qui finiscono i CD copiati", "ripped CDs go here")]]
                        delegate: Row {
                            required property var modelData
                            spacing: 7
                            Icon { anchors.verticalCenter: parent.verticalCenter; name: modelData[0]; size: 12; color: Theme.gold }
                            Text { anchors.verticalCenter: parent.verticalCenter; textFormat: Text.StyledText; text: "<b>" + modelData[1] + "</b>  " + modelData[2]; color: Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 11 }
                        }
                    }
                }
            }
        }
    }

    component PlaceCard: Rectangle {
        id: pc
        property var place
        height: 150; radius: 14
        color: pcTap.mix(Theme.panel, Theme.gray)
        border.width: 1; border.color: !place.ok ? Theme.redA(0.45) : Theme.border
        Rectangle { x: 14; y: 14; width: 40; height: 40; radius: 10; color: pc.place.ok ? Theme.goldA(0.12) : Theme.redA(0.12)
            Icon { anchors.centerIn: parent; name: pc.place.glyph; size: 20; color: pc.place.ok ? Theme.gold : Theme.red400 } }
        Text { x: 66; y: 13; width: parent.width - 96; elide: Text.ElideRight; text: pc.place.name; color: Theme.white; font.family: Theme.font; font.pixelSize: 15; font.bold: true }
        Text { x: 66; y: 35; width: parent.width - 80; elide: Text.ElideRight; text: pc.place.kind; color: Theme.silverA(0.55); font.family: Theme.font; font.pixelSize: 11 }
        Icon { x: parent.width - 30; y: 22; name: "chevron-right"; size: 16; color: Theme.silverA(0.4) }
        Row { x: 14; y: 64; spacing: 7
            Rectangle { anchors.verticalCenter: parent.verticalCenter; width: 8; height: 8; radius: 4; color: pc.place.ok ? Theme.emerald : Theme.red400 }
            Text { width: pc.width - 44; elide: Text.ElideRight; text: pc.place.ok ? root.lt("Funziona", "Working") + (pc.place.rw ? root.lt(" · si può scrivere", " · writable") : root.lt(" · sola lettura", " · read only")) : pc.place.error
                   color: pc.place.ok ? Theme.emerald : Theme.red400; font.family: Theme.font; font.pixelSize: 12; font.bold: true } }
        Item {
            visible: !!(pc.place.usage && pc.place.usage.total)
            x: 14; y: 86; width: parent.width - 28; height: 22
            readonly property real used: pc.place.usage && pc.place.usage.total ? 1 - pc.place.usage.free / pc.place.usage.total : 0
            Rectangle { y: 2; width: parent.width; height: 5; radius: 3; color: Theme.wa(0.08)
                Rectangle { width: parent.width * parent.parent.used; height: parent.height; radius: 3; color: parent.parent.used > 0.92 ? Theme.yellow400 : Theme.gold } }
            Text { y: 11; text: pc.place.usage ? root.gb(pc.place.usage.free) + root.lt(" liberi su ", " free of ") + root.gb(pc.place.usage.total) : ""; color: Theme.silverA(0.55); font.family: Theme.font; font.pixelSize: 11 }
        }
        Flow {
            x: 14; y: parent.height - 12 - 24; width: parent.width - 24; spacing: 4
            SChip { visible: pc.place.lib; glyph: "music"; label: root.lt("Libreria", "Library") }
            SChip { visible: pc.place.shared; glyph: "share-2"; label: root.lt("Condivisa", "Shared") }
            SChip { visible: pc.place.playlist; glyph: "list-music"; label: root.lt("Playlist", "Playlists") }
            SChip { visible: pc.place.rip; glyph: "disc"; label: root.lt("Rip CD", "CD rip") }
            SChip { visible: !pc.place.lib && !pc.place.shared && !pc.place.playlist && !pc.place.rip; on: false; glyph: "music"; label: root.lt("Non ancora usato", "Not used yet") }
        }
        Tap { id: pcTap; onClicked: { root.placeKey = pc.place.key; root.view = "place" } }
    }

    // ── the page of one place ─────────────────────────────────────────────
    Flickable {
        visible: root.view === "place" && !!root.cur
        x: 0; y: 84; width: parent.width; height: parent.height - y
        contentHeight: placeCol.height + 24; clip: true; boundsBehavior: Flickable.StopAtBounds
        Column {
            id: placeCol
            readonly property var p: root.cur || ({ key: "", group: "", name: "", kind: "", root: "", ok: false, rw: false, usage: null, src: null, locals: [], lib: false, shared: false, playlist: false, rip: false, error: "", removable: false })
            x: 32; width: parent.width - 64; spacing: 10
            Text { width: parent.width; elide: Text.ElideRight; text: placeCol.p.kind || ""; color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 13 }
            // state and room
            Rectangle {
                width: parent.width; height: 68; radius: 14; color: Theme.panel; border.width: 1; border.color: placeCol.p.ok ? Theme.border : Theme.redA(0.45)
                Row { x: 16; y: 12; spacing: 7
                    Rectangle { anchors.verticalCenter: parent.verticalCenter; width: 8; height: 8; radius: 4; color: placeCol.p.ok ? Theme.emerald : Theme.red400 }
                    Text { text: placeCol.p.ok ? root.lt("Funziona", "Working") + (placeCol.p.rw ? root.lt(" · si può scrivere", " · writable") : root.lt(" · sola lettura", " · read only")) : String(placeCol.p.error || "")
                           color: placeCol.p.ok ? Theme.emerald : Theme.red400; font.family: Theme.font; font.pixelSize: 13; font.bold: true } }
                Item { visible: !!(placeCol.p.usage && placeCol.p.usage.total); x: 16; y: 36; width: parent.width - 32; height: 24
                    readonly property real used: placeCol.p.usage && placeCol.p.usage.total ? 1 - placeCol.p.usage.free / placeCol.p.usage.total : 0
                    Rectangle { width: parent.width; height: 5; radius: 3; color: Theme.wa(0.08); Rectangle { width: parent.width * parent.parent.used; height: 5; radius: 3; color: Theme.gold } }
                    Text { y: 9; text: placeCol.p.usage ? root.gb(placeCol.p.usage.free) + root.lt(" liberi su ", " free of ") + root.gb(placeCol.p.usage.total) : ""; color: Theme.silverA(0.55); font.family: Theme.font; font.pixelSize: 11 } }
                SBtn { visible: !placeCol.p.ok; small: true; x: parent.width - 14 - width; y: 18; glyph: "refresh-cw"; label: root.lt("Ricontrolla", "Check again"); onClicked: root.load() }
            }
            // in the library
            Text { text: root.lt("Nella libreria", "In the library"); height: 24; verticalAlignment: Text.AlignBottom; color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 10; font.bold: true; font.capitalization: Font.AllUppercase; font.letterSpacing: 1 }
            // the disk or share itself (second disk, USB, network)
            Rectangle {
                visible: !!placeCol.p.src
                width: parent.width; height: 56; radius: 12; color: Theme.panel; border.width: 1; border.color: Theme.border
                readonly property string sub: placeCol.p.src ? String(placeCol.p.src.subpath || "") : ""
                Icon { x: 14; anchors.verticalCenter: parent.verticalCenter; name: "music"; size: 17; color: Theme.gold }
                Text { x: 42; y: 10; width: parent.width - 42 - 260; elide: Text.ElideRight; text: parent.sub ? root.lt("Solo la cartella «", "Only the folder «") + parent.sub + "»" : root.lt("Tutto il contenuto", "All of it"); color: Theme.white; font.family: Theme.font; font.pixelSize: 14; font.bold: true }
                Text { x: 42; y: 30; width: parent.width - 42 - 260; elide: Text.ElideMiddle; text: placeCol.p.root + (parent.sub ? "/" + parent.sub : ""); color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 11 }
                Row { anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; spacing: 6
                    SBtn { small: true; on: placeCol.p.ok; label: root.lt("Solo una cartella…", "Only one folder…"); onClicked: root.onlyOneFolder(placeCol.p) }
                    SBtn { small: true; visible: !!parent.parent.sub; label: root.lt("Tutto", "All of it"); onClicked: root.post("/api/sources/" + placeCol.p.src.id + "/subpath", { subpath: "" }, root.lt("Fatto", "Done")) } }
            }
            // folders of this place added one by one
            Repeater {
                model: placeCol.p.locals
                delegate: Rectangle {
                    required property var modelData
                    width: placeCol.width; height: 56; radius: 12; color: Theme.panel; border.width: 1; border.color: modelData.exists === false ? Theme.redA(0.45) : Theme.border
                    Icon { x: 14; anchors.verticalCenter: parent.verticalCenter; name: "folder"; size: 17; color: Theme.gold }
                    Text { x: 42; y: 10; width: parent.width - 42 - 150; elide: Text.ElideRight; text: String(modelData.path).split("/").pop(); color: Theme.white; font.family: Theme.font; font.pixelSize: 14; font.bold: true }
                    Text { x: 42; y: 30; width: parent.width - 42 - 150; elide: Text.ElideMiddle; text: (modelData.exists === false ? root.lt("Non la trovo più · ", "Not found any more · ") : "") + modelData.path + (modelData.samba ? root.lt(" · condivisa", " · shared") : ""); color: modelData.exists === false ? Theme.red300 : Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 11 }
                    SBtn { small: true; danger: true; x: parent.width - 12 - width; anchors.verticalCenter: parent.verticalCenter; label: root.lt("Togli", "Remove"); onClicked: root.removeLocal(modelData) }
                }
            }
            Text { visible: !placeCol.p.src && !placeCol.p.locals.length; width: parent.width; wrapMode: Text.WordWrap; text: root.lt("Niente di qui è nella libreria.", "Nothing from here is in the library."); color: Theme.silverA(0.55); font.family: Theme.font; font.pixelSize: 13 }
            SBtn { visible: !placeCol.p.src; on: placeCol.p.ok; glyph: "plus"; label: root.lt("Aggiungi una cartella di qui", "Add a folder from here"); onClicked: root.addFolderHere(placeCol.p, false) }

            // what else it is used for
            Text { text: root.lt("Usi", "Uses"); height: 30; verticalAlignment: Text.AlignBottom; color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 10; font.bold: true; font.capitalization: Font.AllUppercase; font.letterSpacing: 1 }
            UseRow {
                glyph: "share-2"; on: placeCol.p.shared
                title: placeCol.p.shared ? root.lt("Condivisa in rete", "Shared on the network") : root.lt("Non condivisa", "Not shared")
                hint: placeCol.p.shared ? "\\\\" + (root.smbIp || root.smbHost) + root.lt("  · utente ", "  · user ") + root.smbUser + root.lt(" · password ", " · password ") + (root.showPw ? root.smbPass : "••••••")
                                        : root.lt("Dal computer non la vedi.", "A computer does not see it.")
                action: placeCol.p.shared ? (root.showPw ? root.lt("Nascondi", "Hide") : root.lt("Mostra password", "Show password"))
                                          : (placeCol.p.src ? "" : root.lt("Condividi una cartella…", "Share a folder…"))
                onAct: { if (placeCol.p.shared) root.showPw = !root.showPw; else root.addFolderHere(placeCol.p, true) }
            }
            UseRow {
                glyph: "list-music"; on: placeCol.p.playlist
                title: placeCol.p.playlist ? root.lt("Le playlist si salvano qui", "Playlists are kept here") : root.lt("Le playlist si salvano altrove", "Playlists are kept elsewhere")
                hint: root.pldir
                action: placeCol.p.ok && placeCol.p.rw ? (placeCol.p.playlist ? root.lt("Cambia cartella", "Change folder") : root.lt("Salvale qui", "Keep them here")) : ""
                onAct: root.playlistsHere(placeCol.p)
            }
            UseRow {
                glyph: "disc"; on: placeCol.p.rip
                title: placeCol.p.rip ? root.lt("I CD rippati finiscono qui", "Ripped CDs go here") : root.lt("I CD rippati finiscono altrove", "Ripped CDs go elsewhere")
                hint: String((root.cd && root.cd.target) || root.lt("cartella predefinita", "default folder"))
                action: placeCol.p.ok && placeCol.p.rw ? (placeCol.p.rip ? root.lt("Cambia cartella", "Change folder") : root.lt("Salvali qui", "Keep them here")) : ""
                onAct: root.ripHere(placeCol.p)
            }
            UseRow {
                visible: placeCol.p.group === "net"
                glyph: "pencil"; on: placeCol.p.rw
                title: placeCol.p.rw ? root.lt("Si può scrivere", "Writable") : root.lt("Sola lettura", "Read only")
                hint: root.lt("Vale dal prossimo riavvio.", "Takes effect at the next restart.")
                action: placeCol.p.rw ? root.lt("Rendi sola lettura", "Make read only") : root.lt("Rendi scrivibile", "Make writable")
                onAct: root.post("/api/sources/" + placeCol.p.src.id + "/rw", { rw: !placeCol.p.rw }, root.lt("Vale dal prossimo riavvio", "Takes effect at the next restart"))
            }
            Item { width: 1; height: 6 }
            Row {
                spacing: 8
                SBtn { lead: true; on: placeCol.p.ok; glyph: "folder"; label: root.lt("Sfoglia i file", "Browse the files"); onClicked: root.view = "files" }
                SBtn { visible: placeCol.p.group === "usb" && placeCol.p.ok; glyph: "copy"; label: root.lt("Copia nell'apparecchio", "Copy into the appliance"); onClicked: if (Ui.importMusic) Ui.importMusic.openFor(placeCol.p) }
                SBtn { visible: placeCol.p.removable; danger: true; glyph: "trash-2"; label: root.lt("Togli questo posto", "Remove this place"); onClicked: root.removePlace(placeCol.p) }
            }
        }
    }

    component UseRow: Rectangle {
        id: ur
        signal act()
        property string glyph
        property bool on: false
        property string title
        property string hint
        property string action
        width: placeCol.width; height: 56; radius: 12; color: Theme.panel; border.width: 1; border.color: on ? Theme.goldA(0.35) : Theme.border
        Rectangle { x: 12; anchors.verticalCenter: parent.verticalCenter; width: 32; height: 32; radius: 8; color: ur.on ? Theme.goldA(0.14) : Theme.wa(0.04)
            Icon { anchors.centerIn: parent; name: ur.glyph; size: 15; color: ur.on ? Theme.gold : Theme.silverA(0.5) } }
        Text { x: 56; y: 10; width: parent.width - 56 - (urBtn.visible ? urBtn.width + 24 : 12); elide: Text.ElideRight; text: ur.title; color: ur.on ? Theme.white : Theme.silver; font.family: Theme.font; font.pixelSize: 14; font.bold: ur.on }
        Text { x: 56; y: 30; width: parent.width - 56 - (urBtn.visible ? urBtn.width + 24 : 12); elide: Text.ElideMiddle; text: ur.hint; color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 11 }
        SBtn { id: urBtn; visible: !!ur.action; small: true; x: parent.width - 12 - width; anchors.verticalCenter: parent.verticalCenter; label: ur.action; onClicked: ur.act() }
    }

    // ── the files: the two-pane file manager, this place on the left ──────
    SrcCommander {
        id: commander
        visible: root.view === "files"
        x: 0; y: 84; width: parent.width; height: parent.height - y
        onVisibleChanged: if (visible) commander.openAt(root.cur ? root.cur.root : "")
    }
}
