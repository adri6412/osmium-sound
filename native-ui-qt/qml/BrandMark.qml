// The Osmium Sound mark: seven gold bars closing in like a level meter,
// OSMIUM in gold, SOUND in off-white. Drawn, not a picture: the kiosk's font
// is DejaVu Sans, the one the logo is set in, and every measure is a
// multiple of the cap height (`cap`) taken on the logo artwork, so the mark
// is the same at 11 points in the tab bar and at full size. Two shapes: in a
// row (bars, OSMIUM, SOUND) for bars and headers, and `stacked` as on the
// logo, with SOUND spread under bars and OSMIUM, where there is room.
import QtQuick
import Hifi.Ui

Item {
    id: root
    property real cap: 11                     // cap height of OSMIUM, in points
    property bool stacked: false
    property color gold: Theme.gold
    property color ink: "#f1f0ea"             // the logo's off-white
    // DejaVu Sans Bold: the cap height is 0.729 em
    readonly property real px: cap / 0.729
    // the bars: width and left edges in cap heights, as on the logo
    readonly property var barX: [0, 0.568, 1.012, 1.346, 1.605, 1.815, 1.988]
    readonly property real barW: Math.max(1, Math.round(cap * 0.074))
    readonly property real barsW: Math.round(cap * 1.988) + barW
    readonly property real gap: cap * 0.5     // bars to the O
    // letter spacing of OSMIUM: measured in the rig against the logo (the
    // word is 7.19 cap heights wide from the O to the M)
    readonly property real track: cap * 0.178
    // bars to the end of OSMIUM (Text counts a spacing after the M too)
    readonly property real rowW: barsW + gap + osmium.implicitWidth - track
    implicitWidth: stacked ? rowW : rowW + cap * 0.55 + sound.implicitWidth
    implicitHeight: stacked ? osmium.height + cap * 1.3 : osmium.height

    Item {
        id: bars
        width: root.barsW; height: root.cap
        // the bars sit on the baseline, as tall as the capitals
        y: osmium.y + osmium.baselineOffset - root.cap
        Repeater {
            model: root.barX
            Rectangle {
                required property real modelData
                x: Math.round(modelData * root.cap); width: root.barW; height: root.cap
                color: root.gold
            }
        }
    }
    Text {
        id: osmium
        x: root.barsW + root.gap
        text: "OSMIUM"; color: root.gold
        font.family: Theme.font; font.bold: true; font.pixelSize: root.px; font.letterSpacing: root.track
    }
    // in a row: SOUND after OSMIUM, same size, in off-white
    Text {
        id: sound
        visible: !root.stacked
        x: osmium.x + osmium.implicitWidth + root.cap * 0.55
        text: "SOUND"; color: root.ink
        font.family: Theme.font; font.bold: true; font.pixelSize: root.px; font.letterSpacing: root.track
    }
    // stacked: S O U N D at 0.54 of the cap height, spread across the whole
    // width, the first and the last letter flush with the edges, 0.69 cap
    // heights under OSMIUM
    Repeater {
        model: root.stacked ? ["S", "O", "U", "N", "D"] : []
        Text {
            required property string modelData
            required property int index
            text: modelData; color: root.ink
            font.family: Theme.font; font.bold: true; font.pixelSize: root.px * 0.543
            x: index * (root.rowW - implicitWidth) / 4
            anchors.baseline: osmium.baseline
            anchors.baselineOffset: root.cap * (0.69 + 0.543)
        }
    }
}
