// I due VU analogici (AnalogVUMeter.jsx / vu.c): quadranti, aghi, cappucci e
// cornice. Il pannello sta nell'artwork 1280x675 e si adatta al riquadro
// mantenendo la forma; gli angoli arrivano da Vu (leftDeg/rightDeg).
import QtQuick
import Hifi.Ui

Item {
    id: root
    property real devScale: 1
    readonly property real ps: Math.min(width / 1280, height / 675)
    readonly property real pw: 1280 * ps
    readonly property real ph: 675 * ps
    readonly property real px0: (width - pw) / 2
    readonly property real py0: (height - ph) / 2

    Rectangle { x: root.px0; y: root.py0; width: root.pw; height: root.ph; color: Theme.dark }
    Image {
        x: root.px0; y: root.py0; width: root.pw; height: root.ph
        source: Sys.assets + "/vu-meter-dials.png"
        smooth: true; asynchronous: true
        sourceSize.width: Math.round(root.pw * root.devScale); sourceSize.height: Math.round(root.ph * root.devScale)
    }
    Repeater {
        model: 2
        Item {
            required property int index
            x: root.px0 + (index === 0 ? 335 : 944) * root.ps
            y: root.py0 + 461 * root.ps
            Rectangle {                              // l'ago: 0,003 x 275 dell'artwork
                width: 0.003 * 1280 * root.ps
                height: 275 * root.ps
                x: -width / 2; y: -height
                color: "#111111"
                antialiasing: true
                transformOrigin: Item.Bottom
                rotation: index === 0 ? Vu.leftDeg : Vu.rightDeg
            }
            Rectangle {                              // cappuccio del perno
                width: 0.014 * 1280 * root.ps; height: width
                x: -width / 2; y: -height / 2
                radius: width / 2
                color: "#111111"
                antialiasing: true
            }
        }
    }
    Image {
        x: root.px0; y: root.py0; width: root.pw; height: root.ph
        source: Sys.assets + "/vu-meter-bezel.png"
        smooth: true; asynchronous: true
        sourceSize.width: Math.round(root.pw * root.devScale); sourceSize.height: Math.round(root.ph * root.devScale)
    }
}
