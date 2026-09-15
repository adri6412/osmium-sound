// Shared helpers of the album and artist pages: the metadata service
// (/api/meta on sources_server), the labels of credit roles and instruments,
// durations, dates and track lists as text.
pragma Singleton
import QtQuick
import Hifi.Ui

QtObject {
    function url(path) { return Api.srcBase + "/api/meta" + path }

    // a translation, or `fallback` when the key has none (Tr.t gives the key back)
    function tt(key, fallback) { var s = Tr.t(key); return s === key ? fallback : s }
    function humanize(s) {
        s = String(s || "").replace(/_/g, " ")
        return s ? s.charAt(0).toUpperCase() + s.slice(1) : ""
    }

    // what a credit says: "Tenor saxophone", "Producer", "Executive producer"…
    // Instruments and vocal types come from MusicBrainz in English: the common
    // ones are translated, the rest are shown as they are.
    function roleLabel(e) {
        if (!e) return ""
        var role = String(e.role || ""), attr = String(e.attr || "")
        // the sleeve's own wording ("1st violin") wins over the instrument's name
        if ((role === "instrument" || role === "vocal") && e.credit) { var c = String(e.credit); return c.charAt(0).toUpperCase() + c.slice(1) }
        if ((role === "instrument" || role === "vocal") && attr)
            return tt("meta.instrument." + attr, humanize(attr))
        if (role === "producer" && attr === "executive") return tt("meta.role.executive", "Executive producer")
        var base = tt("meta.role." + role, humanize(role))
        if (!attr || role === "instrument" || role === "vocal") return base
        // "assistant", "additional assistant", "strings" (an arranger's): word by word
        var words = attr.split(" ").map(function(w) { return tt("meta.attr." + w, tt("meta.instrument." + w, w)).toLowerCase() })
        return base + " (" + words.join(", ") + ")"
    }
    function groupLabel(g) { return tt("meta.group." + g, humanize(g)) }
    readonly property var groupOrder: ["performer", "composition", "production", "engineering", "other"]

    // 245 -> "4:05", 3725 -> "1:02:05"
    function dur(sec) {
        sec = Math.max(0, Math.round(Number(sec) || 0))
        var h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60
        return (h ? h + ":" + String(m).padStart(2, "0") : String(m)) + ":" + String(s).padStart(2, "0")
    }

    // "1959", "1959-08" or "1959-08-17" written the way the UI language does
    function date(d) {
        d = String(d || "")
        var m = d.match(/^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$/)
        if (!m) return d
        if (!m[2]) return m[1]
        var meta = Tr.node("_meta") || {}
        var loc = Qt.locale(String(meta.locale || "en-GB").replace("-", "_"))
        var dt = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3] || 1))
        return m[3] ? dt.toLocaleDateString(loc, "d MMMM yyyy") : dt.toLocaleDateString(loc, "MMMM yyyy")
    }
    function year(d) { var m = String(d || "").match(/^(\d{4})/); return m ? m[1] : "" }

    // [[1,1],[1,2],[1,3],[1,5]] -> "1–3, 5"; on several discs "1.1–1.3, 2.4"
    function trackList(tracks, discs) {
        if (!tracks || !tracks.length) return ""
        var t = tracks.slice().sort(function(a, b) { return a[0] - b[0] || a[1] - b[1] })
        var out = [], i = 0
        function name(x) { return discs > 1 ? x[0] + "." + x[1] : String(x[1]) }
        while (i < t.length) {
            var j = i
            while (j + 1 < t.length && t[j + 1][0] === t[i][0] && t[j + 1][1] === t[j][1] + 1) j++
            out.push(j > i + 1 ? name(t[i]) + "–" + name(t[j]) : j === i + 1 ? name(t[i]) + ", " + name(t[j]) : name(t[i]))
            i = j + 1
        }
        return out.join(", ")
    }

    // Lyrion's role names and ids of one track (tags A and S): "a, b" + "1,2".
    // Names may contain ", " themselves: when the counts disagree the whole
    // string is one person.
    function people(names, ids) {
        names = String(names || ""); ids = String(ids || "")
        if (!names) return []
        var n = names.split(", "), k = ids ? ids.split(",") : []
        if (n.length === k.length) return n.map(function(x, i) { return { name: x, id: k[i] } })
        return [{ name: names, id: k.length === 1 ? k[0] : "" }]
    }

    function bytes(n) {
        n = Number(n) || 0
        if (n < 1024 * 1024) return Math.max(1, Math.round(n / 1024)) + " KB"
        return (n / 1024 / 1024).toFixed(n < 10 * 1024 * 1024 ? 1 : 0) + " MB"
    }
}
