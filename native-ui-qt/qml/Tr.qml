// Traduzioni: Tr.t("player.queue"). Legge `lang` prima di tradurre, cosi' ogni
// binding che usa Tr.t si riaggiorna da solo quando la lingua cambia.
pragma Singleton
import QtQuick

QtObject {
    property string lang: I18n.lang
    function t(key) { void lang; return I18n.t(key) }
    function tf(key, name, value) { void lang; return I18n.tf(key, name, value) }
    function node(key) { void lang; return I18n.node(key) }
    // maiuscolo, come `uppercase` di Tailwind
    function up(key) { void lang; return I18n.t(key).toUpperCase() }
}
