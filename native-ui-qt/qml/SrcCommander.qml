// The file manager of Music sources: two panes side by side, each showing a
// place (tap its name to show another one). Tapping a pane makes it the
// active one: Copy and Move go FROM it TO the other (the arrow says which
// way), New folder / Rename / Delete act on it. "If it is already there" says
// what a copy does with a name the other pane already has: skip it, replace
// it, keep both. The operation runs on the appliance (sources_server file
// jobs) and its line stays at the bottom while it goes.
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    property int act: 0                       // 0: left pane active, 1: right
    readonly property var from: act === 0 ? lp : rp
    readonly property var to: act === 0 ? rp : lp
    property string exists: "skip"
    property string jobId: ""
    property var job: null
    property string msg: ""
    property bool bad: false

    function lt(it, en) { return I18n.lang === "it" ? it : en }
    function su(p) { return Api.srcBase + p }
    // left on `leftPath`, right on another place (the first one that is not it)
    function openAt(leftPath) {
        var ps = Ui.sources ? Ui.sources.places.filter(function(p) { return p.ok && p.root }) : []
        var lpPlace = null
        for (var i = 0; i < ps.length; i++) if (Ui.sources.under(leftPath, ps[i].root)) lpPlace = ps[i]
        var other = ps.filter(function(p) { return !lpPlace || p.key !== lpPlace.key })
        lp.openAt(leftPath || (ps[0] ? ps[0].root : ""), lpPlace ? lpPlace.root : leftPath)
        var r = other.length ? other[0] : (ps[0] || { root: "" })
        rp.openAt(r.root, r.root)
        act = 0; msg = ""
    }
    function say(t, b) { msg = t; bad = !!b }
    function start(url, body) {
        Api.post(su(url), body, function(ok, d) {
            if (!ok || !d || d.success === false || !d.job) { root.say(d && d.message ? String(d.message) : root.lt("Non è riuscito", "That did not work"), true); lp.reload(); rp.reload(); return }
            root.jobId = String(d.job); root.job = { state: "running", progress: 0 }; root.msg = ""
        }, 20000)
    }
    Timer { interval: 700; repeat: true; running: !!root.jobId
        onTriggered: Api.get(root.su("/api/local/job?id=" + root.jobId), function(ok, d) {
            if (!ok || !d) { root.jobId = ""; return }
            root.job = d
            if (d.state === "done" || d.state === "error") {
                root.say(d.state === "error" ? String(d.message || root.lt("Non è riuscito", "That did not work")) : root.lt("Fatto", "Done") + (d.skipped ? root.lt(" · saltati perché c'erano già: ", " · skipped, already there: ") + d.skipped : ""), d.state === "error")
                root.jobId = ""; lp.reload(); rp.reload(); if (Ui.sources) Ui.sources.load()
            }
        }, 5000) }
    function copyMove(op) {
        if (!from.sel.length || !to.path || !to.writable) return
        start(op === "copy" ? "/api/local/copy" : "/api/local/move", { paths: from.sel.slice(), dest: to.path, exists: exists })
    }
    function newFolder() {
        var p = from.path
        if (!p || !from.writable || from.ram) return
        Ui.vk.openText(lt("Nome della nuova cartella", "Name of the new folder"), "", false, function(ok, text) {
            var name = String(text || "").trim()
            if (!ok || !name) return
            Api.post(root.su("/api/local/mkdir"), { path: p, name: name }, function(ok2, d) { if (!ok2 || !d || d.success === false) root.say(d && d.message ? String(d.message) : root.lt("Non è riuscito", "That did not work"), true); root.from.reload() }, 10000)
        })
    }
    function rename() {
        if (from.sel.length !== 1) return
        var p = from.sel[0], old = p.split("/").pop()
        Ui.vk.openText(lt("Nuovo nome", "New name"), old, false, function(ok, text) {
            var name = String(text || "").trim()
            if (!ok || !name || name === old) return
            Api.post(root.su("/api/local/rename"), { path: p, name: name }, function(ok2, d) { if (!ok2 || !d || d.success === false) root.say(d && d.message ? String(d.message) : root.lt("Non è riuscito", "That did not work"), true); root.from.reload() }, 10000)
        })
    }
    function remove() {
        var paths = from.sel.slice(), n = paths.length
        if (!n) return
        Ui.dialogs.confirm(n === 1 ? lt("Eliminare «" + paths[0].split("/").pop() + "»? Non si può annullare.", "Delete «" + paths[0].split("/").pop() + "»? This cannot be undone.")
                                   : lt("Eliminare " + n + " elementi? Non si può annullare.", "Delete " + n + " items? This cannot be undone."),
                           lt("Elimina", "Delete"), true, function(ok) { if (ok) root.start("/api/local/delete", { paths: paths }) })
    }

    component Cmd: Rectangle {
        id: cm
        signal clicked()
        property string glyph; property string label; property bool lead: false; property bool on: true; property bool danger: false
        height: 38; radius: 9; width: cmRow.implicitWidth + 22
        color: lead ? cmTap.mix(Theme.gold, "#ca8a04") : cmTap.mix(Theme.panel, Theme.light)
        border.width: lead ? 0 : 1; border.color: Theme.border
        opacity: on ? 1 : 0.4
        Row { id: cmRow; anchors.centerIn: parent; spacing: 6
            Icon { anchors.verticalCenter: parent.verticalCenter; name: cm.glyph; size: 15; color: cm.lead ? Theme.black : cm.danger ? Theme.red300 : Theme.silver }
            Text { text: cm.label; color: cm.lead ? Theme.black : cm.danger ? Theme.red300 : Theme.white; font.family: Theme.font; font.pixelSize: 12; font.bold: cm.lead } }
        Tap { id: cmTap; enabled: cm.on; onClicked: cm.clicked() }
    }

    // ── commands on the active pane, and what to do with names already there
    Row {
        x: 32; y: 0; spacing: 6
        Cmd { glyph: "plus"; label: root.lt("Nuova cartella", "New folder"); on: !!root.from.path && root.from.writable && !root.from.ram; onClicked: root.newFolder() }
        Cmd { glyph: "pencil"; label: root.lt("Rinomina", "Rename"); on: root.from.sel.length === 1 && root.from.writable; onClicked: root.rename() }
        Cmd { glyph: "trash-2"; label: root.lt("Elimina", "Delete"); danger: true; on: root.from.sel.length > 0 && root.from.writable; onClicked: root.remove() }
    }
    Row {
        x: root.width - 32 - width; y: 2; spacing: 8
        Text { anchors.verticalCenter: parent.verticalCenter; text: root.lt("Se c'è già", "If already there"); color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 10; font.bold: true; font.capitalization: Font.AllUppercase; font.letterSpacing: 1 }
        Rectangle {
            height: 34; radius: 17; width: exRow.implicitWidth + 6; color: Theme.dark; border.width: 1; border.color: Theme.border
            Row { id: exRow; x: 3; y: 3
                Repeater {
                    model: [["skip", root.lt("Salta", "Skip")], ["replace", root.lt("Sostituisci", "Replace")], ["keep", root.lt("Tieni entrambi", "Keep both")]]
                    delegate: Rectangle { required property var modelData; height: 28; radius: 14; width: exT.implicitWidth + 22; color: root.exists === modelData[0] ? Theme.gold : "transparent"
                        Text { id: exT; anchors.centerIn: parent; text: modelData[1]; color: root.exists === modelData[0] ? Theme.black : Theme.silver; font.family: Theme.font; font.pixelSize: 11; font.bold: root.exists === modelData[0] }
                        Tap { onClicked: root.exists = modelData[0] } }
                }
            }
        }
    }

    // ── the two panes ─────────────────────────────────────────────────────
    readonly property real paneW: (width - 64 - 96) / 2
    SrcFileList { id: lp; tag: root.act === 0 ? root.lt("DA", "FROM") : root.lt("A", "TO"); active: root.act === 0; canChangePlace: true
                  x: 32; y: 48; width: root.paneW; height: root.height - 48 - 34
                  mark: root.act === 1 ? rp.sel.map(function(p) { return p.split("/").pop() }) : []
                  onActivated: root.act = 0 }
    Column {
        x: 32 + root.paneW + 10; y: lp.y + lp.height / 2 - height / 2; width: 76; spacing: 10
        Rectangle { width: 76; height: 64; radius: 12; color: cpTap.mix(Theme.gold, "#ca8a04"); opacity: root.from.sel.length && root.to.writable && !root.jobId ? 1 : 0.4
            Column { anchors.centerIn: parent; spacing: 2
                Icon { anchors.horizontalCenter: parent.horizontalCenter; name: root.act === 0 ? "chevron-right" : "chevron-left"; size: 22; color: Theme.black }
                Text { anchors.horizontalCenter: parent.horizontalCenter; text: root.lt("Copia", "Copy"); color: Theme.black; font.family: Theme.font; font.pixelSize: 13; font.bold: true } }
            Tap { id: cpTap; enabled: root.from.sel.length > 0 && root.to.writable && !root.jobId; onClicked: root.copyMove("copy") } }
        Rectangle { width: 76; height: 64; radius: 12; color: mvTap.mix(Theme.panel, Theme.light); border.width: 1; border.color: Theme.border; opacity: root.from.sel.length && root.to.writable && root.from.writable && !root.jobId ? 1 : 0.4
            Column { anchors.centerIn: parent; spacing: 2
                Icon { anchors.horizontalCenter: parent.horizontalCenter; name: root.act === 0 ? "chevron-right" : "chevron-left"; size: 22; color: Theme.silver }
                Text { anchors.horizontalCenter: parent.horizontalCenter; text: root.lt("Sposta", "Move"); color: Theme.white; font.family: Theme.font; font.pixelSize: 13 } }
            Tap { id: mvTap; enabled: root.from.sel.length > 0 && root.to.writable && root.from.writable && !root.jobId; onClicked: root.copyMove("move") } }
    }
    SrcFileList { id: rp; tag: root.act === 1 ? root.lt("DA", "FROM") : root.lt("A", "TO"); active: root.act === 1; canChangePlace: true
                  x: 32 + root.paneW + 96; y: 48; width: root.paneW; height: lp.height
                  mark: root.act === 0 ? lp.sel.map(function(p) { return p.split("/").pop() }) : []
                  onActivated: root.act = 1 }

    // ── the operation going on, or how it went ────────────────────────────
    Item {
        x: 36; y: root.height - 26; width: root.width - 72; height: 22
        Text { anchors.verticalCenter: parent.verticalCenter; width: parent.width - (pg.visible ? 220 : 0); elide: Text.ElideRight
               text: root.jobId && root.job ? root.lt("Sto lavorando… ", "Working… ") + (root.job.progress || 0) + "%  " + String(root.job.current || "")
                     : root.msg ? root.msg : root.lt("Tocca un pannello per sceglierlo: Copia e Sposta vanno da lui all'altro.", "Tap a pane to pick it: Copy and Move go from it to the other one.")
               color: root.bad ? Theme.red300 : root.jobId || root.msg ? Theme.gold : Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 12 }
        Rectangle { id: pg; visible: !!root.jobId; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; width: 200; height: 6; radius: 3; color: Theme.light
            Rectangle { width: parent.width * Math.min(1, ((root.job && root.job.progress) || 0) / 100); height: parent.height; radius: 3; color: Theme.gold } }
    }
}
