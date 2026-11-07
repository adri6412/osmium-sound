#include "kmsmode.h"
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QtDebug>
#include <fcntl.h>
#include <unistd.h>
#include <xf86drm.h>
#include <xf86drmMode.h>

QString kmsOutputName(uint32_t type, uint32_t typeId) {
    // La tabella di Qt 6.8 (qkmsdevice.cpp, connector_type_names), indice =
    // DRM_MODE_CONNECTOR_*. Prima qui c'erano "HDMIB", "DVI-D", "DVI-I": su
    // quelle uscite Qt non riconosceva il nome e ignorava la configurazione.
    static const char *names[] = { "None", "VGA", "DVI", "DVI", "DVI", "Composite", "TV", "LVDS",
                                   "CTV", "DIN", "DP", "HDMI", "HDMI", "TV", "eDP", "Virtual", "DSI" };
    const QString base = type < sizeof(names) / sizeof(names[0]) ? names[type] : "UNKNOWN";
    return base + QString::number(typeId);
}

static QString modeString(const KmsMode &m) { return QString("%1x%2@%3").arg(m.w).arg(m.h).arg(m.hz); }

static const KmsMode *preferredOf(const KmsOutput &o) {
    for (const KmsMode &m : o.modes) if (m.preferred) return &m;
    return o.modes.isEmpty() ? nullptr : &o.modes.first();
}

// La regola di sempre per un monitor, la stessa di best_real_mode() in
// hifi-ui-resolution.sh (la strada Wayland di Electron), cosi' le due
// interfacce finiscono sullo stesso modo video con la stessa impostazione:
//  1. il modo REALE piu' grande con altezza <= tetto e l'aspetto del pannello
//     (1 % di tolleranza), mai sotto 1024x600;
//  2. se non c'e' — pannelli 21:9 o 16:10, o monitor senza il 720p — il piu'
//     PICCOLO tra quelli SOPRA al tetto, sempre con l'aspetto del pannello: e'
//     comunque una frazione dei pixel del nativo (3440x1440 -> 2560x1080);
//  3. se neppure cosi' c'e' un modo, il piu' grande sotto il tetto fra tutti
//     quelli che il monitor elenca (qualunque aspetto);
//  4. solo se il pannello non espone nessun modo piu' piccolo del proprio, si
//     resta sul nativo.
// nullptr = il nativo (ci pensa Qt).
static const KmsMode *cappedMode(const KmsOutput &o, int capH) {
    if (capH == 0) return nullptr;
    const KmsMode *pre = preferredOf(o);
    if (!pre) return nullptr;
    double aspect = (double)pre->w / pre->h;
    const KmsMode *best = nullptr, *above = nullptr;
    for (const KmsMode &mi : o.modes) {
        if (mi.w < 1024 || mi.h < 600) continue;
        if (mi.w >= pre->w && mi.h >= pre->h) continue;
        double a = (double)mi.w / mi.h;
        if (a > aspect * 1.01 || a < aspect * 0.99) continue;
        if (mi.h <= capH) {
            if (!best || mi.h > best->h || (mi.h == best->h && mi.hz > best->hz)) best = &mi;
        } else {
            if (!above || mi.h < above->h || (mi.h == above->h && mi.hz > above->hz)) above = &mi;
        }
    }
    if (!best) best = above;
    // A panel with no smaller mode of its own aspect (the LG 34GK950F only has
    // 3440x1440 at 21:9): any mode the monitor itself lists will do — the biggest
    // under the cap — so the setting always changes something
    if (!best) {
        for (const KmsMode &mi : o.modes) {
            if (mi.w < 1024 || mi.h < 600 || mi.h > capH) continue;
            if (mi.w >= pre->w && mi.h >= pre->h) continue;
            if (!best || mi.h > best->h || (mi.h == best->h && mi.hz > best->hz)) best = &mi;
        }
    }
    if (best && best->w == pre->w && best->h == pre->h) return nullptr;
    return best;
}

// Il modo di quella dimensione da usare su un'uscita: il suo preferito se e'
// quello, altrimenti il piu' vicino a 60 Hz (sotto prima che sopra).
static const KmsMode *modeOfSize(const KmsOutput &o, int w, int h) {
    const KmsMode *pick = nullptr;
    int bestScore = 1 << 30;
    for (const KmsMode &m : o.modes) {
        if (m.w != w || m.h != h) continue;
        if (m.preferred) return &m;
        int score = m.hz == 60 ? 0 : m.hz < 60 ? 60 - m.hz : 1000 + m.hz;
        if (score < bestScore) { bestScore = score; pick = &m; }
    }
    return pick;
}

// La dimensione che TUTTI i monitor sanno fare, scelta col tetto della
// risoluzione: col nativo quella del primo monitor se gli altri la hanno,
// altrimenti la piu' grande in comune; col tetto la piu' grande che ci sta
// sotto, o la piu' piccola sopra. Niente vincolo di aspetto: e' ogni monitor a
// riempire il suo schermo. {0,0} = nessuna in comune.
static QPair<int, int> commonSize(const QList<KmsOutput> &outs, int capH) {
    QList<QPair<int, int>> common;
    for (const KmsMode &m : outs.first().modes) {
        if (m.w < 1024 || m.h < 600) continue;
        QPair<int, int> s(m.w, m.h);
        if (common.contains(s)) continue;
        bool all = true;
        for (int i = 1; i < outs.size() && all; i++) all = modeOfSize(outs[i], m.w, m.h) != nullptr;
        if (all) common.append(s);
    }
    if (common.isEmpty()) return {0, 0};
    auto area = [](const QPair<int, int> &s) { return (qint64)s.first * s.second; };
    if (capH == 0) {
        const KmsMode *pre = preferredOf(outs.first());
        if (pre && common.contains(QPair<int, int>(pre->w, pre->h))) return {pre->w, pre->h};
        QPair<int, int> big = common.first();
        for (const auto &s : common) if (area(s) > area(big)) big = s;
        return big;
    }
    QPair<int, int> under(0, 0), over(0, 0);
    for (const auto &s : common) {
        if (s.second <= capH) {
            if (under.second == 0 || s.second > under.second || (s.second == under.second && area(s) > area(under))) under = s;
        } else {
            if (over.second == 0 || s.second < over.second || (s.second == over.second && area(s) < area(over))) over = s;
        }
    }
    return under.second ? under : over;
}

QJsonObject kmsPlan(const QList<KmsOutput> &outputs, const QString &resolutionPref,
                    const QString &screensPref, const QString &card) {
    const int capH = resolutionPref == "native" ? 0 : resolutionPref == "1080" ? 1080 : 720;
    QList<KmsOutput> outs;
    for (const KmsOutput &o : outputs) if (!o.modes.isEmpty()) outs.append(o);
    if (outs.isEmpty()) return {};

    QJsonObject root;
    root["device"] = card;
    QJsonArray list;
    auto one = [&](const KmsOutput &o, bool primary) {
        QJsonObject e;
        e["name"] = o.name;
        const KmsMode *m = cappedMode(o, capH);
        e["mode"] = m ? modeString(*m) : QString("preferred");
        if (primary) e["primary"] = true;
        return e;
    };

    // Un monitor solo: com'era, e niente configurazione se resta il nativo.
    if (outs.size() == 1) {
        const KmsMode *m = cappedMode(outs.first(), capH);
        if (!m) return {};
        QJsonObject e;
        e["name"] = outs.first().name;
        e["mode"] = modeString(*m);
        list.append(e);
        root["outputs"] = list;
        return root;
    }

    // "Solo su" un monitor: quello acceso, gli altri spenti. Un nome che non
    // e' collegato (il monitor scelto e' stato staccato) torna a duplicare.
    if (screensPref.startsWith("only:")) {
        const QString want = screensPref.mid(5);
        int idx = -1;
        for (int i = 0; i < outs.size(); i++) if (outs[i].name == want) idx = i;
        if (idx >= 0) {
            for (int i = 0; i < outs.size(); i++) {
                if (i == idx) { list.append(one(outs[i], true)); continue; }
                QJsonObject off;
                off["name"] = outs[i].name;
                off["mode"] = "off";
                list.append(off);
            }
            root["outputs"] = list;
            return root;
        }
        qWarning("kms: %s non e' collegato, duplico su tutti", qPrintable(want));
    }

    // Duplica: il primo monitor e' la sorgente, gli altri la clonano, tutti
    // sulla stessa dimensione.
    const QPair<int, int> size = commonSize(outs, capH);
    if (size.first == 0) {
        // Nessuna risoluzione in comune: clonare non si puo' (lo stesso
        // framebuffer su modi diversi). L'interfaccia resta sul primo.
        qWarning("kms: nessuna risoluzione in comune fra i monitor, interfaccia solo su %s", qPrintable(outs.first().name));
        list.append(one(outs.first(), true));
        for (int i = 1; i < outs.size(); i++) {
            QJsonObject off;
            off["name"] = outs[i].name;
            off["mode"] = "off";
            list.append(off);
        }
        root["outputs"] = list;
        return root;
    }
    for (int i = 0; i < outs.size(); i++) {
        QJsonObject e;
        e["name"] = outs[i].name;
        e["mode"] = modeString(*modeOfSize(outs[i], size.first, size.second));
        if (i == 0) e["primary"] = true;
        else e["clones"] = outs.first().name;
        list.append(e);
    }
    root["outputs"] = list;
    // Il cursore hardware sta su un piano del CRTC della sorgente: sui cloni
    // non si vedrebbe. Disegnato nell'immagine, compare su tutti.
    root["hwcursor"] = false;
    return root;
}

QString kmsConfigFor(const QString &pref, const QString &screens, const QString &card) {
    int fd = open(card.toLocal8Bit().constData(), O_RDWR | O_CLOEXEC);
    if (fd < 0) return QString();
    drmModeRes *res = drmModeGetResources(fd);
    if (!res) { close(fd); return QString(); }
    QList<KmsOutput> outs;
    for (int i = 0; i < res->count_connectors; i++) {
        drmModeConnector *c = drmModeGetConnector(fd, res->connectors[i]);
        if (!c) continue;
        if (c->connection == DRM_MODE_CONNECTED && c->count_modes > 0) {
            KmsOutput o;
            o.name = kmsOutputName(c->connector_type, c->connector_type_id);
            for (int m = 0; m < c->count_modes; m++) {
                const drmModeModeInfo &mi = c->modes[m];
                if (mi.flags & DRM_MODE_FLAG_INTERLACE) continue;
                KmsMode km;
                km.w = mi.hdisplay; km.h = mi.vdisplay; km.hz = mi.vrefresh;
                km.preferred = mi.type & DRM_MODE_TYPE_PREFERRED;
                o.modes.append(km);
            }
            outs.append(o);
        }
        drmModeFreeConnector(c);
    }
    drmModeFreeResources(res);
    close(fd);

    const QJsonObject plan = kmsPlan(outs, pref, screens, card);
    if (plan.isEmpty()) return QString();
    QFile f("/tmp/hifi-qt-kms.json");
    if (!f.open(QIODevice::WriteOnly | QIODevice::Truncate)) return QString();
    const QByteArray json = QJsonDocument(plan).toJson(QJsonDocument::Compact);
    f.write(json);
    qInfo("kms: %s", json.constData());
    return f.fileName();
}
