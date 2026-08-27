// Le righe delle Impostazioni (draw_row in screen_settings.c): un elenco di
// oggetti {type, label, ...} costruito da SettingsTab, reso da un componente
// per tipo. Le fasce a fisarmonica e i riquadri scuri contengono a loro volta
// un elenco di righe (children): il componente si annida.
import QtQuick
import Hifi
import Hifi.Ui

Column {
    id: root
    property var rows: []
    property int level: 0
    width: parent ? parent.width : 0

    readonly property var ctl: Ui.settings

    function gapAfter(r) {
        switch (r.type) {
        case "option": case "info": case "label": case "src": case "alarm": case "grid": return r.gap !== undefined ? r.gap : 8
        case "dir": return 4
        case "band": return 8
        case "sep": return 16
        default: return r.gap !== undefined ? r.gap : 16
        }
    }
    function btnBg(style, dim) {
        var c
        switch (style) {
        case "gold": c = Theme.gold; break
        case "orange": c = "#ea580c"; break
        case "red": c = "#dc2626"; break
        case "dark": c = Theme.dark; break
        case "darkred": c = Qt.rgba(0x7f/255, 0x1d/255, 0x1d/255, 0.4); break
        case "ghost": c = Qt.rgba(0, 0, 0, 0); break
        case "amber": c = "#d97706"; break
        case "goldsoft": c = Theme.goldA(0.2); break
        default: c = Theme.accent
        }
        c = Qt.color(c)
        if (dim) c = Qt.rgba(c.r, c.g, c.b, c.a * 0.4)
        return c
    }
    function btnFg(style) {
        switch (style) {
        case "gold": return Theme.black
        case "darkred": return Theme.red300
        case "goldsoft": case "ghost": return Theme.gold
        default: return Theme.white
        }
    }

    Repeater {
        model: root.rows
        Item {
            id: slot
            required property var modelData
            required property int index
            width: root.width
            height: ld.height + (index < root.rows.length - 1 ? root.gapAfter(modelData) : 0)
            Loader {
                id: ld
                width: parent.width
                sourceComponent: {
                    switch (slot.modelData.type) {
                    case "help": return cHelp
                    case "label": return cLabel
                    case "sep": return cSep
                    case "note": return cNote
                    case "info": return cInfo
                    case "toggle": return cToggle
                    case "option": return cOption
                    case "action": return cAction
                    case "input": return cInput
                    case "qr": return cQr
                    case "code": return cCode
                    case "confirm": return cConfirm
                    case "slider": return cSlider
                    case "alarm": return cAlarm
                    case "band": return cBand
                    case "src": return cSrc
                    case "dir": return cDir
                    case "mini": return cMini
                    case "check": return cCheck
                    case "grid": return cGrid
                    case "box": return cBox
                    }
                    return cHelp
                }
                onLoaded: item.row = slot.modelData
            }
        }
    }

    // ─── pulsantino in linea (text-xs py-1.5 px-3, oppure quadrato 32) ─────
    component MiniButton: Rectangle {
        property var m: ({})
        property var row: ({})
        width: m.icon ? 32 : miniText.implicitWidth + 24
        height: m.icon ? 32 : 28
        radius: 6
        color: mTap.mix(root.btnBg(m.style, m.dim), Theme.light)
        Icon { visible: !!m.icon; anchors.centerIn: parent; name: m.icon || ""; size: 16; color: m.dim ? Qt.rgba(root.btnFg(m.style).r, root.btnFg(m.style).g, root.btnFg(m.style).b, 0.4) : root.btnFg(m.style) }
        Text { id: miniText; visible: !m.icon; anchors.centerIn: parent; text: m.label || ""; font.family: Theme.font; font.pixelSize: 12
               color: m.dim ? Qt.rgba(root.btnFg(m.style).r, root.btnFg(m.style).g, root.btnFg(m.style).b, 0.4) : root.btnFg(m.style) }
        Tap { id: mTap; enabled: !m.dim; grow: 4; onClicked: root.ctl.activate(row, m.act, m.arg) }
    }
    component MiniRow: Row {
        property var row: ({})
        property bool packRight: false
        spacing: 8
        Repeater { model: row.mini || []; MiniButton { required property var modelData; m: modelData; row: parent.row } }
    }
    component Switch_: Rectangle {
        property bool on: false
        property bool dim: false
        width: 44; height: 24; radius: 12
        color: dim ? Qt.rgba(on ? Theme.gold.r : Theme.accent.r, on ? Theme.gold.g : Theme.accent.g, on ? Theme.gold.b : Theme.accent.b, 0.55) : (on ? Theme.gold : Theme.accent)
        Rectangle { x: on ? 24 : 4; y: 4; width: 16; height: 16; radius: 8; color: Theme.white; Behavior on x { NumberAnimation { duration: 120 } } }
    }

    // ─── i tipi di riga ────────────────────────────────────────────────────
    Component { id: cHelp
        Text {
            property var row: ({})
            width: parent.width; wrapMode: Text.Wrap
            text: row.label || ""; color: row.tone === "amber" ? "#fde68a" : Theme.silver
            font.family: Theme.font; font.pixelSize: row.px || 14
            lineHeight: (row.px || 14) + 6; lineHeightMode: Text.FixedHeight
            horizontalAlignment: row.center ? Text.AlignHCenter : Text.AlignLeft
        }
    }
    Component { id: cLabel
        Text {
            property var row: ({})
            width: parent.width; height: row.px === 12 ? 16 : 24; verticalAlignment: Text.AlignVCenter
            text: row.dim ? (row.label || "").toUpperCase() : (row.label || "")
            color: row.dim ? Theme.silverA(0.6) : Theme.white
            font.family: Theme.font; font.pixelSize: row.px || 16; elide: Text.ElideRight
        }
    }
    Component { id: cSep
        Rectangle { property var row: ({}); width: parent.width; height: 1; color: Qt.rgba(0x3a/255, 0x3a/255, 0x3a/255, 0.4) }
    }
    Component { id: cNote
        Rectangle {
            property var row: ({})
            readonly property color fg: row.tone === "red" ? Theme.red300 : row.tone === "amber" ? "#fcd34d" : row.tone === "gold" ? Theme.gold : Theme.silver
            width: parent.width; height: noteText.height + 24; radius: 8
            color: row.tone === "red" ? Qt.rgba(0x7f/255, 0x1d/255, 0x1d/255, 0.2) : row.tone === "amber" ? Qt.rgba(0x78/255, 0x35/255, 0x0f/255, 0.2) : row.tone === "gold" ? Theme.goldA(0.2) : Theme.dark
            border.width: row.tone === "dark" || !row.tone ? 0 : 1
            border.color: row.tone === "red" ? Theme.redA(0.3) : row.tone === "amber" ? Qt.rgba(0xf5/255, 0x9e/255, 0x0b/255, 0.3) : Theme.goldA(0.4)
            Icon { visible: !!row.icon; x: 12; y: 12; name: row.icon || ""; size: 14; color: parent.fg }
            Text {
                id: noteText
                x: row.icon ? 34 : 12; y: 12; width: parent.width - x - 12; wrapMode: Text.Wrap
                text: row.label || ""; color: parent.fg; font.family: Theme.font; font.pixelSize: row.px || 14
                lineHeight: (row.px || 14) + 6; lineHeightMode: Text.FixedHeight
                horizontalAlignment: row.center ? Text.AlignHCenter : Text.AlignLeft
            }
        }
    }
    Component { id: cInfo
        Rectangle {
            id: info
            property var row: ({})
            readonly property bool seg: row.style === "seg"
            readonly property real pad: seg ? 0 : 16
            width: parent.width; height: row.hh || (seg ? 36 : 44); radius: 8
            color: seg ? "transparent" : Theme.dark
            readonly property real ty: row.extra && !seg ? 12 : 0
            readonly property real lineH: row.extra && !seg ? 20 : height
            MiniRow { id: mr; row: info.row; anchors.right: parent.right; anchors.rightMargin: info.seg ? 0 : 12; anchors.verticalCenter: parent.verticalCenter }
            readonly property real rightEdge: (info.row.mini && info.row.mini.length) ? mr.x - 12 : width - pad
            Text {
                x: info.pad; y: info.ty; width: (info.rightEdge - info.pad) / 2; height: info.lineH; verticalAlignment: Text.AlignVCenter
                text: row.label || ""; elide: Text.ElideRight
                color: row.tone === "gold" ? Theme.white : Theme.silver; font.family: Theme.font; font.pixelSize: row.px || 14
            }
            Text {                                        // "-> ultima" (aggiornamenti)
                id: extraSeg
                visible: !!row.extra && info.seg
                anchors.right: parent.right; y: info.ty; height: info.lineH; verticalAlignment: Text.AlignVCenter
                text: row.extra || ""; color: Theme.gold; font.family: Theme.mono; font.pixelSize: row.px || 14
            }
            Text {
                id: valText
                x: info.pad + (info.rightEdge - info.pad) / 2; y: info.ty; height: info.lineH; verticalAlignment: Text.AlignVCenter
                width: info.rightEdge - x - (extraSeg.visible ? extraSeg.width + 8 : 0)
                horizontalAlignment: Text.AlignRight; elide: Text.ElideLeft
                text: row.value || ""; color: (row.style === "row" || row.tone === "gold") ? Theme.gold : Theme.white
                font.family: row.mono ? Theme.mono : Theme.font; font.pixelSize: row.px || 14
            }
            Icon { visible: !!row.icon; x: valText.x + valText.width - Math.min(valText.width, valText.implicitWidth) - 18; y: info.ty + info.lineH / 2 - 7; name: row.icon || ""; size: 14; color: Theme.gold }
            Text {
                visible: !!row.extra && !info.seg
                x: info.pad; y: 34; width: info.rightEdge - info.pad; height: 18; verticalAlignment: Text.AlignVCenter
                text: row.extra || ""; elide: Text.ElideRight
                color: row.danger ? Theme.red300 : Theme.silverA(0.6); font.family: Theme.font; font.pixelSize: 12
            }
            Tap { enabled: !!info.row.act; onClicked: root.ctl.activate(info.row, info.row.act) }
        }
    }
    Component { id: cToggle
        Rectangle {
            id: tg
            property var row: ({})
            width: parent.width; radius: 8
            height: row.value ? 12 + 20 + 2 + subText.height + 12 : 48
            color: tTap.mix(Theme.dark, Theme.light)
            readonly property real lx: 16 + (row.icon ? 24 : 0)
            Icon { visible: !!row.icon; x: 16; anchors.verticalCenter: parent.verticalCenter; name: row.icon || ""; size: 16; color: Theme.gold }
            Text {
                x: tg.lx; y: row.value ? 12 : 0; height: row.value ? 20 : parent.height; verticalAlignment: Text.AlignVCenter
                width: parent.width - x - 16 - 44 - 16
                text: row.label || ""; elide: Text.ElideRight; color: Theme.white; font.family: Theme.font; font.pixelSize: 14
            }
            Text {
                id: subText
                visible: !!row.value
                x: tg.lx; y: 34; width: parent.width - x - 16 - 44 - 16; wrapMode: Text.Wrap
                text: row.value || ""; color: Theme.silver; font.family: Theme.font; font.pixelSize: 12; lineHeight: 16; lineHeightMode: Text.FixedHeight
            }
            Switch_ { anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter; on: !!row.on; dim: !!row.dim }
            Tap { id: tTap; enabled: !row.dim; onClicked: root.ctl.activate(tg.row, tg.row.act) }
        }
    }
    Component { id: cOption
        Item {
            id: op
            property var row: ({})
            readonly property bool fill: !row.style || row.style === "fill" || row.style === "seg" || row.style === "row"
            readonly property bool sel: !!row.sel
            width: parent.width
            height: row.hh || (row.value && row.style !== "row" ? 60 : 44)
            Rectangle {
                anchors.fill: parent; radius: 8
                scale: oTap.tapScale
                color: {
                    var bg = op.fill ? (op.sel ? Theme.gold : (op.row.style === "seg" || op.row.style === "row") ? Theme.surface : Theme.light) : Theme.dark
                    return op.fill && !op.sel ? oTap.mix(bg, Theme.accent) : bg
                }
                border.width: op.row.style === "border" && op.sel ? 1 : 0; border.color: Theme.gold
                readonly property color fg: {
                    var c = op.fill ? (op.sel ? Theme.black : Theme.white) : (op.sel ? Theme.gold : Theme.white)
                    return op.row.dim ? Qt.rgba(c.r, c.g, c.b, 0.4) : c
                }
                // "select": chevron a destra; scelta riempita: spunta (Check 18)
                Icon { visible: !!op.row.icon && op.row.style === "border"; x: parent.width - 28; anchors.verticalCenter: parent.verticalCenter; name: op.row.icon || ""; size: 16; color: Theme.silver }
                Icon { visible: !!op.row.icon && op.row.style !== "border" && op.sel; x: parent.width - 33; anchors.verticalCenter: parent.verticalCenter; name: op.row.icon || ""; size: 18; color: parent.fg }
                Icon { visible: op.row.style === "border" && op.sel && !op.row.icon; x: parent.width - 32; anchors.verticalCenter: parent.verticalCenter; name: "check-circle-2"; size: 16; color: Theme.gold }
                // testo centrato (scelte affiancate) oppure etichetta + sotto-linea
                Text {
                    visible: !!op.row.center && !op.row.value
                    anchors.centerIn: parent; width: parent.width - 16
                    horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight
                    text: op.row.label || ""; color: parent.fg; font.family: op.row.mono ? Theme.mono : Theme.font; font.pixelSize: op.row.px || 14
                }
                Text {
                    visible: !(!!op.row.center && !op.row.value)
                    x: 16; width: parent.width - 16 - 40 - (op.row.extra ? 100 : 0)
                    y: op.row.value && op.row.style !== "row" ? 12 : 0
                    height: op.row.value && op.row.style !== "row" ? 20 : parent.height; verticalAlignment: Text.AlignVCenter
                    text: op.row.label || ""; elide: Text.ElideRight; color: parent.fg
                    font.family: Theme.font; font.pixelSize: 14; font.bold: !!op.row.bold || (op.sel && op.row.style === "row")
                }
                Text {
                    visible: !!op.row.value && op.row.style !== "row"
                    x: 16; y: 32; width: parent.width - 16 - 40; height: 18; verticalAlignment: Text.AlignVCenter
                    text: op.row.value || ""; elide: Text.ElideRight
                    color: op.fill && op.sel ? Qt.rgba(0, 0, 0, 0.75) : Theme.silver
                    font.family: op.row.mono ? Theme.mono : Theme.font; font.pixelSize: 12
                }
                Text {
                    visible: !!op.row.extra
                    anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter
                    text: op.row.extra || ""; color: op.fill && op.sel ? Qt.rgba(0, 0, 0, 0.7) : Theme.silverA(0.6)
                    font.family: Theme.mono; font.pixelSize: 12
                }
            }
            Tap { id: oTap; tap: 0.95; enabled: !op.row.dim; onClicked: root.ctl.activate(op.row, op.row.act) }
        }
    }
    Component { id: cAction
        Item {
            id: ac
            property var row: ({})
            width: parent.width; height: row.hh || 44
            readonly property real px: row.px || ((row.hh || 0) >= 56 ? 16 : 14)
            readonly property color fg: root.btnFg(row.style)
            Rectangle {
                anchors.fill: parent; radius: 8
                scale: aTap.tapScale
                visible: ac.row.style !== "ghost"
                color: aTap.mix(root.btnBg(ac.row.style, ac.row.dim), Theme.light)
                border.width: ac.row.style === "darkred" ? 1 : 0; border.color: Theme.redA(0.4)
            }
            Row {
                anchors.centerIn: parent; spacing: 8
                Icon { visible: !!ac.row.icon; name: ac.row.icon || ""; size: (ac.row.hh || 0) >= 56 ? 20 : 18; color: ac.fg; anchors.verticalCenter: parent.verticalCenter }
                Text { visible: !!ac.row.label; text: ac.row.label || ""; color: ac.fg; font.family: Theme.font; font.pixelSize: ac.px; font.bold: !!ac.row.bold; anchors.verticalCenter: parent.verticalCenter }
            }
            Tap { id: aTap; tap: 0.95; enabled: !ac.row.dim; onClicked: root.ctl.activate(ac.row, ac.row.act) }
        }
    }
    Component { id: cInput
        TextField_ {
            id: inp
            property var row: ({})
            width: parent.width; height: row.hh || 46
            color: Theme.surface; restBorder: Theme.accent
            text: row.value || ""; placeholder: row.label || ""; password: !!row.on
            onTextEdited: (t) => root.ctl.fieldSet(inp.row, t)
            onAccepted: root.ctl.fieldCommit(inp.row)
        }
    }
    Component { id: cQr
        Item {
            property var row: ({})
            width: parent.width; height: 232 + (row.label ? 26 : 0)
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter; width: 232; height: 232; radius: 12; color: Theme.white
                QrCode { anchors.centerIn: parent; width: 200; height: 200; text: parent.parent.row.value || "" }
            }
            Text { y: 232 + 16; width: parent.width; horizontalAlignment: Text.AlignHCenter; text: parent.row.label || ""; color: Theme.silver; font.family: Theme.font; font.pixelSize: 12 }
        }
    }
    Component { id: cCode
        Text {
            property var row: ({})
            width: parent.width; height: 22; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
            text: row.label || ""; color: Theme.gold; font.family: Theme.mono; font.pixelSize: 14; elide: Text.ElideMiddle
        }
    }
    Component { id: cConfirm
        Rectangle {
            id: cf
            property var row: ({})
            width: parent.width; height: 16 + prompt.height + 12 + 36 + 16; radius: 8
            color: Qt.rgba(0x78/255, 0x35/255, 0x0f/255, 0.1); border.width: 1; border.color: Qt.rgba(0xf5/255, 0x9e/255, 0x0b/255, 0.3)
            Text { id: prompt; x: 16; y: 16; width: parent.width - 32; wrapMode: Text.Wrap; text: cf.row.label || ""; color: "#fde68a"; font.family: Theme.font; font.pixelSize: 14; lineHeight: 20; lineHeightMode: Text.FixedHeight }
            Row {
                x: 16; y: parent.height - 16 - 36; spacing: 12
                Rectangle {
                    width: (cf.width - 32 - 12) / 2; height: 36; radius: 8; color: ccTap.mix(Theme.dark, Theme.light)
                    Text { anchors.centerIn: parent; text: cf.row.arg || Tr.t("common.cancel"); color: Theme.white; font.family: Theme.font; font.pixelSize: 14 }
                    Tap { id: ccTap; onClicked: root.ctl.activate(cf.row, cf.row.act2 || "confirm_cancel") }
                }
                Rectangle {
                    width: (cf.width - 32 - 12) / 2; height: 36; radius: 8; color: coTap.mix("#d97706", "#f59e0b")
                    Text { anchors.centerIn: parent; text: cf.row.value || ""; color: Theme.white; font.family: Theme.font; font.pixelSize: 14; font.bold: true }
                    Tap { id: coTap; onClicked: root.ctl.activate(cf.row, cf.row.act) }
                }
            }
        }
    }
    Component { id: cSlider
        Item {
            id: sl
            property var row: ({})
            property int val: row.sval || 1
            width: parent.width; height: 24
            readonly property real f: (val - row.smin) / Math.max(1, row.smax - row.smin)
            Rectangle { x: 0; y: 9; width: parent.width; height: 6; radius: 3; color: Theme.accent }
            Rectangle { x: 0; y: 9; width: parent.width * sl.f; height: 6; radius: 3; color: Theme.gold }
            Rectangle { x: parent.width * sl.f - 8; y: 4; width: 16; height: 16; radius: 8; color: Theme.gold }
            MouseArea {
                anchors.fill: parent; anchors.margins: -12
                function at(m) { var f = Math.max(0, Math.min(1, (m.x - 12) / sl.width)); sl.val = sl.row.smin + Math.round(f * (sl.row.smax - sl.row.smin)) }
                onPressed: (m) => at(m)
                onPositionChanged: (m) => { if (pressed) at(m) }
                onReleased: root.ctl.activate(sl.row, sl.row.act, String(sl.val))
            }
        }
    }
    Component { id: cAlarm
        Rectangle {
            id: al
            property var row: ({})
            width: parent.width; height: row.hh || 48; radius: 8; color: alTap.mix(Theme.dark, Theme.light)
            Icon { x: 16; anchors.verticalCenter: parent.verticalCenter; name: "alarm-clock"; size: 18; color: al.row.on ? Theme.gold : Theme.silverA(0.4) }
            Text { x: 46; anchors.verticalCenter: parent.verticalCenter; text: al.row.label || ""; color: al.row.on ? Theme.white : Theme.silverA(0.5); font.family: Theme.mono; font.pixelSize: 18 }
            Switch_ { x: parent.width - 16 - 28 - 44; anchors.verticalCenter: parent.verticalCenter; on: !!al.row.on }
            Tap { id: alTap; onClicked: root.ctl.activate(al.row, al.row.act) }
            Item {
                x: parent.width - 28; width: 28; height: parent.height
                Icon { anchors.centerIn: parent; name: "trash-2"; size: 16; color: Theme.silverA(0.5) }
                Tap { onClicked: root.ctl.activate(al.row, al.row.act2) }
            }
        }
    }
    Component { id: cBand
        Rectangle {
            id: bd
            property var row: ({})
            readonly property bool nested: row.style === 1 || row.style === "nested"
            readonly property bool open: !!row.on
            readonly property real pad: nested ? 12 : 16
            readonly property real headH: nested ? 54 : (row.value ? 74 : 58)
            width: parent.width
            height: headH + (open && row.children && row.children.length ? (nested ? 12 : 16) + inner.height + (nested ? 12 : 16) : 0)
            radius: nested ? 8 : 12
            color: Qt.rgba(0x0f/255, 0x0f/255, 0x0f/255, nested ? 0.4 : 0.6)
            border.width: 1; border.color: Qt.rgba(0x3a/255, 0x3a/255, 0x3a/255, nested ? 0.4 : 0.6)
            Rectangle {                                    // intestazione (hover)
                x: 0; y: 0; width: parent.width; height: bd.headH; radius: bd.radius
                color: bTap.mix(Qt.rgba(0, 0, 0, 0), Qt.rgba(0x2a/255, 0x2a/255, 0x2a/255, 0.35))
                Rectangle { x: bd.pad; y: (bd.headH - (bd.nested ? 28 : 36)) / 2; width: bd.nested ? 28 : 36; height: width; radius: bd.nested ? 6 : 8; color: Theme.goldA(0.2)
                            Icon { anchors.centerIn: parent; name: bd.row.icon || ""; size: bd.nested ? 16 : 20; color: Theme.gold } }
                Text {
                    x: bd.pad + (bd.nested ? 28 : 36) + 12; width: parent.width - x - bd.pad - 32
                    y: bd.row.value ? bd.pad : 0; height: bd.row.value ? 24 : parent.height; verticalAlignment: Text.AlignVCenter
                    text: bd.row.label || ""; elide: Text.ElideRight; color: Theme.white; font.family: Theme.font; font.pixelSize: bd.nested ? 14 : 16
                }
                Text {
                    visible: !!bd.row.value
                    x: bd.pad + (bd.nested ? 28 : 36) + 12; width: parent.width - x - bd.pad - 32; y: bd.pad + 24; height: 16; verticalAlignment: Text.AlignVCenter
                    text: bd.row.value || ""; elide: Text.ElideRight; color: Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 12
                }
                Icon { x: parent.width - bd.pad - (bd.nested ? 16 : 20); anchors.verticalCenter: parent.verticalCenter; name: bd.open ? "chevron-down" : "chevron-right"; size: bd.nested ? 16 : 20; color: Theme.silver }
                Tap { id: bTap; onClicked: root.ctl.activate(bd.row, bd.row.act) }
            }
            Rectangle { visible: bd.open && bd.row.children && bd.row.children.length > 0; x: 0; y: bd.headH; width: parent.width; height: 1; color: Qt.rgba(0x3a/255, 0x3a/255, 0x3a/255, 0.4) }
            // annidamento tramite Loader: il tipo non puo' riferirsi a se stesso
            Loader {
                id: inner
                visible: bd.open
                x: bd.pad; y: bd.headH + (bd.nested ? 12 : 16); width: bd.width - 2 * bd.pad
                source: bd.open && bd.row.children && bd.row.children.length ? "SettingsRows.qml" : ""
                // 🚨 legame, non assegnazione: il contenuto annidato arriva DOPO
                // che il Loader ha caricato (la riga viene assegnata al delegato
                // solo al termine), e senza binding restava vuoto per sempre
                onLoaded: { item.level = root.level + 1; item.rows = Qt.binding(function() { return bd.row.children || [] }) }
            }
        }
    }
    Component { id: cSrc
        Rectangle {
            id: sr
            property var row: ({})
            width: parent.width; height: row.hh || (row.sub2 ? 76 : 60); radius: 8; color: Theme.dark
            MiniRow { id: smr; row: sr.row; anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter }
            readonly property real rgt: (sr.row.mini && sr.row.mini.length) ? smr.x - 12 : width - 12
            Row {
                x: 12; y: sr.row.value || sr.row.sub2 ? 12 : 0; height: sr.row.value || sr.row.sub2 ? 20 : sr.height; spacing: 8
                Text { id: nameText; anchors.verticalCenter: parent.verticalCenter; text: sr.row.label || ""; elide: Text.ElideRight
                       width: Math.min(implicitWidth, sr.rgt - 12 - (tagText.visible ? tagText.width + 8 : 0)); color: Theme.white; font.family: Theme.font; font.pixelSize: sr.row.px || 14 }
                Text { id: tagText; visible: !!sr.row.extra; anchors.verticalCenter: parent.verticalCenter; anchors.verticalCenterOffset: 1; text: (sr.row.extra || "").toUpperCase(); color: Theme.goldA(0.8); font.family: Theme.font; font.pixelSize: 10; font.letterSpacing: 1 }
            }
            Text { x: 12; y: 32; width: sr.rgt - 12; height: 16; verticalAlignment: Text.AlignVCenter; visible: !!sr.row.value; text: sr.row.value || ""; elide: Text.ElideMiddle; color: sr.row.danger ? Theme.red300 : Theme.silverA(0.7); font.family: Theme.font; font.pixelSize: 12 }
            Text { x: 12; y: 48; width: sr.rgt - 12; height: 16; verticalAlignment: Text.AlignVCenter; visible: !!sr.row.sub2; text: sr.row.sub2 || ""; elide: Text.ElideRight; color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 12 }
        }
    }
    Component { id: cDir
        Rectangle {
            id: dr
            property var row: ({})
            width: parent.width; height: 32; radius: 6; color: dTap.mix(Qt.rgba(0x3a/255, 0x3a/255, 0x3a/255, 0.4), Theme.accent)
            Text { x: 12; width: parent.width - 24; anchors.verticalCenter: parent.verticalCenter; text: dr.row.label || ""; elide: Text.ElideRight; color: Theme.white; font.family: Theme.font; font.pixelSize: 14 }
            Tap { id: dTap; onClicked: root.ctl.activate(dr.row, dr.row.act, dr.row.arg) }
        }
    }
    Component { id: cMini
        Item {
            property var row: ({})
            width: parent.width; height: 28
            MiniRow { row: parent.row; anchors.verticalCenter: parent.verticalCenter }
        }
    }
    Component { id: cCheck
        Item {
            id: ck
            property var row: ({})
            width: parent.width; height: Math.max(20, ckText.height)
            Rectangle {
                x: 0; y: 2; width: 16; height: 16; radius: 3
                color: ck.row.on ? Theme.gold : Theme.dark; border.width: ck.row.on ? 0 : 1; border.color: Theme.silverA(0.5)
                Icon { visible: ck.row.on; anchors.centerIn: parent; name: "check"; size: 12; color: Theme.black }
            }
            Text { id: ckText; x: 24; width: parent.width - 24; wrapMode: Text.Wrap; text: ck.row.label || ""; color: Theme.silver; font.family: Theme.font; font.pixelSize: 14; lineHeight: 20; lineHeightMode: Text.FixedHeight }
            Tap { onClicked: root.ctl.activate(ck.row, ck.row.act) }
        }
    }
    // scelte affiancate: le celle sulla stessa riga, alte quanto la piu' alta
    Component { id: cGrid
        Item {
            id: gr
            property var row: ({})
            width: parent.width
            height: gridRow.childrenRect.height
            readonly property int cols: row.cols || 2
            readonly property real cw: (width - 8 * (cols - 1)) / cols
            Row {
                id: gridRow
                spacing: 8
                Repeater {
                    model: gr.row.cells || []
                    Item {
                        required property var modelData
                        required property int index
                        readonly property int span: modelData.span || 1
                        width: (index + span >= gr.cols) ? gr.width - x : gr.cw * span + 8 * (span - 1)
                        height: cellRows.height
                        Loader {
                            id: cellRows; width: parent.width; source: "SettingsRows.qml"
                            onLoaded: { item.level = root.level; item.rows = Qt.binding(function() { return [modelData] }) }
                        }
                    }
                }
            }
        }
    }
    // riquadro scuro attorno a un gruppo di righe (bg-hifi-dark p-3)
    Component { id: cBox
        Rectangle {
            id: bx
            property var row: ({})
            width: parent.width; height: boxRows.height + 24; radius: 8; color: Theme.dark
            Loader {
                id: boxRows; x: 12; y: 12; width: parent.width - 24; source: "SettingsRows.qml"
                onLoaded: { item.level = root.level; item.rows = Qt.binding(function() { return bx.row.children || [] }) }
            }
        }
    }
}
