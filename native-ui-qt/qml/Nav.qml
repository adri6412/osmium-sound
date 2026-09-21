// Nav — il riflettore del telecomando: quale riquadro e' scelto, come ci si
// sposta con le frecce e come lo si "tocca" con OK.
//
// L'interfaccia e' nata per il dito: non c'e' un ordine di riquadri scritto da
// nessuna parte, e scriverlo schermata per schermata avrebbe voluto dire
// rifarle tutte. Qui invece si guarda DOVE sono: i candidati sono tutti i
// riquadri che si possono toccare (Tap.qml si marca da se' con `navigable`), e
// una freccia va sul piu' vicino in quella direzione. Le schermate nuove
// funzionano da sole, senza aggiungere niente.
//
// 🚨 I candidati NON sono un elenco tenuto aggiornato ma un giro dell'albero
// fatto al momento del tasto: le righe di una lista nascono e muoiono mentre
// si scorre, e un elenco registrato sarebbe sempre in ritardo di un passo. Il
// giro si ferma sui rami invisibili (che sono la maggior parte) e parte dallo
// strato modale aperto quando ce n'e' uno, quindi costa poco.
//
// 🚨 OK non chiama la funzione del riquadro: preme DAVVERO nel suo centro
// (Sys.tapAt), come un dito. Cosi' partono anche l'animazione della pressione
// e tutto quello che il riquadro fa al tocco, senza che nessuno debba
// dichiarare due volte cosa fa.
pragma Singleton
import QtQuick

QtObject {
    id: nav

    // la radice della tela, che App.qml si presenta all'avvio (come Ui.app):
    // e' lo strato piu' basso in cui cercare i candidati
    property Item root: null
    // il riquadro col riflettore, e se il riflettore si vede
    property Item item: null
    property bool active: false
    // gli strati modali aperti (NavScope.qml): si naviga solo dentro l'ultimo
    property var scopes: []
    // dov'era il riflettore l'ultima volta, per ritrovare la strada quando la
    // riga sotto il riflettore sparisce (lista che scorre)
    property var lastRect: null
    // e in quali scatole stava: quando la schermata cambia si riparte dalla
    // scatola piu' interna ancora viva, non dal punto piu' vicino in assoluto
    property var lastChain: []

    // ─── strati modali ─────────────────────────────────────────────────────
    function pushScope(area) {
        if (!area || scopes.indexOf(area) >= 0) return
        var s = scopes.slice(); s.push(area); scopes = s
        if (item && !inScope(item)) { item = null; lastRect = null }
        if (active) refocusSoon(true)
    }
    function popScope(area) {
        var i = scopes.indexOf(area); if (i < 0) return
        var s = scopes.slice(); s.splice(i, 1); scopes = s
        if (item && !inScope(item)) { item = null; lastRect = null }
        if (active) refocusSoon(false)
    }
    // 🚨 Uno strato che si apre non ha ancora i suoi riquadri: al momento del
    // pushScope il menu a pressione lunga era largo zero e non c'era niente da
    // illuminare. Quindi si riprova qualche volta, e si smette appena il
    // riflettore ha trovato casa.
    // 🚨 Non basta illuminare il primo riquadro che si trova e smettere: uno
    // strato che entra scorrendo (la coda) al primo giro ha solo i pulsanti in
    // fondo, e il riflettore si fermava sul rosso "Svuota" — con OK a un passo
    // di distanza. Quindi si rifa' la scelta a ogni giro finche' la scena non
    // si e' assestata, e si smette appena l'utente muove lui.
    property int userMoves: 0
    function refocusSoon(useFirst) {
        scopeFocus.first = useFirst
        scopeFocus.tries = 0
        scopeFocus.since = userMoves
        scopeFocus.restart()
    }
    property Timer scopeFocus: Timer {
        property int tries: 0
        property int since: 0
        property bool first: true
        interval: 70; repeat: true
        onTriggered: {
            tries++
            if (nav.userMoves !== since) { stop(); return }        // comanda l'utente
            if (nav.active) {
                if (first) nav.focusFirst()
                else if (!nav.rectOf(nav.item)) nav.focusNearest(nav.lastRect)
            }
            if (tries >= 6) stop()
        }
    }
    function scope() { return scopes.length ? scopes[scopes.length - 1] : root }
    function inScope(it) {
        var top = scope()
        if (!top) return true
        for (var p = it; p; p = p.parent) if (p === top) return true
        return false
    }

    // ─── i candidati ───────────────────────────────────────────────────────
    function collect(from, out) {
        if (!from) return out
        var kids = from.children
        for (var i = 0; i < kids.length; i++) {
            var c = kids[i]
            if (!c.visible || c.opacity < 0.05) continue      // ramo spento: si salta tutto
            if (c.navigable === true && c.enabled) out.push(c)
            collect(c, out)
        }
        return out
    }
    // Il rettangolo sullo schermo, misurato contro chi lo ritaglia (le liste
    // scorrono dentro un `clip: true`).
    //
    // 🚨 `slack` e' quanto si puo' stare FUORI dal bordo ed essere ancora un
    // candidato. Senza, la riga subito sotto il bordo della lista non era
    // candidata, "giu'" non trovava niente in linea e il riflettore se ne
    // andava nel pannello accanto invece di scorrere di una riga. Chi sta
    // appena fuori viene scelto e poi ensureVisible lo porta dentro, che e'
    // esattamente come si scorre una lista col telecomando.
    function rectOf(it, slack) {
        if (!it || !it.visible || it.width <= 1 || it.height <= 1) return null
        var s = slack || 0
        var r = it.mapToItem(null, 0, 0, it.width, it.height)
        for (var p = it.parent; p; p = p.parent) {
            if (p.clip !== true) continue
            var pr = p.mapToItem(null, 0, 0, p.width, p.height)
            if (r.x + r.width < pr.x - s || r.x > pr.x + pr.width + s ||
                r.y + r.height < pr.y - s || r.y > pr.y + pr.height + s) return null
            if (s > 0) continue                       // si tiene il rettangolo intero
            var x0 = Math.max(r.x, pr.x), y0 = Math.max(r.y, pr.y)
            var x1 = Math.min(r.x + r.width, pr.x + pr.width), y1 = Math.min(r.y + r.height, pr.y + pr.height)
            if (x1 - x0 < 6 || y1 - y0 < 6) return null
            r = Qt.rect(x0, y0, x1 - x0, y1 - y0)
        }
        return r
    }
    // quanto si puo' stare oltre il bordo di una lista ed essere ancora il
    // "prossimo": una riga, non mezza pagina
    readonly property real slack: 140
    function candidates() {
        var found = collect(scope(), [])
        var out = []
        for (var i = 0; i < found.length; i++) {
            var r = rectOf(found[i], slack)
            if (r) out.push({ it: found[i], r: r })
        }
        return out
    }

    // ─── spostarsi ─────────────────────────────────────────────────────────
    function cx(r) { return r.x + r.width / 2 }
    function cy(r) { return r.y + r.height / 2 }
    function span(a0, a1, b0, b1) { return Math.min(a1, b1) - Math.max(a0, b0) }

    // Il migliore in una direzione. Due regole, nell'ordine:
    //   1. chi sta di traverso non conta finche' c'e' qualcosa in linea. 🚨 Senza
    //      questa, da un titolo in basso a sinistra "destra" finiva sul pulsante
    //      del brano precedente (venti punti a destra ma centoventi piu' in giu')
    //      invece che nella libreria, che e' quello che si vede a destra.
    //   2. fra quelli in linea vince il piu' vicino di bordo, non di centro: una
    //      riga lunga e una corta accanto valgono uguale.
    function pick(list, cur, dir) {
        var vertical = dir === "up" || dir === "down"
        var best = null, bestScore = 0, bestAligned = false
        for (var i = 0; i < list.length; i++) {
            var r = list[i].r
            if (list[i].it === item) continue
            var dc = dir === "down" ? cy(r) - cy(cur) : dir === "up" ? cy(cur) - cy(r)
                   : dir === "right" ? cx(r) - cx(cur) : cx(cur) - cx(r)
            if (dc <= 1) continue                       // sta dietro, o e' in linea
            var edge = dir === "down" ? r.y - (cur.y + cur.height) : dir === "up" ? cur.y - (r.y + r.height)
                     : dir === "right" ? r.x - (cur.x + cur.width) : cur.x - (r.x + r.width)
            edge = Math.max(0, edge)
            // quanto si sovrappongono di traverso
            var ov = vertical ? span(cur.x, cur.x + cur.width, r.x, r.x + r.width)
                              : span(cur.y, cur.y + cur.height, r.y, r.y + r.height)
            var aligned = ov > 0
            var off = aligned ? 0 : (vertical ? Math.abs(cx(r) - cx(cur)) : Math.abs(cy(r) - cy(cur)))
            var s = edge + dc * 0.2 + off * 2.5
            if (aligned && !bestAligned) { best = list[i].it; bestScore = s; bestAligned = true; continue }
            if (!aligned && bestAligned) continue
            if (!best || s < bestScore) { best = list[i].it; bestScore = s }
        }
        return best ? { it: best, aligned: bestAligned } : null
    }

    function move(dir) {
        userMoves++
        show()
        var list = candidates()
        if (!list.length) return false
        // Il riquadro che avevamo sotto il riflettore non c'e' piu' (lo schermo
        // e' cambiato): questa freccia non muove, riaccende — sul riquadro piu'
        // vicino a dov'eravamo, che e' quello che l'occhio si aspetta.
        var cur = (item && inScope(item)) ? rectOf(item) : null
        if (!cur) return focusNearest(lastRect)
        var best = pick(list, cur, dir)
        // 🚨 Niente in linea, ma la lista sotto il riflettore ha ancora strada:
        // si scorre. Saltare al pannello accanto solo perche' e' l'unica cosa
        // in quella direzione e' il modo piu' rapido per perdere il filo.
        if ((!best || !best.aligned) && canScroll(dir) && nudge(dir)) return true
        if (!best) return false
        focus(best.it)
        return true
    }
    // c'e' ancora dove scorrere, nella lista che contiene il riflettore?
    function canScroll(dir) {
        if (dir !== "up" && dir !== "down") return false
        var f = flickOf(item)
        if (!f || f.contentHeight <= f.height) return false
        return dir === "down" ? f.contentY < f.contentHeight - f.height - 1 : f.contentY > 1
    }

    // Niente in quella direzione: forse c'e' ma la lista non l'ha ancora
    // costruito. Si scorre di mezza vista e si riprova una volta sola.
    function nudge(dir) {
        if (dir !== "up" && dir !== "down") return false
        var f = flickOf(item)
        if (!f || f.contentHeight <= f.height) return false
        var step = Math.max(40, (lastRect ? lastRect.height : 40) * 1.4)
        var want = f.contentY + (dir === "down" ? step : -step)
        want = Math.max(0, Math.min(f.contentHeight - f.height, want))
        var delta = want - f.contentY
        if (Math.abs(delta) < 1) return false
        f.contentY = want
        // il riferimento si sposta con la lista, o il "piu' vicino in giu'"
        // ripartirebbe da un punto che non c'e' piu'
        if (lastRect) lastRect = Qt.rect(lastRect.x, lastRect.y - delta, lastRect.width, lastRect.height)
        retry.dir = dir
        retry.restart()
        return true
    }
    property Timer retry: Timer {
        property string dir: ""
        interval: 40; repeat: false
        onTriggered: {
            // una sola volta: se anche adesso non c'e' niente, si e' in fondo
            var list = nav.candidates()
            var cur = (nav.item && nav.inScope(nav.item)) ? nav.rectOf(nav.item) : nav.lastRect
            if (!cur || !list.length) { nav.focusFirst(); return }
            var best = nav.pick(list, cur, dir)
            if (best) nav.focus(best.it)
        }
    }

    // il primo riquadro dello strato aperto: in alto a sinistra
    function focusFirst() {
        var list = candidates()
        if (!list.length) { item = null; return false }
        var best = null, bestScore = 0
        for (var i = 0; i < list.length; i++) {
            var s = list[i].r.y * 2 + list[i].r.x
            if (!best || s < bestScore) { best = list[i].it; bestScore = s }
        }
        focus(best)
        return true
    }

    function focus(it) {
        if (!it) return
        item = it
        active = true
        ensureVisible(it)
        lastRect = rectOf(it)
        var chain = []
        for (var p = it.parent; p && chain.length < 12; p = p.parent) chain.push(p)
        lastChain = chain
    }
    // un riquadro distrutto lascia un guscio: toccarlo solleva un errore
    function alive(o) { try { return !!o && o.width !== undefined } catch (e) { return false } }
    function isInside(box, it) {
        for (var p = it; p; p = p.parent) if (p === box) return true
        return false
    }

    // ─── farlo vedere ──────────────────────────────────────────────────────
    function flickOf(it) {
        for (var p = it ? it.parent : null; p; p = p.parent)
            if (p.contentY !== undefined && p.contentHeight !== undefined) return p
        return null
    }
    function ensureVisible(it) {
        // tutte le viste che lo contengono, dalla piu' vicina in fuori
        for (var p = it.parent; p; p = p.parent) {
            if (p.contentY === undefined || p.contentHeight === undefined) continue
            var r = it.mapToItem(p.contentItem, 0, 0, it.width, it.height)
            var m = 12
            if (p.contentHeight > p.height) {
                if (r.y - m < p.contentY) p.contentY = Math.max(0, r.y - m)
                else if (r.y + r.height + m > p.contentY + p.height)
                    p.contentY = Math.min(p.contentHeight - p.height, r.y + r.height + m - p.height)
            }
            if (p.contentWidth > p.width) {
                if (r.x - m < p.contentX) p.contentX = Math.max(0, r.x - m)
                else if (r.x + r.width + m > p.contentX + p.width)
                    p.contentX = Math.min(p.contentWidth - p.width, r.x + r.width + m - p.width)
            }
        }
    }
    // una pagina su o giu' nella lista sotto il riflettore
    function page(dir) {
        show()
        var f = flickOf(item)
        if (!f || f.contentHeight <= f.height) return move(dir === "up" ? "up" : "down")
        var step = f.height * 0.9
        var want = Math.max(0, Math.min(f.contentHeight - f.height, f.contentY + (dir === "up" ? -step : step)))
        var delta = want - f.contentY
        f.contentY = want
        if (lastRect) lastRect = Qt.rect(lastRect.x, lastRect.y - delta, lastRect.width, lastRect.height)
        // il riflettore resta dov'e' sullo schermo, sulla riga che ci e' finita
        nearest.restart()
        return true
    }
    property Timer nearest: Timer {
        interval: 40; repeat: false
        onTriggered: nav.focusNearest(nav.lastRect)
    }
    // il riquadro piu' vicino a un punto: dopo una pagina, e dopo che una
    // schermata e' cambiata sotto il riflettore
    // 🚨 Prima la scatola, poi la distanza. Aprendo una tessera della home, il
    // riquadro piu' vicino in assoluto a quella tessera era un pulsante del
    // player a sinistra: il riflettore usciva dalla libreria proprio mentre la
    // libreria mostrava la cosa appena aperta. Quindi si cerca prima dentro la
    // scatola piu' interna in cui eravamo che sia ancora viva e abbia qualcosa
    // dentro, e solo dopo si guarda tutto il resto.
    function focusNearest(where) {
        var list = candidates()
        if (!list.length) { item = null; return false }
        for (var c = 0; c < lastChain.length; c++) {
            if (!alive(lastChain[c])) continue
            var inside = []
            for (var j = 0; j < list.length; j++) if (isInside(lastChain[c], list[j].it)) inside.push(list[j])
            if (inside.length) return focusClosest(inside, where)
        }
        return focusClosest(list, where)
    }
    function focusClosest(list, where) {
        if (!list.length) return focusFirst()
        if (!where) { focus(list[0].it); return true }
        var best = null, bestScore = 0
        for (var i = 0; i < list.length; i++) {
            var r = list[i].r
            var s = Math.abs(cy(r) - cy(where)) + Math.abs(cx(r) - cx(where)) * 0.5
            if (!best || s < bestScore) { best = list[i].it; bestScore = s }
        }
        focus(best)
        return true
    }

    // ─── toccarlo ──────────────────────────────────────────────────────────
    // `hold` = pressione lunga: e' il menu che si apre tenendo il dito su una
    // riga (620 ms, oltre i 500 di pressAndHoldInterval)
    function activate(hold) {
        if (!item || !inScope(item)) { if (!focusFirst()) return false; }
        var r = rectOf(item)
        if (!r) return false
        Sys.tapAt(r.x + r.width / 2, r.y + r.height / 2, hold ? 620 : 0)
        // Quello che si e' appena premuto cambia spesso la schermata (una
        // tessera apre una lista, una riga apre una pagina). Se il riquadro
        // sparisce, il riflettore non resta appeso al vuoto: va su quello che
        // adesso e' piu' vicino a dov'era.
        after.restart()
        return true
    }
    property Timer after: Timer {
        interval: 280; repeat: false
        onTriggered: if (nav.active && !nav.rectOf(nav.item)) nav.focusNearest(nav.lastRect)
    }

    function show() { if (!active) { active = true; if (!item || !inScope(item)) focusFirst() } }
    function hide() { if (active) active = false }
    function clear() { item = null; lastRect = null }
}
