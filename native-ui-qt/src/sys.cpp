#include "sys.h"
#include <QCoreApplication>
#include <QCursor>
#include <QDir>
#include <QStandardPaths>
#include <QUrl>
#include <QElapsedTimer>
#include <QFile>
#include <QGuiApplication>
#include <QImage>
#include <QPainter>
#include <QCryptographicHash>
#include <cmath>
#include <algorithm>
#include <vector>
#include <QQuickWindow>
#include <QTextStream>
#include <QtDebug>
#include <fcntl.h>
#include <linux/input.h>
#include <sys/ioctl.h>
#include <unistd.h>

static QElapsedTimer g_clock;

Sys::Sys(const QString &assets, QObject *parent) : QObject(parent), m_assets(assets) {
    g_clock.start();
    // 🚨 una variabile IMPOSTATA MA VUOTA non deve azzerare il percorso: senza
    // questo la UI leggeva "/ui-language" e ripiegava sull'inglese su un
    // apparecchio impostato in italiano
    m_configDir = qEnvironmentVariable("HIFI_CONFIG_DIR");
    if (m_configDir.isEmpty()) m_configDir = "/etc/hifi-player";
    m_dev = qEnvironmentVariableIsSet("HIFI_DEV");
    m_pointer = conf("pointer-enabled", "1").trimmed() != "0";
    rescanInput();
    if (QDir("/dev/input").exists()) {
        m_watch.addPath("/dev/input");
        connect(&m_watch, &QFileSystemWatcher::directoryChanged, this, [this]() { m_rescan.start(); });
    }
    m_rescan.setSingleShot(true);
    m_rescan.setInterval(500);
    connect(&m_rescan, &QTimer::timeout, this, &Sys::rescanInput);
}

static bool testBit(const unsigned long *arr, int bit) {
    return (arr[bit / (8 * sizeof(long))] >> (bit % (8 * sizeof(long)))) & 1;
}

// Stessa discriminante di input.c / main/inputDevices.js: una tastiera ha le
// lettere vere, non solo tasti speciali (i controller touch compositi e la
// PS/2 fantasma non contano).
void Sys::rescanInput() {
    bool kb = false, touch = false;
    QDir d("/dev/input");
    for (const QString &name : d.entryList({"event*"}, QDir::System | QDir::Files | QDir::NoDotAndDotDot)) {
        int fd = open(QString("/dev/input/" + name).toLocal8Bit().constData(), O_RDONLY | O_NONBLOCK | O_CLOEXEC);
        if (fd < 0) continue;
        unsigned long evbits[(EV_MAX + 8 * sizeof(long)) / (8 * sizeof(long))] = {0};
        unsigned long keybits[(KEY_MAX + 8 * sizeof(long)) / (8 * sizeof(long))] = {0};
        unsigned long absbits[(ABS_MAX + 8 * sizeof(long)) / (8 * sizeof(long))] = {0};
        unsigned long relbits[(REL_MAX + 8 * sizeof(long)) / (8 * sizeof(long))] = {0};
        ioctl(fd, EVIOCGBIT(0, sizeof evbits), evbits);
        ioctl(fd, EVIOCGBIT(EV_KEY, sizeof keybits), keybits);
        ioctl(fd, EVIOCGBIT(EV_ABS, sizeof absbits), absbits);
        ioctl(fd, EVIOCGBIT(EV_REL, sizeof relbits), relbits);
        close(fd);
        bool hasAbs = testBit(evbits, EV_ABS) && (testBit(absbits, ABS_MT_POSITION_X) || testBit(absbits, ABS_X));
        bool isTouch = hasAbs && testBit(keybits, BTN_TOUCH);
        bool isMouse = testBit(evbits, EV_REL) && testBit(relbits, REL_X) && testBit(relbits, REL_Y) && testBit(keybits, BTN_LEFT);
        bool isKey = testBit(evbits, EV_KEY) && testBit(keybits, KEY_A) && testBit(keybits, KEY_Z) && testBit(keybits, KEY_SPACE) && !isMouse;
        if (isKey) kb = true;
        if (isTouch) touch = true;
    }
    if (qEnvironmentVariableIsSet("HIFI_NO_KEYBOARD")) kb = false;
    if (kb != m_hasKeyboard || touch != m_hasTouch) { m_hasKeyboard = kb; m_hasTouch = touch; emit hasKeyboardChanged(); }
}

void Sys::setPointerEnabled(bool on) {
    if (m_pointer == on) return;
    m_pointer = on;
    emit pointerEnabledChanged();
    while (QGuiApplication::overrideCursor()) QGuiApplication::restoreOverrideCursor();
    if (!on) QGuiApplication::setOverrideCursor(QCursor(Qt::BlankCursor));
}

QString Sys::readLine(const QString &path, const QString &fallback) const {
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly | QIODevice::Text)) return fallback;
    QString l = QString::fromUtf8(f.readLine()).trimmed();
    return l.isEmpty() ? fallback : l;
}
QString Sys::readFile(const QString &path) const {
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly)) return QString();
    return QString::fromUtf8(f.readAll());
}
bool Sys::writeLine(const QString &path, const QString &text) const {
    QFile f(path);
    if (!f.open(QIODevice::WriteOnly | QIODevice::Truncate | QIODevice::Text)) { qWarning("sys: non scrivibile %s", qPrintable(path)); return false; }
    f.write((text + "\n").toUtf8());
    return true;
}
bool Sys::exists(const QString &path) const { return QFile::exists(path); }
QString Sys::conf(const QString &name, const QString &fallback) const { return readLine(m_configDir + "/" + name, fallback); }
bool Sys::setConf(const QString &name, const QString &value) const { return writeLine(m_configDir + "/" + name, value); }

bool Sys::shot(const QString &path) const {
    if (!m_win) return false;
    QImage img = m_win->grabWindow();
    if (img.isNull()) return false;
    bool ok = img.save(path.isEmpty() ? "/tmp/hifi-qt.png" : path);
    if (ok) qInfo("sys: fotografia in %s", qPrintable(path.isEmpty() ? "/tmp/hifi-qt.png" : path));
    return ok;
}
void Sys::quit() const { QCoreApplication::quit(); }
qint64 Sys::now() const { return g_clock.elapsed(); }
void Sys::log(const QString &s) const { qInfo("qml: %s", qPrintable(s)); }

// Ogni tocco, movimento o tasto conta come attivita' (salvaschermo,
// auto-apertura del player). Chiamata dal filtro degli eventi in main.cpp.
void Sys::noteInput() {
    qint64 n = g_clock.elapsed();
    if (n - m_lastInput < 200) { m_lastInput = n; return; }   // non inondare i binding
    m_lastInput = n;
    emit lastInputChanged();
}

// ─── icone tinte ────────────────────────────────────────────────────────────
// Le icone sono SVG lucide con stroke/fill "#ffffff" (gen-icons.mjs). Qui si
// sostituisce il bianco col colore voluto e, se il colore ha trasparenza, la
// si mette come stroke-opacity/fill-opacity sulla radice: e' PER FORMA, come fa
// Chromium con currentColor + colore CSS con alpha (i tratti che si
// sovrappongono si sommano, identico a Electron). Il file finisce in una
// cartella temporanea e si genera una volta sola per coppia (icona, colore):
// le coppie sono poche decine, nessun colore e' animato.
QString Sys::tintedIcon(const QString &name, const QColor &color) {
    if (name.isEmpty() || m_iconDir.isEmpty()) return QString();
    const QString key = name + '|' + color.name(QColor::HexArgb);
    auto it = m_tinted.constFind(key);
    if (it != m_tinted.constEnd()) return *it;
    if (m_iconCacheDir.isEmpty()) {
        m_iconCacheDir = QStandardPaths::writableLocation(QStandardPaths::TempLocation)
                         + "/hifi-qt-icons-" + QString::number(getuid());
        QDir().mkpath(m_iconCacheDir);
    }
    const QString path = m_iconCacheDir + '/' + name + '-' + color.name(QColor::HexArgb).mid(1) + ".svg";
    if (!QFile::exists(path)) {
        QFile in(m_iconDir + '/' + name + ".svg");
        if (!in.open(QIODevice::ReadOnly)) { qWarning("icona mancante: %s", qPrintable(in.fileName())); m_tinted.insert(key, QString()); return QString(); }
        QByteArray svg = in.readAll();
        svg.replace("#ffffff", color.name(QColor::HexRgb).toLatin1());
        if (color.alphaF() < 0.999) {
            // sulla radice <svg ...>: gli attributi si ereditano dalle forme
            int gt = svg.indexOf('>');
            int svgTag = svg.indexOf("<svg");
            if (svgTag >= 0) gt = svg.indexOf('>', svgTag);
            if (gt > 0) {
                const QByteArray a = QByteArray::number(color.alphaF(), 'f', 3);
                svg.insert(gt, " stroke-opacity=\"" + a + "\" fill-opacity=\"" + a + "\"");
            }
        }
        QFile out(path + ".tmp");
        if (!out.open(QIODevice::WriteOnly | QIODevice::Truncate)) { m_tinted.insert(key, QString()); return QString(); }
        out.write(svg); out.close();
        QFile::remove(path);
        QFile::rename(path + ".tmp", path);
    }
    const QString url = QUrl::fromLocalFile(path).toString();
    m_tinted.insert(key, url);
    return url;
}

// ─── box-shadow ──────────────────────────────────────────────────────────────
// Un box-shadow CSS e' la sagoma (allargata di `spread`) sfocata con una
// gaussiana di sigma blur/2. Qui la si calcola UNA volta per (raggio, blur,
// spread, colore) in un'immagine 9-patch: angoli interi, centro di 3 px che
// BorderImage stira a qualsiasi misura. Costa zero a ogni fotogramma — la
// sfocatura di MultiEffect avrebbe una passata per scheda per fotogramma.
// La gaussiana e' approssimata con tre box blur (Kutskir), che e' come fanno
// anche i browser.
static void boxBlur1D(std::vector<float> &src, std::vector<float> &dst, int w, int h, int r, bool horizontal) {
    const float iarr = 1.0f / (r + r + 1);
    if (horizontal) {
        for (int y = 0; y < h; y++) {
            const float *row = &src[y * w]; float *out = &dst[y * w];
            float acc = 0;
            for (int x = -r; x <= r; x++) acc += row[std::clamp(x, 0, w - 1)];
            for (int x = 0; x < w; x++) {
                out[x] = acc * iarr;
                acc += row[std::clamp(x + r + 1, 0, w - 1)] - row[std::clamp(x - r, 0, w - 1)];
            }
        }
    } else {
        for (int x = 0; x < w; x++) {
            float acc = 0;
            for (int y = -r; y <= r; y++) acc += src[std::clamp(y, 0, h - 1) * w + x];
            for (int y = 0; y < h; y++) {
                dst[y * w + x] = acc * iarr;
                acc += src[std::clamp(y + r + 1, 0, h - 1) * w + x] - src[std::clamp(y - r, 0, h - 1) * w + x];
            }
        }
    }
}

QString Sys::boxShadow(qreal radius, qreal blur, qreal spread, const QColor &color) {
    const QString key = QString("bs|%1|%2|%3|%4").arg(radius).arg(blur).arg(spread).arg(color.name(QColor::HexArgb));
    auto it = m_tinted.constFind(key);
    if (it != m_tinted.constEnd()) return *it;
    if (m_iconCacheDir.isEmpty()) {
        m_iconCacheDir = QStandardPaths::writableLocation(QStandardPaths::TempLocation)
                         + "/hifi-qt-icons-" + QString::number(getuid());
        QDir().mkpath(m_iconCacheDir);
    }
    const QString path = m_iconCacheDir + "/shadow-" + QString::fromLatin1(QCryptographicHash::hash(key.toUtf8(), QCryptographicHash::Md5).toHex().left(12)) + ".png";
    if (!QFile::exists(path)) {
        const double sigma = blur / 2.0;
        const int margin = int(std::ceil(blur * 1.5)) + 1;          // coda della gaussiana
        const double r = std::max(0.0, radius + spread);
        const int core = 2 * int(std::ceil(r)) + 3;                 // angoli + 3 px stirabili
        const int size = core + 2 * margin;
        QImage shape(size, size, QImage::Format_ARGB32_Premultiplied);
        shape.fill(Qt::transparent);
        {
            QPainter p(&shape);
            p.setRenderHint(QPainter::Antialiasing);
            p.setPen(Qt::NoPen); p.setBrush(Qt::white);
            p.drawRoundedRect(QRectF(margin, margin, core, core), r, r);
        }
        std::vector<float> a(size * size), b(size * size);
        for (int y = 0; y < size; y++) for (int x = 0; x < size; x++) a[y * size + x] = qAlpha(shape.pixel(x, y)) / 255.0f;
        if (sigma > 0.01) {
            // tre box blur che approssimano la gaussiana (Kutskir)
            const int n = 3;
            double wIdeal = std::sqrt(12.0 * sigma * sigma / n + 1.0);
            int wl = int(std::floor(wIdeal)); if (wl % 2 == 0) wl--;
            int wu = wl + 2;
            double mIdeal = (12.0 * sigma * sigma - n * wl * wl - 4.0 * n * wl - 3.0 * n) / (-4.0 * wl - 4.0);
            int m = int(std::round(mIdeal));
            for (int i = 0; i < n; i++) {
                int rr = ((i < m ? wl : wu) - 1) / 2;
                boxBlur1D(a, b, size, size, rr, true);
                boxBlur1D(b, a, size, size, rr, false);
            }
        }
        QImage out(size, size, QImage::Format_ARGB32_Premultiplied);
        const double ca = color.alphaF();
        for (int y = 0; y < size; y++) {
            QRgb *line = reinterpret_cast<QRgb *>(out.scanLine(y));
            for (int x = 0; x < size; x++) {
                double al = std::clamp(double(a[y * size + x]) * ca, 0.0, 1.0);
                line[x] = qPremultiply(qRgba(color.red(), color.green(), color.blue(), int(std::lround(al * 255))));
            }
        }
        out.save(path + ".tmp.png", "PNG");
        QFile::remove(path);
        QFile::rename(path + ".tmp.png", path);
    }
    const QString url = QUrl::fromLocalFile(path).toString();
    m_tinted.insert(key, url);
    return url;
}
