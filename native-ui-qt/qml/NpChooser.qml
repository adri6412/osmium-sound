// The chooser of the Now Playing screen: a popup with the looks of the VU
// meters or the animations, opened by the two buttons next to the
// full-screen one. Each card is a still preview; a tap applies it at once
// with the same requests Settings makes (the meters go on for a VU look,
// off for an animation) and closes the popup.
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    property real devScale: 1
    property string mode: ""            // "" closed, "vu" the VU meter looks, "anim" the animations
    readonly property bool active: mode !== ""
    property var items: []              // [{id, label}]
    property bool loading: false
    property string loadError: ""
    visible: active || fade > 0
    // il telecomando resta qui dentro finche' questo strato e' aperto
    NavScope { active: root.active }
    anchors.fill: parent

    Spring { id: sc; stiffness: 550; damping: 30; rate: Theme.motionRate }
    property real fade: 0
    Behavior on fade { NumberAnimation { duration: Theme.dur(250); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }

    function api(p) { return Api.apiBase + p }
    function nameOf(o) {
        var nm = o.name || {}
        return String(nm[I18n.lang] || nm.en || o.id)
    }
    function open(m) {
        mode = m; items = []; loading = true; loadError = ""
        sc.set(0.92); sc.to = 1.0
        fade = 1
        forceActiveFocus()
        var gen = ++root.gen
        if (m === "vu") {
            Api.get(api("/vu_style"), function(ok, d) {
                if (gen !== root.gen) return
                loading = false
                if (!ok || !d) { loadError = Tr.t("player.chooser.loadError"); return }
                var st = d.styles || [], out = []
                for (var i = 0; i < st.length; i++) out.push({ id: String(st[i].id), label: nameOf(st[i]) })
                items = out
            })
        } else {
            // the built-in scenes first, then the ones downloaded from the store
            var out = ["cd", "cdfront", "vinyl", "cassette"].map(function(k) { return { id: k, label: Tr.t("settings.animations." + k) } })
            Api.get(api("/nowplaying_animation"), function(ok, d) {
                if (gen !== root.gen) return
                loading = false
                var st = (ok && d && d.store) ? d.store : []
                for (var i = 0; i < st.length; i++) out.push({ id: String(st[i].id), label: nameOf(st[i]) })
                items = out
            })
        }
    }
    property int gen: 0
    function close() { if (!active) return; mode = ""; gen++; fade = 0 }
    function choose(id) {
        if (mode === "vu") {
            // the look, and the meters on if they were off (Now Playing then
            // shows them instead of the animation)
            if (!Player.vuEnabled) Api.post(api("/vu_meter"), { enable: true })
            Api.post(api("/vu_style"), { style: id })
            Player.vuStyle = id
            Player.vuEnabled = true
        } else {
            // the animation, and the meters off: it takes their place
            if (Player.vuEnabled) Api.post(api("/vu_meter"), { enable: false })
            Api.post(api("/nowplaying_animation"), { animation: id })
            Player.npAnimation = id
            Player.vuEnabled = false
        }
        // what was just picked is what Now Playing shows next, even if the
        // lyrics were the last view chosen there
        if (Ui.app && !Ui.app.viewVu) { Ui.app.viewVu = true; Sys.setConf("nowplaying-view", "vu") }
        close()
    }

    Keys.onPressed: (e) => { if (e.key === Qt.Key_Escape) { close(); e.accepted = true } }

    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.7 * root.fade)
        MouseArea { anchors.fill: parent; onClicked: root.close() }
    }

    // ─── the card ───────────────────────────────────────────────────────────
    Rectangle {
        id: card
        readonly property int cols: 3
        readonly property real gap: 12
        readonly property real ipad: 24
        readonly property real cellW: 200
        width: Math.min(cols * cellW + (cols - 1) * gap + 2 * ipad, root.width - 48)
        height: Math.min(content.implicitHeight, root.height - 24)
        anchors.centerIn: parent
        radius: 16
        color: Theme.light
        border.width: 1; border.color: Theme.accent
        opacity: root.fade
        scale: sc.value
        BoxShadow { z: -1; targetX: 0; targetY: 0; targetW: parent.width; targetH: parent.height; radius: 16; blur: 50; spread: -12; offsetY: 25; color: Theme.blackA(0.25) }
        MouseArea { anchors.fill: parent }

        Item {
            id: content
            x: card.ipad; y: card.ipad
            width: card.width - 2 * card.ipad
            implicitHeight: 2 * card.ipad + 28 + 12 + gridBox.height + 12 + 44
            readonly property real cw: (width - (card.cols - 1) * card.gap) / card.cols

            Text {
                text: Tr.t(root.mode === "vu" ? "player.chooser.vuTitle" : "player.chooser.animTitle")
                color: Theme.white; font.family: Theme.font; font.pixelSize: 18; font.bold: true; height: 28; verticalAlignment: Text.AlignVCenter
            }
            Text {
                anchors.right: parent.right; y: 4
                text: Tr.t(root.mode === "vu" ? "player.chooser.vuHint" : "player.chooser.animHint")
                color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 12
                width: Math.min(implicitWidth, parent.width - 220); elide: Text.ElideRight
            }

            // the cards: three per row, in a scrolling box when there are many
            Flickable {
                id: gridBox
                y: 28 + 12
                width: parent.width
                readonly property real cardH: root.mode === "vu" ? 8 + Math.round((content.cw - 16) * 675 / 1280) + 36
                                                                 : 8 + Math.round((content.cw - 16) / 2) + 36
                readonly property int rows: Math.max(1, Math.ceil(root.items.length / card.cols))
                contentHeight: rows * cardH + (rows - 1) * card.gap
                height: Math.min(contentHeight, root.height - 24 - 2 * card.ipad - 28 - 12 - 12 - 44)
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                flickDeceleration: 1500; maximumFlickVelocity: 4000

                // the previews live only while the popup is open: a VU look is
                // megabytes of texture, an animation a folder of pictures
                // gone once the fade-out ends: a still a scene queued with
                // Qt.callLater would otherwise land on a destroyed preview
                Loader {
                    active: root.visible
                    sourceComponent: cardsComp
                }
                Component {
                    id: cardsComp
                    Item {
                        width: gridBox.width; height: gridBox.contentHeight
                        Repeater {
                            model: root.items
                            Item {
                                id: cell
                                required property var modelData
                                required property int index
                                readonly property bool sel: root.mode === "vu" ? (Player.vuEnabled && Player.vuStyle === modelData.id)
                                                                              : (!Player.vuEnabled && Player.npAnimation === modelData.id)
                                x: (index % card.cols) * (content.cw + card.gap)
                                y: Math.floor(index / card.cols) * (gridBox.cardH + card.gap)
                                width: content.cw; height: gridBox.cardH
                                Rectangle {
                                    anchors.fill: parent; radius: 8
                                    scale: cellTap.tapScale
                                    color: cell.sel ? Theme.goldA(0.1) : cellTap.mix(Theme.dark, Theme.surface)
                                    border.width: cell.sel ? 2 : 1; border.color: cell.sel ? Theme.gold : Theme.accent
                                    // the still: the meters at rest, or the scene that never runs
                                    Item {
                                        id: pv
                                        x: 8; y: 8; width: parent.width - 16; height: gridBox.cardH - 8 - 36
                                        VuPanel {
                                            visible: root.mode === "vu"
                                            anchors.fill: parent
                                            style: root.mode === "vu" ? cell.modelData.id : "classic"   // never "": the panel would warn
                                            levels: [62, 55]
                                            devScale: root.devScale
                                        }
                                        Rectangle {
                                            visible: root.mode === "anim"
                                            anchors.fill: parent; radius: 6
                                            color: Theme.blackA(0.3); clip: true
                                            NpAnimation {
                                                anchors.fill: parent
                                                kind: root.mode === "anim" ? cell.modelData.id : ""
                                                live: false
                                                active: false
                                                devScale: root.devScale
                                            }
                                        }
                                    }
                                    Text {
                                        x: 12; y: pv.y + pv.height; width: parent.width - 24 - (cell.sel ? 22 : 0); height: 36; verticalAlignment: Text.AlignVCenter
                                        text: cell.modelData.label || ""; elide: Text.ElideRight
                                        color: cell.sel ? Theme.gold : Theme.white; font.family: Theme.font; font.pixelSize: 14; font.bold: cell.sel
                                    }
                                    Icon { visible: cell.sel; x: parent.width - 30; y: pv.y + pv.height + 9; name: "check-circle-2"; size: 18; color: Theme.gold }
                                }
                                Tap { id: cellTap; tap: 0.97; onClicked: root.choose(cell.modelData.id) }
                            }
                        }
                    }
                }
                // while the list is on its way, or when it did not come
                Spinner { anchors.centerIn: parent; radius: 16; visible: root.loading; active: root.loading && root.active }
                Text {
                    anchors.centerIn: parent; visible: !root.loading && root.loadError !== ""
                    text: root.loadError; color: Theme.red400; font.family: Theme.font; font.pixelSize: 14
                }
                ScrollBar_ { flick: gridBox }
            }

            Rectangle {
                y: gridBox.y + gridBox.height + 12
                width: parent.width; height: 44; radius: 8; color: ccTap.mix(Theme.accent, Theme.dark)
                Text { anchors.centerIn: parent; text: Tr.t("common.cancel"); color: Theme.white; font.family: Theme.font; font.pixelSize: 16 }
                Tap { id: ccTap; onClicked: root.close() }
            }
        }
    }
}
