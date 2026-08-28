// La radice: scala la tela logica 1024x600 sul modo video reale ("contain",
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
    readonly property real s: Math.round(Math.min(width / Theme.canvasW, height / Theme.canvasH) * Theme.canvasW) / Theme.canvasW
    readonly property real ox: Math.floor((width - Theme.canvasW * s) / 2)
    readonly property real oy: Math.floor((height - Theme.canvasH * s) / 2)
    property alias app: canvas

    // La scala vera dello schermo, a disposizione di chiunque disegni su una
    // texture (Icon, Cover, le maschere) e di chi chiede le copertine.
    Binding { target: Theme; property: "dpr"; value: root.s }
    // 320 = il lato della copertina in Now Playing, la piu' grande che chiediamo
    Binding { target: Player; property: "coverPx"; value: Theme.coverPx(320) }
    // a 4K un fotogramma costa quattro volte quanto a 1080p e la scena si
    // ridisegna tutta anche solo per gli aghi: la' si va a 20 al secondo
    Binding { target: Vu; property: "hz"; value: root.s >= 2.5 ? 20 : 30 }

    // Niente rettangolo di sfondo: la finestra si pulisce gia' con lo stesso
    // colore (view.setColor in main.cpp). Dipingerlo di nuovo era un riempimento
    // dello schermo intero buttato via a ogni fotogramma — a 4K sono 8 milioni
    // di pixel per 20-30 volte al secondo.

    App {
        id: canvas
        x: root.ox; y: root.oy
        width: Theme.canvasW; height: Theme.canvasH
        scale: root.s
        transformOrigin: Item.TopLeft
        devicePixelScale: root.s
    }
}
