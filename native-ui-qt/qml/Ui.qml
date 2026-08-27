// Punti d'aggancio globali fra i componenti: la tastiera a schermo e la
// radice dell'app, impostati da App.qml al completamento.
pragma Singleton
import QtQuick

QtObject {
    property var app: null
    property var vk: null
    property var dialogs: null
    property var toast: null
    property var settings: null
    property var cdrip: null
}
