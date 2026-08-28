#include "kmsmode.h"
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QtDebug>
#include <fcntl.h>
#include <unistd.h>
#include <xf86drm.h>
#include <xf86drmMode.h>

static const char *connName(uint32_t type) {
    switch (type) {
    case DRM_MODE_CONNECTOR_HDMIA: return "HDMI";
    case DRM_MODE_CONNECTOR_HDMIB: return "HDMIB";
    case DRM_MODE_CONNECTOR_DisplayPort: return "DP";
    case DRM_MODE_CONNECTOR_eDP: return "eDP";
    case DRM_MODE_CONNECTOR_LVDS: return "LVDS";
    case DRM_MODE_CONNECTOR_VGA: return "VGA";
    case DRM_MODE_CONNECTOR_DVID: return "DVI-D";
    case DRM_MODE_CONNECTOR_DVII: return "DVI-I";
    case DRM_MODE_CONNECTOR_DSI: return "DSI";
    default: return "Unknown";
    }
}

QString kmsConfigFor(const QString &pref, const QString &card) {
    int capH = pref == "native" ? 0 : pref == "1080" ? 1080 : 720;
    if (capH == 0) return QString();                 // modo preferito del pannello: ci pensa Qt
    int fd = open(card.toLocal8Bit().constData(), O_RDWR | O_CLOEXEC);
    if (fd < 0) return QString();
    drmModeRes *res = drmModeGetResources(fd);
    if (!res) { close(fd); return QString(); }
    QString out;
    for (int i = 0; i < res->count_connectors && out.isEmpty(); i++) {
        drmModeConnector *c = drmModeGetConnector(fd, res->connectors[i]);
        if (!c) continue;
        if (c->connection == DRM_MODE_CONNECTED && c->count_modes > 0) {
            // aspetto del pannello = quello del modo preferito (o del primo)
            drmModeModeInfo *pre = &c->modes[0];
            for (int m = 0; m < c->count_modes; m++) if (c->modes[m].type & DRM_MODE_TYPE_PREFERRED) { pre = &c->modes[m]; break; }
            double aspect = (double)pre->hdisplay / pre->vdisplay;
            // Stessa regola di best_real_mode() in hifi-ui-resolution.sh (la
            // strada Wayland di Electron), cosi' le due interfacce finiscono
            // sullo stesso modo video con la stessa impostazione:
            //  1. il modo REALE piu' grande con altezza <= tetto e l'aspetto
            //     del pannello (1 % di tolleranza), mai sotto 1024x600;
            //  2. se non c'e' — pannelli 21:9 o 16:10, o monitor senza il
            //     720p — il piu' PICCOLO tra quelli SOPRA al tetto, sempre con
            //     l'aspetto del pannello: e' comunque una frazione dei pixel
            //     del nativo (3440x1440 -> 2560x1080);
            //  3. solo se il pannello non espone nessun modo piu' piccolo del
            //     proprio, si resta sul nativo.
            drmModeModeInfo *best = nullptr, *above = nullptr;
            for (int m = 0; m < c->count_modes; m++) {
                drmModeModeInfo *mi = &c->modes[m];
                if (mi->hdisplay < 1024 || mi->vdisplay < 600) continue;
                if (mi->hdisplay >= pre->hdisplay && mi->vdisplay >= pre->vdisplay) continue;
                double a = (double)mi->hdisplay / mi->vdisplay;
                if (a > aspect * 1.01 || a < aspect * 0.99) continue;
                if (mi->vdisplay <= capH) {
                    if (!best || mi->vdisplay > best->vdisplay || (mi->vdisplay == best->vdisplay && mi->vrefresh > best->vrefresh)) best = mi;
                } else {
                    if (!above || mi->vdisplay < above->vdisplay || (mi->vdisplay == above->vdisplay && mi->vrefresh > above->vrefresh)) above = mi;
                }
            }
            if (!best) best = above;
            if (best && !(best->hdisplay == pre->hdisplay && best->vdisplay == pre->vdisplay)) {
                QString name = QString("%1%2").arg(connName(c->connector_type)).arg(c->connector_type_id);
                QJsonObject o;
                o["name"] = name;
                o["mode"] = QString("%1x%2@%3").arg(best->hdisplay).arg(best->vdisplay).arg(best->vrefresh);
                QJsonObject root;
                root["device"] = card;
                root["outputs"] = QJsonArray{o};
                QFile f("/tmp/hifi-qt-kms.json");
                if (f.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
                    f.write(QJsonDocument(root).toJson(QJsonDocument::Compact));
                    out = f.fileName();
                    qInfo("kms: %s -> %s (tetto %d)", qPrintable(name), qPrintable(o["mode"].toString()), capH);
                }
            }
        }
        drmModeFreeConnector(c);
    }
    drmModeFreeResources(res);
    close(fd);
    return out;
}
