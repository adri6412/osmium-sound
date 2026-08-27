// La schermata principale: pannello Now Playing a sinistra (340 px),
// divisore a gradiente, browser della libreria a destra.
import QtQuick
import Hifi.Ui

Item {
    id: root
    property real devScale: 1
    property bool shown: true
    readonly property bool browsing: browser.browsing
    property alias browser: browser
    property alias mini: mini
    signal expand()
    signal openQueue()
    signal openSleep()
    function showPlaylists() { browser.showPlaylists() }

    Rectangle { anchors.fill: parent; color: Theme.dark }
    MiniPlayer {
        id: mini
        devScale: root.devScale
        onExpand: root.expand()
        onOpenQueue: root.openQueue()
        onOpenSleep: root.openSleep()
    }
    Rectangle {                                     // divisore
        x: 340; width: 1; height: 600
        gradient: Gradient {
            GradientStop { position: 0; color: Theme.borderA(0) }
            GradientStop { position: 0.15; color: Theme.border }
            GradientStop { position: 0.85; color: Theme.border }
            GradientStop { position: 1; color: Theme.borderA(0) }
        }
    }
    Browser { id: browser; devScale: root.devScale }
}
