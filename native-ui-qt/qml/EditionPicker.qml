// "Which edition is it?": the MusicBrainz releases that could be this album
// (search results and the other editions of the one in use). The choice is
// saved by the metadata service (/api/meta/album/pin) and the page reloads.
import QtQuick
import Hifi.Ui

Item {
    id: root
    property string albumId: ""
    property var cands: []
    property string current: ""
    property int state_: 0              // 0 closed 1 loading 2 ready 3 none/error
    property int tries: 0
    signal picked()
    visible: state_ > 0
    anchors.fill: parent
    z: 10

    function open(id) {
        albumId = String(id); cands = []; current = ""; tries = 0; state_ = 1
        load()
    }
    function close() { state_ = 0; poll.stop() }
    function load() {
        Api.get(Meta.url("/album/candidates?album_id=" + albumId), function(ok, d) {
            if (!root) return          // the page was closed meanwhile
            if (root.state_ === 0) return
            if (ok && d && d.status === "pending" && root.tries++ < 30) { poll.restart(); return }
            if (!ok || !d || d.status !== "ok") { root.state_ = 3; return }
            root.cands = d.candidates || []
            root.current = String(d.pinned && d.pinned !== "none" ? d.pinned : (d.current || ""))
            root.state_ = root.cands.length ? 2 : 3
        }, 20000)
    }
    Timer { id: poll; interval: 2000; onTriggered: root.load() }
    function pin(mbid) {
        Api.post(Meta.url("/album/pin"), { album_id: Number(root.albumId), mbid: mbid }, function() { root.picked() })
        close()
    }

    Rectangle { anchors.fill: parent; color: Theme.blackA(0.7) }
    MouseArea { anchors.fill: parent; onClicked: root.close() }
    Rectangle {
        id: box
        x: 16; y: 12; width: parent.width - 32; height: parent.height - 24; radius: 16
        color: Theme.panel; border.width: 1; border.color: Theme.border
        MouseArea { anchors.fill: parent }
        Text {
            x: 20; y: 16; width: parent.width - 80; height: 22; verticalAlignment: Text.AlignVCenter
            text: Tr.t("player.page.editionsTitle"); color: Theme.white; elide: Text.ElideRight
            font.family: Theme.font; font.pixelSize: 16; font.bold: true
        }
        Text {
            x: 20; y: 40; width: parent.width - 40; height: 16; verticalAlignment: Text.AlignVCenter
            text: Tr.t("player.page.editionsHelp"); color: Theme.silverA(0.6); elide: Text.ElideRight
            font.family: Theme.font; font.pixelSize: 12
        }
        Item {
            x: parent.width - 16 - 32; y: 12; width: 32; height: 32
            Icon { anchors.centerIn: parent; name: "x"; size: 16; color: Theme.silverA(0.6) }
            Tap { grow: 6; onClicked: root.close() }
        }
        Text {
            visible: root.state_ !== 2
            x: 20; y: 80; width: parent.width - 40; wrapMode: Text.Wrap
            text: Tr.t(root.state_ === 1 ? "player.page.editionsLoading" : "player.page.editionsNone")
            color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 13
        }
        ListView {
            id: list
            x: 12; y: 66; width: parent.width - 24; height: parent.height - 66 - 64
            visible: root.state_ === 2
            clip: true; spacing: 4
            boundsBehavior: Flickable.StopAtBounds
            flickDeceleration: 1500; maximumFlickVelocity: 4000
            model: root.cands
            delegate: Rectangle {
                id: cand
                required property var modelData
                readonly property bool cur: String(modelData.mbid) === root.current
                width: list.width; height: 52; radius: 8
                color: cTap.pressed ? Theme.light : cur ? Theme.goldA(0.12) : Theme.surface
                border.width: cur ? 1 : 0; border.color: Theme.goldA(0.4)
                Text {
                    x: 12; y: 8; width: parent.width - 24; height: 18; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
                    text: String(cand.modelData.title || "") + (cand.modelData.artist ? " — " + cand.modelData.artist : "")
                    color: Theme.white; font.family: Theme.font; font.pixelSize: 14; font.bold: cand.cur
                }
                Text {
                    x: 12; y: 28; width: parent.width - 24; height: 16; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
                    color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 11
                    text: [Meta.date(cand.modelData.date), cand.modelData.country, cand.modelData.labels, cand.modelData.format,
                           cand.modelData.track_count ? Tr.tf("player.page.editionTracks", "count", String(cand.modelData.track_count)) : ""]
                          .filter(function(x) { return !!x }).join(" · ")
                }
                Tap { id: cTap; onClicked: root.pin(String(cand.modelData.mbid)) }
            }
        }
        ScrollBar_ { flick: list; x: list.x + list.width - 3; y: list.y + (list.height - height) * Math.max(0, Math.min(1, list.contentY / Math.max(1, list.contentHeight - list.height))) }
        Row {
            x: 16; y: parent.height - 52; spacing: 10
            PageButton { icon: "sparkles"; label: Tr.t("player.page.editionAuto"); onClicked: root.pin(null) }
            PageButton { icon: "x"; label: Tr.t("player.page.editionNone"); onClicked: root.pin("none") }
        }
    }
}
