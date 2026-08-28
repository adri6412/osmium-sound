// kmsmode — sceglie il modo video per eglfs a partire da
// /etc/hifi-player/ui-resolution (auto|720|1080|native), con la stessa
// politica di hifi-ui-resolution.sh e drmfb.c: mai una trasformata di scala,
// sempre un modo REALE del pannello, il piu' grande con lo stesso aspetto e
// altezza <= tetto. Scrive il JSON per QT_QPA_EGLFS_KMS_CONFIG.
#pragma once
#include <QString>

// Ritorna il percorso del file JSON scritto, o vuoto se si lascia fare a Qt.
QString kmsConfigFor(const QString &pref, const QString &card = "/dev/dri/card0");
