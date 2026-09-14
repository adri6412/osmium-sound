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
    readonly property bool ready: img.status === Image.Ready || prev.hasImage

    DiagonalFallback {                         // bg-gradient-to-br from-hifi-gray to-hifi-dark
        anchors.fill: parent
        radius: root.radius
        visible: !root.ready
        Icon { anchors.centerIn: parent; name: "music"; size: root.fallbackIcon; color: Theme.silverA(0.2) }
    }

    // 🚨 Due immagini, non una: quando l'indirizzo cambia (le radio ne cambiano
    // uno ogni dieci secondi per aggiornare la copertina del brano in onda) la
    // nuova si carica NASCOSTA e si passa a lei solo quando e' pronta. Con una
    // sola immagine, nell'attimo del caricamento lo stato non e' "pronto" e si
    // vedeva comparire il ripiego grigio: il lampeggio periodico.
    Image {
        id: prev
        anchors.fill: parent
        property bool hasImage: status === Image.Ready
        visible: false
        fillMode: Image.PreserveAspectCrop
        asynchronous: false          // e' gia' nella cache: passaggio immediato
        cache: true
        smooth: true
        sourceSize.width: img.sourceSize.width
        sourceSize.height: img.sourceSize.height
        // 🚨 anche questa deve essere una texture a piena risoluzione: nascosta e
        // senza strato l'effetto non la disegna affatto, e al posto del lampeggio
        // grigio si vedeva sparire la copertina (misurato sull'apparecchio).
        layer.enabled: true
        layer.smooth: true
        layer.textureSize: img.layer.textureSize
    }
    Image {
        id: img
        anchors.fill: parent
        source: root.source
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: true
        visible: false
        smooth: true
        // 🚨 il doppio dei pixel dello schermo: cosi' si decodifica alla misura
        // nativa di quel che manda Lyrion (600 px) e a rimpicciolire e' la
        // scheda video, come fa Chromium. Chiedendo esattamente 1x era Qt a
        // ridurre in fase di caricamento, e si perdeva dettaglio.
        sourceSize.width: Math.round(root.width * root.devScale * 2)
        sourceSize.height: Math.round(root.height * root.devScale * 2)
        // 🚨 la texture che l'effetto usa deve stare alla risoluzione vera: senza
        // questa riga la mascheratura la rasterizza alla misura in punti e la
        // copertina perdeva il 20 % di dettaglio (misurato sull'apparecchio).
        layer.enabled: true
        layer.smooth: true
        layer.textureSize: Qt.size(Math.ceil(root.width * root.devScale * 2),
                                   Math.ceil(root.height * root.devScale * 2))
        onStatusChanged: if (status === Image.Ready) prev.source = source
    }
    Rectangle {
        id: mask
        anchors.fill: parent
        radius: root.radius
        visible: false
        layer.enabled: true
        layer.smooth: true
        // alla risoluzione vera, se no gli angoli tondi vengono seghettati
        layer.textureSize: Qt.size(Math.ceil(root.width * root.devScale),
                                   Math.ceil(root.height * root.devScale))
    }
    MultiEffect {
        anchors.fill: parent
        source: img.status === Image.Ready ? img : prev
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
