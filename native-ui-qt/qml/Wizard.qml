// Le due schermate a pagina intera che precedono l'app (screen_wizard.c):
// il wizard di primo avvio (SetupWizard.jsx: porta in rete e rimanda a un
// browser) e la modalita' installer (InstallWizard.jsx, inglese e semplice di
// proposito). Decide da /boot_mode e /provision_status.
import QtQuick
import QtQuick.Effects
import Hifi
import Hifi.Ui

Item {
    id: root
    property real devScale: 1
    property int mode: 0                 // 0 nessuno, 1 primo avvio, 2 installer
    readonly property bool active: mode !== 0
    property bool dry: false
    visible: active
    anchors.fill: parent
    // primo avvio
    property string ip: ""
    property bool wired: false
    property bool connected: false
    property string stage: ""
    property string perror: ""
    property var nets: []                // [{ssid,security,signal}]
    property int pick: -1
    property string pass: ""
    property bool connecting: false
    property string wifiErr: ""
    // installer
    property int step: 0                 // welcome, disk, confirm, progress
    property var disks: []               // [{path,model,transport,size}]
    property int sel: -1
    property bool disksLoading: false
    property string disksErr: ""
    property string state: "idle"
    property string msg: ""
    property int progress: 0
    property int countdown: 0

    Component.onCompleted: {
        if (Sys.forcedWizard) { dry = true; mode = Sys.forcedWizard === "install" ? 2 : 1; start(); return }
        Api.get(Api.apiBase + "/boot_mode", function(ok, d) {
            if (ok && d && d.mode === "installer") { mode = 2; start(); return }
            Api.get(Api.apiBase + "/provision_status", function(ok2, d2) {
                if (ok2 && d2 && typeof d2 === "object" && (d2.pending || !d2.completed)) { mode = 1; readProvision(d2); start() }
            }, 6000)
        }, 6000)
    }
    function start() { readNet(); if (mode === 1) pollProvision(); if (mode === 2) readInstall() }
    function readNet() {
        Api.get(Api.apiBase + "/network_status", function(ok, d) {
            if (!ok || !d || typeof d !== "object") return
            if (d.ip) ip = String(d.ip)
            wired = d.type === "wired"
            connected = !!d.connected && ip !== "" && ip.indexOf("127.") !== 0
            // Ripiego come in InstallWizard.jsx: se lo stato di rete non porta
            // l'indirizzo, il QR resterebbe senza numero da mostrare.
            if (!ip) Api.get(Api.apiBase + "/system_info", function(ok2, d2) {
                if (ok2 && d2 && d2.local_ip && d2.local_ip !== "Unknown") ip = String(d2.local_ip)
            }, 6000)
        }, 6000)
    }
    function readProvision(d) {
        // 🚨 Fine del primo avvio. Senza questo la schermata "apri in un
        // browser" restava lì anche a configurazione finita, e per vedere
        // l'interfaccia bisognava riavviare.
        // Servono ENTRAMBE le condizioni, come in SetupWizard.jsx:
        // get_provision_status() risponde `{pending: false}` senza `completed`
        // anche solo mentre hifi-webui si riavvia, e quel lampo chiuderebbe il
        // wizard a metà configurazione. In prova a secco (Sys.forcedWizard) la
        // schermata deve restare, o non ci si potrebbe piu' guardare.
        if (!dry && d.pending === false && d.completed === true) { root.mode = 0; return }
        stage = String(d.stage || ""); perror = d.error ? String(d.error) : ""
        var n = (d.networks || []).map(function(x) { return { ssid: String(x.ssid || ""), security: String(x.security || ""), signal: Number(x.signal || 0) } })
        if (n.length || !nets.length) nets = n
    }
    function pollProvision() { Api.get(Api.apiBase + "/provision_status", function(ok, d) { if (ok && d && typeof d === "object") readProvision(d) }, 6000) }
    function readInstall() { Api.get(Api.apiBase + "/install/status", function(ok, d) { if (ok && d && typeof d === "object") { state = String(d.state || "idle"); msg = String(d.message || ""); progress = Number(d.progress || 0) } }, 6000) }
    function readDisks() {
        disksLoading = true; disks = []
        Api.get(Api.apiBase + "/install/disks", function(ok, d) {
            var out = []
            if (ok && d && d.disks) for (var i = 0; i < d.disks.length; i++) {
                var k = d.disks[i], p = String(k.path || "")
                if (p.indexOf("boot0") >= 0 || p.indexOf("boot1") >= 0) continue
                out.push({ path: p, model: String(k.model || ""), transport: String(k.transport || ""), size: Number(k.size || 0) })
            }
            disks = out; disksErr = ok ? "" : "No disks available."; disksLoading = false
        }, 8000)
    }
    Timer { interval: 3000; repeat: true; running: root.active; onTriggered: { root.readNet(); if (root.mode === 1) root.pollProvision() } }
    Timer { interval: 1000; repeat: true; running: root.mode === 2; onTriggered: root.readInstall() }
    Timer { interval: 1000; repeat: true; running: root.mode === 2 && root.state === "done"
            onTriggered: { if (root.countdown === 0) root.countdown = 10; else if (root.countdown > 1) root.countdown--; else if (!root.dry) { root.countdown = 0; Api.post(Api.apiBase + "/reboot", {}) } } }
    function wifiConnect() {
        if (pick < 0) return
        connecting = true; wifiErr = ""
        Api.post(Api.apiBase + "/provision_wifi_connect", { ssid: nets[pick].ssid, password: pass }, function(ok, d, st) {
            if (!ok || st < 200 || st >= 300) wifiErr = Tr.t("wizard.wifi.connectFailed")
            connecting = false
        }, 20000)
    }
    function fmtSize(b) { var gb = b / (1024 * 1024 * 1024); return gb >= 1000 ? (gb / 1024).toFixed(1) + " TB" : gb >= 10 ? Math.round(gb) + " GB" : gb.toFixed(1) + " GB" }
    function stepTo(s) { step = s; if (s === 1) readDisks(); fadeAnim.restart() }
    NumberAnimation { id: fadeAnim; target: body; property: "opacity"; from: 0; to: 1; duration: 200 }
    Keys.onPressed: (e) => {
        if (mode === 1 && pick >= 0) {
            if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) wifiConnect()
            else if (e.key === Qt.Key_Escape) { pick = -1; pass = "" }
        } else if (mode === 2 && e.key === Qt.Key_Escape) { if (step === 2) stepTo(1); else if (step === 1) stepTo(0) }
    }
    onActiveChanged: if (active) forceActiveFocus()

    // quadratone dorato con l'alone e il disco
    component Hero: Item {
        property real side: 64
        property real iconPx: 32
        width: side; height: side
        // shadow-[0_0_40px_rgba(212,175,55,0.3)]: box-shadow esatto, non la sfocatura di MultiEffect
        BoxShadow { targetX: 0; targetY: 0; targetW: parent.width; targetH: parent.height; radius: 16; blur: 40; offsetY: 0; color: Theme.goldA(0.3) }
        // bg-gradient-to-br from-hifi-gold to-yellow-600: diagonale
        DiagonalFallback { anchors.fill: parent; radius: 16; from: Theme.gold; to: "#ca8a04" }
        Icon { anchors.centerIn: parent; name: "disc-3"; size: parent.iconPx; color: Theme.black }
    }
    component BigButton: Rectangle {
        property string label: ""
        property string trail: ""
        property color fg: Theme.black
        signal clicked()
        height: 46; radius: 12
        Row { anchors.centerIn: parent; spacing: 8
              Text { text: parent.parent.label; color: parent.parent.fg; font.family: Theme.font; font.pixelSize: 15; font.bold: true; anchors.verticalCenter: parent.verticalCenter }
              Icon { visible: !!parent.parent.trail; name: parent.parent.trail || ""; size: 18; color: parent.parent.fg; anchors.verticalCenter: parent.verticalCenter } }
        Tap { onClicked: parent.clicked() }
    }
    component QrCorner: Rectangle {
        readonly property string value: "http://" + (root.ip || "hifiplayer.local")
        x: 1024 - 16 - width; y: 64; width: 124; height: 124 + 20; radius: 12; color: Theme.white
        // shadow-lg: 0 10px 15px -3px + 0 4px 6px -4px, nero al 10 %
        BoxShadow { z: -1; targetX: 0; targetY: 0; targetW: parent.width; targetH: parent.height; radius: 12; blur: 15; spread: -3; offsetY: 10; color: Theme.blackA(0.1) }
        BoxShadow { z: -1; targetX: 0; targetY: 0; targetW: parent.width; targetH: parent.height; radius: 12; blur: 6; spread: -4; offsetY: 4; color: Theme.blackA(0.1) }
        QrCode { x: 10; y: 10; width: 104; height: 104; text: parent.value }
        Icon { x: 8; y: parent.height - 18; name: "smartphone"; size: 11; color: Theme.blackA(0.7) }   // icona Smartphone accanto all'indirizzo
        Text { x: 20; y: parent.height - 20; width: parent.width - 24; height: 16; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; text: parent.value; elide: Text.ElideMiddle; color: Qt.rgba(0, 0, 0, 0.7); font.family: Theme.font; font.pixelSize: 10 }
    }

    Rectangle { anchors.fill: parent; color: Theme.dark }
    Item {
        id: body
        anchors.fill: parent
        // ── primo avvio ─────────────────────────────────────────────────────
        Item {
            visible: root.mode === 1
            anchors.fill: parent
            readonly property real headH: 64 + 24 + 30 + 8 + 40 + 16
            readonly property int shownNets: Math.min(5, Math.max(2, root.nets.length))
            readonly property real bh: root.connected ? headH + 74 + 16 + 110 : headH + 48 * (root.nets.length ? Math.min(5, root.nets.length) : 2) + (root.pick >= 0 ? 12 + 44 + 8 + 40 : 32)
            readonly property real ty0: Math.max(16, 300 - bh / 2)
            Hero { x: 512 - 32; y: parent.ty0; side: 64; iconPx: 32 }
            Text { y: parent.ty0 + 88; width: parent.width; height: 30; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; text: Tr.t(root.connected ? "wizard.qr.connectedTitle" : "wizard.wifi.title"); color: Theme.white; font.family: Theme.font; font.pixelSize: 24; font.bold: true }
            Text { id: setupSub; x: 512 - 220; y: parent.ty0 + 126; width: 440; height: 40; wrapMode: Text.Wrap; maximumLineCount: 2; horizontalAlignment: Text.AlignHCenter; text: Tr.t(root.connected ? "wizard.qr.connectedSubtitle" : "wizard.wifi.setupSubtitle"); color: Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 14 }
            // collegato: l'indirizzo e i consigli
            Column {
                visible: root.connected
                anchors.horizontalCenter: parent.horizontalCenter; y: parent.ty0 + 182; spacing: 16
                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: addrText.implicitWidth + 64; height: 74; radius: 16; color: Theme.white
                    Text { y: 14; width: parent.width; height: 14; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; text: Tr.up("wizard.qr.addressLabel"); color: Qt.rgba(0, 0, 0, 0.5); font.family: Theme.font; font.pixelSize: 11; font.bold: true; font.letterSpacing: 0.5 }
                    Text { id: addrText; y: 30; width: parent.width; height: 34; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; text: "http://" + (root.ip || "hifiplayer.local"); color: Theme.black; font.family: Theme.font; font.pixelSize: 24; font.bold: true }
                }
                Rectangle {
                    width: 380; height: tips.height + 24; radius: 12; color: Theme.goldA(0.1); border.width: 1; border.color: Theme.goldA(0.3)
                    Column { id: tips; x: 16; y: 12; width: parent.width - 32; spacing: 4
                             Text { text: Tr.up("wizard.qr.tipsLabel"); color: Theme.gold; font.family: Theme.font; font.pixelSize: 11; font.bold: true; font.letterSpacing: 0.5 }
                             Text { width: parent.width; wrapMode: Text.Wrap; text: Tr.t("wizard.qr.addressHint"); color: Theme.wa(0.9); font.family: Theme.font; font.pixelSize: 13; lineHeight: 18; lineHeightMode: Text.FixedHeight }
                             Text { width: parent.width; wrapMode: Text.Wrap; text: Tr.t("wizard.qr.pcRecommended"); color: Theme.wa(0.9); font.family: Theme.font; font.pixelSize: 13; lineHeight: 18; lineHeightMode: Text.FixedHeight } }
                }
            }
            // non collegato: le reti e, sotto, la password della rete scelta
            Item {
                visible: !root.connected
                x: 512 - 190; y: parent.ty0 + 182; width: 380
                readonly property real formH: root.pick >= 0 ? 12 + 44 + 8 + 40 : 32
                readonly property real listH: Math.max(44, Math.min(root.nets.length * 44, 600 - 16 - y - formH - 20))
                // la scheda: bg-hifi-dark border border-white/10 rounded-2xl p-5
                Rectangle { x: -20; y: -20; width: parent.width + 40; height: parent.listH + parent.formH + 40; radius: 16; color: Theme.dark; border.width: 1; border.color: Theme.wa(0.1) }
                // la cornice dell'elenco: rounded-lg border border-white/10
                Rectangle { visible: root.nets.length > 0; width: parent.width; height: parent.listH; radius: 8; color: "transparent"; border.width: 1; border.color: Theme.wa(0.1) }
                Item {
                    visible: root.nets.length === 0
                    width: parent.width; height: 60
                    Text { y: 10; width: parent.width; height: 24; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; text: Tr.t(root.stage ? "wizard.wifi.scanning" : "wizard.wifi.noNetworks"); color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 13 }
                    Spinner { anchors.horizontalCenter: parent.horizontalCenter; y: 41; radius: 11; thickness: 3; active: root.active && root.mode === 1 && !root.connected }
                }
                ListView {
                    id: netList
                    visible: root.nets.length > 0
                    width: parent.width; height: parent.listH; clip: true; spacing: 0
                    model: root.nets
                    boundsBehavior: Flickable.StopAtBounds
                    delegate: Rectangle {
                        required property var modelData
                        required property int index
                        readonly property bool on: index === root.pick
                        // righe senza fondo, divise da divide-white/5; la scelta e' oro/10 senza bordo
                        width: netList.width; height: 44; radius: 8
                        color: on ? Theme.goldA(0.1) : "transparent"
                        Rectangle { visible: index < root.nets.length - 1; x: 0; y: 43; width: parent.width; height: 1; color: Theme.wa(0.05) }
                        Icon { x: 10; anchors.verticalCenter: parent.verticalCenter; name: "wifi"; size: 16; color: parent.on ? Theme.gold : Theme.silverA(0.6) }
                        Text { x: 36; width: parent.width - 86; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; text: modelData.ssid; color: parent.on ? Theme.gold : Theme.white; font.family: Theme.font; font.pixelSize: 14 }
                        // lucchetto (12 px, opacity-60) per le reti protette, al posto del %
                        Icon { anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; name: "lock"; size: 12
                               visible: modelData.security !== "" && modelData.security !== "--" && modelData.security.toLowerCase() !== "none"
                               color: parent.on ? Theme.goldA(0.6) : Theme.silverA(0.6) }
                        Tap { onClicked: { root.pick = root.pick === index ? -1 : index; root.pass = ""; root.wifiErr = "" } }
                    }
                }
                TextField_ {
                    id: passField
                    visible: root.pick >= 0
                    y: parent.listH + 12; width: parent.width; height: 44; textSize: 16; padding: 14
                    color: Theme.wa(0.05); restBorder: Theme.wa(0.1); focusColor: Theme.goldA(0.5); password: true   // bg-white/5, border-white/10, focus oro/50
                    text: root.pass; placeholder: Tr.t("wizard.wifi.passwordPlaceholder")
                    onTextEdited: (t) => root.pass = t
                    onAccepted: root.wifiConnect()
                }
                BigButton { visible: root.pick >= 0; y: parent.listH + 12 + 44 + 8; width: parent.width; height: 40; color: cTap2.mix(Theme.gold, Theme.wa(0.2)); label: Tr.t(root.connecting ? "wizard.wifi.connecting" : "wizard.connect"); onClicked: root.wifiConnect()
                            Tap { id: cTap2; onClicked: root.wifiConnect() } }
                Text { visible: root.pick < 0 && !root.wifiErr && !(root.perror && root.stage === "failed"); y: parent.listH + 10; width: parent.width; height: 26; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; text: Tr.t("wizard.wifi.rescan"); color: Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 13
                       Tap { grow: 10; onClicked: Api.post(Api.apiBase + "/provision_wifi_rescan", {}, function() { root.pollProvision() }) } }
            }
            Text { visible: root.wifiErr !== "" || (root.perror !== "" && root.stage === "failed"); x: 512 - 190; y: 600 - 38; width: 380; height: 24; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; text: root.wifiErr || root.perror; color: Theme.red400; font.family: Theme.font; font.pixelSize: 12 }
        }
        // ── installer ───────────────────────────────────────────────────────
        Item {
            visible: root.mode === 2
            anchors.fill: parent
            readonly property bool running: root.state === "running"
            readonly property bool done: root.state === "done"
            readonly property bool err: root.state === "error"
            readonly property bool busy: running || done || err
            // barra in alto / piede con Back
            Item {
                visible: !parent.busy && (root.step === 1 || root.step === 2)
                anchors.fill: parent
                Rectangle { y: 47; width: parent.width; height: 1; color: Theme.borderA(0.6) }
                Glow { x: 24 + 4 - outer; y: 20 + 4 - outer; radius: 4; blur: 6; color: Theme.goldA(0.8) }   // shadow 0 0 6px oro/80
                Rectangle { x: 24; y: 20; width: 8; height: 8; radius: 4; color: Theme.gold }
                Text { x: 40; y: 0; height: 48; verticalAlignment: Text.AlignVCenter; text: "OSMIUM SOUND"; color: Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 11; font.bold: true; font.letterSpacing: 2.2 }
                Rectangle { y: 600 - 56; width: parent.width; height: 1; color: Theme.borderA(0.6) }
                Item {
                    x: 32; y: 600 - 56 + 11; width: 88; height: 34
                    Icon { x: 0; anchors.verticalCenter: parent.verticalCenter; name: "chevron-left"; size: 18; color: Theme.silverA(0.6) }
                    Text { x: 24; anchors.verticalCenter: parent.verticalCenter; text: "Back"; color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 13 }
                    Tap { grow: 6; onClicked: root.stepTo(root.step === 2 ? 1 : 0) }
                }
            }
            QrCorner { visible: !parent.busy && root.step <= 1 }
            // avanzamento / esito
            Item {
                visible: parent.busy
                anchors.fill: parent
                readonly property real y0: 300 - (64 + 24 + 26 + 4 + 40 + 24 + 8) / 2
                Hero { x: 512 - 32; y: parent.y0; side: 64; iconPx: 32 }
                Icon { visible: parent.parent.done; x: 512 - 16; y: parent.y0 + 16; name: "check-circle"; size: 32; color: Theme.black }
                Text { y: parent.y0 + 88; width: parent.width; height: 26; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; text: parent.parent.err ? "Installation failed" : parent.parent.done ? "Installation complete" : "Installing…"; color: Theme.white; font.family: Theme.font; font.pixelSize: 20; font.bold: true }
                Text { x: 512 - 192; y: parent.y0 + 118; width: 384; height: 40; wrapMode: Text.Wrap; maximumLineCount: 2; horizontalAlignment: Text.AlignHCenter
                       text: root.msg || (parent.parent.done ? "Remove the boot media (USB/DVD) now — rebooting automatically." : "Do not power off or remove the boot media.")
                       color: parent.parent.err ? Theme.red300 : Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 14 }
                Rectangle { visible: parent.parent.running; x: 512 - 192; y: parent.y0 + 178; width: 384; height: 8; radius: 4; color: Theme.border
                            Rectangle { width: parent.width * Math.max(0, Math.min(100, root.progress)) / 100; height: 8; radius: 4; color: Theme.gold } }
                Text { visible: parent.parent.done && root.countdown > 0; x: 512 - 160; y: parent.y0 + 174; width: 320; height: 18; horizontalAlignment: Text.AlignHCenter; text: "Rebooting in " + root.countdown + "s…"; color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 12 }
                BigButton { visible: parent.parent.err; x: 512 - 60; y: parent.y0 + 166; width: 120; height: 40; color: Theme.gold; label: "Retry"; onClicked: { root.state = "idle"; root.stepTo(0) } }
            }
            // welcome
            Item {
                visible: !parent.busy && root.step === 0
                anchors.fill: parent
                readonly property real y0: 300 - (80 + 24 + 36 + 12 + 48 + 32 + 46 + 24 + 18) / 2
                Hero { x: 512 - 40; y: parent.y0; side: 80; iconPx: 40 }
                Text { y: parent.y0 + 104; width: parent.width; height: 36; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; text: "Install Osmium Sound"; color: Theme.white; font.family: Theme.font; font.pixelSize: 30; font.bold: true }
                Text { x: 512 - 224; y: parent.y0 + 152; width: 448; height: 48; wrapMode: Text.Wrap; maximumLineCount: 2; horizontalAlignment: Text.AlignHCenter; text: "This will install Osmium Sound onto this computer's disk. All data on the chosen disk will be erased."; color: Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 15 }
                BigButton { x: 512 - 105; y: parent.y0 + 232; width: 210; color: Theme.gold; label: "Choose disk"; trail: "chevron-right"; onClicked: root.stepTo(1) }
                Text { x: 512 - 240; y: parent.y0 + 302; width: 480; height: 18; horizontalAlignment: Text.AlignHCenter; text: "Or scan the QR code (top right) to use your phone instead"; color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 12 }
            }
            // scelta del disco
            Item {
                visible: !parent.busy && root.step === 1
                anchors.fill: parent
                readonly property int rows: root.disksLoading || root.disks.length === 0 ? 1 : root.disks.length
                readonly property real listH: root.disksLoading || root.disks.length === 0 ? 80 : rows * 62 + (rows - 1) * 12
                readonly property real y0: 48 + (600 - 48 - 56) / 2 - (30 + 4 + 20 + 32 + listH) / 2
                Text { y: parent.y0; width: parent.width; height: 30; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; text: "Choose the installation disk"; color: Theme.white; font.family: Theme.font; font.pixelSize: 24; font.bold: true }
                Text { y: parent.y0 + 34; width: parent.width; height: 20; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; text: "The selected disk will be wiped and fully replaced by Osmium Sound."; color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 13 }
                Column {
                    visible: root.disksLoading || root.disks.length === 0
                    y: parent.y0 + 86; width: parent.width; spacing: 10
                    Text { width: parent.width; height: 24; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; text: root.disksLoading ? "Looking for disks…" : (root.disksErr || "No disks available."); color: Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 13 }
                    Spinner { visible: root.disksLoading; active: root.active && root.mode === 2 && root.step === 1; anchors.horizontalCenter: parent.horizontalCenter; radius: 12; thickness: 3 }
                    Rectangle { visible: !root.disksLoading; anchors.horizontalCenter: parent.horizontalCenter; width: 140; height: 34; radius: 12; color: rfTap.mix(Theme.surface, Theme.light)
                                Text { anchors.centerIn: parent; text: "Refresh list"; color: Theme.white; font.family: Theme.font; font.pixelSize: 13 }
                                Tap { id: rfTap; onClicked: root.readDisks() } }
                }
                Column {
                    visible: !root.disksLoading && root.disks.length > 0
                    x: 512 - 256; y: parent.y0 + 86; spacing: 12
                    Repeater {
                        model: root.disks
                        Rectangle {
                            required property var modelData
                            required property int index
                            width: 512; height: 62; radius: 16; color: dkTap.mix(Theme.surface, Theme.light); border.width: 1; border.color: Theme.border
                            Icon { x: 20; anchors.verticalCenter: parent.verticalCenter; name: "hard-drive"; size: 28; color: Theme.gold }
                            Text { x: 64; y: 13; height: 20; width: parent.width - 104; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; text: modelData.model || modelData.path; color: Theme.white; font.family: Theme.font; font.pixelSize: 15 }
                            Text { x: 64; y: 33; height: 18; width: parent.width - 104; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; text: modelData.path + " · " + root.fmtSize(modelData.size) + (modelData.transport ? " · " + modelData.transport : ""); color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 12 }
                            Icon { x: parent.width - 29; anchors.verticalCenter: parent.verticalCenter; name: "chevron-right"; size: 18; color: Theme.silverA(0.4) }
                            Tap { id: dkTap; onClicked: { root.sel = index; root.stepTo(2) } }
                        }
                    }
                }
            }
            // conferma
            Item {
                visible: !parent.busy && root.step === 2 && root.sel >= 0
                anchors.fill: parent
                readonly property real y0: 48 + (600 - 48 - 56) / 2 - (40 + 16 + 32 + 16 + 92 + 24 + 46) / 2
                readonly property var dk: root.sel >= 0 && root.sel < root.disks.length ? root.disks[root.sel] : { path: "", model: "" }
                Icon { x: 512 - 20; y: parent.y0; name: "alert-circle"; size: 40; color: "#fbbf24" }
                Text { y: parent.y0 + 56; width: parent.width; height: 32; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; text: "Confirm installation?"; color: Theme.white; font.family: Theme.font; font.pixelSize: 24; font.bold: true }
                Rectangle { x: 512 - 256; y: parent.y0 + 104; width: 512; height: 92; radius: 16; color: Qt.rgba(0x78/255, 0x35/255, 0x0f/255, 0.1); border.width: 1; border.color: Qt.rgba(0xf5/255, 0x9e/255, 0x0b/255, 0.3)
                            Text { x: 20; y: 18; width: parent.width - 40; height: 56; wrapMode: Text.Wrap; maximumLineCount: 3; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                                   text: "ALL DATA on " + (parent.parent.dk.model || parent.parent.dk.path) + " (" + parent.parent.dk.path + ") will be permanently erased. This cannot be undone."; color: "#fde68a"; font.family: Theme.font; font.pixelSize: 13 } }
                BigButton { x: 512 - 256; y: parent.y0 + 220; width: 512; color: "#d97706"; fg: Theme.white; label: "Erase and install"
                            onClicked: { if (root.dry) { root.msg = "Forced preview — install not started."; return }
                                         Api.post(Api.apiBase + "/install/start", { device: parent.dk.path }); root.state = "running"; root.progress = 0 } }
                Text { visible: root.dry && root.msg !== ""; y: parent.y0 + 274; width: parent.width; height: 20; horizontalAlignment: Text.AlignHCenter; text: root.msg; color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 12 }
            }
        }
    }
}
