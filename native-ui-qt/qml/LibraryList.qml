// Le liste del browser (draw_rows in screen_main.c): righe per artisti,
// brani, cartelle, playlist, radio, app, menu Jive e voci di plugin; griglia
// a 3 colonne per gli album. Il modello e' Library (righe visibili).
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    property int view: Library.view
    property string pluginCmd: ""
    signal rowTap(int row, bool onPlay)
    signal rowLongPress(int row, real x, real y)
    readonly property bool grid: view === LibraryModel.Albums
    readonly property int pitch: view === LibraryModel.Tracks || view === LibraryModel.PlaylistTracks ? 50
                               : view === LibraryModel.Radios || view === LibraryModel.Apps ? 54 : 58
    readonly property real cardW: (width - 24) / 3
    readonly property real cardH: cardW + 48
    readonly property real devScale: Ui.app ? Ui.app.devicePixelScale : 1
    function scrollToRow(row) {
        if (grid) gridView.positionViewAtIndex(row, GridView.Beginning)
        else listView.positionViewAtIndex(row, ListView.Beginning)
    }
    function scrollTop() { listView.contentY = 0; gridView.contentY = 0 }

    // URL di un'icona di menu/radio: percorso sul server oppure http locale
    function iconUrl(icon) {
        if (!icon) return ""
        if (icon.indexOf("http") === 0) {
            var h = icon.indexOf("127.0.0.1"); if (h < 0) h = icon.indexOf("localhost")
            if (h < 0) return ""
            var slash = icon.indexOf("/", h); if (slash < 0) return ""
            return Api.lmsBase + icon.substring(slash)
        }
        return Api.lmsBase + "/" + (icon.charAt(0) === "/" ? icon.substring(1) : icon)
    }

    // ─── righe ─────────────────────────────────────────────────────────────
    ListView {
        id: listView
        anchors.fill: parent
        visible: !root.grid
        model: root.grid ? null : Library
        spacing: 4
        clip: true
        flickDeceleration: 1500; maximumFlickVelocity: 4000
        boundsBehavior: Flickable.StopAtBounds
        cacheBuffer: 200
        delegate: Item {
            id: row
            required property int index
            required property string id
            required property string text
            required property string sub
            required property string icon
            required property var go
            required property var play
            required property bool isDir
            required property bool hasItems
            required property bool isAudio
            width: listView.width; height: root.pitch - 4
            readonly property int v: root.view
            readonly property bool playBtn: v === LibraryModel.Artists || v === LibraryModel.Playlists || v === LibraryModel.Folders ||
                                            ((v === LibraryModel.MenuHome || v === LibraryModel.Menu) && play && play.length > 0) ||
                                            (v === LibraryModel.PluginItems && isAudio)
            readonly property real iconW: v === LibraryModel.Artists || v === LibraryModel.Playlists ? 28
                                        : v === LibraryModel.Tracks || v === LibraryModel.PlaylistTracks ? 13
                                        : v === LibraryModel.Folders ? 15 : 24
            Rectangle { anchors.fill: parent; radius: 8; color: rowTap.pressed && !rowTap.moved ? Theme.mix(Theme.surface, Theme.wa(0.05), 1) : Theme.surface }
            // icona a sinistra
            Item {
                x: 12; anchors.verticalCenter: parent.verticalCenter; width: row.iconW; height: row.iconW
                Rectangle { anchors.fill: parent; radius: 14; color: Theme.light; visible: row.v === LibraryModel.Artists }
                Rectangle { anchors.fill: parent; radius: 8; color: Theme.light; visible: row.v === LibraryModel.Playlists }
                Image {
                    id: rowImg
                    anchors.fill: parent
                    visible: false
                    source: (row.v >= LibraryModel.Radios) ? root.iconUrl(row.icon) : ""
                    asynchronous: true; cache: true
                    sourceSize.width: Math.round(24 * root.devScale); sourceSize.height: Math.round(24 * root.devScale)
                    fillMode: Image.PreserveAspectCrop
                }
                Rectangle { id: rowMask; anchors.fill: parent; radius: 4; visible: false; layer.enabled: true }
                ShaderImage { anchors.fill: parent; source: rowImg; mask: rowMask; visible: rowImg.status === Image.Ready }
                Icon {
                    anchors.centerIn: parent
                    visible: rowImg.status !== Image.Ready
                    name: row.v === LibraryModel.Artists ? "user" : row.v === LibraryModel.Playlists ? "list-music"
                        : row.v === LibraryModel.Folders ? (row.isDir ? "folder" : "music")
                        : row.v === LibraryModel.Radios ? "radio" : row.v === LibraryModel.Apps ? "app-window"
                        : row.v === LibraryModel.PluginItems ? (row.hasItems ? "folder" : "music")
                        : (row.v === LibraryModel.MenuHome || row.v === LibraryModel.Menu) ? ((row.go && row.go.length) ? "app-window" : "music") : "music"
                    size: row.v === LibraryModel.Artists ? 13 : row.v === LibraryModel.Playlists ? 14 : row.v === LibraryModel.Folders ? 15 : row.v === LibraryModel.Tracks || row.v === LibraryModel.PlaylistTracks ? 13 : 15
                    color: row.v === LibraryModel.Artists || row.v === LibraryModel.Playlists ? Theme.silver
                         : (row.v === LibraryModel.Folders && row.isDir) ? Theme.gold : Theme.silverA(0.6)
                }
            }
            Text {
                x: 12 + row.iconW + 12; anchors.verticalCenter: parent.verticalCenter
                width: parent.width - x - (row.playBtn ? 48 : 12)
                text: row.text; elide: Text.ElideRight
                color: Theme.white; font.family: Theme.font; font.pixelSize: 14
            }
            Rectangle {                                   // pulsante play a destra
                visible: row.playBtn
                x: parent.width - 12 - 28; anchors.verticalCenter: parent.verticalCenter; width: 28; height: 28; radius: 14
                color: Theme.goldA(0.2)
                Icon { anchors.centerIn: parent; anchors.horizontalCenterOffset: 1; name: "play"; filled: true; size: 12; color: Theme.gold }
            }
            MouseArea {
                id: rowTap
                anchors.fill: parent
                property bool moved: false
                pressAndHoldInterval: 500
                onPressed: moved = false
                onPositionChanged: (m) => { if (Math.abs(m.y - pressY) > 10 || Math.abs(m.x - pressX) > 10) moved = true }
                property real pressX: 0; property real pressY: 0
                onPressedChanged: if (pressed) { pressX = mouseX; pressY = mouseY }
                onClicked: (m) => root.rowTap(row.index, row.playBtn && m.x >= width - 48)
                onPressAndHold: (m) => { if (!moved) root.rowLongPress(row.index, row.mapToItem(root, m.x, m.y).x, row.mapToItem(root, m.x, m.y).y) }
            }
        }
        ScrollBar_ { flick: listView }
    }

    // ─── griglia degli album ───────────────────────────────────────────────
    GridView {
        id: gridView
        anchors.fill: parent
        visible: root.grid
        model: root.grid ? Library : null
        cellWidth: root.cardW + 12; cellHeight: root.cardH + 12
        clip: true
        flickDeceleration: 1500; maximumFlickVelocity: 4000
        boundsBehavior: Flickable.StopAtBounds
        cacheBuffer: 300
        delegate: Item {
            id: card
            required property int index
            required property string id
            required property string text
            required property string sub
            required property string art
            width: root.cardW; height: root.cardH
            Rectangle { anchors.fill: parent; radius: 12; color: cardTap.pressed ? Theme.mix(Theme.surface, Theme.wa(0.05), 1) : Theme.surface; border.width: 1; border.color: Theme.border }
            Item {
                id: artBox
                width: root.cardW; height: root.cardW
                Rectangle { anchors.fill: parent; radius: 12; color: Theme.gray; visible: artImg.status !== Image.Ready
                            Icon { anchors.centerIn: parent; name: "disc"; size: 40; color: Theme.silverA(0.2) } }
                Image {
                    id: artImg; anchors.fill: parent; visible: false
                    source: card.art ? Api.lmsBase + "/music/" + card.art + "/cover_300x300_o.jpg" : ""
                    asynchronous: true; cache: true; fillMode: Image.PreserveAspectCrop
                    sourceSize.width: Math.round(root.cardW * root.devScale); sourceSize.height: Math.round(root.cardW * root.devScale)
                }
                // angoli tondi solo in alto (rounded-t-xl)
                Rectangle { id: artMask; anchors.fill: parent; radius: 12; visible: false; layer.enabled: true
                            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 12 } }
                ShaderImage { anchors.fill: parent; source: artImg; mask: artMask; visible: artImg.status === Image.Ready }
                Rectangle {
                    x: parent.width - 6 - 30; y: parent.height - 6 - 30; width: 30; height: 30; radius: 15; color: Theme.blackA(0.6)
                    Icon { anchors.centerIn: parent; anchors.horizontalCenterOffset: 1; name: "play"; filled: true; size: 14; color: Theme.white }
                }
            }
            Text { x: 8; y: artBox.height + 8; width: parent.width - 16; height: 16; verticalAlignment: Text.AlignVCenter; text: card.text; elide: Text.ElideRight; color: Theme.white; font.family: Theme.font; font.pixelSize: 12 }
            Text { x: 8; y: artBox.height + 24; width: parent.width - 16; height: 16; verticalAlignment: Text.AlignVCenter; text: card.sub; elide: Text.ElideRight; color: Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 12 }
            MouseArea {
                id: cardTap
                anchors.fill: parent
                onClicked: (m) => {
                    var bx = root.cardW - 6 - 15, by = root.cardW - 6 - 15
                    root.rowTap(card.index, Math.abs(m.x - bx) <= 18 && Math.abs(m.y - by) <= 18)
                }
            }
        }
        ScrollBar_ { flick: gridView }
    }
}
