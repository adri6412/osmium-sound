// NavScope — "finche' sono aperto, il telecomando si muove solo qui dentro".
//
// Si mette dentro lo strato che copre gli altri (un dialogo, la tastiera a
// schermo, la coda, la procedura guidata) e si accende col suo stesso
// interruttore: Nav allora cerca i candidati soltanto fra i suoi riquadri, e
// le frecce non vanno piu' a finire sulla schermata sotto.
import QtQuick
import Hifi.Ui

Item {
    id: scope
    // lo strato da cui non si esce: di norma chi ci contiene
    property Item area: parent
    property bool active: false

    visible: false
    width: 0; height: 0
    onActiveChanged: active ? Nav.pushScope(area) : Nav.popScope(area)
    Component.onCompleted: if (active) Nav.pushScope(area)
    // 🚨 anche alla distruzione: uno strato che se ne va senza spegnersi
    // (un caricatore che si svuota) lascerebbe il telecomando chiuso dentro
    // qualcosa che non c'e' piu'
    Component.onDestruction: Nav.popScope(area)
}
