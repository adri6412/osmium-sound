// Tinte e misure condivise, da tailwind.config.js e da gfx.h/ui.h della UI in C.
pragma Singleton
import QtQuick

QtObject {
    readonly property color dark:    "#0a0a0a"      // hifi-dark
    readonly property color panel:   "#0f0f0f"      // hifi-panel
    readonly property color gray:    "#1a1a1a"      // hifi-gray
    readonly property color surface: "#161616"      // hifi-surface
    readonly property color light:   "#2a2a2a"      // hifi-light
    readonly property color accent:  "#3a3a3a"      // hifi-accent
    readonly property color border:  "#252525"      // hifi-border
    readonly property color gold:    "#d4af37"      // hifi-gold
    readonly property color silver:  "#c0c0c0"      // hifi-silver
    readonly property color white:   "#ffffff"
    readonly property color black:   "#000000"
    readonly property color emerald: "#10b981"
    readonly property color red300:  "#fca5a5"
    readonly property color red400:  "#f87171"
    readonly property color red500:  "#ef4444"
    readonly property color yellow400: "#facc15"
    readonly property color green500: "#22c55e"

    function wa(a)     { return Qt.rgba(1, 1, 1, a) }
    function silverA(a) { return Qt.rgba(0xc0/255, 0xc0/255, 0xc0/255, a) }
    function goldA(a)  { return Qt.rgba(0xd4/255, 0xaf/255, 0x37/255, a) }
    function blackA(a) { return Qt.rgba(0, 0, 0, a) }
    function redA(a)   { return Qt.rgba(0xef/255, 0x44/255, 0x44/255, a) }
    function borderA(a) { return Qt.rgba(0x25/255, 0x25/255, 0x25/255, a) }
    function panelA(a) { return Qt.rgba(0x0f/255, 0x0f/255, 0x0f/255, a) }
    function mix(a0, b0, f) {
        var a = Qt.color(a0), b = Qt.color(b0)
        return Qt.rgba(a.r + (b.r - a.r) * f, a.g + (b.g - a.g) * f, a.b + (b.b - a.b) * f, a.a + (b.a - a.a) * f)
    }

    readonly property string font: "DejaVu Sans"
    readonly property string mono: "DejaVu Sans Mono"

    // curva "easeOut" di framer-motion / CSS: cubic-bezier(0, 0, 0.58, 1)
    readonly property var easeOut: [0, 0, 0.58, 1, 1, 1]
    readonly property var easeInOut: [0.42, 0, 0.58, 1, 1, 1]
    readonly property var easeIn: [0.42, 0, 1, 1, 1, 1]

    readonly property int canvasW: 1024
    readonly property int canvasH: 600

    // Quanti pixel veri vale un punto della tela: 1 a 1024x600, 1,25 a 720p,
    // 1,875 a 1080p, 3,6 a 4K. La imposta Main.qml appena sa il modo video.
    // 🚨 Serve a tutto cio' che diventa una TEXTURE (icone dentro un effetto,
    // maschere, immagini): quella roba viene disegnata alla misura in punti e
    // poi ingrandita, quindi senza questo fattore si vede sgranata mentre il
    // testo, che e' geometria, resta nitido.
    property real dpr: 1

    // Misura da chiedere a Lyrion per una copertina larga `pts` punti.
    // A scaglioni di 300 px: le immagini restano poche e la cache del server
    // (che le ridimensiona al volo) continua a servire.
    function coverPx(pts) {
        return Math.min(1200, Math.max(300, Math.ceil(pts * dpr / 300) * 300))
    }
}
