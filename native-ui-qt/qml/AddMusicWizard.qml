// "Add music": the wizard of Music sources. It starts from where the music
// is, in the owner's words — a USB stick, a computer or NAS, this appliance,
// or "I don't know, look for me" — and what was already found sits below the
// question, one tap away. A USB stick goes on to ImportWizard.qml (listen
// from it, or copy it in). A network share goes through device → shared
// folder → sign-in, asked only when the device wants it. A folder of this
// appliance is picked among the folders found on its disks (simple) or in
// the explorer (advanced, SrcExplorer in picker mode). Data and actions are
// sources_server's, the ones the old bands of the section used.
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    anchors.fill: parent
    visible: false
    // where | found | net | netShares | netConfirm | folder | adv | done
    property string step: "where"
    property var hosts: []
    property string scanState: ""
    property int scanPct: 0
    property bool canList: true
    property string host: ""; property string hostName: ""
    property string share: ""
    property string user: ""; property string pw: ""
    property bool rw: true
    property var smbShares: []
    property bool busy: false
    property string err: ""
    property var cands: []            // folders found on this appliance's disks
    property string chosen: ""
    property string doneText: ""
    readonly property var src: Ui.sources

    Component.onCompleted: Ui.addMusic = root
    NavScope { active: root.visible }

    function lt(it, en) { return I18n.lang === "it" ? it : en }
    function su(p) { return Api.srcBase + p }
    function open() { step = "where"; err = ""; busy = false; visible = true; scan(); if (src) src.load() }
    function close() { visible = false; scanPoll.stop() }
    function finish(text) { doneText = text; step = "done"; if (src) src.load() }

    // ── network discovery, from the moment the wizard opens ──────────────
    function scan() {
        scanState = "running"; scanPct = 0; hosts = []
        Api.post(su("/api/sources/smb/discover"), {}, function() { scanPoll.restart(); poll() }, 10000)
    }
    function poll() {
        Api.get(su("/api/sources/smb/discover"), function(ok, d) {
            if (!ok || !d || typeof d !== "object") return
            root.scanState = String(d.state || ""); root.scanPct = Number(d.progress || 0)
            root.hosts = (d.hosts || []).map(function(h) { return { ip: String(h.ip || ""), name: String(h.name || "") } })
            if (d.tools && d.tools.shares === false) root.canList = false
            if (root.scanState !== "running") scanPoll.stop()
        }, 8000)
    }
    Timer { id: scanPoll; interval: 900; repeat: true; onTriggered: root.poll() }

    // ── USB ───────────────────────────────────────────────────────────────
    function sticks() { return src ? src.places.filter(function(p) { return p.group === "usb" && p.ok }) : [] }
    function newDisks() { return src ? src.disks.filter(function(d) { return !d.adopted }) : [] }
    function toUsb(p) {
        var s = p ? [p] : sticks()
        if (s.length === 1) { close(); if (Ui.importMusic) Ui.importMusic.openFor(s[0]); return }
        step = "usb"
    }

    // ── network share: device → folder → sign-in ──────────────────────────
    function pickHost(ip, name) {
        scanPoll.stop(); host = ip; hostName = name || ip; share = ""; smbShares = []; err = ""; step = "netShares"
        if (canList) loadShares()
    }
    function typeHost() {
        Ui.vk.openText(lt("Indirizzo del computer o NAS (es. 192.168.1.20)", "Address of the computer or NAS (e.g. 192.168.1.20)"), host, false, function(ok, t) {
            t = String(t || "").trim().replace(/^\\\\|^\/\//, "")
            if (ok && t) root.pickHost(t, t)
        })
    }
    function typeShare() {
        Ui.vk.openText(lt("Nome della cartella condivisa", "Name of the shared folder"), share, false, function(ok, t) {
            t = String(t || "").trim()
            if (ok && t) root.pickShare(t)
        })
    }
    function askAuth(refused, retry) {
        Ui.dialogs.login(Tr.tf("sources.wizard.signInTo", "device", hostName || host), Tr.t("sources.wizard.authHint"), user,
                         refused ? Tr.t("sources.wizard.wrongPassword") : "",
                         function(u, p) { if (u === null || !root.visible) return; root.user = u; root.pw = p; retry() })
    }
    function loadShares() {
        busy = true; err = ""
        var tried = user !== ""
        Api.post(su("/api/sources/smb/shares"), { server: host, username: user, password: pw }, function(ok, d) {
            root.busy = false
            if (root.step !== "netShares") return
            if (!ok || !d || d.success === false) {
                if (d && d.code === "msg.smbBadCredentials") { root.askAuth(tried, root.loadShares); return }
                root.err = d && d.message ? String(d.message) : Tr.t("sources.wizard.listFailed"); root.canList = false; return
            }
            root.smbShares = (d.shares || []).map(function(x) { return { name: String(x.name || ""), comment: String(x.comment || "") } })
            if (d.needs_auth && !root.smbShares.length) root.askAuth(tried, root.loadShares)
        }, 40000)
    }
    function pickShare(name) {
        share = name; err = ""; busy = true
        var tried = user !== ""
        Api.post(su("/api/sources/smb/test"), { server: host, share: name, username: user, password: pw }, function(ok, d) {
            root.busy = false
            if (ok && d && d.success !== false) { root.step = "netConfirm"; return }
            if (d && d.code === "msg.smbBadCredentials") { root.askAuth(tried, function() { root.pickShare(name) }); return }
            root.err = d && d.message ? String(d.message) : Tr.t("sources.wizard.openFailed")
        }, 40000)
    }
    function addShare() {
        busy = true; err = ""
        Api.post(su("/api/sources/smb"), { server: host, share: share, username: user, password: pw, rw: rw }, function(ok, d) {
            root.busy = false
            if (ok && d && d.success !== false) { root.finish(lt("«" + share + "» di " + (hostName || host) + " è nella libreria: la musica compare in Musica man mano che la leggo.",
                                                                 "«" + share + "» on " + (hostName || host) + " is in the library: its music shows up in Music as I read it.")); return }
            if (d && d.code === "msg.smbBadCredentials") { root.step = "netShares"; root.askAuth(root.user !== "", function() { root.pickShare(root.share) }); return }
            root.err = d && d.message ? String(d.message) : Tr.t("sources.wizard.openFailed")
        }, 60000)
    }

    // ── a folder of this appliance ────────────────────────────────────────
    function inLib(p) { return src && src.libPaths.some(function(x) { return src.under(p, x) }) }
    function loadCands() {
        cands = []; chosen = ""
        var dev = src ? src.places.filter(function(p) { return p.group === "dev" && p.ok && p.root }) : []
        var out = [], left = dev.length
        dev.forEach(function(p) {
            out.push({ name: p.key === "sys" ? lt("Tutta la cartella della musica", "The whole music folder") : lt("Tutto il disco", "The whole disk"), place: p.name, path: p.root, inLib: inLib(p.root), whole: true })
            Api.get(su("/api/local/list?path=" + encodeURIComponent(p.root)), function(ok, d) {
                if (ok && d && d.entries) d.entries.filter(function(e) { return e.dir }).forEach(function(e) {
                    out.push({ name: String(e.name), place: p.name, path: String(e.path), inLib: root.inLib(String(e.path)), whole: false })
                })
                if (--left === 0) {
                    out.sort(function(a, b) { return (a.inLib - b.inLib) || (b.whole - a.whole) })
                    root.cands = out
                    var free = out.filter(function(c) { return !c.inLib })
                    root.chosen = free.length ? free[0].path : ""
                }
            }, 10000)
        })
    }
    function addFolder(path) {
        if (!path) return
        busy = true
        Api.post(su("/api/sources/local"), { path: path }, function(ok, d) {
            root.busy = false
            if (ok && d && d.success !== false) root.finish(lt("La cartella è nella libreria: la musica compare in Musica man mano che la leggo.", "The folder is in the library: its music shows up in Music as I read it."))
            else root.err = d && d.message ? String(d.message) : lt("Non è riuscito", "That did not work")
        }, 30000)
    }

    // ── drawing ───────────────────────────────────────────────────────────
    component Choice: Rectangle {
        id: ch
        signal picked()
        property string glyph; property string title; property string hint; property bool lead: false
        width: (chGrid.width - 12) / 2; height: 92; radius: 14
        color: chTap.mix(lead ? Theme.goldA(0.10) : Theme.dark, Theme.light)
        border.width: lead ? 1.5 : 1; border.color: lead ? Theme.gold : Theme.border
        Rectangle { x: 16; anchors.verticalCenter: parent.verticalCenter; width: 50; height: 50; radius: 25; color: ch.lead ? Theme.gold : Theme.goldA(0.12)
            Icon { anchors.centerIn: parent; name: ch.glyph; size: 23; color: ch.lead ? Theme.black : Theme.gold } }
        Text { x: 80; y: 20; width: parent.width - 80 - 34; elide: Text.ElideRight; text: ch.title; color: Theme.white; font.family: Theme.font; font.pixelSize: 14; font.bold: true }
        Text { x: 80; y: 43; width: parent.width - 80 - 34; wrapMode: Text.WordWrap; maximumLineCount: 2; text: ch.hint; color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 12 }
        Icon { x: parent.width - 30; anchors.verticalCenter: parent.verticalCenter; name: "chevron-right"; size: 16; color: ch.lead ? Theme.gold : Theme.silverA(0.4) }
        Tap { id: chTap; onClicked: ch.picked() }
    }
    component Line: Rectangle {
        id: ln
        signal act()
        property string glyph; property string title; property string hint; property string action; property bool done: false; property bool chosen: false; property bool radio: false
        width: parent.width; height: 54; radius: 10
        color: chosen ? Theme.goldA(0.10) : lnTap.mix(Theme.dark, Theme.gray); border.width: chosen ? 1.5 : 1; border.color: chosen ? Theme.gold : Theme.border
        opacity: done ? 0.6 : 1
        Tap { id: lnTap; enabled: !ln.done; navigable: !lnBtn.visible; onClicked: ln.act() }
        Rectangle { visible: ln.radio; x: 14; anchors.verticalCenter: parent.verticalCenter; width: 20; height: 20; radius: 10; color: "transparent"; border.width: 2; border.color: ln.chosen ? Theme.gold : Theme.wa(0.25)
            Rectangle { visible: ln.chosen; anchors.centerIn: parent; width: 9; height: 9; radius: 5; color: Theme.gold } }
        Icon { x: ln.radio ? 44 : 14; anchors.verticalCenter: parent.verticalCenter; name: ln.glyph; size: 18; color: Theme.gold }
        Text { x: ln.radio ? 74 : 44; y: 9; width: parent.width - x - 170; elide: Text.ElideRight; text: ln.title; color: Theme.white; font.family: Theme.font; font.pixelSize: 13; font.bold: true }
        Text { x: ln.radio ? 74 : 44; y: 29; width: parent.width - x - 170; elide: Text.ElideMiddle; text: ln.hint; color: Theme.silverA(0.55); font.family: Theme.font; font.pixelSize: 11 }
        SBtn { id: lnBtn; visible: !!ln.action && !ln.done; small: true; lead: !ln.radio; x: parent.width - 10 - width; anchors.verticalCenter: parent.verticalCenter; label: ln.action; onClicked: ln.act() }
        Row { visible: ln.done; x: parent.width - 14 - width; anchors.verticalCenter: parent.verticalCenter; spacing: 6
            Icon { anchors.verticalCenter: parent.verticalCenter; name: "check"; size: 14; color: Theme.emerald }
            Text { text: ln.action; color: Theme.emerald; font.family: Theme.font; font.pixelSize: 12 } }
    }
    component Head: Text { color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 10; font.bold: true; font.capitalization: Font.AllUppercase; font.letterSpacing: 1 }

    Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0, 0, 0.72); MouseArea { anchors.fill: parent; onClicked: root.close() } }
    Rectangle {
        id: card
        width: root.step === "adv" ? Math.min(1010, root.width - 32) : Math.min(860, root.width - 40)
        height: root.step === "adv" ? Math.min(584, root.height - 16) : Math.min(568, root.height - 24)
        anchors.centerIn: parent
        radius: 18; color: Theme.panel; border.width: 1; border.color: Theme.border
        BoxShadow { z: -1; targetX: 0; targetY: 0; targetW: parent.width; targetH: parent.height; radius: 18; blur: 50; spread: -12; offsetY: 25; color: Theme.blackA(0.3) }
        MouseArea { anchors.fill: parent }

        // the three steps
        Row {
            x: 28; y: 22; spacing: 10
            Repeater {
                model: [root.lt("Dove", "Where"), root.lt("Scegli", "Choose"), root.lt("Fatto", "Done")]
                delegate: Row {
                    required property var modelData
                    required property int index
                    readonly property int cur: root.step === "where" || root.step === "found" ? 0 : root.step === "done" ? 2 : 1
                    spacing: 7
                    Rectangle { width: 22; height: 22; radius: 11
                        color: index === cur ? Theme.gold : index < cur ? Theme.goldA(0.25) : "transparent"; border.width: index === cur ? 0 : 1; border.color: index < cur ? Theme.goldA(0.5) : Theme.wa(0.2)
                        Text { visible: index >= cur; anchors.centerIn: parent; text: String(index + 1); color: index === cur ? Theme.black : Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 11; font.bold: true }
                        Icon { visible: index < cur; anchors.centerIn: parent; name: "check"; size: 12; color: Theme.gold } }
                    Text { anchors.verticalCenter: parent.verticalCenter; text: modelData; color: index === cur ? Theme.white : Theme.silverA(0.45); font.family: Theme.font; font.pixelSize: 12; font.bold: index === cur }
                    Rectangle { visible: index < 2; anchors.verticalCenter: parent.verticalCenter; width: 26; height: 1; color: Theme.wa(0.15) }
                }
            }
        }
        // simple | advanced, while choosing a folder of this appliance
        Rectangle {
            visible: root.step === "folder" || root.step === "adv"
            x: parent.width - 28 - 18 - 20 - width; y: 16; width: 236; height: 34; radius: 17; color: Theme.dark; border.width: 1; border.color: Theme.border
            Rectangle { x: root.step === "folder" ? 3 : parent.width / 2; y: 3; width: parent.width / 2 - 3; height: 28; radius: 14; color: Theme.gold }
            Row { anchors.fill: parent
                Item { width: parent.width / 2; height: parent.height
                    Text { anchors.centerIn: parent; text: root.lt("Semplice", "Simple"); color: root.step === "folder" ? Theme.black : Theme.silver; font.family: Theme.font; font.pixelSize: 12; font.bold: root.step === "folder" }
                    Tap { onClicked: { root.step = "folder"; root.loadCands() } } }
                Item { width: parent.width / 2; height: parent.height
                    Row { anchors.centerIn: parent; spacing: 6
                        Icon { anchors.verticalCenter: parent.verticalCenter; name: "list"; size: 13; color: root.step === "adv" ? Theme.black : Theme.silver }
                        Text { text: root.lt("Avanzate", "Advanced"); color: root.step === "adv" ? Theme.black : Theme.silver; font.family: Theme.font; font.pixelSize: 12; font.bold: root.step === "adv" } }
                    Tap { onClicked: { root.step = "adv"; pickEx.openAt(root.src && root.src.places.length ? root.src.places[0].root : "") } } }
            }
        }
        Item { x: parent.width - 28 - 26; y: 18; width: 30; height: 30
            Icon { anchors.centerIn: parent; name: "x"; size: 18; color: Theme.silverA(0.6) }
            Tap { grow: 8; onClicked: root.close() } }

        // ── where ───────────────────────────────────────────────────────
        Item {
            visible: root.step === "where"
            anchors.fill: parent
            Text { x: 28; y: 60; text: root.lt("Dove si trova la tua musica?", "Where is your music?"); color: Theme.white; font.family: Theme.font; font.pixelSize: 24; font.bold: true }
            Text { x: 28; y: 96; text: root.lt("Scegli la risposta che ti somiglia di più. Se non lo sai, nessun problema: cerco io.", "Pick the answer closest to yours. If you do not know, no problem: I will look."); color: Theme.silverA(0.65); font.family: Theme.font; font.pixelSize: 13 }
            Flow {
                id: chGrid
                x: 28; y: 126; width: parent.width - 56; spacing: 12
                Choice { glyph: "usb"; title: root.lt("Su una chiavetta o disco USB", "On a USB stick or disk"); hint: root.lt("Collegala dietro all'apparecchio: la trovo da solo.", "Plug it in at the back: I will find it."); onPicked: root.toUsb(null) }
                Choice { glyph: "network"; title: root.lt("Sul computer o sul NAS", "On a computer or NAS"); hint: root.lt("Una cartella condivisa in rete (Windows, Mac, NAS).", "A folder shared on the network (Windows, Mac, NAS)."); onPicked: root.step = "net" }
                Choice { glyph: "speaker"; title: root.lt("Dentro questo apparecchio", "Inside this appliance"); hint: root.lt("Sul disco di sistema o su un secondo disco montato dentro.", "On the system disk or a second disk mounted inside."); onPicked: { root.step = "folder"; root.loadCands() } }
                Choice { lead: true; glyph: "sparkles"; title: root.lt("Non lo so: cerca tu", "I don't know: look for me"); hint: root.lt("Guardo USB, rete e dischi e ti mostro cosa c'è.", "I look at USB, network and disks and show you what is there."); onPicked: { root.step = "found"; root.loadCands() } }
            }
            Item {
                x: 28; y: 334; width: parent.width - 56; height: 150; clip: true
                Row { spacing: 8
                    Icon { anchors.verticalCenter: parent.verticalCenter; name: "search"; size: 12; color: Theme.silverA(0.5) }
                    Head { text: root.scanState === "running" ? root.lt("Sto cercando… ", "Looking… ") + root.scanPct + "%" : root.lt("Trovato adesso, senza fare nulla", "Found just now, by itself") } }
                Column {
                    y: 22; width: parent.width; spacing: 8
                    Repeater { model: root.sticks().slice(0, 2)
                        delegate: Line { required property var modelData; glyph: "usb"; title: modelData.name + (modelData.usage ? "  ·  " + root.src.gb(modelData.usage.total) : ""); hint: root.lt("collegata adesso", "plugged in"); action: root.lt("Cosa ne faccio?", "What do I do with it?"); onAct: root.toUsb(modelData) } }
                    Repeater { model: root.hosts.slice(0, Math.max(0, 2 - root.sticks().length))
                        delegate: Line { required property var modelData; glyph: "network"; title: (modelData.name || modelData.ip); hint: modelData.name ? modelData.ip : root.lt("dispositivo in rete", "network device"); action: root.lt("Aggiungi", "Add"); onAct: root.pickHost(modelData.ip, modelData.name) } }
                    Text { visible: !root.sticks().length && !root.hosts.length && root.scanState !== "running"; text: root.lt("Per ora niente: collega una chiavetta o scegli qui sopra.", "Nothing yet: plug in a stick or pick above."); color: Theme.silverA(0.55); font.family: Theme.font; font.pixelSize: 12 }
                }
            }
            Rectangle { x: 28; y: parent.height - 64; width: parent.width - 56; height: 1; color: Theme.border }
            Row { x: 28; y: parent.height - 46; spacing: 8
                Icon { anchors.verticalCenter: parent.verticalCenter; name: "list"; size: 16; color: Theme.gold }
                Text { anchors.verticalCenter: parent.verticalCenter; text: root.lt("Sai già dove sta?", "Know where it is?"); color: Theme.silverA(0.65); font.family: Theme.font; font.pixelSize: 13 }
                Text { anchors.verticalCenter: parent.verticalCenter; text: root.lt("Avanzate: sfoglia tutte le cartelle", "Advanced: browse every folder"); color: Theme.gold; font.family: Theme.font; font.pixelSize: 13; font.underline: true
                    Tap { grow: 8; onClicked: { root.step = "adv"; pickEx.openAt(root.src && root.src.places.length ? root.src.places[0].root : "") } } } }
            SBtn { x: parent.width - 28 - width; y: parent.height - 54; label: root.lt("Annulla", "Cancel"); onClicked: root.close() }
        }

        // ── look for me: everything that was found ──────────────────────
        Item {
            visible: root.step === "found"
            anchors.fill: parent
            Text { x: 28; y: 60; text: root.lt("Ecco cosa ho trovato", "Here is what I found"); color: Theme.white; font.family: Theme.font; font.pixelSize: 24; font.bold: true }
            Text { x: 28; y: 96; text: root.scanState === "running" ? root.lt("Sto ancora guardando la rete… ", "Still looking at the network… ") + root.scanPct + "%" : root.lt("Tocca quello che vuoi aggiungere.", "Tap what you want to add."); color: Theme.silverA(0.65); font.family: Theme.font; font.pixelSize: 13 }
            Flickable {
                x: 28; y: 126; width: parent.width - 56; height: parent.height - 126 - 80; clip: true; contentHeight: fCol.height; boundsBehavior: Flickable.StopAtBounds
                Column {
                    id: fCol; width: parent.width; spacing: 8
                    Repeater { model: root.sticks()
                        delegate: Line { required property var modelData; glyph: "usb"; title: modelData.name; hint: root.lt("chiavetta USB collegata", "USB stick plugged in"); action: root.lt("Cosa ne faccio?", "What do I do with it?"); onAct: root.toUsb(modelData) } }
                    Repeater { model: root.newDisks()
                        delegate: Line { required property var modelData; glyph: "hard-drive"; title: root.lt("Disco nuovo dentro: ", "New disk inside: ") + (modelData.model || modelData.path); hint: root.src ? root.src.gb(modelData.size) : ""; action: root.lt("Preparalo", "Set it up")
                                         onAct: { root.close(); root.src.view = "home" } } }
                    Repeater { model: root.hosts
                        delegate: Line { required property var modelData; glyph: "network"; title: modelData.name || modelData.ip; hint: modelData.name ? modelData.ip : root.lt("dispositivo in rete", "network device"); action: root.lt("Aggiungi", "Add"); onAct: root.pickHost(modelData.ip, modelData.name) } }
                    Repeater { model: root.cands.filter(function(c) { return !c.inLib && !c.whole })
                        delegate: Line { required property var modelData; glyph: "folder"; title: modelData.name; hint: modelData.place; action: root.lt("Aggiungi", "Add"); onAct: root.addFolder(modelData.path) } }
                }
            }
            Rectangle { x: 28; y: parent.height - 72; width: parent.width - 56; height: 1; color: Theme.border }
            SBtn { x: 28; y: parent.height - 56; glyph: "chevron-left"; label: root.lt("Indietro", "Back"); onClicked: root.step = "where" }
            SBtn { x: parent.width - 28 - width; y: parent.height - 56; glyph: "refresh-cw"; label: root.lt("Cerca ancora", "Look again"); onClicked: { root.scan(); root.loadCands() } }
        }

        // ── USB: which stick, or plug one in ────────────────────────────
        Item {
            visible: root.step === "usb"
            anchors.fill: parent
            Text { x: 28; y: 60; text: root.sticks().length ? root.lt("Quale chiavetta?", "Which stick?") : root.lt("Collega la chiavetta", "Plug the stick in"); color: Theme.white; font.family: Theme.font; font.pixelSize: 24; font.bold: true }
            Text { x: 28; y: 96; width: parent.width - 56; wrapMode: Text.WordWrap; text: root.sticks().length ? "" : root.lt("Infilala in una presa USB dietro all'apparecchio: appena la vedo vado avanti da solo.", "Put it in a USB port at the back: as soon as I see it I go on by myself."); color: Theme.silverA(0.65); font.family: Theme.font; font.pixelSize: 13 }
            Column { x: 28; y: 130; width: parent.width - 56; spacing: 8
                Repeater { model: root.sticks()
                    delegate: Line { required property var modelData; glyph: "usb"; title: modelData.name; hint: modelData.usage ? root.src.gb(modelData.usage.total) : ""; action: root.lt("Questa", "This one"); onAct: root.toUsb(modelData) } }
                Repeater { model: root.src ? root.src.usbBad : []
                    delegate: Line { required property var modelData; glyph: "alert-triangle"; title: String(modelData.label || modelData.model || "USB"); hint: modelData.needs_format ? root.lt("Non la so leggere: va formattata da un computer", "I cannot read it: format it on a computer") : String(modelData.error || ""); action: "" } }
                Row { visible: !root.sticks().length; spacing: 10
                    Spinner { active: root.visible && root.step === "usb"; radius: 9; thickness: 2; anchors.verticalCenter: parent.verticalCenter }
                    Text { anchors.verticalCenter: parent.verticalCenter; text: root.lt("Aspetto la chiavetta…", "Waiting for the stick…"); color: Theme.gold; font.family: Theme.font; font.pixelSize: 13 } }
            }
            // as soon as one appears, on to it
            Timer { interval: 1000; repeat: true; running: root.visible && root.step === "usb" && root.sticks().length === 1 && !root.src.usbBad.length; onTriggered: root.toUsb(null) }
            Rectangle { x: 28; y: parent.height - 72; width: parent.width - 56; height: 1; color: Theme.border }
            SBtn { x: 28; y: parent.height - 56; glyph: "chevron-left"; label: root.lt("Indietro", "Back"); onClicked: root.step = "where" }
        }

        // ── network: which device ───────────────────────────────────────
        Item {
            visible: root.step === "net"
            anchors.fill: parent
            Text { x: 28; y: 60; text: root.lt("Su quale computer o NAS?", "On which computer or NAS?"); color: Theme.white; font.family: Theme.font; font.pixelSize: 24; font.bold: true }
            Text { x: 28; y: 96; text: root.scanState === "running" ? root.lt("Sto guardando la rete di casa… ", "Looking at the home network… ") + root.scanPct + "%" : root.lt("Questi sono i dispositivi che condividono cartelle.", "These are the devices sharing folders."); color: Theme.silverA(0.65); font.family: Theme.font; font.pixelSize: 13 }
            Flickable {
                x: 28; y: 126; width: parent.width - 56; height: parent.height - 126 - 80; clip: true; contentHeight: nCol.height; boundsBehavior: Flickable.StopAtBounds
                Column { id: nCol; width: parent.width; spacing: 8
                    Repeater { model: root.hosts
                        delegate: Line { required property var modelData; glyph: "network"; title: modelData.name || modelData.ip; hint: modelData.name ? modelData.ip : ""; action: root.lt("Questo", "This one"); onAct: root.pickHost(modelData.ip, modelData.name) } }
                    Text { visible: !root.hosts.length && root.scanState !== "running"; text: root.lt("Non ho trovato niente. È acceso? Puoi anche scrivere l'indirizzo.", "I found nothing. Is it on? You can also type its address."); color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 13 }
                }
            }
            Rectangle { x: 28; y: parent.height - 72; width: parent.width - 56; height: 1; color: Theme.border }
            Row { x: 28; y: parent.height - 56; spacing: 8
                SBtn { glyph: "chevron-left"; label: root.lt("Indietro", "Back"); onClicked: root.step = "where" }
                SBtn { glyph: "refresh-cw"; label: root.lt("Cerca ancora", "Look again"); on: root.scanState !== "running"; onClicked: root.scan() } }
            SBtn { x: parent.width - 28 - width; y: parent.height - 56; glyph: "keyboard"; label: root.lt("Scrivi l'indirizzo", "Type the address"); onClicked: root.typeHost() }
        }

        // ── network: which shared folder ────────────────────────────────
        Item {
            visible: root.step === "netShares"
            anchors.fill: parent
            Text { x: 28; y: 60; width: parent.width - 56; elide: Text.ElideRight; text: root.lt("Quale cartella di ", "Which folder on ") + (root.hostName || root.host) + "?"; color: Theme.white; font.family: Theme.font; font.pixelSize: 24; font.bold: true }
            Text { x: 28; y: 96; width: parent.width - 56; elide: Text.ElideRight
                   text: root.busy ? root.lt("Chiedo l'elenco delle cartelle…", "Asking for the list of folders…") : root.err ? root.err : root.user ? root.lt("Entrato come ", "Signed in as ") + root.user : root.lt("Le cartelle che condivide in rete.", "The folders it shares on the network.")
                   color: root.err ? Theme.red300 : Theme.silverA(0.65); font.family: Theme.font; font.pixelSize: 13 }
            Flickable {
                x: 28; y: 126; width: parent.width - 56; height: parent.height - 126 - 80; clip: true; contentHeight: sCol.height; boundsBehavior: Flickable.StopAtBounds
                Column { id: sCol; width: parent.width; spacing: 8
                    Repeater { model: root.smbShares
                        delegate: Line { required property var modelData; glyph: "folder"; title: modelData.name; hint: modelData.comment; action: root.lt("Questa", "This one"); onAct: root.pickShare(modelData.name) } }
                }
            }
            Rectangle { x: 28; y: parent.height - 72; width: parent.width - 56; height: 1; color: Theme.border }
            Row { x: 28; y: parent.height - 56; spacing: 8
                SBtn { glyph: "chevron-left"; label: root.lt("Indietro", "Back"); onClicked: { root.step = "net"; root.err = "" } }
                SBtn { glyph: "lock"; label: root.lt("Nome e password", "Name and password"); onClicked: root.askAuth(false, root.loadShares) } }
            SBtn { x: parent.width - 28 - width; y: parent.height - 56; glyph: "keyboard"; label: root.lt("Scrivi il nome", "Type the name"); onClicked: root.typeShare() }
        }

        // ── network: confirm ────────────────────────────────────────────
        Item {
            visible: root.step === "netConfirm"
            anchors.fill: parent
            Text { x: 28; y: 60; text: root.lt("Aggiungo questa cartella?", "Add this folder?"); color: Theme.white; font.family: Theme.font; font.pixelSize: 24; font.bold: true }
            Column { x: 28; y: 110; width: parent.width - 56; spacing: 10
                Line { glyph: "network"; title: root.share; hint: "//" + root.host + "/" + root.share + (root.user ? root.lt(" · utente ", " · user ") + root.user : "") }
                Rectangle { width: parent.width; height: 64; radius: 10; color: root.rw ? Theme.goldA(0.08) : "transparent"; border.width: 1; border.color: root.rw ? Theme.goldA(0.5) : Theme.border
                    Rectangle { x: 14; anchors.verticalCenter: parent.verticalCenter; width: 22; height: 22; radius: 5; color: root.rw ? Theme.gold : Theme.dark; border.width: root.rw ? 0 : 1; border.color: Theme.light
                        Icon { visible: root.rw; anchors.centerIn: parent; name: "check"; size: 14; color: Theme.black } }
                    Text { x: 50; y: 12; text: root.lt("Si può anche scrivere", "Allow writing too"); color: Theme.white; font.family: Theme.font; font.pixelSize: 14; font.bold: true }
                    Text { x: 50; y: 34; width: parent.width - 64; elide: Text.ElideRight; text: root.lt("Serve per salvarci i CD rippati, le playlist, o per sistemare le cartelle da qui.", "Needed to keep ripped CDs or playlists there, or to tidy its folders from here."); color: Theme.silverA(0.55); font.family: Theme.font; font.pixelSize: 11 }
                    Tap { onClicked: root.rw = !root.rw } }
                Text { visible: !!root.err; width: parent.width; wrapMode: Text.WordWrap; text: root.err; color: Theme.red300; font.family: Theme.font; font.pixelSize: 13 }
                Row { visible: root.busy; spacing: 10
                    Spinner { active: root.busy && root.visible; radius: 9; thickness: 2; anchors.verticalCenter: parent.verticalCenter }
                    Text { anchors.verticalCenter: parent.verticalCenter; text: Tr.t("sources.mounting"); color: Theme.gold; font.family: Theme.font; font.pixelSize: 13 } }
            }
            Rectangle { x: 28; y: parent.height - 72; width: parent.width - 56; height: 1; color: Theme.border }
            SBtn { x: 28; y: parent.height - 56; glyph: "chevron-left"; label: root.lt("Indietro", "Back"); onClicked: root.step = "netShares" }
            SBtn { x: parent.width - 28 - width; y: parent.height - 56; lead: true; glyph: "plus"; on: !root.busy; label: root.lt("Aggiungi «", "Add «") + root.share + "»"; onClicked: root.addShare() }
        }

        // ── a folder of this appliance, simple ──────────────────────────
        Item {
            visible: root.step === "folder"
            anchors.fill: parent
            Text { x: 28; y: 64; text: root.lt("Quale cartella aggiungo?", "Which folder do I add?"); color: Theme.white; font.family: Theme.font; font.pixelSize: 24; font.bold: true }
            Text { x: 28; y: 100; text: root.lt("Ho guardato dentro questo apparecchio: queste sono le sue cartelle.", "I looked inside this appliance: these are its folders."); color: Theme.silverA(0.65); font.family: Theme.font; font.pixelSize: 13 }
            Flickable {
                x: 28; y: 130; width: parent.width - 56; height: parent.height - 130 - 80; clip: true; contentHeight: cCol.height; boundsBehavior: Flickable.StopAtBounds
                Column { id: cCol; width: parent.width; spacing: 8
                    Repeater { model: root.newDisks()
                        delegate: Line { required property var modelData; glyph: "hard-drive"; title: root.lt("Disco nuovo dentro: ", "New disk inside: ") + (modelData.model || modelData.path); hint: root.lt("va preparato dalla pagina La tua musica", "set it up from the Your music page"); action: root.lt("Vai", "Go"); onAct: { root.close(); root.src.view = "home" } } }
                    Repeater { model: root.cands
                        delegate: Line { required property var modelData; radio: !modelData.inLib; done: modelData.inLib; chosen: root.chosen === modelData.path
                                         glyph: "folder"; title: modelData.name; hint: modelData.place + "  ›  " + modelData.path.split("/").pop()
                                         action: modelData.inLib ? root.lt("già nella libreria", "already in the library") : ""; onAct: root.chosen = modelData.path } }
                    Text { visible: !root.cands.length; text: root.lt("Guardo le cartelle…", "Looking at the folders…"); color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 13 }
                    Rectangle {
                        width: parent.width; height: 56; radius: 12; color: "transparent"; border.width: 1; border.color: Theme.wa(0.16)
                        Icon { x: 16; anchors.verticalCenter: parent.verticalCenter; name: "list"; size: 18; color: Theme.gold }
                        Text { x: 46; y: 10; text: root.lt("Non è qui? Sfoglia tutte le cartelle", "Not here? Browse every folder"); color: Theme.white; font.family: Theme.font; font.pixelSize: 14; font.bold: true }
                        Text { x: 46; y: 31; text: root.lt("Avanzate: albero, colonne, crea una cartella", "Advanced: tree, columns, make a folder"); color: Theme.silverA(0.55); font.family: Theme.font; font.pixelSize: 11 }
                        Icon { x: parent.width - 30; anchors.verticalCenter: parent.verticalCenter; name: "chevron-right"; size: 16; color: Theme.gold }
                        Tap { onClicked: { root.step = "adv"; pickEx.openAt(root.src && root.src.places.length ? root.src.places[0].root : "") } }
                    }
                }
            }
            Rectangle { x: 28; y: parent.height - 72; width: parent.width - 56; height: 1; color: Theme.border }
            SBtn { x: 28; y: parent.height - 56; glyph: "chevron-left"; label: root.lt("Indietro", "Back"); onClicked: root.step = "where" }
            SBtn { x: parent.width - 28 - width; y: parent.height - 56; lead: true; glyph: "plus"; on: !!root.chosen && !root.busy
                   label: root.chosen ? root.lt("Aggiungi «", "Add «") + root.chosen.split("/").pop() + "»" : root.lt("Aggiungi", "Add"); onClicked: root.addFolder(root.chosen) }
        }

        // ── a folder, advanced: the explorer ────────────────────────────
        Item {
            visible: root.step === "adv"
            anchors.fill: parent
            Text { x: 28; y: 62; text: root.lt("Scegli la cartella", "Pick the folder"); color: Theme.white; font.family: Theme.font; font.pixelSize: 22; font.bold: true }
            SrcExplorer { id: pickEx; picker: true; x: -4; y: 102; width: parent.width + 8; height: parent.height - 102 - 84 }
            Rectangle { x: 28; y: parent.height - 72; width: parent.width - 56; height: 1; color: Theme.border }
            Column { x: 28; y: parent.height - 58; width: parent.width - 470; spacing: 3
                Head { text: root.lt("Cartella scelta", "Chosen folder") }
                Text { width: parent.width; elide: Text.ElideLeft; text: pickEx.path || root.lt("scegline una a sinistra", "pick one on the left"); color: Theme.gold; font.family: Theme.font; font.pixelSize: 13 } }
            Row { x: parent.width - 28 - width; y: parent.height - 56; spacing: 8
                SBtn { glyph: "chevron-left"; label: root.lt("Indietro", "Back"); onClicked: { root.step = "folder"; root.loadCands() } }
                SBtn { lead: true; glyph: "plus"; on: !!pickEx.path && !root.busy; label: root.lt("Aggiungi questa cartella", "Add this folder"); onClicked: root.addFolder(pickEx.path) } }
        }

        // ── done ────────────────────────────────────────────────────────
        Item {
            visible: root.step === "done"
            anchors.fill: parent
            Rectangle { x: parent.width / 2 - 36; y: 120; width: 72; height: 72; radius: 36; color: Theme.goldA(0.14)
                Icon { anchors.centerIn: parent; name: "check"; size: 36; color: Theme.gold } }
            Text { x: 60; y: 214; width: parent.width - 120; horizontalAlignment: Text.AlignHCenter; text: root.lt("Fatto", "Done"); color: Theme.white; font.family: Theme.font; font.pixelSize: 26; font.bold: true }
            Text { x: 80; y: 258; width: parent.width - 160; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; text: root.doneText; color: Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 14; lineHeight: 20; lineHeightMode: Text.FixedHeight }
            SBtn { anchors.horizontalCenter: parent.horizontalCenter; y: parent.height - 80; lead: true; label: root.lt("Chiudi", "Close"); onClicked: root.close() }
        }
    }
}
