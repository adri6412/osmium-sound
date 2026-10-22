// The signal path: source → Lyrion → player → DAC, each step marked
// untouched (green), converted on purpose (gold) or changed (orange), and a
// verdict at the bottom. What the DAC is fed comes from the kernel via
// /signal_path (hifi_signal_path.py), polled while the dialog is open: it
// follows the next track, a pause, a switch between PCM and DSD.
import QtQuick
import Hifi.Ui

Rectangle {
    id: root
    signal done()
    signal openSetting()                 // the BitPerfect setting in Settings → Playback
    property bool open: false
    property var d: null                 // the last answer
    property bool failed: false

    width: 480
    height: body.implicitHeight + 40
    radius: 16; color: Theme.panel; border.width: 1; border.color: Theme.border
    BoxShadow { z: -1; targetX: 0; targetY: 0; targetW: parent.width; targetH: parent.height; radius: 16; blur: 50; spread: -12; offsetY: 25; color: Theme.blackA(0.25) }   // shadow-2xl
    MouseArea { anchors.fill: parent }          // a tap on the dialog does not close it

    readonly property color cOk: Theme.emerald
    readonly property color cConv: Theme.gold
    readonly property color cWarn: "#fb923c"    // orange-400
    readonly property color cIdle: Theme.silverA(0.45)
    readonly property color cPlain: Theme.silverA(0.7)
    function tone(t) { return t === "ok" ? cOk : t === "conv" ? cConv : t === "warn" ? cWarn : t === "plain" ? cPlain : cIdle }

    // ─── data ─────────────────────────────────────────────────────────────
    function load() {
        var q = "player=" + encodeURIComponent(Player.playerId)
            + "&type=" + encodeURIComponent(Player.type)
            + "&rate=" + Math.round(Player.sampleRate) + "&bits=" + Player.sampleSize
            + "&remote=" + (Player.remote ? 1 : 0)
            + "&rg=" + (Player.prefReplayGain !== "" && Player.prefReplayGain !== "0" ? 1 : 0)
            + "&xfade=" + (Player.prefTransitionType !== "" && Player.prefTransitionType !== "0" && Number(Player.prefTransitionDur) > 0 ? 1 : 0)
            + "&digvol=" + (Player.prefDigitalVol === "1" ? 1 : 0)
            + "&volume=" + Player.volume
        Api.get(Api.apiBase + "/signal_path?" + q, function(ok, r) {
            if (!root.open) return
            root.failed = !(ok && r && r.success)
            if (!root.failed) root.d = r
        }, 4000)
    }
    onOpenChanged: if (open) { d = null; failed = false; load() }
    Timer { interval: 1500; repeat: true; running: root.open; onTriggered: root.load() }

    // ─── words ────────────────────────────────────────────────────────────
    function t(k) { return Tr.t("player.signalPath." + k) }
    function sub(s, map) { for (var k in map) s = s.split("{" + k + "}").join(map[k]); return s }
    function num(x) { var s = String(x); return Tr.lang === "it" ? s.replace(".", ",") : s }
    function rate(r) {
        if (!r) return ""
        if (r >= 1000000) return num((r / 1000000).toFixed(1)) + " MHz"
        return num(Math.round(r / 100) / 10) + " kHz"
    }
    function dsdName(bitRate) {
        var n = Math.round(bitRate / (bitRate % 48000 === 0 ? 48000 : 44100))
        return n >= 32 ? "DSD" + n : "DSD"
    }
    readonly property var typeNames: ({ flc: "FLAC", alc: "ALAC", alcx: "ALAC", wvp: "WavPack", wvpx: "WavPack", aif: "AIFF",
                                        wav: "WAV", mp3: "MP3", aac: "AAC", mp4: "AAC", ogg: "Ogg Vorbis", ops: "Opus",
                                        wma: "WMA", wmal: "WMA Lossless", ape: "APE", mpc: "Musepack", dsf: "DSF", dff: "DFF" })

    // [{key, icon, label, value, details: [{text, tone}], tone}]
    readonly property var stages: build(d)
    function build(r) {
        if (!r) return []
        var s = r.source, ch = r.changes || [], out = []
        var has = function(c) { return ch.indexOf(c) >= 0 }
        var typeName = typeNames[s.type] || (s.type || "").toUpperCase()

        // source
        var sv = typeName
        if (s.dsd) sv += (sv ? " · " : "") + dsdName(s.rate)
        else {
            if (s.bits) sv += (sv ? " · " : "") + s.bits + " bit"
            if (s.rate) sv += (sv ? " · " : "") + rate(s.rate)
        }
        // lossless / lossy only when the codec is known; an unknown or empty
        // type (some radios) says nothing rather than claim "lossless"
        var sd = []
        if (s.quality === "lossless") sd.push({ text: t("lossless"), tone: "ok" })
        else if (s.quality === "lossy") sd.push({ text: t("lossy"), tone: "idle" })
        if (s.remote) sd.push({ text: t("stream"), tone: "idle" })
        out.push({ key: "source", icon: s.remote ? "radio" : "music", label: t("source"), value: sv || "—", details: sd })

        // Lyrion
        var ld = []
        if (has("replaygain")) ld.push({ text: t("replaygain"), tone: "warn" })
        if (has("crossfade")) ld.push({ text: t("crossfade"), tone: "warn" })
        if (has("resampled")) ld.push({ text: sub(t("resampled"), { rate: rate(r.hw ? r.hw.rate : r.player.max_rate) }), tone: "warn" })
        // PCM to DSD: in Lyrion when this device is the server; after the
        // player (its own step below) when the music comes from another one
        var p2d = r.player ? r.player.pcm2dsd : null
        var p2dText = p2d ? sub(t("pcmToDsd"), { dsd: p2d.mode.toUpperCase(), filter: p2d.filter.toUpperCase() }) : ""
        var p2dAfter = has("pcmToDsd") && p2d && p2d.state === "player"
        if (has("pcmToDsd") && !p2dAfter) ld.push({ text: p2dText, tone: "conv" })
        if (!ld.length) ld.push({ text: t("asIs"), tone: "ok" })
        ld.push({ text: r.lyrion.local ? t("lyrionHere") : sub(t("lyrionOn"), { host: r.lyrion.server }), tone: "idle" })
        out.push({ key: "lyrion", icon: "library", label: "Lyrion", value: "Lyrion Music Server", details: ld })

        // player
        if (!r.local) {
            out.push({ key: "player", icon: "speaker", label: t("player"), value: Player.playerName || "—",
                       details: [{ text: t("otherDevice"), tone: "idle" }] })
            return out
        }
        var p = r.player, pd = []
        if (has("volume")) pd.push({ text: sub(t("volumeDigital"), { n: Player.volume }), tone: "warn" })
        else if (p.volume === "hardware") pd.push({ text: t("volumeDac"), tone: "ok" })
        else if (p.dsd_out && Player.prefDigitalVol === "1" && Player.volume < 100) pd.push({ text: t("volumeDsd"), tone: "ok" })
        else pd.push({ text: t("volumeFull"), tone: "ok" })
        if (has("dsdToPcm")) pd.push({ text: t("dsdToPcm"), tone: "warn" })
        if (p.realtime) pd.push({ text: t("realtime"), tone: "ok" })
        out.push({ key: "player", icon: "audio-lines", label: r.zone ? sub(t("zone"), { name: r.zone }) : t("player"),
                   value: "squeezelite · " + p.name, details: pd })
        if (p2dAfter)
            out.push({ key: "convert", icon: "sparkles", label: t("conversion"), value: p2d.mode.toUpperCase(),
                       details: [{ text: p2dText, tone: "conv" }, { text: t("convertHere"), tone: "idle" }] })

        // DAC
        var h = r.hw, dd = [], dv = r.dac.name || r.dac.card || t("unknownDac")
        // green / gold when the whole path earns it; a change made upstream
        // is marked there, not on the DAC
        var good = r.verdict === "bitperfect" ? "ok" : r.verdict === "converted" ? "conv" : "plain"
        if (!h) dd.push({ text: t("idle"), tone: "idle" })
        else if (h.kind === "dsd") dd.push({ text: sub(t("hwNative"), { dsd: h.dsd, rate: rate(h.bit_rate) }), tone: good })
        else if (h.kind === "dop") dd.push({ text: sub(t("hwDop"), { dsd: h.dsd, rate: rate(h.rate) }), tone: good })
        else dd.push({ text: sub(t("hwPcm"), { bits: h.bits, rate: rate(h.rate) }), tone: good })
        if (r.dac.kind !== "unknown") dd.push({ text: t("conn." + r.dac.kind), tone: "idle" })
        out.push({ key: "dac", icon: r.dac.kind === "usb" ? "usb" : "speaker", label: "DAC", value: dv, details: dd })
        return out
    }
    // a step's colour: its most telling detail
    function stageTone(st) {
        var ts = st.details.map(function(x) { return x.tone })
        return ts.indexOf("warn") >= 0 ? "warn" : ts.indexOf("conv") >= 0 ? "conv" : ts.indexOf("ok") >= 0 ? "ok"
             : ts.indexOf("plain") >= 0 ? "plain" : "idle"
    }
    readonly property var verdict: {
        if (failed) return { tone: "idle", icon: "alert-circle", title: t("v.failed"), text: "" }
        if (!d) return { tone: "idle", icon: "clock", title: t("v.loading"), text: "" }
        var v = d.verdict
        if (v === "bitperfect") return { tone: "ok", icon: "check-circle-2", title: "Bit-perfect", text: t("v.bitperfect") }
        if (v === "converted") return { tone: "conv", icon: "sparkles", title: sub(t("v.convertedTitle"), { dsd: d.player.pcm2dsd.mode.toUpperCase() }), text: t("v.converted") }
        if (v === "processed") return { tone: "warn", icon: "alert-triangle", title: t("v.processedTitle"), text: t("v.processed") }
        if (v === "idle") return { tone: "idle", icon: "pause", title: t("v.idleTitle"), text: t("v.idle") }
        return { tone: "idle", icon: "info", title: t("v.unknownTitle"), text: t("v.unknown") }
    }

    // ─── drawing ──────────────────────────────────────────────────────────
    Column {
        id: body
        x: 20; y: 20; width: parent.width - 40
        Item {
            width: parent.width; height: 24
            Icon { anchors.verticalCenter: parent.verticalCenter; name: "audio-lines"; size: 16; color: Theme.gold }
            Text { x: 24; anchors.verticalCenter: parent.verticalCenter; text: root.t("title"); color: Theme.white; font.family: Theme.font; font.pixelSize: 15; font.bold: true }
            // Settings → Playback, where the BitPerfect light used to lead
            Rectangle {
                anchors.right: parent.right; anchors.rightMargin: 40; anchors.verticalCenter: parent.verticalCenter
                width: 32; height: 32; radius: 16; color: setTap.mix(Theme.wa(0), Theme.wa(0.1))
                Icon { anchors.centerIn: parent; name: "settings"; size: 16; color: Theme.silverA(0.7) }
                Tap { id: setTap; navRadius: 16; onClicked: root.openSetting() }
            }
            Rectangle {
                anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                width: 32; height: 32; radius: 16; color: xTap.mix(Theme.wa(0), Theme.wa(0.1))
                Icon { anchors.centerIn: parent; name: "x"; size: 16; color: Theme.silverA(0.7) }
                Tap { id: xTap; navRadius: 16; onClicked: root.done() }
            }
        }
        Item { width: 1; height: 14 }
        Repeater {
            model: root.stages
            Item {
                id: row
                required property var modelData
                required property int index
                readonly property color c: root.tone(root.stageTone(modelData))
                readonly property bool last: index === root.stages.length - 1
                width: body.width
                height: Math.max(36, txt.implicitHeight) + (last ? 0 : 14)
                // the line to the next step
                Rectangle {
                    visible: !row.last
                    x: 17; y: 36; width: 2; height: row.height - 36
                    color: Theme.wa(0.08)
                }
                Rectangle {
                    width: 36; height: 36; radius: 18
                    color: Qt.rgba(row.c.r, row.c.g, row.c.b, 0.10)
                    border.width: 1; border.color: Qt.rgba(row.c.r, row.c.g, row.c.b, 0.45)
                    Icon { anchors.centerIn: parent; name: row.modelData.icon; size: 16; color: row.c }
                }
                Column {
                    id: txt
                    x: 50; width: parent.width - 50
                    Text { text: row.modelData.label.toUpperCase(); color: Theme.silverA(0.5); font.family: Theme.font; font.pixelSize: 10; font.letterSpacing: 0.8 }
                    Text { width: parent.width; text: row.modelData.value; color: Theme.white; font.family: Theme.font; font.pixelSize: 15; font.bold: true; elide: Text.ElideRight }
                    Repeater {
                        model: row.modelData.details
                        Row {
                            required property var modelData
                            spacing: 6
                            Rectangle { anchors.verticalCenter: parent.verticalCenter; width: 5; height: 5; radius: 2.5; color: root.tone(parent.modelData.tone) }
                            Text {
                                text: parent.modelData.text
                                color: parent.modelData.tone === "idle" ? Theme.silverA(0.55) : Theme.silverA(0.85)
                                font.family: Theme.font; font.pixelSize: 12
                            }
                        }
                    }
                }
            }
        }
        Item { width: 1; height: 16 }
        Rectangle {
            readonly property color c: root.tone(root.verdict.tone)
            width: body.width; height: vcol.implicitHeight + 24; radius: 10
            color: Qt.rgba(c.r, c.g, c.b, 0.08); border.width: 1; border.color: Qt.rgba(c.r, c.g, c.b, 0.35)
            Icon { x: 14; y: 14; name: root.verdict.icon; size: 20; color: parent.c }
            Column {
                id: vcol
                x: 46; y: 12; width: parent.width - 60
                Text { text: root.verdict.title; color: parent.parent.c; font.family: Theme.font; font.pixelSize: 15; font.bold: true }
                Text { width: parent.width; visible: text !== ""; text: root.verdict.text; color: Theme.silverA(0.75); font.family: Theme.font; font.pixelSize: 12; wrapMode: Text.Wrap }
            }
        }
    }
}
