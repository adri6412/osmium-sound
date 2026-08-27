// L'orologio a schermo intero (Screensaver.jsx / screensaver.c): dopo 5
// minuti senza tocchi e senza musica, oppure alzato a mano dall'orologio del
// Now Playing (allora si toglie solo con un tocco). Dissolvenza di 1 s, sfondo
// che si sposta fra 5 posizioni ogni 45 s, due punti che lampeggiano.
import QtQuick
import Hifi.Ui

Item {
    id: root
    property int idleMs: 300000
    property real lastInput: 0
    property bool blocked: false
    property bool active: false
    property bool manual: false
    property bool closing: false
    property real shownAt: 0
    visible: active
    anchors.fill: parent

    property real fade: 0
    Behavior on fade { NumberAnimation { duration: 1000; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeInOut } }
    function show(man) {
        if (active && !closing) return
        active = true; closing = false; manual = !!man
        shownAt = Sys.now(); driftIdx = 0; dx = 0; dy = 0
        fade = 1
    }
    function hide() { if (!active || closing) return; closing = true; fade = 0 }
    Timer { interval: 50; repeat: true; running: root.closing; onTriggered: if (root.fade === 0) { root.active = false; root.closing = false; root.manual = false } }
    // 5 minuti di inattivita' senza riproduzione locale; se la musica riparte
    // da fuori si toglie da solo (tranne quello alzato a mano)
    Timer {
        interval: 5000; repeat: true; running: true
        onTriggered: {
            if (!root.active) {
                if (!Player.playing && Sys.now() - root.lastInput >= root.idleMs && !root.blocked) root.show(false)
            } else if (!root.manual && Player.playing) root.hide()
        }
    }
    // sfondo che si sposta: gli stessi 5 sfasamenti del JSX
    readonly property var drift: [[0, 0], [0.08, 0.05], [-0.06, 0.09], [0.05, -0.07], [-0.08, -0.04]]
    property int driftIdx: 0
    property real dx: 0
    property real dy: 0
    Behavior on dx { NumberAnimation { duration: 4000; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeInOut } }
    Behavior on dy { NumberAnimation { duration: 4000; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeInOut } }
    Timer { interval: 45000; repeat: true; running: root.active; onTriggered: { root.driftIdx = (root.driftIdx + 1) % 5; root.dx = root.drift[root.driftIdx][0]; root.dy = root.drift[root.driftIdx][1] } }
    property date now: new Date()
    Timer { interval: 500; repeat: true; running: root.active; triggeredOnStart: true; onTriggered: root.now = new Date() }

    Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0, 0, root.fade) }
    Rectangle {
        x: -parent.width / 2 + root.dx * parent.width; y: -parent.height / 2 + root.dy * parent.height
        width: parent.width * 2; height: parent.height * 2
        opacity: 0.2 * root.fade
        gradient: Gradient {
            orientation: Gradient.Vertical
            GradientStop { position: 0; color: Theme.dark }
            GradientStop { position: 0.5; color: Theme.black }
            GradientStop { position: 1; color: Theme.gray }
        }
    }
    Item {
        anchors.fill: parent
        opacity: root.fade
        readonly property real cy: 300 - 40
        Row {
            id: clock
            anchors.horizontalCenter: parent.horizontalCenter
            y: parent.cy + 64 - 192 * 0.78
            spacing: 16
            Text { text: Qt.formatTime(root.now, "HH"); color: Theme.white; font.family: Theme.font; font.pixelSize: 192; font.letterSpacing: 2 }
            Text { text: ":"; color: Qt.rgba(1, 1, 1, root.now.getSeconds() % 2 === 0 ? 0.5 : 0.2); font.family: Theme.font; font.pixelSize: 160; anchors.baseline: clock.children[0].baseline; anchors.baselineOffset: -32 }
            Text { text: Qt.formatTime(root.now, "mm"); color: Theme.white; font.family: Theme.font; font.pixelSize: 192; font.letterSpacing: 2 }
        }
        Text { anchors.horizontalCenter: parent.horizontalCenter; y: parent.cy + 64 + 32; height: 36; verticalAlignment: Text.AlignVCenter; text: Qt.formatTime(root.now, "ss"); color: Theme.goldA(0.8); font.family: Theme.mono; font.pixelSize: 30; font.letterSpacing: 6 }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter; y: parent.cy + 64 + 32 + 36 + 16; height: 32; verticalAlignment: Text.AlignVCenter
            text: (I18n.lang === "it" ? root.now.toLocaleDateString(Qt.locale("it_IT"), "dddd d MMMM yyyy") : root.now.toLocaleDateString(Qt.locale("en_US"), "dddd, MMMM d, yyyy")).toUpperCase()
            color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 24; font.letterSpacing: 2.4
        }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter; y: parent.cy + 256 - 8; spacing: 8; opacity: 0.2
            Rectangle { width: 8; height: 8; radius: 4; color: Theme.gold; anchors.verticalCenter: parent.verticalCenter }
            Text { text: "HIFI PLAYER"; color: Theme.white; font.family: Theme.font; font.pixelSize: 14; font.bold: true; font.letterSpacing: 7; anchors.verticalCenter: parent.verticalCenter }
        }
    }
    // il tocco sveglia sempre; il movimento del mouse solo se non e' voluto
    MouseArea {
        anchors.fill: parent
        hoverEnabled: !root.manual
        onReleased: if (Sys.now() - root.shownAt > 400) root.hide()
        onPositionChanged: if (!root.manual && Sys.now() - root.shownAt > 400) root.hide()
        onWheel: if (!root.manual) root.hide()
    }
    Keys.onPressed: if (!root.manual) root.hide()
}
