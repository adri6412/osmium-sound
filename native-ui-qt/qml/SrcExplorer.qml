// The explorer of Music sources: the places on the left as a tree (this
// appliance's disks, USB, network, with the folders down to the one open and
// the ones inside it), the details view on the right (name, modified, size),
// a command bar on top. In `picker` mode it is the advanced side of the
// add-music wizard: no bin, no ticks, only "new folder" — the folder that is
// open is the one taken (`path`). Reads and changes the disks through
// sources_server's /api/local/*, like the web admin's File page.
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    property bool picker: false
    property string path: ""
    property string parentPath: ""
    property var entries: []
    property bool writable: false
    property bool ram: false
    property bool loading: false
    property var history: []
    property var sel: []                 // selected paths
    property var clip: null              // { op: "copy" | "move", paths: [] }
    property string jobId: ""
    property var job: null
    property string msg: ""

    function lt(it, en) { return I18n.lang === "it" ? it : en }
    function su(p) { return Api.srcBase + p }
    function under(p, r) { return !!r && (p === r || p.indexOf(r + "/") === 0) }
    function places() { return Ui.sources ? Ui.sources.places : [] }
    function placeFor(p) { var ps = places(), best = null; for (var i = 0; i < ps.length; i++) if (ps[i].root && under(p, ps[i].root) && (!best || ps[i].root.length > best.root.length)) best = ps[i]; return best }

    function openAt(p) { history = []; load(p || "", false) }
    function load(next, remember) {
        loading = true
        Api.get(su("/api/local/list?path=" + encodeURIComponent(next || "")), function(ok, d) {
            root.loading = false
            if (!ok || !d || d.success === false) { root.msg = d && d.message ? String(d.message) : lt("Cartella non raggiungibile", "Folder not reachable"); return }
            var p = String(d.path || "")
            if (remember && root.path !== p) { var h = root.history.slice(); h.push(root.path); root.history = h }
            root.path = p; root.parentPath = String(d.parent || ""); root.writable = !!d.writable; root.ram = !!d.ram
            root.entries = (d.entries || []).filter(function(e) { return !root.picker || p === "" || true })
            root.sel = []; root.msg = ""
        }, 15000)
    }
    function reload() { load(path, false) }
    function goBack() { if (!history.length) return; var h = history.slice(); var prev = h.pop(); history = h; load(prev, false) }
    function isSel(p) { return sel.indexOf(p) >= 0 }
    function toggle(p) { var s = sel.slice(), i = s.indexOf(p); if (i >= 0) s.splice(i, 1); else s.push(p); sel = s }
    function selSize() { var n = 0; for (var i = 0; i < entries.length; i++) if (isSel(entries[i].path)) n += Number(entries[i].size || 0); return n }
    function gb(n) { return Ui.sources ? Ui.sources.gb(n) : String(n) }
    function size(e) {
        if (e.dir) return ""
        var n = Number(e.size) || 0
        if (n < 1024) return n + " B"
        if (n < 1048576) return Math.round(n / 1024) + " KB"
        if (n < 1073741824) return (n / 1048576).toFixed(1).replace(".", ",") + " MB"
        return (n / 1073741824).toFixed(1).replace(".", ",") + " GB"
    }
    function when(e) { return e.mtime ? Qt.formatDateTime(new Date(e.mtime * 1000), "dd/MM/yyyy") : "" }
    function glyph(e) {
        if (e.dir) return "folder"
        var n = String(e.name).toLowerCase()
        if (/\.(flac|mp3|wav|m4a|aac|ogg|opus|aiff?|dsf|dff|ape|wv|mpc)$/.test(n)) return "music"
        if (/\.(jpe?g|png|webp|gif|bmp)$/.test(n)) return "image"
        if (/\.(m3u8?|pls|xspf|cue)$/.test(n)) return "list-music"
        return "file"
    }
    function fail(d) { msg = d && d.message ? String(d.message) : lt("Non è riuscito", "That did not work") }
    function startJob(url, body) {
        Api.post(su(url), body, function(ok, d) {
            if (!ok || !d || d.success === false || !d.job) { root.fail(d); root.reload(); return }
            root.jobId = String(d.job); root.job = { state: "running", progress: 0 }
        }, 20000)
    }
    Timer { interval: 700; repeat: true; running: !!root.jobId
        onTriggered: Api.get(root.su("/api/local/job?id=" + root.jobId), function(ok, d) {
            if (!ok || !d) { root.jobId = ""; return }
            root.job = d
            if (d.state === "done" || d.state === "error") {
                root.msg = d.state === "error" ? String(d.message || root.lt("Non è riuscito", "That did not work")) : root.lt("Fatto", "Done") + (d.skipped ? root.lt(" · saltati ", " · skipped ") + d.skipped : "")
                root.jobId = ""; root.reload()
            }
        }, 5000) }

    function newFolder() {
        if (!path || !writable || ram) return
        Ui.vk.openText(lt("Nome della nuova cartella", "Name of the new folder"), "", false, function(ok, text) {
            var name = String(text || "").trim()
            if (!ok || !name) return
            Api.post(root.su("/api/local/mkdir"), { path: root.path, name: name }, function(ok2, d) {
                if (!ok2 || !d || d.success === false) root.fail(d)
                root.load(ok2 && d && d.path ? String(d.path) : root.path, false)
            }, 10000)
        })
    }
    function rename() {
        if (sel.length !== 1) return
        var p = sel[0], old = p.split("/").pop()
        Ui.vk.openText(lt("Nuovo nome", "New name"), old, false, function(ok, text) {
            var name = String(text || "").trim()
            if (!ok || !name || name === old) return
            Api.post(root.su("/api/local/rename"), { path: p, name: name }, function(ok2, d) { if (!ok2 || !d || d.success === false) root.fail(d); root.reload() }, 10000)
        })
    }
    function copySel(op) { if (!sel.length) return; clip = { op: op, paths: sel.slice() }; msg = (op === "copy" ? lt("Copiati: ", "Copied: ") : lt("Tagliati: ", "Cut: ")) + sel.length + lt(" · vai dove vuoi e premi Incolla", " · go where you want and press Paste") }
    function paste() {
        if (!clip || !path || !writable) return
        startJob(clip.op === "copy" ? "/api/local/copy" : "/api/local/move", { paths: clip.paths, dest: path, exists: "keep" })
        clip = null
    }
    function remove() {
        if (!sel.length) return
        var n = sel.length, paths = sel.slice()
        Ui.dialogs.confirm(n === 1 ? lt("Eliminare «" + paths[0].split("/").pop() + "»? Non si può annullare.", "Delete «" + paths[0].split("/").pop() + "»? This cannot be undone.")
                                   : lt("Eliminare " + n + " elementi? Non si può annullare.", "Delete " + n + " items? This cannot be undone."),
                           lt("Elimina", "Delete"), true, function(ok) { if (ok) root.startJob("/api/local/delete", { paths: paths }) })
    }

    component Cmd: Rectangle {
        id: cm
        signal clicked()
        property string glyph
        property string label
        property bool lead: false
        property bool on: true
        property bool danger: false
        height: 38; radius: 9; width: cmRow.implicitWidth + 22
        color: lead ? cmTap.mix(Theme.gold, "#ca8a04") : cmTap.mix(Theme.panel, Theme.light)
        border.width: lead ? 0 : 1; border.color: Theme.border
        opacity: on ? 1 : 0.4
        Row { id: cmRow; anchors.centerIn: parent; spacing: 6
            Icon { anchors.verticalCenter: parent.verticalCenter; name: cm.glyph; size: 15; color: cm.lead ? Theme.black : cm.danger ? Theme.red300 : Theme.silver }
            Text { text: cm.label; color: cm.lead ? Theme.black : cm.danger ? Theme.red300 : Theme.white; font.family: Theme.font; font.pixelSize: 12; font.bold: cm.lead } }
        Tap { id: cmTap; enabled: cm.on; onClicked: cm.clicked() }
    }
    component Sq: Rectangle {
        id: sq
        signal clicked()
        property string glyph
        property bool on: true
        width: 38; height: 38; radius: 9; color: sqTap.mix(Theme.panel, Theme.light); border.width: 1; border.color: Theme.border; opacity: on ? 1 : 0.4
        Icon { anchors.centerIn: parent; name: sq.glyph; size: 17; color: Theme.silver }
        Tap { id: sqTap; enabled: sq.on; onClicked: sq.clicked() }
    }

    // ── command bar ───────────────────────────────────────────────────────
    Row {
        x: 32; y: 0; spacing: 6
        Cmd { lead: true; glyph: "plus"; label: root.lt("Nuova cartella", "New folder"); on: !!root.path && root.writable && !root.ram; onClicked: root.newFolder() }
        Cmd { visible: !root.picker; glyph: "scissors"; label: root.lt("Taglia", "Cut"); on: root.sel.length > 0 && root.writable; onClicked: root.copySel("move") }
        Cmd { visible: !root.picker; glyph: "copy"; label: root.lt("Copia", "Copy"); on: root.sel.length > 0; onClicked: root.copySel("copy") }
        Cmd { visible: !root.picker; glyph: "clipboard"; label: root.lt("Incolla", "Paste") + (root.clip ? " (" + root.clip.paths.length + ")" : ""); on: !!root.clip && !!root.path && root.writable && !root.ram; onClicked: root.paste() }
        Cmd { visible: !root.picker; glyph: "pencil"; label: root.lt("Rinomina", "Rename"); on: root.sel.length === 1 && root.writable; onClicked: root.rename() }
        Cmd { visible: !root.picker; glyph: "trash-2"; label: root.lt("Elimina", "Delete"); danger: true; on: root.sel.length > 0 && root.writable; onClicked: root.remove() }
    }
    // ── back, up, path ────────────────────────────────────────────────────
    Row {
        x: 32; y: 46; spacing: 6
        Sq { glyph: "chevron-left"; on: root.history.length > 0; onClicked: root.goBack() }
        Sq { glyph: "chevron-up"; on: !!root.path; onClicked: root.load(root.parentPath, true) }
    }
    Rectangle {
        x: 32 + 88; y: 46; width: root.width - 32 - 88 - 32; height: 38; radius: 9; color: Theme.panel; border.width: 1; border.color: Theme.border
        readonly property var pl: root.placeFor(root.path)
        Icon { x: 12; anchors.verticalCenter: parent.verticalCenter; name: parent.pl ? parent.pl.glyph : "folder"; size: 15; color: Theme.gold }
        Text {
            x: 36; width: parent.width - 48; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideLeft; textFormat: Text.StyledText
            text: {
                if (!root.path) return root.lt("Tutti i posti", "All places")
                var pl = parent.pl
                if (!pl) return root.path
                var rest = root.path.slice(pl.root.length).split("/").filter(function(x) { return x })
                var head = (pl.group === "dev" ? root.lt("Questo apparecchio", "This appliance") + "  ›  " : "") + pl.name
                if (!rest.length) return "<font color='#d4af37'>" + head + "</font>"
                var last = rest.pop()
                return head + (rest.length ? "  ›  " + rest.join("  ›  ") : "") + "  ›  <font color='#d4af37'>" + last + "</font>"
            }
            color: Theme.silver; font.family: Theme.font; font.pixelSize: 13
        }
    }

    // ── body: tree + details ──────────────────────────────────────────────
    Rectangle {
        id: body
        x: 32; y: 94; width: root.width - 64; height: root.height - y - (root.picker ? 0 : 34); radius: 12
        color: Theme.panel; border.width: 1; border.color: Theme.border; clip: true
        // the tree: groups, places, the folders down to the open one and inside it
        Flickable {
            id: treeF
            x: 6; y: 6; width: 206; height: parent.height - 12
            contentHeight: treeCol.height; clip: true; boundsBehavior: Flickable.StopAtBounds
            Column {
                id: treeCol
                width: parent.width; spacing: 1
                Repeater {
                    model: {
                        var out = [], ps = root.places(), groups = [["dev", root.lt("Questo apparecchio", "This appliance"), "speaker"], ["usb", "USB", "usb"], ["net", root.lt("Rete", "Network"), "network"]]
                        var openPl = root.placeFor(root.path)
                        for (var g = 0; g < groups.length; g++) {
                            var items = ps.filter(function(p) { return p.group === groups[g][0] && p.ok && p.root })
                            if (!items.length) continue
                            out.push({ depth: 0, glyph: groups[g][2], name: groups[g][1], path: "", head: true })
                            for (var i = 0; i < items.length; i++) {
                                var p = items[i], here = openPl && openPl.key === p.key
                                out.push({ depth: 1, glyph: p.glyph, name: p.name, path: p.root, open: here, cur: here && root.path === p.root })
                                if (!here) continue
                                var rest = root.path.slice(p.root.length).split("/").filter(function(x) { return x }), acc = p.root
                                for (var k = 0; k < rest.length; k++) {
                                    acc += "/" + rest[k]
                                    out.push({ depth: 2 + k, glyph: "folder", name: rest[k], path: acc, open: true, cur: acc === root.path })
                                }
                                var subs = root.entries.filter(function(e) { return e.dir })
                                for (var s = 0; s < subs.length && s < 40; s++)
                                    out.push({ depth: 2 + rest.length, glyph: "folder", name: subs[s].name, path: subs[s].path })
                            }
                        }
                        return out
                    }
                    delegate: Rectangle {
                        required property var modelData
                        width: treeCol.width; height: 30; radius: 7
                        color: modelData.cur ? Theme.goldA(0.14) : tnTap.mix(Qt.rgba(0, 0, 0, 0), Theme.wa(0.05))
                        readonly property real ind: 6 + Math.min(modelData.depth, 5) * 13
                        Icon { visible: !modelData.head && modelData.depth > 0; x: parent.ind; anchors.verticalCenter: parent.verticalCenter; name: modelData.open ? "chevron-down" : "chevron-right"; size: 11; color: Theme.silverA(0.45) }
                        Icon { x: parent.ind + (modelData.head ? 0 : 14); anchors.verticalCenter: parent.verticalCenter; name: modelData.glyph; size: 14; color: modelData.head ? Theme.silverA(0.6) : Theme.gold }
                        Text { x: parent.ind + (modelData.head ? 20 : 34); width: parent.width - x - 6; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight
                               text: modelData.name; color: modelData.cur ? Theme.gold : modelData.head ? Theme.silverA(0.6) : Theme.silver
                               font.family: Theme.font; font.pixelSize: modelData.head ? 11 : 12; font.bold: !!modelData.head }
                        Tap { id: tnTap; enabled: !!modelData.path; onClicked: root.load(modelData.path, true) }
                    }
                }
            }
        }
        Rectangle { x: 218; y: 0; width: 1; height: parent.height; color: Theme.border }
        // details
        Item {
            id: list
            x: 226; y: 0; width: parent.width - 226 - 8; height: parent.height
            Item {
                width: parent.width; height: 34
                Text { x: root.picker ? 12 : 40; anchors.verticalCenter: parent.verticalCenter; text: root.lt("Nome", "Name"); color: Theme.white; font.family: Theme.font; font.pixelSize: 11; font.bold: true }
                Text { x: parent.width - 170; anchors.verticalCenter: parent.verticalCenter; text: root.lt("Modificato", "Modified"); color: Theme.silverA(0.55); font.family: Theme.font; font.pixelSize: 11 }
                Text { x: parent.width - 80; width: 72; horizontalAlignment: Text.AlignRight; anchors.verticalCenter: parent.verticalCenter; text: root.lt("Dimensione", "Size"); color: Theme.silverA(0.55); font.family: Theme.font; font.pixelSize: 11 }
                Rectangle { y: 33; width: parent.width; height: 1; color: Theme.border }
            }
            ListView {
                id: lv
                y: 38; width: parent.width; height: parent.height - 40
                clip: true; spacing: 2; boundsBehavior: Flickable.StopAtBounds
                model: root.path ? root.entries : []
                delegate: Rectangle {
                    required property var modelData
                    readonly property bool ticked: !root.picker && root.isSel(modelData.path)
                    width: lv.width; height: 36; radius: 7
                    color: ticked ? Theme.goldA(0.14) : rTap.mix(Qt.rgba(0, 0, 0, 0), Theme.wa(0.05))
                    border.width: ticked ? 1 : 0; border.color: Theme.goldA(0.45)
                    opacity: root.picker && !modelData.dir ? 0.45 : 1
                    Rectangle { visible: !root.picker; x: 8; anchors.verticalCenter: parent.verticalCenter; width: 20; height: 20; radius: 5
                        color: parent.ticked ? Theme.gold : Theme.dark; border.width: parent.ticked ? 0 : 1; border.color: Theme.light
                        Icon { visible: parent.parent.ticked; anchors.centerIn: parent; name: "check"; size: 13; color: Theme.black }
                        Tap { grow: 8; onClicked: root.toggle(modelData.path) } }
                    Icon { x: root.picker ? 12 : 40; anchors.verticalCenter: parent.verticalCenter; name: root.glyph(modelData); size: 16; color: modelData.dir ? Theme.gold : Theme.silverA(0.6) }
                    Text { x: root.picker ? 38 : 66; width: parent.width - x - 180; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; text: modelData.name; color: Theme.white; font.family: Theme.font; font.pixelSize: 13 }
                    Text { x: parent.width - 170; anchors.verticalCenter: parent.verticalCenter; text: root.when(modelData); color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 12 }
                    Text { x: parent.width - 80; width: 72; horizontalAlignment: Text.AlignRight; anchors.verticalCenter: parent.verticalCenter; text: root.size(modelData); color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 12 }
                    RowTap { id: rTap; flick: lv; anchors.leftMargin: root.picker ? 0 : 36
                             onClicked: { if (modelData.dir) root.load(modelData.path, true); else if (!root.picker) root.toggle(modelData.path) } }
                }
                // at the top level: the places themselves
                Text { visible: !root.path && !root.loading; y: 10; x: 12; width: parent.width - 24; wrapMode: Text.WordWrap; text: root.lt("Scegli un posto a sinistra.", "Pick a place on the left."); color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 13 }
                Text { visible: !!root.path && !root.loading && !root.entries.length; y: 10; x: 12; text: root.lt("Cartella vuota", "Empty folder"); color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 13 }
            }
        }
    }
    // ── status bar ────────────────────────────────────────────────────────
    Item {
        visible: !root.picker
        x: 36; y: root.height - 26; width: root.width - 72; height: 22
        Text {
            anchors.verticalCenter: parent.verticalCenter; width: parent.width - 200; elide: Text.ElideRight
            text: root.jobId && root.job ? root.lt("Sto lavorando… ", "Working… ") + (root.job.progress || 0) + "%  " + String(root.job.current || "")
                  : root.msg ? root.msg
                  : root.sel.length ? root.sel.length + root.lt(" selezionati", " selected") + (root.selSize() ? " · " + root.gb(root.selSize()) : "")
                  : root.entries.length + root.lt(" elementi", " items") + (root.path && !root.writable ? root.lt(" · sola lettura", " · read only") : "") + (root.ram ? root.lt(" · nella memoria: sparisce al riavvio", " · in memory: gone at restart") : "")
            color: root.msg || root.sel.length || root.jobId ? Theme.gold : Theme.silverA(0.55); font.family: Theme.font; font.pixelSize: 12
        }
        Text {
            readonly property var pl: root.placeFor(root.path)
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            text: pl && pl.usage && pl.usage.total ? pl.name + ": " + root.gb(pl.usage.free) + root.lt(" liberi", " free") : ""
            color: Theme.silverA(0.55); font.family: Theme.font; font.pixelSize: 12
        }
    }
}
