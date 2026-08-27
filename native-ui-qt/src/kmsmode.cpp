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
            drmModeModeInfo *best = nullptr;
            for (int m = 0; m < c->count_modes; m++) {
                drmModeModeInfo *mi = &c->modes[m];
                if (mi->vdisplay > capH) continue;
                double a = (double)mi->hdisplay / mi->vdisplay;
                if (std::abs(a - aspect) > 0.02) continue;
                if (!best || mi->vdisplay > best->vdisplay || (mi->vdisplay == best->vdisplay && mi->vrefresh > best->vrefresh)) best = mi;
            }
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
