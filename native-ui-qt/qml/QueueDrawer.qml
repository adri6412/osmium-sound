// Il cassetto della coda (LyrionServer.jsx, QueueRow): w-[400px], righe da 58
// con la maniglia per riordinare, scorrimento laterale per togliere, piede
// con "salva come playlist" e "svuota".
import QtQuick
import Hifi.Ui

Rectangle {
    id: root
    property bool interactive: true
    // 🚨 ListModel, non un array: durante il riordino si sposta una riga con
    // move() e i delegati restano vivi (con un array il modello veniva
    // rimpiazzato a ogni passo e la lista si scompaginava)
    property alias items: qmodel
    readonly property int count: qmodel.count
    property int cur: -1
    ListModel { id: qmodel }
    signal close()
    signal save()
    color: Theme.panel
    BoxShadow { z: -1; targetX: 0; targetY: 0; targetW: parent.width; targetH: parent.height; radius: 0; blur: 50; spread: -12; offsetY: 25; color: Theme.blackA(0.25) }   // shadow-2xl
    Rectangle { width: 1; height: parent.height; color: Theme.border }

    function load() {
        Player.query(["status", "0", "999", "tags:acdltK"], function(ok, r) {
            if (!ok) return
            var loop = r.playlist_loop || []
            qmodel.clear()
            for (var i = 0; i < loop.length; i++) {
                var it = loop[i]
                qmodel.append({ id: String(it.id), title: String(it.title || it.track || "—"), artist: String(it.artist || "") })
            }
            root.cur = r.playlist_cur_index !== undefined ? Number(r.playlist_cur_index) : -1
        })
    }
    Connections { target: Player; function onControlsChanged() { if (root.visible) root.cur = Player.index } }

    // intestazione h-12
    Item {
        id: head
        width: parent.width; height: 48
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
        Icon { x: 16; anchors.verticalCenter: parent.verticalCenter; name: "list-music"; size: 16; color: Theme.gold }
        Text { id: headTitle; x: 40; anchors.verticalCenter: parent.verticalCenter; text: Tr.t("player.queue"); color: Theme.white; font.family: Theme.font; font.pixelSize: 14; font.bold: true }
        Text { x: headTitle.x + headTitle.implicitWidth + 8; anchors.verticalCenter: parent.verticalCenter; text: "(" + root.count + ")"; color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 11 }
        Item {
            x: parent.width - 16 - 28; y: 10; width: 28; height: 28
            Icon { anchors.centerIn: parent; name: "x"; size: 16; color: Theme.silverA(0.6) }
            Tap { grow: 8; onClicked: root.close() }
        }
    }

    // lista
    ListView {
        id: list
        x: 8; y: 56; width: parent.width - 16; height: parent.height - 48 - 67 - 16
        clip: true
        model: qmodel
        spacing: 4
        // le righe che si spostano scivolano al loro posto, come il layout
        // animato di framer-motion in QueueRow
        displaced: Transition { NumberAnimation { properties: "y"; duration: 180 } }
        move: Transition { NumberAnimation { properties: "y"; duration: 180 } }
        interactive: root.interactive && !dragRow.active
        flickDeceleration: 1500; maximumFlickVelocity: 4000
        boundsBehavior: Flickable.StopAtBounds
        delegate: Item {
            id: row
            required property int index
            required property string title
            required property string artist
            readonly property bool current: index === root.cur
            width: list.width; height: 54
            // 🚨 mai legare `y` sul delegato: la ListView posiziona lei le
            // righe e con un binding finiscono tutte a y=0. Lo scarto del
            // trascinamento va sulla scheda interna.
            readonly property real dragDy: dragRow.active && dragRow.cur === index
                                           ? dragRow.dy - (dragRow.cur - dragRow.from) * 58 : 0
            z: dragRow.active && dragRow.cur === index ? 2 : 0
            property real swipeDx: 0
            Rectangle {                              // sfondo rosso con cestino (scorrimento)
                y: row.dragDy; width: parent.width; height: parent.height; radius: 8; color: Theme.redA(0.2); visible: row.swipeDx < 0
                Icon { anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter; name: "trash-2"; size: 16; color: Theme.red300 }
            }
            Rectangle {
                x: row.swipeDx; y: row.dragDy; width: parent.width; height: parent.height; radius: 8
                color: row.current ? Theme.goldA(0.15) : Theme.surface
                border.width: row.current ? 1 : 0; border.color: Theme.goldA(0.3)
                Icon { x: 12; anchors.verticalCenter: parent.verticalCenter; name: "grip-vertical"; size: 15; color: dragRow.active && dragRow.cur === row.index ? Theme.white : Theme.silverA(0.4) }   // active:text-white
                Text {
                    x: 31; width: 24; anchors.verticalCenter: parent.verticalCenter; horizontalAlignment: Text.AlignHCenter
                    text: row.current ? "▶" : String(row.index + 1)
                    color: row.current ? Theme.gold : Theme.silverA(0.4); font.family: Theme.mono; font.pixelSize: 11
                }
                Text {
                    x: 59; y: 7; width: parent.width - 59 - 8; height: 17; verticalAlignment: Text.AlignVCenter
                    text: row.title; elide: Text.ElideRight
                    color: row.current ? Theme.white : Theme.wa(0.9); font.family: Theme.font; font.pixelSize: 14; font.bold: row.current
                }
                Text {
                    x: 59; y: 24; width: parent.width - 59 - 8; height: 14; verticalAlignment: Text.AlignVCenter
                    text: row.artist ? row.artist : Tr.t("player.unknownArtist"); elide: Text.ElideRight
                    color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 11
                }
            }
            MouseArea {
                anchors.fill: parent
                enabled: root.interactive
                property real x0: 0; property real y0: 0; property bool horiz: false; property bool decided: false
                onPressed: (m) => {
                    x0 = m.x; y0 = m.y; horiz = false; decided = false
                    // coordinate di scena: quelle relative alla riga si spostano
                    // insieme alla riga durante il riordino e falsavano la corsa
                    if (m.x < 31) { dragRow.start(row.index, mapToItem(null, m.x, m.y).y); m.accepted = true }
                }
                onPositionChanged: (m) => {
                    if (dragRow.active) { dragRow.update(mapToItem(null, m.x, m.y).y); return }
                    var dx = m.x - x0, dy = m.y - y0
                    if (!decided && (Math.abs(dx) >= 10 || Math.abs(dy) >= 10)) { decided = true; horiz = Math.abs(dx) > Math.abs(dy) }
                    if (decided && horiz) row.swipeDx = Math.min(0, dx)
                    else if (decided && !horiz) { preventStealing = false }
                }
                preventStealing: true
                onReleased: (m) => {
                    if (decided && horiz) {
                        if (row.swipeDx < -96) { Player.cmd(["playlist", "delete", String(row.index)]); Qt.callLater(root.load) }
                        row.swipeDx = 0
                    } else if (!decided) {
                        Player.cmd(["playlist", "index", String(row.index)])
                        root.cur = row.index
                    }
                }
                onCanceled: row.swipeDx = 0
            }
        }
        // barra di scorrimento 3 px #333
        Rectangle {
            visible: list.contentHeight > list.height
            x: list.width - 3; width: 3; radius: 2; color: "#333333"
            height: Math.max(20, list.height * list.height / Math.max(1, list.contentHeight))
            y: (list.height - height) * (list.contentY / Math.max(1, list.contentHeight - list.height))
        }
        Text {
            anchors.centerIn: parent; visible: root.count === 0
            text: Tr.t("player.queueEmpty"); color: Theme.silverA(0.4); font.family: Theme.font; font.pixelSize: 14
        }
    }
    // 🚨 la presa del trascinamento sta QUI, non nel delegato: quando il modello
    // si riordina la ListView ricicla i delegati e il delegato che aveva il
    // mouse perde la presa dopo il primo spostamento.
    MouseArea {
        id: handleArea
        x: list.x; y: list.y; width: 31; height: list.height
        enabled: root.interactive
        preventStealing: true
        onPressed: (m) => {
            var idx = Math.floor((m.y + list.contentY) / 58)
            if (idx < 0 || idx >= qmodel.count) { m.accepted = false; return }
            dragRow.start(idx, m.y)
        }
        onPositionChanged: (m) => { if (dragRow.active) dragRow.update(m.y) }
        onReleased: if (dragRow.active) dragRow.finish()
        onCanceled: if (dragRow.active) dragRow.finish()
    }

    // riordino con la maniglia (data-drag-handle nel JSX)
    QtObject {
        id: dragRow
        property bool active: false
        property int from: -1; property int cur: -1
        property real y0: 0; property real dy: 0
        function start(i, y) { active = true; from = cur = i; y0 = y; dy = 0 }
        function update(y) {
            dy = y - y0
            var target = from + Math.round(dy / 58)
            if (Sys.devMode) Sys.log("drag: y=" + Math.round(y) + " dy=" + Math.round(dy) + " from=" + from + " cur=" + cur + " target=" + target)
            target = Math.max(0, Math.min(qmodel.count - 1, target))
            if (target !== cur) {
                qmodel.move(cur, target, 1)
                if (root.cur === cur) root.cur = target
                else if (cur < root.cur && target >= root.cur) root.cur--
                else if (cur > root.cur && target <= root.cur) root.cur++
                cur = target
            }
        }
        function finish() {
            active = false
            if (cur !== from) { Player.cmd(["playlist", "move", String(from), String(cur)]); Qt.callLater(root.load) }
            dy = 0
        }
    }

    // piede
    Item {
        y: parent.height - 67; width: parent.width; height: 67
        Rectangle { width: parent.width; height: 1; color: Theme.border }
        readonly property bool has: root.count > 0
        Rectangle {
            id: saveBtn
            x: 12; y: 12; width: parent.width - 24 - 8 - 108; height: 42; radius: 8
            // disabled:opacity-40 su TUTTO il pulsante: fondo, bordo, icona e testo al 40 %
            color: parent.has ? saveTap.mix(Theme.surface, Theme.light) : Qt.rgba(0x16/255, 0x16/255, 0x16/255, 0.4)
            border.width: 1; border.color: parent.has ? Theme.border : Theme.borderA(0.4)
            Row {
                anchors.centerIn: parent; spacing: 8
                Icon { name: "save"; size: 15; color: saveBtn.parent.has ? Theme.white : Theme.wa(0.4); anchors.verticalCenter: parent.verticalCenter }
                Text { text: Tr.t("player.saveAsPlaylist"); color: saveBtn.parent.has ? Theme.white : Theme.wa(0.4); font.family: Theme.font; font.pixelSize: 14; anchors.verticalCenter: parent.verticalCenter }
            }
            Tap { id: saveTap; enabled: saveBtn.parent.has; onClicked: root.save() }
        }
        Rectangle {
            id: clearBtn
            x: parent.width - 12 - 108; y: 12; width: 108; height: 42; radius: 8
            color: Theme.redA(parent.has ? 0.1 : 0.04); border.width: 1; border.color: Theme.redA(parent.has ? 0.2 : 0.08)
            Row {
                anchors.centerIn: parent; spacing: 8
                Icon { name: "trash-2"; size: 15; color: clearBtn.parent.has ? Theme.red300 : Qt.rgba(0xfc/255, 0xa5/255, 0xa5/255, 0.4); anchors.verticalCenter: parent.verticalCenter }
                Text { text: Tr.t("player.clearQueue"); color: clearBtn.parent.has ? Theme.red300 : Qt.rgba(0xfc/255, 0xa5/255, 0xa5/255, 0.4); font.family: Theme.font; font.pixelSize: 14; anchors.verticalCenter: parent.verticalCenter }
            }
            Tap { enabled: clearBtn.parent.has; onClicked: { Player.cmd(["playlist", "clear"]); Qt.callLater(root.load) } }
        }
    }
}
