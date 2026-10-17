// A USB stick: what do I do with it? Listen to it from there (it is already
// in the library: sticks are taken in by themselves), or copy it into the
// appliance so it stays when the stick goes. The copy has a simple side —
// where to, and "only what is missing" or "everything" — and an advanced one:
// two panes, FROM the stick TO the appliance, to pick by hand. The last step
// follows the copy, which carries on by itself once the window is closed
// (the "Your music" page keeps showing it). Copies run as sources_server file
// jobs (/api/local/copy|move with `exists`: skip / replace / keep).
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    anchors.fill: parent
    visible: false
    property string step: "what"      // what | adv | progress
    property var stick: null          // the place (SourcesPage) of the stick
    property bool copyIt: true
    property string mode: "skip"      // skip: only what is missing · replace: everything
    property string dest: ""
    property string jobId: ""
    property var job: null
    property string err: ""
    property bool busy: false
    readonly property var src: Ui.sources

    Component.onCompleted: Ui.importMusic = root
    NavScope { active: root.visible }

    function lt(it, en) { return I18n.lang === "it" ? it : en }
    function su(p) { return Api.srcBase + p }
    function defaultDest() {
        if (!src) return ""
        var dev = src.places.filter(function(p) { return p.group === "dev" && p.ok && p.root && p.rw })
        var second = dev.filter(function(p) { return p.key !== "sys" })
        return (second.length ? second[0] : dev[0] || { root: "" }).root
    }
    function openFor(place) {
        stick = place; copyIt = true; mode = "skip"; err = ""; busy = false; jobId = ""; job = null
        dest = defaultDest(); step = "what"; visible = true
    }
    function follow(id) { jobId = id; step = "progress"; visible = true }
    function close() { visible = false }
    function destTop() {
        var ps = src ? src.places : [], best = null
        for (var i = 0; i < ps.length; i++) if (ps[i].root && src.under(dest, ps[i].root) && (!best || ps[i].root.length > best.root.length)) best = ps[i]
        return best ? best.root : dest
    }
    function destName(p) {
        if (!src || !p) return p
        var ps = src.places, best = null
        for (var i = 0; i < ps.length; i++) if (ps[i].root && src.under(p, ps[i].root) && (!best || ps[i].root.length > best.root.length)) best = ps[i]
        if (!best) return p
        var rest = p.slice(best.root.length).split("/").filter(function(x) { return x })
        return (best.group === "dev" ? lt("Questo apparecchio", "This appliance") + "  ›  " : "") + best.name + (rest.length ? "  ›  " + rest.join("  ›  ") : "")
    }
    function start(op, paths, to, exists) {
        if (!paths.length || !to) return
        busy = true; err = ""
        Api.post(su("/api/local/" + op), { paths: paths, dest: to, exists: exists }, function(ok, d) {
            root.busy = false
            if (!ok || !d || d.success === false || !d.job) { root.err = d && d.message ? String(d.message) : lt("Non è riuscito", "That did not work"); return }
            root.jobId = String(d.job); root.job = { state: "running", progress: 0 }; root.step = "progress"
            if (root.src) root.src.jobId = root.jobId
        }, 20000)
    }
    // simple: everything on the stick, into the chosen folder
    function copyAll() {
        if (!stick) return
        busy = true
        Api.get(su("/api/local/list?path=" + encodeURIComponent(stick.root)), function(ok, d) {
            root.busy = false
            if (!ok || !d || !d.entries) { root.err = lt("Non riesco a leggere la chiavetta", "I cannot read the stick"); return }
            root.start("copy", d.entries.map(function(e) { return String(e.path) }), root.dest, root.mode)
        }, 15000)
    }
    function listenOnly() {
        if (stick && !stick.lib) Api.post(su("/api/sources/local"), { path: stick.root }, function() { if (root.src) root.src.load() }, 20000)
        close()
    }
    Timer { interval: 800; repeat: true; running: root.visible && !!root.jobId && root.step === "progress"
        onTriggered: Api.get(root.su("/api/local/job?id=" + root.jobId), function(ok, d) {
            if (!ok || !d) return
            root.job = d
            if (d.state === "done" || d.state === "error") { if (root.src) root.src.load() }
        }, 5000) }

    component Way: Rectangle {
        id: wy
        signal picked()
        property string glyph; property string title; property string hint; property string foot; property bool chosen: false; property bool best: false
        width: (parent.width - 12) / 2; height: 112; radius: 14
        color: wyTap.mix(chosen ? Theme.goldA(0.10) : Theme.dark, Theme.light)
        border.width: chosen ? 1.5 : 1; border.color: chosen ? Theme.gold : Theme.border
        Rectangle { x: 16; y: 16; width: 44; height: 44; radius: 22; color: wy.chosen ? Theme.gold : Theme.goldA(0.12)
            Icon { anchors.centerIn: parent; name: wy.glyph; size: 21; color: wy.chosen ? Theme.black : Theme.gold } }
        Text { x: 74; y: 16; width: parent.width - 90 - (bestR.visible ? bestR.width + 8 : 0); elide: Text.ElideRight; text: wy.title; color: Theme.white; font.family: Theme.font; font.pixelSize: 15; font.bold: true }
        Text { x: 74; y: 39; width: parent.width - 90; wrapMode: Text.WordWrap; maximumLineCount: 2; text: wy.hint; color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 12 }
        Text { x: 74; y: parent.height - 28; width: parent.width - 90; elide: Text.ElideRight; text: wy.foot; color: wy.chosen ? Theme.gold : Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 12 }
        Rectangle { id: bestR; visible: wy.best; x: parent.width - 14 - width; y: 16; width: bT.implicitWidth + 16; height: 22; radius: 11; color: Theme.gold
            Text { id: bT; anchors.centerIn: parent; text: root.lt("consigliata", "recommended"); color: Theme.black; font.family: Theme.font; font.pixelSize: 11; font.bold: true } }
        Tap { id: wyTap; onClicked: wy.picked() }
    }
    component Radio: Rectangle {
        id: rd
        signal picked()
        property string title; property string hint; property bool chosen: false
        width: parent.width; height: 44; radius: 10
        color: chosen ? Theme.goldA(0.08) : rdTap.mix(Qt.rgba(0, 0, 0, 0), Theme.wa(0.04)); border.width: 1; border.color: chosen ? Theme.goldA(0.5) : Theme.border
        Rectangle { x: 14; anchors.verticalCenter: parent.verticalCenter; width: 20; height: 20; radius: 10; color: "transparent"; border.width: 2; border.color: rd.chosen ? Theme.gold : Theme.wa(0.25)
            Rectangle { visible: rd.chosen; anchors.centerIn: parent; width: 9; height: 9; radius: 5; color: Theme.gold } }
        Text { x: 46; width: parent.width - 60; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; textFormat: Text.StyledText; text: "<b>" + rd.title + "</b>   <font color='#8a8a8a'>" + rd.hint + "</font>"; color: Theme.white; font.family: Theme.font; font.pixelSize: 13 }
        Tap { id: rdTap; onClicked: rd.picked() }
    }
    component Head: Text { color: Theme.silverA(0.45); font.family: Theme.font; font.pixelSize: 10; font.bold: true; font.capitalization: Font.AllUppercase; font.letterSpacing: 1 }
    component Seg: Rectangle {
        id: sg
        property var items: []          // [[value, label]]
        property string value
        signal pick(string v)
        height: 34; radius: 17; width: sgRow.implicitWidth + 6; color: Theme.dark; border.width: 1; border.color: Theme.border
        Row { id: sgRow; x: 3; y: 3; spacing: 0
            Repeater { model: sg.items
                delegate: Rectangle { required property var modelData; height: 28; radius: 14; width: sgT.implicitWidth + 28; color: sg.value === modelData[0] ? Theme.gold : "transparent"
                    Text { id: sgT; anchors.centerIn: parent; text: modelData[1]; color: sg.value === modelData[0] ? Theme.black : Theme.silver; font.family: Theme.font; font.pixelSize: 12; font.bold: sg.value === modelData[0] }
                    Tap { onClicked: sg.pick(modelData[0]) } } } }
    }

    Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0, 0, 0.72); MouseArea { anchors.fill: parent; onClicked: root.close() } }
    Rectangle {
        id: card
        width: root.step === "adv" ? Math.min(1010, root.width - 32) : Math.min(860, root.width - 40)
        height: root.step === "adv" ? Math.min(584, root.height - 16) : Math.min(568, root.height - 24)
        anchors.centerIn: parent
        radius: 18; color: Theme.panel; border.width: 1; border.color: Theme.border
        BoxShadow { z: -1; targetX: 0; targetY: 0; targetW: parent.width; targetH: parent.height; radius: 18; blur: 50; spread: -12; offsetY: 25; color: Theme.blackA(0.3) }
        MouseArea { anchors.fill: parent }

        Row {
            x: 28; y: 22; spacing: 10
            Repeater {
                model: [root.lt("Dove", "Where"), root.lt("Cosa faccio", "What to do"), root.lt("Fatto", "Done")]
                delegate: Row {
                    required property var modelData
                    required property int index
                    readonly property int cur: root.step === "progress" ? 2 : 1
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
        Rectangle {
            visible: root.step !== "progress" && root.copyIt
            x: parent.width - 28 - 18 - 20 - width; y: 16; width: 236; height: 34; radius: 17; color: Theme.dark; border.width: 1; border.color: Theme.border
            Rectangle { x: root.step === "what" ? 3 : parent.width / 2; y: 3; width: parent.width / 2 - 3; height: 28; radius: 14; color: Theme.gold }
            Row { anchors.fill: parent
                Item { width: parent.width / 2; height: parent.height
                    Text { anchors.centerIn: parent; text: root.lt("Semplice", "Simple"); color: root.step === "what" ? Theme.black : Theme.silver; font.family: Theme.font; font.pixelSize: 12; font.bold: root.step === "what" }
                    Tap { onClicked: root.step = "what" } }
                Item { width: parent.width / 2; height: parent.height
                    Row { anchors.centerIn: parent; spacing: 6
                        Icon { anchors.verticalCenter: parent.verticalCenter; name: "copy"; size: 13; color: root.step === "adv" ? Theme.black : Theme.silver }
                        Text { text: root.lt("Avanzate", "Advanced"); color: root.step === "adv" ? Theme.black : Theme.silver; font.family: Theme.font; font.pixelSize: 12; font.bold: root.step === "adv" } }
                    Tap { onClicked: root.toAdv() } }
            }
        }
        Item { x: parent.width - 28 - 26; y: 18; width: 30; height: 30
            Icon { anchors.centerIn: parent; name: "x"; size: 18; color: Theme.silverA(0.6) }
            Tap { grow: 8; onClicked: root.close() } }

        // ── what to do, simple ──────────────────────────────────────────
        Item {
            visible: root.step === "what"
            anchors.fill: parent
            Text { x: 28; y: 62; width: parent.width - 56; elide: Text.ElideRight; text: (root.stick ? root.stick.name : "USB") + root.lt(": cosa ne faccio?", ": what do I do with it?"); color: Theme.white; font.family: Theme.font; font.pixelSize: 24; font.bold: true }
            Text { x: 28; y: 98; text: root.stick && root.stick.usage ? root.lt("Contiene ", "It holds ") + root.src.gb(root.stick.usage.total - root.stick.usage.free) + root.lt(". Puoi ascoltarla da lì o copiarla dentro l'apparecchio.", ". Listen to it from there, or copy it into the appliance.") : ""; color: Theme.silverA(0.65); font.family: Theme.font; font.pixelSize: 13 }
            Row {
                x: 28; y: 128; width: parent.width - 56; spacing: 12
                Way { chosen: !root.copyIt; glyph: "usb"; title: root.lt("Ascoltala dalla chiavetta", "Listen from the stick"); hint: root.lt("Resta sulla chiavetta: si sente finché è collegata.", "It stays on the stick: it plays while it is plugged in.")
                      foot: root.stick && root.stick.lib ? root.lt("È già nella libreria", "Already in the library") : root.lt("La aggiungo alla libreria", "I add it to the library"); onPicked: root.copyIt = false }
                Way { chosen: root.copyIt; best: true; glyph: "copy"; title: root.lt("Copiala nell'apparecchio", "Copy it into the appliance"); hint: root.lt("Resta anche quando togli la chiavetta.", "It stays when the stick goes.")
                      foot: { var p = root.src ? root.src.places.filter(function(x) { return x.root && root.src.under(root.dest, x.root) }) : []; return p.length && p[p.length - 1].usage ? p[p.length - 1].name + ": " + root.src.gb(p[p.length - 1].usage.free) + root.lt(" liberi", " free") : "" }
                      onPicked: root.copyIt = true }
            }
            Head { visible: root.copyIt; x: 28; y: 258; text: root.lt("Dove", "Where") }
            Rectangle {
                visible: root.copyIt
                x: 28; y: 274; width: parent.width - 56; height: 44; radius: 10; color: Theme.dark; border.width: 1; border.color: Theme.border
                Icon { x: 14; anchors.verticalCenter: parent.verticalCenter; name: "folder"; size: 17; color: Theme.gold }
                Text { x: 42; width: parent.width - 42 - 100; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideLeft; text: root.destName(root.dest); color: Theme.white; font.family: Theme.font; font.pixelSize: 13 }
                SBtn { small: true; x: parent.width - 8 - width; anchors.verticalCenter: parent.verticalCenter; label: root.lt("Cambia", "Change")
                       onClicked: if (Ui.folderChooser) Ui.folderChooser.openAt(root.dest, root.lt("Copia qui", "Copy here"), function(p) { root.dest = p }) }
            }
            Head { visible: root.copyIt; x: 28; y: 332; text: root.lt("Cosa", "What") }
            Column {
                visible: root.copyIt
                x: 28; y: 348; width: parent.width - 56; spacing: 8
                Radio { chosen: root.mode === "skip"; title: root.lt("Solo quello che manca", "Only what is missing"); hint: root.lt("quello che c'è già lo salto", "what is already there is skipped"); onPicked: root.mode = "skip" }
                Radio { chosen: root.mode === "replace"; title: root.lt("Tutto", "Everything"); hint: root.lt("quello che c'è già lo sostituisco", "what is already there is replaced"); onPicked: root.mode = "replace" }
            }
            Text { visible: !!root.err; x: 28; y: parent.height - 96; width: parent.width - 56; elide: Text.ElideRight; text: root.err; color: Theme.red300; font.family: Theme.font; font.pixelSize: 13 }
            Rectangle { x: 28; y: parent.height - 72; width: parent.width - 56; height: 1; color: Theme.border }
            Row { visible: root.copyIt; x: 28; y: parent.height - 48; spacing: 8
                Icon { anchors.verticalCenter: parent.verticalCenter; name: "copy"; size: 15; color: Theme.gold }
                Text { anchors.verticalCenter: parent.verticalCenter; text: root.lt("Avanzate: scegli tu cosa copiare e dove", "Advanced: pick what to copy and where"); color: Theme.gold; font.family: Theme.font; font.pixelSize: 13; font.underline: true
                    Tap { grow: 8; onClicked: root.toAdv() } } }
            Row { x: parent.width - 28 - width; y: parent.height - 56; spacing: 8
                SBtn { glyph: "chevron-left"; label: root.lt("Indietro", "Back"); onClicked: { root.close(); if (Ui.addMusic) Ui.addMusic.open() } }
                SBtn { lead: true; glyph: root.copyIt ? "copy" : "check"; on: !root.busy && (!root.copyIt || !!root.dest)
                       label: !root.copyIt ? (root.stick && root.stick.lib ? root.lt("Va bene così", "Fine as it is") : root.lt("Aggiungi alla libreria", "Add to the library")) : root.lt("Copia", "Copy")
                       onClicked: if (root.copyIt) root.copyAll(); else root.listenOnly() } }
        }

        // ── what to do, advanced: two panes ─────────────────────────────
        Item {
            visible: root.step === "adv"
            anchors.fill: parent
            Text { x: 28; y: 62; text: root.lt("Scegli cosa copiare e dove", "Pick what to copy and where"); color: Theme.white; font.family: Theme.font; font.pixelSize: 22; font.bold: true }
            SrcFileList { id: fromP; tag: root.lt("DA", "FROM"); active: true; x: 28; y: 104; width: (parent.width - 56 - 96) / 2; height: parent.height - 104 - 84 }
            Column {
                x: 28 + fromP.width + 10; y: fromP.y + fromP.height / 2 - height / 2; width: 76; spacing: 8
                Rectangle { anchors.horizontalCenter: parent.horizontalCenter; width: 52; height: 52; radius: 26; color: Theme.gold
                    Icon { anchors.centerIn: parent; name: "chevron-right"; size: 26; color: Theme.black } }
                Text { anchors.horizontalCenter: parent.horizontalCenter; text: root.lt("va in", "goes to"); color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 12 }
            }
            SrcFileList { id: toP; tag: root.lt("A", "TO"); selectable: false; x: 28 + fromP.width + 96; y: 104; width: fromP.width; height: fromP.height
                          mark: fromP.sel.map(function(p) { return p.split("/").pop() }) }
            Rectangle { x: 28; y: parent.height - 72; width: parent.width - 56; height: 1; color: Theme.border }
            Column { x: 28; y: parent.height - 62; spacing: 4
                Head { text: root.lt("Se c'è già", "If it is already there") }
                Seg { items: [["skip", root.lt("Salta", "Skip")], ["replace", root.lt("Sostituisci", "Replace")], ["keep", root.lt("Tieni entrambi", "Keep both")]]
                      value: root.mode; onPick: (v) => root.mode = v } }
            Row { x: parent.width - 28 - width; y: parent.height - 56; spacing: 8
                SBtn { glyph: "chevron-left"; label: root.lt("Indietro", "Back"); onClicked: root.step = "what" }
                SBtn { label: root.lt("Sposta", "Move"); on: fromP.sel.length > 0 && toP.writable && !root.busy; onClicked: root.start("move", fromP.sel, toP.path, root.mode) }
                SBtn { lead: true; glyph: "copy"; on: fromP.sel.length > 0 && toP.writable && !root.busy; label: root.lt("Copia", "Copy"); onClicked: root.start("copy", fromP.sel, toP.path, root.mode) } }
        }

        // ── the copy, going on by itself ────────────────────────────────
        Item {
            visible: root.step === "progress"
            anchors.fill: parent
            readonly property var j: root.job || ({})
            readonly property bool over: j.state === "done" || j.state === "error"
            Text { x: 28; y: 62; text: parent.j.state === "error" ? root.lt("La copia si è fermata", "The copy stopped") : parent.over ? root.lt("Copia finita", "Copy finished") : root.lt("Sto copiando la musica", "Copying the music"); color: Theme.white; font.family: Theme.font; font.pixelSize: 24; font.bold: true }
            Text { x: 28; y: 98; width: parent.width - 56; wrapMode: Text.WordWrap
                   text: parent.j.state === "error" ? String(parent.j.message || "")
                         : parent.over ? root.lt("La libreria si aggiorna da sola: i brani compaiono in Musica fra poco. Ora puoi togliere la chiavetta.", "The library updates by itself: the tracks show up in Music shortly. You can take the stick out now.")
                         : root.lt("Puoi chiudere questa finestra: continuo da solo e i brani compaiono in Musica a copia finita. Non togliere la chiavetta finché non ho finito.", "You can close this window: I carry on by myself and the tracks show up in Music when it is done. Do not take the stick out before I am finished.")
                   color: parent.j.state === "error" ? Theme.red300 : Theme.silverA(0.65); font.family: Theme.font; font.pixelSize: 13 }
            Rectangle {
                x: 28; y: 160; width: parent.width - 56; height: 96; radius: 12; color: Theme.dark; border.width: 1; border.color: Theme.border
                id: pbox
                readonly property var j: parent.j
                Text { x: 16; y: 14; text: (pbox.j.progress || 0) + "%" + (pbox.j.total ? "  ·  " + root.src.gb(pbox.j.done || 0) + root.lt(" di ", " of ") + root.src.gb(pbox.j.total) : ""); color: Theme.white; font.family: Theme.font; font.pixelSize: 16; font.bold: true }
                Text { x: parent.width - 16 - width; y: 16; text: pbox.j.skipped ? root.lt("saltati perché c'erano già: ", "skipped, already there: ") + pbox.j.skipped : ""; color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 12 }
                Rectangle { x: 16; y: 46; width: parent.width - 32; height: 8; radius: 4; color: Theme.light
                    Rectangle { width: parent.width * Math.min(1, (pbox.j.progress || 0) / 100); height: parent.height; radius: 4; color: pbox.j.state === "error" ? Theme.red400 : Theme.gold } }
                Text { x: 16; y: 66; width: parent.width - 32; elide: Text.ElideMiddle; text: pbox.j.current ? root.lt("Adesso: ", "Now: ") + pbox.j.current : ""; color: Theme.silverA(0.55); font.family: Theme.font; font.pixelSize: 12 }
            }
            Rectangle { x: 28; y: parent.height - 72; width: parent.width - 56; height: 1; color: Theme.border }
            SBtn { x: parent.width - 28 - width; y: parent.height - 56; lead: true; label: parent.over ? root.lt("Chiudi", "Close") : root.lt("Chiudi, continua da solo", "Close, carry on by yourself"); onClicked: root.close() }
        }
    }
    function toAdv() {
        if (!stick) return
        step = "adv"; mode = mode === "replace" ? "replace" : "skip"
        fromP.openAt(stick.root); toP.openAt(dest, destTop())
    }
}
