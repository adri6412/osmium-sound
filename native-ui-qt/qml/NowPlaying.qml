// Il Now Playing a schermo intero (player espanso di LyrionServer.jsx), con le
// misure di screen_np.c: intestazione px-5 pt-3, colonna copertina 44 %,
// copertina 320 con ombra, targa LED, a destra info / avanzamento / comandi
// e il pannello VU oppure i testi.
import QtQuick
import QtQuick.Effects
import Hifi.Ui

Item {
    id: root
    property real devScale: 1
    property bool viewVu: true                         // scelta dell'utente
    readonly property bool effVu: viewVu && Player.vuEnabled
    property bool shown: false                         // a video (VU attivi solo qui)
    signal collapse()
    signal openQueue()
    signal openSleep()
    signal startScreensaver()
    signal toggleView()

    readonly property real pad: 20
    readonly property real leftW: (1024 - pad * 2) * 0.44
    readonly property real bodyY: 52
    readonly property real bodyH: 600 - bodyY - pad
    readonly property real artSide: Math.min(leftW, 320)
    readonly property real ledW: Math.min(leftW, 368)
    readonly property real ledH: ledW * 175 / 897
    readonly property real artY: bodyY + (bodyH - (artSide + 32 + ledH)) / 2
    readonly property real rx: pad + leftW + 24
    readonly property real rw: 1024 - rx - pad

    // Con i VU in movimento la scena si ridisegna ~30 volte al secondo: tutto
    // cio' che non si muove sta in uno strato cotto una volta (layer), cosi'
    // il fotogramma e' una sola quad piu' gli aghi — misurato sul Dell:
    // 4,9 W senza, contro i 2,4 W della UI in C che ridipinge solo gli aghi.
    Item {
        id: staticLayer
        anchors.fill: parent
        layer.enabled: root.shown && root.effVu
        layer.textureSize: Qt.size(Math.round(width * root.devScale), Math.round(height * root.devScale))
        layer.smooth: true
        // Senza canale alpha: la schermata e' opaca (ha il suo fondo scuro), e
        // cosi' la scheda video la ricopia e basta invece di fonderla con quello
        // che c'e' sotto — un fotogramma in meno di lettura dello schermo intero.
        layer.format: ShaderEffectSource.RGB
    // ─── fondale: la copertina piccola e sfocata al 20 %, poi i gradienti ──
    Rectangle { anchors.fill: parent; color: Theme.dark }
    Item {
        anchors.fill: parent
        clip: true
        // Come Electron: bg-cover della copertina sulla tela (1024 quadrata,
        // centrata), scale-125 (1280) e blur-lg = 16 punti. La sfocatura e'
        // di 16 punti sullo schermo, non di piu': si devono intravedere le
        // forme della copertina, e' cio' che da' profondita' al fondale.
        // Si parte da 400 px (non 160: a 8x l'immagine era gia' impastata
        // dal solo ingrandimento, sfocatura reale ~130 punti, fondale piatto)
        // e 16 punti / (1280/400) = 5 px di sfocatura sulla sorgente.
        Image {
            id: bgSrc
            source: Player.artworkUrl
            asynchronous: true; visible: false
            sourceSize.width: 400; sourceSize.height: 400
            width: 400; height: 400
            fillMode: Image.PreserveAspectCrop
        }
        MultiEffect {
            source: bgSrc
            visible: bgSrc.status === Image.Ready
            width: 400; height: 400
            x: 512 - 640; y: 300 - 640
            scale: 3.2
            transformOrigin: Item.TopLeft
            // blur-lg (16) e' applicato PRIMA di scale-125: 20 punti effettivi a schermo
            blurEnabled: true; blur: 0.41; blurMax: 16
            opacity: 0.2
        }
    }
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, 0) }
            GradientStop { position: 0.5; color: Qt.rgba(0, 0, 0, 0.6) }
            GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.95) }
        }
    }

    // ─── intestazione ──────────────────────────────────────────────────────
    RoundButton { x: root.pad; y: 12; width: 38; height: 38; icon: "chevron-down"; iconSize: 22; onClicked: root.collapse() }

    Rectangle {                                   // l'orologio: tocco = salvaschermo
        id: clockPill
        x: root.pad + root.leftW / 2 - width / 2
        y: 31 - height / 2
        width: clockText.implicitWidth + 32; height: 36
        radius: 18
        color: clockTap.mix(Theme.wa(0.10), Theme.wa(0.25))
        Text {
            id: clockText
            anchors.centerIn: parent
            text: Qt.formatTime(new Date(), "HH:mm")
            color: Theme.white; font.family: Theme.font; font.pixelSize: 20; font.letterSpacing: 0.5; font.weight: Font.Medium
            Timer { interval: 5000; running: root.shown; repeat: true; triggeredOnStart: true; onTriggered: clockText.text = Qt.formatTime(new Date(), "HH:mm") }
        }
        Tap { id: clockTap; onClicked: root.startScreensaver() }
    }
    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        y: 31 - height / 2
        text: Tr.up("player.nowPlaying")
        color: Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 10; font.letterSpacing: 2.5
    }
    RoundButton {                                 // VU <-> testi (nascosto se i VU sono spenti)
        x: 1024 - root.pad - 34 * 3 - 16; y: 14; width: 34; height: 34
        visible: Player.vuEnabled
        icon: root.viewVu ? "mic-2" : "audio-lines"; iconSize: 18
        onClicked: root.toggleView()
    }
    RoundButton { x: 1024 - root.pad - 34 * 2 - 8; y: 14; width: 34; height: 34; icon: "list-music"; iconSize: 18; onClicked: root.openQueue() }
    RoundButton {
        x: 1024 - root.pad - 34; y: 14; width: 34; height: 34; icon: "moon"; iconSize: 18
        bg: Player.sleepSecs > 0 ? Theme.goldA(0.3) : Theme.wa(0.10)
        bgPress: Player.sleepSecs > 0 ? Theme.goldA(0.3) : Theme.wa(0.20)
        fg: Player.sleepSecs > 0 ? Theme.gold : Theme.white
        onClicked: root.openSleep()
    }

    // ─── copertina con ombra 0 20px 60px rgba(0,0,0,.7) e targa LED ────────
    Rectangle {
        id: artShadowSrc
        x: root.pad + (root.leftW - root.artSide) / 2; y: root.artY + 20
        width: root.artSide; height: root.artSide; radius: 16
        color: Qt.rgba(0, 0, 0, 0.7)
        visible: false
        layer.enabled: true
    }
    MultiEffect {
        source: artShadowSrc
        x: artShadowSrc.x; y: artShadowSrc.y; width: artShadowSrc.width; height: artShadowSrc.height
        blurEnabled: true; blur: 1.0; blurMax: 60
        autoPaddingEnabled: true
    }
    Cover {
        id: art
        x: root.pad + (root.leftW - root.artSide) / 2; y: root.artY
        width: root.artSide; height: root.artSide
        source: Player.artworkUrl
        radius: 16; devScale: root.devScale
        // Electron chiede `border-white/8`, che Tailwind 3.3 NON genera (la scala
        // va di 5 in 5): resta il colore di preflight, un filo grigio chiaro pieno.
        // E' cosi' che la si vede sull'apparecchio, quindi cosi' e' anche qui.
        border: "#e5e7eb"
    }
    LedBar {
        x: root.pad + (root.leftW - root.ledW) / 2; y: root.artY + root.artSide + 32
        width: root.ledW; devScale: root.devScale
    }

    // ─── colonna di destra ─────────────────────────────────────────────────
    Column {
        id: col
        x: root.rx; y: root.bodyY + 1
        width: root.rw
        Text {
            id: titleText
            width: parent.width
            text: Player.title || Tr.t("player.noTrack")
            color: Theme.white; font.family: Theme.font; font.pixelSize: 24; font.bold: true
            wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight
            lineHeight: 30; lineHeightMode: Text.FixedHeight
        }
        // 6 e non 2 (mt-0.5): misurato sull'apparecchio, a parita' di riga
        // da 30 Chromium appoggia il glifo 4 punti piu' in basso di Qt, e
        // tutto cio' che segue (artista, tempi, barra, comandi) stava 4-5
        // punti piu' in alto che in Electron.
        Item { width: 1; height: 6 }
        Text {
            width: parent.width; height: 28; verticalAlignment: Text.AlignVCenter
            text: Player.artist || Tr.t("player.unknownArtist")
            color: Theme.gold; font.family: Theme.font; font.pixelSize: 18; elide: Text.ElideRight
        }
        Text {
            width: parent.width; height: 20; verticalAlignment: Text.AlignVCenter
            text: Player.album
            color: Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 14; elide: Text.ElideRight
        }
        Item { width: 1; height: 6; visible: Player.chip !== "" }
        Rectangle {                                // etichetta del formato
            visible: Player.chip !== ""
            width: chipText.implicitWidth + 16; height: 22; radius: 4
            color: Theme.wa(0.05); border.width: 1; border.color: Theme.wa(0.05)
            Text {
                id: chipText; anchors.centerIn: parent
                text: Player.chip; color: Theme.silverA(0.5)
                font.family: Theme.font; font.pixelSize: 11; font.letterSpacing: 0.3
            }
        }
        Item { width: 1; height: 8 }
        Item {                                     // tempi
            width: parent.width; height: 16
            Text { anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; text: Player.formatTime(Player.elapsed); color: Theme.silverA(0.6); font.family: Theme.mono; font.pixelSize: 12 }
            Text { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; text: Player.formatTime(Player.duration); color: Theme.silverA(0.6); font.family: Theme.mono; font.pixelSize: 12 }
        }
        Item { width: 1; height: 6 }
        Item {                                     // barra di avanzamento
            id: barBox
            width: parent.width; height: 6
            Rectangle { anchors.fill: parent; radius: 3; color: Theme.wa(0.10) }
            // riempimento scalato con scaleX come in Electron: la rampa oro -> giallo si
            // comprime, il giallo sta sempre sul bordo destro del riempimento
            Rectangle {
                width: Player.duration > 0 ? parent.width * Math.max(0, Math.min(1, Player.elapsed / Player.duration)) : 0
                height: parent.height; radius: 3
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: Theme.gold }
                    GradientStop { position: 1; color: Theme.yellow400 }
                }
            }
            MouseArea {
                anchors.fill: parent; anchors.topMargin: -12; anchors.bottomMargin: -12
                onClicked: (m) => Player.seekFraction(m.x / width)
            }
        }
        Item { width: 1; height: 12 }
        Item {                                     // comandi
            id: controls
            width: parent.width; height: 56
            readonly property real cy: 28
            Item {                                 // shuffle
                x: 9 - 20; y: controls.cy - 20; width: 40; height: 40
                Icon { anchors.centerIn: parent; name: "shuffle"; size: 18
                       color: Player.shuffle > 0 ? Theme.gold : shTap.mix(Theme.silverA(0.6), Theme.white) }
                Tap { id: shTap; onClicked: Player.cycleShuffle() }
            }
            Item {                                 // precedente (whileTap .9)
                x: 30 + 12 - 22; y: controls.cy - 22; width: 44; height: 44
                Icon { anchors.centerIn: parent; name: "skip-back"; size: 24; color: Theme.silver; scale: prevTap.tapScale }
                Tap { id: prevTap; tap: 0.9; onClicked: Player.prev() }
            }
            Item {                                 // play, con alone 0 0 24px oro/40
                id: playBtn
                x: 66; y: controls.cy - 28; width: 56; height: 56
                Glow { anchors.centerIn: parent; radius: 28; blur: 24; color: Theme.goldA(0.4) }
                Rectangle { anchors.fill: parent; radius: 28; color: Theme.gold; scale: playTap.tapScale }
                Icon {
                    anchors.centerIn: parent
                    anchors.horizontalCenterOffset: Player.playing ? 0 : 4
                    name: Player.playing ? "pause" : "play"; filled: true; size: 26; color: Theme.black
                    scale: playTap.tapScale
                }
                Tap { id: playTap; tap: 0.95; grow: 4; onClicked: Player.togglePlay() }
            }
            Item {                                 // successivo
                x: 134 + 12 - 22; y: controls.cy - 22; width: 44; height: 44
                Icon { anchors.centerIn: parent; name: "skip-forward"; size: 24; color: Theme.silver; scale: nextTap.tapScale }
                Tap { id: nextTap; tap: 0.9; onClicked: Player.next() }
            }
            Item {                                 // ripeti
                x: 170 + 9 - 20; y: controls.cy - 20; width: 40; height: 40
                Icon { anchors.centerIn: parent; name: Player.repeat === 1 ? "repeat-1" : "repeat"; size: 18
                       color: Player.repeat > 0 ? Theme.gold : rpTap.mix(Theme.silverA(0.6), Theme.white) }
                Tap { id: rpTap; onClicked: Player.cycleRepeat() }
            }
            // volume, a destra: icona + barra 155 px
            Item {
                x: parent.width - 180 + 8.5 - 18; y: controls.cy - 18; width: 36; height: 36
                Icon { anchors.centerIn: parent; name: Player.volume === 0 ? "volume-x" : "volume-2"; size: 17
                       color: Player.volumeFixed ? Theme.silverA(0.21) : Theme.silverA(0.7) }
                Tap { onClicked: Player.toggleMute() }
            }
            Item {
                id: volBar
                x: parent.width - 180 + 25; y: controls.cy - 3; width: 155; height: 6
                readonly property real frac: Math.max(0, Math.min(100, Player.volume)) / 100
                // <input type=range> con appearance-none: traccia uniforme e pomello, NESSUNA parte riempita
                Rectangle { anchors.fill: parent; radius: 3; color: Player.volumeFixed ? Theme.wa(0.05) : Theme.wa(0.10) }
                Rectangle { x: parent.width * volBar.frac - 8; y: -5; width: 16; height: 16; radius: 8; color: Player.volumeFixed ? Theme.silverA(0.3) : Theme.gold }
                MouseArea {
                    anchors.fill: parent; anchors.margins: -14
                    enabled: !Player.volumeFixed
                    function vol(m) { return Math.round((m.x - 14) * 100 / volBar.width) }
                    onPressed: (m) => Player.setVolume(vol(m), false)
                    onPositionChanged: (m) => { if (pressed) Player.setVolume(vol(m), false) }
                    onReleased: (m) => Player.setVolume(vol(m), true)
                }
            }
        }
        Item { width: 1; height: 12 }
    }

    // ─── testi (nello strato: non si muovono da soli) ──────────────────────
    Lyrics {
        x: root.rx; y: col.y + col.height; width: root.rw; height: 600 - root.pad - y
        visible: !root.effVu; active: root.shown && !root.effVu
    }
    }   // fine dello strato statico

    // ─── VU: fuori dallo strato, sono l'unica cosa che si muove ────────────
    VuPanel {
        x: root.rx; y: col.y + col.height; width: root.rw; height: 600 - root.pad - y
        visible: root.effVu; devScale: root.devScale
    }

    Binding { target: Vu; property: "active"; value: root.shown && root.effVu }
}
