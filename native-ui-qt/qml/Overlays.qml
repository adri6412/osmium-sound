// Pannelli sovrapposti condivisi dalle due schermate (overlays.c): cassetto
// della coda (x:'100%' molla 240/28), timer di spegnimento e "salva come
// playlist" (scale 0,92 -> 1 con dissolvenza).
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    property int active: 0            // 0 nessuno, 1 coda, 2 salva, 3 sonno
    property int leaving: 0
    readonly property bool busy: active !== 0
    signal savedPlaylist()

    Spring { id: slide; stiffness: 240; damping: 28 }     // 0 dentro, 1 fuori
    property real fade: 0
    Behavior on fade { NumberAnimation { id: fadeAnim; duration: 200; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }

    function openQueue() {
        queue.load()
        active = 1; leaving = 0
        slide.set(1); slide.to = 0
        fadeAnim.duration = 200
        fade = 1
    }
    function openSleep() {
        active = 3; leaving = 0
        fadeAnim.duration = 180
        fade = 1
    }
    function openSave() {
        save.name = ""; save.msg = ""
        active = 2; leaving = 0
        fadeAnim.duration = 180
        fade = 1
    }
    function close() {
        if (active === 0) return
        leaving = active
        if (active === 1) slide.to = 1
        fadeAnim.duration = active === 1 ? 220 : 150
        fade = 0
    }
    // fine dell'uscita: quando la dissolvenza (e la molla) sono ferme
    Timer {
        interval: 30; repeat: true
        running: root.leaving !== 0
        onTriggered: if (root.fade === 0 && !slide.running) { root.active = 0; root.leaving = 0 }
    }

    visible: active !== 0
    // sfondo scuro: /60 per la coda, /70 per i dialoghi
    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, (root.active === 1 ? 0.6 : 0.7) * root.fade)
        MouseArea { anchors.fill: parent; onClicked: { if (root.active === 2) { root.active = 1; root.fade = 1 } else root.close() } }
    }

    // ─── coda ──────────────────────────────────────────────────────────────
    QueueDrawer {
        id: queue
        x: 1024 - 400 + slide.value * 400
        width: 400; height: 600
        visible: root.active === 1 || root.active === 2
        interactive: root.active === 1 && root.leaving === 0
        onClose: root.close()
        onSave: root.openSave()
    }

    // ─── salva come playlist ───────────────────────────────────────────────
    SavePlaylistDialog {
        id: save
        anchors.centerIn: parent
        visible: root.active === 2
        opacity: root.fade
        scale: 0.92 + 0.08 * root.fade
        onCancel: { root.active = 1; root.fade = 1 }
        onSaved: { root.active = 0; root.fade = 0; root.savedPlaylist() }
    }

    // ─── timer di spegnimento ──────────────────────────────────────────────
    SleepDialog {
        anchors.centerIn: parent
        visible: root.active === 3
        opacity: root.fade
        scale: 0.92 + 0.08 * root.fade
        onDone: root.close()
    }
    Keys.onEscapePressed: close()
}
