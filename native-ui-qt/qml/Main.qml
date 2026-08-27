// La radice: scala la tela logica 1024x600 sul modo video reale ("contain",
// come ScaledCanvas.jsx) e impila le schermate e gli strati sovrapposti nello
// stesso ordine del ciclo di app.c.
import QtQuick
import Hifi.Ui

Item {
    id: root
    // fattore di scala e scarti, letti anche dal canale di collaudo (main.cpp)
    readonly property real s: Math.min(width / Theme.canvasW, height / Theme.canvasH)
    readonly property real ox: Math.floor((width - Theme.canvasW * s) / 2)
    readonly property real oy: Math.floor((height - Theme.canvasH * s) / 2)
    property alias app: canvas

    Rectangle { anchors.fill: parent; color: Theme.dark }

    App {
        id: canvas
        x: root.ox; y: root.oy
        width: Theme.canvasW; height: Theme.canvasH
        scale: root.s
        transformOrigin: Item.TopLeft
        devicePixelScale: root.s
    }
}
