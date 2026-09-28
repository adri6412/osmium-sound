// The key map of a remote the appliance knows out of the box (Fire TV,
// G20S PRO, Xiaomi — kModels in remote.cpp), shown once, the first time that
// model shows up among the input devices: right after it has been paired,
// or on an appliance that already had it when this screen arrived.
//
// A card like the tour's: the annotated drawing (assets/remotes/<model>-<lang>
// .jpg, the same pictures the web admin shows), whole and without scrolling,
// and "Got it" at the bottom, where the remote's spotlight starts.
//
// Which models were already shown lives in <config>/remote-intro-seen
// (comma-separated ids). Settings → Remote control opens it again.
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    property bool active: false
    property string model: ""
    // opened from Settings: no tour after it (the person asked for the map)
    property bool manual: false
    // the first introduction of a remote ends with the tour of how to use it
    signal tourWanted(string model)
    // something else owns the screen (a dialog, the tour, the wizard):
    // the card waits for it to go
    property bool blocked: false
    visible: active || fade > 0
    anchors.fill: parent
    NavScope { active: root.active }
    // the picture is no longer a stop: the only thing to press is "Got it"
    readonly property Item navFirst: okTap

    property real fade: 0
    Behavior on fade { NumberAnimation { duration: Theme.dur(240); easing.type: Easing.OutCubic } }

    readonly property var labels: ({ firetv: "Fire TV", g20s: "G20S PRO", xiaomi: "Xiaomi" })
    readonly property string lang: Tr.lang === "it" ? "it" : "en"
    readonly property string picture: model ? "file://" + Sys.assets + "/remotes/" + model + "-" + lang + ".jpg" : ""

    function seen() { return Sys.conf("remote-intro-seen", "").split(",").filter(function(s) { return s !== "" }) }
    function open(m, byHand) {
        model = m
        manual = !!byHand
        active = true
        fade = 1
    }
    function close() {
        var s = seen()
        var first = model && s.indexOf(model) < 0
        if (first) { s.push(model); Sys.setConf("remote-intro-seen", s.join(",")) }
        var m = model
        active = false
        fade = 0
        pending = ""
        if (first && !manual) tourWanted(m)
        else Qt.callLater(check)                 // a second new remote, paired together
    }

    // a model that has not been introduced yet, waiting for the screen
    property string pending: ""
    function check() {
        if (active) return
        var s = seen(), devs = Remote.devices
        for (var i = 0; i < devs.length; i++) {
            var m = devs[i].model
            if (m && root.labels[m] && s.indexOf(m) < 0) { pending = m; wait.restart(); return }
        }
    }
    Connections { target: Remote; function onDevicesChanged() { root.check() } }
    Component.onCompleted: check()
    // 🚨 Not straight away: a remote is often paired from inside a dialog or
    // the setup wizard, and the card must not land on top of them.
    Timer {
        id: wait
        interval: 900; repeat: true
        onTriggered: {
            if (!root.pending || root.active) { stop(); return }
            if (!root.blocked) { stop(); root.open(root.pending) }
        }
    }

    Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0, 0, 0.74 * root.fade) }
    MouseArea { anchors.fill: parent; enabled: root.active }       // nothing underneath takes a touch

    Rectangle {
        id: card
        readonly property real pad: 18
        width: Math.min(root.width - 32, 980)
        height: root.height - 32
        x: (root.width - width) / 2; y: 16
        radius: 16
        color: Theme.light
        border.width: 1; border.color: Theme.goldA(0.35)
        opacity: root.fade
        scale: 0.97 + 0.03 * root.fade

        Text {
            id: title
            x: card.pad; y: card.pad; width: parent.width - 2 * card.pad
            text: Tr.tf("settings.remote.intro.title", "name", root.labels[root.model] || "")
            color: Theme.white; font.family: Theme.font; font.pixelSize: 18; font.bold: true
            elide: Text.ElideRight
        }
        Text {
            id: sub
            x: card.pad; y: title.y + title.height + 4; width: parent.width - 2 * card.pad
            text: Tr.t("settings.remote.intro.body")
            color: Theme.silverA(0.75); font.family: Theme.font; font.pixelSize: 13
            wrapMode: Text.Wrap
        }

        // 🚨 The whole remote at once, fitted to the frame: it used to be as
        // wide as the card and scroll, and the owner had to scroll to find the
        // key in their hand. The pictures are drawn for this (remote-map.py
        // --ui: wide, with large labels), so fitted they stay readable.
        Rectangle {
            id: frame
            x: card.pad; y: sub.y + sub.height + 12
            width: parent.width - 2 * card.pad
            height: bottomBar.y - 12 - y
            radius: 10; color: Theme.dark; clip: true
            Image {
                id: pic
                anchors.fill: parent
                anchors.margins: 6
                source: root.picture
                asynchronous: true; smooth: true; mipmap: true
                fillMode: Image.PreserveAspectFit
            }
        }

        Item {
            id: bottomBar
            x: card.pad; width: parent.width - 2 * card.pad; height: 44
            y: card.height - card.pad - height
            Text {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - okBtn.width - 16
                text: Tr.t("settings.remote.intro.later")
                color: Theme.silverA(0.55); font.family: Theme.font; font.pixelSize: 12
                wrapMode: Text.Wrap
            }
            Rectangle {
                id: okBtn
                anchors.right: parent.right
                width: okText.implicitWidth + 44; height: 44; radius: 8
                color: okTap.mix(Theme.gold, "#ca8a04")
                scale: okTap.tapScale
                Text { id: okText; anchors.centerIn: parent; text: Tr.t("settings.remote.intro.gotIt"); color: Theme.black; font.family: Theme.font; font.pixelSize: 15; font.bold: true }
                Tap { id: okTap; tap: 0.95; onClicked: root.close() }
            }
        }
    }
}
