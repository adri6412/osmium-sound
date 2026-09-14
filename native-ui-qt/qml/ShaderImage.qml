// Immagine ritagliata da una maschera (angoli tondi), via MultiEffect.
import QtQuick
import QtQuick.Effects

MultiEffect {
    property var mask: null
    maskEnabled: mask !== null
    maskSource: mask
}
