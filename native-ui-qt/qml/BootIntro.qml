// L'animazione di avvio (BootIntro.jsx): il filmato srotolato in fotogrammi
// JPEG a 15 fps (assets/intro/NNN.jpg), poi la dissolvenza di 600 ms di
// App.jsx. Sotto, la UI e' gia' pronta. Senza fotogrammi si parte diretti.
import QtQuick
import Hifi.Ui

Item {
    id: root
    property real devScale: 1
    property bool active: false
    property int nframes: 0
    property int cur: 0
    property bool fading: false
    readonly property int ring: 8
    visible: active
    anchors.fill: parent
    Component.onCompleted: {
        var dir = Sys.assets + "/intro/"
        var n = 0
        while (n < 256 && Sys.exists(dir + String(n + 1).padStart(3, "0") + ".jpg")) n++
        nframes = n
        if (n >= 2) { active = true; clock.start() }
    }
    function frameUrl(i) { return "file://" + Sys.assets + "/intro/" + String(i + 1).padStart(3, "0") + ".jpg" }
    Timer {
        id: clock
        interval: 1000 / 15; repeat: true
        onTriggered: {
            if (root.cur + 1 >= root.nframes) { clock.stop(); root.fading = true; return }
            root.cur++
        }
    }
    Rectangle { anchors.fill: parent; color: Theme.black; opacity: root.fading ? 0 : 1
                Behavior on opacity { NumberAnimation { duration: 600; easing.type: Easing.BezierSpline; easing.bezierCurve: [0.25, 0.1, 0.25, 1, 1, 1]; onRunningChanged: if (!running && root.fading) root.active = false } } }
    Item {
        anchors.fill: parent
        opacity: root.fading ? 0 : 1
        Behavior on opacity { NumberAnimation { duration: 600; easing.type: Easing.BezierSpline; easing.bezierCurve: [0.25, 0.1, 0.25, 1, 1, 1] } }   // transition: opacity 600ms ease
        // un anello di immagini precaricate: quella mostrata e le successive
        Repeater {
            model: root.nframes > 0 ? root.ring : 0
            Image {
                required property int index
                readonly property int frame: index + Math.floor(Math.max(0, root.cur - index + root.ring - 1) / root.ring) * root.ring
                anchors.fill: parent
                fillMode: Image.PreserveAspectCrop
                asynchronous: true; cache: false
                source: frame < root.nframes ? root.frameUrl(frame) : ""
                visible: frame === root.cur
                sourceSize.width: Math.round(root.width * root.devScale); sourceSize.height: Math.round(root.height * root.devScale)
            }
        }
    }
    MouseArea { anchors.fill: parent }        // assorbe tutto finche' non finisce
}
