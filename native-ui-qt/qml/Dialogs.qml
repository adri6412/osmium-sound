// Finestre modali sopra tutta la schermata (dialog.c): conferma, scelta da
// elenco, testo lungo, pannello Wi-Fi, procedura di formattazione, accesso a
// una cartella di rete. Un solo
// meccanismo: fondo nero/70, scheda che entra con la molla 550/30 da 0,92 e
// dissolvenza 0,3 s; in uscita 0,2 s.
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    property int kind: 0            // 0 nessuno 1 conferma 2 scelta 3 testo 4 wifi 5 formattazione 6 accesso 7 spegnimento
    readonly property bool active: kind !== 0
    property bool closing: false
    visible: active
    // il telecomando resta qui dentro finche' questo strato e' aperto
    NavScope { active: root.active && !root.closing }
    anchors.fill: parent

    property string title: ""
    property string body: ""
    property string okLabel: ""
    property bool danger: false
    property var cb: null
    property var items: []
    property int current: -1
    // wifi
    property var networks: []       // [{ssid, security, signal, band}]
    property var dualSsids: ({})    // nome -> true quando la rete e' su piu' bande
    property string ssid: ""
    property string band: ""        // banda scelta da un nome doppio (2.4 / 5 / 6)
    property string pass: ""
    property string err: ""
    property int wifiSel: -1
    property bool editingPass: false
    // formattazione
    property int step: 0
    property string fdev: ""; property string fmodel: ""; property string fsize: ""; property string fconfirm: ""
    property string ffs: "ext4"; property string flabel: "Musica"; property string ftyped: ""; property string fmsg: ""
    property int fpct: 0
    // accesso (cartella di rete): nome utente e password
    property string luser: ""
    property string lpass: ""

    Spring { id: sc; stiffness: 550; damping: 30; rate: Theme.motionRate }
    property real fade: 0
    Behavior on fade { NumberAnimation { id: fadeAnim; duration: Theme.dur(300); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
    Behavior on closeScale { NumberAnimation { duration: Theme.dur(200); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
    property real closeScale: 1

    function openCommon(k) {
        kind = k; closing = false
        wifiSel = -1; editingPass = false; err = ""
        sc.set(0.92); sc.to = 1.0
        closeScale = 1
        fadeAnim.duration = Theme.dur(300); fade = 1
    }
    function confirm(text, ok, dang, f) { openCommon(1); body = text || ""; okLabel = ok || Tr.t("common.confirm"); danger = !!dang; cb = f }
    function pick(t, list, cur, f) {
        openCommon(2); title = t || ""; items = list || []; current = cur; cb = f
        // porta la voce corrente sotto gli occhi, come fa la select di Chromium
        // con 487 fusi orari in elenco
        Qt.callLater(function() { if (root.current >= 0) pickList.positionViewAtIndex(root.current, ListView.Center) })
    }
    function text(t, b) { openCommon(3); title = t || ""; body = b || "" }
    // `pre` ({ssid, pass, band, err}) reopens the window as it was after a
    // failed attempt: the name and the key stay, the reason is written under
    // them, and the owner corrects one character instead of starting over.
    function wifi(list, f, pre) {
        openCommon(4); title = Tr.t("wizard.wifi.title"); networks = list || []; dualSsids = markDual(networks); cb = f
        pre = pre || {}
        ssid = pre.ssid || ""; band = pre.band || ""; pass = pre.pass || ""; err = pre.err || ""
        for (var i = 0; i < networks.length; i++) if (ssid && (networks[i].ssid || "") === ssid && (!band || (networks[i].band || "") === band)) { wifiSel = i; break }
    }
    function updateWifi(list) { if (kind === 4) { networks = list || []; dualSsids = markDual(networks) } }
    // Quasi ogni router di casa trasmette lo stesso nome su 2.4 e 5 GHz: i nomi
    // doppi sono i soli a cui serve (e per cui ha senso mandare) la banda.
    function markDual(list) {
        var seen = {}, dup = {}
        for (var i = 0; i < list.length; i++) {
            var s = list[i].ssid || ""
            if (seen[s]) dup[s] = true
            seen[s] = true
        }
        return dup
    }
    function wifiError(m) { if (kind === 4) err = m || "" }
    function format(device, model, size, confirmWord, f) {
        openCommon(5); step = 0
        fdev = device || ""; fmodel = model || device || ""; fconfirm = confirmWord || ""
        var gb = size / (1024 * 1024 * 1024)
        fsize = gb >= 1000 ? (gb / 1024).toFixed(1) + " TB" : gb >= 10 ? Math.round(gb) + " GB" : gb.toFixed(1) + " GB"
        ffs = "ext4"; flabel = "Musica"; ftyped = ""; fmsg = ""; fpct = 0; cb = f
    }
    // Asks for the username and password of a network device. `f(user, pass)`
    // on "sign in", `f(null, null)` on cancel; `error` is shown under the
    // fields (the previous attempt was refused).
    function login(t, b, user, error, f) {
        openCommon(6); title = t || ""; body = b || ""
        luser = user || ""; lpass = ""; err = error || ""; cb = f
    }
    // Restart or shut down: `f("reboot" | "shutdown")`, `f("")` on cancel.
    function power(f) { openCommon(7); cb = f }
    function formatStatus(state, msg, pct) {
        if (kind !== 5 || step < 2) return
        fmsg = msg || ""; fpct = pct || 0
        if (state === "done") step = 3
        if (state === "error") step = 4
    }
    function close() {
        if (!active || closing) return
        closing = true
        closeScale = 0.92
        fadeAnim.duration = Theme.dur(200); fade = 0
    }
    Timer { interval: 30; repeat: true; running: root.closing; onTriggered: if (root.fade === 0) { root.kind = 0; root.closing = false } }

    function finishOk(ok) { var f = cb; close(); if (f) f(ok) }
    function finishPick(i) { var f = cb; close(); if (f) f(i) }
    function finishWifi(ok) { var f = cb; var s = ssid, p = pass, b = band; close(); if (f) f(ok ? s : null, ok ? p : null, ok ? b : "") }
    function finishLogin(ok) { var f = cb; var u = luser.trim(), p = lpass; close(); if (f) f(ok ? u : null, ok ? p : null) }
    function finishPower(act) { var f = cb; close(); if (f) f(act) }
    function backdrop() {
        if (kind === 1) finishOk(false)
        else if (kind === 7) finishPower("")
        else if (kind === 2) finishPick(-1)
        else if (kind === 4) finishWifi(false)
        else if (kind === 6) finishLogin(false)
        else if (kind === 5) { if (step <= 1) close() }
        else close()
    }
    function fmtCan() { return flabel !== "" && ftyped === flabel }
    function fmtStart() { step = 2; fpct = 0; fmsg = Tr.t("sources.internal.phasePreparing"); if (cb) cb(fdev, ffs, flabel) }

    Keys.onPressed: (e) => {
        if (e.key === Qt.Key_Escape) { if (kind === 5 && step === 2) return; backdrop(); e.accepted = true }
        else if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) {
            if (kind === 1) finishOk(true); else if (kind === 4 && ssid) finishWifi(true)
            else if (kind === 6) { if (luser.trim()) finishLogin(true) }
            else if (kind !== 5) close()
            e.accepted = true
        }
    }
    onActiveChanged: if (active) forceActiveFocus()

    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, (root.kind === 5 ? 0.8 : 0.7) * root.fade)   // bg-black/70, formattazione bg-black/80
        MouseArea { anchors.fill: parent; onClicked: root.backdrop() }
    }

    // ─── la scheda ─────────────────────────────────────────────────────────
    Rectangle {
        id: card
        readonly property real cw: root.kind === 3 ? 512 : root.kind === 4 ? 384 : 448
        readonly property real ipad: root.kind === 4 ? 20 : 24
        width: Math.min(cw, root.width - 48)
        height: Math.min(content.implicitHeight, root.height - 24)
        anchors.centerIn: parent
        radius: 16
        color: root.kind === 4 ? Theme.dark : Theme.light
        border.width: 1; border.color: root.kind === 4 ? Theme.wa(0.1) : Theme.accent
        opacity: root.fade
        scale: sc.value * root.closeScale
        BoxShadow { z: -1; targetX: 0; targetY: 0; targetW: parent.width; targetH: parent.height; radius: 16; blur: 50; spread: -12; offsetY: 25; color: Theme.blackA(0.25) }   // shadow-2xl
        MouseArea { anchors.fill: parent }

        Item {
            id: content
            x: card.ipad; y: card.ipad
            width: card.width - 2 * card.ipad
            implicitHeight: 2 * card.ipad + (root.kind === 1 ? confirmBox.height : root.kind === 2 ? pickBox.height : root.kind === 3 ? textBox.height : root.kind === 4 ? wifiBox.height : root.kind === 6 ? loginBox.height : root.kind === 7 ? powerBox.height : fmtBox.height)

            // 1) conferma: max-w-md, testo 18, Annulla + azione 48
            Column {
                id: confirmBox
                visible: root.kind === 1
                width: parent.width; spacing: 24
                Text { width: parent.width; text: root.body; wrapMode: Text.Wrap; color: Theme.white; font.family: Theme.font; font.pixelSize: 18; lineHeight: 28; lineHeightMode: Text.FixedHeight }
                Row {
                    width: parent.width; spacing: 12
                    Rectangle {
                        width: (parent.width - 12) / 2; height: 48; radius: 8; color: cTap.mix(Theme.accent, Theme.dark)
                        Text { anchors.centerIn: parent; text: Tr.t("common.cancel"); color: Theme.white; font.family: Theme.font; font.pixelSize: 16 }
                        Tap { id: cTap; onClicked: root.finishOk(false) }
                    }
                    Rectangle {
                        width: (parent.width - 12) / 2; height: 48; radius: 8
                        color: oTap.mix(root.danger ? "#dc2626" : Theme.gold, root.danger ? "#b91c1c" : "#ca8a04")
                        Text { anchors.centerIn: parent; text: root.okLabel; color: root.danger ? Theme.white : Theme.black; font.family: Theme.font; font.pixelSize: 16; font.bold: true }
                        Tap { id: oTap; onClicked: root.finishOk(true) }
                    }
                }
            }

            // 2) scelta da elenco: titolo 18 bold, righe 44, Annulla
            Column {
                id: pickBox
                visible: root.kind === 2
                width: parent.width
                Text { text: root.title; color: Theme.white; font.family: Theme.font; font.pixelSize: 18; font.bold: true; height: 28; verticalAlignment: Text.AlignVCenter }
                Item { width: 1; height: 12 }
                ListView {
                    id: pickList
                    width: parent.width
                    height: Math.min(root.items.length * 44, root.height - 220)
                    clip: true
                    model: root.items
                    boundsBehavior: Flickable.StopAtBounds
                    Component.onCompleted: if (root.current >= 0) positionViewAtIndex(root.current, ListView.Center)
                    onModelChanged: if (root.current >= 0) Qt.callLater(function() { positionViewAtIndex(root.current, ListView.Center) })
                    delegate: Rectangle {
                        required property var modelData
                        required property int index
                        readonly property bool cur: index === root.current
                        width: pickList.width; height: 44; radius: 8
                        color: cur ? Theme.goldA(0.2) : pTap.mix(Qt.rgba(0,0,0,0), Theme.wa(0.05))
                        Text { x: 12; width: parent.width - 48; anchors.verticalCenter: parent.verticalCenter; text: String(modelData); elide: Text.ElideRight; color: parent.cur ? Theme.gold : Theme.white; font.family: Theme.font; font.pixelSize: 14 }
                        Icon { visible: parent.cur; x: parent.width - 28; anchors.verticalCenter: parent.verticalCenter; name: "check"; size: 16; color: Theme.gold }
                        Tap { id: pTap; onClicked: root.finishPick(index) }
                    }
                }
                Item { width: 1; height: 12 }
                Rectangle {
                    width: parent.width; height: 44; radius: 8; color: pcTap.mix(Theme.accent, Theme.dark)
                    Text { anchors.centerIn: parent; text: Tr.t("common.cancel"); color: Theme.white; font.family: Theme.font; font.pixelSize: 16 }
                    Tap { id: pcTap; onClicked: root.finishPick(-1) }
                }
            }

            // 3) testo lungo (changelog): max-w-lg, 3/5 dello schermo
            Column {
                id: textBox
                visible: root.kind === 3
                width: parent.width
                Text { text: root.title; color: Theme.white; font.family: Theme.font; font.pixelSize: 18; font.bold: true; height: 28; verticalAlignment: Text.AlignVCenter }
                Item { width: 1; height: 16 }
                Flickable {
                    width: parent.width; height: root.height * 3 / 5; clip: true
                    contentHeight: bodyText.height
                    boundsBehavior: Flickable.StopAtBounds
                    Text { id: bodyText; width: parent.width; text: root.body; wrapMode: Text.Wrap; color: Theme.silver; font.family: Theme.font; font.pixelSize: 14; lineHeight: 20; lineHeightMode: Text.FixedHeight }
                }
                Item { width: 1; height: 16 }
                Rectangle {
                    width: parent.width; height: 44; radius: 8; color: tcTap.mix(Theme.accent, Theme.dark)
                    Text { anchors.centerIn: parent; text: Tr.t("common.close"); color: Theme.white; font.family: Theme.font; font.pixelSize: 16 }
                    Tap { id: tcTap; onClicked: root.close() }
                }
            }

            // 4) Wi-Fi (WifiConfigPanel.jsx): elenco 160, SSID, password, Annulla / Connetti
            Column {
                id: wifiBox
                visible: root.kind === 4
                width: parent.width
                Text { text: root.title; color: Theme.white; font.family: Theme.font; font.pixelSize: 18; font.bold: true; height: 28; verticalAlignment: Text.AlignVCenter }
                Item { width: 1; height: 12 }
                Rectangle {
                    width: parent.width; height: 160; radius: 8; color: "transparent"; border.width: 1; border.color: Theme.wa(0.1)
                    clip: true
                    Text { anchors.centerIn: parent; visible: root.networks.length === 0; text: Tr.t("wizard.wifi.scanning"); color: Theme.silver; font.family: Theme.font; font.pixelSize: 14 }
                    ListView {
                        id: wifiList
                        anchors.fill: parent
                        model: root.networks
                        boundsBehavior: Flickable.StopAtBounds
                        delegate: Item {
                            id: netItem
                            required property var modelData
                            required property int index
                            readonly property bool sel: index === root.wifiSel
                            width: wifiList.width; height: 36
                            Rectangle { anchors.fill: parent; color: Theme.goldA(0.1); visible: parent.sel }        // bg-hifi-gold/10
                            Rectangle { visible: index > 0; width: parent.width; height: 1; color: Theme.wa(0.05) }   // divide-white/5
                            Icon { x: 12; anchors.verticalCenter: parent.verticalCenter; name: "wifi"; size: 14; color: parent.sel ? Theme.gold : Theme.silver }
                            Row {
                                id: netName
                                x: 32; width: parent.width - 60; spacing: 6
                                anchors.verticalCenter: parent.verticalCenter
                                Text { width: Math.min(implicitWidth, netName.width - (tag.visible ? tag.width + 6 : 0) - (savedTag.visible ? savedTag.width + 6 : 0)); text: netItem.modelData.ssid || ""; elide: Text.ElideRight; color: netItem.sel ? Theme.gold : Theme.white; font.family: Theme.font; font.pixelSize: 14; anchors.verticalCenter: parent.verticalCenter }
                                BandTag { id: tag; band: root.dualSsids[netItem.modelData.ssid || ""] ? (netItem.modelData.band || "") : ""; on: netItem.sel; anchors.verticalCenter: parent.verticalCenter }
                                // "Saved", as Android puts it: NetworkManager still has the key
                                // for this network, so a touch on the row joins it without asking
                                Rectangle {
                                    id: savedTag
                                    visible: !!netItem.modelData.saved
                                    width: visible ? savedText.implicitWidth + 12 : 0; height: 18; radius: 4
                                    color: netItem.sel ? Theme.goldA(0.15) : Theme.wa(0.06)
                                    anchors.verticalCenter: parent.verticalCenter
                                    Text { id: savedText; anchors.centerIn: parent; text: Tr.t("settings.network.saved"); color: netItem.sel ? Theme.goldA(0.9) : Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 10 }
                                }
                            }
                            Icon { visible: !!modelData.security; x: parent.width - 20; anchors.verticalCenter: parent.verticalCenter; name: "lock"; size: 12; color: parent.sel ? Theme.goldA(0.6) : Theme.silverA(0.6) }   // opacity-60 sul colore ereditato
                            Tap { onClicked: { root.wifiSel = index; root.ssid = modelData.ssid || ""; root.band = root.dualSsids[modelData.ssid || ""] ? (modelData.band || "") : ""; root.err = ""; if (modelData.saved) { root.pass = ""; root.finishWifi(true) } } }
                        }
                    }
                }
                Item { width: 1; height: 12 }
                TextField_ {
                    id: ssidField
                    width: parent.width; height: 40; textSize: 14; padding: 12
                    text: root.ssid; placeholder: Tr.t("wizard.wifi.title")
                    color: Theme.wa(0.05); restBorder: Theme.wa(0.1); focusColor: Theme.goldA(0.5)   // focus:border-hifi-gold/50
                    // Un nome scritto a mano non e' piu' la riga toccata: nessuna
                    // banda da fissare.
                    onTextEdited: (t) => { root.ssid = t; root.band = "" }
                }
                Item { width: 1; height: 8 }
                TextField_ {
                    id: passField
                    width: parent.width; height: 40; textSize: 14; padding: 12
                    // In chiaro: la chiave si scrive una volta sola, sulla tastiera
                    // a schermo, e un carattere sbagliato dietro i pallini e' il
                    // motivo piu' comune di una connessione fallita.
                    text: root.pass; placeholder: Tr.t("wizard.wifi.passwordPlaceholder")
                    color: Theme.wa(0.05); restBorder: Theme.wa(0.1); focusColor: Theme.goldA(0.5)
                    onTextEdited: (t) => root.pass = t
                }
                Text { visible: root.err !== ""; width: parent.width; height: 20; verticalAlignment: Text.AlignVCenter; text: root.err; color: Theme.red400; font.family: Theme.font; font.pixelSize: 12 }
                Item { width: 1; height: 12 }
                Row {
                    width: parent.width; spacing: 8
                    Rectangle {
                        // "Annulla": fondo trasparente, bordo bianco/10, testo silver
                        width: (parent.width - 8) / 2; height: 40; radius: 8; color: wcTap.mix(Qt.rgba(1, 1, 1, 0), Theme.wa(0.1)); border.width: 1; border.color: Theme.wa(0.1)
                        Text { anchors.centerIn: parent; text: Tr.t("common.cancel"); color: Theme.silver; font.family: Theme.font; font.pixelSize: 14 }
                        Tap { id: wcTap; onClicked: root.finishWifi(false) }
                    }
                    Rectangle {
                        width: (parent.width - 8) / 2; height: 40; radius: 8
                        color: woTap.mix(Theme.gold, "#ca8a04")
                        opacity: root.ssid ? 1 : 0.4                    // disabled:opacity-40 su fondo E testo
                        Text { anchors.centerIn: parent; text: Tr.t("wizard.connect"); color: Theme.black; font.family: Theme.font; font.pixelSize: 14; font.bold: true }
                        Tap { id: woTap; enabled: root.ssid !== ""; onClicked: root.finishWifi(true) }
                    }
                }
            }

            // 6) accesso a una cartella di rete: nome utente, password, Annulla / Accedi
            Column {
                id: loginBox
                visible: root.kind === 6
                width: parent.width
                Row {
                    spacing: 8
                    Icon { name: "lock"; size: 18; color: Theme.gold; anchors.verticalCenter: parent.verticalCenter }
                    Text { width: loginBox.width - 26; height: 28; verticalAlignment: Text.AlignVCenter; text: root.title; elide: Text.ElideRight; color: Theme.white; font.family: Theme.font; font.pixelSize: 18; font.bold: true }
                }
                Item { width: 1; height: 8 }
                Text { width: parent.width; text: root.body; wrapMode: Text.Wrap; color: Theme.silver; font.family: Theme.font; font.pixelSize: 14; lineHeight: 20; lineHeightMode: Text.FixedHeight }
                Item { width: 1; height: 16 }
                TextField_ {
                    width: parent.width; height: 46; textSize: 14; padding: 12
                    text: root.luser; placeholder: Tr.t("sources.wizard.userLabel"); restBorder: Theme.accent
                    onTextEdited: (t) => { root.luser = t; root.err = "" }
                }
                Item { width: 1; height: 8 }
                TextField_ {
                    width: parent.width; height: 46; textSize: 14; padding: 12
                    text: root.lpass; placeholder: Tr.t("sources.pass"); password: true; restBorder: Theme.accent
                    onTextEdited: (t) => { root.lpass = t; root.err = "" }
                    onAccepted: if (root.luser.trim()) root.finishLogin(true)
                }
                Item { width: 1; height: 8; visible: root.err !== "" }
                Text { visible: root.err !== ""; width: parent.width; wrapMode: Text.Wrap; text: root.err; color: Theme.red400; font.family: Theme.font; font.pixelSize: 13; lineHeight: 18; lineHeightMode: Text.FixedHeight }
                Item { width: 1; height: 20 }
                Row {
                    width: parent.width; spacing: 12
                    Rectangle {
                        width: (parent.width - 12) / 2; height: 48; radius: 8; color: lcTap.mix(Theme.accent, Theme.dark)
                        Text { anchors.centerIn: parent; text: Tr.t("common.cancel"); color: Theme.white; font.family: Theme.font; font.pixelSize: 16 }
                        Tap { id: lcTap; onClicked: root.finishLogin(false) }
                    }
                    Rectangle {
                        width: (parent.width - 12) / 2; height: 48; radius: 8
                        color: loTap.mix(Theme.gold, "#ca8a04")
                        opacity: root.luser.trim() ? 1 : 0.4
                        Text { anchors.centerIn: parent; text: Tr.t("sources.wizard.signIn"); color: Theme.black; font.family: Theme.font; font.pixelSize: 16; font.bold: true }
                        Tap { id: loTap; enabled: root.luser.trim() !== ""; onClicked: root.finishLogin(true) }
                    }
                }
            }

            // 7) power: two big tiles, restart and shut down, then Cancel.
            // The popup is already the confirmation: a tile acts at once.
            Column {
                id: powerBox
                visible: root.kind === 7
                width: parent.width
                Row {
                    spacing: 8
                    Icon { name: "power"; size: 18; color: Theme.gold; anchors.verticalCenter: parent.verticalCenter }
                    Text { width: powerBox.width - 26; height: 28; verticalAlignment: Text.AlignVCenter; text: Tr.t("settings.controls.powerTitle"); elide: Text.ElideRight; color: Theme.white; font.family: Theme.font; font.pixelSize: 18; font.bold: true }
                }
                Item { width: 1; height: 20 }
                Row {
                    width: parent.width; spacing: 12
                    Repeater {
                        model: [{ act: "reboot", icon: "rotate-cw", key: "settings.controls.powerReboot", c: "#ea580c", p: "#c2410c" },
                                { act: "shutdown", icon: "power", key: "settings.controls.powerShutdown", c: "#dc2626", p: "#b91c1c" }]
                        Rectangle {
                            required property var modelData
                            width: (parent.width - 12) / 2; height: 112; radius: 12
                            color: pwTap.mix(modelData.c, modelData.p)
                            scale: pwTap.tapScale
                            Icon { anchors.horizontalCenter: parent.horizontalCenter; y: 22; name: parent.modelData.icon; size: 36; color: Theme.white }
                            Text { anchors.horizontalCenter: parent.horizontalCenter; y: 70; height: 24; verticalAlignment: Text.AlignVCenter; text: Tr.t(parent.modelData.key); color: Theme.white; font.family: Theme.font; font.pixelSize: 17; font.bold: true }
                            Tap { id: pwTap; tap: 0.95; onClicked: root.finishPower(parent.modelData.act) }
                        }
                    }
                }
                Item { width: 1; height: 12 }
                Rectangle {
                    width: parent.width; height: 48; radius: 8; color: pwcTap.mix(Theme.accent, Theme.dark)
                    Text { anchors.centerIn: parent; text: Tr.t("common.cancel"); color: Theme.white; font.family: Theme.font; font.pixelSize: 16 }
                    Tap { id: pwcTap; onClicked: root.finishPower("") }
                }
            }

            // 5) formattazione (FormatWizard.jsx): scelta -> conferma -> avanzamento -> esito
            Column {
                id: fmtBox
                visible: root.kind === 5
                width: parent.width
                // passo 0: filesystem ed etichetta
                Column {
                    visible: root.step === 0
                    width: parent.width
                    Text { height: 28; verticalAlignment: Text.AlignVCenter; text: Tr.t("sources.internal.wizardTitle"); color: Theme.white; font.family: Theme.font; font.pixelSize: 18; font.bold: true }
                    Item { width: 1; height: 4 }
                    Text { height: 20; verticalAlignment: Text.AlignVCenter; text: root.fmodel + " · " + root.fsize; color: Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 14 }
                    Item { width: 1; height: 16 }
                    Text { height: 20; verticalAlignment: Text.AlignVCenter; text: Tr.t("sources.internal.fsLabel"); color: Theme.silver; font.family: Theme.font; font.pixelSize: 14 }
                    Item { width: 1; height: 8 }
                    Row {
                        width: parent.width; spacing: 12
                        Repeater {
                            model: ["ext4", "exfat"]
                            Rectangle {
                                required property string modelData
                                readonly property bool on: root.ffs === modelData
                                width: (parent.width - 12) / 2; height: 64; radius: 8
                                color: on ? Theme.goldA(0.1) : Theme.dark; border.width: 1; border.color: on ? Theme.gold : Theme.accent
                                Text { x: 12; y: 12; height: 20; verticalAlignment: Text.AlignVCenter; text: Tr.t(modelData === "ext4" ? "sources.internal.fsExt4" : "sources.internal.fsExfat"); color: Theme.white; font.family: Theme.font; font.pixelSize: 14 }
                                Text { x: 12; y: 36; width: parent.width - 24; text: Tr.t(modelData === "ext4" ? "sources.internal.fsExt4Hint" : "sources.internal.fsExfatHint"); wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight; color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 12 }
                                Tap { onClicked: root.ffs = modelData }
                            }
                        }
                    }
                    Item { width: 1; height: 16 }
                    Text { height: 20; verticalAlignment: Text.AlignVCenter; text: Tr.t("sources.internal.labelField"); color: Theme.silver; font.family: Theme.font; font.pixelSize: 14 }
                    Item { width: 1; height: 8 }
                    TextField_ { width: parent.width; height: 48; text: root.flabel; restBorder: Theme.accent; onTextEdited: (t) => root.flabel = t }
                    Item { width: 1; height: 24 }
                    Row {
                        width: parent.width; spacing: 12
                        Rectangle {
                            width: (parent.width - 12) / 2; height: 48; radius: 8; color: f0c.mix(Theme.accent, Theme.dark)
                            Text { anchors.centerIn: parent; text: Tr.t("common.cancel"); color: Theme.white; font.family: Theme.font; font.pixelSize: 16 }
                            Tap { id: f0c; onClicked: root.close() }
                        }
                        Rectangle {
                            width: (parent.width - 12) / 2; height: 48; radius: 8; color: root.flabel ? f0o.mix(Theme.gold, "#ca8a04") : Theme.goldA(0.4)
                            Text { anchors.centerIn: parent; text: Tr.t("common.next"); color: Theme.black; font.family: Theme.font; font.pixelSize: 16; font.bold: true }
                            Tap { id: f0o; enabled: root.flabel !== ""; onClicked: { root.step = 1; root.ftyped = "" } }
                        }
                    }
                }
                // passo 1: avvertenza e conferma digitata
                Column {
                    visible: root.step === 1
                    width: parent.width
                    Row {
                        spacing: 8
                        Icon { name: "alert-triangle"; size: 22; color: Theme.red400; anchors.verticalCenter: parent.verticalCenter }
                        Text { height: 28; verticalAlignment: Text.AlignVCenter; text: Tr.t("sources.internal.warnTitle"); color: Theme.white; font.family: Theme.font; font.pixelSize: 18; font.bold: true }
                    }
                    Item { width: 1; height: 12 }
                    Text {
                        width: parent.width; wrapMode: Text.Wrap; color: Theme.silver; font.family: Theme.font; font.pixelSize: 14; lineHeight: 20; lineHeightMode: Text.FixedHeight
                        text: Tr.tf("sources.internal.warnBody", "model", root.fmodel).replace("{size}", root.fsize).replace("{path}", root.fdev)
                    }
                    Item { width: 1; height: 16 }
                    Text { height: 20; verticalAlignment: Text.AlignVCenter; text: Tr.tf("sources.internal.typeToConfirm", "label", root.flabel); color: Theme.silver; font.family: Theme.font; font.pixelSize: 14 }
                    Item { width: 1; height: 8 }
                    TextField_ { width: parent.width; height: 48; text: root.ftyped; restBorder: Theme.redA(0.4); focusBorder: true; focusColor: Theme.red400; onTextEdited: (t) => root.ftyped = t }   // focus:border-red-400
                    Item { width: 1; height: 24 }
                    Row {
                        width: parent.width; spacing: 12
                        Rectangle {
                            width: (parent.width - 12) / 2; height: 48; radius: 8; color: f1c.mix(Theme.accent, Theme.dark)
                            Text { anchors.centerIn: parent; text: Tr.t("common.back"); color: Theme.white; font.family: Theme.font; font.pixelSize: 16 }
                            Tap { id: f1c; onClicked: { root.step = 0; root.ftyped = "" } }
                        }
                        Rectangle {
                            width: (parent.width - 12) / 2; height: 48; radius: 8; color: root.fmtCan() ? f1o.mix("#dc2626", "#b91c1c") : Qt.rgba(0xdc/255, 0x26/255, 0x26/255, 0.4)
                            Text { anchors.centerIn: parent; text: Tr.t("sources.internal.formatNow"); color: Theme.white; font.family: Theme.font; font.pixelSize: 16; font.bold: true }
                            Tap { id: f1o; enabled: root.fmtCan(); onClicked: root.fmtStart() }
                        }
                    }
                }
                // passo 2: avanzamento
                Column {
                    visible: root.step === 2
                    width: parent.width
                    Spinner { anchors.horizontalCenter: parent.horizontalCenter; radius: 28; color: Theme.accent; active: root.kind === 5 && root.step === 2 }
                    Item { width: 1; height: 24 }
                    Text { width: parent.width; height: 24; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; text: root.fmsg; color: Theme.wa(0.8); font.family: Theme.font; font.pixelSize: 16 }
                    Item { width: 1; height: 24 }
                    Rectangle {
                        width: parent.width; height: 12; radius: 6; color: Theme.dark
                        Rectangle { width: parent.width * Math.max(0, Math.min(100, root.fpct)) / 100; height: 12; radius: 6; color: Theme.accent }
                    }
                    Item { width: 1; height: 12 }
                    Text { width: parent.width; height: 20; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; text: Tr.t("sources.internal.keepPowered"); color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 14 }
                }
                // passo 3/4: fatto o errore
                Column {
                    visible: root.step >= 3
                    width: parent.width
                    Icon { anchors.horizontalCenter: parent.horizontalCenter; name: root.step === 4 ? "alert-triangle" : "check-circle"; size: 56; color: root.step === 4 ? Theme.red500 : Theme.green500 }
                    Item { width: 1; height: 24 }
                    Text { width: parent.width; height: 28; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; text: root.step === 4 ? Tr.t("common.error") : Tr.t("sources.internal.doneAdopted"); color: Theme.white; font.family: Theme.font; font.pixelSize: 18; font.bold: true }
                    Item { width: 1; height: 8 }
                    Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; text: root.step === 4 ? root.fmsg : Tr.t("sources.internal.doneHint"); color: Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 14; lineHeight: 20; lineHeightMode: Text.FixedHeight }
                    Item { width: 1; height: 24 }
                    Rectangle {
                        width: parent.width; height: 48; radius: 8; color: f3.mix(root.step === 4 ? Theme.accent : Theme.gold, Theme.dark)
                        Text { anchors.centerIn: parent; text: Tr.t("sources.internal.close"); color: root.step === 4 ? Theme.white : Theme.black; font.family: Theme.font; font.pixelSize: 16; font.bold: true }
                        Tap { id: f3; onClicked: root.close() }
                    }
                }
            }
        }
    }
}
