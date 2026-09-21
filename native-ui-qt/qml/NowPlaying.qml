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
    // the VU needles come from this device's own DAC: meaningless while
    // driving another player (#99)
    readonly property bool effVu: viewVu && Player.vuEnabled && Player.isOwn
    // with the VU meters off, a CD / vinyl / cassette may take their place
    // (Settings → Animations); it is not tied to our own DAC, so no isOwn
    readonly property bool animChosen: Player.npAnimation !== "" && Player.npAnimation !== "none"   // built in or from the store
    readonly property bool effAnim: viewVu && !Player.vuEnabled && animChosen
    property bool shown: false                         // a video (VU attivi solo qui)
    // Full screen (NpStage), from the button next to the clock: the meters
    // when they are on, else the chosen animation; nothing when neither.
    readonly property string stageMode: Player.vuEnabled ? (Player.isOwn ? "vu" : "") : (animChosen ? "anim" : "")
    property bool stageOpen: false
    readonly property bool staged: stageOpen && stageMode !== ""
    signal collapse()
    signal openQueue()
    signal openSleep()
    signal openPlayerPicker()
    signal startScreensaver()
    signal toggleView()
    signal openPlaybackSetting(string which)
    signal openSettings()

    readonly property real pad: 20
    readonly property real leftW: (root.width - pad * 2) * 0.44
    readonly property real bodyY: 52
    readonly property real bodyH: root.height - bodyY - pad
    readonly property real artSide: Math.min(leftW, 320)
    readonly property real ledW: Math.min(leftW, 368)
    readonly property real ledH: ledW * 175 / 897
    readonly property real artY: bodyY + (bodyH - (artSide + 32 + ledH)) / 2
    readonly property real rx: pad + leftW + 24
    readonly property real rw: root.width - rx - pad

    // ─── dal telecomando ───────────────────────────────────────────────────
    // Lo stesso che fanno i pulsanti dell'intestazione, per i tasti che
    // l'utente puo' assegnare (Impostazioni -> Telecomando). Schermo intero
    // con niente da mostrare non fa nulla e lo dice a chi ha chiamato.
    function toggleStage() {
        if (stageOpen) { stageOpen = false; return true }
        if (stageMode === "") return false
        stageOpen = true
        return true
    }
    // il prossimo skin dei VU / la prossima animazione, senza aprire la scelta
    function cycleLook(kind) { chooser.cycle(kind) }

    // Con i VU in movimento la scena si ridisegna ~30 volte al secondo: tutto
    // cio' che non si muove sta in uno strato cotto una volta (layer), cosi'
    // il fotogramma e' una sola quad piu' gli aghi — misurato sul Dell:
    // 4,9 W senza, contro i 2,4 W della UI in C che ridipinge solo gli aghi.
    Item {
        id: staticLayer
        anchors.fill: parent
        visible: !root.staged
        layer.enabled: root.shown && !root.staged && (root.effVu || root.effAnim)
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
        // 🚨 doppia immagine come nella copertina: le radio cambiano l'indirizzo
        // ogni dieci secondi e, con una sola, mentre la nuova arriva il fondale
        // spariva — il lampeggio periodico dell'intera schermata.
        Image {
            id: bgPrev
            asynchronous: false; visible: false
            sourceSize.width: 400; sourceSize.height: 400
            width: 400; height: 400
            fillMode: Image.PreserveAspectCrop
            layer.enabled: true
            layer.textureSize: Qt.size(400, 400)
        }
        Image {
            id: bgSrc
            source: Player.artworkUrl
            asynchronous: true; visible: false
            sourceSize.width: 400; sourceSize.height: 400
            width: 400; height: 400
            fillMode: Image.PreserveAspectCrop
            layer.enabled: true
            layer.textureSize: Qt.size(400, 400)
            onStatusChanged: if (status === Image.Ready) bgPrev.source = source
        }
        MultiEffect {
            source: bgSrc.status === Image.Ready ? bgSrc : bgPrev
            visible: bgSrc.status === Image.Ready || bgPrev.status === Image.Ready
            width: 400; height: 400
            x: root.width / 2 - 640; y: root.height / 2 - 640
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
    // full screen (big meters or the animation), right next to the button
    // that puts the player back into its bar: the two do opposite things
    RoundButton {
        x: root.pad + 46; y: 12; width: 38; height: 38
        visible: root.stageMode !== ""
        icon: "maximize-2"; iconSize: 20
        onClicked: root.stageOpen = true
    }

    // The clock and the two choosers — which VU meter look, which animation —
    // are one block, centred on the cover underneath (the cover and the LED
    // plate sit on the same axis). The lit one says what plays on screen.
    Row {
        x: root.pad + (root.leftW - width) / 2
        y: 31 - 18
        spacing: 10
        Rectangle {                               // l'orologio: tocco = salvaschermo
            id: clockPill
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
        Row {
            spacing: 8
            RoundButton {                         // the meters' looks (our own DAC only, like the meters)
                width: 36; height: 36
                visible: Player.isOwn
                icon: "vu-meter"; iconSize: 18
                bg: Player.vuEnabled ? Theme.goldA(0.3) : Theme.wa(0.10)
                bgPress: Player.vuEnabled ? Theme.goldA(0.3) : Theme.wa(0.20)
                fg: Player.vuEnabled ? Theme.gold : Theme.white
                onClicked: chooser.open("vu")
            }
            RoundButton {                         // the animations
                width: 36; height: 36
                icon: "disc-3"; iconSize: 18
                bg: !Player.vuEnabled && root.animChosen ? Theme.goldA(0.3) : Theme.wa(0.10)
                bgPress: !Player.vuEnabled && root.animChosen ? Theme.goldA(0.3) : Theme.wa(0.20)
                fg: !Player.vuEnabled && root.animChosen ? Theme.gold : Theme.white
                onClicked: chooser.open("anim")
            }
        }
    }
    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        y: 31 - height / 2
        text: Player.isOwn ? Tr.up("player.nowPlaying") : Tr.tf("player.controlling", "name", Player.playerName).toUpperCase()
        color: Player.isOwn ? Theme.silverA(0.7) : Theme.gold; font.family: Theme.font; font.pixelSize: 10; font.letterSpacing: 2.5
    }
    RoundButton {                                 // player da pilotare (#99)
        x: root.width - root.pad - 34 * 5 - 32; y: 14; width: 34; height: 34; icon: "speaker"; iconSize: 18
        bg: Player.isOwn ? Theme.wa(0.10) : Theme.goldA(0.3)
        bgPress: Player.isOwn ? Theme.wa(0.20) : Theme.goldA(0.3)
        fg: Player.isOwn ? Theme.white : Theme.gold
        onClicked: root.openPlayerPicker()
    }
    RoundButton {                                 // VU or animation <-> lyrics (hidden when neither is available)
        x: root.width - root.pad - 34 * 4 - 24; y: 14; width: 34; height: 34
        visible: (Player.vuEnabled && Player.isOwn) || (!Player.vuEnabled && root.animChosen)
        icon: root.viewVu ? "mic-2" : (Player.vuEnabled ? "vu-meter" : "disc-3"); iconSize: 18
        onClicked: root.toggleView()
    }
    RoundButton { x: root.width - root.pad - 34 * 3 - 16; y: 14; width: 34; height: 34; icon: "list-music"; iconSize: 18; onClicked: root.openQueue() }
    RoundButton {
        x: root.width - root.pad - 34 * 2 - 8; y: 14; width: 34; height: 34; icon: "moon"; iconSize: 18
        bg: Player.sleepSecs > 0 ? Theme.goldA(0.3) : Theme.wa(0.10)
        bgPress: Player.sleepSecs > 0 ? Theme.goldA(0.3) : Theme.wa(0.20)
        fg: Player.sleepSecs > 0 ? Theme.gold : Theme.white
        onClicked: root.openSleep()
    }
    // straight to Settings
    RoundButton { x: root.width - root.pad - 34; y: 14; width: 34; height: 34; icon: "settings"; iconSize: 18; onClicked: root.openSettings() }

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
        // BitPerfect / ReplayGain follow the player being driven, like the
        // format LEDs and the volume slider: the prefs behind ledMode are
        // polled on the selected player, not on our own (#101)
        mode: Player.ledMode
        onOpenSetting: (which) => root.openPlaybackSetting(which)
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
            text: Player.artist || (Player.stationName !== "" ? "" : Tr.t("player.unknownArtist"))   // a radio with no song yet: nothing
            color: npArtistTap.mix(Theme.gold, Theme.white); font.family: Theme.font; font.pixelSize: 18; elide: Text.ElideRight
            // the artist's page (library tracks only)
            Tap { id: npArtistTap; width: Math.min(parent.width, parent.implicitWidth); anchors.fill: undefined; height: parent.height
                  enabled: Player.artistId !== ""; onClicked: Ui.app.openArtist(Player.artistId, Player.artist) }
        }
        Text {
            width: parent.width; height: 20; verticalAlignment: Text.AlignVCenter
            text: Player.album
            color: npAlbumTap.mix(Theme.silverA(0.7), Theme.white); font.family: Theme.font; font.pixelSize: 14; elide: Text.ElideRight
            Tap { id: npAlbumTap; width: Math.min(parent.width, parent.implicitWidth); anchors.fill: undefined; height: parent.height
                  enabled: Player.albumId !== ""; onClicked: Ui.app.openAlbum(Player.albumId, Player.album) }
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
            // 🚨 i cinque comandi erano attaccati (centri a 9/42/94/146/179 punti,
            // come in Electron): su un touchscreen si toccava il vicino. Ora c'e'
            // un passo di respiro in piu' fra uno e l'altro.
            readonly property real g: 12
            Item {                                 // shuffle
                x: 9 - 20; y: controls.cy - 20; width: 40; height: 40
                Icon { anchors.centerIn: parent; name: "shuffle"; size: 18; scale: shTap.tapScale
                       color: Player.shuffle > 0 ? Theme.gold : shTap.mix(Theme.silverA(0.6), Theme.white) }
                Tap { id: shTap; tap: 0.88; onClicked: Player.cycleShuffle() }
            }
            Item {                                 // precedente (whileTap .9)
                x: 30 + 12 - 22 + controls.g; y: controls.cy - 22; width: 44; height: 44
                Icon { anchors.centerIn: parent; name: "skip-back"; size: 24; color: Theme.silver; scale: prevTap.tapScale }
                Tap { id: prevTap; tap: 0.9; onClicked: Player.prev() }
            }
            Item {                                 // play, con alone 0 0 24px oro/40
                id: playBtn
                x: 66 + 2 * controls.g; y: controls.cy - 28; width: 56; height: 56
                Glow { anchors.centerIn: parent; radius: 28; blur: 24; color: Theme.goldA(0.4) }
                Rectangle { anchors.fill: parent; radius: 28; color: Theme.gold; scale: playTap.tapScale }
                // Due icone che si scambiano in dissolvenza: cambiare `name` di
                // colpo era uno scatto, e lo scarto ottico del triangolo
                // saltava con lui. A riposo quella di sotto e' `visible: false`.
                property real pf: Player.playing ? 1 : 0
                Behavior on pf { NumberAnimation { duration: Theme.dur(110); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
                Icon {
                    anchors.centerIn: parent; anchors.horizontalCenterOffset: 4
                    name: "play"; filled: true; size: 26; color: Theme.black
                    opacity: 1 - playBtn.pf; visible: opacity > 0.01; scale: playTap.tapScale
                }
                Icon {
                    anchors.centerIn: parent
                    name: "pause"; filled: true; size: 26; color: Theme.black
                    opacity: playBtn.pf; visible: opacity > 0.01; scale: playTap.tapScale
                }
                Tap { id: playTap; tap: 0.95; grow: 4; onClicked: Player.togglePlay() }
            }
            Item {                                 // successivo
                x: 134 + 12 - 22 + 3 * controls.g; y: controls.cy - 22; width: 44; height: 44
                Icon { anchors.centerIn: parent; name: "skip-forward"; size: 24; color: Theme.silver; scale: nextTap.tapScale }
                Tap { id: nextTap; tap: 0.9; onClicked: Player.next() }
            }
            Item {                                 // ripeti
                x: 170 + 9 - 20 + 4 * controls.g; y: controls.cy - 20; width: 40; height: 40
                Icon { anchors.centerIn: parent; name: Player.repeat === 1 ? "repeat-1" : "repeat"; size: 18; scale: rpTap.tapScale
                       color: Player.repeat > 0 ? Theme.gold : rpTap.mix(Theme.silverA(0.6), Theme.white) }
                Tap { id: rpTap; tap: 0.88; onClicked: Player.cycleRepeat() }
            }
            Item {                                 // preferito (Lyrion Favorites): cuore pieno e oro se il brano lo e'
                id: favBox
                x: 170 + 9 - 20 + 4 * controls.g + 45; y: controls.cy - 20; width: 40; height: 40   // same pitch as next -> repeat
                visible: Player.favoritesAvailable && Player.trackUrl !== ""
                // lo scoppio quando si AGGIUNGE: 0 -> 1 -> 0 in poco piu' di
                // un quarto di secondo, e finisce li'
                property real pop: 0
                SequentialAnimation {
                    id: favBurst
                    NumberAnimation { target: favBox; property: "pop"; from: 0; to: 1; duration: Theme.dur(90);  easing.type: Easing.OutQuad }
                    NumberAnimation { target: favBox; property: "pop"; to: 0;         duration: Theme.dur(220); easing.type: Easing.OutCubic }
                }
                Icon { anchors.centerIn: parent; name: "heart"; filled: Player.isFavorite; size: 18
                       scale: favTap.tapScale * (1 + 0.3 * favBox.pop)
                       color: Player.isFavorite ? Theme.gold : favTap.mix(Theme.silverA(0.6), Theme.white) }
                Tap {
                    id: favTap; tap: 0.9
                    onClicked: {
                        var was = Player.isFavorite
                        Player.toggleFavorite()
                        // 🚨 Qui e non su onFavoriteChanged: quel segnale scatta
                        // anche cambiando brano, e il cuore scoppierebbe da solo.
                        // 🚨 E non mentre i VU o una scena girano: tutto questo
                        // sta nello strato cotto, e animarlo li' ricuoce una
                        // texture a schermo intero a ogni fotogramma.
                        if (!was && Theme.lushMotion && !root.effVu && !root.effAnim) favBurst.restart()
                        Ui.toast.say("heart", Tr.t(was ? "player.removedFromFavorites" : "player.addedToFavorites"))
                    }
                }
            }
            // volume, a destra: icona + barra 155 px
            Item {
                x: parent.width - 180 + 8.5 - 18; y: controls.cy - 18; width: 36; height: 36
                Icon { anchors.centerIn: parent; name: Player.muted || Player.volume === 0 ? "volume-x" : "volume-2"; size: 17; scale: muteTap.tapScale
                       color: Player.volumeFixed ? Theme.silverA(0.21) : muteTap.mix(Theme.silverA(0.7), Theme.white) }
                Tap { id: muteTap; tap: 0.88; grow: 4; onClicked: Player.toggleMute() }
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
        x: root.rx; y: col.y + col.height; width: root.rw; height: root.height - root.pad - y
        visible: !root.effVu && !root.effAnim; active: root.shown && !root.effVu && !root.effAnim
    }
    }   // fine dello strato statico

    // ─── VU: fuori dallo strato, sono l'unica cosa che si muove ────────────
    VuPanel {
        x: root.rx; y: col.y + col.height; width: root.rw; height: root.height - root.pad - y
        visible: root.effVu && !root.staged; devScale: root.devScale
    }
    // the animation in the same box, also outside the layer. Loaded while the
    // VU meters are off and one is chosen (so switching to the lyrics and back
    // does not reload the pictures); it runs only while visible on screen.
    NpAnimation {
        x: root.rx; y: col.y + col.height; width: root.rw; height: root.height - root.pad - y
        // unloaded while the full-screen stage runs its own copy
        kind: Player.vuEnabled || root.staged ? "" : Player.npAnimation
        visible: root.effAnim && !root.staged
        active: root.shown && root.effAnim && !root.staged
        devScale: root.devScale
    }

    NpStage {
        anchors.fill: parent
        mode: root.staged ? root.stageMode : ""
        shown: root.shown && root.staged
        devScale: root.devScale
        onClose: root.stageOpen = false
    }
    // the popup of the two chooser buttons (VU meter looks / animations)
    NpChooser {
        id: chooser
        anchors.fill: parent
        devScale: root.devScale
        z: 10
    }
    onShownChanged: if (!shown) chooser.close()

    // the meters run for the VU panels, and for the cassette deck's level
    // meters, here or at full screen (only our own DAC has levels)
    Binding { target: Vu; property: "active"; value: root.shown && Player.isOwn && (root.effVu || (root.staged && root.stageMode === "vu")
                                                     || ((root.effAnim || root.staged) && Player.npAnimation === "cassette")) }
}
