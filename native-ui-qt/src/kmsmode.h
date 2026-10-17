// kmsmode — sceglie il modo video per eglfs a partire da
// /etc/hifi-player/ui-resolution (auto|720|1080|native), con la stessa
// politica di hifi-ui-resolution.sh e drmfb.c: mai una trasformata di scala,
// sempre un modo REALE del pannello, il piu' grande con lo stesso aspetto e
// altezza <= tetto. Scrive il JSON per QT_QPA_EGLFS_KMS_CONFIG.
//
// Con piu' monitor collegati decide anche cosa mostra ciascuno, da
// /etc/hifi-player/ui-screens:
//   mirror (di serie)  la stessa interfaccia su tutti: il primo monitor e' la
//                      sorgente, gli altri lo clonano ("clones" di eglfs_kms,
//                      che fa leggere a ogni CRTC lo stesso framebuffer — per
//                      questo tutti devono stare sulla STESSA risoluzione);
//   only:<uscita>      solo su quel monitor, gli altri spenti ("mode": "off").
// Niente "estendi": l'interfaccia e' una finestra sola.
#pragma once
#include <QJsonObject>
#include <QList>
#include <QString>

struct KmsMode { int w = 0, h = 0, hz = 0; bool preferred = false; };
struct KmsOutput { QString name; QList<KmsMode> modes; };

// Nome di un'uscita come lo scrive Qt (qkmsdevice.cpp): tipo + numero, con
// HDMI-A/HDMI-B -> "HDMI" e tutti i DVI -> "DVI". La configurazione e'
// abbinata per nome: un nome diverso da quello di Qt viene ignorato in silenzio.
QString kmsOutputName(uint32_t connectorType, uint32_t typeId);

// Il piano, senza toccare il DRM (per i test): vuoto = si lascia fare a Qt.
QJsonObject kmsPlan(const QList<KmsOutput> &outputs, const QString &resolutionPref,
                    const QString &screensPref, const QString &card = "/dev/dri/card0");

// Ritorna il percorso del file JSON scritto, o vuoto se si lascia fare a Qt.
QString kmsConfigFor(const QString &pref, const QString &screens = "mirror",
                     const QString &card = "/dev/dri/card0");
