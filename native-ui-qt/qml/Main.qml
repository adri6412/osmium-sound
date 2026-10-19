// La radice: scala la tela logica (1024x600, adattata alla forma dello schermo) sul modo video reale ("contain",
// come ScaledCanvas.jsx) e impila le schermate e gli strati sovrapposti nello
// stesso ordine del ciclo di app.c.
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    // fattore di scala e scarti, letti anche dal canale di collaudo (main.cpp)
    // La scala e' arrotondata in modo che la tela sia larga un numero INTERO di
    // pixel (a 720p: 1229 invece di 1228,8). Cosi' gli strati cotti in texture
    // alla risoluzione dello schermo (Now Playing con i VU, maschere) combaciano
    // con la griglia dei pixel invece di essere ricampionati con uno scarto
    // frazionario che sfoca tutto di un filo. In altezza lo scarto e' < 1 px
    // sull'ultima riga, invisibile.
    // The canvas takes the screen's shape between 3:2 and 16:9: 600 points
    // tall and wider on a 16:9 panel (1067 x 600), 1024 wide and taller on a
    // 16:10 one (1024 x 640). Outside that range (ultrawide, 4:3) it stops at
    // the nearest end and the rest is black bars, as before.
    // (Ultrawide test: the upper end is 6:1, so 21:9, 32:9 and bar panels all
    // fill the screen; Theme.wide / Theme.ultra switch the arrangement.)
    // Settings -> Display -> Rotation (Sys.rotation, degrees clockwise). eglfs
    // draws straight on the panel and has no way to turn a Qt Quick scene, so
    // the canvas is turned here: it sits in a frame the size of the screen,
    // with width and height swapped for a quarter turn, rotated about its
    // centre. Touches follow by themselves (Qt Quick maps every event through
    // the rotation); whatever measures on screen must measure against the
    // canvas, not the window (Nav.qml).
    // ...less what the hardware already turns since this boot: upside down
    // the kernel turns the display plane itself (and udev the touch screen),
    // so the canvas only turns by what is left — nothing, or the difference
    // after a change made since the boot (Sys.hwRotation).
    readonly property int turn: (Sys.rotation - Sys.hwRotation + 360) % 360
    readonly property bool sideways: turn === 90 || turn === 270
    readonly property real fw: sideways ? height : width
    readonly property real fh: sideways ? width : height
    // TEST ONLY (remove before any release): /etc/hifi-player/ui-test-aspect = e.g. 2.4 pretends the
    // screen has that shape, to look at the ultrawide arrangements on a 16:9 monitor (bars top and bottom).
    readonly property real testAspect: parseFloat(Sys.conf("ui-test-aspect", "0")) || 0
    readonly property real aspect: testAspect > 0 ? testAspect : fh > 0 ? fw / fh : 1024 / 600
    readonly property real fitAspect: Math.max(1.5, Math.min(6, aspect))
    // Bar panels (3:1 and wider, 600 px tall or less): a 600-point canvas would be
    // scaled down to about 0.7 and everything would turn tiny, so they get a 440-point one.
    // TEST-ONLY: /etc/hifi-player/ui-test-bar = 1 forces it (remove before any release)
    readonly property bool shortBar: Sys.conf("ui-test-bar", "0") === "1" || (aspect >= 3 && fh <= 600)
    readonly property int baseH: shortBar ? 440 : 600
    Binding { target: Theme; property: "canvasW"; value: root.fitAspect >= 1024 / 600 ? Math.round(root.baseH * root.fitAspect) : 1024 }
    Binding { target: Theme; property: "canvasH"; value: root.fitAspect >= 1024 / 600 ? root.baseH : Math.round(1024 / root.fitAspect) }
    readonly property real s: Math.round(Math.min(fw / Theme.canvasW, fh / Theme.canvasH) * Theme.canvasW) / Theme.canvasW
    readonly property real ox: Math.floor((fw - Theme.canvasW * s) / 2)
    readonly property real oy: Math.floor((fh - Theme.canvasH * s) / 2)
    property alias app: canvas

    // La scala vera dello schermo, a disposizione di chiunque disegni su una
    // texture (Icon, Cover, le maschere) e di chi chiede le copertine.
    Binding { target: Theme; property: "dpr"; value: root.s }

    // How much the interface is allowed to move (Settings -> Interface motion).
    // Read once here because Theme only imports QtQuick; Settings writes it
    // back when the owner changes it.
    Component.onCompleted: Theme.motionLevel = Sys.conf("ui-motion", "full")
    // 320 = il lato della copertina in Now Playing, la piu' grande che chiediamo
    Binding { target: Player; property: "coverPx"; value: Theme.coverPx(320) }
    // a 4K un fotogramma costa quattro volte quanto a 1080p e la scena si
    // ridisegna tutta anche solo per gli aghi: la' si va a 20 al secondo
    Binding { target: Vu; property: "hz"; value: root.s >= 2.5 ? 20 : 30 }

    // Niente rettangolo di sfondo: la finestra si pulisce gia' con lo stesso
    // colore (view.setColor in main.cpp). Dipingerlo di nuovo era un riempimento
    // dello schermo intero buttato via a ogni fotogramma — a 4K sono 8 milioni
    // di pixel per 20-30 volte al secondo.

    Item {
        id: frame
        width: root.fw; height: root.fh
        anchors.centerIn: parent
        rotation: root.turn
        App {
            id: canvas
            x: root.ox; y: root.oy
            width: Theme.canvasW; height: Theme.canvasH
            scale: root.s
            transformOrigin: Item.TopLeft
            devicePixelScale: root.s
        }
    }
}
