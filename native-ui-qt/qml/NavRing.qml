// Il riflettore del telecomando intorno a un riquadro.
//
// Si disegna DENTRO il riquadro che illumina (di norma il suo MouseArea), non
// in uno strato sopra la scena: cosi' segue da solo la riga mentre la lista
// scorre, invece di doverle correre dietro. Nasce solo quando serve (il
// Loader e' spento il resto del tempo), e l'apparizione e' una dissolvenza
// corta — niente animazioni che continuano, la scheda video di questo
// apparecchio non e' un lusso.
import QtQuick
import Hifi.Ui

Loader {
    id: ring
    // chi e' illuminato: di norma chi ci contiene. Chi ha un riquadro grande e
    // un bersaglio piccolo (Cover Flow) passa `fill: false` e si mette da se'
    // x, y, larghezza e altezza.
    property Item target: parent
    property real radius: 10
    property bool fill: true
    // the faint gold wash inside the ring; a photo turns sepia under it, so
    // a big picture passes "transparent" and keeps just the outline
    property color tint: Theme.goldA(0.12)

    anchors.fill: fill ? parent : undefined
    active: !!target && Nav.item === target && Nav.active
    z: 100
    // Two rings: the gold one outside and a dark one just inside. On a dark
    // box the gold shows; on one that is already gold (the chosen option, the
    // main button) the gold melts into it and the dark line remains — with a
    // single ring the spotlight simply vanished there.
    sourceComponent: Rectangle {
        color: ring.tint
        border.width: 2
        border.color: Theme.gold
        radius: ring.radius
        opacity: 0
        Component.onCompleted: opacity = 1
        Behavior on opacity { NumberAnimation { duration: Theme.dur(120) } }
        Rectangle {
            anchors.fill: parent
            anchors.margins: 2
            color: "transparent"
            border.width: 2
            border.color: Theme.dark
            radius: Math.max(0, ring.radius - 2)
        }
    }
}
