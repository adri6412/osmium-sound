// The bottom-right CD-rip notification: once a rip starts the big window
// (CdRip) closes and the rip runs in the background; this card follows its
// progress from anywhere in the kiosk, and stays — with the result and an
// Eject button — once it is done. Tapping it while ripping reopens CdRip.
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    readonly property var cd: Ui.cdrip
    // set by App.qml: a modal overlay (wizard, update, dialog, keyboard, …) is on
    property bool blocked: false

    readonly property bool ripping: !!cd && cd.ripping
    readonly property bool finished: !!cd && (cd.state === "done" || cd.state === "error" || cd.state === "cancelled")
    // dismissed by hand after it finished; cleared when a new rip starts
    property bool dismissed: false
    // not while the big CdRip window is open (it shows the same progress), and
    // not under a modal overlay
    readonly property bool shown: !!cd && !blocked && !cd.open && !dismissed && (ripping || finished)

    readonly property real pct: cd ? Math.max(0, Math.min(100, cd.progress)) : 0
    readonly property string title: {
        if (!cd) return ""
        var ar = (cd.artist || "") + (cd.artist && cd.album ? " — " : "") + (cd.album || "")
        return ar || Tr.t("player.cd.ripping")
    }

    anchors.fill: parent
    visible: fade > 0.01

    onRippingChanged: if (ripping) dismissed = false

    Spring { id: rise; stiffness: 550; damping: 30; rate: Theme.motionRate }
    property real fade: 0
    Behavior on fade { NumberAnimation { duration: Theme.dur(300); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
    onShownChanged: {
        if (shown) { rise.set(0); rise.to = 1; fade = 1 }
        else fade = 0
    }

    Rectangle {
        id: box
        width: Math.min(340, root.width - 48)
        height: root.ripping ? 96 : (72 + ejectBtn.height + 12)
        x: parent.width - 24 - width
        y: parent.height - 24 - height + (1 - rise.value) * 12
        radius: 12
        opacity: root.fade
        scale: 0.96 + 0.04 * rise.value
        color: "#2a2a2a"; border.width: 1; border.color: "#3a3a3a"
        BoxShadow { z: -1; targetX: 0; targetY: 0; targetW: parent.width; targetH: parent.height; radius: 12; blur: 50; spread: -12; offsetY: 25; color: Theme.blackA(0.25) }

        // spinning disc while ripping; the result icon once done
        Icon {
            id: ic
            x: 16; y: 16; size: 20
            name: root.ripping ? "disc" : (root.cd && root.cd.state === "done" ? "check" : (root.cd && root.cd.state === "cancelled" ? "disc" : "x"))
            color: root.cd && root.cd.state === "done" ? "#34d399"
                   : (root.cd && root.cd.state === "error" ? Theme.red300 : Theme.gold)
            RotationAnimation on rotation { from: 0; to: 360; duration: 2000; loops: Animation.Infinite; running: root.visible && root.ripping }
        }

        // title / result headline
        Text {
            id: head
            x: 46; y: 15; width: parent.width - 46 - (root.ripping ? 16 : 36)
            height: 20; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
            text: root.ripping ? root.title
                  : (root.cd && root.cd.state === "done" ? Tr.t("player.cd.ripDone")
                     : (root.cd && root.cd.state === "cancelled" ? Tr.t("player.cd.cancelled")
                        : (root.cd && root.cd.msg ? root.cd.msg : Tr.t("player.cd.ripError"))))
            wrapMode: root.ripping ? Text.NoWrap : Text.Wrap
            maximumLineCount: root.ripping ? 1 : 2
            color: Theme.white; font.family: Theme.font; font.pixelSize: 14; font.bold: true
        }

        // ── while ripping: progress bar + "track X of Y" + percentage ──────────
        Rectangle {
            visible: root.ripping
            x: 46; y: 46; width: parent.width - 46 - 16; height: 8; radius: 4; color: Theme.wa(0.1)
            Rectangle {
                width: parent.width * root.pct / 100; height: 8; radius: 4
                gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: Theme.gold } GradientStop { position: 1; color: Theme.yellow400 } }
            }
        }
        Text {
            visible: root.ripping
            x: 46; y: 62; height: 18; verticalAlignment: Text.AlignVCenter
            text: Tr.tf("player.cd.ripProgress", "track", String(root.cd ? root.cd.curTrack : 0)).replace("{total}", String(root.cd ? root.cd.total : 0))
            color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 12
        }
        Text {
            visible: root.ripping
            anchors.right: parent.right; anchors.rightMargin: 16; y: 62; height: 18; verticalAlignment: Text.AlignVCenter
            text: Math.round(root.pct) + "%"
            color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 12
        }

        // body tap while ripping → reopen the big window (to cancel, etc.)
        Tap { enabled: root.ripping; onClicked: if (root.cd) root.cd.openDialog() }

        // ── when finished: Eject + a close (X) ─────────────────────────────────
        Item {
            visible: !root.ripping
            x: parent.width - 16 - 24; y: 12; width: 24; height: 24
            Icon { anchors.centerIn: parent; name: "x"; size: 14; color: Theme.silverA(0.6) }
            Tap { grow: 6; onClicked: root.dismissed = true }
        }
        Rectangle {
            id: ejectBtn
            visible: !root.ripping
            x: 46; y: 46; width: ejText.implicitWidth + 28; height: 32; radius: 8
            color: ejTap.mix(Theme.gold, "#ca8a04")
            Text { id: ejText; anchors.centerIn: parent; text: Tr.t("player.cd.eject"); color: Theme.black; font.family: Theme.font; font.pixelSize: 13; font.bold: true }
            Tap { id: ejTap; onClicked: if (root.cd) root.cd.eject() }
        }
    }
}
