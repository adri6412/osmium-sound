// Credits by role, grouped (performers, composition, production, recording
// and mixing, other), from the metadata service or from the library's own
// tags. Each name that leads somewhere can be tapped: an artist of the
// library (artist_id / id) or a person known to MusicBrainz (mbid).
import QtQuick
import Hifi.Ui

Column {
    id: root
    // [{group, role, attr, credit, people: [{name, mbid, artist_id | id}], tracks: [[disc, n]] | null}]
    property var credits: []
    // [{role, name, area}]
    property var places: []
    property int discs: 1
    property bool grouped: true
    property real labelW: 176
    signal person(var p)

    readonly property var groups: {
        var by = {}, out = []
        for (var i = 0; i < credits.length; i++) {
            var g = grouped ? String(credits[i].group || "other") : ""
            if (!by[g]) by[g] = []
            by[g].push(credits[i])
        }
        var order = grouped ? Meta.groupOrder.concat(Object.keys(by).filter(function(k) { return Meta.groupOrder.indexOf(k) < 0 })) : [""]
        for (var j = 0; j < order.length; j++)
            if (by[order[j]]) out.push({ label: order[j] ? Meta.groupLabel(order[j]) : "", entries: by[order[j]] })
        if (places && places.length)
            out.push({ label: Meta.groupLabel("places"), entries: places.map(function(p) {
                return { role: p.role, attr: "", people: [{ name: p.area ? p.name + " (" + p.area + ")" : p.name }], tracks: null }
            }) })
        return out
    }
    spacing: 4

    Repeater {
        model: root.groups
        Column {
            id: grp
            required property var modelData
            required property int index
            width: root.width; spacing: 0
            Item { width: 1; height: grp.index > 0 && grp.modelData.label ? 10 : 0 }
            Text {
                visible: grp.modelData.label !== ""
                width: parent.width; height: 24; verticalAlignment: Text.AlignVCenter
                text: grp.modelData.label; color: Theme.gold
                font.family: Theme.font; font.pixelSize: 13; font.bold: true
            }
            Repeater {
                model: grp.modelData.entries
                Item {
                    id: entry
                    required property var modelData
                    readonly property string cover: modelData.tracks && modelData.tracks.length ? Tr.tf("player.page.onTracks", "list", Meta.trackList(modelData.tracks, root.discs)) : ""
                    width: root.width; height: Math.max(roleText.height, names.height) + 8
                    Text {
                        id: roleText
                        y: 4; width: root.labelW - 12
                        text: Meta.roleLabel(entry.modelData); wrapMode: Text.Wrap
                        color: Theme.silverA(0.65); font.family: Theme.font; font.pixelSize: 12
                        lineHeight: 17; lineHeightMode: Text.FixedHeight
                    }
                    Flow {
                        id: names
                        x: root.labelW; y: 3; width: root.width - root.labelW
                        spacing: 6
                        Repeater {
                            model: entry.modelData.people || []
                            Text {
                                required property var modelData
                                required property int index
                                readonly property string libId: String(modelData.artist_id || modelData.id || "")
                                readonly property bool linked: libId !== "" || !!modelData.mbid
                                readonly property bool last: index === (entry.modelData.people || []).length - 1
                                text: String(modelData.name || "") + (modelData.credit ? " (" + modelData.credit + ")" : "") + (last ? "" : ",")
                                color: libId !== "" ? pTap.mix(Theme.white, Theme.gold) : linked ? pTap.mix(Theme.silverA(0.9), Theme.gold) : Theme.silverA(0.75)
                                font.family: Theme.font; font.pixelSize: 13
                                lineHeight: 19; lineHeightMode: Text.FixedHeight
                                Tap { id: pTap; grow: 4; enabled: parent.linked; onClicked: root.person(parent.modelData) }
                            }
                        }
                        Text {
                            visible: entry.cover !== ""
                            text: entry.cover; color: Theme.silverA(0.45)
                            font.family: Theme.font; font.pixelSize: 11
                            lineHeight: 19; lineHeightMode: Text.FixedHeight
                        }
                    }
                }
            }
        }
    }
}
