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

    anchors.fill: fill ? parent : undefined
    active: !!target && Nav.item === target && Nav.active
    z: 100
    sourceComponent: Rectangle {
        color: Theme.goldA(0.12)
        border.width: 2
        border.color: Theme.gold
        radius: ring.radius
        opacity: 0
        Component.onCompleted: opacity = 1
        Behavior on opacity { NumberAnimation { duration: Theme.dur(120) } }
    }
}
