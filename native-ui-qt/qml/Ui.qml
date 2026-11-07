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

    // Now Playing artwork. For an inserted audio CD Lyrion only serves a generic
    // glyph (plugins/CDplayer/.../cdplayer_svg.png), so use the disc's Cover Art
    // Archive image — the same cover shown on the CD album card. The track url
    // (cdplay://…CDDBDiscid=…) is appended as a cache-buster so swapping the
    // disc reloads the cover instead of keeping the previous one.
    readonly property string npArtwork: Player.type === "CD"
        ? Api.srcBase + "/api/cd/cover?v=" + encodeURIComponent(Player.trackUrl)
        : Player.artworkUrl
}
