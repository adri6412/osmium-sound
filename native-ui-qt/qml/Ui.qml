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
    property var folderChooser: null     // FolderChooser.qml: the one folder picker of the kiosk
    property var sources: null         // SourcesPage.qml: Music sources, its places and data
    property var addMusic: null        // AddMusicWizard.qml
    property var importMusic: null     // ImportWizard.qml: a USB stick, listen or copy
    property var overlays: null     // coda, salva playlist, sonno, finestra "nome"
}
