// La barra di scorrimento del contenuto (content-scrollbar: 3 px, #333).
import QtQuick

Rectangle {
    property Flickable flick
    visible: flick && flick.contentHeight > flick.height
    x: flick.width - 3; width: 3; radius: 2; color: "#333333"
    height: flick ? Math.max(20, flick.height * flick.height / Math.max(1, flick.contentHeight)) : 0
    y: flick ? (flick.height - height) * Math.max(0, Math.min(1, flick.contentY / Math.max(1, flick.contentHeight - flick.height))) : 0
}
