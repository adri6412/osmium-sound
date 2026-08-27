// L'avviso "chiavetta collegata" (UsbToast.jsx): in basso a destra, sparisce
// da solo dopo 4,5 s, si chiude toccandolo. Non e' modale.
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    property bool open: false
    property bool closing: false
    property string text: ""
    anchors.fill: parent
    visible: open
    Spring { id: rise; stiffness: 550; damping: 30 }
    property real fade: 0
    Behavior on fade { NumberAnimation { duration: 300; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
    function show(label) {
        text = Tr.tf("usbToast.mounted", "label", label || "USB")
        open = true; closing = false
        rise.set(0); rise.to = 1; fade = 1
        auto.restart()
    }
    function close() { if (!open || closing) return; closing = true; rise.to = 0; fade = 0 }
    Timer { id: auto; interval: 4500; onTriggered: root.close() }
    Timer { interval: 50; repeat: true; running: root.closing; onTriggered: if (root.fade === 0) { root.open = false; root.closing = false } }
    Rectangle {
        id: box
        width: Math.min(320, 16 + 18 + 12 + msg.implicitWidth + 16); height: 48; radius: 12
        x: parent.width - 24 - width; y: parent.height - 24 - height + (1 - rise.value) * 12
        opacity: root.fade
        color: "#2a2a2a"; border.width: 1; border.color: "#3a3a3a"
        Rectangle { z: -1; x: 2; y: 6; width: parent.width; height: parent.height + 2; radius: 12; color: Qt.rgba(0, 0, 0, 0.43) }
        Icon { x: 16; anchors.verticalCenter: parent.verticalCenter; name: "usb"; size: 18; color: Theme.gold }
        Text { id: msg; x: 46; width: parent.width - 62; anchors.verticalCenter: parent.verticalCenter; text: root.text; elide: Text.ElideRight; color: Theme.white; font.family: Theme.font; font.pixelSize: 14 }
        Tap { onClicked: root.close() }
    }
}
