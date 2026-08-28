// Campo di testo dell'interfaccia: fondo scuro r8, bordo oro quando ha il
// fuoco, segnaposto grigio, cursore oro. Sui touch senza tastiera fisica
// apre la tastiera a schermo (come App.jsx con hasPhysicalKeyboard()).
import QtQuick
import Hifi.Ui

Rectangle {
    id: root
    property string text: ""
    property string placeholder: ""
    property bool password: false
    property bool focusBorder: true
    property color restBorder: Theme.border
    property color focusColor: Theme.gold          // focus:border-hifi-gold (o oro/50 nel wizard Wi-Fi)
    property real textSize: 16
    property real padding: 16
    property alias input: input
    property bool active: input.activeFocus
    signal textEdited(string t)
    signal accepted()
    radius: 8; color: Theme.dark
    border.width: 1
    border.color: input.activeFocus && focusBorder ? focusColor : restBorder
    // 🚨 mettere il fuoco da codice deve aprire ANCHE la tastiera a schermo:
    // succede quando una voce di Lyrion chiede del testo (le ricerche dentro
    // App/Radio) e quando si apre "salva come playlist". Prima compariva il
    // campo col cursore lampeggiante e nessun modo di scrivere.
    function takeFocus() { input.forceActiveFocus(); openVk() }
    function openVk() { if (!Sys.hasKeyboard) vkOpen(root) }
    // aggancio alla tastiera a schermo, fornito dalla radice
    property var vkOpen: function(field) { if (Ui.vk) Ui.vk.open(field) }

    TextInput {
        id: input
        x: root.padding; width: parent.width - root.padding * 2; height: parent.height
        verticalAlignment: TextInput.AlignVCenter
        text: root.text
        echoMode: root.password ? TextInput.Password : TextInput.Normal
        color: Theme.white; font.family: Theme.font; font.pixelSize: root.textSize
        selectByMouse: false
        clip: true
        cursorDelegate: Rectangle { width: 1; height: root.textSize + 2; color: Theme.gold; visible: input.activeFocus }
        onTextEdited: { root.text = text; root.textEdited(text) }
        onAccepted: root.accepted()
        activeFocusOnPress: true
        inputMethodHints: Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase
    }
    Text {
        x: root.padding; anchors.verticalCenter: parent.verticalCenter
        visible: root.text === "" && !input.activeFocus
        text: root.placeholder; color: Theme.silverA(0.4); font.family: Theme.font; font.pixelSize: root.textSize
        elide: Text.ElideRight; width: parent.width - root.padding * 2
    }
    MouseArea {
        anchors.fill: parent
        onClicked: { input.forceActiveFocus(); root.openVk() }
    }
}
