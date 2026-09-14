// Alone morbido attorno a un elemento tondo: l'equivalente esatto di un
// `box-shadow: 0 0 <blur>px <colore>` CSS su un cerchio, senza sfocature.
//
// Un box-shadow con blur B e' la forma sfocata con una gaussiana di sigma
// B/2: fuori dal bordo l'alpha vale a0 * (1 - Phi(d/sigma)), con d la
// distanza dal bordo. Qui e' un gradiente radiale con gli scalini di quella
// curva. Prima si usava MultiEffect.blur su un disco: misurato sul
// mini PC, dava un terzo dell'intensita' e meta' della portata di Electron
// (al bordo +13 sul fondo contro +35, a 14 px +7 contro +18).
import QtQuick
import QtQuick.Shapes

Item {
    id: root
    property real radius: 28          // raggio dell'elemento (il pulsante)
    property real blur: 24            // il blur del box-shadow CSS, in punti
    property color color: "#d4af37"   // colore dell'alone, alpha compresa (rgba del CSS)
    readonly property real sigma: blur / 2
    readonly property real outer: radius + 3 * sigma
    // centrato sull'elemento: chi lo usa lo ancora al centro del pulsante
    width: outer * 2; height: outer * 2
    function a(k) { return Qt.rgba(color.r, color.g, color.b, color.a * k) }
    // 1 - Phi(z) per z = -1, 0, 0.5, 1, 1.5, 2, 3
    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeWidth: -1
            fillGradient: RadialGradient {
                centerX: root.outer; centerY: root.outer
                focalX: root.outer; focalY: root.outer
                centerRadius: root.outer
                GradientStop { position: 0; color: root.a(1) }
                GradientStop { position: (root.radius - root.sigma) / root.outer; color: root.a(0.841) }
                GradientStop { position: root.radius / root.outer; color: root.a(0.5) }
                GradientStop { position: (root.radius + 0.5 * root.sigma) / root.outer; color: root.a(0.309) }
                GradientStop { position: (root.radius + root.sigma) / root.outer; color: root.a(0.159) }
                GradientStop { position: (root.radius + 1.5 * root.sigma) / root.outer; color: root.a(0.067) }
                GradientStop { position: (root.radius + 2 * root.sigma) / root.outer; color: root.a(0.023) }
                GradientStop { position: 1; color: root.a(0) }
            }
            PathAngleArc { centerX: root.outer; centerY: root.outer; radiusX: root.outer; radiusY: root.outer; startAngle: 0; sweepAngle: 360 }
        }
    }
}
