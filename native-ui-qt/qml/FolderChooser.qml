// The folder chooser, with the look of the web admin's File page: the places
// on the left, back / up and the path on top, a card per place on the first
// screen and a tile per folder after that, a new folder, and one button to
// take the folder you are in. Everything that picks a folder opens this —
// a local music folder, a shared folder, the playlist folder, the CD rip
// destination and prefix — so the owner meets one navigator, not four.
// Reads /api/local/list like the File page; folders only.
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    property bool open: false
    property bool closing: false
    property string title: ""
    property string pickLabel: ""
    property var cb: null
    property string path: ""
    property string parentPath: ""
    property bool atRoot: path === ""
    property var places: []          // [{name, path, kind, usage:{free,total}, count}]
    property var entries: []         // folders of `path`, or the places at the root
    property bool writable: false
    property bool loading: false
    property var history: []
    property string newName: ""
    anchors.fill: parent
    visible: open
    NavScope { active: root.open && !root.closing }
    Component.onCompleted: Ui.folderChooser = root

    Spring { id: sc; stiffness: 550; damping: 30; rate: Theme.motionRate }
    property real fade: 0
    Behavior on fade { NumberAnimation { duration: Theme.dur(300); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
    property real closeScale: 1
    Behavior on closeScale { NumberAnimation { duration: Theme.dur(200) } }
    Timer { interval: 40; repeat: true; running: root.closing; onTriggered: if (root.fade === 0) { root.open = false; root.closing = false } }

    // open(start, label, fn): fn(path) is called with the folder taken
    function openAt(start, label, fn) {
        pickLabel = label || Tr.t("sources.useThisFolder"); cb = fn || null
        history = []; newName = ""; entries = []
        open = true; closing = false; sc.set(0.94); sc.to = 1; closeScale = 1; fade = 1
        load(String(start || ""), false)
    }
    function close() { if (!open || closing) return; closing = true; closeScale = 0.94; fade = 0 }
    function load(next, remember) {
        loading = true
        Api.get(Api.srcBase + "/api/local/list?path=" + encodeURIComponent(next || ""), function(ok, d) {
            root.loading = false
            if (!ok || !d || d.success === false) { if (next) root.load("", false); return }
            var p = String(d.path || "")
            if (remember && root.path !== p) { var h = root.history.slice(); h.push(root.path); root.history = h }
            root.path = p; root.parentPath = String(d.parent || ""); root.writable = !!d.writable
            var all = d.entries || []
            root.entries = p ? all.filter(function(e) { return !!e.dir }) : all
            if (!p) root.places = all
        }, 8000)
    }
    function goBack() { if (!history.length) return; var h = history.slice(); var prev = h.pop(); history = h; load(prev, false) }
    function take() { if (atRoot) return; var p = path, f = cb; close(); if (f) f(p) }
    function mkdir() {
        var name = newName; newName = ""
        if (!name || atRoot) return
        Api.post(Api.srcBase + "/api/local/mkdir", { path: root.path, name: name }, function(ok, d) { root.load(ok && d && d.path ? String(d.path) : root.path, false) })
    }
    function gb(n) {
        var v = Number(n) || 0
        if (v >= 1099511627776) return (v / 1099511627776).toFixed(1) + " TB"
        if (v >= 10 * 1073741824) return Math.round(v / 1073741824) + " GB"
        if (v >= 1073741824) return (v / 1073741824).toFixed(1) + " GB"
        return Math.round(v / 1048576) + " MB"
    }
    function placeSub(p) {
        if (p.usage && p.usage.total) return Tr.tf("fileChooser.freeOf", "free", gb(p.usage.free)).replace("{total}", gb(p.usage.total))
        var n = Number(p.count) || 0
        return n ? Tr.tf("fileChooser.items", "n", String(n)) : Tr.t("fileChooser.emptyPlace")
    }
    function placeGlyph(p) {
        var k = String(p.kind || "")
        return k === "music" ? "music" : k === "internal" ? "hard-drive" : k === "network" ? "network" : k === "usb" ? "usb" : k === "playlists" ? "list-music" : k === "home" ? "home" : "folder"
    }
    function activePlace() {
        for (var i = 0; i < places.length; i++) { var pp = String(places[i].path || ""); if (pp && (path === pp || path.indexOf(pp + "/") === 0)) return pp }
        return ""
    }
    function shownPath() {
        if (!path) return Tr.t("fileChooser.root")
        var ap = activePlace()
        for (var i = 0; i < places.length; i++) if (String(places[i].path) === ap) return String(places[i].name) + path.slice(ap.length).split("/").join("  ›  ")
        return path
    }

    Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0, 0, 0.7 * root.fade); MouseArea { anchors.fill: parent; onClicked: root.close() } }
    Rectangle {
        id: card
        width: Math.min(760, root.width - 48); height: root.height * 0.88
        anchors.centerIn: parent
        radius: 16; color: Theme.panel; border.width: 1; border.color: Theme.border
        opacity: root.fade; scale: sc.value * root.closeScale
        BoxShadow { z: -1; targetX: 0; targetY: 0; targetW: parent.width; targetH: parent.height; radius: 16; blur: 50; spread: -12; offsetY: 25; color: Theme.blackA(0.25) }
        MouseArea { anchors.fill: parent }
        Icon { x: 20; y: 22; name: "folder"; size: 16; color: Theme.gold }
        Text { x: 44; y: 16; height: 28; verticalAlignment: Text.AlignVCenter; text: Tr.t("fileChooser.title"); color: Theme.white; font.family: Theme.font; font.pixelSize: 14; font.bold: true }
        Item {
            x: parent.width - 20 - 28; y: 16; width: 28; height: 28
            Icon { anchors.centerIn: parent; name: "x"; size: 16; color: Theme.silverA(0.6) }
            Tap { grow: 6; onClicked: root.close() }
        }

        // ── places, on the left ───────────────────────────────────────────
        Item {
            id: side
            x: 20; y: 56; width: 170; height: parent.height - 56 - 20 - 50
            Text { x: 6; y: 0; height: 20; text: Tr.t("fileChooser.places"); color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 10; font.bold: true; font.capitalization: Font.AllUppercase; font.letterSpacing: 1 }
            Column {
                y: 26; width: parent.width; spacing: 2
                Repeater {
                    model: root.places
                    delegate: Rectangle {
                        required property var modelData
                        readonly property bool on: root.activePlace() === String(modelData.path || "")
                        width: side.width; height: 36; radius: 8
                        color: on ? Theme.goldA(0.12) : plTap.mix(Qt.rgba(0, 0, 0, 0), Theme.wa(0.05))
                        border.width: on ? 1 : 0; border.color: Theme.goldA(0.4)
                        Icon { x: 10; anchors.verticalCenter: parent.verticalCenter; name: root.placeGlyph(modelData); size: 16; color: parent.on ? Theme.gold : Theme.silver }
                        Text { x: 34; width: parent.width - 42; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; text: String(modelData.name || ""); color: parent.on ? Theme.gold : Theme.silver; font.family: Theme.font; font.pixelSize: 13 }
                        Tap { id: plTap; onClicked: root.load(String(modelData.path || ""), true) }
                    }
                }
            }
        }

        // ── the bar: back, up, path ───────────────────────────────────────
        Item {
            id: main
            x: side.x + side.width + 14; y: 56; width: parent.width - x - 20; height: side.height
            Rectangle {
                id: backBtn
                x: 0; y: 0; width: 36; height: 36; radius: 8; color: bkTap.mix(Theme.dark, Theme.light); border.width: 1; border.color: Theme.border; opacity: root.history.length ? 1 : 0.4
                Icon { anchors.centerIn: parent; name: "chevron-left"; size: 18; color: Theme.silver }
                Tap { id: bkTap; enabled: root.history.length > 0; onClicked: root.goBack() }
            }
            Rectangle {
                id: upBtn
                x: 42; y: 0; width: 36; height: 36; radius: 8; color: upTap.mix(Theme.dark, Theme.light); border.width: 1; border.color: Theme.border; opacity: root.atRoot ? 0.4 : 1
                Icon { anchors.centerIn: parent; name: "chevron-up"; size: 18; color: Theme.silver }
                Tap { id: upTap; enabled: !root.atRoot; onClicked: root.load(root.parentPath, true) }
            }
            Rectangle {
                x: 84; y: 0; width: parent.width - 84; height: 36; radius: 8; color: Theme.dark; border.width: 1; border.color: Theme.border
                Text { x: 12; width: parent.width - 24; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideMiddle; text: root.shownPath(); color: Theme.white; font.family: Theme.font; font.pixelSize: 13 }
            }

            // ── the first screen: a card per place; then a tile per folder ──
            Text { visible: root.loading; x: 4; y: 56; text: Tr.t("common.loading"); color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 12 }
            Item {
                visible: !root.loading && !root.entries.length
                x: 0; y: 56; width: parent.width; height: 120
                Icon { x: parent.width / 2 - 20; y: 20; name: "folder"; size: 40; color: Theme.silverA(0.3) }
                Text { y: 72; width: parent.width; horizontalAlignment: Text.AlignHCenter; text: Tr.t("fileChooser.empty"); color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 13 }
            }
            GridView {
                id: grid
                visible: !root.loading && root.entries.length > 0
                x: 0; y: 48; width: parent.width; height: parent.height - 48 - (root.atRoot ? 0 : 48)
                clip: true; boundsBehavior: Flickable.StopAtBounds
                cellWidth: root.atRoot ? Math.floor(width / 2) : Math.floor(width / Math.max(2, Math.floor(width / 150)))
                cellHeight: root.atRoot ? 66 : 92
                model: root.entries
                delegate: Item {
                    required property var modelData
                    width: grid.cellWidth; height: grid.cellHeight
                    Rectangle {
                        x: 4; y: 4; width: parent.width - 8; height: parent.height - 8; radius: 10
                        color: tTap.mix(Theme.dark, Theme.light); border.width: 1; border.color: Theme.border
                        // a place: icon on the left, name and what it holds
                        Icon { visible: root.atRoot; x: 14; anchors.verticalCenter: parent.verticalCenter; name: root.placeGlyph(modelData); size: 24; color: Theme.gold }
                        Text { visible: root.atRoot; x: 50; y: 12; width: parent.width - 62; elide: Text.ElideRight; text: String(modelData.name || ""); color: Theme.white; font.family: Theme.font; font.pixelSize: 13; font.bold: true }
                        Text { visible: root.atRoot; x: 50; y: 32; width: parent.width - 62; elide: Text.ElideRight; text: root.atRoot ? root.placeSub(modelData) : ""; color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 11 }
                        // a folder: the icon above the name
                        Icon { visible: !root.atRoot; x: parent.width / 2 - 17; y: 14; name: "folder"; size: 34; color: Theme.gold }
                        Text { visible: !root.atRoot; x: 8; y: 56; width: parent.width - 16; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideMiddle; text: String(modelData.name || ""); color: Theme.white; font.family: Theme.font; font.pixelSize: 12 }
                        Tap { id: tTap; onClicked: root.load(String(modelData.path || ""), true) }
                    }
                }
            }
            // new folder, only inside a writable folder
            TextField_ { visible: !root.atRoot; x: 0; y: parent.height - 40; width: parent.width - 8 - 96; height: 36; textSize: 13; padding: 10; restBorder: Theme.border; text: root.newName; placeholder: Tr.t("fileChooser.newFolder"); onTextEdited: (t) => root.newName = t }
            Rectangle {
                visible: !root.atRoot
                x: parent.width - 96; y: parent.height - 40; width: 96; height: 36; radius: 8; color: mkTap.mix(Theme.light, Theme.accent); opacity: root.newName !== "" && root.writable ? 1 : 0.4
                Text { anchors.centerIn: parent; text: Tr.t("fileChooser.create"); color: Theme.white; font.family: Theme.font; font.pixelSize: 12 }
                Tap { id: mkTap; enabled: root.newName !== "" && root.writable; onClicked: root.mkdir() }
            }
        }

        // ── cancel / use this folder ──────────────────────────────────────
        Rectangle {
            x: 20; y: parent.height - 20 - 42; width: cxText.implicitWidth + 32; height: 42; radius: 8; color: cxTap.mix(Theme.light, Theme.accent)
            Text { id: cxText; anchors.centerIn: parent; text: Tr.t("common.cancel"); color: Theme.white; font.family: Theme.font; font.pixelSize: 14 }
            Tap { id: cxTap; onClicked: root.close() }
        }
        Rectangle {
            x: 20 + cxText.implicitWidth + 32 + 8; y: parent.height - 20 - 42; width: parent.width - 20 - x; height: 42; radius: 8
            color: okTap.mix(Theme.gold, "#ca8a04"); opacity: root.atRoot ? 0.4 : 1
            Text { anchors.centerIn: parent; text: root.pickLabel; color: Theme.black; font.family: Theme.font; font.pixelSize: 14; font.bold: true }
            Tap { id: okTap; enabled: !root.atRoot; onClicked: root.take() }
        }
    }
}
