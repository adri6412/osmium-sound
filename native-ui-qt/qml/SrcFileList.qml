// One pane of the two-pane file manager (SrcCommander.qml) and of the USB
// copy (ImportWizard.qml): a tag, the place it shows (tap to change it), up,
// the path, the folder's entries with a tick each when `selectable`, and a
// footer line. Reads sources_server's /api/local/list.
import QtQuick
import Hifi
import Hifi.Ui

Rectangle {
    id: root
    signal activated()
    property string tag
    property bool selectable: true
    property bool active: false
    property bool canChangePlace: false
    property string path: ""
    property string parentPath: ""
    property string rootPath: ""        // not above this one
    property var entries: []
    property var sel: []
    property bool writable: false
    property bool ram: false
    property var mark: []               // names to flag "already there"
    property bool choosing: false
    color: Theme.panel; radius: 12; border.width: active ? 1.5 : 1; border.color: active ? Theme.goldA(0.6) : Theme.border

    function lt(it, en) { return I18n.lang === "it" ? it : en }
    function openAt(p, top) { rootPath = top || p; load(p) }
    function load(p) {
        Api.get(Api.srcBase + "/api/local/list?path=" + encodeURIComponent(p || ""), function(ok, d) {
            if (!ok || !d || d.success === false) return
            root.path = String(d.path || ""); root.parentPath = String(d.parent || ""); root.writable = !!d.writable; root.ram = !!d.ram
            root.entries = d.entries || []; root.sel = []
        }, 15000)
    }
    function reload() { load(path) }
    function isSel(p) { return sel.indexOf(p) >= 0 }
    function toggle(p) { var s = sel.slice(), i = s.indexOf(p); if (i >= 0) s.splice(i, 1); else s.push(p); sel = s; activated() }
    function selBytes() { var n = 0; for (var i = 0; i < entries.length; i++) if (isSel(entries[i].path)) n += Number(entries[i].size || 0); return n }
    function size(e) {
        if (e.dir) return ""
        var n = Number(e.size) || 0
        if (n < 1048576) return Math.max(1, Math.round(n / 1024)) + " KB"
        if (n < 1073741824) return (n / 1048576).toFixed(1).replace(".", ",") + " MB"
        return (n / 1073741824).toFixed(1).replace(".", ",") + " GB"
    }
    function glyph(e) {
        if (e.dir) return "folder"
        var n = String(e.name).toLowerCase()
        if (/\.(flac|mp3|wav|m4a|aac|ogg|opus|aiff?|dsf|dff|ape|wv|mpc)$/.test(n)) return "music"
        if (/\.(jpe?g|png|webp|gif|bmp)$/.test(n)) return "image"
        if (/\.(m3u8?|pls|xspf|cue)$/.test(n)) return "list-music"
        return "file"
    }
    readonly property var place: Ui.sources ? (function() { var ps = Ui.sources.places, best = null
        for (var i = 0; i < ps.length; i++) if (ps[i].root && Ui.sources.under(root.path, ps[i].root) && (!best || ps[i].root.length > best.root.length)) best = ps[i]
        return best })() : null

    Rectangle { x: 10; y: 12; width: tagT.implicitWidth + 14; height: 22; radius: 6; color: root.active ? Theme.gold : Theme.light
        Text { id: tagT; anchors.centerIn: parent; text: root.tag; color: root.active ? Theme.black : Theme.silver; font.family: Theme.font; font.pixelSize: 10; font.bold: true } }
    Rectangle {
        x: tagT.implicitWidth + 32; y: 8; width: 30; height: 30; radius: 8; color: upTap.mix(Theme.dark, Theme.light); border.width: 1; border.color: Theme.border
        opacity: root.path !== root.rootPath && !!root.parentPath ? 1 : 0.4
        Icon { anchors.centerIn: parent; name: "chevron-up"; size: 15; color: Theme.silver }
        Tap { id: upTap; enabled: root.path !== root.rootPath && !!root.parentPath; onClicked: { root.activated(); root.load(root.parentPath) } }
    }
    Rectangle {
        x: tagT.implicitWidth + 68; y: 8; width: parent.width - x - 10; height: 30; radius: 8; color: plTap.mix(Theme.dark, Theme.light); border.width: 1; border.color: root.canChangePlace ? Theme.goldA(0.3) : Theme.border
        Icon { x: 8; anchors.verticalCenter: parent.verticalCenter; name: root.place ? root.place.glyph : "folder"; size: 14; color: Theme.gold }
        Text { x: 28; width: parent.width - 36 - (root.canChangePlace ? 18 : 0); anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideLeft; textFormat: Text.StyledText
               text: { var pl = root.place; if (!pl) return root.path; var rest = root.path.slice(pl.root.length).split("/").filter(function(x) { return x })
                       return pl.name + (rest.length ? "  ›  <font color='#d4af37'>" + rest.join("  ›  ") + "</font>" : "") }
               color: Theme.silver; font.family: Theme.font; font.pixelSize: 12 }
        Icon { visible: root.canChangePlace; x: parent.width - 20; anchors.verticalCenter: parent.verticalCenter; name: "chevron-down"; size: 13; color: Theme.silverA(0.6) }
        Tap { id: plTap; enabled: root.canChangePlace; onClicked: { root.activated(); root.choosing = !root.choosing } }
    }
    Text { x: root.selectable ? 42 : 14; y: 46; text: root.lt("Nome", "Name"); color: Theme.white; font.family: Theme.font; font.pixelSize: 10; font.bold: true }
    Text { x: parent.width - 12 - width; y: 46; text: root.lt("Dimensione", "Size"); color: Theme.silverA(0.55); font.family: Theme.font; font.pixelSize: 10 }
    Rectangle { x: 10; y: 62; width: parent.width - 20; height: 1; color: Theme.border }
    ListView {
        id: lv
        visible: !root.choosing
        x: 6; y: 66; width: parent.width - 12; height: parent.height - 66 - 30
        clip: true; spacing: 2; boundsBehavior: Flickable.StopAtBounds
        model: root.entries
        delegate: Rectangle {
            required property var modelData
            readonly property bool ticked: root.selectable && root.isSel(modelData.path)
            readonly property bool there: root.mark.indexOf(String(modelData.name)) >= 0
            width: lv.width; height: 34; radius: 7
            color: ticked ? Theme.goldA(0.14) : there ? Qt.rgba(0.98, 0.8, 0.08, 0.07) : rTap.mix(Qt.rgba(0, 0, 0, 0), Theme.wa(0.05))
            border.width: ticked || there ? 1 : 0; border.color: ticked ? Theme.goldA(0.45) : Qt.rgba(0.98, 0.8, 0.08, 0.4)
            RowTap { id: rTap; flick: lv; anchors.leftMargin: root.selectable ? 32 : 0
                     onClicked: { root.activated(); if (modelData.dir) root.load(modelData.path); else if (root.selectable) root.toggle(modelData.path) } }
            Rectangle { visible: root.selectable; x: 8; anchors.verticalCenter: parent.verticalCenter; width: 20; height: 20; radius: 5
                color: parent.ticked ? Theme.gold : Theme.dark; border.width: parent.ticked ? 0 : 1; border.color: Theme.light
                Icon { visible: parent.parent.ticked; anchors.centerIn: parent; name: "check"; size: 13; color: Theme.black }
                Tap { grow: 8; onClicked: root.toggle(modelData.path) } }
            Icon { x: root.selectable ? 36 : 10; anchors.verticalCenter: parent.verticalCenter; name: root.glyph(modelData); size: 15; color: modelData.dir ? Theme.gold : Theme.silverA(0.6) }
            Text { id: nmT; x: root.selectable ? 58 : 32; width: Math.min(implicitWidth, parent.width - x - 76 - (thereT.visible ? thereT.width + 6 : 0)); anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; text: modelData.name; color: Theme.white; font.family: Theme.font; font.pixelSize: 12 }
            Rectangle { id: thereT; visible: parent.there; x: nmT.x + nmT.width + 6; anchors.verticalCenter: parent.verticalCenter; width: thT.implicitWidth + 12; height: 17; radius: 9; color: "transparent"; border.width: 1; border.color: Theme.yellow400
                Text { id: thT; anchors.centerIn: parent; text: root.lt("c'è già", "already there"); color: Theme.yellow400; font.family: Theme.font; font.pixelSize: 9 } }
            Text { x: parent.width - 8 - width; anchors.verticalCenter: parent.verticalCenter; text: root.size(modelData); color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 11 }
        }
        Text { visible: !root.entries.length; y: 8; x: 8; text: root.lt("Cartella vuota", "Empty folder"); color: Theme.silverA(0.55); font.family: Theme.font; font.pixelSize: 12 }
    }
    // the places, to show another one in this pane
    Flickable {
        visible: root.choosing
        x: 6; y: 66; width: parent.width - 12; height: parent.height - 66 - 30
        clip: true; contentHeight: plCol.height; boundsBehavior: Flickable.StopAtBounds
        Column {
            id: plCol; width: parent.width; spacing: 4
            Repeater {
                model: Ui.sources ? Ui.sources.places.filter(function(p) { return p.ok && p.root }) : []
                delegate: Rectangle {
                    required property var modelData
                    width: plCol.width; height: 44; radius: 9
                    color: pcTap.mix(Theme.dark, Theme.light); border.width: 1; border.color: root.place && root.place.key === modelData.key ? Theme.goldA(0.5) : Theme.border
                    Icon { x: 12; anchors.verticalCenter: parent.verticalCenter; name: modelData.glyph; size: 16; color: Theme.gold }
                    Text { x: 38; y: 6; width: parent.width - 50; elide: Text.ElideRight; text: modelData.name; color: Theme.white; font.family: Theme.font; font.pixelSize: 13; font.bold: true }
                    Text { x: 38; y: 24; width: parent.width - 50; elide: Text.ElideRight; text: modelData.group === "dev" ? root.lt("Questo apparecchio", "This appliance") : modelData.group === "usb" ? "USB" : root.lt("Rete", "Network"); color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 10 }
                    Tap { id: pcTap; onClicked: { root.choosing = false; root.openAt(modelData.root, modelData.root) } }
                }
            }
        }
    }
    Text { x: 12; y: parent.height - 24; width: parent.width - 24; elide: Text.ElideRight
           text: root.choosing ? root.lt("Scegli il posto da mostrare qui", "Pick the place to show here")
                 : root.selectable && root.sel.length ? root.sel.length + root.lt(" selezionati", " selected") + (root.selBytes() ? " · " + Ui.sources.gb(root.selBytes()) : "")
                 : root.entries.length + root.lt(" elementi", " items") + (root.place && root.place.usage ? " · " + Ui.sources.gb(root.place.usage.free) + root.lt(" liberi", " free") : "") + (root.path && !root.writable ? root.lt(" · sola lettura", " · read only") : "")
           color: root.selectable && root.sel.length ? Theme.gold : Theme.silverA(0.55); font.family: Theme.font; font.pixelSize: 11 }
}
