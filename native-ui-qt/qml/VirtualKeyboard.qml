// La tastiera a schermo (VirtualKeyboard.jsx / vkbd.c): pannello largo 768
// che sale dal basso con la molla 320/24, stessa disposizione dei tasti di
// simple-keyboard, anteprima con cursore lampeggiante, Cancella e Conferma.
// Ogni tasto propaga subito il testo al campo (onChange), come in Electron.
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    property bool active: false
    property bool closing: false
    property bool shift: false
    property bool sym: false          // strato dei simboli
    property bool password: false
    property string text: ""
    property string label: ""
    property var field: null            // TextField_ collegato, se c'e'
    property var cb: null               // cb(confirmed, text)
    visible: active
    anchors.fill: parent

    Spring { id: slide; stiffness: 320; damping: 24 }      // 0 fuori, 1 a posto
    property real fade: 0
    Behavior on fade { NumberAnimation { duration: 200; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }

    function openText(lbl, initial, pw, f) {
        label = lbl || Tr.t("keyboard.enterText")
        text = initial || ""; password = !!pw; cb = f; field = null
        shift = false; sym = false; closing = false; active = true
        slide.set(0); slide.to = 1; fade = 1
        caretOn = true
    }
    function open(fld) {
        openText(fld.placeholder, fld.text, fld.password, null)
        field = fld
    }
    function close(confirmed) {
        if (!active || closing) return
        closing = true; closedOk = confirmed
        slide.to = 0; fade = 0
    }
    property bool closedOk: false
    Timer {
        interval: 30; repeat: true; running: root.closing
        onTriggered: if (!slide.running && slide.value === 0) {
            root.active = false; root.closing = false
            var f = root.cb, t = root.text, ok = root.closedOk
            root.cb = null
            if (f) f(ok, t)
        }
    }
    function notify() { if (field) { field.text = text; field.textEdited(text) } if (cb && !field) cb(false, text) }
    function put(s) { text += s; notify() }
    function backspace() { text = text.slice(0, -1); notify() }
    property bool caretOn: true
    Timer { interval: 500; repeat: true; running: root.active; onTriggered: root.caretOn = !root.caretOn }

    // testo dalla tastiera fisica collegata a caldo
    Keys.onPressed: (e) => {
        if (e.key === Qt.Key_Escape) { close(false); e.accepted = true; return }
        if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { close(true); e.accepted = true; return }
        if (e.key === Qt.Key_Backspace) { backspace(); e.accepted = true; return }
        if (e.text && e.text.length && e.text.charCodeAt(0) >= 32) { put(e.text); e.accepted = true }
    }
    onActiveChanged: if (active) forceActiveFocus()

    MouseArea { anchors.fill: parent; onClicked: root.close(false) }

    // 🚨 Due strati: lettere e simboli. Senza il secondo mancavano i due punti,
    // la barra e la chiocciola — cioe' tutto quello che serve per scrivere un
    // indirizzo, un percorso di rete o una porta, e quei campi si compilano
    // proprio da qui. Il tasto in basso a sinistra passa dall'uno all'altro.
    readonly property var letterRows: [
        [{k:"1"},{k:"2"},{k:"3"},{k:"4"},{k:"5"},{k:"6"},{k:"7"},{k:"8"},{k:"9"},{k:"0"}],
        [{k:"q"},{k:"w"},{k:"e"},{k:"r"},{k:"t"},{k:"y"},{k:"u"},{k:"i"},{k:"o"},{k:"p"}],
        [{k:"a"},{k:"s"},{k:"d"},{k:"f"},{k:"g"},{k:"h"},{k:"j"},{k:"k"},{k:"l"}],
        [{k:"⇧",fn:"shift",flex:1.5},{k:"z"},{k:"x"},{k:"c"},{k:"v"},{k:"b"},{k:"n"},{k:"m"},{k:"."},{k:"-"},{k:"⌫",fn:"bksp",flex:2.5}],
        [{k:"?#:",fn:"sym",flex:2},{k:"space",fn:"space",flex:8}]]
    readonly property var symRows: [
        [{k:"1"},{k:"2"},{k:"3"},{k:"4"},{k:"5"},{k:"6"},{k:"7"},{k:"8"},{k:"9"},{k:"0"}],
        [{k:"@"},{k:"#"},{k:"€"},{k:"$"},{k:"%"},{k:"&"},{k:"*"},{k:"("},{k:")"},{k:"~"}],
        [{k:"-"},{k:"_"},{k:"="},{k:"+"},{k:"/"},{k:"\\"},{k:"|"},{k:":"},{k:";"}],
        [{k:"'"},{k:"\""},{k:","},{k:"."},{k:"!"},{k:"?"},{k:"<"},{k:">"},{k:"["},{k:"]"},{k:"⌫",fn:"bksp",flex:2.5}],
        [{k:"ABC",fn:"sym",flex:2},{k:"space",fn:"space",flex:8}]]
    readonly property var rows: sym ? symRows : letterRows

    Rectangle {
        id: sheet
        readonly property real sheetH: 16 + 60 + 12 + (8 + 5 * 40 + 4 * 8 + 8) + 12 + 42 + 16
        width: Math.min(768, parent.width); height: sheetH + 16
        x: (parent.width - width) / 2
        y: parent.height - sheetH + (1 - slide.value) * sheetH
        radius: 16; color: Theme.dark
        opacity: root.fade                                 // la dissolvenza c'era ma non era legata a niente
        BoxShadow { z: -1; targetX: 0; targetY: 0; targetW: parent.width; targetH: parent.height; radius: 16; blur: 50; spread: -12; offsetY: 25; color: Theme.blackA(0.25) }   // shadow-2xl
        // border-t su rounded-t-2xl: la riga non esce dagli angoli
        Rectangle { x: 16; width: parent.width - 32; height: 1; color: Theme.accent }
        MouseArea { anchors.fill: parent }

        Text { x: 16; y: 16; height: 16; verticalAlignment: Text.AlignVCenter; text: root.label; color: Theme.silver; font.family: Theme.font; font.pixelSize: 12 }
        Rectangle {                                      // anteprima
            x: 16; y: 32; width: parent.width - 32 - 36 - 12; height: 44; radius: 8
            color: Theme.blackA(0.4); border.width: 1; border.color: Theme.accent
            Text {
                id: preview
                x: 12; width: parent.width - 24; anchors.verticalCenter: parent.verticalCenter
                text: root.text ? (root.password ? "*".repeat(Math.min(60, root.text.length)) : root.text) : "…"
                color: root.text ? Theme.white : Theme.silverA(0.4); font.family: Theme.mono; font.pixelSize: 18
                elide: Text.ElideLeft
            }
            Text { x: 12 + (root.text ? Math.min(preview.width, preview.implicitWidth) : 0) + 2; anchors.verticalCenter: parent.verticalCenter; visible: root.caretOn; text: "|"; color: Theme.gold; font.family: Theme.mono; font.pixelSize: 18 }
        }
        Rectangle {                                      // X
            x: parent.width - 16 - 36; y: 32; width: 36; height: 36; radius: 8; color: xTap.mix(Theme.light, Theme.accent)
            scale: xTap.tapScale                            // whileTap 0.95
            Icon { anchors.centerIn: parent; name: "x"; size: 20; color: Theme.white }
            Tap { id: xTap; tap: 0.95; onClicked: root.close(false) }
        }
        // il riquadro #1a1a1a (r8, padding 8) del contenitore .simple-keyboard
        Rectangle { x: 16; y: keys.y - 8; width: sheet.width - 32; height: keys.height + 16; radius: 8; color: Theme.gray }
        // tasti
        Column {
            id: keys
            x: 24; y: 32 + 44 + 12 + 8; width: sheet.width - 48; spacing: 8
            Repeater {
                model: root.rows
                Row {
                    id: krow
                    required property var modelData
                    readonly property real tot: modelData.reduce(function(a, k) { return a + (k.flex || 1) }, 0)
                    readonly property real avail: keys.width - (modelData.length - 1) * 8
                    spacing: 8
                    Repeater {
                        model: krow.modelData
                        Rectangle {
                            required property var modelData
                            readonly property bool fn: !!modelData.fn
                            width: krow.modelData.length === 1 ? keys.width : Math.round(krow.avail * (modelData.flex || 1) / krow.tot)
                            height: 40; radius: 6
                            // tasti normali #2a2a2a -> #4a4a4a da premuti; i tasti funzione restano #4a4a4a;
                            // lo shift attivo e' oro con testo nero (.hg-button.shift-active)
                            readonly property bool shiftOn: modelData.fn === "shift" && root.shift
                            color: shiftOn ? Theme.gold : fn ? "#4a4a4a" : kTap.mix(Theme.light, "#4a4a4a")
                            border.width: 1; border.color: shiftOn ? Theme.gold : Theme.accent
                            scale: kTap.tapScale
                            Text { anchors.centerIn: parent; text: modelData.fn === "space" ? Tr.t("keyboard.space") : (root.shift && !root.sym ? modelData.k.toUpperCase() : modelData.k); color: shiftOn ? Theme.black : Theme.white; font.family: Theme.font; font.pixelSize: 15; font.bold: true }
                            Tap {
                                id: kTap; tap: 0.95
                                onClicked: {
                                    if (modelData.fn === "shift") root.shift = !root.shift
                                    else if (modelData.fn === "sym") root.sym = !root.sym
                                    else if (modelData.fn === "bksp") root.backspace()
                                    else if (modelData.fn === "space") root.put(" ")
                                    else root.put(root.shift && !root.sym ? modelData.k.toUpperCase() : modelData.k)   // lo shift resta finche' non lo si ritocca, come in Electron
                                }
                            }
                        }
                    }
                }
            }
        }
        // Cancella + Conferma
        Rectangle {
            id: clearBtn
            x: 16; y: keys.y + keys.height + 8 + 12; height: 42; radius: 8
            width: 16 + 16 + 8 + clearText.implicitWidth + 8
            color: clTap.mix(Theme.light, Theme.accent)
            scale: clTap.tapScale                           // whileTap 0.95
            Icon { x: 8; anchors.verticalCenter: parent.verticalCenter; name: "x"; size: 16; color: Theme.white }
            Text { id: clearText; x: 28; anchors.verticalCenter: parent.verticalCenter; text: Tr.t("keyboard.clear"); color: Theme.white; font.family: Theme.font; font.pixelSize: 14; font.bold: true }
            Tap { id: clTap; tap: 0.95; onClicked: { root.text = ""; root.notify() } }
        }
        Rectangle {
            x: clearBtn.x + clearBtn.width + 8; y: clearBtn.y; width: parent.width - 16 - x; height: 42; radius: 8
            color: okTap.mix(Theme.gold, "#ca8a04")
            scale: okTap.tapScale                           // whileTap 0.95
            Text { anchors.centerIn: parent; text: Tr.t("keyboard.confirm"); color: Theme.black; font.family: Theme.font; font.pixelSize: 14; font.bold: true }
            Tap { id: okTap; tap: 0.95; onClicked: root.close(true) }
        }
    }
}
