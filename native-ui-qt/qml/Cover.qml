// Copertina con angoli tondi e ripiego (nota grigia) se manca.
import QtQuick
import QtQuick.Effects
import Hifi.Ui

Item {
    id: root
    property url source
    property real radius: 16
    property real devScale: 1
    property real fallbackIcon: 40
    property color border: Theme.wa(0.08)
    readonly property bool ready: img.status === Image.Ready
    Rectangle {
        anchors.fill: parent
        radius: root.radius
        color: Theme.gray
        visible: !root.ready
        Icon { anchors.centerIn: parent; name: "music"; size: root.fallbackIcon; color: Theme.silverA(0.2) }
    }
    Image {
        id: img
        anchors.fill: parent
        source: root.source
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: true
        visible: false
        sourceSize.width: Math.round(root.width * root.devScale)
        sourceSize.height: Math.round(root.height * root.devScale)
    }
    Rectangle {
        id: mask
        anchors.fill: parent
        radius: root.radius
        visible: false
        layer.enabled: true
        layer.smooth: true
    }
    MultiEffect {
        anchors.fill: parent
        source: img
        visible: root.ready
        maskEnabled: true
        maskSource: mask
    }
    Rectangle {
        anchors.fill: parent
        radius: root.radius
        color: "transparent"
        border.width: 1
        border.color: root.border
    }
}
