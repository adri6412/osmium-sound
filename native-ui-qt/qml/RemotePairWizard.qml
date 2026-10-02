// "Add a remote", as a small wizard over everything: which remote (the three
// certified models, or another one), then either the way to put that model
// in pairing mode while the box looks for it and pairs it by itself (the scan
// is told the model, api_server bt_remotes_scan), or the plain scan, a list
// to tap and the pairing. Opened from Settings → Remote control; the key map
// and the practice run (RemoteIntro) come by themselves once it closes.
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    property bool active: false
    visible: active || fade > 0
    anchors.fill: parent
    signal closed()
    NavScope { active: root.active }

    property real fade: 0
    Behavior on fade { NumberAnimation { duration: Theme.dur(220); easing.type: Easing.OutCubic } }

    readonly property var names: ({ firetv: "Fire TV", g20s: "G20S PRO", xiaomi: "Xiaomi" })
    property int step: 0             // 0 which remote, 1 a certified one, 2 another one
    property string model: ""
    // step 1: "looking", "done", "notYet"; step 2: "scanning", "list", "none", "pairing", "done", "failed"
    property string phase: ""
    property var found: []
    property string message: ""
    property int run: 0              // every new request stops the answers of the old ones

    function open() { run++; step = 0; model = ""; phase = ""; found = []; message = ""; active = true; fade = 1 }
    function close() { run++; active = false; fade = 0; closed() }
    function choose(m) {
        if (m === "other") { step = 2; scan(); return }
        model = m; step = 1; search()
    }
    function back() { run++; step = 0; model = ""; phase = ""; found = []; message = "" }
    function api(p) { return Api.apiBase + p }

    // ~2½ minutes of looking for the chosen model, in rounds of ten seconds
    function search() { var r = ++run; phase = "looking"; round(r, 12) }
    function round(r, left) {
        Api.post(api("/bt_remotes/scan"), { seconds: 10, model: model }, function(ok, d) {
            if (r !== root.run) return
            if (ok && d && d.paired) { root.phase = "done"; return }
            if (left <= 1) { root.phase = "notYet"; return }
            again.r = r; again.left = left - 1; again.interval = ok ? 500 : 3000; again.restart()
        }, 60000)
    }
    Timer { id: again; property int r: 0; property int left: 0; onTriggered: root.round(r, left) }

    function scan() {
        var r = ++run
        phase = "scanning"; found = []; message = ""
        Api.post(api("/bt_remotes/scan"), { seconds: 12 }, function(ok, d) {
            if (r !== root.run) return
            root.found = ok && d ? (d.found || []) : []
            root.phase = root.found.length ? "list" : "none"
        }, 60000)
    }
    function pair(mac) {
        var r = ++run
        phase = "pairing"; message = ""
        Api.post(api("/bt_remotes/add"), { mac: mac }, function(ok, d) {
            if (r !== root.run) return
            var good = ok && d && d.success !== false
            root.phase = good ? "done" : "failed"
            root.message = d && d.message ? String(d.message) : ""
        }, 120000)
    }

    Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0, 0, 0.74 * root.fade) }
    MouseArea { anchors.fill: parent; enabled: root.active }

    component Btn: Rectangle {
        id: b
        property string text: ""
        property bool gold: false
        signal clicked()
        width: bt.implicitWidth + 36; height: 44; radius: 8
        color: gold ? bTap.mix(Theme.gold, "#ca8a04") : bTap.mix(Theme.wa(0.06), Theme.wa(0.14))
        scale: bTap.tapScale
        Text { id: bt; anchors.centerIn: parent; text: b.text; color: b.gold ? Theme.black : Theme.silver
               font.family: Theme.font; font.pixelSize: 15; font.bold: b.gold }
        Tap { id: bTap; tap: 0.95; onClicked: b.clicked() }
    }

    Rectangle {
        id: card
        readonly property real pad: 22
        width: Math.min(root.width - 32, 620)
        height: Math.min(root.height - 32, 440)
        x: (root.width - width) / 2; y: (root.height - height) / 2
        radius: 16; color: Theme.light
        border.width: 1; border.color: Theme.goldA(0.35)
        opacity: root.fade
        scale: 0.97 + 0.03 * root.fade
        MouseArea { anchors.fill: parent }

        Text {
            id: title
            x: card.pad; y: card.pad; width: parent.width - 2 * card.pad - 40
            text: root.step === 1 ? root.names[root.model] : Tr.t("settings.remote.pair.title")
            color: Theme.white; font.family: Theme.font; font.pixelSize: 19; font.bold: true
            elide: Text.ElideRight
        }
        Item {                                         // close
            x: parent.width - card.pad - 32; y: card.pad - 6; width: 32; height: 32
            Icon { anchors.centerIn: parent; name: "x"; size: 18; color: Theme.silverA(0.7) }
            Tap { tap: 0.9; onClicked: root.close() }
        }

        Item {
            id: body
            x: card.pad; y: title.y + title.height + 14
            width: parent.width - 2 * card.pad
            height: foot.y - 14 - y

            // ── 0: which remote ────────────────────────────────────────────
            Column {
                visible: root.step === 0
                width: parent.width; spacing: 12
                Text { text: Tr.t("settings.remote.pair.which"); color: Theme.silver; font.family: Theme.font; font.pixelSize: 15 }
                Grid {
                    columns: 2; spacing: 10
                    Repeater {
                        model: [["firetv", "Fire TV", "remote"], ["g20s", "G20S PRO", "remote"], ["xiaomi", "Xiaomi", "remote"], ["other", "", "bluetooth-searching"]]
                        Rectangle {
                            required property var modelData
                            width: (body.width - 10) / 2; height: 64; radius: 12
                            color: tTap.mix(Theme.surface, Theme.accent)
                            border.width: 1; border.color: Theme.border
                            scale: tTap.tapScale
                            Icon { x: 18; anchors.verticalCenter: parent.verticalCenter; name: parent.modelData[2]; size: 22
                                   color: parent.modelData[0] === "other" ? Theme.silverA(0.7) : Theme.gold }
                            Text {
                                x: 52; width: parent.width - 62; anchors.verticalCenter: parent.verticalCenter
                                text: parent.modelData[0] === "other" ? Tr.t("settings.remote.pair.other") : parent.modelData[1]
                                color: Theme.white; font.family: Theme.font; font.pixelSize: 16; wrapMode: Text.Wrap
                            }
                            Tap { id: tTap; tap: 0.96; onClicked: root.choose(parent.modelData[0]) }
                        }
                    }
                }
            }

            // ── 1: a certified remote ──────────────────────────────────────
            Column {
                visible: root.step === 1
                width: parent.width; spacing: 14
                Text {
                    width: parent.width; wrapMode: Text.Wrap
                    text: root.model ? Tr.t("settings.remote.pair.how." + root.model) : ""
                    color: Theme.white; font.family: Theme.font; font.pixelSize: 18; lineHeight: 1.25
                }
                Text {
                    width: parent.width; wrapMode: Text.Wrap
                    text: Tr.t("settings.remote.pair.wait")
                    color: Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 14
                }
                Row {
                    spacing: 12; height: 40
                    Spinner { visible: root.phase === "looking"; active: visible && root.active; radius: 12; thickness: 3; anchors.verticalCenter: parent.verticalCenter }
                    Icon { visible: root.phase !== "looking"; anchors.verticalCenter: parent.verticalCenter; size: 24
                           name: root.phase === "done" ? "check-circle" : "info"; color: root.phase === "done" ? Theme.emerald : Theme.silverA(0.7) }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        width: body.width - 40; wrapMode: Text.Wrap
                        text: root.phase === "done" ? Tr.tf("settings.remote.pair.paired", "name", root.names[root.model] || "")
                            : root.phase === "notYet" ? Tr.t("settings.remote.pair.notYet")
                            : Tr.tf("settings.remote.pair.looking", "name", root.names[root.model] || "")
                        color: root.phase === "done" ? Theme.emerald : Theme.silver; font.family: Theme.font; font.pixelSize: 15
                    }
                }
            }

            // ── 2: another remote ──────────────────────────────────────────
            Item {
                visible: root.step === 2
                anchors.fill: parent
                Text {
                    id: otherHelp
                    width: parent.width; wrapMode: Text.Wrap
                    text: Tr.t("settings.remote.btHelp")
                    color: Theme.silverA(0.75); font.family: Theme.font; font.pixelSize: 14
                }
                Row {
                    visible: root.phase === "scanning" || root.phase === "pairing" || root.phase === "done" || root.phase === "none" || root.phase === "failed"
                    y: otherHelp.height + 18; spacing: 12
                    Spinner { visible: root.phase === "scanning" || root.phase === "pairing"; active: visible && root.active; radius: 12; thickness: 3; anchors.verticalCenter: parent.verticalCenter }
                    Icon { visible: root.phase === "done" || root.phase === "none" || root.phase === "failed"; anchors.verticalCenter: parent.verticalCenter; size: 24
                           name: root.phase === "done" ? "check-circle" : "info"; color: root.phase === "done" ? Theme.emerald : Theme.silverA(0.7) }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        width: body.width - 40; wrapMode: Text.Wrap
                        text: root.phase === "scanning" ? Tr.t("settings.remote.btSearching")
                            : root.phase === "pairing" ? Tr.t("settings.remote.btPairing")
                            : root.phase === "none" ? Tr.t("settings.remote.btFoundNone")
                            : root.message || (root.phase === "done" ? Tr.t("settings.remote.pair.pairedOther") : "")
                        color: root.phase === "done" ? Theme.emerald : Theme.silver; font.family: Theme.font; font.pixelSize: 15
                    }
                }
                // what answered, to tap
                Flickable {
                    visible: root.phase === "list"
                    y: otherHelp.height + 14; width: parent.width; height: parent.height - y
                    contentHeight: flist.height; clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    Column {
                        id: flist
                        width: parent.width; spacing: 8
                        Repeater {
                            model: root.found
                            Rectangle {
                                required property var modelData
                                width: flist.width; height: 54; radius: 10
                                color: fTap.mix(Theme.surface, Theme.accent)
                                Icon { x: 14; anchors.verticalCenter: parent.verticalCenter; name: "remote"; size: 18; color: Theme.gold }
                                Column {
                                    x: 44; anchors.verticalCenter: parent.verticalCenter
                                    Text { text: String(parent.parent.modelData.name || parent.parent.modelData.mac); color: Theme.white; font.family: Theme.font; font.pixelSize: 15 }
                                    Text { text: String(parent.parent.modelData.mac); color: Theme.silverA(0.5); font.family: Theme.mono; font.pixelSize: 11 }
                                }
                                Tap { id: fTap; onClicked: root.pair(parent.modelData.mac) }
                            }
                        }
                    }
                }
            }
        }

        // ── the buttons ─────────────────────────────────────────────────────
        Item {
            id: foot
            x: card.pad; width: parent.width - 2 * card.pad; height: 44
            y: card.height - card.pad - height
            Btn {
                visible: root.step > 0 && root.phase !== "done"
                text: Tr.t("common.back")
                onClicked: root.back()
            }
            Row {
                anchors.right: parent.right; spacing: 10
                Btn {
                    visible: (root.step === 1 && root.phase === "notYet") || (root.step === 2 && (root.phase === "none" || root.phase === "failed" || root.phase === "list"))
                    text: root.step === 1 ? Tr.t("settings.remote.pair.retry") : Tr.t("settings.remote.btSearch")
                    onClicked: root.step === 1 ? root.search() : root.scan()
                }
                Btn {
                    id: doneBtn
                    visible: root.phase === "done"
                    gold: true
                    text: Tr.t("tutorial.finish")
                    onClicked: root.close()
                }
            }
        }
    }
}
